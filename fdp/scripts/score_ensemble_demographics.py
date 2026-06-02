#!/usr/bin/env python3
"""
score_ensemble_demographics.py — CVAP-based demographic scoring for ensemble plans.

For each draw × district, computes:
  - CVAP totals by race (Black, Hispanic, White, Asian)
  - Percentage each group represents of total CVAP
  - Majority flags (> 50% threshold)

Uses the same vectorized matrix-multiply approach as score_ensemble_plans.py —
no Python loops over draws.

Requires:
  - Plans parquet (downloaded from Modal volume)
  - CVAP data in fdp.cvap (already loaded by build_vtd_inputs.py)

Usage (from fgdp/ root):
    # Download plans first if needed:
    modal volume get --force fdga-chain-data /ensemble/{run_name}_plans.parquet .

    uv run --project fdp python fdp/scripts/score_ensemble_demographics.py \\
        --run-name congress_2026_v1 \\
        --plans-file congress_2026_v1_plans.parquet

    uv run --project fdp python fdp/scripts/score_ensemble_demographics.py \\
        --run-name congress_2026_v1 \\
        --plans-file congress_2026_v1_plans.parquet \\
        --dry-run
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

DB_URL = os.environ.get("DATABASE_URL")

MAJORITY_THRESHOLD = 0.50   # > 50% CVAP = majority district


# ---------------------------------------------------------------------------
# Stage 1 — Load plan matrix
# ---------------------------------------------------------------------------

def load_plan_matrix(plans_file: Path) -> tuple[np.ndarray, list[str], int]:
    """
    Load plans parquet → (n_vtds × n_draws) int16 matrix.
    Returns (plan_np, geoids, n_districts).
    """
    print(f"Loading plan matrix from {plans_file.name}…")
    df = pd.read_parquet(plans_file, columns=["geoid", "draw", "district"])
    pivot = df.pivot(index="geoid", columns="draw", values="district")
    plan_np = pivot.values.astype(np.int16)
    geoids = list(pivot.index)
    n_districts = int(plan_np.max())
    n_vtds, n_draws = plan_np.shape
    print(f"  {n_vtds:,} VTDs × {n_draws:,} draws  ({n_districts} districts)")
    return plan_np, geoids, n_districts


# ---------------------------------------------------------------------------
# Stage 2 — Load CVAP from Supabase
# ---------------------------------------------------------------------------

def load_cvap(geoids: list[str]) -> np.ndarray:
    """
    Pull CVAP data from fdp.cvap, aligned to the plan matrix row order.
    Returns (n_vtds × 5) float64 matrix: [tot, blk, hsp, wht, asn]
    """
    print("Loading CVAP from Supabase…")
    sql = """
        SELECT geoid, cvap_tot, cvap_blk, cvap_hsp, cvap_wht, cvap_asn
        FROM fdp.cvap
        WHERE geo_level = 'vtd'
          AND year = (SELECT MAX(year) FROM fdp.cvap WHERE geo_level = 'vtd')
        ORDER BY geoid
    """
    with psycopg.connect(DB_URL) as conn:
        rows = conn.execute(sql).fetchall()

    cvap_df = pd.DataFrame(rows, columns=["geoid","cvap_tot","cvap_blk","cvap_hsp","cvap_wht","cvap_asn"])
    cvap_df = cvap_df.set_index("geoid")
    print(f"  {len(cvap_df):,} VTDs in Supabase CVAP")

    # Align to plan matrix row order (geoids from plans parquet)
    n_vtds = len(geoids)
    cvap_np = np.zeros((n_vtds, 5), dtype=np.float64)
    matched = 0
    for i, geoid in enumerate(geoids):
        if geoid in cvap_df.index:
            row = cvap_df.loc[geoid]
            cvap_np[i] = [row.cvap_tot, row.cvap_blk, row.cvap_hsp, row.cvap_wht, row.cvap_asn]
            matched += 1

    print(f"  {matched:,}/{n_vtds:,} VTDs matched to CVAP data")
    if matched < n_vtds * 0.99:
        print(f"  WARNING: {n_vtds - matched} VTDs unmatched — check GEOID format")

    return cvap_np


# ---------------------------------------------------------------------------
# Stage 3 — Vectorized demographic scoring
# ---------------------------------------------------------------------------

def score_demographics(
    plan_np:     np.ndarray,   # (n_vtds, n_draws)
    cvap_np:     np.ndarray,   # (n_vtds, 5) — [tot, blk, hsp, wht, asn]
    n_districts: int,
    plan_id:     str,
) -> pd.DataFrame:
    """
    For each draw × district, compute CVAP totals and majority flags.
    Returns a long-format DataFrame ready for upsert.
    """
    n_vtds, n_draws = plan_np.shape
    print(f"\nScoring {n_draws:,} draws × {n_districts} districts…")
    t0 = time.time()

    # Pre-allocate: (n_districts, n_draws, 5)
    # Index 0=tot, 1=blk, 2=hsp, 3=wht, 4=asn
    all_cvap = np.zeros((n_districts, n_draws, 5), dtype=np.float64)

    for d_idx, district in enumerate(range(1, n_districts + 1)):
        mask = (plan_np == district)             # (n_vtds, n_draws) bool
        all_cvap[d_idx] = mask.T.astype(np.float64) @ cvap_np   # (n_draws, 5)
        if (d_idx + 1) % 5 == 0:
            print(f"  District {district:>3}/{n_districts}…")

    print(f"  Matrix math done in {time.time()-t0:.1f}s")

    # ── Build long-format DataFrame ──────────────────────────────────────────
    draws_arr     = np.arange(1, n_draws + 1)      # (n_draws,)
    districts_arr = np.arange(1, n_districts + 1)  # (n_districts,)

    # Flatten to (n_districts × n_draws) rows
    dist_flat  = np.repeat(districts_arr, n_draws)  # [1,1,…,2,2,…]
    draw_flat  = np.tile(draws_arr, n_districts)    # [1,2,3,…,1,2,3,…]
    total_rows = n_districts * n_draws

    # Extract columns: all_cvap has shape (n_districts, n_draws, 5)
    tot_flat = all_cvap[:, :, 0].ravel().astype(np.int64)
    blk_flat = all_cvap[:, :, 1].ravel().astype(np.int64)
    hsp_flat = all_cvap[:, :, 2].ravel().astype(np.int64)
    wht_flat = all_cvap[:, :, 3].ravel().astype(np.int64)
    asn_flat = all_cvap[:, :, 4].ravel().astype(np.int64)

    # Percentages (safe divide)
    tot_safe = np.where(tot_flat > 0, tot_flat.astype(np.float64), np.nan)
    pct_blk  = np.round(blk_flat / tot_safe, 5)
    pct_hsp  = np.round(hsp_flat / tot_safe, 5)
    pct_wht  = np.round(wht_flat / tot_safe, 5)
    pct_asn  = np.round(asn_flat / tot_safe, 5)
    pct_min_coalition = np.round(1.0 - pct_wht, 5)  # all non-white CVAP

    # Majority flags
    maj_blk  = pct_blk  > MAJORITY_THRESHOLD
    maj_wht  = pct_wht  > MAJORITY_THRESHOLD
    maj_hsp  = pct_hsp  > MAJORITY_THRESHOLD
    maj_coal = pct_min_coalition > MAJORITY_THRESHOLD

    df = pd.DataFrame({
        "plan_id":                   plan_id,
        "draw":                      draw_flat.astype(np.int32),
        "district":                  dist_flat.astype(np.int32),
        "cvap_tot":                  tot_flat,
        "cvap_blk":                  blk_flat,
        "cvap_hsp":                  hsp_flat,
        "cvap_wht":                  wht_flat,
        "cvap_asn":                  asn_flat,
        "pct_black":                 pct_blk,
        "pct_hispanic":              pct_hsp,
        "pct_white":                 pct_wht,
        "pct_asian":                 pct_asn,
        "pct_minority_coalition":    pct_min_coalition,
        "majority_black":            maj_blk,
        "majority_white":            maj_wht,
        "majority_hispanic":         maj_hsp,
        "majority_minority_coalition": maj_coal,
    })

    print(f"  Built {len(df):,} rows  ({time.time()-t0:.1f}s total)")
    return df


# ---------------------------------------------------------------------------
# Stage 4 — Upsert to Supabase
# ---------------------------------------------------------------------------

def upsert_demographics(df: pd.DataFrame, batch_size: int = 50_000) -> None:
    PK = ["plan_id", "draw", "district"]
    update_cols = [c for c in df.columns if c not in PK and c != "created_at"]
    col_names  = ", ".join(f'"{c}"' for c in df.columns)
    pk_str     = ", ".join(f'"{c}"' for c in PK)
    update_str = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)

    total     = len(df)
    n_batches = (total + batch_size - 1) // batch_size
    total_done = 0
    t0        = time.time()
    print(f"\nUpserting {total:,} rows in {n_batches} batch(es)…")

    with psycopg.connect(DB_URL) as conn:
        conn.execute("SET SESSION default_transaction_read_only = off")

        for i in range(n_batches):
            batch = df.iloc[i * batch_size : (i + 1) * batch_size]
            buf   = io.StringIO()
            batch.to_csv(buf, index=False, na_rep="\\N")
            buf.seek(0); buf.readline()

            conn.execute("BEGIN READ WRITE")
            with conn.cursor() as cur:
                cur.execute(
                    "CREATE TEMP TABLE IF NOT EXISTS _tmp_demo "
                    "(LIKE fdp.ensemble_demographics INCLUDING DEFAULTS)"
                )
                cur.execute("TRUNCATE _tmp_demo")
                with cur.copy(
                    f"COPY _tmp_demo ({col_names}) FROM STDIN (FORMAT CSV, NULL '\\N')"
                ) as copy:
                    copy.write(buf.read())
                cur.execute(
                    f"INSERT INTO fdp.ensemble_demographics ({col_names}) "
                    f"SELECT {col_names} FROM _tmp_demo "
                    f"ON CONFLICT ({pk_str}) DO UPDATE SET {update_str}"
                )
                n = cur.rowcount
            conn.execute("COMMIT")

            total_done += n
            elapsed = time.time() - t0
            rate    = total_done / elapsed if elapsed > 0 else 0
            eta     = (total - total_done) / rate if rate > 0 else 0
            print(f"  Batch {i+1:>3}/{n_batches}  {total_done:>9,}/{total:,}"
                  f"  {rate:,.0f} rows/s  ETA {eta/60:.1f} min")

    print(f"\n✓ {total_done:,} rows in {(time.time()-t0)/60:.1f} min")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--run-name",   required=True,
                    help="Run name (becomes plan_id in ensemble_demographics)")
    ap.add_argument("--plans-file", required=True, dest="plans_file",
                    help="Path to plans parquet (downloaded from Modal volume)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Score but do not write to Supabase")
    ap.add_argument("--batch-size", type=int, default=50_000,
                    dest="batch_size")
    args = ap.parse_args()

    if not DB_URL and not args.dry_run:
        print("ERROR: DATABASE_URL not set.")
        sys.exit(1)

    plans_path = Path(args.plans_file)
    if not plans_path.exists():
        print(f"ERROR: plans file not found: {plans_path}")
        sys.exit(1)

    # ── Run pipeline ─────────────────────────────────────────────────────────
    plan_np, geoids, n_districts = load_plan_matrix(plans_path)
    cvap_np                      = load_cvap(geoids)
    df                           = score_demographics(plan_np, cvap_np, n_districts, args.run_name)

    # ── Print enacted plan summary (draw=1) ──────────────────────────────────
    enacted = df[df.draw == 1].copy()
    print(f"\nEnacted plan demographics (draw=1) — {n_districts} districts:")
    print(f"  Majority Black : {enacted.majority_black.sum()}")
    print(f"  Majority White : {enacted.majority_white.sum()}")
    print(f"  Majority Hispanic : {enacted.majority_hispanic.sum()}")
    print(f"  Majority Minority Coalition : {enacted.majority_minority_coalition.sum()}")

    if args.dry_run:
        print(f"\n[dry-run] Would upsert {len(df):,} rows to fdp.ensemble_demographics")
        print(df[df.draw == 1][["plan_id","draw","district","pct_black","pct_white","majority_black","majority_minority_coalition"]].head(6).to_string())
        return

    upsert_demographics(df, batch_size=args.batch_size)

    # ── Verify via view ──────────────────────────────────────────────────────
    print("\nEnsemble distribution (avg majority-X districts across draws):")
    sql = """
        SELECT
            ROUND(AVG(n_majority_black)::numeric,    2) AS avg_maj_black,
            ROUND(AVG(n_majority_white)::numeric,    2) AS avg_maj_white,
            ROUND(AVG(n_majority_hispanic)::numeric, 2) AS avg_maj_hispanic,
            ROUND(AVG(n_majority_coalition)::numeric,2) AS avg_maj_coalition
        FROM fdp.v_demographic_draw_stats
        WHERE plan_id = %s AND draw > 1
    """
    with psycopg.connect(DB_URL) as conn:
        row = conn.execute(sql, (args.run_name,)).fetchone()
    if row:
        print(f"  Avg majority Black     : {row[0]}")
        print(f"  Avg majority White     : {row[1]}")
        print(f"  Avg majority Hispanic  : {row[2]}")
        print(f"  Avg majority Coalition : {row[3]}")

    print(f"\nNext: run Senate + House benchmarks, then visualize:")
    print(f"  SELECT * FROM fdp.v_demographic_distribution WHERE plan_id = '{args.run_name}';")


if __name__ == "__main__":
    main()
