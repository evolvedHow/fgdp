#!/usr/bin/env python3
"""
Score an ensemble plan file against local election Parquet data.

Algorithm (vectorised numpy — no Python loops over draws):
  1. Load plan assignments parquet → pivot to (n_vtds × n_draws) matrix
  2. Load election_results_vtd.parquet → pivot to (n_vtds × N_race_parties) matrix
  3. For each district: boolean mask × matrix-multiply → (n_draws × N_race_parties)
  4. Reshape to long-format DataFrame, compute 2pv and winner
  5. Write to {run_name}_scores.parquet

Requires: export_supabase_to_parquet.py must have been run once to produce
          election_results_vtd.parquet in the data directory.

Usage (from fgdp/ root):
    # Score a Modal run (download parquet first):
    modal volume get fdga-chain-data /ensemble/congress_2026_v2_plans.parquet .
    uv run --project fdp python fdp/scripts/score_ensemble_plans.py \\
        --run-name congress_2026_v2 \\
        --plans-file congress_2026_v2_plans.parquet

    # Dry run (score but don't write output):
    uv run --project fdp python fdp/scripts/score_ensemble_plans.py \\
        --run-name congress_2026_v2 \\
        --plans-file congress_2026_v2_plans.parquet \\
        --dry-run

    # Filter to specific races:
    uv run --project fdp python fdp/scripts/score_ensemble_plans.py \\
        --run-name congress_2026_v2 \\
        --plans-file congress_2026_v2_plans.parquet \\
        --races governor senate president
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd

# ── Config ─────────────────────────────────────────────────────────────────

_SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = _SCRIPT_DIR.parent / "data/repos/main"

# Legacy defaults (used when --run-name / --plans-file are not provided)
_DEFAULT_PARQUET = DEFAULT_DATA_DIR / "ensemble/ga_congress_2020_alarm_5001_plans.parquet"
_DEFAULT_PLAN_ID = "ga_congress_2020_alarm_5001"
LOADED_BY = "score_ensemble_plans.py"

# Set by main() from CLI args; used throughout
PLANS_PARQUET: Path = _DEFAULT_PARQUET
PLAN_ID:       str  = _DEFAULT_PLAN_ID
N_DISTRICTS:   int  = 14   # overridden after loading the parquet


# ── Stage 1 — Load plan matrix ─────────────────────────────────────────────

def load_plan_matrix(race_filter: list[str] | None) -> tuple[np.ndarray, list[str]]:
    """
    Read the plans parquet and return:
      - plan_np:  (n_vtds, n_draws) int16 matrix of district assignments
      - geoids:   ordered list of VTD GEOIDs matching rows of plan_np

    Also sets the global N_DISTRICTS from the data.
    """
    global N_DISTRICTS
    print(f"Loading plan matrix from {PLANS_PARQUET.name} …")
    plans = pd.read_parquet(PLANS_PARQUET, columns=["geoid", "draw", "district"])
    plan_mat = plans.pivot(index="geoid", columns="draw", values="district")
    plan_np  = plan_mat.values.astype(np.int16)
    geoids   = list(plan_mat.index)
    n_vtds, n_draws = plan_np.shape
    N_DISTRICTS = int(plan_np.max())
    print(f"  {n_vtds:,} VTDs × {n_draws:,} draws  "
          f"({N_DISTRICTS} districts)")
    return plan_np, geoids


# ── Stage 2 — Load election results from Parquet ───────────────────────────

def load_elections(
    geoids: list[str],
    race_filter: list[str] | None,
    elections_file: Path,
) -> tuple[np.ndarray, list[tuple]]:
    """
    Load election results from local Parquet and return:
      - elec_np:  (n_vtds, 2*N_races) float64 matrix
      - races:    list of (year, election_type, office) tuples, one per pair of cols
    Column order: race0_dem, race0_rep, race1_dem, race1_rep, …

    elections_file: path to election_results_vtd.parquet produced by
                    export_supabase_to_parquet.py.
    """
    if not elections_file.exists():
        raise FileNotFoundError(
            f"Election results Parquet not found: {elections_file}\n"
            "  Run export_supabase_to_parquet.py first:\n"
            "    DATABASE_URL='...' uv run --project fdp "
            "python fdp/scripts/export_supabase_to_parquet.py"
        )

    # Always restrict to priority races unless caller explicitly overrides
    PRIORITY_OFFICES = ("president", "governor", "senate", "us-house", "state-rep")
    effective_filter = race_filter if race_filter else list(PRIORITY_OFFICES)

    print(f"\nLoading election results from {elections_file.name} …")
    df = pd.read_parquet(elections_file)

    # Filter to priority offices and dem/rep only
    df = df[
        df["party"].isin(["dem", "rep"]) &
        df["office"].isin(effective_filter)
    ]

    # Identify unique races
    races = (df[["year","election_type","office"]]
             .drop_duplicates()
             .sort_values(["year","office"])
             .itertuples(index=False, name=None))
    races = list(races)
    print(f"  {len(df):,} rows  |  {len(races)} races  |  "
          f"{df['geoid'].nunique():,} VTDs")

    # Build wide matrix: rows=geoid (in geoids order), cols=race_dem, race_rep alternating
    geoid_index = {g: i for i, g in enumerate(geoids)}
    n_vtds   = len(geoids)
    n_cols   = len(races) * 2
    elec_np  = np.zeros((n_vtds, n_cols), dtype=np.int64)

    for race_idx, (year, etype, office) in enumerate(races):
        dem_col = race_idx * 2
        rep_col = race_idx * 2 + 1
        subset  = df[(df.year==year) & (df.election_type==etype) & (df.office==office)]
        for _, row in subset.iterrows():
            vtd_idx = geoid_index.get(row.geoid)
            if vtd_idx is None:
                continue
            if row.party == "dem":
                elec_np[vtd_idx, dem_col] = int(row.votes)
            else:
                elec_np[vtd_idx, rep_col] = int(row.votes)

    print(f"  Election matrix: {elec_np.shape}")
    return elec_np, races


# ── Stage 3 — Vectorised scoring ──────────────────────────────────────────

def score_plans(plan_np: np.ndarray, elec_np: np.ndarray, races: list[tuple]) -> pd.DataFrame:
    """
    For each of N_DISTRICTS districts, compute per-draw vote totals via matrix multiply.

    plan_np:  (n_vtds, n_draws)   int8    — district assignment per VTD per draw
    elec_np:  (n_vtds, 2*N_races) int64   — dem/rep votes per VTD per race
    """
    n_vtds, n_draws = plan_np.shape
    n_races = len(races)
    print(f"\nScoring {n_draws:,} draws × {N_DISTRICTS} districts × {n_races} races …")
    t0 = time.time()

    # scores[district_idx, draw_idx, race_col] = total votes in that district/draw
    all_district_votes = np.empty((N_DISTRICTS, n_draws, n_races * 2), dtype=np.int64)

    for d_idx, district in enumerate(range(1, N_DISTRICTS + 1)):
        # mask: (n_vtds, n_draws) bool
        mask = (plan_np == district)
        # Matrix multiply: (n_draws, n_vtds) @ (n_vtds, 2*n_races) = (n_draws, 2*n_races)
        all_district_votes[d_idx] = mask.T.astype(np.int64) @ elec_np
        if (d_idx + 1) % 5 == 0:
            print(f"  District {district:2d}/{N_DISTRICTS} done …")

    print(f"  Matrix math done in {time.time()-t0:.1f}s")

    # ── Build long-format DataFrame ─────────────────────────────────────────
    records = []
    draws_arr     = np.arange(1, n_draws + 1)
    districts_arr = np.arange(1, N_DISTRICTS + 1)

    for race_idx, (year, etype, office) in enumerate(races):
        dem_col_idx = race_idx * 2
        rep_col_idx = race_idx * 2 + 1

        dem_mat   = all_district_votes[:, :, dem_col_idx]
        rep_mat   = all_district_votes[:, :, rep_col_idx]
        total_mat = dem_mat + rep_mat

        with np.errstate(invalid="ignore", divide="ignore"):
            d2pv_mat = np.where(total_mat > 0, dem_mat / total_mat, np.nan)

        dist_flat  = np.repeat(districts_arr, n_draws)
        draw_flat  = np.tile(draws_arr, N_DISTRICTS)
        dem_flat   = dem_mat.ravel()
        rep_flat   = rep_mat.ravel()
        tot_flat   = total_mat.ravel()
        d2pv_flat  = d2pv_mat.ravel()

        winner_flat = np.where(
            np.isnan(d2pv_flat), None,
            np.where(d2pv_flat > 0.5, "dem",
            np.where(d2pv_flat < 0.5, "rep", "tie"))
        )

        race_df = pd.DataFrame({
            "plan_id":       PLAN_ID,
            "draw":          draw_flat,
            "district":      dist_flat,
            "year":          int(year),
            "election_type": etype,
            "office":        office,
            "dem_votes":     dem_flat,
            "rep_votes":     rep_flat,
            "total_votes":   tot_flat,
            "dem_2pv":       np.round(d2pv_flat, 6),
            "winner":        winner_flat,
            "loaded_by":     LOADED_BY,
        })
        records.append(race_df)
        enacted_row = race_df[race_df.draw == 1]
        enacted_dem = (enacted_row["winner"] == "dem").sum()
        print(f"  Race {race_idx+1:2d}/{n_races}: {year} {etype} {office}  "
              f"— enacted dem seats: {enacted_dem}/{N_DISTRICTS}")

    scores = pd.concat(records, ignore_index=True)
    print(f"\nScored {len(scores):,} rows total in {time.time()-t0:.1f}s")
    return scores


# ── Stage 4 — Save to Parquet ─────────────────────────────────────────────

def save_scores(scores: pd.DataFrame, out_path: Path) -> None:
    """Write scored ensemble to Parquet (replaces Supabase upsert)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    scores.to_parquet(out_path, index=False)
    size_mb = out_path.stat().st_size / 1_000_000
    print(f"\n✓ {len(scores):,} rows → {out_path.name}  ({size_mb:.1f} MB)")


