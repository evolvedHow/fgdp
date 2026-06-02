#!/usr/bin/env python3
"""
load_missing_elections.py — Load 2018 Governor and 2020 President to Supabase.

Pre-requisites:
  1. 2020 President parquet — run first:
       uv run python scripts/build_vtd_inputs.py --only president2020

  2. 2018 Governor parquet — run first:
       Rscript scripts/export_2018_governor.R

Both produce VTD-level parquets with RDH-format column names.
This script melts them to long format and upserts to fdp.election_results.

Usage (from fdp/ directory):
    uv run python scripts/load_missing_elections.py
    uv run python scripts/load_missing_elections.py --dry-run
    uv run python scripts/load_missing_elections.py --only president2020
    uv run python scripts/load_missing_elections.py --only governor2018
"""
from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

import pandas as pd
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fdp.transforms.pg_loaders import melt_election_vtd, upsert_to_pg

# ── Paths ──────────────────────────────────────────────────────────────────────

VTD_DIR  = Path(__file__).resolve().parent.parent / "data/repos/main/vtd"

PRES_2020_PARQUET = VTD_DIR / "vtd_elections_2020_president.parquet"
GOV_2018_PARQUET  = VTD_DIR / "vtd_elections_2018_governor.parquet"

DB_URL = os.environ.get("DATABASE_URL")


# ── Helpers ────────────────────────────────────────────────────────────────────

def check_already_loaded(conn: psycopg.Connection, year: int, office: str) -> int:
    """Return row count for this year/office in fdp.election_results."""
    row = conn.execute(
        "SELECT COUNT(*) FROM fdp.election_results "
        "WHERE year = %s AND office = %s AND geo_level = 'vtd'",
        (year, office),
    ).fetchone()
    return row[0] if row else 0


def load_election(
    parquet_path: Path,
    year: int,
    office: str,
    dry_run: bool,
) -> None:
    label = f"{year} {office}"

    if not parquet_path.exists():
        print(f"  ERROR: {parquet_path} not found.")
        if year == 2020:
            print("  Run: uv run python scripts/build_vtd_inputs.py --only president2020")
        elif year == 2018:
            print("  Run: Rscript scripts/export_2018_governor.R")
        return

    print(f"\n── {label} ──────────────────────────────────────────")
    print(f"  Reading: {parquet_path.name}")
    df = pd.read_parquet(parquet_path)
    print(f"  {len(df):,} VTDs  ×  {len(df.columns)} columns")
    print(f"  Columns: {[c for c in df.columns if c not in ('GEOID20','VAP_MOD')]}")

    # Melt wide → long using existing pg_loaders pipeline
    long_df = melt_election_vtd(
        df,
        state    = "GA",
        source   = "ALARM" if year == 2018 else "RDH",
        geo_level= "vtd",
        collection_geo_level = "vtd" if year == 2018 else "block",
        loaded_by= "load_missing_elections.py",
    )

    # Filter to just this year/office (in case the parquet has extras)
    long_df = long_df[(long_df["year"] == year) & (long_df["office"] == office)]
    print(f"  {len(long_df):,} rows after melt  "
          f"({long_df['party'].value_counts().to_dict()})")

    if len(long_df) == 0:
        print(f"  WARNING: no rows matched year={year} office={office} — check column parsing")
        return

    if dry_run:
        print(f"\n  [dry-run] Would upsert {len(long_df):,} rows to fdp.election_results")
        print(long_df.head(4).to_string())
        return

    PK = ["geoid", "year", "election_type", "office", "party", "candidate"]

    # Check existing count (read-only, autocommit fine here)
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        existing = check_already_loaded(conn, year, office)
        if existing > 0:
            print(f"  {existing:,} rows already in Supabase — will upsert (update existing)")

    # Upsert in an explicit READ WRITE transaction
    # (Supabase session pooler defaults to read-only; BEGIN READ WRITE overrides it)
    with psycopg.connect(DB_URL) as conn:
        conn.execute("SET SESSION default_transaction_read_only = off")
        conn.execute("BEGIN READ WRITE")
        n = upsert_to_pg(conn, long_df, schema="fdp", table="election_results", pk_cols=PK)
        conn.execute("COMMIT")
    print(f"  ✓ Loaded {n:,} rows")

    with psycopg.connect(DB_URL, autocommit=True) as conn:
        count = check_already_loaded(conn, year, office)
    print(f"  Supabase now has {count:,} rows for {label}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="Parse and melt but do not write to Supabase")
    ap.add_argument("--only", choices=["president2020", "governor2018"],
                    help="Load only one election")
    args = ap.parse_args()

    if not DB_URL and not args.dry_run:
        print("ERROR: DATABASE_URL not set.")
        print("  export DATABASE_URL='postgresql://...'")
        sys.exit(1)

    run_pres = args.only in (None, "president2020")
    run_gov  = args.only in (None, "governor2018")

    if run_pres:
        load_election(PRES_2020_PARQUET, year=2020, office="president", dry_run=args.dry_run)

    if run_gov:
        load_election(GOV_2018_PARQUET,  year=2018, office="governor",  dry_run=args.dry_run)

    if not args.dry_run:
        print("\n✓ Done. Both elections now in Supabase.")
        print("\nVerify:")
        print("  SELECT year, office, COUNT(*) FROM fdp.election_results")
        print("  WHERE year IN (2018,2020) GROUP BY 1,2 ORDER BY 1,2;")


if __name__ == "__main__":
    main()
