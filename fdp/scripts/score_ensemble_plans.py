#!/usr/bin/env python3
"""
Score an ensemble plan file against elections in Supabase.

Algorithm (vectorised numpy — no Python loops over draws):
  1. Load plan assignments parquet → pivot to (n_vtds × n_draws) matrix
  2. Pull election_results from Supabase → pivot to (n_vtds × N_race_parties)
  3. For each district: boolean mask × matrix-multiply → (n_draws × N_race_parties)
  4. Reshape to long-format DataFrame, compute 2pv and winner
  5. Upsert to fdp.ensemble_scores

Usage (from fgdp/ root):
    # Score a Modal run (download parquet first):
    modal volume get fdga-chain-data /ensemble/my_run_plans.parquet .
    uv run --project fdp python fdp/scripts/score_ensemble_plans.py \\
        --run-name my_run \\
        --plans-file my_run_plans.parquet

    # Legacy: score the original ALARM 5001-plan ensemble (hardcoded path):
    uv run --project fdp python fdp/scripts/score_ensemble_plans.py
    uv run --project fdp python fdp/scripts/score_ensemble_plans.py --dry-run
    uv run --project fdp python fdp/scripts/score_ensemble_plans.py --races governor senate president
"""
from __future__ import annotations

import argparse
import io
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

# ── Config ─────────────────────────────────────────────────────────────────

# Legacy defaults (used when --run-name / --plans-file are not provided)
_DEFAULT_PARQUET = (
    Path(__file__).resolve().parent.parent
    / "data/repos/main/ensemble/ga_congress_2020_alarm_5001_plans.parquet"
)
_DEFAULT_PLAN_ID = "ga_congress_2020_alarm_5001"
LOADED_BY = "score_ensemble_plans.py"

# Set by main() from CLI args; used throughout
PLANS_PARQUET: Path = _DEFAULT_PARQUET
PLAN_ID:       str  = _DEFAULT_PLAN_ID
N_DISTRICTS:   int  = 14   # overridden after loading the parquet

DB_URL = os.environ.get("DATABASE_URL")
if not DB_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set.\n"
        "  export DATABASE_URL='postgresql://postgres.xxx:password@...pooler.supabase.com:5432/postgres'"
    )


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


# ── Stage 2 — Load election results ────────────────────────────────────────

def load_elections(geoids: list[str], race_filter: list[str] | None) -> tuple[np.ndarray, list[tuple]]:
    """
    Pull dem + rep votes from Supabase and return:
      - elec_np:  (n_vtds, 2*N_races) float64 matrix
      - races:    list of (year, election_type, office) tuples, one per pair of cols
    Column order: race0_dem, race0_rep, race1_dem, race1_rep, …
    """
    # Always restrict to priority races unless caller explicitly overrides
    PRIORITY_OFFICES = ("president", "governor", "senate", "us-house", "state-rep")
    effective_filter = race_filter if race_filter else list(PRIORITY_OFFICES)
    placeholders = ", ".join(f"'{r}'" for r in effective_filter)
    office_filter = f"AND office IN ({placeholders})"

    print("\nPulling election results from Supabase …")
    with psycopg.connect(DB_URL) as conn:
        rows = conn.execute(f"""
            SELECT geoid, year, election_type, office, party, votes
            FROM fdp.election_results
            WHERE geo_level = 'vtd'
              AND party IN ('dem', 'rep')
              {office_filter}
            ORDER BY geoid, year, election_type, office, party
        """).fetchall()

    df = pd.DataFrame(rows, columns=["geoid","year","election_type","office","party","votes"])

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
    # Shape: (14, 5001, 2*n_races)
    all_district_votes = np.empty((N_DISTRICTS, n_draws, n_races * 2), dtype=np.int64)

    for d_idx, district in enumerate(range(1, N_DISTRICTS + 1)):
        # mask: (n_vtds, n_draws) bool
        mask = (plan_np == district)
        # Matrix multiply: (n_draws, n_vtds) @ (n_vtds, 2*n_races) = (n_draws, 2*n_races)
        all_district_votes[d_idx] = mask.T.astype(np.int64) @ elec_np
        if (d_idx + 1) % 5 == 0:
            print(f"  District {district:2d}/14 done …")

    print(f"  Matrix math done in {time.time()-t0:.1f}s")

    # ── Build long-format DataFrame ─────────────────────────────────────────
    records = []
    draws_arr     = np.arange(1, n_draws + 1)            # (5001,)
    districts_arr = np.arange(1, N_DISTRICTS + 1)        # (14,)

    for race_idx, (year, etype, office) in enumerate(races):
        dem_col_idx = race_idx * 2
        rep_col_idx = race_idx * 2 + 1

        # dem_mat[d_idx, draw_idx], rep_mat same — shape (14, 5001)
        dem_mat   = all_district_votes[:, :, dem_col_idx]
        rep_mat   = all_district_votes[:, :, rep_col_idx]
        total_mat = dem_mat + rep_mat

        with np.errstate(invalid="ignore", divide="ignore"):
            d2pv_mat = np.where(total_mat > 0, dem_mat / total_mat, np.nan)

        # Flatten: (14 × 5001,) arrays
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
        print(f"  Race {race_idx+1:2d}/{n_races}: {year} {etype} {office}  "
              f"— enacted dem seats: "
              f"{(race_df[race_df.draw==1]['winner']=='dem').sum()}/14")

    scores = pd.concat(records, ignore_index=True)
    print(f"\nScored {len(scores):,} rows total in {time.time()-t0:.1f}s")
    return scores


