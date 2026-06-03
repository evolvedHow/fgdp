#!/usr/bin/env python3
"""
export_supabase_to_parquet.py — One-time export of Supabase reference tables to Parquet.

Run this ONCE to export election results and CVAP data from Supabase.
After this, the scoring pipeline uses local Parquet files; Supabase is no longer needed.

Exports:
  {data_dir}/election_results_vtd.parquet  — fdp.election_results WHERE geo_level = 'vtd'
  {data_dir}/cvap_vtd.parquet             — fdp.cvap WHERE geo_level = 'vtd'

Optionally also frees Supabase space by truncating/dropping large tables:
  fdp.ensemble_plans   (13.5M rows — plans already in Modal volume as Parquet)
  fdp.ensemble_scores  (900k rows  — now written as Parquet by scoring pipeline)
  fdp.ensemble_demographics  (1.4M rows — same)
  fdp.ensemble_draw_stats    (50k rows  — same)
  fdp.ensemble_competitive_counts  (15k rows — same)

Usage (from fgdp/ root):
    DATABASE_URL="postgresql://..." uv run --project fdp \\
        python fdp/scripts/export_supabase_to_parquet.py

    # Also truncate large tables to free Supabase space:
    DATABASE_URL="..." uv run --project fdp \\
        python fdp/scripts/export_supabase_to_parquet.py --free-supabase

    # Dry run (print row counts only):
    DATABASE_URL="..." uv run --project fdp \\
        python fdp/scripts/export_supabase_to_parquet.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import psycopg

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = _SCRIPT_DIR.parent / "data/repos/main"

DB_URL = os.environ.get("DATABASE_URL")

# Tables to truncate when --free-supabase is passed
# Order matters: computed tables first (no FK dependencies), then plans
_TABLES_TO_DROP = [
    ("fdp.ensemble_competitive_counts", "competitive counts (15k rows)"),
    ("fdp.ensemble_draw_stats",         "draw stats (50k rows)"),
    ("fdp.ensemble_demographics",       "demographics (1.4M rows)"),
    ("fdp.ensemble_scores",             "partisan scores (900k+ rows)"),
    ("fdp.ensemble_plans",              "plan assignments (13.5M rows — largest!)"),
]


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def export_election_results(conn: psycopg.Connection, out_path: Path, dry_run: bool) -> None:
    """Export fdp.election_results (VTD level) to Parquet."""
    row = conn.execute(
        "SELECT COUNT(*) FROM fdp.election_results WHERE geo_level = 'vtd'"
    ).fetchone()
    n = row[0] if row else 0
    print(f"  election_results (vtd): {n:,} rows")

    if dry_run:
        return

    rows = conn.execute("""
        SELECT geoid, year, election_type, office, party, votes
        FROM fdp.election_results
        WHERE geo_level = 'vtd'
          AND party IN ('dem', 'rep')
        ORDER BY geoid, year, election_type, office, party
    """).fetchall()

    df = pd.DataFrame(rows, columns=["geoid", "year", "election_type", "office", "party", "votes"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    size_mb = out_path.stat().st_size / 1_000_000
    print(f"  → Saved {len(df):,} rows to {out_path.name}  ({size_mb:.1f} MB)")


def export_cvap(conn: psycopg.Connection, out_path: Path, dry_run: bool) -> None:
    """Export fdp.cvap (VTD level, most recent year) to Parquet."""
    row = conn.execute(
        "SELECT MAX(year) FROM fdp.cvap WHERE geo_level = 'vtd'"
    ).fetchone()
    max_year = row[0] if row and row[0] else None

    row2 = conn.execute(
        "SELECT COUNT(*) FROM fdp.cvap WHERE geo_level = 'vtd'"
    ).fetchone()
    n = row2[0] if row2 else 0
    print(f"  cvap (vtd, max_year={max_year}): {n:,} rows")

    if dry_run:
        return

    rows = conn.execute("""
        SELECT geoid, year, cvap_tot, cvap_blk, cvap_hsp, cvap_wht, cvap_asn
        FROM fdp.cvap
        WHERE geo_level = 'vtd'
        ORDER BY geoid, year
    """).fetchall()

    df = pd.DataFrame(rows, columns=["geoid", "year", "cvap_tot", "cvap_blk", "cvap_hsp", "cvap_wht", "cvap_asn"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    size_mb = out_path.stat().st_size / 1_000_000
    print(f"  → Saved {len(df):,} rows to {out_path.name}  ({size_mb:.1f} MB)")


def free_supabase(conn: psycopg.Connection, dry_run: bool) -> None:
    """Truncate large ensemble tables to reclaim Supabase free-tier storage."""
    print("\nFreeing Supabase storage:")
    for table, description in _TABLES_TO_DROP:
        try:
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            n = row[0] if row else 0
            print(f"  {table}: {n:,} rows  [{description}]")
            if not dry_run and n > 0:
                conn.execute("BEGIN READ WRITE")
                conn.execute(f"TRUNCATE {table}")
                conn.execute("COMMIT")
                print(f"    → TRUNCATED")
        except Exception as exc:
            print(f"  WARNING: could not process {table}: {exc}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--data-dir", default=None,
                    help=f"Root data directory (default: {DEFAULT_DATA_DIR})")
    ap.add_argument("--free-supabase", action="store_true",
                    help="After export, TRUNCATE large Supabase tables to reclaim space")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print row counts only; do not write files or modify DB")
    args = ap.parse_args()

    if not DB_URL:
        print("ERROR: DATABASE_URL not set.")
        print("  export DATABASE_URL='postgresql://...'")
        sys.exit(1)

    data_dir = Path(args.data_dir) if args.data_dir else DEFAULT_DATA_DIR
    elec_out = data_dir / "election_results_vtd.parquet"
    cvap_out  = data_dir / "cvap_vtd.parquet"

    print(f"Connecting to Supabase…")
    print(f"Output directory: {data_dir}")
    if args.dry_run:
        print("  [dry-run] No files will be written.\n")

    with psycopg.connect(DB_URL) as conn:
        print("\nExporting reference tables:")
        export_election_results(conn, elec_out, args.dry_run)
        export_cvap(conn, cvap_out, args.dry_run)

        if args.free_supabase:
            free_supabase(conn, args.dry_run)

    if not args.dry_run:
        print(f"\n✓ Export complete.")
        print(f"  {elec_out}")
        print(f"  {cvap_out}")
        print(f"\nYou can now close/delete the Supabase project.")
        print(f"All scoring scripts will use local Parquet files from now on.")
        if not args.free_supabase:
            print(f"\nTo also free Supabase space, rerun with --free-supabase:")
            print(f"  DATABASE_URL=\"...\" python {__file__} --free-supabase")
    else:
        print(f"\n[dry-run complete] Rerun without --dry-run to export.")


if __name__ == "__main__":
    main()
