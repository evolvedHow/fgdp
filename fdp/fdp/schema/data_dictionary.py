"""
FDP Data Dictionary — auto-generate LLM context from the live Supabase schema.

Reads table and column descriptions directly from PostgreSQL COMMENT strings
(the same comments set in 002_cdm.sql) and produces a structured text block
suitable for use as an LLM system-prompt data dictionary.

This module is the canonical source of truth for what an LLM "knows" about
the FDP schema.  All apps that need NLQ→SQL (fdworkbench, future analytics
tools) should import from here rather than maintaining their own hardcoded
data dictionaries.

Usage
-----
    from fdp.schema.data_dictionary import get_data_dictionary

    # Returns a multi-line string ready to embed in an LLM system prompt
    dd = get_data_dictionary(db_url=os.environ["DATABASE_URL"])

Caching
-------
The data dictionary is cached in memory (per process) after the first call.
Call ``clear_cache()`` if you need to refresh after a schema change.
"""

from __future__ import annotations

import os

import psycopg
import psycopg.rows

# Module-level cache — populated on first call, survives for process lifetime.
_CACHE: str | None = None


def clear_cache() -> None:
    """Invalidate the in-memory data dictionary cache."""
    global _CACHE
    _CACHE = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_data_dictionary(
    db_url: str | None = None,
    schema: str = "fdp",
    include_views: bool = True,
    include_row_counts: bool = True,
    use_cache: bool = True,
) -> str:
    """
    Auto-generate a structured data dictionary from the live PostgreSQL schema.

    Reads table/column names, data types, and COMMENT strings from the
    database.  Falls back to empty strings where no COMMENT is set.

    Parameters
    ----------
    db_url:             PostgreSQL connection string (defaults to DATABASE_URL).
    schema:             Schema to introspect (default: fdp).
    include_views:      Include analytical views in the output (default: True).
    include_row_counts: Append current row count per table (default: True).
    use_cache:          Return cached result if available (default: True).

    Returns
    -------
    str — formatted data dictionary ready to embed in an LLM system prompt.
    """
    global _CACHE
    if use_cache and _CACHE is not None:
        return _CACHE

    url = db_url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "No PostgreSQL connection string.  Set DATABASE_URL or pass db_url=."
        )

    result = _build(url, schema=schema, include_views=include_views,
                    include_row_counts=include_row_counts)
    if use_cache:
        _CACHE = result
    return result


# ---------------------------------------------------------------------------
# Internal build
# ---------------------------------------------------------------------------

def _build(
    db_url: str,
    schema: str,
    include_views: bool,
    include_row_counts: bool,
) -> str:
    with psycopg.connect(db_url, row_factory=psycopg.rows.dict_row) as conn:
        tables = _fetch_tables(conn, schema, include_views)
        lines: list[str] = [
            f"# FDP Database Schema  (schema: {schema})",
            "",
            "All queries must use the fdp. prefix (e.g. SELECT * FROM fdp.election_results).",
            "Use PostgreSQL syntax — NOT DuckDB or SQLite syntax.",
            "",
        ]

        for tbl in tables:
            tname = tbl["table_name"]
            ttype = tbl["table_type"]
            tcomment = tbl["table_comment"] or ""

            row_count_str = ""
            if include_row_counts and ttype == "BASE TABLE":
                n = _fetch_row_count(conn, schema, tname)
                row_count_str = f"  [{n:,} rows]"

            kind = "VIEW" if ttype == "VIEW" else "TABLE"
            lines.append(f"## {kind}: {schema}.{tname}{row_count_str}")
            if tcomment:
                # First sentence only — keep the prompt concise
                first_sentence = tcomment.split(".")[0].strip() + "."
                lines.append(first_sentence)
            lines.append("")

            cols = _fetch_columns(conn, schema, tname)
            lines.append("| Column | Type | Description |")
            lines.append("|--------|------|-------------|")
            for col in cols:
                cname = col["column_name"]
                ctype = col["data_type"]
                cdesc = (col["column_comment"] or "").split("\n")[0].strip()
                lines.append(f"| `{cname}` | {ctype} | {cdesc} |")
            lines.append("")

        # Append query patterns and domain glossary
        lines.extend(_domain_notes())

    return "\n".join(lines)


