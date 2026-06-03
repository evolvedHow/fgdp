#!/usr/bin/env python3
"""
build_draw_stats.py — Compute per-draw benchmark statistics from ensemble scores Parquet.

Reads {run_name}_scores.parquet and computes:

  {run_name}_draw_stats.parquet        — one row per (plan_id, draw, year, office):
      dem_seats, rep_seats, tied_seats, avg_dem_2pv,
      efficiency_gap, mean_median

  {run_name}_competitive_counts.parquet — one row per (plan_id, draw, year, office, threshold):
      n_competitive

All heavy computation runs via DuckDB in-process — no database server needed.
DuckDB reads the scores Parquet lazily (no full-file load into RAM).

Thresholds come from --thresholds or --config (YAML). If neither is provided
the script builds partisan stats only (no competitive counts).

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
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = _SCRIPT_DIR.parent / "data/repos/main"

# Optional: load BenchmarkConfig to read thresholds from YAML
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from fdp.benchmark_config.benchmark import BenchmarkConfig
    _HAVE_CONFIG = True
except ImportError:
    _HAVE_CONFIG = False


# ---------------------------------------------------------------------------
# DuckDB query templates
# ---------------------------------------------------------------------------

# Partisan rollup — identical logic to the old PostgreSQL INSERT...SELECT,
# now executed in DuckDB against a local Parquet file.
_DRAW_STATS_SQL = """
SELECT
    plan_id, draw, year, election_type, office,

    COUNT(*) FILTER (WHERE winner = 'dem')  AS dem_seats,
    COUNT(*) FILTER (WHERE winner = 'rep')  AS rep_seats,
    COUNT(*) FILTER (WHERE winner = 'tie')  AS tied_seats,

    ROUND(AVG(dem_2pv), 6)                  AS avg_dem_2pv,

    -- Efficiency gap: (wasted_dem - wasted_rep) / total_votes
    -- Positive = Republican advantage, negative = Democratic advantage
    ROUND((
        SUM(
            CASE WHEN winner = 'dem'
                 THEN dem_votes - total_votes / 2.0
                 ELSE CAST(dem_votes AS DOUBLE)
            END
        )
        -
        SUM(
            CASE WHEN winner = 'rep'
                 THEN rep_votes - total_votes / 2.0
                 ELSE CAST(rep_votes AS DOUBLE)
            END
        )
    ) / NULLIF(SUM(total_votes), 0), 6)     AS efficiency_gap,

    -- Mean-median difference: mean(dem_2pv) - median(dem_2pv)
    -- Positive = Democratic skew; negative = Republican advantage
    ROUND(
        AVG(dem_2pv)
        - PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY dem_2pv),
        6
    )                                       AS mean_median

FROM read_parquet(?)
WHERE plan_id = ?
GROUP BY plan_id, draw, year, election_type, office
ORDER BY draw, year, office
"""

# Competitive counts — parameterised by threshold value
_COMPETITIVE_SQL = """
SELECT
    plan_id, draw, year, election_type, office,
    ? AS threshold,
    COUNT(*) FILTER (
        WHERE dem_2pv IS NOT NULL
          AND ABS(dem_2pv - 0.5) * 2 <= ?
    ) AS n_competitive
FROM read_parquet(?)
WHERE plan_id = ?
GROUP BY plan_id, draw, year, election_type, office
ORDER BY draw, year, office
"""

_VERIFY_SQL = """
SELECT
    COUNT(*)                                    AS n_rows,
    COUNT(DISTINCT draw)                        AS n_draws,
    COUNT(DISTINCT year || '_' || office)       AS n_races,
    MIN(dem_seats)                              AS min_dem,
    MAX(dem_seats)                              AS max_dem,
    ROUND(AVG(dem_seats), 2)                   AS avg_dem,
    ROUND(AVG(ABS(efficiency_gap)), 4)         AS avg_abs_eg
