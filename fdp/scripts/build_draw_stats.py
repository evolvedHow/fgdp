#!/usr/bin/env python3
"""
build_draw_stats.py — Compute per-draw benchmark statistics from ensemble_scores.

Reads fdp.ensemble_scores for a given plan_id and computes:

  ensemble_draw_stats        — one row per (plan_id, draw, year, office):
      dem_seats, rep_seats, tied_seats, avg_dem_2pv,
      efficiency_gap, mean_median

  ensemble_competitive_counts — one row per (plan_id, draw, year, office, threshold):
      n_competitive

All heavy computation is pushed to PostgreSQL — no large data transfers.

Thresholds come from --thresholds or --config (YAML). If neither is provided
the script refuses to write competitive counts (partisan stats are still built).

Usage (from fgdp/ root):
    uv run --project fdp python fdp/scripts/build_draw_stats.py \\
        --run-name congress_2026_v2 \\
        --config fdp/configs/benchmarks/ga_congress_2026_v2.yml

    # Or pass thresholds explicitly:
    uv run --project fdp python fdp/scripts/build_draw_stats.py \\
        --run-name congress_2026_v1 --thresholds 0.05 0.07

    uv run --project fdp python fdp/scripts/build_draw_stats.py \\
        --run-name congress_2026_v2 --dry-run \\
        --config fdp/configs/benchmarks/ga_congress_2026_v2.yml
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import psycopg

# Optional: load BenchmarkConfig to read thresholds from YAML
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from fdp.benchmark_config.benchmark import BenchmarkConfig
    _HAVE_CONFIG = True
except ImportError:
    _HAVE_CONFIG = False

DB_URL = os.environ.get("DATABASE_URL")


# ---------------------------------------------------------------------------
# SQL templates
# ---------------------------------------------------------------------------

_COUNT_SQL = """
SELECT COUNT(*) FROM fdp.ensemble_scores WHERE plan_id = %s
"""

# Partisan rollup — no threshold-dependent columns
_DRAW_STATS_SQL = """
INSERT INTO fdp.ensemble_draw_stats (
    plan_id, draw, year, election_type, office,
    dem_seats, rep_seats, tied_seats,
    avg_dem_2pv, efficiency_gap, mean_median
)
SELECT
    plan_id, draw, year, election_type, office,

    COUNT(*) FILTER (WHERE winner = 'dem')  AS dem_seats,
    COUNT(*) FILTER (WHERE winner = 'rep')  AS rep_seats,
    COUNT(*) FILTER (WHERE winner = 'tie')  AS tied_seats,

    ROUND(AVG(dem_2pv)::NUMERIC, 6)         AS avg_dem_2pv,

    -- Efficiency gap: (wasted_dem - wasted_rep) / total_votes
    -- Positive = Republican advantage, negative = Democratic advantage
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
    -- Positive = Democratic skew; negative = Republican advantage
    ROUND((
        AVG(dem_2pv)
        - PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY dem_2pv)
    )::NUMERIC, 6) AS mean_median

FROM fdp.ensemble_scores
WHERE plan_id = %s
GROUP BY plan_id, draw, year, election_type, office

ON CONFLICT (plan_id, draw, year, election_type, office) DO UPDATE SET
    dem_seats      = EXCLUDED.dem_seats,
    rep_seats      = EXCLUDED.rep_seats,
    tied_seats     = EXCLUDED.tied_seats,
    avg_dem_2pv    = EXCLUDED.avg_dem_2pv,
    efficiency_gap = EXCLUDED.efficiency_gap,
    mean_median    = EXCLUDED.mean_median
"""

# Competitive counts — one INSERT per threshold, value substituted at runtime
_COMPETITIVE_SQL = """
INSERT INTO fdp.ensemble_competitive_counts
    (plan_id, draw, year, election_type, office, threshold, n_competitive)
