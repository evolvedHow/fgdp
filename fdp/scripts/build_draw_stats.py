#!/usr/bin/env python3
"""
build_draw_stats.py — Compute per-draw benchmark statistics from ensemble_scores.

Reads fdp.ensemble_scores for a given plan_id and computes per-draw rollups:
  - dem_seats, rep_seats (seat counts)
  - efficiency_gap, mean_median (partisan metrics)
  - n_competitive_007, n_competitive_010 (competitiveness)

All computation is pushed to PostgreSQL — no large data transfers.

Usage (from fgdp/ root):
    uv run --project fdp python fdp/scripts/build_draw_stats.py \\
        --run-name congress_2026_v1

    uv run --project fdp python fdp/scripts/build_draw_stats.py \\
        --run-name congress_2026_v1 --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import psycopg

DB_URL = os.environ.get("DATABASE_URL")


# ---------------------------------------------------------------------------
# SQL — all computation server-side
# ---------------------------------------------------------------------------

# Insert/upsert draw stats computed entirely from ensemble_scores
_DRAW_STATS_SQL = """
INSERT INTO fdp.ensemble_draw_stats (
    plan_id, draw, year, election_type, office,
    dem_seats, rep_seats, tied_seats,
    avg_dem_2pv, efficiency_gap, mean_median,
    n_competitive_007, n_competitive_010
)
SELECT
    plan_id,
    draw,
    year,
    election_type,
    office,

    COUNT(*) FILTER (WHERE winner = 'dem')  AS dem_seats,
    COUNT(*) FILTER (WHERE winner = 'rep')  AS rep_seats,
    COUNT(*) FILTER (WHERE winner = 'tie')  AS tied_seats,

    -- Average Dem two-party vote share across all districts in this draw
    ROUND(AVG(dem_2pv)::NUMERIC, 6)         AS avg_dem_2pv,

    -- Efficiency gap = (wasted_dem - wasted_rep) / total_votes
    -- wasted_dem: votes above 50%% threshold if Dem wins, or all Dem votes if Dem loses
    -- wasted_rep: votes above 50%% threshold if Rep wins, or all Rep votes if Rep loses
    ROUND((
        SUM(
            CASE WHEN winner = 'dem'
                 THEN dem_votes::numeric - total_votes::numeric / 2.0
                 ELSE dem_votes::numeric
            END
        )
        -
        SUM(
            CASE WHEN winner = 'rep'
                 THEN rep_votes::numeric - total_votes::numeric / 2.0
                 ELSE rep_votes::numeric
            END
        )
    ) / NULLIF(SUM(total_votes), 0)::numeric, 6) AS efficiency_gap,

    -- Mean-median difference: mean(dem_2pv) - median(dem_2pv)
    -- Positive = Democratic skew (votes more efficiently spread)
    -- Negative = Republican advantage
    ROUND((
        AVG(dem_2pv)
        - PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY dem_2pv)
    )::NUMERIC, 6)  AS mean_median,

    -- Competitive districts: win_margin = |dem_2pv - 0.5| * 2
    COUNT(*) FILTER (
        WHERE dem_2pv IS NOT NULL
          AND ABS(dem_2pv - 0.5) * 2 <= 0.07
    ) AS n_competitive_007,

    COUNT(*) FILTER (
        WHERE dem_2pv IS NOT NULL
          AND ABS(dem_2pv - 0.5) * 2 <= 0.10
    ) AS n_competitive_010

FROM fdp.ensemble_scores
WHERE plan_id = %s
GROUP BY plan_id, draw, year, election_type, office

ON CONFLICT (plan_id, draw, year, election_type, office) DO UPDATE SET
    dem_seats         = EXCLUDED.dem_seats,
    rep_seats         = EXCLUDED.rep_seats,
    tied_seats        = EXCLUDED.tied_seats,
    avg_dem_2pv       = EXCLUDED.avg_dem_2pv,
    efficiency_gap    = EXCLUDED.efficiency_gap,
    mean_median       = EXCLUDED.mean_median,
    n_competitive_007 = EXCLUDED.n_competitive_007,
    n_competitive_010 = EXCLUDED.n_competitive_010
