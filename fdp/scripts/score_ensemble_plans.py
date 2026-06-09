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
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import yaml

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
    Read the plans parquet in batches and return:
      - plan_np:  (n_vtds, n_draws) int16 matrix of district assignments
      - geoids:   ordered list of VTD GEOIDs matching rows of plan_np

    Reads in 5M-row batches so PyArrow never holds all 243M rows simultaneously
    (~60MB peak per batch vs ~3GB for a full-table read). Eliminates the
    address-space fragmentation that caused OOM crashes during scoring.

    Also sets the global N_DISTRICTS from the data.
    """
    global N_DISTRICTS
    print(f"Loading plan matrix from {PLANS_PARQUET.name} …")

    pf = pq.ParquetFile(PLANS_PARQUET)
    BATCH = 5_000_000  # rows per batch — ~60MB of PyArrow memory at a time

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

    geoids   = sorted(all_geoids)
    geoid_np = pa.array(geoids)          # value_set for index_in
    n_vtds   = len(geoids)
    n_draws  = draws_max - draws_min + 1
    plan_np  = np.zeros((n_vtds, n_draws), dtype=np.int16)
    N_DISTRICTS = 0
    total_rows  = 0

    # Pass 2: fill plan_np in batches
    for batch in pf.iter_batches(batch_size=BATCH, columns=["geoid", "draw", "district"]):
        row_idx = (pc.index_in(batch.column("geoid"), value_set=geoid_np)
                   .to_numpy(zero_copy_only=False).astype(np.int32))
        col_idx = (batch.column("draw").to_numpy() - draws_min).astype(np.int32)
        vals    = batch.column("district").to_numpy().astype(np.int16)
        N_DISTRICTS = max(N_DISTRICTS, int(vals.max()))
        plan_np[row_idx, col_idx] = vals
        total_rows += len(batch)

    print(f"  Read {total_rows:,} rows  (batched, ~60MB peak per batch)")
    print(f"  {n_vtds:,} VTDs × {n_draws:,} draws  ({N_DISTRICTS} districts)")
    return plan_np, geoids


# ── Stage 2 — Load election results from Parquet ───────────────────────────

def load_elections(
    geoids: list[str],
    race_filter: list[str] | None,
    elections_file: Path,
    config_race_keys: list[tuple] | None = None,
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
    PRIORITY_OFFICES = ("president", "governor", "senate", "us-house", "state-rep", "composite")

    print(f"\nLoading election results from {elections_file.name} …")
    df = pd.read_parquet(elections_file)

    # Filter to relevant offices and dem/rep only.
    # config_race_keys uses row-wise apply (slightly slower than .isin) because
    # it must match on (year, election_type, office) tuples together, not each column alone.
    if config_race_keys:
        # Config-driven: exact (year, election_type, office) tuples
        race_set = {(y, t, o) for y, t, o in config_race_keys}
        df = df[
            df["party"].isin(["dem", "rep"]) &
            df.apply(
                lambda r: (int(r["year"]), r["election_type"], r["office"]) in race_set,
                axis=1,
            )
        ]
    elif race_filter:
        df = df[df["party"].isin(["dem", "rep"]) & df["office"].isin(race_filter)]
    else:
        df = df[df["party"].isin(["dem", "rep"]) & df["office"].isin(list(PRIORITY_OFFICES))]

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

def score_plans(
    plan_np: np.ndarray,
    elec_np: np.ndarray,
    races: list[tuple],
    out_path: Path,
    dry_run: bool = False,
) -> int:
    """
    For each district, compute per-draw vote totals then stream each race to Parquet.

    Streams one race at a time to keep peak memory under ~2GB (vs 8+ GB for full concat).
    Returns total row count written.

    plan_np:  (n_vtds, n_draws)   int16   — district assignment per VTD per draw
    elec_np:  (n_vtds, 2*N_races) int64   — dem/rep votes per VTD per race
    """
    n_vtds, n_draws = plan_np.shape
    n_races = len(races)
    print(f"\nScoring {n_draws:,} draws × {N_DISTRICTS} districts × {n_races} races …")
    t0 = time.time()

    elec_f32 = elec_np.astype(np.float32)

    # scores[district_idx, draw_idx, race_col] = total votes in that district/draw
    all_district_votes = np.empty((N_DISTRICTS, n_draws, n_races * 2), dtype=np.float32)

    # Pre-allocate all working buffers ONCE.
    # plan_np_T: C-contiguous transpose — avoids numpy creating a 486MB internal copy
    # on each np.equal call (plan_np.T is Fortran-order/non-contiguous).
    # bool_buf + float_buf: reused each district so the 970MB alloc happens once, not 56×.
    plan_np_T = np.ascontiguousarray(plan_np.T)           # (n_draws, n_vtds) int16 ~486MB
    bool_buf  = np.empty((n_draws, n_vtds), dtype=np.bool_)    # 242MB
    float_buf = np.empty((n_draws, n_vtds), dtype=np.float32)  # 970MB

    for d_idx, district in enumerate(range(1, N_DISTRICTS + 1)):
        np.equal(plan_np_T, district, out=bool_buf)
        np.copyto(float_buf, bool_buf, casting="unsafe")
        all_district_votes[d_idx] = float_buf @ elec_f32
        if (d_idx + 1) % 5 == 0:
            print(f"  District {district:2d}/{N_DISTRICTS} done …", flush=True)

    plan_np_T = bool_buf = float_buf = elec_f32 = None

    del plan_np  # free ~500MB before building DataFrames
    print(f"  Matrix math done in {time.time()-t0:.1f}s", flush=True)

    draws_arr     = np.arange(1, n_draws + 1)
    districts_arr = np.arange(1, N_DISTRICTS + 1)
    dist_flat     = np.repeat(districts_arr, n_draws)
    draw_flat     = np.tile(draws_arr, N_DISTRICTS)

    total_rows = 0
    writer = None
    if not dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)

    for race_idx, (year, etype, office) in enumerate(races):
        dem_col_idx = race_idx * 2
        rep_col_idx = race_idx * 2 + 1

        dem_mat   = all_district_votes[:, :, dem_col_idx]
        rep_mat   = all_district_votes[:, :, rep_col_idx]
        total_mat = dem_mat + rep_mat

        with np.errstate(invalid="ignore", divide="ignore"):
            d2pv_flat = np.where(
                total_mat.ravel() > 0,
                dem_mat.ravel() / total_mat.ravel(),
                np.nan
            )

        winner_flat = np.where(
            np.isnan(d2pv_flat), "none",
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
            "dem_votes":     dem_mat.ravel().astype(np.int64),
            "rep_votes":     rep_mat.ravel().astype(np.int64),
            "total_votes":   total_mat.ravel().astype(np.int64),
            "dem_2pv":       np.round(d2pv_flat, 6),
            "winner":        winner_flat,
            "loaded_by":     LOADED_BY,
        })
        del total_mat, d2pv_flat, winner_flat  # free before next race

        enacted_dem = (race_df[race_df.draw == 1]["winner"] == "dem").sum()
        print(f"  Race {race_idx+1:2d}/{n_races}: {year} {etype} {office}  "
              f"— enacted dem seats: {enacted_dem}/{N_DISTRICTS}", flush=True)

        if not dry_run:
            tbl = pa.Table.from_pandas(race_df, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(out_path, tbl.schema)
            writer.write_table(tbl)
            del tbl
        total_rows += len(race_df)
        del race_df

    if writer:
        writer.close()

    print(f"\nScored {total_rows:,} rows total in {time.time()-t0:.1f}s", flush=True)
    return total_rows


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
                    help="Path to benchmark YAML config (e.g. fdp/configs/benchmarks/ga_congress_2026_v3.yml). "
                         "When provided, restricts scored elections to those listed in the config's elections: block "
                         "(by year, election_type, office). The composite election (year=0) is always included.")
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

    # When --config is provided, build race filter from YAML elections block
    config_race_keys: list[tuple] | None = None
    if args.config:
        cfg_path = Path(args.config)
        if not cfg_path.exists():
            print(f"ERROR: config file not found: {cfg_path}")
            import sys; sys.exit(1)
        cfg = yaml.safe_load(cfg_path.read_text())
        elections_cfg = cfg.get("elections", [])
        if elections_cfg:
            # Build (year, election_type, office) tuples from YAML
            config_race_keys = [
                (int(e["year"]), e.get("election_type", "general"), e["office"])
                for e in elections_cfg
            ]
            # Always include the composite election
            config_race_keys.append((0, "composite", "composite"))
            print(f"  Config {cfg_path.name}: filtering to {len(config_race_keys)-1} elections + composite")

    plan_np, geoids = load_plan_matrix(args.races)
    elec_np, races  = load_elections(geoids, args.races, elections_file, config_race_keys)
    n_rows = score_plans(plan_np, elec_np, races, out_file, dry_run=args.dry_run)

    if not args.dry_run:
        size_mb = out_file.stat().st_size / 1_000_000
        print(f"\n✓ {n_rows:,} rows → {out_file.name}  ({size_mb:.1f} MB)")
        print(f"\nNext step:")
        print(f"  uv run --project fdp python fdp/scripts/build_draw_stats.py \\")
        print(f"      --run-name {PLAN_ID} --config fdp/configs/benchmarks/<your_config>.yml")


if __name__ == "__main__":
    main()
