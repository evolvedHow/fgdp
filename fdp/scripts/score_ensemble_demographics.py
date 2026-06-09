#!/usr/bin/env python3
"""
score_ensemble_demographics.py — CVAP-based demographic scoring for ensemble plans.

For each draw × district, computes:
  - CVAP totals by race (Black, Hispanic, White, Asian) from 2024 ACS CVAP Special Tabulation
  - Percentage each group represents of total VAP
  - Majority/influence flags (configurable threshold, default 0.20)

Uses 2024 ACS CVAP Special Tabulation (any-part Black / Total Citizen VAP). Source: cvap_vtd.parquet.
Uses the same vectorized matrix-multiply approach as score_ensemble_plans.py —
no Python loops over draws.

Requires: build_cvap_vtd.py must have been run once to produce
          cvap_vtd.parquet in the data directory. Fallback: pass --bvap-file bvap_vtd.parquet to use 2020 Census PL 94-171 headcounts instead.

Usage (from fgdp/ root):
    # Download plans first if needed:
    modal volume get --force fdga-chain-data /ensemble/{run_name}_plans.parquet .

    uv run --project fdp python fdp/scripts/score_ensemble_demographics.py \\
        --run-name senate_450K_2601 \\
        --plans-file senate_450K_2601_plans.parquet

    uv run --project fdp python fdp/scripts/score_ensemble_demographics.py \\
        --run-name senate_450K_2601 \\
        --plans-file senate_450K_2601_plans.parquet \\
        --dry-run
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

_SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = _SCRIPT_DIR.parent / "data/repos/main"

MAJORITY_THRESHOLD = 0.20   # ≥ 20% BVAP = influence/coalition district (configurable)


# ---------------------------------------------------------------------------
# Stage 1 — Load plan matrix (DuckDB-based for memory efficiency)
# ---------------------------------------------------------------------------

def load_plan_matrix(plans_file: Path) -> tuple[np.ndarray, list[str], int]:
    """
    Load plans parquet in batches → (n_vtds × n_draws) int16 matrix.

    Reads in 5M-row batches so PyArrow never holds all rows simultaneously
    (~60MB peak per batch vs ~3GB full-table). Eliminates address-space
    fragmentation that caused OOM crashes during scoring.

    Returns (plan_np, geoids, n_districts).
    """
    print(f"Loading plan matrix from {plans_file.name}…")

    pf = pq.ParquetFile(plans_file)
    BATCH = 5_000_000

    # Pass 1: discover unique geoids and draw range
    all_geoids: set[str] = set()
    draws_min = draws_max = None
    for batch in pf.iter_batches(batch_size=BATCH, columns=["geoid", "draw"]):
        for g in pc.unique(batch.column("geoid")).to_pylist():
            all_geoids.add(g)
        darr = batch.column("draw").to_numpy()
        bmin, bmax = int(darr.min()), int(darr.max())
        if draws_min is None or bmin < draws_min:
            draws_min = bmin
        if draws_max is None or bmax > draws_max:
            draws_max = bmax

    geoids      = sorted(all_geoids)
    geoid_np    = pa.array(geoids)
    n_vtds      = len(geoids)
    n_draws     = draws_max - draws_min + 1
    plan_np     = np.zeros((n_vtds, n_draws), dtype=np.int16)
    n_districts = 0
    total_rows  = 0

    # Pass 2: fill plan_np in batches
    for batch in pf.iter_batches(batch_size=BATCH, columns=["geoid", "draw", "district"]):
        row_idx = (pc.index_in(batch.column("geoid"), value_set=geoid_np)
                   .to_numpy(zero_copy_only=False).astype(np.int32))
        col_idx = (batch.column("draw").to_numpy() - draws_min).astype(np.int32)
        vals    = batch.column("district").to_numpy().astype(np.int16)
        n_districts = max(n_districts, int(vals.max()))
        plan_np[row_idx, col_idx] = vals
        total_rows += len(batch)

    print(f"  Read {total_rows:,} rows  (batched)")
    print(f"  {n_vtds:,} VTDs × {n_draws:,} draws  ({n_districts} districts)")
    return plan_np, geoids, n_districts


# ---------------------------------------------------------------------------
# Stage 2 — Load BVAP from Parquet (2020 Census PL 94-171)
# ---------------------------------------------------------------------------

def load_bvap(geoids: list[str], bvap_file: Path) -> np.ndarray:
    """
    Load BVAP data from local Parquet, aligned to the plan matrix row order.
    Returns (n_vtds × 5) float64 matrix: [tot, blk, wht, hsp, asn]

    bvap_file: path to cvap_vtd.parquet produced by build_cvap_vtd.py.
    Columns: GEOID20, bvap_tot, bvap_blk, bvap_wht, bvap_hsp, bvap_asn, bvap_coalition
    """
    if not bvap_file.exists():
        raise FileNotFoundError(
            f"BVAP Parquet not found: {bvap_file}\n"
            "  Run build_cvap_vtd.py first:\n"
            "    uv run --project fdp python fdp/scripts/build_cvap_vtd.py"
        )

    print(f"Loading BVAP from {bvap_file.name}…")
    bvap_df = pd.read_parquet(bvap_file).set_index("GEOID20")
    print(f"  {len(bvap_df):,} VTDs in BVAP data (2024 ACS CVAP Special Tabulation (any-part Black))")

    # Align to plan matrix row order
    n_vtds = len(geoids)
    bvap_np = np.zeros((n_vtds, 5), dtype=np.float64)
    matched = 0
    for i, geoid in enumerate(geoids):
        if geoid in bvap_df.index:
            row = bvap_df.loc[geoid]
            bvap_np[i] = [row.bvap_tot, row.bvap_blk, row.bvap_wht, row.bvap_hsp, row.bvap_asn]
            matched += 1

    print(f"  {matched:,}/{n_vtds:,} VTDs matched to BVAP data")
    if matched < n_vtds * 0.99:
        print(f"  WARNING: {n_vtds - matched} VTDs unmatched — check GEOID format")

    return bvap_np


# ---------------------------------------------------------------------------
# Stage 3 — Vectorized demographic scoring
# ---------------------------------------------------------------------------

def score_demographics(
    plan_np:     np.ndarray,   # (n_vtds, n_draws)
    bvap_np:     np.ndarray,   # (n_vtds, 5) — [tot, blk, wht, hsp, asn]
    n_districts: int,
    plan_id:     str,
    majority_threshold: float = MAJORITY_THRESHOLD,
) -> pd.DataFrame:
    """
    For each draw × district, compute BVAP totals and majority/influence flags.
    Returns a long-format DataFrame ready for Parquet write.
    """
    n_vtds, n_draws = plan_np.shape
    print(f"\nScoring {n_draws:,} draws × {n_districts} districts…")
    t0 = time.time()

    bvap_f32 = bvap_np.astype(np.float32)
    all_bvap = np.zeros((n_districts, n_draws, 5), dtype=np.float32)

    # Pre-allocate all working buffers ONCE (same fragmentation fix as score_ensemble_plans).
    plan_np_T = np.ascontiguousarray(plan_np.T)
    bool_buf  = np.empty((n_draws, n_vtds), dtype=np.bool_)
    float_buf = np.empty((n_draws, n_vtds), dtype=np.float32)

    for d_idx, district in enumerate(range(1, n_districts + 1)):
        np.equal(plan_np_T, district, out=bool_buf)
        np.copyto(float_buf, bool_buf, casting="unsafe")
        all_bvap[d_idx] = float_buf @ bvap_f32
        if (d_idx + 1) % 5 == 0:
            print(f"  District {district:>3}/{n_districts}…")

    plan_np_T = bvap_f32 = bool_buf = float_buf = None

    print(f"  Matrix math done in {time.time()-t0:.1f}s")

    draws_arr     = np.arange(1, n_draws + 1)
    districts_arr = np.arange(1, n_districts + 1)

    dist_flat  = np.repeat(districts_arr, n_draws)
    draw_flat  = np.tile(draws_arr, n_districts)

    tot_flat = all_bvap[:, :, 0].ravel().astype(np.int64)
    blk_flat = all_bvap[:, :, 1].ravel().astype(np.int64)
    wht_flat = all_bvap[:, :, 2].ravel().astype(np.int64)
    hsp_flat = all_bvap[:, :, 3].ravel().astype(np.int64)
    asn_flat = all_bvap[:, :, 4].ravel().astype(np.int64)

    tot_safe = np.where(tot_flat > 0, tot_flat.astype(np.float64), np.nan)
    pct_blk  = np.round(blk_flat / tot_safe, 5)
    pct_hsp  = np.round(hsp_flat / tot_safe, 5)
    pct_wht  = np.round(wht_flat / tot_safe, 5)
    pct_asn  = np.round(asn_flat / tot_safe, 5)
    pct_min_coalition = np.round(1.0 - pct_wht, 5)

    maj_blk  = pct_blk  >= majority_threshold
    maj_wht  = pct_wht  >= majority_threshold
    maj_hsp  = pct_hsp  >= majority_threshold
    maj_coal = pct_min_coalition >= majority_threshold

    df = pd.DataFrame({
        "plan_id":                     plan_id,
        "draw":                        draw_flat.astype(np.int32),
        "district":                    dist_flat.astype(np.int32),
        "bvap_tot":                    tot_flat,
        "bvap_blk":                    blk_flat,
        "bvap_hsp":                    hsp_flat,
        "bvap_wht":                    wht_flat,
        "bvap_asn":                    asn_flat,
        "pct_black":                   pct_blk,
        "pct_hispanic":                pct_hsp,
        "pct_white":                   pct_wht,
        "pct_asian":                   pct_asn,
        "pct_minority_coalition":      pct_min_coalition,
        "majority_black":              maj_blk,
        "majority_white":              maj_wht,
        "majority_hispanic":           maj_hsp,
        "majority_minority_coalition": maj_coal,
    })

    print(f"  Built {len(df):,} rows  ({time.time()-t0:.1f}s total)")
    return df


# ---------------------------------------------------------------------------
# Stage 4 — Save to Parquet
# ---------------------------------------------------------------------------

def save_demographics(df: pd.DataFrame, out_path: Path) -> None:
    """Write demographic scores to Parquet (replaces Supabase upsert)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    size_mb = out_path.stat().st_size / 1_000_000
    print(f"\n✓ {len(df):,} rows → {out_path.name}  ({size_mb:.1f} MB)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--run-name",   required=True,
                    help="Run name (becomes plan_id in output Parquet)")
    ap.add_argument("--plans-file", required=True, dest="plans_file",
                    help="Path to plans parquet (downloaded from Modal volume)")
    ap.add_argument("--data-dir", default=None,
                    help=f"Root data directory (default: {DEFAULT_DATA_DIR})")
    ap.add_argument("--bvap-file", default=None, dest="bvap_file",
                    help="Path to demographic Parquet (same schema as bvap_vtd.parquet). "
                         "Defaults to {data_dir}/vtd/cvap_vtd.parquet (any-part Black CVAP, ACS 2024). "
                         "Pass bvap_vtd.parquet to use 2020 Census PL 94-171 headcounts.")
    ap.add_argument("--majority-threshold", type=float, default=MAJORITY_THRESHOLD,
                    dest="majority_threshold",
                    help=f"BVAP fraction threshold for majority/influence flag "
                         f"(default: {MAJORITY_THRESHOLD})")
    ap.add_argument("--out-file", default=None, dest="out_file",
                    help="Output path. Defaults to "
                         "{data_dir}/ensemble/{run_name}_demographics.parquet.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Score but do not write output")
    args = ap.parse_args()

    data_dir = Path(args.data_dir) if args.data_dir else DEFAULT_DATA_DIR

    plans_path = Path(args.plans_file)
    if not plans_path.exists():
        print(f"ERROR: plans file not found: {plans_path}")
        sys.exit(1)

    bvap_file = (
        Path(args.bvap_file).resolve()
        if args.bvap_file
        else data_dir / "vtd" / "cvap_vtd.parquet"
    )
    out_file = (
        Path(args.out_file).resolve()
        if args.out_file
        else data_dir / "ensemble" / f"{args.run_name}_demographics.parquet"
    )

    # ── Run pipeline ─────────────────────────────────────────────────────────
    plan_np, geoids, n_districts = load_plan_matrix(plans_path)
    bvap_np                      = load_bvap(geoids, bvap_file)
    df                           = score_demographics(
        plan_np, bvap_np, n_districts, args.run_name,
        majority_threshold=args.majority_threshold,
    )

    # ── Print enacted plan summary (draw=1) ──────────────────────────────────
    enacted = df[df.draw == 1].copy()
    threshold_pct = int(args.majority_threshold * 100)
    print(f"\nEnacted plan demographics (draw=1, threshold={threshold_pct}%) — {n_districts} districts:")
    print(f"  {threshold_pct}%+ Black districts        : {enacted.majority_black.sum()}")
    print(f"  {threshold_pct}%+ White districts         : {enacted.majority_white.sum()}")
    print(f"  {threshold_pct}%+ Hispanic districts      : {enacted.majority_hispanic.sum()}")
    print(f"  {threshold_pct}%+ Minority Coalition      : {enacted.majority_minority_coalition.sum()}")

    if args.dry_run:
        print(f"\n[dry-run] Would write {len(df):,} rows to {out_file.name}")
        print(df[df.draw == 1][[
            "plan_id","draw","district","pct_black","pct_white",
            "majority_black","majority_minority_coalition"
        ]].head(6).to_string())
        return

    save_demographics(df, out_file)
    print(f"\nNext: run visualize_benchmark.py after build_draw_stats.py completes.")


if __name__ == "__main__":
    main()
