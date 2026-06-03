#!/usr/bin/env python3
"""
visualize_benchmark.py — Generate benchmark charts for a redistricting ensemble run.

Reads local Parquet files produced by the scoring pipeline and produces
four chart files (saved as PNG):

  {run_name}_partisan.png      — Partisan lean histograms (one per election, auto grid)
  {run_name}_competitiveness_{N}pct.png — Competitive district count histograms
  {run_name}_demographics.png  — Majority-minority district count histograms
  {run_name}_river_{election}.png — River chart: district dem_2pv bands + enacted overlay

Reads from {data_dir}/ensemble/:
  {run_name}_scores.parquet
  {run_name}_draw_stats.parquet
  {run_name}_competitive_counts.parquet
  {run_name}_demographics.parquet

Usage (from fgdp/ root):
    uv run --project fdp python fdp/scripts/visualize_benchmark.py \\
        --run-name congress_2026_v2

    uv run --project fdp python fdp/scripts/visualize_benchmark.py \\
        --run-name congress_2026_v2 \\
        --out-dir fdp/data/repos/main/ensemble/charts \\
        --elections 2022_general_governor 2024_general_president
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")   # headless — no display needed
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import duckdb

# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------

FDGA_BLUE   = "#1B4F8A"
FDGA_RED    = "#C0392B"
FDGA_GOLD   = "#F0A500"
FDGA_GREY   = "#7F8C8D"
FDGA_LIGHT  = "#D6E4F0"

plt.rcParams.update({
    "font.family":      "sans-serif",
    "font.size":        10,
    "axes.spines.top":  False,
    "axes.spines.right": False,
    "axes.grid":        True,
    "grid.alpha":       0.3,
    "figure.dpi":       150,
})

_SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = _SCRIPT_DIR.parent / "data/repos/main"


def _race_label(year: int, election_type: str, office: str) -> str:
    """Human-readable label for any election — no hardcoded list needed."""
    etype_suffix = {"runoff": " Runoff", "primary": " Primary", "special": " Special"}.get(
        election_type, ""
    )
    office_title = office.replace("-", " ").title()
    return f"{year} {office_title}{etype_suffix}"


# ---------------------------------------------------------------------------
# Data loaders (DuckDB reading from Parquet — no database connection needed)
# ---------------------------------------------------------------------------

def _duck() -> duckdb.DuckDBPyConnection:
    """Return a fresh in-memory DuckDB connection."""
    return duckdb.connect()


def load_races(draw_stats_file: Path) -> list[tuple[int, str, str]]:
    """
    Return the distinct (year, election_type, office) combinations present
    in draw_stats Parquet for this run, sorted chronologically.
    Works for any state/election set — no hardcoded race list.
    """
    conn = _duck()
    rows = conn.execute("""
        SELECT DISTINCT year, election_type, office
        FROM read_parquet(?)
        ORDER BY year, office
    """, [str(draw_stats_file)]).fetchall()
    return [(int(r[0]), r[1], r[2]) for r in rows]


def load_draw_stats(draw_stats_file: Path) -> pd.DataFrame:
    """Load draw stats for this run (all draws, all races)."""
    conn = _duck()
    df = conn.execute("""
        SELECT draw, year, election_type, office,
               dem_seats, rep_seats,
               efficiency_gap, mean_median,
               avg_dem_2pv
        FROM read_parquet(?)
        ORDER BY draw, year, office
    """, [str(draw_stats_file)]).df()
    if not df.empty:
        for col in ("dem_seats", "rep_seats", "efficiency_gap", "mean_median", "avg_dem_2pv"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def load_competitive_counts(comp_file: Path | None) -> pd.DataFrame:
    """
    Load competitive counts from Parquet.
    Returns empty DataFrame if the file doesn't exist (no thresholds were computed).
    """
    if comp_file is None or not comp_file.exists():
        return pd.DataFrame()
    conn = _duck()
    df = conn.execute("""
        SELECT draw, year, election_type, office,
               threshold::DOUBLE AS threshold,
               n_competitive
        FROM read_parquet(?)
        ORDER BY threshold, draw, year, office
    """, [str(comp_file)]).df()
    if not df.empty:
        df["threshold"]     = pd.to_numeric(df["threshold"],     errors="coerce")
        df["n_competitive"] = pd.to_numeric(df["n_competitive"], errors="coerce")
    return df


def load_district_scores(scores_file: Path, plan_id: str,
                          year: int, election_type: str, office: str) -> pd.DataFrame:
    """Load per-district dem_2pv for all draws — used for river chart."""
    conn = _duck()
    df = conn.execute("""
        SELECT draw, district, dem_2pv
        FROM read_parquet(?)
        WHERE plan_id = ? AND year = ? AND election_type = ? AND office = ?
        ORDER BY draw, district
    """, [str(scores_file), plan_id, year, election_type, office]).df()
    if not df.empty:
        df["dem_2pv"] = pd.to_numeric(df["dem_2pv"], errors="coerce")
    return df


def load_demographic_draw_stats(demo_file: Path | None) -> pd.DataFrame:
    """
    Compute majority-X district counts per draw from demographics Parquet.
    Equivalent to the old fdp.v_demographic_draw_stats view.
    Returns empty DataFrame if the file doesn't exist.
    """
    if demo_file is None or not demo_file.exists():
        return pd.DataFrame()
    conn = _duck()
    df = conn.execute("""
        SELECT draw,
            SUM(CAST(majority_black              AS INTEGER)) AS n_majority_black,
            SUM(CAST(majority_white              AS INTEGER)) AS n_majority_white,
            SUM(CAST(majority_hispanic           AS INTEGER)) AS n_majority_hispanic,
            SUM(CAST(majority_minority_coalition AS INTEGER)) AS n_majority_coalition
        FROM read_parquet(?)
        GROUP BY draw
        ORDER BY draw
    """, [str(demo_file)]).df()
    return df


# ---------------------------------------------------------------------------
# Chart 1: Partisan lean histograms
# ---------------------------------------------------------------------------

def chart_partisan(df: pd.DataFrame, plan_id: str, out_path: Path,
                   races: list[tuple]) -> None:
    """Dem-seat histograms — one subplot per election, auto-sized grid."""
    n = len(races)
    ncols = min(n, 3)
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(14, 5 * nrows))
    fig.suptitle(
        f"Partisan Lean Distribution — {plan_id}\n"
        "Each bar = fraction of simulated maps producing N Democratic seats",
        fontsize=12, fontweight="bold", y=1.01,
    )

    axes_flat = np.array(axes).flatten()
    for ax, (year, etype, office) in zip(axes_flat, races):
        race_df  = df[(df.year == year) & (df.election_type == etype) & (df.office == office)]
        sim      = race_df[race_df.draw > 1]
        enacted  = race_df[race_df.draw == 1]

        if sim.empty:
            ax.set_visible(False)
            continue

        enacted_seats = int(enacted.dem_seats.iloc[0]) if not enacted.empty else None

        seat_counts = sim.dem_seats.value_counts().sort_index()
        xs = seat_counts.index.tolist()
        ys = seat_counts.values.tolist()
        total = len(sim)

        colors = [FDGA_BLUE if x == enacted_seats else FDGA_LIGHT for x in xs]
        ax.bar(xs, [y / total * 100 for y in ys], color=colors,
               edgecolor="white", linewidth=0.5, zorder=3)

        q25 = sim.dem_seats.quantile(0.25)
        q75 = sim.dem_seats.quantile(0.75)
        ax.axvspan(q25 - 0.5, q75 + 0.5, alpha=0.12, color=FDGA_BLUE,
                   label="IQR (A-grade range)", zorder=1)

        if enacted_seats is not None:
            ax.axvline(enacted_seats, color=FDGA_RED, linewidth=2.0,
                       linestyle="--", zorder=4, label=f"Enacted: D{enacted_seats}")
            pctile = (sim.dem_seats <= enacted_seats).mean() * 100
            grade  = _grade(pctile)
            ax.text(0.97, 0.95, f"Pctile: {pctile:.0f}%\nGrade: {grade}",
                    transform=ax.transAxes, ha="right", va="top",
                    fontsize=8.5, color=FDGA_RED,
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                              edgecolor=FDGA_RED, alpha=0.8))

        ax.set_title(_race_label(year, etype, office), fontsize=10, fontweight="bold")
        ax.set_xlabel("Democratic Seats")
        ax.set_ylabel("% of Simulated Maps")
        ax.set_xticks(range(max(1, min(xs) - 1), max(xs) + 2))
        ax.set_xlim(min(xs) - 0.7, max(xs) + 0.7)

        if ax is axes_flat[0]:
            ax.legend(fontsize=7, loc="upper left")

    for ax in axes_flat[len(races):]:
        ax.set_visible(False)

    plt.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", dpi=150)
    plt.close(fig)
    print(f"  Saved: {out_path.name}")


# ---------------------------------------------------------------------------
# Chart 2: Competitiveness histograms
# ---------------------------------------------------------------------------

def chart_competitiveness(comp_df: pd.DataFrame, plan_id: str,
                           out_path: Path, threshold: float,
                           races: list[tuple]) -> None:
    """Competitive district count distribution for a single threshold."""
    if comp_df.empty:
        print(f"  WARNING: no competitive count data for threshold={threshold:.1%} — skipping")
        return

    thr_df = comp_df[comp_df.threshold == threshold]
    if thr_df.empty:
        print(f"  WARNING: threshold {threshold:.1%} not in data — skipping competitiveness chart")
        return

    n     = len(races)
    ncols = min(n, 3)
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(14, 5 * nrows))
    pct_label = f"{threshold:.0%}"
    fig.suptitle(
        f"Competitive Districts Distribution — {plan_id}\n"
        f"Win margin ≤ {pct_label} threshold.  Vertical line = enacted map.",
        fontsize=12, fontweight="bold", y=1.01,
    )

    axes_flat = np.array(axes).flatten()
    for ax, (year, etype, office) in zip(axes_flat, races):
        race_thr = thr_df[
            (thr_df.year == year) & (thr_df.election_type == etype) & (thr_df.office == office)
        ]
        sim     = race_thr[race_thr.draw > 1]
        enacted = race_thr[race_thr.draw == 1]

        if sim.empty:
            ax.set_visible(False)
            continue

        enacted_comp = int(enacted.n_competitive.iloc[0]) if not enacted.empty else None

        counts = sim.n_competitive.value_counts().sort_index()
        xs     = counts.index.tolist()
        total  = len(sim)

        colors = [FDGA_BLUE if x == enacted_comp else FDGA_LIGHT for x in xs]
        ax.bar(xs, [c / total * 100 for c in counts.values],
               color=colors, edgecolor="white", linewidth=0.5, zorder=3)

        if enacted_comp is not None:
            ax.axvline(enacted_comp, color=FDGA_RED, linewidth=2.0,
                       linestyle="--", zorder=4)
            avg    = sim.n_competitive.mean()
            pctile = (sim.n_competitive >= enacted_comp).mean() * 100
            ax.text(0.97, 0.95,
                    f"Enacted: {enacted_comp}\nEns avg: {avg:.1f}\nPctile: {pctile:.0f}%",
                    transform=ax.transAxes, ha="right", va="top",
                    fontsize=8.5, color=FDGA_RED,
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                              edgecolor=FDGA_RED, alpha=0.8))

        ax.set_title(_race_label(year, etype, office), fontsize=10, fontweight="bold")
        ax.set_xlabel(f"Competitive Districts (margin ≤ {pct_label})")
        ax.set_ylabel("% of Simulated Maps")
        if xs:
            ax.set_xticks(range(min(xs), max(xs) + 1))

    for ax in axes_flat[len(races):]:
        ax.set_visible(False)

    plt.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", dpi=150)
    plt.close(fig)
    print(f"  Saved: {out_path.name}")


# ---------------------------------------------------------------------------
# Chart 3: Demographic histograms
# ---------------------------------------------------------------------------

def chart_demographics(demo_df: pd.DataFrame, plan_id: str, out_path: Path) -> None:
    """Majority-minority district count distributions."""
    sim     = demo_df[demo_df.draw > 1]
    enacted = demo_df[demo_df.draw == 1]

    groups = [
        ("n_majority_black",     "Majority-Black Districts\n(any-part Black CVAP > 50%)",    FDGA_BLUE),
        ("n_majority_white",     "Majority-White Districts\n(White non-Hispanic CVAP > 50%)", FDGA_GREY),
        ("n_majority_coalition", "Majority Minority Coalition\n(Non-White CVAP > 50%)",       FDGA_GOLD),
    ]

    fig, axes = plt.subplots(1, 3, figsize=(14, 5))
    fig.suptitle(
        f"Demographic Distribution — {plan_id}\n"
        "CVAP-based majority thresholds.  Vertical line = enacted map.",
        fontsize=12, fontweight="bold",
    )

    for ax, (col, title, color) in zip(axes, groups):
        if col not in sim.columns:
            ax.set_visible(False)
            continue

        counts = sim[col].astype(int).value_counts().sort_index()
        xs     = counts.index.tolist()
        total  = len(sim)
        enacted_val = int(enacted[col].iloc[0]) if not enacted.empty else None

        bar_colors = [color if x == enacted_val else "#D5D8DC" for x in xs]
        ax.bar(xs, [c / total * 100 for c in counts.values],
               color=bar_colors, edgecolor="white", linewidth=0.5, zorder=3)

        if enacted_val is not None:
            ax.axvline(enacted_val, color=FDGA_RED, linewidth=2.0,
                       linestyle="--", zorder=4)
            avg = sim[col].mean()
            pctile = (sim[col] >= enacted_val).mean() * 100
            ax.text(0.97, 0.95,
                    f"Enacted: {enacted_val}\nEns avg: {avg:.1f}\nPctile: {pctile:.0f}%",
                    transform=ax.transAxes, ha="right", va="top",
                    fontsize=9, color=FDGA_RED,
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                              edgecolor=FDGA_RED, alpha=0.8))

        ax.set_title(title, fontsize=10, fontweight="bold")
        ax.set_xlabel("Number of Districts")
        ax.set_ylabel("% of Simulated Maps")
        if xs:
            ax.set_xticks(range(min(xs), max(xs) + 1))

    plt.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", dpi=150)
    plt.close(fig)
    print(f"  Saved: {out_path.name}")


# ---------------------------------------------------------------------------
# Chart 4: River chart
# ---------------------------------------------------------------------------

def chart_river(plan_id: str, year: int, etype: str, office: str,
                scores_file: Path, out_path: Path) -> None:
    """
    River chart: districts sorted by median dem_2pv across ensemble.
    Shows 5th/25th/50th/75th/95th percentile bands + enacted plan overlay.
    """
    label = _race_label(year, etype, office)
    print(f"  Loading district scores for river chart ({label})…")
    dist_df = load_district_scores(scores_file, plan_id, year, etype, office)

    if dist_df.empty:
        print(f"  WARNING: no data for {label} — skipping river chart")
        return

    sim     = dist_df[dist_df.draw > 1]
    enacted = dist_df[dist_df.draw == 1]

    bands = sim.groupby("district")["dem_2pv"].quantile(
        [0.05, 0.25, 0.50, 0.75, 0.95]
    ).unstack()
    bands.columns = ["p05", "p25", "p50", "p75", "p95"]
    bands = bands.sort_values("p50").reset_index()

    district_order = bands["district"].tolist()
    x = np.arange(len(district_order))

    fig, ax = plt.subplots(figsize=(12, 6))

    ax.fill_between(x, bands.p05, bands.p95, alpha=0.15, color=FDGA_BLUE,
                    label="5th–95th pct (95% CI)")
    ax.fill_between(x, bands.p25, bands.p75, alpha=0.35, color=FDGA_BLUE,
                    label="25th–75th pct (IQR / A-grade)")
    ax.plot(x, bands.p50, color=FDGA_BLUE, linewidth=1.5,
            linestyle="--", label="Median (50th pct)", zorder=3)

    if not enacted.empty:
        enacted_vals = (enacted.set_index("district")
                        .reindex(district_order)["dem_2pv"]
                        .values)
        ax.plot(x, enacted_vals, color=FDGA_RED, linewidth=2.0,
                marker="o", markersize=5, label="Enacted plan", zorder=5)

    ax.axhline(0.5, color="black", linewidth=0.8, linestyle=":", alpha=0.5,
               label="50% (tie)")

    ax.set_xticks(x)
    ax.set_xticklabels([f"D{d}" for d in district_order], rotation=45, ha="right")
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, _: f"{v*100:.0f}%")
    )
    ax.set_xlabel("District (sorted by median Democratic vote share)")
    ax.set_ylabel("Democratic Two-Party Vote Share")
    ax.set_title(
        f"River Chart — {label}\n{plan_id}",
        fontsize=12, fontweight="bold",
    )
    ax.legend(loc="upper left", fontsize=8.5, framealpha=0.9)

    plt.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", dpi=150)
    plt.close(fig)
    print(f"  Saved: {out_path.name}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _grade(pctile: float) -> str:
    if 25 <= pctile <= 75:  return "A"
    if 10 <= pctile <= 90:  return "B"
    if  5 <= pctile <= 95:  return "C"
    if  1 <= pctile <= 99:  return "F"
    return "FAIL"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--run-name", required=True,
                    help="Run name to visualize (e.g. congress_2026_v2)")
    ap.add_argument("--data-dir", default=None,
                    help=f"Root data directory (default: {DEFAULT_DATA_DIR})")
    ap.add_argument("--out-dir", default=None,
                    help="Output directory for PNG files "
                         "(default: {data_dir}/ensemble/charts)")
    ap.add_argument("--river-elections", nargs="*",
                    default=None,
                    dest="river_elections",
                    help="Elections to generate river charts for (format: YYYY_type_office). "
                         "Default: all elections found for this run.")
    args = ap.parse_args()

    plan_id  = args.run_name
    data_dir = Path(args.data_dir) if args.data_dir else DEFAULT_DATA_DIR
    ens_dir  = data_dir / "ensemble"

    # Parquet file paths (convention-based)
    draw_stats_file = ens_dir / f"{plan_id}_draw_stats.parquet"
    comp_file       = ens_dir / f"{plan_id}_competitive_counts.parquet"
    demo_file       = ens_dir / f"{plan_id}_demographics.parquet"
    scores_file     = ens_dir / f"{plan_id}_scores.parquet"

    # Output directory
    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        out_dir = ens_dir / "charts"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nGenerating benchmark charts for: {plan_id}")
    print(f"Data directory : {ens_dir}")
    print(f"Output directory: {out_dir}")

    # ── Check required files ─────────────────────────────────────────────────
    if not draw_stats_file.exists():
        print(f"\nERROR: draw stats not found: {draw_stats_file}")
        print("  Run: uv run --project fdp python fdp/scripts/build_draw_stats.py "
              f"--run-name {plan_id}")
        sys.exit(1)

    # ── Load data ────────────────────────────────────────────────────────────
    print("\nLoading draw stats…")
    df = load_draw_stats(draw_stats_file)

    print("Discovering elections for this run…")
    races = load_races(draw_stats_file)
    if not races:
        print("  WARNING: no elections found in draw stats — charts may be empty")
    else:
        print(f"  Elections: {[(y, o) for y, _, o in races]}")

    print("Loading competitive counts…")
    comp_df = load_competitive_counts(comp_file if comp_file.exists() else None)
    if comp_df.empty:
        print("  WARNING: no competitive count data found.")
        print(f"  Run: build_draw_stats.py --run-name {plan_id} --config <yaml>")
    else:
        thresholds_available = sorted(comp_df.threshold.unique().tolist())
        print(f"  Thresholds available: {[f'{t:.1%}' for t in thresholds_available]}")

    print("Loading demographic stats…")
    demo_df = load_demographic_draw_stats(demo_file if demo_file.exists() else None)

    # ── Generate charts ──────────────────────────────────────────────────────
    print("\nGenerating charts…")

    # Chart 1: Partisan histograms
    chart_partisan(df, plan_id,
                   out_dir / f"{plan_id}_partisan.png",
                   races=races)

    # Chart 2: Competitiveness histograms — one per threshold
    if not comp_df.empty:
        for t in sorted(comp_df.threshold.unique()):
            t_str = f"{int(t * 100):02d}"
            chart_competitiveness(comp_df, plan_id,
                                  out_dir / f"{plan_id}_competitiveness_{t_str}pct.png",
                                  threshold=t,
                                  races=races)
    else:
        print("  Skipping competitiveness charts (no data)")

    # Chart 3: Demographic histograms
    if not demo_df.empty:
        chart_demographics(demo_df, plan_id,
                           out_dir / f"{plan_id}_demographics.png")
    else:
        print("  WARNING: no demographic data — skipping demographics chart")
        print(f"  Run: score_ensemble_demographics.py --run-name {plan_id} first")

    # Chart 4: River charts
    if args.river_elections is not None:
        river_specs = args.river_elections
    else:
        river_specs = [f"{y}_{et}_{o}" for y, et, o in races]

    if not scores_file.exists():
        print(f"  WARNING: scores Parquet not found ({scores_file.name}) — skipping river charts")
    else:
        for elec_str in river_specs:
            parts = elec_str.split("_", 2)
            if len(parts) != 3:
                print(f"  WARNING: cannot parse election '{elec_str}' — use YYYY_type_office")
                continue
            year, etype, office = int(parts[0]), parts[1], parts[2]
            fname = f"{plan_id}_river_{elec_str}.png"
            chart_river(plan_id, year, etype, office,
                        scores_file,
                        out_dir / fname)

    print(f"\n✓ All charts saved to: {out_dir}")
    print("\nFiles:")
    for f in sorted(out_dir.glob(f"{plan_id}_*.png")):
        size_kb = f.stat().st_size // 1024
        print(f"  {f.name}  ({size_kb} kB)")


if __name__ == "__main__":
    main()
