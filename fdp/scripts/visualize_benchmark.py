#!/usr/bin/env python3
"""
visualize_benchmark.py — Generate benchmark charts for a redistricting ensemble run.

Produces four chart files (saved as PNG):

  {run_name}_partisan.png      — Partisan lean histograms (one per election, 2×3 grid)
  {run_name}_competitiveness.png — Competitive district count histograms
  {run_name}_demographics.png  — Majority-minority district count histograms
  {run_name}_river.png         — River chart: district dem_2pv bands + enacted overlay

Usage (from fgdp/ root):
    uv run --project fdp python fdp/scripts/visualize_benchmark.py \\
        --run-name congress_2026_v1

    uv run --project fdp python fdp/scripts/visualize_benchmark.py \\
        --run-name congress_2026_v1 \\
        --out-dir fdp/data/repos/main/ensemble/charts \\
        --elections 2022_general_governor 2024_general_president
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")   # headless — no display needed
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
import psycopg
import psycopg.rows

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

DB_URL = os.environ.get("DATABASE_URL")

PRIORITY_RACES = [
    (2018, "general",  "governor"),
    (2020, "general",  "president"),
    (2021, "runoff",   "senate"),
    (2022, "general",  "governor"),
    (2022, "general",  "senate"),
    (2024, "general",  "president"),
]

RACE_LABELS = {
    (2018, "general",  "governor"):  "2018 Governor",
    (2020, "general",  "president"): "2020 President",
    (2021, "runoff",   "senate"):    "2021 Senate Runoff",
    (2022, "general",  "governor"):  "2022 Governor",
    (2022, "general",  "senate"):    "2022 Senate",
    (2024, "general",  "president"): "2024 President",
}


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _conn() -> psycopg.Connection:
    if not DB_URL:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg.connect(DB_URL, row_factory=psycopg.rows.dict_row)


def load_draw_stats(plan_id: str) -> pd.DataFrame:
    """Load ensemble_draw_stats for this plan (all draws, all races)."""
    sql = """
        SELECT draw, year, election_type, office,
               dem_seats, rep_seats,
               efficiency_gap, mean_median,
               n_competitive_007, n_competitive_010,
               avg_dem_2pv
        FROM fdp.ensemble_draw_stats
        WHERE plan_id = %s
        ORDER BY draw, year, office
    """
    with _conn() as conn:
        rows = conn.execute(sql, (plan_id,)).fetchall()
    df = pd.DataFrame(rows)
    if not df.empty:
        for col in ("dem_seats", "rep_seats", "tied_seats",
                    "efficiency_gap", "mean_median", "avg_dem_2pv",
                    "n_competitive_007", "n_competitive_010"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def load_district_scores(plan_id: str, year: int, election_type: str, office: str) -> pd.DataFrame:
    """Load per-district dem_2pv for all draws — used for river chart."""
    sql = """
        SELECT draw, district, dem_2pv
        FROM fdp.ensemble_scores
        WHERE plan_id = %s AND year = %s AND election_type = %s AND office = %s
        ORDER BY draw, district
    """
    with _conn() as conn:
        rows = conn.execute(sql, (plan_id, year, election_type, office)).fetchall()
    df = pd.DataFrame(rows)
    if not df.empty:
        df["dem_2pv"] = pd.to_numeric(df["dem_2pv"], errors="coerce")
    return df


def load_demographic_draw_stats(plan_id: str) -> pd.DataFrame:
    """Load majority-X district counts per draw from v_demographic_draw_stats."""
    sql = """
        SELECT draw, n_majority_black, n_majority_white,
               n_majority_hispanic, n_majority_coalition
        FROM fdp.v_demographic_draw_stats
        WHERE plan_id = %s
        ORDER BY draw
    """
    with _conn() as conn:
        rows = conn.execute(sql, (plan_id,)).fetchall()
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Chart 1: Partisan lean histograms
# ---------------------------------------------------------------------------

def chart_partisan(df: pd.DataFrame, plan_id: str, out_path: Path) -> None:
    """2×3 grid of dem_seats histograms, one per election."""
    races = PRIORITY_RACES
    fig, axes = plt.subplots(2, 3, figsize=(14, 8))
    fig.suptitle(
        f"Partisan Lean Distribution — {plan_id}\n"
        "Each bar = fraction of 10,000 simulated maps producing N Democratic seats",
        fontsize=12, fontweight="bold", y=1.01,
    )

    for ax, (year, etype, office) in zip(axes.flat, races):
        race_df  = df[(df.year == year) & (df.election_type == etype) & (df.office == office)]
        sim      = race_df[race_df.draw > 1]
        enacted  = race_df[race_df.draw == 1]

        if sim.empty:
            ax.set_visible(False)
            continue

        enacted_seats = int(enacted.dem_seats.iloc[0]) if not enacted.empty else None

        # Histogram
        seat_counts = sim.dem_seats.value_counts().sort_index()
        xs = seat_counts.index.tolist()
        ys = seat_counts.values.tolist()
        total = len(sim)

        # Color bars: blue if this is enacted value, light grey otherwise
        colors = [FDGA_BLUE if x == enacted_seats else FDGA_LIGHT for x in xs]
        bars = ax.bar(xs, [y / total * 100 for y in ys], color=colors,
                      edgecolor="white", linewidth=0.5, zorder=3)

        # IQR shading
        q25 = sim.dem_seats.quantile(0.25)
        q75 = sim.dem_seats.quantile(0.75)
        ax.axvspan(q25 - 0.5, q75 + 0.5, alpha=0.12, color=FDGA_BLUE,
                   label="IQR (A-grade range)", zorder=1)

        # Enacted line
        if enacted_seats is not None:
            ax.axvline(enacted_seats, color=FDGA_RED, linewidth=2.0,
                       linestyle="--", zorder=4, label=f"Enacted: D{enacted_seats}")
            # Percentile rank
            pctile = (sim.dem_seats <= enacted_seats).mean() * 100
            grade  = _grade(pctile)
            ax.text(0.97, 0.95, f"Pctile: {pctile:.0f}%\nGrade: {grade}",
                    transform=ax.transAxes, ha="right", va="top",
                    fontsize=8.5, color=FDGA_RED,
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                              edgecolor=FDGA_RED, alpha=0.8))

        ax.set_title(RACE_LABELS.get((year, etype, office), f"{year} {office}"),
                     fontsize=10, fontweight="bold")
        ax.set_xlabel("Democratic Seats")
        ax.set_ylabel("% of Simulated Maps")
        ax.set_xticks(range(max(1, min(xs) - 1), max(xs) + 2))
        ax.set_xlim(min(xs) - 0.7, max(xs) + 0.7)

        # Legend only on first chart
        if ax == axes.flat[0]:
            ax.legend(fontsize=7, loc="upper left")

    plt.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", dpi=150)
    plt.close(fig)
    print(f"  Saved: {out_path.name}")


# ---------------------------------------------------------------------------
# Chart 2: Competitiveness histograms
# ---------------------------------------------------------------------------

def chart_competitiveness(df: pd.DataFrame, plan_id: str, out_path: Path) -> None:
    """Competitive district count distributions at 7% and 10% thresholds."""
    races = PRIORITY_RACES
    fig, axes = plt.subplots(2, 3, figsize=(14, 8))
    fig.suptitle(
        f"Competitive Districts Distribution — {plan_id}\n"
        "Win margin ≤ 7% (primary threshold).  Vertical line = enacted map.",
        fontsize=12, fontweight="bold", y=1.01,
    )

    for ax, (year, etype, office) in zip(axes.flat, races):
        race_df = df[(df.year == year) & (df.election_type == etype) & (df.office == office)]
        sim     = race_df[race_df.draw > 1]
        enacted = race_df[race_df.draw == 1]

        if sim.empty:
            ax.set_visible(False)
            continue

        enacted_comp = int(enacted.n_competitive_007.iloc[0]) if not enacted.empty else None

        counts = sim.n_competitive_007.value_counts().sort_index()
        xs     = counts.index.tolist()
        total  = len(sim)

        colors = [FDGA_BLUE if x == enacted_comp else FDGA_LIGHT for x in xs]
        ax.bar(xs, [c / total * 100 for c in counts.values],
               color=colors, edgecolor="white", linewidth=0.5, zorder=3)

        if enacted_comp is not None:
            ax.axvline(enacted_comp, color=FDGA_RED, linewidth=2.0,
                       linestyle="--", zorder=4)
            avg = sim.n_competitive_007.mean()
            pctile = (sim.n_competitive_007 >= enacted_comp).mean() * 100
            ax.text(0.97, 0.95,
                    f"Enacted: {enacted_comp}\nEns avg: {avg:.1f}\nPctile: {pctile:.0f}%",
                    transform=ax.transAxes, ha="right", va="top",
                    fontsize=8.5, color=FDGA_RED,
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                              edgecolor=FDGA_RED, alpha=0.8))

        ax.set_title(RACE_LABELS.get((year, etype, office), f"{year} {office}"),
                     fontsize=10, fontweight="bold")
        ax.set_xlabel("Competitive Districts (margin ≤ 7%)")
        ax.set_ylabel("% of Simulated Maps")
        if xs:
            ax.set_xticks(range(min(xs), max(xs) + 1))

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
        ("n_majority_black",     "Majority-Black Districts\n(any-part Black CVAP > 50%)",  FDGA_BLUE),
        ("n_majority_white",     "Majority-White Districts\n(White non-Hispanic CVAP > 50%)", FDGA_GREY),
        ("n_majority_coalition", "Majority Minority Coalition\n(Non-White CVAP > 50%)", FDGA_GOLD),
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

        counts = sim[col].value_counts().sort_index()
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
                out_path: Path) -> None:
    """
    River chart: districts sorted by median dem_2pv across ensemble.
    Shows 5th/25th/50th/75th/95th percentile bands + enacted plan overlay.
    """
    label = RACE_LABELS.get((year, etype, office), f"{year} {office}")
    print(f"  Loading district scores for river chart ({label})…")
    dist_df = load_district_scores(plan_id, year, etype, office)

    if dist_df.empty:
        print(f"  WARNING: no data for {label} — skipping river chart")
        return

    sim     = dist_df[dist_df.draw > 1]
    enacted = dist_df[dist_df.draw == 1]

    # Compute percentiles per district
    bands = sim.groupby("district")["dem_2pv"].quantile(
        [0.05, 0.25, 0.50, 0.75, 0.95]
    ).unstack()
    bands.columns = ["p05", "p25", "p50", "p75", "p95"]
    bands = bands.sort_values("p50").reset_index()   # sort by median

    district_order = bands["district"].tolist()
    x = np.arange(len(district_order))

    fig, ax = plt.subplots(figsize=(12, 6))

    # Shaded bands
    ax.fill_between(x, bands.p05, bands.p95, alpha=0.15, color=FDGA_BLUE,
                    label="5th–95th pct (95% CI)")
    ax.fill_between(x, bands.p25, bands.p75, alpha=0.35, color=FDGA_BLUE,
                    label="25th–75th pct (IQR / A-grade)")

    # Median line
    ax.plot(x, bands.p50, color=FDGA_BLUE, linewidth=1.5,
            linestyle="--", label="Median (50th pct)", zorder=3)

    # Enacted overlay
    if not enacted.empty:
        enacted_vals = (enacted.set_index("district")
                        .reindex(district_order)["dem_2pv"]
                        .values)
        ax.plot(x, enacted_vals, color=FDGA_RED, linewidth=2.0,
                marker="o", markersize=5, label="Enacted plan", zorder=5)

    # 50% line
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
                    help="plan_id to visualize (e.g. congress_2026_v1)")
    ap.add_argument("--out-dir", default=None,
                    help="Output directory for PNG files (default: fdp/data/repos/main/ensemble/charts)")
    ap.add_argument("--river-elections", nargs="*",
                    default=["2022_general_governor", "2024_general_president"],
                    dest="river_elections",
                    help="Elections to generate river charts for (format: YYYY_type_office)")
    args = ap.parse_args()

    if not DB_URL:
        print("ERROR: DATABASE_URL not set.")
        sys.exit(1)

    plan_id = args.run_name

    # Output directory
    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        out_dir = (Path(__file__).resolve().parent.parent
                   / "data/repos/main/ensemble/charts")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nGenerating benchmark charts for: {plan_id}")
    print(f"Output directory: {out_dir}")

    # Load data
    print("\nLoading draw stats…")
    df = load_draw_stats(plan_id)
    if df.empty:
        print(f"ERROR: no draw stats found for '{plan_id}'.")
        print("  Run: uv run --project fdp python fdp/scripts/build_draw_stats.py --run-name " + plan_id)
        sys.exit(1)

    print("Loading demographic stats…")
    demo_df = load_demographic_draw_stats(plan_id)

    # Chart 1: Partisan histograms
    print("\nGenerating charts…")
    chart_partisan(df, plan_id,
                   out_dir / f"{plan_id}_partisan.png")

    # Chart 2: Competitiveness histograms
    chart_competitiveness(df, plan_id,
                          out_dir / f"{plan_id}_competitiveness.png")

    # Chart 3: Demographic histograms
    if not demo_df.empty:
        chart_demographics(demo_df, plan_id,
                           out_dir / f"{plan_id}_demographics.png")
    else:
        print("  WARNING: no demographic data — skipping demographics chart")
        print("  Run: score_ensemble_demographics.py first")

    # Chart 4: River charts
    for elec_str in args.river_elections:
        parts = elec_str.split("_", 2)
        if len(parts) != 3:
            print(f"  WARNING: cannot parse election '{elec_str}' — use YYYY_type_office")
            continue
        year, etype, office = int(parts[0]), parts[1], parts[2]
        fname = f"{plan_id}_river_{elec_str}.png"
        chart_river(plan_id, year, etype, office,
                    out_dir / fname)

    print(f"\n✓ All charts saved to: {out_dir}")
    print("\nFiles:")
    for f in sorted(out_dir.glob(f"{plan_id}_*.png")):
        size_kb = f.stat().st_size // 1024
        print(f"  {f.name}  ({size_kb} kB)")


if __name__ == "__main__":
    main()
