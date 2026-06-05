#!/usr/bin/env python3
"""
build_scorecard.py — Convert GerryChain scored Parquets to canonical scorecard JSON.

The canonical scorecard is the shared data model that allows both GerryChain runs and
ALARM/Harvard pre-computed ensembles to be displayed through the same fdensemble UI.

Output: {data_dir}/{run_name}_scorecard.json
  Grades are pre-computed (Princeton-style) so fdensemble reads them directly
  without needing access to the raw Parquet files.

Usage (from fgdp/ root):
    uv run --project fdp python fdp/scripts/build_scorecard.py --run-name congress_2026_v2
    uv run --project fdp python fdp/scripts/build_scorecard.py --run-name senate_2026_v1
    uv run --project fdp python fdp/scripts/build_scorecard.py --run-name house_2026_v1
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = _SCRIPT_DIR.parent / "data/repos/main/ensemble"

MAJORITY_THRESHOLD = 0.50
COMPETITIVE_THRESHOLD_DEFAULT = 0.05

# Princeton grading constants (mirrors fdensemble/main.py)
_GRADE_ORDER = ["A", "B", "C", "F"]

_METRIC_META: dict[str, tuple] = {
    # key: (label, headline, category, description, higher_is_better)
    "dem_seats": (
        "Seat–Vote Proportionality",
        "Does the seat count reflect how people actually voted?",
        "partisan",
        "In a fair map, the share of seats each party wins should reflect its share "
        "of statewide votes. This metric counts districts projected to lean Democratic "
        "based on each plan's vote patterns — not as a partisan goal, but as a "
        "measuring stick for proportionality. The histogram shows how many "
        "Democratic-leaning seats thousands of neutrally drawn alternative maps "
        "produce. If the enacted map falls far from this range, lines were likely "
        "drawn to systematically over- or under-represent one party.",
        None),
    "efficiency_gap": (
        "Wasted Votes Balance",
        "Are both parties' votes equally effective at winning representation?",
        "partisan",
        "Every election produces 'wasted' votes — votes cast in losing districts "
        "(all wasted) and surplus votes beyond what was needed to win (also wasted). "
        "A fair map wastes votes at roughly equal rates for both parties. The "
        "Efficiency Gap measures the difference: a positive value means one party's "
        "votes are being wasted at a higher rate than the other's — a sign that "
        "district lines are concentrating or dispersing that party's voters "
        "artificially. Developed by Stephanopoulos & McGhee; cited in federal "
        "gerrymandering litigation.",
        None),   # symmetric: values near zero are best; both tails are bad
    "mean_median": (
        "Vote Distribution Symmetry",
        "Does each party need the same number of votes to win a district?",
        "partisan",
        "The Mean-Median difference reveals whether one party's votes are "
        "systematically spread more efficiently across districts than the other's. "
        "When one party wins many districts by modest margins while the other piles "
        "up large majorities in fewer districts, the map gives the first party a "
        "structural seat advantage — even when both parties receive equal votes "
        "statewide. A value near zero means both parties convert votes to seats "
        "at roughly the same rate. A large deviation in either direction is a "
        "signal of asymmetric voter distribution — often a hallmark of gerrymandering.",
        None),   # symmetric: values near zero are best; both tails are bad
    "comp_seats": (
        "Electoral Competitiveness",
        "How many districts give voters a meaningful choice?",
        "competitive",
        f"A competitive district is one where the outcome is genuinely uncertain — "
        f"where the margin between the two parties is within "
        f"{COMPETITIVE_THRESHOLD_DEFAULT*100:.0f} percentage points of 50/50. "
        f"Competitive districts force elected officials to be responsive to a "
        f"broad range of constituents, not just their party base. Maps designed "
        f"to protect incumbents — whether Republican or Democratic — tend to "
        f"minimize competitiveness. This metric asks whether the enacted map "
        f"produces fewer competitive districts than neutral alternatives would.",
        True),
    "maj_black": (
        "Black Community Representation",
        "Do Black voters have the opportunity to elect representatives of their choice?",
        "minority",
        "This counts districts where Black citizens make up more than 50% of the "
        "Citizen Voting Age Population (CVAP). Under Section 2 of the Voting Rights "
        "Act, mapmakers must not draw lines that dilute minority communities' ability "
        "to elect their preferred candidates. The histogram shows how many "
        "majority-Black districts thousands of neutrally drawn alternative maps "
        "produce — establishing what geography alone would naturally support. "
        "The Princeton ensemble test treats deviation in either direction as a "
        "statistical anomaly: too few raises VRA dilution concerns; too many means "
        "the map is also unusual compared to neutral redistricting. "
        "Uses CVAP rather than VAP for precision (excludes non-citizens).",
        None),
    "min_coal": (
        "Minority Coalition Representation",
        "Do communities of color collectively hold electoral influence?",
        "minority",
        "This counts districts where voters of color — Black, Hispanic, Asian, "
        "and others — together make up more than 50% of the Citizen Voting Age "
        "Population. Even when no single racial group holds a majority, communities "
        "of color can collectively influence electoral outcomes. This 'coalition' "
        "measure is increasingly important as Georgia's demographics diversify. "
        "The Princeton ensemble test treats deviation in either direction as anomalous: "
        "the grade reflects statistical distance from neutral redistricting outcomes, "
        "not a policy judgment about the direction of that distance. "
        "Uses 2024 ACS 5-year CVAP estimates.",
        None),
}


def _generate_takeaway(key: str, enacted: float, pct_rank: float, histogram: dict) -> str:
    """
    Generate a factual, non-partisan takeaway sentence based on the metric result.
    States what the enacted map does and which party (if any) benefits — as a
    neutral observation, not an endorsement.
    """
    p50  = histogram["p50"]
    p5   = histogram["p5"]
    p95  = histogram["p95"]
    diff = enacted - p50

    def _outlier_phrase(pr: float) -> str:
        if pr >= 97.5 or pr <= 2.5:
            return "an extreme outlier — this result would occur by chance in fewer than 1 in 40 neutral maps"
        if pr >= 95 or pr <= 5:
            return "outside the normal range for neutral maps"
        if pr >= 90 or pr <= 10:
            return "toward the edge of the normal range"
        return "within the normal range for neutral maps"

    if key == "dem_seats":
        # Use pct_rank as the primary signal — consistent with _seats_grade thresholds.
        # abs(diff) < 0.5 is unreliable: a narrow distribution can produce a low pct_rank
        # even when the enacted value is numerically close to the median.
        if pct_rank >= 40:
            return (f"The enacted map produces {enacted:.0f} Democratic-leaning seats — "
                    f"at the {pct_rank:.0f}th percentile, within the typical range for neutral maps "
                    f"(median: {p50:.0f}, range: {p5:.0f}–{p95:.0f}). "
                    f"No significant seat-count advantage detected for either party.")
        elif pct_rank >= 5:
            return (f"The enacted map produces {enacted:.0f} Democratic-leaning seats — "
                    f"at the {pct_rank:.0f}th percentile, below the neutral median of {p50:.0f} "
                    f"(range: {p5:.0f}–{p95:.0f}). "
                    f"This is {_outlier_phrase(pct_rank)}, suggesting a structural seat advantage for Republicans.")
        else:
            return (f"The enacted map produces {enacted:.0f} Democratic-leaning seats — "
                    f"at the {pct_rank:.0f}th percentile, {_outlier_phrase(pct_rank)}. "
                    f"Neutral alternatives typically produce {p50:.0f} Dem-leaning seats "
                    f"(range: {p5:.0f}–{p95:.0f}). The map gives Republicans a strong structural advantage.")

    elif key == "efficiency_gap":
        # Positive = Republican structural advantage (Dem votes wasted more)
        if abs(diff) < 0.01:
            return (f"Wasted votes are distributed nearly equally between parties "
                    f"(gap: {enacted:.3f}, neutral median: {p50:.3f}). "
                    f"Neither party has a structural vote-efficiency advantage.")
        elif enacted > p50:
            return (f"The enacted map's efficiency gap ({enacted:.3f}) is above the neutral "
                    f"median ({p50:.3f}), at the {pct_rank:.0f}th percentile — "
                    f"{_outlier_phrase(pct_rank)}. Democratic votes are wasted at a higher "
                    f"rate, giving Republicans a structural advantage in translating votes to seats.")
        else:
            return (f"The enacted map's efficiency gap ({enacted:.3f}) is below the neutral "
                    f"median ({p50:.3f}), at the {pct_rank:.0f}th percentile — "
                    f"{_outlier_phrase(pct_rank)}. Republican votes are wasted at a higher "
                    f"rate, giving Democrats a structural advantage in translating votes to seats.")

    elif key == "mean_median":
        # Positive = Republican structural advantage
        if abs(diff) < 0.005:
            return (f"Both parties convert votes to seats at nearly equal rates "
                    f"(mean–median: {enacted:.3f}, neutral median: {p50:.3f}). "
                    f"No systematic asymmetry detected.")
        elif enacted > p50:
            return (f"The mean–median difference ({enacted:.3f}) is above the neutral median "
                    f"({p50:.3f}), at the {pct_rank:.0f}th percentile — "
                    f"{_outlier_phrase(pct_rank)}. Democratic voters are disproportionately "
                    f"concentrated in fewer districts, giving Republicans a more efficient "
                    f"geographic spread of support.")
        else:
            return (f"The mean–median difference ({enacted:.3f}) is below the neutral median "
                    f"({p50:.3f}), at the {pct_rank:.0f}th percentile — "
                    f"{_outlier_phrase(pct_rank)}. Republican voters are disproportionately "
                    f"concentrated in fewer districts, giving Democrats a more efficient "
                    f"geographic spread of support.")

    elif key == "comp_seats":
        if enacted == 0:
            return (f"The enacted map has zero competitive districts within the "
                    f"{COMPETITIVE_THRESHOLD_DEFAULT*100:.0f}pp threshold. "
                    f"At the {pct_rank:.0f}th percentile, this is {_outlier_phrase(pct_rank)}. "
                    f"Every district has a predetermined partisan lean — voters have no "
                    f"meaningful choice in any race.")
        elif pct_rank < 25:
            return (f"The enacted map has just {enacted:.0f} competitive district(s) — "
                    f"fewer than {100-pct_rank:.0f}% of neutral maps. "
                    f"Most voters live in districts where outcomes are predetermined.")
        elif pct_rank > 75:
            return (f"The enacted map has {enacted:.0f} competitive districts — "
                    f"more than most neutral alternatives (neutral range: {p5:.0f}–{p95:.0f}). "
                    f"Voters have meaningful electoral choice in more races than typical.")
        else:
            return (f"The enacted map has {enacted:.0f} competitive district(s), "
                    f"within the typical range for neutral maps ({p5:.0f}–{p95:.0f}).")

    elif key == "maj_black":
        if pct_rank < 10:
            return (f"The enacted map has {enacted:.0f} majority-Black district(s) — "
                    f"fewer than {100-pct_rank:.0f}% of neutral maps "
                    f"(neutral range: {p5:.0f}–{p95:.0f}). "
                    f"This is significantly below what geography alone would suggest, "
                    f"raising potential Voting Rights Act concerns.")
        elif pct_rank > 90:
            return (f"The enacted map has {enacted:.0f} majority-Black district(s) — "
                    f"more than most neutral alternatives (neutral range: {p5:.0f}–{p95:.0f}). "
                    f"Black communities have strong electoral representation opportunity.")
        else:
            return (f"The enacted map has {enacted:.0f} majority-Black district(s), "
                    f"within the typical range for neutral maps ({p5:.0f}–{p95:.0f}).")

    elif key == "min_coal":
        if pct_rank < 10:
            return (f"The enacted map has {enacted:.0f} minority-coalition district(s) — "
                    f"fewer than {100-pct_rank:.0f}% of neutral maps "
                    f"(neutral range: {p5:.0f}–{p95:.0f}). "
                    f"Communities of color have less collective electoral influence "
                    f"than geography alone would support.")
        elif pct_rank > 90:
            return (f"The enacted map has {enacted:.0f} minority-coalition district(s) — "
                    f"more than most neutral alternatives. Communities of color have "
                    f"strong collective electoral influence.")
        else:
            return (f"The enacted map has {enacted:.0f} minority-coalition district(s), "
                    f"within the typical range for neutral maps ({p5:.0f}–{p95:.0f}).")

    else:
        # Generic fallback
        outlier = _outlier_phrase(pct_rank)
        return (f"Enacted value: {enacted:.3f}. Neutral median: {p50:.3f} "
                f"(range: {p5:.3f}–{p95:.3f}). "
                f"At the {pct_rank:.0f}th percentile — {outlier}.")

_OFFICE_LABELS = {
    "president": "President",
    "governor": "Governor",
    "senate": "U.S. Senate",
    "us-house": "U.S. House",
    "state-rep": "State House",
    "composite": "2018–2024 Composite",
}


# ── Princeton grading primitives ───────────────────────────────────────────────

def _pct_rank(dist: np.ndarray, val: float) -> float:
    return float((dist <= val).mean() * 100)


def _ensemble_pass(pct_rank: float) -> bool:
    return 5.0 <= pct_rank <= 95.0


def _comp_grade(pct_rank: float) -> str:
    if pct_rank >= 95: return "A"
    if pct_rank >= 64: return "B"
    if pct_rank >= 5:  return "C"
    return "F"


def _directional_grade(pct_rank: float, higher_is_better: bool) -> str:
    rank = pct_rank if higher_is_better else (100 - pct_rank)
    if rank >= 95: return "A"
    if rank >= 64: return "B"
    if rank >= 5:  return "C"
    return "F"


def _seats_grade(pct_rank: float) -> str:
    """
    Seat-count grade (dem_seats).  Lower = Republican-biased; F only fires below the
    5th-percentile ensemble boundary so the individual card never contradicts a passing
    ensemble badge on the composite panel.
    """
    if pct_rank >= 50: return "A"   # at or above neutral median — no partisan skew
    if pct_rank >= 20: return "B"   # below median but well inside ensemble
    if pct_rank >= 5:  return "C"   # in lower tail of ensemble
    return "F"                       # below 5th-pct — statistical outlier


def _simple_grade(pct_rank: float) -> str:
    """
    Center-band grade for symmetric metrics (minority counts, efficiency gap,
    mean-median).  Values near the neutral median are best; both tails are bad.
    F fires only outside the 5–95 ensemble boundary, consistent with _ensemble_pass.
    """
    dist = abs(pct_rank - 50.0)
    if dist <= 10: return "A"   # pct 40–60: comfortably in the middle
    if dist <= 30: return "B"   # pct 20–80: normal range
    if dist <= 45: return "C"   # pct 5–95:  in ensemble but toward tails
    return "F"                   # outside 5–95: statistical outlier


def _adj(grade: str, delta: int) -> str:
    try:
        i = _GRADE_ORDER.index(grade)
    except ValueError:
        return grade
    return _GRADE_ORDER[max(0, min(len(_GRADE_ORDER) - 1, i - delta))]


def _histogram_data(dist: np.ndarray, enacted: float, n_bins: int = 40) -> dict:
    counts, edges = np.histogram(dist, bins=n_bins)
    return {
        "edges":   [round(float(v), 4) for v in edges],
        "counts":  counts.tolist(),
        "enacted": round(float(enacted), 4),
        "p5":      round(float(np.percentile(dist, 5)),  4),
        "p50":     round(float(np.percentile(dist, 50)), 4),
        "p95":     round(float(np.percentile(dist, 95)), 4),
        "mean":    round(float(np.mean(dist)), 4),
    }


def _metric_entry(key: str, dist: np.ndarray, enacted_val: float) -> dict | None:
    if np.std(dist) < 1e-9:
        return None
    label, headline, category, desc, higher_is_better = _METRIC_META[key]
    pct     = _pct_rank(dist, enacted_val)
    hist    = _histogram_data(dist, enacted_val)

    if key == "dem_seats":
        grade = _seats_grade(pct)    # directional: fewer Dem seats = worse; F only below 5th pct
    elif key == "comp_seats":
        grade = _comp_grade(pct)
    elif higher_is_better is None:
        grade = _simple_grade(pct)   # symmetric: both tails are bad; F only outside 5–95
    else:
        grade = _directional_grade(pct, higher_is_better)

    return {
        "label":       label,
        "headline":    headline,
        "category":    category,
        "description": desc,
        "takeaway":    _generate_takeaway(key, enacted_val, pct, hist),
        "grade":       grade,
        "enacted":     round(float(enacted_val), 4),
        "pct_rank":    round(pct, 1),
        "histogram":   hist,
    }


# ── Per-election metrics ───────────────────────────────────────────────────────

def _build_election_metrics(
    run_name: str,
    data_dir: Path,
    year: int,
    election_type: str,
    office: str,
    conn: duckdb.DuckDBPyConnection,
    competitive_threshold: float,
) -> dict:
    """
    Build grades dict for one election (same format as fdensemble's grades dict).
    Uses draw_stats.parquet for partisan metrics and competitive_counts.parquet
    for competitiveness.
    """
    ds_file = data_dir / f"{run_name}_draw_stats.parquet"

    ds = conn.execute("""
        SELECT draw, dem_seats, efficiency_gap, mean_median
        FROM read_parquet(?)
        WHERE year=? AND election_type=? AND office=?
        ORDER BY draw
    """, [str(ds_file), year, election_type, office]).df()

    sim     = ds[ds["draw"] > 1]
    enacted = ds[ds["draw"] == 1]
    if len(enacted) == 0:
        print(f"    WARNING: no enacted draw (draw=1) found for {year} {office}")
        return {}

    enacted_row = enacted.iloc[0]
    metrics: dict = {}

    for key in ["dem_seats", "efficiency_gap", "mean_median"]:
        dist = sim[key].to_numpy(dtype=float)
        entry = _metric_entry(key, dist, float(enacted_row[key]))
        if entry:
            metrics[key] = entry

    # Competitive seats
    cc_file = data_dir / f"{run_name}_competitive_counts.parquet"
    if cc_file.exists():
        cc = conn.execute("""
            SELECT draw, n_competitive
            FROM read_parquet(?)
            WHERE year=? AND election_type=? AND office=? AND threshold=?
            ORDER BY draw
        """, [str(cc_file), year, election_type, office, competitive_threshold]).df()

        if len(cc) > 0:
            sim_cc     = cc[cc["draw"] > 1]
            enacted_cc = cc[cc["draw"] == 1]
            if len(enacted_cc) > 0:
                dist = sim_cc["n_competitive"].to_numpy(dtype=float)
                entry = _metric_entry("comp_seats", dist, float(enacted_cc["n_competitive"].iloc[0]))
                if entry:
                    entry["threshold"] = competitive_threshold
                    metrics["comp_seats"] = entry

    # partisan_bias is null for GerryChain (we don't compute it)
    metrics["partisan_bias"] = None

    return metrics


# ── River chart ────────────────────────────────────────────────────────────────

def _build_river(
    run_name: str,
    data_dir: Path,
    year: int,
    election_type: str,
    office: str,
    n_districts: int,
    conn: duckdb.DuckDBPyConnection,
) -> dict | None:
    """
    Compute river chart data (p5/p50/p95 per district rank position) using DuckDB.
    For house-scale runs (180 districts × 24k draws = 4.3M rows), DuckDB handles
    the ranking and percentile computation entirely in-process.
    """
    scores_file = data_dir / f"{run_name}_scores.parquet"
    if not scores_file.exists():
        return None

    # Enacted plan sorted by dem_2pv ascending — include district id for labeling
    enacted_df = conn.execute("""
        SELECT district, dem_2pv
        FROM read_parquet(?)
        WHERE year=? AND election_type=? AND office=? AND draw=1
        ORDER BY dem_2pv ASC
    """, [str(scores_file), year, election_type, office]).df()

    if len(enacted_df) == 0:
        return None

    # Ensemble: rank districts within each draw, then percentile across draws
    ribbon_df = conn.execute("""
        WITH ranked AS (
            SELECT draw, dem_2pv,
                   ROW_NUMBER() OVER (PARTITION BY draw ORDER BY dem_2pv) AS rank_pos
            FROM read_parquet(?)
            WHERE year=? AND election_type=? AND office=? AND draw > 1
        )
        SELECT rank_pos,
               PERCENTILE_CONT(0.05) WITHIN GROUP (ORDER BY dem_2pv) AS p5,
               PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY dem_2pv) AS p50,
               PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY dem_2pv) AS p95,
               COUNT(*) AS n_draws
        FROM ranked
        GROUP BY rank_pos
        ORDER BY rank_pos
    """, [str(scores_file), year, election_type, office]).df()

    if len(ribbon_df) == 0:
        return None

    n_draws = int(ribbon_df["n_draws"].iloc[0])

    return {
        "n_districts":        n_districts,
        "n_draws":            n_draws,
        "p5":                 [round(float(v), 4) for v in ribbon_df["p5"]],
        "p50":                [round(float(v), 4) for v in ribbon_df["p50"]],
        "p95":                [round(float(v), 4) for v in ribbon_df["p95"]],
        "enacted":            [round(float(v), 4) for v in enacted_df["dem_2pv"]],
        "enacted_district_ids": [int(v) for v in enacted_df["district"]],
    }


# ── Demographics ───────────────────────────────────────────────────────────────

def _build_demographics(
    run_name: str,
    data_dir: Path,
    conn: duckdb.DuckDBPyConnection,
) -> dict | None:
    demo_file = data_dir / f"{run_name}_demographics.parquet"
    if not demo_file.exists():
        return None

    dd = conn.execute("""
        SELECT draw,
               SUM(CAST(majority_black AS INTEGER))              AS n_maj_black,
               SUM(CAST(majority_minority_coalition AS INTEGER)) AS n_maj_coal
        FROM read_parquet(?)
        GROUP BY draw
        ORDER BY draw
    """, [str(demo_file)]).df()

    sim     = dd[dd["draw"] > 1]
    enacted = dd[dd["draw"] == 1]
    if len(enacted) == 0:
        return None

    enacted_row = enacted.iloc[0]
    metrics: dict = {}

    for key, col in [("maj_black", "n_maj_black"), ("min_coal", "n_maj_coal")]:
        dist = sim[col].astype(float).to_numpy()
        entry = _metric_entry(key, dist, float(enacted_row[col]))
        if entry:
            metrics[key] = entry

    return {
        "source":  "cvap",
        "year":    None,  # populated by caller
        "metrics": metrics,
    }


# ── Composite Princeton grades ─────────────────────────────────────────────────

def _build_composite_grades(
    elections: list[dict],
    demographics: dict | None,
    n_districts: int,
) -> dict:
    """
    Compute Princeton composite grades across elections.
    For GerryChain, partisan_bias is unavailable → normative test defaults to pass.
    Uses the most restrictive (worst) grade across elections for partisan fairness.
    """
    partisan_grades: list[str] = []
    first_e_pass: bool | None = None

    for elec in elections:
        metrics = elec.get("metrics", {})
        ds = metrics.get("dem_seats")
        if ds is None:
            continue

        e_pass = _ensemble_pass(ds["pct_rank"])
        if first_e_pass is None:
            first_e_pass = e_pass

        # No partisan_bias for GerryChain → normative test skipped (conservative: n_pass=True)
        n_pass = True
        g = "A" if (e_pass and n_pass) else "B" if (not e_pass and n_pass) else "C"

        # Competitiveness adjustment
        comp = metrics.get("comp_seats")
        if comp:
            if comp["grade"] == "A": g = _adj(g, +1)
            if comp["grade"] == "F": g = _adj(g, -1)

        partisan_grades.append(g)

    # Use worst grade across elections (most conservative)
    partisan_g: str | None = None
    if partisan_grades:
        worst_idx = max(range(len(partisan_grades)), key=lambda i: _GRADE_ORDER.index(partisan_grades[i]))
        partisan_g = partisan_grades[worst_idx]

    # Competitiveness: first election that has it
    comp_g: str | None = None
    for elec in elections:
        nc = elec.get("metrics", {}).get("comp_seats")
        if nc:
            comp_g = nc["grade"]
            break

    # Demographics
    demo_g: str | None = None
    if demographics:
        mj = demographics.get("metrics", {}).get("min_coal")
        if mj:
            demo_g = mj["grade"]

    result: dict = {}

    if partisan_g:
        e_pass = first_e_pass if first_e_pass is not None else True
        n_elec = len([e for e in elections if e.get("metrics", {}).get("dem_seats")])
        is_composite = n_elec == 1 and elections[0].get("office") == "composite"
        if is_composite:
            benchmark_desc = (
                "Assessed using the Princeton Gerrymandering Project's ensemble test "
                "against a composite partisan benchmark averaging 5 elections: "
                "2018 Governor, 2020 President, 2021 Warnock Senate Runoff, "
                "2022 Governor + Senate (averaged), and 2024 President. "
                "Third-party candidates are excluded (2-party vote shares only). "
                "The ENSEMBLE test checks whether the enacted map falls within the "
                "normal range (5th–95th percentile) of outcomes for thousands of "
                "randomly drawn alternative maps drawn without partisan intent. "
                f"Ensemble: {'✓ PASS — the enacted map is within the normal range' if e_pass else '✗ FAIL — the enacted map produces unusually partisan outcomes compared to neutral alternatives'}. "
                "Note: The normative (cube-law symmetry) test requires a partisan bias "
                "metric not available in GerryChain runs — it is conservatively set to Pass."
            )
        else:
            benchmark_desc = (
                "Assessed using the Princeton Gerrymandering Project's ensemble test "
                "across all elections in this benchmark. "
                "The ENSEMBLE test checks whether the enacted map falls within the "
                "normal range (5th–95th percentile) of outcomes for thousands of "
                "randomly drawn alternative maps — maps that follow all legal "
                "requirements but were drawn without partisan intent. "
                f"Evaluated across {n_elec} elections; the most restrictive result is used. "
                f"Ensemble: {'✓ PASS — the enacted map is within the normal range' if e_pass else '✗ FAIL — the enacted map produces unusually partisan outcomes compared to neutral alternatives'}. "
                "Note: The normative (cube-law symmetry) test requires a partisan bias "
                "metric not available in GerryChain runs — it is conservatively set to Pass."
            )
        result["_partisan_fairness"] = {
            "label":          "Partisan Fairness",
            "grade":          partisan_g,
            "ensemble_pass":  e_pass,
            "normative_pass": True,
            "description":    benchmark_desc,
        }

        overall = partisan_g
        if comp_g == "A": overall = _adj(overall, +1)
        if comp_g == "F": overall = _adj(overall, -1)
        result["_overall"] = {
            "label":       "Overall",
            "grade":       overall,
            "description": (
                "The Overall grade summarizes how the enacted map compares to "
                "thousands of alternative maps drawn without partisan intent. "
                "It starts from the Partisan Fairness grade and adjusts upward "
                "if the map is unusually competitive (more competitive districts "
                "than typical), or downward if it has zero competitive districts. "
                "Geographic quality (compactness, county splits) is not yet "
                "available for GerryChain runs. "
                "An A means the enacted map performs as well as or better than "
                "neutral alternatives — it does not stand out as gerrymandered. "
                "An F means the map produces outcomes that are highly unlikely "
                "to occur by chance in a fair redistricting process."
            ),
        }

    # Geographic: not available for GerryChain (no Polsby-Popper or splits)
    # result["_geographic"] deliberately omitted — frontend skips if absent

    return result


# ── Main scorecard builder ─────────────────────────────────────────────────────

def _build_enacted_districts(
    base_run_name: str,
    data_dir: Path,
    n_districts: int,
    chamber: str,
    river_enacted: list[float] | None,
    river_district_ids: list[int] | None,
    conn: duckdb.DuckDBPyConnection,
) -> list[dict] | None:
    """
    Compute per-district metrics for the enacted plan (draw=1).
    Returns a list of district dicts with id, dem_2pv, total_vap, centroid_lat/lon.
    """
    # Plans parquet: VTD → district assignment for each draw
    # Convention: if base_run_name ends with '_composite', strip it for the plans file.
    plans_run = base_run_name.removesuffix("_composite")
    plans_file = data_dir / f"{plans_run}_plans.parquet"
    if not plans_file.exists():
        return None

    # VTD composite: centroid + VAP per VTD
    vtd_composite_file = data_dir.parent / "vtd" / "vtd_composite.parquet"
    if not vtd_composite_file.exists():
        return None

    # Load enacted plan's VTD → district mapping
    enacted_plan = conn.execute("""
        SELECT geoid AS vtd_geoid, district
        FROM read_parquet(?)
        WHERE draw = 1
    """, [str(plans_file)]).df()

    # Load VTD composite data (centroid + VAP)
    vtd_comp = conn.execute("""
        SELECT GEOID20, VAP_MOD, centroid_lat, centroid_lon
        FROM read_parquet(?)
    """, [str(vtd_composite_file)]).df()

    # Check if centroid columns exist
    if "centroid_lat" not in vtd_comp.columns:
        return None

    # Join: VTD → district + centroid + VAP
    joined = enacted_plan.merge(vtd_comp, left_on="vtd_geoid", right_on="GEOID20", how="inner")

    # Compute VAP-weighted centroid per district
    joined["lat_weighted"] = joined["centroid_lat"] * joined["VAP_MOD"]
    joined["lon_weighted"] = joined["centroid_lon"] * joined["VAP_MOD"]

    district_stats = joined.groupby("district").agg(
        total_vap=("VAP_MOD", "sum"),
        lat_sum=("lat_weighted", "sum"),
        lon_sum=("lon_weighted", "sum"),
    ).reset_index()

    district_stats["centroid_lat"] = (district_stats["lat_sum"] / district_stats["total_vap"]).round(5)
    district_stats["centroid_lon"] = (district_stats["lon_sum"] / district_stats["total_vap"]).round(5)

    # Build district id → dem_2pv mapping from river data (sorted by dem_2pv ascending)
    # river_enacted is already sorted ascending; river_district_ids is the integer district ID in that rank order
    dem_2pv_map: dict[int, float] = {}
    if river_enacted and river_district_ids and len(river_enacted) == n_districts:
        for dist_id, dem_2pv in zip(river_district_ids, river_enacted):
            dem_2pv_map[int(dist_id)] = round(float(dem_2pv), 4)

    districts = []
    for _, row in district_stats.sort_values("district").iterrows():
        dist_int = int(row["district"])
        # Label: for congress use GA-XX format; for others use integer
        if chamber == "congress":
            dist_label = f"GA-{dist_int:02d}"
        else:
            dist_label = str(dist_int)

        districts.append({
            "id":           dist_label,
            "district_num": dist_int,
            "dem_2pv":      dem_2pv_map.get(dist_int, round(float(0.5), 4)),
            "total_vap":    int(row["total_vap"]),
            "centroid_lat": float(row["centroid_lat"]),
            "centroid_lon": float(row["centroid_lon"]),
        })

    return districts if districts else None


def build_scorecard(
    run_name: str,
    data_dir: Path,
    chamber: str | None = None,
    competitive_threshold: float = COMPETITIVE_THRESHOLD_DEFAULT,
    base_run_name: str | None = None,
) -> dict:
    """
    Build the canonical scorecard JSON for a GerryChain scored run.

    Returns the scorecard dict (also written to disk by main()).
    """
    conn = duckdb.connect()
    _base = base_run_name or run_name

    ds_file = data_dir / f"{_base}_draw_stats.parquet"
    if not ds_file.exists():
        raise FileNotFoundError(
            f"draw_stats not found: {ds_file}\n"
            "  Run build_draw_stats.py first:\n"
            "    uv run --project fdp python fdp/scripts/build_draw_stats.py --run-name {run_name}"
        )

    # Discover elections and n_districts
    meta_df = conn.execute("""
        SELECT DISTINCT year, election_type, office,
               MAX(dem_seats + rep_seats + tied_seats) AS n_d
        FROM read_parquet(?)
        WHERE draw = 1
        GROUP BY year, election_type, office
        ORDER BY year, office
    """, [str(ds_file)]).df()

    # Override data-file prefix for all subsequent lookups
    # (river, competitive counts use the same base prefix)
    _orig_run_name = run_name  # output name
    run_name = _base           # data file prefix

    n_districts = int(meta_df["n_d"].max())
    n_draws_total = int(conn.execute(
        "SELECT COUNT(DISTINCT draw) FROM read_parquet(?)", [str(ds_file)]
    ).fetchone()[0])

    if not chamber:
        chamber = {14: "congress", 56: "senate", 180: "house"}.get(n_districts, f"{n_districts}-district")

    print(f"  {n_draws_total:,} draws × {n_districts} districts × {len(meta_df)} elections")

    # Build per-election data
    elections: list[dict] = []
    for _, row in meta_df.iterrows():
        year          = int(row["year"])
        election_type = str(row["election_type"])
        office        = str(row["office"])
        office_label  = _OFFICE_LABELS.get(office, office.title())
        label         = office_label if office == "composite" else f"{year} {office_label}"

        print(f"  Election: {label}…", end="", flush=True)

        metrics = _build_election_metrics(
            run_name, data_dir, year, election_type, office, conn, competitive_threshold
        )
        river = _build_river(
            run_name, data_dir, year, election_type, office, n_districts, conn
        )

        elections.append({
            "year":           year,
            "election_type":  election_type,
            "office":         office,
            "label":          label,
            "metrics":        metrics,
            "river":          river,
        })
        print(" done")

    # Demographics — composite runs use base run's demographics file
    print("  Demographics…", end="", flush=True)
    demo_run = run_name
    if not (data_dir / f"{run_name}_demographics.parquet").exists():
        base = run_name.removesuffix("_composite")
        if (data_dir / f"{base}_demographics.parquet").exists():
            demo_run = base
    demographics = _build_demographics(demo_run, data_dir, conn)
    if demographics:
        demographics["year"] = 2024  # CVAP 2024 vintage (from ACS 2020–2024 5yr)
    print(" done")

    # Composite grades (includes _partisan_fairness, _overall)
    composite = _build_composite_grades(elections, demographics, n_districts)

    # Add demographics metrics to the grades dict so fdensemble renders them
    grades = {**composite}
    if demographics:
        grades.update(demographics["metrics"])

    # Build enacted plan districts (for Compare tab)
    print("  Enacted districts…", end="", flush=True)
    # Get enacted river data for dem_2pv lookup (sorted by dem_2pv asc)
    river_enacted = None
    river_dist_ids = None
    if elections and elections[0].get("river"):
        rv = elections[0]["river"]
        river_enacted  = rv.get("enacted")
        river_dist_ids = rv.get("enacted_district_ids")

    enacted_districts = _build_enacted_districts(
        _base, data_dir, n_districts, chamber or "unknown",
        river_enacted, river_dist_ids, conn,
    )
    print(f" {len(enacted_districts) if enacted_districts else 0} districts")

    plans = [{
        "id":       "enacted",
        "label":    f"Enacted {chamber.title() if chamber else ''} Map",
        "source":   "catalog",
        "grades":   {k: v for k, v in grades.items() if k.startswith("_")},
        "metrics":  {
            key: {
                "value":    elections[0]["metrics"][key]["enacted"],
                "pct_rank": elections[0]["metrics"][key]["pct_rank"],
                "grade":    elections[0]["metrics"][key]["grade"],
            }
            for key in ["dem_seats", "efficiency_gap", "mean_median", "comp_seats"]
            if elections and key in elections[0].get("metrics", {})
               and elections[0]["metrics"][key] is not None
        },
        "districts": enacted_districts or [],
    }]

    scorecard = {
        "run": {
            "id":          _orig_run_name,
            "name":        _orig_run_name.replace("_", " ").title(),
            "source":      "gerrychain",
            "source_run":  _base,           # underlying parquet prefix
            "chamber":     chamber,
            "n_districts": n_districts,
            "n_draws":     n_draws_total,
            "n_plans":     n_draws_total,  # alias for fdensemble compat
            "algorithm":   "ReCom",
            "date":        date.today().isoformat(),
            "description": (
                f"GerryChain ReCom MCMC ensemble — {chamber} redistricting, "
                f"{n_draws_total:,} draws across {len(elections)} elections."
            ),
            "tags":        ["gerrychain", "recom", chamber],
            "elections":   [
                {"year": e["year"], "election_type": e["election_type"],
                 "office": e["office"], "label": e["label"]}
                for e in elections
            ],
        },
        "elections":    elections,
        "demographics": demographics,
        "compactness":  {"polsby_popper": None, "county_splits": None, "muni_splits": None},
        "grades":       grades,
        "plans":        plans,
    }

    return scorecard


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--run-name", required=True,
                    help="Output run name / scorecard id (e.g. fdga_2026_benchmark_congress)")
    ap.add_argument("--base-run-name", default=None,
                    help="Parquet file prefix if different from --run-name "
                         "(e.g. congress_2026_v2_composite)")
    ap.add_argument("--data-dir", default=None,
                    help=f"Directory containing *_draw_stats.parquet etc. (default: {DEFAULT_DATA_DIR})")
    ap.add_argument("--out", default=None,
                    help="Output JSON path (default: {data_dir}/{run_name}_scorecard.json)")
    ap.add_argument("--chamber", default=None,
                    help="Chamber name — auto-detected from n_districts if omitted")
    ap.add_argument("--competitive-threshold", type=float, default=COMPETITIVE_THRESHOLD_DEFAULT,
                    help=f"Win-margin threshold for competitive seats (default: {COMPETITIVE_THRESHOLD_DEFAULT})")
    args = ap.parse_args()

    data_dir = Path(args.data_dir) if args.data_dir else DEFAULT_DATA_DIR
    out_file = Path(args.out) if args.out else (data_dir / f"{args.run_name}_scorecard.json")

    print(f"Building scorecard: {args.run_name}")
    scorecard = build_scorecard(
        args.run_name, data_dir, args.chamber, args.competitive_threshold,
        base_run_name=args.base_run_name
    )

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(scorecard, indent=2, default=str))
    size_kb = out_file.stat().st_size / 1024

    n_elec = len(scorecard["elections"])
    print(f"\n✓ {out_file.name}  ({size_kb:.0f} KB)")
    print(f"  Overall grade: {scorecard['grades'].get('_overall', {}).get('grade', 'N/A')}")
    print(f"\nCopy scorecard to fdensemble/input_data/ to make it available in the UI:")
    print(f"  cp {out_file} fdensemble/input_data/")


if __name__ == "__main__":
    main()
