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

_SCRIPT_DIR   = Path(__file__).resolve().parent
_REPO_ROOT    = _SCRIPT_DIR.parent.parent          # fgdp/
DEFAULT_DATA_DIR = _SCRIPT_DIR.parent / "data/repos/main/ensemble"

# VTD → municipality lookup (built from ALARM RDS via scripts/build_alarm_scorecard.py)
_VTD_MUNI_PATH = _REPO_ROOT / "fdensemble" / "data" / "vtd_muni.parquet"

COMPETITIVE_THRESHOLD_DEFAULT = 0.05
COMPETITIVE_THRESHOLDS_DEFAULT = [0.035, 0.05]  # 7-point and 10-point margins
INFLUENCE_MIN_THRESHOLD       = 0.37   # minority influence band lower bound (FDGA standard)
INFLUENCE_MAX_THRESHOLD       = 0.50   # minority influence band upper bound

# Demographic threshold slider — precompute per-draw counts at each step for
# maj_black, maj_white, min_coal.  Default display uses 0.50 (true VRA majority).
DEMO_THRESHOLDS        = [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]
DEMO_DEFAULT_THRESHOLD = 0.50   # primary display threshold in the UI
MAJORITY_THRESHOLD = DEMO_DEFAULT_THRESHOLD   # alias imported by build_alarm_scorecard.py

# Princeton grading constants (mirrors fdensemble/main.py)
_GRADE_ORDER = ["A", "B", "C", "F"]

