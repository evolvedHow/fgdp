#!/usr/bin/env python3
"""
Migrate the Fair Districts Data Platform (FDP) DuckDB CDM files into the
Postgres server defined in docker/postgres/docker-compose.yml.

What it does
------------
1. Creates the schemas ``cdm``, ``manifest``, ``semantic``, ``dashboard`` and
   ``analytics``.
2. Copies every base table from:

   * data/cdm.duckdb      -> cdm.*
   * data/manifest.duckdb -> manifest.*
   * data/semantic.duckdb -> semantic.*
3. Re-creates the semantic-layer views in Postgres.
4. Builds dashboard-oriented materialized views / views in dashboard.*.
5. Applies the canonical FDP DDL (fdp.*) and ensemble scoring DDL.
6. Builds the analytics specification layer in analytics.* and seeds county
   reference / 2010-2020 census data.

Run it
------
    cd ~/codebox/fgdp/fdp
    uv run python scripts/cdm_to_postgres.py

Environment variables
---------------------
POSTGRES_DSN  Postgres connection string (default: the docker-compose Postgres).
FDP_ROOT      Path to the fdp repo root (default: parent of this script).
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

import duckdb
import psycopg


DEFAULT_DSN = "host=localhost port=5432 dbname=fdga user=homelab password=homelab"
POSTGRES_DSN = os.getenv("POSTGRES_DSN", DEFAULT_DSN)

SCRIPT_DIR = Path(__file__).resolve().parent
FDP_ROOT = Path(os.getenv("FDP_ROOT", SCRIPT_DIR.parent))
DATA_DIR = FDP_ROOT / "data"
SQL_DIR = FDP_ROOT / "sql" / "postgres"

SOURCES = {
    "cdm": DATA_DIR / "cdm.duckdb",
    "manifest": DATA_DIR / "manifest.duckdb",
    "semantic": DATA_DIR / "semantic.duckdb",
}

# Census Bureau 2010-2019 county estimates file; CENSUS2010POP column gives the
# 2010 Census county population used for 2010-2020 shift analysis.
CENSUS_POP_CSV_URL = (
    "https://www2.census.gov/programs-surveys/popest/datasets/"
    "2010-2019/counties/totals/co-est2019-alldata.csv"
)

METRO_ATLANTA_COUNTIES = {
    "Barrow", "Bartow", "Butts", "Carroll", "Cherokee", "Clayton", "Cobb",
    "Coweta", "Dawson", "DeKalb", "Douglas", "Fayette", "Forsyth", "Fulton",
    "Gwinnett", "Hall", "Haralson", "Heard", "Henry", "Jasper", "Lamar",
    "Meriwether", "Morgan", "Newton", "Paulding", "Pickens", "Pike",
    "Rockdale", "Spalding", "Walton",
}

METRO_SAVANNAH_COUNTIES = {"Bryan", "Chatham", "Effingham"}


def map_type(duck_type: str) -> str:
    """Map a DuckDB column type to the closest PostgreSQL type."""
    dt = duck_type.upper().strip()

    # Text-like
    if dt in ("VARCHAR", "TEXT", "STRING", "BLOB", "BYTEA"):
        return "TEXT"

    # Integers
    if dt in ("TINYINT", "SMALLINT"):
        return "SMALLINT"
    if dt == "INTEGER":
        return "INTEGER"
    if dt == "BIGINT":
        return "BIGINT"

    # Floating point
    if dt in ("DOUBLE", "FLOAT", "REAL"):
        return "DOUBLE PRECISION"

    # Boolean
    if dt == "BOOLEAN":
        return "BOOLEAN"

    # Timestamps
    if dt == "TIMESTAMP WITH TIME ZONE":
        return "TIMESTAMPTZ"
    if dt in ("TIMESTAMP WITHOUT TIME ZONE", "TIMESTAMP"):
        return "TIMESTAMP"
    if dt == "DATE":
        return "DATE"
    if dt == "TIME":
        return "TIME"

    # JSON
    if dt == "JSON":
        return "JSONB"

    # Decimal / numeric
    m = re.match(r"(DECIMAL|NUMERIC)\s*\((\d+)\s*,\s*(\d+)\)", dt)
    if m:
        return f"NUMERIC({m.group(2)},{m.group(3)})"
    if dt.startswith("DECIMAL") or dt.startswith("NUMERIC"):
        return "NUMERIC"

    # Arrays fallback -> text array (rare in this dataset)
    if "[]" in dt:
        return "TEXT[]"

    # Unknown: store as text to avoid data loss
    return "TEXT"


def split_sql_statements(sql: str) -> list[str]:
    """Split a SQL script into individual statements.

    Respects single quotes, double quotes, $tag$dollar quoting$tag$, and
    both -- line comments and /* */ block comments so that semicolons inside
    comments or PL/pgSQL function bodies do not break the split.
    """
    statements: list[str] = []
    current: list[str] = []
    i = 0
    n = len(sql)
    in_single = False
    in_double = False
    dollar_tag: str | None = None
    in_line_comment = False
    in_block_comment = False

    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue

        if in_single:
            current.append(ch)
            if ch == "'" and nxt != "'":
                in_single = False
        elif in_double:
            current.append(ch)
            if ch == '"' and nxt != '"':
                in_double = False
        elif dollar_tag is not None:
            current.append(ch)
            if ch == "$":
                j = sql.find("$", i + 1)
                if j != -1:
                    tag = sql[i + 1 : j]
                    if tag == dollar_tag:
                        # append the rest of the closing delimiter ($tag$)
                        current.extend(sql[i + 1 : j + 1])
                        dollar_tag = None
                        i = j
        else:
            if ch == "'" and nxt != "'":
                in_single = True
                current.append(ch)
            elif ch == '"' and nxt != '"':
                in_double = True
                current.append(ch)
            elif ch == "$":
                j = sql.find("$", i + 1)
                if j != -1:
                    dollar_tag = sql[i + 1 : j]
                    current.extend(sql[i : j + 1])  # append opening $tag$
                    i = j
                else:
                    current.append(ch)
            elif ch == "-" and nxt == "-":
                in_line_comment = True
                i += 2
                continue
            elif ch == "/" and nxt == "*":
                in_block_comment = True
                i += 2
                continue
            elif ch == ";":
                stmt = "".join(current).strip()
                if stmt:
                    statements.append(stmt)
                current = []
                i += 1
                continue
            else:
                current.append(ch)
        i += 1

    stmt = "".join(current).strip()
    if stmt:
        statements.append(stmt)
    return statements


def execute_sql_file(cur: psycopg.Cursor, path: Path) -> None:
    """Read a SQL file and execute each statement individually."""
    if not path.exists():
        print(f"  warning: {path} not found; skipping")
        return

    sql = path.read_text(encoding="utf-8")
    for stmt in split_sql_statements(sql):
        if not stmt:
            continue
        cur.execute(stmt)
    print(f"  applied {path.name}")


def clean_value(value):
    """Replace DuckDB NaN/inf floats with None for safe Postgres insertion."""
    if isinstance(value, float):
        if value != value:  # NaN
            return None
    return value


def load_base_tables(pg_cur: psycopg.Cursor, schema: str, db_path: Path) -> None:
    """Copy every base table from a DuckDB file into a Postgres schema."""
    pg_cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    with duckdb.connect(str(db_path), read_only=True) as dcon:
        tables = [
            r[0]
            for r in dcon.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' AND table_type = 'BASE TABLE' "
                "ORDER BY table_name"
            ).fetchall()
        ]

        for table in tables:
            columns = dcon.execute(f'DESCRIBE "{table}"').fetchall()
            # Normalize column names to lowercase so unquoted SQL references work.
            columns = [(c[0].lower(), c[1]) for c in columns]
            col_defs = [f'"{c[0]}" {map_type(c[1])}' for c in columns]

            pg_cur.execute(f"DROP TABLE IF EXISTS {schema}.\"{table}\" CASCADE")
            pg_cur.execute(
                f"CREATE TABLE {schema}.\"{table}\" ({', '.join(col_defs)})"
            )

            rows = dcon.execute(f'SELECT * FROM "{table}"').fetchall()
            if rows:
                col_names = [f'"{c[0]}"' for c in columns]
                placeholders = ", ".join(["%s"] * len(columns))
                insert_sql = (
                    f"INSERT INTO {schema}.\"{table}\" ({', '.join(col_names)}) "
                    f"VALUES ({placeholders})"
                )
                cleaned = [
                    tuple(clean_value(v) for v in row) for row in rows
                ]
                pg_cur.executemany(insert_sql, cleaned)

            print(f"  loaded {schema}.{table}: {len(rows)} rows")


def _load_county_names() -> dict[str, str]:
    """Return {county_fips: county_name} from the reference county GeoJSON."""
    geo_path = (
        FDP_ROOT / "data" / "repos" / "main" / "boundaries" / "reference" / "county.geojson"
    )
    if not geo_path.exists():
        return {}
    with open(geo_path, encoding="utf-8") as f:
        geo = json.load(f)
    return {
        "13" + feat["properties"]["COUNTYFP20"]: feat["properties"]["COUNTY"]
        for feat in geo.get("features", [])
    }


def _load_pop_2010(cache_dir: Path) -> dict[str, int]:
    """Download and parse the 2010 county population CSV; return {fips: pop}."""
    csv_path = cache_dir / "co-est2019-alldata.csv"
    try:
        if not csv_path.exists():
            print(f"    downloading 2010 county population CSV...")
            urllib.request.urlretrieve(CENSUS_POP_CSV_URL, csv_path)
        pop2010: dict[str, int] = {}
        with open(csv_path, newline="", encoding="latin-1") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["STATE"] == "13" and row["COUNTY"] != "000":
                    pop2010[row["STATE"] + row["COUNTY"]] = int(row["CENSUS2010POP"])
        return pop2010
    except Exception as exc:
        print(f"    warning: could not fetch 2010 county population CSV: {exc}")
        return {}


def seed_analytics_reference(cur: psycopg.Cursor) -> None:
    """Populate analytics.county_reference and analytics.raw_county_census."""
    counties = _load_county_names()
    if not counties:
        print("  warning: county.geojson not found; skipping analytics reference seed")
        return

    cur.execute("TRUNCATE analytics.raw_county_census, analytics.county_reference CASCADE")

    ref_rows = [
        (fips, name, name in METRO_ATLANTA_COUNTIES, name in METRO_SAVANNAH_COUNTIES)
        for fips, name in counties.items()
    ]
    cur.executemany(
        "INSERT INTO analytics.county_reference VALUES (%s, %s, %s, %s)",
        ref_rows,
    )
    print(f"  seeded analytics.county_reference: {len(ref_rows)} rows")

    pop2010 = _load_pop_2010(Path("/tmp/opencode"))

    # 2020 Census county totals are rolled up from the 2020 VTD demographics.
    cur.execute(
        """
        SELECT LEFT(geoid, 5) AS county_fips,
               SUM(pop) AS pop_2020,
               SUM(pop_white) AS pop_white_2020,
               SUM(pop_black) AS pop_black_2020,
               SUM(pop_hisp) AS pop_hispanic_2020,
               SUM(pop_asian) AS pop_asian_2020,
               GREATEST(SUM(pop - pop_white - pop_black - pop_hisp - pop_asian - pop_aian), 0) AS pop_other_2020
        FROM semantic.raw_vtd_demographics
        GROUP BY LEFT(geoid, 5)
        """
    )
    rows2020 = {row[0]: row[1:] for row in cur.fetchall()}

    census_rows = []
    for fips, name in counties.items():
        is_atl = name in METRO_ATLANTA_COUNTIES
        is_sav = name in METRO_SAVANNAH_COUNTIES
        pop10 = pop2010.get(fips)
        pop20 = rows2020.get(fips)
        if pop20:
            census_rows.append(
                (fips, name, is_atl, is_sav, pop10, *pop20)
            )
        else:
            census_rows.append(
                (fips, name, is_atl, is_sav, pop10, None, None, None, None, None, None)
            )

    cur.executemany(
        """
        INSERT INTO analytics.raw_county_census
        (county_fips, county_name, is_metro_atlanta, is_metro_savannah,
         pop_2010, pop_2020, pop_white_2020, pop_black_2020,
         pop_hispanic_2020, pop_asian_2020, pop_other_2020)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        census_rows,
    )
    print(f"  seeded analytics.raw_county_census: {len(census_rows)} rows")


