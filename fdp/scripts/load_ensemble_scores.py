#!/usr/bin/env python3
"""
Load a scored GerryChain ensemble into Postgres.

Expects:
  - fdp/data/repos/main/ensemble/{run_name}_scores.parquet
  - fdp/data/repos/main/ensemble/{run_name}_demographics.parquet

Inserts into:
  - fdp.ensemble_scores
  - analytics.ensemble_demographic_scores
  - fdp.ensemble_runs (catalog record)

Then refreshes the analytics materialized views.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path

import pandas as pd
import psycopg

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = SCRIPT_DIR.parent / "data" / "repos" / "main"
# Default to the Supabase shared/dashboard target (session pooler, IPv4-compatible).
# Override with the POSTGRES_DSN environment variable or --dsn.
DEFAULT_DSN = (
    "postgresql://postgres.jzhxmnjmigfhggzfcwkv:fairdistrictsGA2026!"
    "@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
)


def load(
    run_name: str,
    data_dir: Path,
    dsn: str,
) -> None:
    scores_path = data_dir / "ensemble" / f"{run_name}_scores.parquet"
    demo_path = data_dir / "ensemble" / f"{run_name}_demographics.parquet"

    if not scores_path.exists():
        raise FileNotFoundError(scores_path)
    if not demo_path.exists():
        raise FileNotFoundError(demo_path)

    print(f"Loading {run_name} into Postgres ...")
    scores_df = pd.read_parquet(scores_path)
    demo_df = pd.read_parquet(demo_path)

    with psycopg.connect(dsn) as conn:
        conn.autocommit = True
        cur = conn.cursor()

        cur.execute("CREATE SCHEMA IF NOT EXISTS analytics")

        # Idempotent: delete any existing rows for this run
        cur.execute(
            "DELETE FROM analytics.ensemble_demographic_scores WHERE plan_id = %s",
            (run_name,),
        )
        cur.execute(
            "DELETE FROM fdp.ensemble_scores WHERE plan_id = %s",
            (run_name,),
        )

        # Scores
        score_cols = [
            "plan_id", "draw", "district", "year", "election_type", "office",
            "dem_votes", "rep_votes", "total_votes", "dem_2pv", "winner", "loaded_by",
        ]
        # Ensure all columns exist (loaded_by may be missing in some outputs)
        for c in score_cols:
            if c not in scores_df.columns:
                scores_df[c] = None
        records = scores_df[score_cols].values.tolist()
        cur.executemany(
            """
            INSERT INTO fdp.ensemble_scores
            (plan_id, draw, district, year, election_type, office,
             dem_votes, rep_votes, total_votes, dem_2pv, winner, loaded_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            records,
        )
        print(f"  inserted {len(records):,} score rows")

        # Demographics
        demo_cols = [
            "plan_id", "draw", "district", "bvap_tot", "bvap_blk", "bvap_hsp",
            "bvap_wht", "bvap_asn", "pct_black", "pct_hispanic", "pct_white",
            "pct_asian", "pct_minority_coalition", "majority_black",
            "majority_white", "majority_hispanic", "majority_minority_coalition",
        ]
        demo_records = demo_df[demo_cols].values.tolist()
        cur.executemany(
            """
            INSERT INTO analytics.ensemble_demographic_scores
            (plan_id, draw, district, bvap_tot, bvap_blk, bvap_hsp,
             bvap_wht, bvap_asn, pct_black, pct_hispanic, pct_white,
             pct_asian, pct_minority_coalition, majority_black,
             majority_white, majority_hispanic, majority_minority_coalition)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            demo_records,
        )
        print(f"  inserted {len(demo_records):,} demographic rows")

        # Catalog record
        n_draws = int(scores_df["draw"].max())
        n_vtds = int(scores_df["district"].nunique())  # actually n_districts; n_vtds is 2698
        cur.execute(
            """
            INSERT INTO fdp.ensemble_runs
            (run_name, benchmark_id, status, started_at, completed_at,
             params, n_draws, n_vtds, n_chains_run, plans_file,
             scores_file, demographics_file, loaded_by)
            VALUES (%s, %s, 'completed', NOW(), NOW(), %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_name) DO UPDATE SET
                benchmark_id = EXCLUDED.benchmark_id,
                status = 'completed',
                completed_at = NOW(),
                params = EXCLUDED.params,
                n_draws = EXCLUDED.n_draws,
                n_vtds = EXCLUDED.n_vtds,
                n_chains_run = EXCLUDED.n_chains_run,
                plans_file = EXCLUDED.plans_file,
                scores_file = EXCLUDED.scores_file,
                demographics_file = EXCLUDED.demographics_file,
                loaded_by = EXCLUDED.loaded_by,
                updated_at = NOW()
            """,
            (
                run_name,
                run_name,
                json.dumps({"loaded_at": datetime.datetime.now().isoformat()}),
                n_draws,
                2698,
                1,
                str(data_dir / "ensemble" / f"{run_name}_plans.parquet"),
                str(scores_path),
                str(demo_path),
                "load_ensemble_scores.py",
            ),
        )
        print(f"  registered run '{run_name}'")

        # Refresh materialized views
        for mv in (
            "analytics.agg_sim_partisan_outcomes",
            "analytics.agg_sim_competitiveness",
            "analytics.agg_sim_minority_representation",
        ):
            cur.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {mv}")
            print(f"  refreshed {mv}")

    print("\nDone. Analytics materialized views are populated.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--data-dir", default=DEFAULT_DATA_DIR, type=Path)
    ap.add_argument("--dsn", default=os.getenv("POSTGRES_DSN", DEFAULT_DSN))
    args = ap.parse_args()
    load(args.run_name, args.data_dir, args.dsn)


if __name__ == "__main__":
    main()