SELECT
    plan_id, draw, year, election_type, office,
    %(threshold)s AS threshold,
    COUNT(*) FILTER (
        WHERE dem_2pv IS NOT NULL
          AND ABS(dem_2pv - 0.5) * 2 <= %(threshold)s
    ) AS n_competitive
FROM fdp.ensemble_scores
WHERE plan_id = %(plan_id)s
GROUP BY plan_id, draw, year, election_type, office

ON CONFLICT (plan_id, draw, year, election_type, office, threshold) DO UPDATE SET
    n_competitive = EXCLUDED.n_competitive
"""

_VERIFY_SQL = """
SELECT
    COUNT(*)                                                    AS n_rows,
    COUNT(DISTINCT draw)                                        AS n_draws,
    COUNT(DISTINCT year || '_' || office)                       AS n_races,
    MIN(dem_seats)                                              AS min_dem,
    MAX(dem_seats)                                              AS max_dem,
    ROUND(AVG(dem_seats)::numeric, 2)                           AS avg_dem,
    ROUND(AVG(ABS(efficiency_gap))::numeric, 4)                 AS avg_abs_eg
FROM fdp.ensemble_draw_stats
WHERE plan_id = %s AND draw > 1
"""

_VERIFY_COMP_SQL = """
SELECT threshold, ROUND(AVG(n_competitive)::numeric, 2) AS avg_competitive
FROM fdp.ensemble_competitive_counts
WHERE plan_id = %s AND draw > 1
GROUP BY threshold
ORDER BY threshold
"""

_ENACTED_SQL = """
SELECT d.year, d.office, d.dem_seats, d.rep_seats,
       ROUND(d.efficiency_gap * 100, 2) AS eg_pct