def _fetch_tables(
    conn: psycopg.Connection,
    schema: str,
    include_views: bool,
) -> list[dict]:
    type_filter = "IN ('BASE TABLE', 'VIEW')" if include_views else "= 'BASE TABLE'"
    sql = f"""
        SELECT
            t.table_name,
            t.table_type,
            obj_description(
                (quote_ident(t.table_schema) || '.' || quote_ident(t.table_name))::regclass,
                'pg_class'
            ) AS table_comment
        FROM information_schema.tables t
        WHERE t.table_schema = %s
          AND t.table_type {type_filter}
        ORDER BY
            CASE t.table_type WHEN 'BASE TABLE' THEN 0 ELSE 1 END,
            t.table_name
    """
    with conn.cursor() as cur:
        cur.execute(sql, [schema])
        return cur.fetchall()


def _fetch_columns(conn: psycopg.Connection, schema: str, table: str) -> list[dict]:
    sql = """
        SELECT
            c.column_name,
            c.data_type,
            col_description(
                (quote_ident(c.table_schema) || '.' || quote_ident(c.table_name))::regclass,
                c.ordinal_position
            ) AS column_comment
        FROM information_schema.columns c
        WHERE c.table_schema = %s AND c.table_name = %s
          AND c.column_name NOT IN ('created_at', 'updated_at', 'update_count', 'loaded_by')
        ORDER BY c.ordinal_position
    """
    with conn.cursor() as cur:
        cur.execute(sql, [schema, table])
        return cur.fetchall()


def _fetch_row_count(conn: psycopg.Connection, schema: str, table: str) -> int:
    try:
        with conn.cursor() as cur:
            cur.execute(f'SELECT COUNT(*) AS n FROM {schema}."{table}"')
            return cur.fetchone()["n"]
    except Exception:  # noqa: BLE001
        return -1


def _domain_notes() -> list[str]:
    """Redistricting domain glossary and query pattern hints."""
    return [
        "---",
        "",
        "## Domain Glossary",
        "",
        "- **VTD** (Voting Tabulation District): The smallest Census geography used for "
        "redistricting analysis — Georgia has 2,698 VTDs.  Each VTD row has an 11-char geoid.",
        "- **geoid**: For VTDs, an 11-char Census FIPS code.  First 2 chars = state (13=GA), "
        "next 3 chars = county FIPS, remaining = VTD code.  "
        "LEFT(geoid, 5) gives the county FIPS.",
        "- **CVAP** (Citizen Voting Age Population): The number of U.S. citizens 18+ in a "
        "geographic unit.  More meaningful than raw VAP for Voting Rights Act analysis.",
        "- **dem_2pv**: Democratic two-party vote share = dem_votes / (dem_votes + rep_votes). "
        "A value above 0.5 means Democrats won that unit on two-party basis.",
        "- **election_type**: 'general' | 'runoff' | 'special'. "
        "The 2022 Warnock/Walker runoff is election_type='runoff', year=2022.",
        "- **office**: Canonical lowercase names — 'president', 'governor', 'senate', "
        "'attorney-general', 'secretary-of-state', 'lt-governor'.",
        "- **geo_level**: The geography granularity — 'vtd', 'block', 'county', 'state'.",
        "",
        "## Common Query Patterns",
        "",
        "-- County-level aggregation (LEFT(geoid, 5) = county FIPS):",
        "SELECT LEFT(geoid, 5) AS county_fips, SUM(votes) AS total_votes",
        "FROM fdp.election_results WHERE year = 2024 AND office = 'president'",
        "GROUP BY LEFT(geoid, 5) ORDER BY total_votes DESC;",
        "",
        "-- Two-party vote share per county:",
        "SELECT county_fips, dem_votes, rep_votes,",
        "       ROUND(100.0 * dem_votes / NULLIF(dem_votes + rep_votes, 0), 1) AS dem_2pv",
        "FROM fdp.v_county_results WHERE year = 2024 AND office = 'president';",
        "",
        "-- Majority-minority VTDs (>50% Black CVAP):",
        "SELECT c.geoid, c.cvap_tot, c.cvap_blk,",
        "       ROUND(100.0 * c.cvap_blk / NULLIF(c.cvap_tot, 0), 1) AS pct_blk",
        "FROM fdp.cvap c WHERE c.geo_level = 'vtd' AND c.year = 2024",
        "  AND c.cvap_blk::numeric / NULLIF(c.cvap_tot, 0) > 0.5",
        "ORDER BY pct_blk DESC;",
        "",
        "-- Statewide validation (compare to SoS certified totals):",
        "SELECT office, party, SUM(votes) AS total_votes",
        "FROM fdp.election_results WHERE year = 2024 AND geo_level = 'vtd'",
        "GROUP BY office, party ORDER BY office, total_votes DESC;",
        "",
    ]