# ── Formula metadata — displayed in info tooltips in fdensemble UI ────────────
# Every entry: formula (plain text), data_source, config_keys (names of
# configurable threshold params shown alongside the formula).
_METRIC_FORMULAS: dict[str, dict] = {
    "dem_seats": {
        "formula":       "count(d : dem_2pv_d ≥ 0.50)",
        "detail":        "dem_2pv_d = Σ dem_votes_vtd / Σ (dem_votes_vtd + rep_votes_vtd) for all VTDs in district d",
        "data_source":   "VTD composite — 2018–2024 six-election equal-weight average (2018 Gov, 2020 Pres, 2021 Warnock runoff, 2022 Gov, 2022 Senate, 2024 Pres)",
        "config_keys":   [],
        "grading_method": "seats (directional, one-sided)",
    },
    "efficiency_gap": {
        "formula":       "(Σ wasted_dem − Σ wasted_rep) / Σ total_votes  across all districts",
        "detail":        "wasted_dem = excess Dem votes beyond 50%+1 in Dem wins + all Dem votes in Dem losses; symmetric for Rep",
        "data_source":   "VTD composite — 2018–2024 six-election equal-weight average (2018 Gov, 2020 Pres, 2021 Warnock runoff, 2022 Gov, 2022 Senate, 2024 Pres)",
        "config_keys":   [],
        "grading_method": "symmetric (both tails bad)",
    },
    "mean_median": {
        "formula":       "mean(dem_2pv_d) − median(dem_2pv_d)  across all d",
        "detail":        "Positive → Dem votes distributed less efficiently across districts (Republican structural advantage). Negative → reverse.",
        "data_source":   "VTD composite — 2018–2024 six-election equal-weight average (2018 Gov, 2020 Pres, 2021 Warnock runoff, 2022 Gov, 2022 Senate, 2024 Pres)",
        "config_keys":   [],
        "grading_method": "symmetric (both tails bad)",
    },
    "comp_seats": {
        "formula":       "count(d : |dem_2pv_d − 0.50| ≤ competitive_margin)",
        "detail":        "A district is competitive if the two-party Democratic share falls within ±competitive_margin of 50%",
        "data_source":   "VTD composite — 2018–2024 six-election equal-weight average (2018 Gov, 2020 Pres, 2021 Warnock runoff, 2022 Gov, 2022 Senate, 2024 Pres)",
        "config_keys":   ["competitive_margin"],
        "grading_method": "competitive (higher = more competitive)",
    },
    "partisan_bias": {
        "formula":       "seats_R(vote=50%) − seats_D(vote=50%)",
        "detail":        "Princeton cube-law normative test: how many more seats one party would win if both parties received exactly 50% of the statewide vote",
        "data_source":   "VTD composite — 2018–2024 composite",
        "config_keys":   [],
        "grading_method": "normative test (Princeton cube-law)",
    },
    "polsby_popper": {
        "formula":       "mean_d(4π × area_d / perimeter_d²)",
        "detail":        "Per-district Polsby-Popper score averaged across all districts. 1 = perfect circle; lower = more irregular",
        "data_source":   "2020 Census VTD geometries (TIGER/Line)",
        "config_keys":   [],
        "grading_method": "directional (higher = more compact)",
    },
    "county_splits": {
        "formula":       "count(counties c : ∃ VTDs v1, v2 ∈ c assigned to different districts)",
        "detail":        "A county is 'split' when at least two of its VTDs are assigned to different congressional/legislative districts",
        "data_source":   "2020 Census county–VTD geographic assignment",
        "config_keys":   [],
        "grading_method": "directional (lower = fewer splits)",
    },
    "muni_splits": {
        "formula":       "count(municipalities m : ∃ VTDs v1, v2 ∈ m assigned to different districts)",
        "detail":        "An incorporated municipality (city, town) is 'split' when at least two of its VTDs are assigned to different districts. Urban cracking indicator.",
        "data_source":   "2020 Census VTD-to-municipality mapping (COUSUBFP)",
        "config_keys":   [],
        "grading_method": "directional (lower = fewer splits)",
    },
    "maj_black": {
        "formula":       "count(d : cvap_blk_d / cvap_tot_d ≥ majority_threshold)",
        "detail":        "Uses 2024 ACS CVAP Special Tabulation (any-part Black CVAP / Total Citizen VAP), aggregated to 2020 VTDs by build_cvap_vtd.py. CVAP is the VRA §2 standard — excludes non-citizen population from the denominator, so Black-opportunity districts correctly show 51-57% rather than 47-49%.",
        "data_source":   "2024 ACS CVAP Special Tabulation (any-part Black CVAP / Total Citizen VAP) — cvap_vtd.parquet",
        "config_keys":   ["bvap_majority_threshold"],
        "grading_method": "directional (higher = better; only shortfalls penalized)",
    },
    "maj_hisp": {
        "formula":       "count(d : bvap_hsp_d / bvap_tot_d ≥ majority_threshold)",
        "detail":        "Hispanic or Latino VAP share per district (2020 Census P0040002)",
        "data_source":   "2020 Census PL 94-171 VAP (Table P4) — ga_pl2020_vtd.zip",
        "config_keys":   ["majority_threshold"],
        "grading_method": "symmetric (standard Princeton — both tails evaluated)",
    },
    "maj_aian": {
        "formula":       "count(d : AIAN_VAP_d / total_VAP_d ≥ majority_threshold)",
        "detail":        "American Indian and Alaska Native VAP share per district",
        "data_source":   "2020 Census PL 94-171 VAP (Table P4) — ga_pl2020_vtd.zip",
        "config_keys":   ["majority_threshold"],
        "grading_method": "symmetric (standard Princeton — both tails evaluated)",
    },
    "maj_asian": {
        "formula":       "count(d : bvap_asn_d / bvap_tot_d ≥ majority_threshold)",
        "detail":        "Asian American VAP share per district (2020 Census P0040008 NH Asian alone)",
        "data_source":   "2020 Census PL 94-171 VAP (Table P4) — ga_pl2020_vtd.zip",
        "config_keys":   ["majority_threshold"],
        "grading_method": "symmetric (standard Princeton — both tails evaluated)",
    },
    "min_coal": {
        "formula":       "count(d : (1 − bvap_wht_d / bvap_tot_d) ≥ majority_threshold)",
        "detail":        "Combined non-white VAP share (1 − NH White fraction). A minority-coalition district includes multiple racial groups, none individually a majority.",
        "data_source":   "2020 Census PL 94-171 VAP (Table P4) — ga_pl2020_vtd.zip",
        "config_keys":   ["majority_threshold"],
        "grading_method": "directional (higher = better; only shortfalls penalized)",
    },
    "maj_white": {
        "formula":       "count(d : bvap_wht_d / bvap_tot_d ≥ majority_threshold)",
        "detail":        "Districts where non-Hispanic white citizens are a majority of eligible voters (2020 Census P0040005). Shown alongside minority metrics to complete the demographic picture.",
        "data_source":   "2020 Census PL 94-171 VAP (Table P4) — ga_pl2020_vtd.zip",
        "config_keys":   ["majority_threshold"],
        "grading_method": "symmetric (both tails notable)",
    },
    "min_influence": {
        "formula":       "count(d : influence_min ≤ (1 − bvap_wht_d / bvap_tot_d) < influence_max)",
        "detail":        "Districts where communities of color have meaningful electoral influence but do not constitute a majority. Below the majority threshold for direct VRA Section 2 protection, but above the FDGA influence floor where minority voters can meaningfully affect outcomes.",
        "data_source":   "2020 Census PL 94-171 VAP (Table P4) — ga_pl2020_vtd.zip",
        "config_keys":   ["influence_min_threshold", "influence_max_threshold"],
        "grading_method": "directional (higher = more influence districts)",
    },
    "dem_safe_seats": {
        "formula":       "count(d : dem_2pv_d > 0.50 + competitive_margin)",
        "detail":        "Democratic-leaning districts outside the competitive zone — margin exceeds threshold on the Democratic side",
        "data_source":   "VTD composite — 2018–2024 composite",
        "config_keys":   ["competitive_margin"],
        "grading_method": "symmetric (both tails notable)",
    },
    "rep_safe_seats": {
        "formula":       "count(d : dem_2pv_d < 0.50 − competitive_margin)",
        "detail":        "Republican-leaning districts outside the competitive zone — margin exceeds threshold on the Republican side",
        "data_source":   "VTD composite — 2018–2024 composite",
        "config_keys":   ["competitive_margin"],
        "grading_method": "symmetric (both tails notable)",
    },
}

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
        "Counts districts where Black Citizen Voting Age Population (CVAP) meets or exceeds the "
        "selected threshold. At 50% (default): traditional VRA Section 2 majority standard — "
        "districts where Black voters can independently elect candidates of their choice. "
        "Slide the threshold down to 20% to see influence districts, where Black voters "
        "hold meaningful but not majority electoral power. "
        "Under Section 2 of the Voting Rights Act, mapmakers must not draw lines that "
        "dilute minority communities' ability to elect their preferred candidates. "
        "The histogram shows how many districts at the selected threshold thousands of "
        "neutrally drawn alternative maps produce. Directional grading: only enacted maps "
        "producing fewer majority-Black districts than neutral alternatives are penalized. "
        "A map that preserves or exceeds the neutral ensemble's Black district count does "
        "not score down. "
        "Uses 2024 ACS CVAP Special Tabulation (any-part Black Citizen VAP / Total Citizen VAP). "
        "CVAP is the VRA §2 standard — excludes non-citizen population from the denominator.",
        True),
    "min_coal": (
        "Minority Coalition Representation",
        "Do communities of color collectively hold electoral influence?",
        "minority",
        "Counts districts where non-white Voting Age Population meets or exceeds the "
        "selected threshold. At 50% (default): districts where communities of color "
        "collectively hold majority electoral power. At 20%: broader influence districts "
        "where diverse communities have meaningful but not majority impact. "
        "Directional grading: only enacted maps producing fewer minority-coalition "
        "districts than neutral alternatives are penalized. "
        "Uses 2024 ACS CVAP Special Tabulation (non-white Citizen VAP / Total Citizen VAP).",
        True),
    "muni_splits": (
        "Split Cities & Municipalities",
        "How many cities and towns are divided across different districts?",
        "geographic",
        "Counts incorporated municipalities (cities, towns) whose territory is split "
        "across two or more congressional districts. Urban cracking — dividing a city "
        "among multiple districts — dilutes its collective political voice and reduces "
        "the ability of city residents to elect a single representative who understands "
        "local concerns. Fewer splits means more communities are kept intact. The neutral "
        "ensemble shows how many splits geography-driven redistricting would typically "
        "produce; the enacted map is compared against this baseline.",
        False),
    "maj_white": (
        "Majority-White Districts",
        "How many districts have a white-citizen majority of eligible voters?",
        "minority",
        "Counts districts where non-Hispanic white Voting Age Population meets or exceeds "
        "the selected threshold. At 50% (default): districts with a true white-citizen "
        "majority of eligible voters. Slide the threshold down to 20% to see districts "
        "where white voters hold strong but not majority influence. "
        "Shown alongside Black and Minority Coalition metrics to complete the full "
        "demographic picture of how the map distributes political power across racial groups. "
        "The Princeton ensemble test grades statistical distance from neutral redistricting "
        "outcomes symmetrically — unusually high or low counts compared to neutral maps "
        "both indicate the map departs from geography-driven redistricting.",
        None),
    "min_influence": (
        "Minority Influence Districts",
        "How many districts give communities of color meaningful electoral influence without a majority?",
        "minority",
        "Counts districts where communities of color collectively hold between the FDGA influence "
        f"floor ({INFLUENCE_MIN_THRESHOLD*100:.0f}%) and the majority threshold "
        f"({INFLUENCE_MAX_THRESHOLD*100:.0f}%) of the Citizen Voting Age Population. "
        "These districts are below the threshold for direct Section 2 Voting Rights Act protection "
        "but above the level at which minority voters can meaningfully influence electoral outcomes "
        "and hold candidates accountable. More influence districts indicates broader minority "
        "electoral participation. Both thresholds are configurable.",
        True),
    "dem_safe_seats": (
        "Safe Democratic Seats",
        "How many districts lean solidly Democratic — beyond the competitive margin?",
        "competitive",
        f"Counts districts where the Democratic two-party vote share exceeds "
        f"50% + {COMPETITIVE_THRESHOLD_DEFAULT*100:.0f}pp — the outer boundary of the competitive zone. "
        "These seats are reliably Democratic and not meaningfully contested. "
        "Together with safe Republican seats and competitive seats, this completes the "
        "three-bucket political balance picture from the scorecard. "
        "An unusually high or low count signals packing or cracking of Democratic voters "
        "relative to what neutral geography-driven redistricting would produce.",
        None),
    "rep_safe_seats": (
        "Safe Republican Seats",
        "How many districts lean solidly Republican — beyond the competitive margin?",
        "competitive",
        f"Counts districts where the Republican two-party vote share exceeds "
        f"50% + {COMPETITIVE_THRESHOLD_DEFAULT*100:.0f}pp — the outer boundary of the competitive zone. "
        "These seats are reliably Republican and not meaningfully contested. "
        "Together with safe Democratic seats and competitive seats, this completes the "
        "three-bucket political balance picture from the scorecard. "
        "An unusually high or low count signals packing or cracking of Republican voters "
        "relative to what neutral geography-driven redistricting would produce.",
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

    elif key == "muni_splits":
        if pct_rank >= 95:
            return (
                f"The enacted map splits {enacted:.0f} cities and municipalities — "
                f"more than {pct_rank:.0f}% of neutral maps "
                f"(typical range: {p5:.0f}–{p95:.0f}). "
                f"This is an extreme outlier: the enacted map cracks far more urban "
                f"communities than geography-driven redistricting would produce. "
                f"Dividing cities dilutes their collective political voice and reduces "
                f"constituent access to a single local representative."
            )
        elif pct_rank >= 75:
            return (
                f"The enacted map splits {enacted:.0f} cities and municipalities — "
                f"more than most neutral alternatives (typical range: {p5:.0f}–{p95:.0f}). "
                f"More urban communities are divided across multiple districts than "
                f"geography-driven redistricting would typically produce."
            )
        elif pct_rank <= 5:
            return (
                f"The enacted map splits just {enacted:.0f} cities and municipalities — "
                f"fewer than {100-pct_rank:.0f}% of neutral maps "
                f"(typical range: {p5:.0f}–{p95:.0f}). "
                f"Urban communities are exceptionally well preserved compared to "
                f"what neutral redistricting would produce."
            )
        elif pct_rank <= 25:
            return (
                f"The enacted map splits {enacted:.0f} cities and municipalities — "
                f"fewer than most neutral alternatives. Urban communities are well "
                f"preserved relative to geography-driven redistricting."
            )
        else:
            return (
                f"The enacted map splits {enacted:.0f} cities and municipalities, "
                f"within the typical range for neutral maps ({p5:.0f}–{p95:.0f})."
            )

    elif key == "maj_white":
        if pct_rank >= 95:
            return (
                f"The enacted map has {enacted:.0f} majority-white districts — "
                f"more than {pct_rank:.0f}% of neutral maps "
                f"(typical range: {p5:.0f}–{p95:.0f}). "
                f"This is statistically unusual and may indicate minority vote dilution "
                f"or cracking of diverse communities."
            )
        elif pct_rank <= 5:
            return (
                f"The enacted map has {enacted:.0f} majority-white districts — "
                f"fewer than {100-pct_rank:.0f}% of neutral maps "
                f"(typical range: {p5:.0f}–{p95:.0f}). "
                f"This is a statistical outlier below the normal range."
            )
        else:
            return (
                f"The enacted map has {enacted:.0f} majority-white district(s), "
                f"within the typical range for neutral maps ({p5:.0f}–{p95:.0f})."
            )

    elif key == "min_influence":
        if pct_rank < 5:
            return (
                f"The enacted map has {enacted:.0f} minority influence district(s) — "
                f"fewer than {100-pct_rank:.0f}% of neutral maps "
                f"(typical range: {p5:.0f}–{p95:.0f}). "
                f"Communities of color have fewer districts where they can meaningfully "
                f"influence electoral outcomes than neutral redistricting would typically produce."
            )
        elif pct_rank >= 95:
            return (
                f"The enacted map has {enacted:.0f} minority influence district(s) — "
                f"more than {pct_rank:.0f}% of neutral maps "
                f"(typical range: {p5:.0f}–{p95:.0f}). "
                f"This is statistically unusual — more districts fall in the influence band "
                f"than geography alone would typically produce."
            )
        elif pct_rank >= 50:
            return (
                f"The enacted map has {enacted:.0f} minority influence district(s) — "
                f"at the {pct_rank:.0f}th percentile, above the neutral median of {p50:.0f}. "
                f"Communities of color have influence in more districts than typical neutral maps."
            )
        else:
            return (
                f"The enacted map has {enacted:.0f} minority influence district(s), "
                f"within the typical range for neutral maps ({p5:.0f}–{p95:.0f})."
            )

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
        "p25":     round(float(np.percentile(dist, 25)), 4),
        "p40":     round(float(np.percentile(dist, 40)), 4),
        "p50":     round(float(np.percentile(dist, 50)), 4),
        "p60":     round(float(np.percentile(dist, 60)), 4),
        "p75":     round(float(np.percentile(dist, 75)), 4),
        "p95":     round(float(np.percentile(dist, 95)), 4),
        "mean":    round(float(np.mean(dist)), 4),
    }