def main() -> int:
    print(f"FDP root: {FDP_ROOT}")
    print(f"Postgres: {POSTGRES_DSN.replace('homelab', '***')}")

    for name, path in SOURCES.items():
        if not path.exists():
            print(f"error: missing source database {path}", file=sys.stderr)
            return 1

    print("\nConnecting to Postgres...")
    with psycopg.connect(POSTGRES_DSN) as pg_conn:
        pg_conn.autocommit = True
        cur = pg_conn.cursor()

        # Ensure target schemas exist.
        for schema in ("cdm", "manifest", "semantic", "dashboard", "analytics"):
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

        print("\nLoading CDM tables from cdm.duckdb...")
        load_base_tables(cur, "cdm", SOURCES["cdm"])

        print("\nLoading manifest tables from manifest.duckdb...")
        load_base_tables(cur, "manifest", SOURCES["manifest"])

        print("\nLoading semantic raw tables from semantic.duckdb...")
        load_base_tables(cur, "semantic", SOURCES["semantic"])

        print("\nApplying table/column documentation...")
        execute_sql_file(cur, SQL_DIR / "000_comments.sql")

        print("\nBuilding semantic views...")
        execute_sql_file(cur, SQL_DIR / "001_semantic_views.sql")

        print("\nBuilding dashboard views...")
        execute_sql_file(cur, SQL_DIR / "002_dashboard_views.sql")

        print("\nApplying canonical FDP CDM DDL (fdp schema)...")
        cur.execute("CREATE SCHEMA IF NOT EXISTS fdp")
        execute_sql_file(cur, FDP_ROOT / "sql" / "002_cdm.sql")

        print("\nApplying ensemble scoring/run DDL (fdp schema)...")
        execute_sql_file(cur, FDP_ROOT / "sql" / "004_ensemble_scores.sql")
        execute_sql_file(cur, FDP_ROOT / "sql" / "005_ensemble_runs.sql")

        print("\nApplying analytics specification...")
        execute_sql_file(cur, SQL_DIR / "003_analytics_spec.sql")

        print("\nSeeding analytics reference tables...")
        seed_analytics_reference(cur)

        print("\nVerifying object counts...")
        cur.execute(
            """
            SELECT nspname, relkind, COUNT(*)
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname IN ('cdm','fdp','manifest','semantic','dashboard','analytics')
              AND c.relkind IN ('r','v','m')
            GROUP BY nspname, relkind
            ORDER BY nspname, relkind;
            """
        )
        for row in cur.fetchall():
            kind = {"r": "tables", "v": "views", "m": "matviews"}.get(
                row[1], row[1]
            )
            print(f"  {row[0]}: {row[2]} {kind}")

    print("\nDone. Connect with:")
    print("  psql 'host=localhost port=5432 dbname=fdga user=homelab password=homelab'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