# ── Main ──────────────────────────────────────────────────────────────────

def main() -> None:
    global PLANS_PARQUET, PLAN_ID

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-name", default=None,
                    help="Run name (becomes plan_id in output). "
                         "Defaults to the legacy ALARM plan ID.")
    ap.add_argument("--plans-file", default=None, dest="plans_file",
                    help="Path to the plans parquet file. "
                         "Defaults to {data_dir}/ensemble/{run_name}_plans.parquet.")
    ap.add_argument("--data-dir", default=None,
                    help=f"Root data directory (default: {DEFAULT_DATA_DIR})")
    ap.add_argument("--elections-file", default=None, dest="elections_file",
                    help="Path to election_results_vtd.parquet. "
                         "Defaults to {data_dir}/election_results_vtd.parquet.")
    ap.add_argument("--out-file", default=None, dest="out_file",
                    help="Path to write scores Parquet. "
                         "Defaults to {data_dir}/ensemble/{run_name}_scores.parquet.")
    ap.add_argument("--config", default=None,
                    help="(Ignored — reserved for future election filtering from YAML.)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Compute scores but do not write output")
    ap.add_argument("--races", nargs="*", default=None,
                    help="Score only these offices (e.g. governor senate president)")
    args = ap.parse_args()

    # Resolve data directory
    data_dir = Path(args.data_dir) if args.data_dir else DEFAULT_DATA_DIR

    # Override globals from CLI
    if args.run_name:
        PLAN_ID = args.run_name
    if args.plans_file:
        PLANS_PARQUET = Path(args.plans_file).resolve()
    elif args.run_name:
        PLANS_PARQUET = data_dir / "ensemble" / f"{PLAN_ID}_plans.parquet"

    elections_file = (
        Path(args.elections_file).resolve()
        if args.elections_file
        else data_dir / "election_results_vtd.parquet"
    )
    out_file = (
        Path(args.out_file).resolve()
        if args.out_file
        else data_dir / "ensemble" / f"{PLAN_ID}_scores.parquet"
    )

    if not PLANS_PARQUET.exists():
        print(f"ERROR: plans file not found: {PLANS_PARQUET}")
        print("  Download from Modal volume first:")
        print(f"    modal volume get fdga-chain-data /ensemble/{PLAN_ID}_plans.parquet .")
        import sys; sys.exit(1)

    plan_np, geoids = load_plan_matrix(args.races)
    elec_np, races  = load_elections(geoids, args.races, elections_file)
    scores          = score_plans(plan_np, elec_np, races)

    if args.dry_run:
        print("\n[dry-run] Skipping write.")
        print(scores.head(10).to_string())
        return

    save_scores(scores, out_file)
    print(f"\nNext step:")
    print(f"  uv run --project fdp python fdp/scripts/build_draw_stats.py \\")
    print(f"      --run-name {PLAN_ID} --config fdp/configs/benchmarks/<your_config>.yml")


if __name__ == "__main__":
    main()