FROM fdp.ensemble_draw_stats d
WHERE d.plan_id = %s AND d.draw = 1
ORDER BY d.year, d.office
"""

_ENACTED_COMP_SQL = """
SELECT year, office, threshold, n_competitive
FROM fdp.ensemble_competitive_counts
WHERE plan_id = %s AND draw = 1
ORDER BY year, office, threshold
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _thresholds_from_config(config_path: str) -> list[float]:
    if not _HAVE_CONFIG:
        print("WARNING: fdp package not importable — cannot read thresholds from config.")
        return []
    cfg = BenchmarkConfig.from_yaml(config_path)
    return cfg.competitiveness.thresholds


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--run-name", required=True,
                    help="plan_id to compute stats for (e.g. congress_2026_v2)")
    ap.add_argument("--config", default=None,
                    help="Path to YAML benchmark config — thresholds are read from "
                         "competitiveness.thresholds. Takes precedence over --thresholds.")
    ap.add_argument("--thresholds", nargs="+", type=float, default=None,
                    help="Competitiveness win-margin thresholds as fractions "
                         "(e.g. --thresholds 0.05 0.07). Ignored if --config is set.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show row counts and resolved thresholds but do not write.")
    args = ap.parse_args()

    if not DB_URL:
        print("ERROR: DATABASE_URL not set.")
        sys.exit(1)

    plan_id = args.run_name

    # ── Resolve thresholds ───────────────────────────────────────────────────
    if args.config:
        thresholds = _thresholds_from_config(args.config)
        print(f"  Thresholds from config: {thresholds}")
    elif args.thresholds:
        thresholds = sorted(args.thresholds)
        print(f"  Thresholds from CLI:    {thresholds}")
    else:
        thresholds = []
        print("  WARNING: no --config or --thresholds supplied.")
        print("  Partisan stats (seats, EG, mean-median) will be built.")
        print("  Competitive counts will NOT be computed.")

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
    if thresholds:
        print(f"  Competitive thresholds: {[f'{t:.1%}' for t in thresholds]}")

    if args.dry_run:
        print("\n[dry-run] Would execute INSERT...SELECT on PostgreSQL.")
        print(f"  Partisan rows: ~{n_source // 14:,}")
        if thresholds:
            print(f"  Competitive rows per threshold: ~{n_source // 14:,}")
        return

    # ── Partisan rollup ──────────────────────────────────────────────────────
    print("\nComputing partisan stats (seats, EG, mean-median)…")
    t0 = time.time()
    with psycopg.connect(DB_URL) as conn:
        conn.execute("SET SESSION default_transaction_read_only = off")
        conn.execute("BEGIN READ WRITE")
        conn.execute(_DRAW_STATS_SQL, (plan_id,))
        conn.execute("COMMIT")
    print(f"  Done in {time.time() - t0:.1f}s")

    # ── Competitive counts — one pass per threshold ──────────────────────────
    if thresholds:
        print("\nComputing competitive counts…")
        for t in thresholds:
            t0 = time.time()
            with psycopg.connect(DB_URL) as conn:
                conn.execute("SET SESSION default_transaction_read_only = off")
                conn.execute("BEGIN READ WRITE")
                conn.execute(_COMPETITIVE_SQL, {"plan_id": plan_id, "threshold": t})
                conn.execute("COMMIT")
            print(f"  threshold={t:.3f}: done in {time.time() - t0:.1f}s")

    # ── Verify ───────────────────────────────────────────────────────────────
    print("\nVerification:")
    with psycopg.connect(DB_URL) as conn:
        row = conn.execute(_VERIFY_SQL, (plan_id,)).fetchone()
        if row:
            print(f"  Partisan rows    : {row[0]:,}")
            print(f"  Draws            : {row[1]:,}")
            print(f"  Races            : {row[2]}")
            print(f"  Dem seats range  : {row[3]}–{row[4]}  (avg {row[5]})")
            print(f"  Avg |EG|         : {row[6]}")

        if thresholds:
            comp_rows = conn.execute(_VERIFY_COMP_SQL, (plan_id,)).fetchall()
            for cr in comp_rows:
                print(f"  Avg competitive  : {cr[1]} districts at {float(cr[0]):.1%}")

    # ── Enacted plan summary ─────────────────────────────────────────────────
    print("\nEnacted plan (draw=1):")
    with psycopg.connect(DB_URL) as conn:
        p_rows = conn.execute(_ENACTED_SQL,      (plan_id,)).fetchall()
        c_rows = conn.execute(_ENACTED_COMP_SQL, (plan_id,)).fetchall() if thresholds else []

    # Index competitive counts by (year, office, threshold) for display
    comp_lookup: dict[tuple, int] = {}
    thr_list: list[float] = []
    for cr in c_rows:
        key = (cr[0], cr[1], float(cr[2]))
        comp_lookup[key] = cr[3]
        t_val = float(cr[2])
        if t_val not in thr_list:
            thr_list.append(t_val)
    thr_list.sort()

    thr_hdr = "  ".join(f"C{int(t*100):02d}" for t in thr_list)
    print(f"  {'Year':<6} {'Office':<12} {'Seats':>8} {'EG%':>7}  {thr_hdr}")
    print("  " + "-" * (38 + 6 * len(thr_list)))
    for r in p_rows:
        year, office, dem, rep, eg = r
        comp_vals = "  ".join(
            f"{comp_lookup.get((year, office, t), '-'):>4}"
            for t in thr_list
        )
        print(f"  {year:<6} {office:<12} D{dem}/R{rep}  {eg:>6}%  {comp_vals}")

    print(f"\n✓ Done. Query distributions:")
    print(f"  SELECT * FROM fdp.v_partisan_distribution WHERE plan_id = '{plan_id}';")
    print(f"  SELECT * FROM fdp.v_enacted_vs_benchmark  WHERE plan_id = '{plan_id}';")
    print(f"  SELECT threshold, n_competitive")
    print(f"    FROM fdp.ensemble_competitive_counts")
    print(f"   WHERE plan_id = '{plan_id}' AND draw = 1")
    print(f"   ORDER BY threshold;")


if __name__ == "__main__":
    main()