def _a_grade_range(key: str, dist: np.ndarray, higher_is_better) -> dict:
    """Distribution VALUE range corresponding to A-grade (for histogram highlighting)."""
    if key in ("comp_seats", "comp_seats_7pt", "comp_seats_10pt"):
        return {"lo": round(float(np.percentile(dist, 95)), 4), "hi": None}
    elif key in ("dem_seats", "dem_safe_seats"):
        return {"lo": round(float(np.percentile(dist, 50)), 4), "hi": None}
    elif key == "rep_safe_seats":
        return {"lo": round(float(np.percentile(dist, 40)), 4),
                "hi": round(float(np.percentile(dist, 60)), 4)}
    elif higher_is_better is None:
        return {"lo": round(float(np.percentile(dist, 40)), 4),
                "hi": round(float(np.percentile(dist, 60)), 4)}
    elif higher_is_better:
        return {"lo": round(float(np.percentile(dist, 95)), 4), "hi": None}
    else:
        return {"lo": None, "hi": round(float(np.percentile(dist, 5)), 4)}


def _metric_entry(key: str, dist: np.ndarray, enacted_val: float) -> dict | None:
    if np.std(dist) < 1e-9:
        return None
    label, headline, category, desc, higher_is_better = _METRIC_META[key]
    pct     = _pct_rank(dist, enacted_val)
    hist    = _histogram_data(dist, enacted_val)

    if key == "dem_seats":
        grade = _seats_grade(pct)    # directional: fewer Dem seats = worse; F only below 5th pct
    elif key in ("comp_seats", "comp_seats_7pt", "comp_seats_10pt"):
        grade = _comp_grade(pct)
    elif higher_is_better is None:
        grade = _simple_grade(pct)   # symmetric: both tails are bad; F only outside 5–95
    else:
        grade = _directional_grade(pct, higher_is_better)

    # grade_fn tells the frontend which grading function to apply when regrading
    # after ensemble quality filtering. Mirrors the Python grading dispatch above.
    if key == "dem_seats":
        grade_fn = "seats"
    elif key in ("comp_seats", "comp_seats_7pt", "comp_seats_10pt"):
        grade_fn = "comp"
    elif higher_is_better is None:
        grade_fn = "simple"
    else:
        grade_fn = "directional"

    return {
        "label":            label,
        "headline":         headline,
        "category":         category,
        "description":      desc,
        "takeaway":         _generate_takeaway(key, enacted_val, pct, hist),
        "grade":            grade,
        "enacted":          round(float(enacted_val), 4),
        "pct_rank":         round(pct, 1),
        "histogram":        hist,
        "formula_info":     _METRIC_FORMULAS.get(key),
        "a_grade_range":    _a_grade_range(key, dist, higher_is_better),
        # Browser-side quality filter (ensemble quality filter slider)
        "draw_values":      [round(float(v), 4) for v in dist.tolist()],
        "higher_is_better": higher_is_better,
        "grade_fn":         grade_fn,
    }


