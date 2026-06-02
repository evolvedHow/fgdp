#!/usr/bin/env python3
"""
Load ensemble plan assignments from parquet into fdp.ensemble_plans (Supabase).

Source: data/repos/main/ensemble/ga_congress_2020_alarm_5001_plans.parquet
Target: fdp.ensemble_plans  (13,492,698 rows for the 5001-draw GA congress ensemble)

Usage (from fdp/ in WSL):
    uv run python scripts/load_ensemble_plans.py
    uv run python scripts/load_ensemble_plans.py --dry-run        # stats only
    uv run python scripts/load_ensemble_plans.py --start-batch 61 # resume after failure
    uv run python scripts/load_ensemble_plans.py --batch-size 50000
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import pandas as pd
import psycopg

# ── Config ────────────────────────────────────────────────────────────────────

PARQUET_PATH = (
    Path(__file__).resolve().parent.parent
    / "data/repos/main/ensemble/ga_congress_2020_alarm_5001_plans.parquet"
)

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres.qcuveiiywbrmzguzducu:fdga-fdp-2016%21"
    "@aws-1-us-east-2.pooler.supabase.com:5432/postgres",
)

PK_COLS   = ["plan_id", "draw", "geoid"]
BATCH_SIZE_DEFAULT = 50_000   # rows per upsert batch


# ── Loader ────────────────────────────────────────────────────────────────────

def _upsert_batch(conn, batch: "pd.DataFrame") -> int:
    """Upsert one batch using an explicit BEGIN/COMMIT around COPY + INSERT."""
    import io

    col_names   = ", ".join(f'"{c}"' for c in batch.columns)
    pk_str      = ", ".join(f'"{c}"' for c in PK_COLS)
    update_cols = [c for c in batch.columns
                   if c not in PK_COLS and c not in
                   {"created_at", "updated_at", "update_count", "loaded_at"}]
    update_str  = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)

    buf = io.StringIO()
    batch.to_csv(buf, index=False, na_rep="\\N")
    buf.seek(0)
    buf.readline()   # discard header row

    with conn.cursor() as cur:
        # BEGIN READ WRITE explicitly overrides default_transaction_read_only=on
        # which the Supabase session pooler may set on the connection.
        cur.execute("BEGIN READ WRITE")
        cur.execute(
            "CREATE TEMP TABLE IF NOT EXISTS _fdp_tmp_ensemble_plans "
            "(LIKE fdp.ensemble_plans INCLUDING DEFAULTS)"
        )
        cur.execute("TRUNCATE _fdp_tmp_ensemble_plans")
        with cur.copy(
            f"COPY _fdp_tmp_ensemble_plans ({col_names}) "
            f"FROM STDIN (FORMAT CSV, NULL '\\N')"
        ) as copy:
            copy.write(buf.read())
        cur.execute(
            f"INSERT INTO fdp.ensemble_plans ({col_names}) "
            f"SELECT {col_names} FROM _fdp_tmp_ensemble_plans "
            f"ON CONFLICT ({pk_str}) DO UPDATE SET {update_str}"
        )
        n = cur.rowcount
        cur.execute("COMMIT")

    return n


def load_ensemble_plans(
    dry_run: bool = False,
    batch_size: int = BATCH_SIZE_DEFAULT,
    start_batch: int = 1,
) -> None:
    print(f"Reading {PARQUET_PATH} …")
    df = pd.read_parquet(PARQUET_PATH)
    total = len(df)
    print(f"  {total:,} rows  ×  {len(df.columns)} columns")
    print(f"  Draws:    {df['draw'].min()}–{df['draw'].max()}")
    print(f"  VTDs:     {df['geoid'].nunique():,}")
    print(f"  Districts:{df['district'].min()}–{df['district'].max()}")

    if dry_run:
        print("\n[dry-run] No data written.")
        return

    n_batches   = (total + batch_size - 1) // batch_size
    start_idx   = start_batch - 1          # 0-indexed
    rows_before = start_idx * batch_size   # already loaded in prior run

    if start_batch > 1:
        print(f"\nResuming from batch {start_batch} "
              f"(skipping {rows_before:,} already-loaded rows)")

    print(f"\nConnecting to Supabase (autocommit=True) …")
    total_rows = 0
    t0 = time.time()

    # autocommit=True + explicit SET ensures we're never in a read-only session
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SET SESSION default_transaction_read_only = off")
        for i in range(start_idx, n_batches):
            batch = df.iloc[i * batch_size : (i + 1) * batch_size]
            n = _upsert_batch(conn, batch)
            total_rows += n

            elapsed  = time.time() - t0
            done     = rows_before + total_rows
            pct      = done / total * 100
            rate     = total_rows / elapsed if elapsed > 0 else 0
            eta      = (total - done) / rate if rate > 0 else 0
            print(
                f"  Batch {i+1:>4}/{n_batches}  "
                f"{done:>12,}/{total:,} rows  "
                f"({pct:5.1f}%)  "
                f"{rate:,.0f} rows/s  "
                f"ETA {eta/60:.1f} min"
            )

    elapsed = time.time() - t0
    print(f"\n✓ Done. {total_rows:,} new rows in {elapsed/60:.1f} min "
          f"({total_rows/elapsed:,.0f} rows/s)")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="Print stats only, do not write to database")
    ap.add_argument("--batch-size", type=int, default=BATCH_SIZE_DEFAULT,
                    help=f"Rows per upsert batch (default: {BATCH_SIZE_DEFAULT:,})")
    ap.add_argument("--start-batch", type=int, default=1,
                    help="Resume from this 1-indexed batch number (default: 1)")
    args = ap.parse_args()

    load_ensemble_plans(
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        start_batch=args.start_batch,
    )
