#!/usr/bin/env python3
"""
score_ensemble_demographics.py — BVAP-based demographic scoring for ensemble plans.

For each draw × district, computes:
  - BVAP totals by race (Black, Hispanic, White, Asian) from 2020 Census PL 94-171
  - Percentage each group represents of total VAP
  - Majority/influence flags (configurable threshold, default 0.20)

Uses Census headcounts (not ACS estimates). Source: ga_pl2020_vtd.zip.
Uses the same vectorized matrix-multiply approach as score_ensemble_plans.py —
no Python loops over draws.

Requires: build_bvap_vtd.py must have been run once to produce
          bvap_vtd.parquet in the data directory.

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
    Load plans parquet → (n_vtds × n_draws) int16 matrix via PyArrow.

    Uses PyArrow dictionary encoding to keep geoid strings as compact
    integer indices (~486MB vs ~12GB for plain Python strings).
    Single parquet scan, no DuckDB overhead.

    Returns (plan_np, geoids, n_districts).
    """
    print(f"Loading plan matrix from {plans_file.name}…")

    # read_dictionary preserves parquet dict encoding for geoid → ~486MB vs ~3.6GB
    table = pq.read_table(plans_file, columns=["geoid", "draw", "district"],
                          read_dictionary=["geoid"])
    print(f"  Read {len(table):,} rows")

    # Get sorted unique geoids (2698 values) without combining the chunked column
    geoids  = sorted(pc.unique(table["geoid"]).to_pylist())
    row_idx = pc.index_in(table["geoid"], value_set=pa.array(geoids)) \
                .combine_chunks().to_numpy(zero_copy_only=False).astype(np.int32)

    draw_arr    = table["draw"].combine_chunks().to_numpy()
    draws_min   = int(draw_arr.min())
    draws_max   = int(draw_arr.max())
    col_idx     = (draw_arr - draws_min).astype(np.int32)
    del draw_arr

    district_arr = table["district"].combine_chunks().to_numpy()
    n_districts  = int(district_arr.max())
    vals         = district_arr.astype(np.int16)
    del district_arr, table

    n_vtds  = len(geoids)
    n_draws = draws_max - draws_min + 1

    plan_np = np.zeros((n_vtds, n_draws), dtype=np.int16)
    plan_np[row_idx, col_idx] = vals
    del row_idx, col_idx, vals

    print(f"  {n_vtds:,} VTDs × {n_draws:,} draws  ({n_districts} districts)")
    return plan_np, geoids, n_districts


# ---------------------------------------------------------------------------
# Stage 2 — Load BVAP from Parquet (2020 Census PL 94-171)
# ---------------------------------------------------------------------------

def load_bvap(geoids: list[str], bvap_file: Path) -> np.ndarray:
    """
    Load BVAP data from local Parquet, aligned to the plan matrix row order.
    Returns (n_vtds × 5) float64 matrix: [tot, blk, wht, hsp, asn]

    bvap_file: path to bvap_vtd.parquet produced by build_bvap_vtd.py.
    Columns: GEOID20, bvap_tot, bvap_blk, bvap_wht, bvap_hsp, bvap_asn, bvap_coalition
    """
    if not bvap_file.exists():
        raise FileNotFoundError(
            f"BVAP Parquet not found: {bvap_file}\n"
            "  Run build_bvap_vtd.py first:\n"
            "    uv run --project fdp python fdp/scripts/build_bvap_vtd.py"
        )

    print(f"Loading BVAP from {bvap_file.name}…")
    bvap_df = pd.read_parquet(bvap_file).set_index("GEOID20")
    print(f"  {len(bvap_df):,} VTDs in BVAP data (2020 Census PL 94-171)")

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

    all_bvap = np.zeros((n_districts, n_draws, 5), dtype=np.float64)

    for d_idx, district in enumerate(range(1, n_districts + 1)):
        mask = (plan_np == district)
        all_bvap[d_idx] = mask.T.astype(np.float64) @ bvap_np
        if (d_idx + 1) % 5 == 0:
            print(f"  District {district:>3}/{n_districts}…")

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
                    help="Path to bvap_vtd.parquet (2020 Census PL 94-171). "
                         "Defaults to {data_dir}/vtd/bvap_vtd.parquet.")
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
        else data_dir / "vtd" / "bvap_vtd.parquet"
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
    print(f"  Influence Black             : {enacted.majority_black.sum()}")
    print(f"  Influence White             : {enacted.majority_white.sum()}")
    print(f"  Influence Hispanic          : {enacted.majority_hispanic.sum()}")
    print(f"  Influence Minority Coalition: {enacted.majority_minority_coalition.sum()}")

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