# ── Per-election metrics ───────────────────────────────────────────────────────

def _build_election_metrics(
    run_name: str,
    data_dir: Path,
    year: int,
    election_type: str,
    office: str,
    conn: duckdb.DuckDBPyConnection,
    competitive_thresholds: list[float],
) -> dict:
    """
    Build grades dict for one election (same format as fdensemble's grades dict).
    Uses draw_stats.parquet for partisan metrics and competitive_counts.parquet
    for competitiveness. Produces comp_seats_7pt and comp_seats_10pt from
    competitive_thresholds[0] and competitive_thresholds[1] respectively.
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

    # Competitive seats — produce named metrics for each threshold
    cc_file = data_dir / f"{run_name}_competitive_counts.parquet"
    _comp_keys = ["comp_seats_7pt", "comp_seats_10pt"]
    if cc_file.exists() and competitive_thresholds:
        for i, t in enumerate(competitive_thresholds[:2]):
            metric_key = _comp_keys[i] if i < len(_comp_keys) else f"comp_seats_t{i}"
            cc = conn.execute("""
                SELECT draw, n_competitive
                FROM read_parquet(?)
                WHERE year=? AND election_type=? AND office=? AND threshold=?
                ORDER BY draw
            """, [str(cc_file), year, election_type, office, t]).df()

            if len(cc) > 0:
                sim_cc     = cc[cc["draw"] > 1]
                enacted_cc = cc[cc["draw"] == 1]
                if len(enacted_cc) > 0:
                    dist = sim_cc["n_competitive"].to_numpy(dtype=float)
                    entry = _metric_entry("comp_seats", dist, float(enacted_cc["n_competitive"].iloc[0]))
                    if entry:
                        entry["threshold"] = t
                        margin_pts = int(round(t * 200))  # ±3.5pp → 7pt, ±5pp → 10pt
                        entry["label"] = f"Electoral Competitiveness ({margin_pts}-pt)"
                        metrics[metric_key] = entry

    # Safe seats — use the most stringent threshold (7-point, index 0)
    safe_threshold = competitive_thresholds[0] if competitive_thresholds else COMPETITIVE_THRESHOLD_DEFAULT
    scores_file = data_dir / f"{run_name}_scores.parquet"
    if scores_file.exists():
        safe = conn.execute("""
            SELECT draw,
                   SUM(CASE WHEN dem_2pv > 0.5 + ? THEN 1 ELSE 0 END) AS dem_safe,
                   SUM(CASE WHEN dem_2pv < 0.5 - ? THEN 1 ELSE 0 END) AS rep_safe
            FROM read_parquet(?)
            WHERE year=? AND election_type=? AND office=?
            GROUP BY draw
            ORDER BY draw
        """, [safe_threshold, safe_threshold,
              str(scores_file), year, election_type, office]).df()

        if len(safe) > 0:
            sim_safe     = safe[safe["draw"] > 1]
            enacted_safe = safe[safe["draw"] == 1]
            if len(enacted_safe) > 0:
                for key, col in [("dem_safe_seats", "dem_safe"), ("rep_safe_seats", "rep_safe")]:
                    dist = sim_safe[col].to_numpy(dtype=float)
                    entry = _metric_entry(key, dist, float(enacted_safe[col].iloc[0]))
                    if entry:
                        entry["threshold"] = safe_threshold
                        metrics[key] = entry

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

def _build_demo_threshold_arrays(
    run_name: str,
    data_dir: Path,
    conn: duckdb.DuckDBPyConnection,
) -> dict:
    """
    Pre-compute per-draw district counts for maj_black, maj_white, min_coal at each
    threshold in DEMO_THRESHOLDS.  Returns a dict keyed by metric name, each containing:
      - "draw_values_by_threshold": { "0.20": [int, ...], "0.30": [...], ..., "0.50": [...] }
      - "enacted_by_threshold":     { "0.20": int, ..., "0.50": int }

    Uses raw pct_black / pct_white / pct_minority_coalition columns from the demographics
    parquet — no re-scoring required; those columns are written by score_ensemble_demographics.py.
    """
    demo_file = data_dir / f"{run_name}_demographics.parquet"
    if not demo_file.exists():
        return {}

    result: dict = {
        "maj_black": {"draw_values_by_threshold": {}, "enacted_by_threshold": {}},
        "maj_white": {"draw_values_by_threshold": {}, "enacted_by_threshold": {}},
        "min_coal":  {"draw_values_by_threshold": {}, "enacted_by_threshold": {}},
    }

    for T in DEMO_THRESHOLDS:
        tkey = f"{T:.2f}"
        df = conn.execute("""
            SELECT draw,
                   SUM(CASE WHEN pct_black              >= ? THEN 1 ELSE 0 END) AS maj_black,
                   SUM(CASE WHEN pct_white              >= ? THEN 1 ELSE 0 END) AS maj_white,
                   SUM(CASE WHEN pct_minority_coalition >= ? THEN 1 ELSE 0 END) AS min_coal
            FROM read_parquet(?)
            GROUP BY draw
            ORDER BY draw
        """, [T, T, T, str(demo_file)]).df()

        sim     = df[df["draw"] > 1]
        enacted = df[df["draw"] == 1]
        enacted_row = enacted.iloc[0] if len(enacted) > 0 else None

        for metric in ("maj_black", "maj_white", "min_coal"):
            result[metric]["draw_values_by_threshold"][tkey] = sim[metric].astype(int).tolist()
            if enacted_row is not None:
                result[metric]["enacted_by_threshold"][tkey] = int(enacted_row[metric])

    return result


def _build_demographics(
    run_name: str,
    data_dir: Path,
    conn: duckdb.DuckDBPyConnection,
    influence_min: float = INFLUENCE_MIN_THRESHOLD,
    influence_max: float = INFLUENCE_MAX_THRESHOLD,
) -> dict | None:
    demo_file = data_dir / f"{run_name}_demographics.parquet"
    if not demo_file.exists():
        return None

    # ── Build threshold arrays for maj_black, maj_white, min_coal ──────────────
    # Uses raw pct columns from the parquet; default display at DEMO_DEFAULT_THRESHOLD.
    threshold_data = _build_demo_threshold_arrays(run_name, data_dir, conn)
    default_key = f"{DEMO_DEFAULT_THRESHOLD:.2f}"

    metrics: dict = {}

    for key in ("maj_black", "maj_white", "min_coal"):
        td = threshold_data.get(key, {})
        draw_vals_default = td.get("draw_values_by_threshold", {}).get(default_key)
        enacted_default   = td.get("enacted_by_threshold", {}).get(default_key)
        if draw_vals_default is None or enacted_default is None:
            continue
        dist  = np.array(draw_vals_default, dtype=float)
        entry = _metric_entry(key, dist, float(enacted_default))
        if entry:
            entry["draw_values_by_threshold"] = td["draw_values_by_threshold"]
            entry["enacted_by_threshold"]     = td["enacted_by_threshold"]
            entry.pop("draw_values", None)   # redundant — draw_values_by_threshold["0.50"] is the canonical source
            metrics[key] = entry

    # ── min_influence — fixed influence band (37–50%), no threshold slider ─────
    dd = conn.execute("""
        SELECT draw,
               SUM(CAST(
                   pct_minority_coalition >= ? AND pct_minority_coalition < ?
               AS INTEGER)) AS n_min_influence
        FROM read_parquet(?)
        GROUP BY draw
        ORDER BY draw
    """, [influence_min, influence_max, str(demo_file)]).df()

    sim_inf     = dd[dd["draw"] > 1]
    enacted_inf = dd[dd["draw"] == 1]
    if len(enacted_inf) > 0:
        dist  = sim_inf["n_min_influence"].astype(float).to_numpy()
        entry = _metric_entry("min_influence", dist, float(enacted_inf.iloc[0]["n_min_influence"]))
        if entry:
            metrics["min_influence"] = entry

    if not metrics:
        return None

    return {
        "source":  "cvap",
        "year":    2024,  # 2024 ACS CVAP Special Tabulation (any-part Black)
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

        # All three partisan metrics must pass the ensemble test.
        # Checking only dem_seats under-reports gerrymandering when geographic
        # self-sorting already creates a structural baseline.
        elec_metrics = metrics
        pm_pcts = {m: elec_metrics[m]["pct_rank"]
                   for m in ("dem_seats", "efficiency_gap", "mean_median")
                   if elec_metrics.get(m)}
        pm_failed = {m: r for m, r in pm_pcts.items() if not _ensemble_pass(r)}
        e_pass = len(pm_failed) == 0
        if first_e_pass is None:
            first_e_pass = e_pass

        # No partisan_bias for GerryChain → normative test skipped (conservative: n_pass=True)
        n_pass = True
        g = "A" if (e_pass and n_pass) else "B" if (not e_pass and n_pass) else "C"

        # Severity downgrade: vote-efficiency metric at extreme tail (>97th or <3rd pctile)
        if not e_pass and any(r > 97 or r < 3 for m, r in pm_failed.items()
                              if m in ("efficiency_gap", "mean_median")):
            g = _adj(g, -1)   # B→C, C→D

        # Competitiveness adjustment — use 7pt (more stringent) primary metric
        comp = metrics.get("comp_seats_7pt") or metrics.get("comp_seats")
        if comp:
            if comp["grade"] == "A": g = _adj(g, +1)
            if comp["grade"] == "F": g = _adj(g, -1)

        partisan_grades.append(g)

    # Use worst grade across elections (most conservative)
    partisan_g: str | None = None
    if partisan_grades:
        worst_idx = max(range(len(partisan_grades)), key=lambda i: _GRADE_ORDER.index(partisan_grades[i]))
        partisan_g = partisan_grades[worst_idx]

    # Competitiveness: use 7pt metric (most stringent)
    comp_g: str | None = None
    for elec in elections:
        m = elec.get("metrics", {})
        nc = m.get("comp_seats_7pt") or m.get("comp_seats")
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


def _build_muni_splits(
    run_name: str,
    data_dir: Path,
    conn: duckdb.DuckDBPyConnection,
) -> tuple[dict | None, pd.DataFrame | None]:
    """
    Compute municipal splits per plan from the GerryChain plans parquet + VTD→muni mapping.

    A municipality is "split" when its VTDs are assigned to 2+ different districts.
    Returns (metric_entry_dict, full_draws_df) where full_draws_df has columns (draw, muni_splits)
    including draw=1 (enacted).  Returns (None, None) if data is unavailable.
    """
    if not _VTD_MUNI_PATH.exists():
        print(f"    [muni_splits] vtd_muni.parquet not found at {_VTD_MUNI_PATH} — skipping")
        return None, None

    # Plans parquet may be the composite run or the underlying base run
    plans_file = data_dir / f"{run_name}_plans.parquet"
    if not plans_file.exists():
        base = run_name.removesuffix("_composite")
        plans_file = data_dir / f"{base}_plans.parquet"
    if not plans_file.exists():
        print(f"    [muni_splits] plans parquet not found for {run_name} — skipping")
        return None, None

    # DuckDB join: for each (draw, muni), count distinct districts
    result = conn.execute("""
        WITH plan_muni AS (
            SELECT p.draw, v.muni_id, p.district
            FROM read_parquet(?) p
            JOIN read_parquet(?) v ON p.geoid = v.geoid
        ),
        muni_by_draw AS (
            SELECT draw, muni_id, COUNT(DISTINCT district) AS n_districts
            FROM plan_muni
            GROUP BY draw, muni_id
        )
        SELECT draw,
               SUM(CASE WHEN n_districts > 1 THEN 1 ELSE 0 END) AS muni_splits
        FROM muni_by_draw
        GROUP BY draw
        ORDER BY draw
    """, [str(plans_file), str(_VTD_MUNI_PATH)]).df()

    if result.empty:
        return None, None

    # draw=1 is the enacted plan in GerryChain parquets
    enacted_row = result[result["draw"] == 1]
    sampled = result[result["draw"] != 1]["muni_splits"].values

    if len(sampled) < 10 or enacted_row.empty:
        return None, None

    enacted_val = float(enacted_row["muni_splits"].iloc[0])
    return _metric_entry("muni_splits", sampled, enacted_val), result[["draw", "muni_splits"]]


def _build_correlations(
    run_name: str,
    data_dir: Path,
    year: int,
    election_type: str,
    office: str,
    competitive_threshold: float,  # single threshold for correlation (use 7pt)
    conn: duckdb.DuckDBPyConnection,
    muni_splits_df: pd.DataFrame | None = None,
    n_scatter: int = 300,
) -> dict | None:
    """
    Compute cross-metric correlation matrix + downsampled scatter pairs for the
    urban-cracking / partisan-bias correlation story.

    Returns { "matrix": {...}, "scatter": {...} } or None if insufficient data.
    The scatter dict uses keys like "muni_splits_vs_dem_seats" with:
        { x[], y[], enacted_x, enacted_y, r }.
    """
    ds_file = data_dir / f"{run_name}_draw_stats.parquet"
    if not ds_file.exists():
        return None

    # Load sim draws for dem_seats, efficiency_gap, mean_median (aligned by draw)
    sim_df = conn.execute("""
        SELECT draw, dem_seats, efficiency_gap, mean_median
        FROM read_parquet(?)
        WHERE year=? AND election_type=? AND office=? AND draw > 1
        ORDER BY draw
    """, [str(ds_file), year, election_type, office]).df()

    if len(sim_df) < 50:
        return None

    enacted_df = conn.execute("""
        SELECT dem_seats, efficiency_gap, mean_median
        FROM read_parquet(?)
        WHERE year=? AND election_type=? AND office=? AND draw = 1
    """, [str(ds_file), year, election_type, office]).df()

    base = sim_df[["draw", "dem_seats", "efficiency_gap", "mean_median"]].copy()
    enacted_vals: dict = {}
    if len(enacted_df) > 0:
        er = enacted_df.iloc[0]
        enacted_vals = {
            "dem_seats":      float(er["dem_seats"]),
            "efficiency_gap": float(er["efficiency_gap"]),
            "mean_median":    float(er["mean_median"]),
        }

    # Join competitive seats by draw
    cc_file = data_dir / f"{run_name}_competitive_counts.parquet"
    if cc_file.exists():
        try:
            cc_sim = conn.execute("""
                SELECT draw, n_competitive
                FROM read_parquet(?)
                WHERE year=? AND election_type=? AND office=? AND threshold=? AND draw > 1
            """, [str(cc_file), year, election_type, office, competitive_threshold]).df()
            cc_enacted = conn.execute("""
                SELECT n_competitive FROM read_parquet(?)
                WHERE year=? AND election_type=? AND office=? AND threshold=? AND draw = 1
            """, [str(cc_file), year, election_type, office, competitive_threshold]).df()
            if len(cc_sim) > 0:
                base = base.merge(
                    cc_sim[["draw", "n_competitive"]].rename(columns={"n_competitive": "comp_seats"}),
                    on="draw", how="inner",
                )
            if len(cc_enacted) > 0:
                enacted_vals["comp_seats"] = float(cc_enacted["n_competitive"].iloc[0])
        except Exception:
            pass

    # Join muni splits by draw (pre-computed to avoid re-running the expensive query)
    if muni_splits_df is not None and not muni_splits_df.empty:
        sim_muni = muni_splits_df[muni_splits_df["draw"] != 1][["draw", "muni_splits"]]
        enacted_muni = muni_splits_df[muni_splits_df["draw"] == 1]
        if not sim_muni.empty:
            base = base.merge(sim_muni, on="draw", how="inner")
        if not enacted_muni.empty:
            enacted_vals["muni_splits"] = float(enacted_muni["muni_splits"].iloc[0])

    keys = [c for c in base.columns if c != "draw"]
    if len(keys) < 2:
        return None

    arrays = {k: base[k].to_numpy(dtype=float) for k in keys}

    # Pearson correlation matrix
    matrix: dict = {}
    for k1 in keys:
        matrix[k1] = {}
        for k2 in keys:
            if k1 == k2:
                matrix[k1][k2] = 1.0
            else:
                r = float(np.corrcoef(arrays[k1], arrays[k2])[0, 1])
                matrix[k1][k2] = round(r, 4) if not np.isnan(r) else None

    # Key scatter pairs for urban-crack story
    scatter_pairs = [
        ("muni_splits",   "dem_seats"),
        ("muni_splits",   "efficiency_gap"),
        ("muni_splits",   "comp_seats"),
        ("dem_seats",     "efficiency_gap"),
    ]

    scatter: dict = {}
    rng = np.random.default_rng(42)
    n = len(next(iter(arrays.values())))
    for x_key, y_key in scatter_pairs:
        if x_key not in arrays or y_key not in arrays:
            continue
        idx = np.sort(rng.choice(n, min(n_scatter, n), replace=False))
        r_val = matrix.get(x_key, {}).get(y_key)
        scatter[f"{x_key}_vs_{y_key}"] = {
            "x":         [round(float(v), 4) for v in arrays[x_key][idx]],
            "y":         [round(float(v), 4) for v in arrays[y_key][idx]],
            "enacted_x": round(float(enacted_vals[x_key]), 4) if x_key in enacted_vals else None,
            "enacted_y": round(float(enacted_vals[y_key]), 4) if y_key in enacted_vals else None,
            "r":         r_val,
        }

    return {"matrix": matrix, "scatter": scatter}


def build_scorecard(
    run_name: str,
    data_dir: Path,
    chamber: str | None = None,
    competitive_thresholds: list[float] | None = None,
    base_run_name: str | None = None,
    influence_min: float = INFLUENCE_MIN_THRESHOLD,
    influence_max: float = INFLUENCE_MAX_THRESHOLD,
    # Legacy single-threshold compat (ignored if competitive_thresholds is set)
    competitive_threshold: float | None = None,
    source: str | None = None,   # "gerrychain" | "alarm" — auto-detected from run_name if None
) -> dict:
    """
    Build the canonical scorecard JSON for a GerryChain or ALARM SMC scored run.

    Returns the scorecard dict (also written to disk by main()).
    """
    # Auto-detect source from run name if not provided
    if source is None:
        source = "alarm" if "_alarm" in run_name.lower() else "gerrychain"
    if competitive_thresholds is None:
        if competitive_threshold is not None:
            competitive_thresholds = [competitive_threshold]
        else:
            competitive_thresholds = COMPETITIVE_THRESHOLDS_DEFAULT

    conn = duckdb.connect()
    _base = base_run_name or run_name

    ds_file = data_dir / f"{_base}_draw_stats.parquet"
    if not ds_file.exists():
        raise FileNotFoundError(
            f"draw_stats not found: {ds_file}\n"
            "  Run build_draw_stats.py first:\n"
            "    uv run --project fdp python fdp/scripts/build_draw_stats.py --run-name {run_name}"
        )

    # Discover elections to include in the scorecard.
    # Priority: use composite if available (single aggregate entry); fall back to all.
    # The composite row has year=0 and office='composite' — it's the primary view.
    _meta_all = conn.execute("""
        SELECT DISTINCT year, election_type, office,
               MAX(dem_seats + rep_seats + tied_seats) AS n_d
        FROM read_parquet(?)
        WHERE draw = 1
        GROUP BY year, election_type, office
        ORDER BY year, office
    """, [str(ds_file)]).df()

    _has_composite = "composite" in _meta_all["office"].values
    if _has_composite:
        # Use composite only — hides per-election clutter from the scorecard UI
        meta_df = _meta_all[_meta_all["office"] == "composite"].copy()
    else:
        # Legacy: no composite available, show all elections
        meta_df = _meta_all

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
            run_name, data_dir, year, election_type, office, conn, competitive_thresholds
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
    demographics = _build_demographics(
        demo_run, data_dir, conn,
        influence_min=influence_min,
        influence_max=influence_max,
    )
    print(" done")

    # Municipal splits
    print("  Municipal splits…", end="", flush=True)
    muni_splits_entry, muni_splits_df = _build_muni_splits(run_name, data_dir, conn)
    print(f" {muni_splits_entry['enacted']:.0f} splits (grade {muni_splits_entry['grade']})" if muni_splits_entry else " n/a")

    # Correlations — cross-metric scatter and Pearson r matrix for urban-crack story
    print("  Correlations…", end="", flush=True)
    correlations: dict | None = None
    if elections:
        corr_elec = next((e for e in elections if e["office"] == "composite"), elections[0])
        try:
            correlations = _build_correlations(
                run_name, data_dir,
                corr_elec["year"], corr_elec["election_type"], corr_elec["office"],
                competitive_thresholds[0], conn,
                muni_splits_df=muni_splits_df,
            )
        except Exception as exc:
            print(f" WARNING: {exc}", end="")
    n_pairs = len(correlations["scatter"]) if correlations else 0
    print(f" {n_pairs} scatter pairs" if correlations else " n/a")

    # Composite grades (_partisan_fairness, _overall) are intentionally NOT stored
    # in the scorecard JSON.  They are derived interpretation, not raw data.
    # fdensemble always recomputes them at serve time via _compute_composite_grades()
    # so there is exactly one implementation of grading logic.
    # _build_composite_grades() is called once below for the build-time summary print.

    # grades dict: demographics metrics + geographic metrics only (no composites)
    grades: dict = {}
    if demographics:
        grades.update(demographics["metrics"])
    if muni_splits_entry:
        grades["muni_splits"] = muni_splits_entry

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
        # Composite grades (_partisan_fairness, _overall) intentionally omitted —
        # fdensemble recomputes them at serve time via _compute_composite_grades().
        "grades":   {},
        "metrics":  {
            key: {
                "value":    elections[0]["metrics"][key]["enacted"],
                "pct_rank": elections[0]["metrics"][key]["pct_rank"],
                "grade":    elections[0]["metrics"][key]["grade"],
            }
            for key in ["dem_seats", "efficiency_gap", "mean_median",
                        "comp_seats_7pt", "comp_seats_10pt",
                        "dem_safe_seats", "rep_safe_seats"]
            if elections and key in elections[0].get("metrics", {})
               and elections[0]["metrics"][key] is not None
        },
        "districts": enacted_districts or [],
    }]

    scorecard = {
        "run": {
            "id":          _orig_run_name,
            "name":        _orig_run_name.replace("_", " ").title(),
            "source":      source,
            "source_run":  _base,           # underlying parquet prefix
            "chamber":     chamber,
            "n_districts": n_districts,
            "n_draws":     n_draws_total,
            "n_plans":     n_draws_total,  # alias for fdensemble compat
            "algorithm":   "SMC" if source == "alarm" else "ReCom",
            "date":        date.today().isoformat(),
            "description": (
                (
                    f"ALARM SMC ensemble — {chamber} redistricting, "
                    f"{n_draws_total:,} plans via independent SMC chains across {len(elections)} elections."
                ) if source == "alarm" else (
                    f"GerryChain ReCom MCMC ensemble — {chamber} redistricting, "
                    f"{n_draws_total:,} draws across {len(elections)} elections."
                )
            ),
            "tags":        [source, "smc" if source == "alarm" else "recom", chamber],
            "elections":   [
                {"year": e["year"], "election_type": e["election_type"],
                 "office": e["office"], "label": e["label"]}
                for e in elections
            ],
            # Configurable threshold values used — surfaced in UI info tooltips
            "config": {
                "competitive_thresholds":   competitive_thresholds,
                "influence_min_threshold":  influence_min,
                "influence_max_threshold":  influence_max,
            },
        },
        "elections":    elections,
        "demographics": demographics,
        "compactness":  {"polsby_popper": None, "county_splits": None,
                         "muni_splits": muni_splits_entry},
        "grades":       grades,
        "plans":        plans,
        "correlations": correlations,
        "config": {
            "competitive_thresholds":  competitive_thresholds,
            "influence_min_threshold": influence_min,
            "influence_max_threshold": influence_max,
            "grading": {
                "ensemble_pass_lo":      5,
                "ensemble_pass_hi":      95,
                "seats_grade_a_pct":     50,
                "seats_grade_b_pct":     20,
                "comp_grade_a_pct":      95,
                "symmetric_a_band":      10,
                "symmetric_b_band":      30,
                "directional_a_pct":     95,
                "directional_b_pct":     64,
            },
            "source_locations": {
                "competitive_thresholds":  "fdp/configs/benchmarks/*.yml → competitiveness.thresholds",
                "influence_min_threshold": "fdp/scripts/build_scorecard.py → INFLUENCE_MIN_THRESHOLD",
                "influence_max_threshold": "fdp/scripts/build_scorecard.py → INFLUENCE_MAX_THRESHOLD",
            },
        },
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
    ap.add_argument("--competitive-thresholds", nargs="+", type=float,
                    default=COMPETITIVE_THRESHOLDS_DEFAULT, dest="competitive_thresholds",
                    help=f"Win-margin thresholds for competitive seats — 7pt and 10pt "
                         f"(default: {COMPETITIVE_THRESHOLDS_DEFAULT})")
    ap.add_argument("--influence-min", type=float, default=INFLUENCE_MIN_THRESHOLD,
                    help=f"Minority influence district lower bound (default: {INFLUENCE_MIN_THRESHOLD} = {INFLUENCE_MIN_THRESHOLD*100:.0f}%%)")
    ap.add_argument("--influence-max", type=float, default=INFLUENCE_MAX_THRESHOLD,
                    help=f"Minority influence district upper bound (default: {INFLUENCE_MAX_THRESHOLD} = {INFLUENCE_MAX_THRESHOLD*100:.0f}%%)")
    ap.add_argument("--source", default=None, choices=["gerrychain", "alarm"],
                    help="Ensemble source (auto-detected from run_name if omitted: '_alarm' → alarm, else gerrychain)")
    args = ap.parse_args()

    data_dir = Path(args.data_dir) if args.data_dir else DEFAULT_DATA_DIR
    out_file = Path(args.out) if args.out else (data_dir / f"{args.run_name}_scorecard.json")

    print(f"Building scorecard: {args.run_name}")
    scorecard = build_scorecard(
        args.run_name, data_dir, args.chamber,
        competitive_thresholds=args.competitive_thresholds,
        base_run_name=args.base_run_name,
        influence_min=args.influence_min,
        influence_max=args.influence_max,
        source=args.source,
    )

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(scorecard, separators=(',', ':'), default=str))
    size_kb = out_file.stat().st_size / 1024

    n_elec = len(scorecard["elections"])
    print(f"\n✓ {out_file.name}  ({size_kb:.0f} KB)")
    _cd = _build_composite_grades(
        scorecard["elections"], scorecard.get("demographics"),
        scorecard["run"]["n_districts"],
    )
    print(f"  Overall grade (build-time estimate): {_cd.get('_overall', {}).get('grade', 'N/A')}")
    print(f"\nCopy scorecard to fdensemble/input_data/ to make it available in the UI:")
    print(f"  cp {out_file} fdensemble/input_data/")


if __name__ == "__main__":
    main()