FROM draw_stats_df
WHERE draw > 1
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
                    help="Run name to compute stats for (e.g. congress_2026_v2)")
    ap.add_argument("--data-dir", default=None,
                    help=f"Root data directory (default: {DEFAULT_DATA_DIR})")
    ap.add_argument("--scores-file", default=None, dest="scores_file",
                    help="Path to the scores Parquet. "
                         "Defaults to {data_dir}/ensemble/{run_name}_scores.parquet.")
    ap.add_argument("--config", default=None,
                    help="Path to YAML benchmark config — thresholds read from "
                         "competitiveness.thresholds. Takes precedence over --thresholds.")
    ap.add_argument("--thresholds", nargs="+", type=float, default=None,
                    help="Competitiveness win-margin thresholds as fractions "
                         "(e.g. --thresholds 0.05 0.07). Ignored if --config is set.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show row counts and resolved thresholds but do not write.")
    args = ap.parse_args()

    plan_id  = args.run_name
    data_dir = Path(args.data_dir) if args.data_dir else DEFAULT_DATA_DIR

    scores_file = (
        Path(args.scores_file).resolve()
        if args.scores_file
        else data_dir / "ensemble" / f"{plan_id}_scores.parquet"
    )
    stats_out = data_dir / "ensemble" / f"{plan_id}_draw_stats.parquet"
    comp_out  = data_dir / "ensemble" / f"{plan_id}_competitive_counts.parquet"

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
    if not scores_file.exists():
        print(f"ERROR: scores Parquet not found: {scores_file}")
        print("  Run score_ensemble_plans.py first.")
        sys.exit(1)

    conn = duckdb.connect()
    row = conn.execute(
        "SELECT COUNT(*) FROM read_parquet(?)", [str(scores_file)]
    ).fetchone()
    n_source = row[0] if row else 0

    if n_source == 0:
        print(f"ERROR: no rows in {scores_file.name}")
        sys.exit(1)

    print(f"\nBuilding draw stats for: {plan_id}")
    print(f"  Source rows: {n_source:,}  ({scores_file.name})")
    if thresholds:
        print(f"  Competitive thresholds: {[f'{t:.1%}' for t in thresholds]}")

    if args.dry_run:
        print("\n[dry-run] Would compute partisan + competitive stats via DuckDB.")
        n_draws = conn.execute(
            "SELECT COUNT(DISTINCT draw) FROM read_parquet(?)", [str(scores_file)]
        ).fetchone()[0]
        n_races = conn.execute(
            "SELECT COUNT(DISTINCT year || '_' || office) FROM read_parquet(?)",
            [str(scores_file)]
        ).fetchone()[0]
        print(f"  Draws: {n_draws:,}   Races: {n_races}")
        return

    scores_path_str = str(scores_file)

    # ── Partisan rollup ──────────────────────────────────────────────────────
    print("\nComputing partisan stats (seats, EG, mean-median) via DuckDB…")
    t0 = time.time()
    draw_stats_df = conn.execute(
        _DRAW_STATS_SQL, [scores_path_str, plan_id]
    ).df()
    print(f"  {len(draw_stats_df):,} rows computed in {time.time() - t0:.1f}s")

    stats_out.parent.mkdir(parents=True, exist_ok=True)
    draw_stats_df.to_parquet(stats_out, index=False)
    size_mb = stats_out.stat().st_size / 1_000_000
    print(f"  → {stats_out.name}  ({size_mb:.1f} MB)")

    # ── Competitive counts — one pass per threshold ──────────────────────────
    comp_frames: list[pd.DataFrame] = []
    if thresholds:
        print("\nComputing competitive counts…")
        for t in thresholds:
            t0 = time.time()
            df_t = conn.execute(
                _COMPETITIVE_SQL, [t, t, scores_path_str, plan_id]
            ).df()
            comp_frames.append(df_t)
            print(f"  threshold={t:.3f}: {len(df_t):,} rows in {time.time() - t0:.1f}s")

        comp_df = pd.concat(comp_frames, ignore_index=True)
        comp_df.to_parquet(comp_out, index=False)
        size_mb = comp_out.stat().st_size / 1_000_000
        print(f"  → {comp_out.name}  ({size_mb:.1f} MB)")

    # ── Verify ───────────────────────────────────────────────────────────────
    print("\nVerification:")
    conn.register("draw_stats_df", draw_stats_df)
    row = conn.execute(_VERIFY_SQL).fetchone()
    if row:
        print(f"  Partisan rows    : {row[0]:,}")
        print(f"  Draws            : {row[1]:,}")
        print(f"  Races            : {row[2]}")
        print(f"  Dem seats range  : {row[3]}–{row[4]}  (avg {row[5]})")
        print(f"  Avg |EG|         : {row[6]}")

    if comp_frames:
        comp_df = pd.concat(comp_frames)
        for t in thresholds:
            avg = comp_df[comp_df.threshold == t]["n_competitive"].mean()
            print(f"  Avg competitive  : {avg:.2f} districts at {t:.1%}")

    # ── Enacted plan summary ─────────────────────────────────────────────────
    print("\nEnacted plan (draw=1):")
    enacted = draw_stats_df[draw_stats_df.draw == 1]
    thr_hdr = "  ".join(f"C{int(t*100):02d}" for t in thresholds)
    print(f"  {'Year':<6} {'Office':<12} {'Seats':>8} {'EG%':>7}  {thr_hdr}")
    print("  " + "-" * (38 + 6 * len(thresholds)))

    enacted_comp = {}
    if comp_frames:
        comp_df_full = pd.concat(comp_frames)
        enacted_comp_df = comp_df_full[comp_df_full.draw == 1]
        for _, cr in enacted_comp_df.iterrows():
            enacted_comp[(int(cr.year), cr.office, float(cr.threshold))] = int(cr.n_competitive)

    for _, r in enacted.iterrows():
        eg_pct = round(float(r.efficiency_gap or 0) * 100, 2)
        comp_vals = "  ".join(
            f"{enacted_comp.get((int(r.year), r.office, t), '-'):>4}"
            for t in thresholds
        )
        print(f"  {int(r.year):<6} {r.office:<12} D{int(r.dem_seats)}/R{int(r.rep_seats)}"
              f"  {eg_pct:>6}%  {comp_vals}")

    print(f"\n✓ Done.")
    print(f"  Partisan stats : {stats_out}")
    if thresholds:
        print(f"  Competitive    : {comp_out}")
    print(f"\nNext:")
    print(f"  uv run --project fdp python fdp/scripts/visualize_benchmark.py \\")
    print(f"      --run-name {plan_id}")


if __name__ == "__main__":
    main()
