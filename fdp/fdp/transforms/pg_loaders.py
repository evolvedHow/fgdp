"""
FDP PostgreSQL CDM loaders — transforms wide parquet data into the
normalized CDM tables (fdp.geography, fdp.election_results, fdp.cvap).

These functions sit between the parquet layer (source of truth / R interchange)
and the PostgreSQL serving layer (multi-user queries, Looker Studio, Tableau).

Usage
-----
    import pandas as pd
    import psycopg
    from fdp.transforms.pg_loaders import (
        extract_geography_dim,
        melt_election_vtd,
        normalize_cvap_vtd,
        upsert_to_pg,
    )

    df = pd.read_parquet("ga-2022-general-election-vtd.parquet")

    geo_df      = extract_geography_dim(df, state="GA", vintage_year=2020)
    results_df  = melt_election_vtd(df, state="GA", source="RDH")

    with psycopg.connect(DATABASE_URL) as conn:
        upsert_to_pg(conn, geo_df,      "fdp", "geography",
                     ["geoid", "vintage_year"])
        upsert_to_pg(conn, results_df,  "fdp", "election_results",
                     ["geoid", "year", "election_type", "office", "party", "candidate"])

Backward compatibility
----------------------
``extract_vtd_dim`` is kept as a deprecated alias for ``extract_geography_dim``.
"""

from __future__ import annotations

import io
import os
import re
import warnings
from typing import Callable

import pandas as pd


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default vintage year — matches 2020 Census boundaries.
#: Override via the FDP_VINTAGE_YEAR env var or the --vintage CLI flag.
_DEFAULT_VINTAGE_YEAR = int(os.environ.get("FDP_VINTAGE_YEAR", 2020))

#: Maps RDH election-type prefix to canonical string
_ETYPE_MAP: dict[str, str] = {
    "G": "general",
    "R": "runoff",
    "S": "special",
}

#: Maps RDH party code to canonical string
_PARTY_MAP: dict[str, str] = {
    "D": "dem",
    "R": "rep",
    "L": "lib",
    "G": "grn",
    "I": "ind",
}

#: RDH column regex — captures (type_prefix, YY, office_code, party_code, candidate_code)
_COL_RE = re.compile(r"^([GRS])(\d{2})([A-Z0-9]{2,6})([DRLGI])([A-Z0-9]{2,4})$")

#: Maps CVAP column base name (without year suffix) to CDM column name
_CVAP_COL_MAP: dict[str, str] = {
    "CVAP_TOT": "cvap_tot",
    "CVAP_BLK": "cvap_blk",
    "CVAP_BLA": "cvap_blk",   # alternate RDH naming for Black alone or in combination
    "CVAP_HSP": "cvap_hsp",
    "CVAP_WHT": "cvap_wht",
    "CVAP_ASN": "cvap_asn",
    "CVAP_AMI": "cvap_ami",
    "CVAP_NHP": "cvap_nhp",
}

#: CVAP column pattern — e.g. CVAP_TOT24 or CVAP_BLK24
_CVAP_RE = re.compile(r"^(CVAP_[A-Z]+)(\d{2})$")


# ---------------------------------------------------------------------------
# extract_geography_dim
# ---------------------------------------------------------------------------

def extract_geography_dim(
    df: pd.DataFrame,
    state: str = "GA",
    geo_level: str = "vtd",
    geo_type: str = "census",
    vintage_year: int | None = None,
    loaded_by: str | None = None,
) -> pd.DataFrame:
    """
    Extract the geography dimension rows from a wide election or CVAP parquet.

    Returns a DataFrame with columns matching fdp.geography:
      geoid, geo_level, geo_type, state, county_fips, vintage_year, loaded_by

    ``county_fips`` is derived from the first 5 characters of the geoid — this
    works for all Census GEOIDs.  ``name`` is not populated here; it can be
    enriched later from a shapefile or a static county lookup.

    Parameters
    ----------
    df:           Wide parquet DataFrame with a GEOID20 column.
    state:        State abbreviation (default: GA).
    geo_level:    Geographic level of these rows (default: vtd).
    geo_type:     'census' or 'political' (default: census).
    vintage_year: Boundary year (default: FDP_VINTAGE_YEAR env var, else 2020).
    loaded_by:    Label for the loaded_by audit column (e.g. 'fdp load-pg').
    """
    vy = vintage_year if vintage_year is not None else _DEFAULT_VINTAGE_YEAR

    geo = pd.DataFrame({
        "geoid":        df["GEOID20"].astype(str),
        "geo_level":    geo_level,
        "geo_type":     geo_type,
        "state":        state.upper(),
        "county_fips":  df["GEOID20"].astype(str).str[:5],
        "vintage_year": vy,
    })

    if loaded_by:
        geo["loaded_by"] = loaded_by

    return geo.drop_duplicates(subset=["geoid", "vintage_year"])


