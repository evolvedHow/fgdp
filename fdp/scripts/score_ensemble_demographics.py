#!/usr/bin/env python3
"""
score_ensemble_demographics.py — CVAP-based demographic scoring for ensemble plans.

For each draw × district, computes:
  - CVAP totals by race (Black, Hispanic, White, Asian)
  - Percentage each group represents of total CVAP
  - Majority flags (> 50% threshold)

Uses the same vectorized matrix-multiply approach as score_ensemble_plans.py —
no Python loops over draws.

Requires: export_supabase_to_parquet.py must have been run once to produce
          cvap_vtd.parquet in the data directory.

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
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = _SCRIPT_DIR.parent / "data/repos/main"

MAJORITY_THRESHOLD = 0.50   # > 50% CVAP = majority district


# ---------------------------------------------------------------------------
# Stage 1 — Load plan matrix (DuckDB-based for memory efficiency)
# ---------------------------------------------------------------------------

def load_plan_matrix(plans_file: Path) -> tuple[np.ndarray, list[str], int]:
    """
    Load plans parquet → (n_vtds × n_draws) int16 matrix via DuckDB.

    Uses DuckDB instead of pandas pivot to avoid Python object overhead on
    the geoid string column. For house-scale runs (64M+ rows, 24k draws,
    180 districts) pandas peak memory during pivot exceeds 5GB; DuckDB
    keeps strings dictionary-encoded and uses ~2GB total.

    Returns (plan_np, geoids, n_districts).
    """
    print(f"Loading plan matrix from {plans_file.name}…")
    conn = duckdb.connect()

    # Metadata in one pass
    meta = conn.execute("""
        SELECT COUNT(DISTINCT geoid) AS n_vtds,
               COUNT(DISTINCT draw)  AS n_draws,
               MAX(district)         AS n_districts
        FROM read_parquet(?)
    """, [str(plans_file)]).fetchone()
    n_vtds, n_draws, n_districts = int(meta[0]), int(meta[1]), int(meta[2])

    # Ordered geoids and draws
    geoids = [r[0] for r in conn.execute(
        "SELECT DISTINCT geoid FROM read_parquet(?) ORDER BY geoid",
        [str(plans_file)]
    ).fetchall()]
    draws = [r[0] for r in conn.execute(
        "SELECT DISTINCT draw FROM read_parquet(?) ORDER BY draw",
        [str(plans_file)]
    ).fetchall()]

    # Map geoid strings → integer row indices entirely in DuckDB SQL.
    # Avoids ever creating 64M Python string objects in the Python process.
    # fetchnumpy() then returns only integer arrays (~650 MB total for house).
    p = str(plans_file)
    result = conn.execute("""
        WITH geoid_map AS (
            SELECT geoid,
                   (ROW_NUMBER() OVER (ORDER BY geoid) - 1)::INTEGER AS geoid_idx
            FROM (SELECT DISTINCT geoid FROM read_parquet(?))
        ),
        draw_map AS (
            SELECT draw,
                   (ROW_NUMBER() OVER (ORDER BY draw) - 1)::INTEGER AS draw_idx
            FROM (SELECT DISTINCT draw FROM read_parquet(?))
        )
        SELECT g.geoid_idx, d.draw_idx, p.district::SMALLINT AS district
        FROM read_parquet(?) p
        JOIN geoid_map g USING (geoid)
        JOIN draw_map  d USING (draw)
        ORDER BY d.draw_idx, g.geoid_idx
    """, [p, p, p]).fetchnumpy()

    row_idx = result["geoid_idx"].astype(np.int32)
    col_idx = result["draw_idx"].astype(np.int32)
    vals    = result["district"].astype(np.int16)

    plan_np = np.zeros((n_vtds, n_draws), dtype=np.int16)
    plan_np[row_idx, col_idx] = vals

    print(f"  {n_vtds:,} VTDs × {n_draws:,} draws  ({n_districts} districts)")
    return plan_np, geoids, n_districts


# ---------------------------------------------------------------------------
# Stage 2 — Load CVAP from Parquet
# ---------------------------------------------------------------------------

def load_cvap(geoids: list[str], cvap_file: Path) -> np.ndarray:
    """
    Load CVAP data from local Parquet, aligned to the plan matrix row order.
    Returns (n_vtds × 5) float64 matrix: [tot, blk, hsp, wht, asn]

    cvap_file: path to cvap_vtd.parquet produced by export_supabase_to_parquet.py.
    """
    if not cvap_file.exists():
        raise FileNotFoundError(
            f"CVAP Parquet not found: {cvap_file}\n"
            "  Run export_supabase_to_parquet.py first:\n"
            "    DATABASE_URL='...' uv run --project fdp "
            "python fdp/scripts/export_supabase_to_parquet.py"
        )

    print(f"Loading CVAP from {cvap_file.name}…")
    cvap_df = pd.read_parquet(cvap_file)

    # Use most recent year available
    max_year = cvap_df["year"].max()
    cvap_df = cvap_df[cvap_df["year"] == max_year].set_index("geoid")
    print(f"  {len(cvap_df):,} VTDs in CVAP (year={max_year})")

    # Align to plan matrix row order
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
    Returns a long-format DataFrame ready for Parquet write.
    """
    n_vtds, n_draws = plan_np.shape
    print(f"\nScoring {n_draws:,} draws × {n_districts} districts…")
    t0 = time.time()

    all_cvap = np.zeros((n_districts, n_draws, 5), dtype=np.float64)

    for d_idx, district in enumerate(range(1, n_districts + 1)):
        mask = (plan_np == district)
        all_cvap[d_idx] = mask.T.astype(np.float64) @ cvap_np
        if (d_idx + 1) % 5 == 0:
            print(f"  District {district:>3}/{n_districts}…")

    print(f"  Matrix math done in {time.time()-t0:.1f}s")

    draws_arr     = np.arange(1, n_draws + 1)
    districts_arr = np.arange(1, n_districts + 1)

    dist_flat  = np.repeat(districts_arr, n_draws)
    draw_flat  = np.tile(draws_arr, n_districts)

    tot_flat = all_cvap[:, :, 0].ravel().astype(np.int64)
    blk_flat = all_cvap[:, :, 1].ravel().astype(np.int64)
    hsp_flat = all_cvap[:, :, 2].ravel().astype(np.int64)
    wht_flat = all_cvap[:, :, 3].ravel().astype(np.int64)
    asn_flat = all_cvap[:, :, 4].ravel().astype(np.int64)

    tot_safe = np.where(tot_flat > 0, tot_flat.astype(np.float64), np.nan)
    pct_blk  = np.round(blk_flat / tot_safe, 5)
    pct_hsp  = np.round(hsp_flat / tot_safe, 5)
    pct_wht  = np.round(wht_flat / tot_safe, 5)
    pct_asn  = np.round(asn_flat / tot_safe, 5)
    pct_min_coalition = np.round(1.0 - pct_wht, 5)

    maj_blk  = pct_blk  > MAJORITY_THRESHOLD
    maj_wht  = pct_wht  > MAJORITY_THRESHOLD
    maj_hsp  = pct_hsp  > MAJORITY_THRESHOLD
    maj_coal = pct_min_coalition > MAJORITY_THRESHOLD

    df = pd.DataFrame({
        "plan_id":                     plan_id,
        "draw":                        draw_flat.astype(np.int32),
        "district":                    dist_flat.astype(np.int32),
        "cvap_tot":                    tot_flat,
        "cvap_blk":                    blk_flat,
        "cvap_hsp":                    hsp_flat,
        "cvap_wht":                    wht_flat,
        "cvap_asn":                    asn_flat,
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
    ap.add_argument("--cvap-file", default=None, dest="cvap_file",
                    help="Path to cvap_vtd.parquet. "
                         "Defaults to {data_dir}/cvap_vtd.parquet.")
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

    cvap_file = (
        Path(args.cvap_file).resolve()
        if args.cvap_file
        else data_dir / "cvap_vtd.parquet"
    )
    out_file = (
        Path(args.out_file).resolve()
        if args.out_file
        else data_dir / "ensemble" / f"{args.run_name}_demographics.parquet"
    )

    # ── Run pipeline ─────────────────────────────────────────────────────────
    plan_np, geoids, n_districts = load_plan_matrix(plans_path)
    cvap_np                      = load_cvap(geoids, cvap_file)
    df                           = score_demographics(plan_np, cvap_np, n_districts, args.run_name)

    # ── Print enacted plan summary (draw=1) ──────────────────────────────────
    enacted = df[df.draw == 1].copy()
    print(f"\nEnacted plan demographics (draw=1) — {n_districts} districts:")
    print(f"  Majority Black             : {enacted.majority_black.sum()}")
    print(f"  Majority White             : {enacted.majority_white.sum()}")
    print(f"  Majority Hispanic          : {enacted.majority_hispanic.sum()}")
    print(f"  Majority Minority Coalition: {enacted.majority_minority_coalition.sum()}")

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