"""

_COUNT_SQL = """
SELECT COUNT(*) FROM fdp.ensemble_scores WHERE plan_id = %s
"""

_VERIFY_SQL = """
SELECT
    COUNT(*)                                                    AS n_rows,
    COUNT(DISTINCT draw)                                        AS n_draws,
    COUNT(DISTINCT year || '_' || office)                       AS n_races,
    MIN(dem_seats)                                              AS min_dem,
    MAX(dem_seats)                                              AS max_dem,
    ROUND(AVG(dem_seats)::numeric, 2)                           AS avg_dem,
    ROUND(AVG(n_competitive_007)::numeric, 2)                   AS avg_competitive_7,
    ROUND(AVG(ABS(efficiency_gap))::numeric, 4)                 AS avg_abs_eg
FROM fdp.ensemble_draw_stats
WHERE plan_id = %s AND draw > 1
"""

_ENACTED_SQL = """
SELECT year, office, dem_seats, rep_seats,
       ROUND(efficiency_gap * 100, 2) AS eg_pct,
       n_competitive_007, n_competitive_010
FROM fdp.ensemble_draw_stats
WHERE plan_id = %s AND draw = 1
ORDER BY year, office
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--run-name", required=True,
                    help="plan_id to compute stats for (e.g. congress_2026_v1)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show row counts but do not write to Supabase")
    args = ap.parse_args()

    if not DB_URL:
        print("ERROR: DATABASE_URL not set.")
        sys.exit(1)

    plan_id = args.run_name

    # ── Check source data ────────────────────────────────────────────────────
    with psycopg.connect(DB_URL) as conn:
        row = conn.execute(_COUNT_SQL, (plan_id,)).fetchone()
        n_source = row[0] if row else 0

    if n_source == 0:
        print(f"ERROR: no rows in fdp.ensemble_scores for plan_id='{plan_id}'")
        print("  Run score_ensemble_plans.py first.")
        sys.exit(1)

    print(f"\nBuilding draw stats for: {plan_id}")
    print(f"  Source rows in ensemble_scores: {n_source:,}")

    if args.dry_run:
        print("\n[dry-run] Would execute INSERT...SELECT on PostgreSQL.")
        print("  SQL pushes all computation to the DB — no Python loops.")
        print(f"  Expected output: ~{n_source // 14:,} rows in ensemble_draw_stats")
        return

    # ── Compute + upsert (server-side SQL) ──────────────────────────────────
    print("\nRunning server-side computation…")
    t0 = time.time()

    with psycopg.connect(DB_URL) as conn:
        conn.execute("SET SESSION default_transaction_read_only = off")
        conn.execute("BEGIN READ WRITE")
        conn.execute(_DRAW_STATS_SQL, (plan_id,))
        conn.execute("COMMIT")

    elapsed = time.time() - t0
    print(f"  Done in {elapsed:.1f}s")

    # ── Verify ───────────────────────────────────────────────────────────────
    print("\nVerification:")
    with psycopg.connect(DB_URL) as conn:
        row = conn.execute(_VERIFY_SQL, (plan_id,)).fetchone()
        if row:
            print(f"  Rows written     : {row[0]:,}")
            print(f"  Draws            : {row[1]:,}")
            print(f"  Races            : {row[2]}")
            print(f"  Dem seats range  : {row[3]}–{row[4]}  (avg {row[5]})")
            print(f"  Avg competitive  : {row[6]} districts at 7%")
            print(f"  Avg |EG|         : {row[7]}")

    # ── Enacted plan summary ─────────────────────────────────────────────────
    print("\nEnacted plan stats (draw=1):")
    with psycopg.connect(DB_URL) as conn:
        rows = conn.execute(_ENACTED_SQL, (plan_id,)).fetchall()
    print(f"  {'Year':<6} {'Office':<12} {'Seats':>8} {'EG%':>7} {'Comp7':>6} {'Comp10':>7}")
    print("  " + "-" * 50)
    for r in rows:
        print(f"  {r[0]:<6} {r[1]:<12} D{r[2]}/R{r[3]}  {r[4]:>6}%  {r[5]:>5}  {r[6]:>6}")

    print(f"\n✓ Done. Query distributions:")
    print(f"  SELECT * FROM fdp.v_partisan_distribution WHERE plan_id = '{plan_id}';")
    print(f"  SELECT * FROM fdp.v_enacted_vs_benchmark WHERE plan_id = '{plan_id}';")
    print(f"  SELECT * FROM fdp.v_correlation_competitive_partisan WHERE plan_id = '{plan_id}';")


if __name__ == "__main__":
    main()