def extract_vtd_dim(
    df: pd.DataFrame,
    state: str = "GA",
    vintage_year: int | None = None,
) -> pd.DataFrame:
    """
    Deprecated alias for ``extract_geography_dim`` with geo_level='vtd'.

    Use ``extract_geography_dim`` directly for new code.
    """
    warnings.warn(
        "extract_vtd_dim is deprecated; use extract_geography_dim instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return extract_geography_dim(
        df,
        state=state,
        geo_level="vtd",
        geo_type="census",
        vintage_year=vintage_year,
    )


# ---------------------------------------------------------------------------
# melt_election_vtd
# ---------------------------------------------------------------------------

def melt_election_vtd(
    df: pd.DataFrame,
    state: str = "GA",
    source: str = "RDH",
    geo_level: str = "vtd",
    collection_geo_level: str = "precinct",
    loaded_by: str | None = None,
    log_fn: Callable | None = None,
) -> pd.DataFrame:
    """
    Melt a wide election VTD parquet → long format for fdp.election_results.

    Each RDH column (e.g. ``G22GOVDABR``) becomes one row:
      geoid, geo_level, collection_geo_level, state, year, election_type,
      office, party, candidate, votes, source

    RDH column naming convention: {prefix}{YY}{OFFICE}{PARTY}{CANDIDATE}
      prefix: G=general, R=runoff, S=special
      YY:     2-digit year (22=2022, 24=2024)
      OFFICE: GOV, USS, PRE, ATG, SOS, LTG, PSC, INS, LAB, AGR, SUP, …
      PARTY:  D=dem, R=rep, L=lib, G=grn, I=ind
      CAND:   3-4 char surname code (ABR, KEM, WAR, WAL, TRU, HAR, …)

    Parameters
    ----------
    df:                   Wide election VTD parquet (output of ``fdp aggregate election``).
    state:                State abbreviation.
    source:               Data provenance label (RDH, VEST, derived, …).
    geo_level:            Geographic level of the rows (default: vtd).
    collection_geo_level: Level at which votes were originally counted by the
                          election board before disaggregation (default: precinct).
                          Set to None if unknown.
    loaded_by:            Label for the loaded_by audit column.
    log_fn:               Optional logging callback (receives a string).
    """
    from fdp.ingest.race_registry import _CODE_TO_NAME  # noqa: PLC0415

    chunks: list[pd.DataFrame] = []
    skipped_cols: list[str] = []

    for col in df.columns:
        if col in ("GEOID20", "VAP_MOD"):
            continue
        m = _COL_RE.match(col)
        if not m:
            skipped_cols.append(col)
            continue

        type_pfx, yy, office_code, party_code, cand_code = m.groups()

        chunk = pd.DataFrame({
            "geoid":                df["GEOID20"].astype(str),
            "geo_level":            geo_level,
            "collection_geo_level": collection_geo_level,
            "state":                state.upper(),
            "year":                 2000 + int(yy),
            "election_type":        _ETYPE_MAP.get(type_pfx, "general"),
            "office":               _CODE_TO_NAME.get(office_code, f"other_{office_code.lower()}"),
            "party":                _PARTY_MAP.get(party_code, "other"),
            "candidate":            cand_code.lower(),
            "votes":                pd.to_numeric(df[col], errors="coerce").fillna(0).astype("int64"),
            "source":               source,
        })
        if loaded_by:
            chunk["loaded_by"] = loaded_by

        chunks.append(chunk)

    if skipped_cols and log_fn:
        log_fn(f"    [dim]skipped {len(skipped_cols)} non-election cols[/]")

    if not chunks:
        return pd.DataFrame(
            columns=["geoid", "geo_level", "collection_geo_level", "state",
                     "year", "election_type", "office", "party", "candidate",
                     "votes", "source"]
        )

    result = pd.concat(chunks, ignore_index=True)

    if log_fn:
        races = result[["year", "election_type", "office"]].drop_duplicates()
        log_fn(f"    {len(result):,} rows  ({len(races)} race×year combinations)")

    return result


# ---------------------------------------------------------------------------
# normalize_cvap_vtd
# ---------------------------------------------------------------------------