# ── Stage 4 — Upsert to Supabase ──────────────────────────────────────────

def upsert_scores(scores: pd.DataFrame, batch_size: int = 100_000) -> None:
    PK = ["plan_id","draw","district","year","election_type","office"]
    update_cols = [c for c in scores.columns if c not in PK and
                   c not in {"created_at","updated_at","update_count","loaded_at"}]
    col_names  = ", ".join(f'"{c}"' for c in scores.columns)
    pk_str     = ", ".join(f'"{c}"' for c in PK)
    update_str = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)

    total      = len(scores)
    n_batches  = (total + batch_size - 1) // batch_size
    total_rows = 0
    t0         = time.time()
    print(f"\nUpserting {total:,} rows in {n_batches} batches …")

    with psycopg.connect(DB_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SET SESSION default_transaction_read_only = off")

        for i in range(n_batches):
            batch = scores.iloc[i * batch_size : (i + 1) * batch_size]
            buf   = io.StringIO()
            batch.to_csv(buf, index=False, na_rep="\\N")
            buf.seek(0); buf.readline()

            with conn.cursor() as cur:
                cur.execute("BEGIN READ WRITE")
                cur.execute(
                    "CREATE TEMP TABLE IF NOT EXISTS _tmp_scores "
                    "(LIKE fdp.ensemble_scores INCLUDING DEFAULTS)"
                )
                cur.execute("TRUNCATE _tmp_scores")
                with cur.copy(
                    f"COPY _tmp_scores ({col_names}) FROM STDIN (FORMAT CSV, NULL '\\N')"
                ) as copy:
                    copy.write(buf.read())
                cur.execute(
                    f"INSERT INTO fdp.ensemble_scores ({col_names}) "
                    f"SELECT {col_names} FROM _tmp_scores "
                    f"ON CONFLICT ({pk_str}) DO UPDATE SET {update_str}"
                )
                n = cur.rowcount
                cur.execute("COMMIT")

            total_rows += n
            elapsed = time.time() - t0
            rate    = total_rows / elapsed if elapsed > 0 else 0
            eta     = (total - total_rows) / rate if rate > 0 else 0
            print(f"  Batch {i+1:>3}/{n_batches}  "
                  f"{total_rows:>9,}/{total:,}  "
                  f"({100*total_rows/total:5.1f}%)  "
                  f"{rate:,.0f} rows/s  ETA {eta/60:.1f} min")

    elapsed = time.time() - t0
    print(f"\n✓ {total_rows:,} rows in {elapsed/60:.1f} min")


# ── Main ──────────────────────────────────────────────────────────────────

def main() -> None:
    global PLANS_PARQUET, PLAN_ID

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-name", default=None,
                    help="Run name (becomes plan_id in ensemble_scores). "
                         "Defaults to the legacy ALARM plan ID.")
    ap.add_argument("--plans-file", default=None, dest="plans_file",
                    help="Path to the plans parquet file. "
                         "Defaults to the legacy ALARM parquet path.")
    ap.add_argument("--config", default=None,
                    help="(Ignored for now — reserved for future election filtering from YAML.)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Compute scores but do not write to Supabase")
    ap.add_argument("--races", nargs="*", default=None,
                    help="Score only these offices (e.g. governor senate president)")
    ap.add_argument("--batch-size", type=int, default=100_000,
                    help="Rows per upsert batch (default: 100,000)")
    args = ap.parse_args()

    # Override globals from CLI
    if args.run_name:
        PLAN_ID = args.run_name
    if args.plans_file:
        PLANS_PARQUET = Path(args.plans_file).resolve()

    if not PLANS_PARQUET.exists():
        print(f"ERROR: plans file not found: {PLANS_PARQUET}")
        print("  Download from Modal volume first:")
        print(f"    modal volume get fdga-chain-data /ensemble/{PLAN_ID}_plans.parquet .")
        import sys; sys.exit(1)

    plan_np, geoids = load_plan_matrix(args.races)
    elec_np, races  = load_elections(geoids, args.races)
    scores          = score_plans(plan_np, elec_np, races)

    if args.dry_run:
        print("\n[dry-run] Skipping upsert.")
        print(scores.head(10).to_string())
        return

    upsert_scores(scores, batch_size=args.batch_size)

    # Quick validation
    print("\nValidation — enacted plan seat counts:")
    with psycopg.connect(DB_URL) as conn:
        rows = conn.execute("""
            SELECT year, office, enacted_dem_seats, enacted_rep_seats,
                   ROUND(median_dem_seats,1) AS median_sim, enacted_pctile, princeton_grade
            FROM fdp.v_ensemble_vs_enacted
            ORDER BY year, office
        """).fetchall()
        print(f"  {'Year':<6} {'Office':<30} {'Enacted':>8} {'Median':>8} "
              f"{'Pctile':>8} {'Grade'}")
        print("  " + "-"*70)
        for r in rows:
            print(f"  {r[0]:<6} {r[2]:<30} "
                  f"D{r[2]:>2}/R{r[3]:>2}  {r[4]:>7}  {r[5]:>7}%  {r[6]}")


if __name__ == "__main__":
    main()