def normalize_cvap_vtd(
    df: pd.DataFrame,
    year: int,
    state: str = "GA",
    source: str = "RDH",
    geo_level: str = "vtd",
    loaded_by: str | None = None,
) -> pd.DataFrame:
    """
    Normalize a wide CVAP VTD parquet → fdp.cvap row format.

    RDH CVAP columns carry a 2-digit year suffix (e.g. ``CVAP_TOT24``).
    This function strips the suffix, maps to CDM column names, and returns
    one row per VTD.

    Parameters
    ----------
    df:         Wide CVAP VTD parquet (output of ``fdp aggregate cvap``).
    year:       ACS 5-year end year (e.g. 2024 for 2020–2024 ACS).
    state:      State abbreviation.
    source:     Data provenance label.
    geo_level:  Geographic level of the rows (default: vtd).
    loaded_by:  Label for the loaded_by audit column.
    """
    result = pd.DataFrame({
        "geoid":     df["GEOID20"].astype(str),
        "geo_level": geo_level,
        "state":     state.upper(),
        "year":      year,
        "source":    source,
    })

    if loaded_by:
        result["loaded_by"] = loaded_by

    # Initialize all CVAP columns as None
    for cdm_col in ["cvap_tot", "cvap_blk", "cvap_hsp", "cvap_wht",
                    "cvap_asn", "cvap_ami", "cvap_nhp", "cvap_oth"]:
        result[cdm_col] = None

    for col in df.columns:
        m = _CVAP_RE.match(col)
        if not m:
            continue
        base, _ = m.groups()
        cdm_col = _CVAP_COL_MAP.get(base)
        if cdm_col and result[cdm_col].isna().all():
            result[cdm_col] = (
                pd.to_numeric(df[col], errors="coerce").fillna(0).astype("int64")
            )

    return result


# ---------------------------------------------------------------------------
# upsert_to_pg
# ---------------------------------------------------------------------------

def upsert_to_pg(
    conn,
    df: pd.DataFrame,
    schema: str,
    table: str,
    pk_cols: list[str],
    replace: bool = False,
    log_fn: Callable | None = None,
) -> int:
    """
    Bulk-upsert a DataFrame into a PostgreSQL table.

    Uses COPY to a temporary table, then INSERT … ON CONFLICT DO UPDATE.
    This is the fastest approach for any row count and is safe to re-run
    (idempotent via the ON CONFLICT clause).

    Audit columns (created_at, updated_at, update_count, loaded_by) are
    intentionally excluded from the UPDATE SET clause so that:
      - created_at is set once at INSERT time and never overwritten
      - updated_at and update_count are managed by the fdp.touch_row() trigger

    Parameters
    ----------
    conn:     Open psycopg connection.
    df:       DataFrame whose columns match the target table.
    schema:   PostgreSQL schema name (e.g. "fdp").
    table:    PostgreSQL table name (e.g. "election_results").
    pk_cols:  Primary key column names — used for the ON CONFLICT clause.
    replace:  If True, DELETE existing rows matching the pk before inserting.
              Use this to reload a specific year/office without touching others.
    log_fn:   Optional logging callback.

    Returns
    -------
    Number of rows upserted.
    """
    if df.empty:
        return 0

    # Audit columns that should never be overwritten on conflict
    _IMMUTABLE_COLS = {"created_at", "updated_at", "update_count", "loaded_at"}

    fqt       = f"{schema}.{table}"
    tmp_table = f"_fdp_tmp_{table}"
    col_names = ", ".join(f'"{c}"' for c in df.columns)
    pk_str    = ", ".join(f'"{c}"' for c in pk_cols)
    update_cols = [
        c for c in df.columns
        if c not in pk_cols and c not in _IMMUTABLE_COLS
    ]
    update_str  = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)

    # ── 1. Write to in-memory CSV buffer ──────────────────────────────────────
    buf = io.StringIO()
    df.to_csv(buf, index=False, na_rep="\\N")
    buf.seek(0)
    buf.readline()   # discard header row

    with conn.cursor() as cur:
        # ── 2. Create temp table mirroring the target ─────────────────────────
        cur.execute(
            f"CREATE TEMP TABLE {tmp_table} "
            f"(LIKE {fqt} INCLUDING DEFAULTS) ON COMMIT DROP"
        )

        # ── 3. COPY data into temp table ─────────────────────────────────────
        copy_sql = (
            f"COPY {tmp_table} ({col_names}) "
            f"FROM STDIN (FORMAT CSV, NULL '\\N')"
        )
        with cur.copy(copy_sql) as copy:
            copy.write(buf.read())

        # ── 4. Optional: delete existing rows before upsert ───────────────────
        if replace:
            pk_join = " AND ".join(
                f"{fqt}.\"{c}\" = {tmp_table}.\"{c}\"" for c in pk_cols
            )
            cur.execute(f"DELETE FROM {fqt} USING {tmp_table} WHERE {pk_join}")

        # ── 5. Upsert from temp → target ─────────────────────────────────────
        if update_str:
            upsert_sql = (
                f"INSERT INTO {fqt} ({col_names}) "
                f"SELECT {col_names} FROM {tmp_table} "
                f"ON CONFLICT ({pk_str}) DO UPDATE SET {update_str}"
            )
        else:
            # All columns are PK columns (e.g. a pure junction table) — ignore conflicts
            upsert_sql = (
                f"INSERT INTO {fqt} ({col_names}) "
                f"SELECT {col_names} FROM {tmp_table} "
                f"ON CONFLICT ({pk_str}) DO NOTHING"
            )
        cur.execute(upsert_sql)
        row_count = cur.rowcount

    if log_fn:
        action = "replaced+inserted" if replace else "upserted"
        log_fn(f"    [green]✓[/] {row_count:,} rows {action} into {fqt}")

    return row_count
