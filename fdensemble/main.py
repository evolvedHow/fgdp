import argparse, io, json, mimetypes, os, uuid
from datetime import datetime
from pathlib import Path

# python:3.12-slim ships without the OS mime database; register manually so
# FastAPI StaticFiles serves JS/CSS with correct Content-Type headers.
mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('text/css',               '.css')
mimetypes.add_type('image/svg+xml',          '.svg')
mimetypes.add_type('application/json',       '.json')

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

load_dotenv()

# ── FDP platform client (fdp-first architecture) ──────────────────────────────
# fdp_client wraps the FDP REST API when FDPAPI_BASE env var is set.
# Falls back to local ALARM dataverse files when FDPAPI_BASE is not set (current default).
# See fdp_client.py for migration details and prerequisites.
from fdp_client import using_api, health_check as _fdp_health  # noqa: E402

if using_api():
    import logging as _logging
    _logging.getLogger(__name__).info(
        "FDP API mode active — data will be fetched from %s",
        __import__("os").environ.get("FDPAPI_BASE"),
    )

# ── Config ────────────────────────────────────────────────────────────────────
STATE                   = os.getenv('STATE', 'GA')
PLAN_TYPE               = os.getenv('PLAN_TYPE', 'cd')
PLAN_YEAR               = os.getenv('PLAN_YEAR', '2020')
N_DISTRICTS             = int(os.getenv('N_DISTRICTS', '14'))
ENACTED_PLAN_LABEL      = os.getenv('ENACTED_PLAN_LABEL', 'cd_2020')
DATA_DIR                = Path(os.getenv('DATA_DIR', 'dataverse_files/GA_cd_2020'))
RUNS_DIR                = Path(os.getenv('RUNS_DIR', 'runs'))
MAPS_DIR                = Path(os.getenv('MAPS_DIR', 'uploaded_maps'))
COMPETITIVE_MARGIN      = float(os.getenv('COMPETITIVE_MARGIN_MAIN', '0.07'))
BVAP_THRESHOLD          = float(os.getenv('BVAP_MAJORITY_THRESHOLD', '0.50'))
MINORITY_THRESHOLD      = float(os.getenv('MAJORITY_THRESHOLD', '0.50'))
DEM_COLOR               = os.getenv('DEM_COLOR', '#3D77BB')
FIG_DPI                 = int(os.getenv('FIG_DPI', '120'))

_DATAVERSE_DOI = 'doi:10.7910/DVN/SLCD3E'
_STATE_NAMES = {
    'GA': 'Georgia', 'TX': 'Texas', 'FL': 'Florida', 'NC': 'North Carolina',
    'PA': 'Pennsylvania', 'OH': 'Ohio', 'VA': 'Virginia', 'MI': 'Michigan',
    'WI': 'Wisconsin', 'AZ': 'Arizona', 'NV': 'Nevada', 'CO': 'Colorado',
}
STATE_FULL = _STATE_NAMES.get(STATE, STATE)

# ── Default column mapping (ALARM stats CSV names) ────────────────────────────
# Override individual keys in meta.json "columns" to support future ALARM releases.
_DEFAULT_COLS = {
    'dem_seats':      'e_dem',
    'partisan_bias':  'pbias',
    'efficiency_gap': 'egap',
    'dem_share':      'ndshare',
    'county_splits':  'county_splits',
    'muni_splits':    'muni_splits',
    'polsby_popper':  'comp_polsby',
    'vap_total':      'total_vap',
    'vap_black':      'vap_black',
    'vap_hisp':       'vap_hisp',
    'vap_aian':       'vap_aian',
    'vap_asian':      'vap_asian',
    'vap_nhpi':       'vap_nhpi',
    'dem_votes':      'ndv',
    'rep_votes':      'nrv',
}


def _col(df: pd.DataFrame, mapping: dict, key: str):
    name = mapping.get(key, _DEFAULT_COLS.get(key, key))
    return df[name] if name in df.columns else None


# ── Princeton grading primitives ──────────────────────────────────────────────
_GRADE_ORDER = ['A', 'B', 'C', 'F']


def _pct_rank(dist: np.ndarray, val: float) -> float:
    return float((dist <= val).mean() * 100)


def _ensemble_pass(pct_rank: float) -> bool:
    """Plan is within 5th–95th percentile of ensemble."""
    return 5.0 <= pct_rank <= 95.0


def _normative_pass(pbias: float, n: int) -> bool:
    """Cube-law symmetry: |partisan bias| within leeway = max(1, 7%×n) / n."""
    leeway = max(1.0, 0.07 * n) / n
    return abs(pbias) <= leeway


def _partisan_grade(e_pass: bool, n_pass: bool) -> str:
    """Princeton 2×2 intersection table."""
    if e_pass and n_pass:      return 'A'
    if (not e_pass) and n_pass: return 'B'
    if e_pass and (not n_pass): return 'C'
    return 'F'


def _adj(grade: str, delta: int) -> str:
    """Shift grade by delta positions (+1 = improve, -1 = worsen)."""
    try:
        i = _GRADE_ORDER.index(grade)
    except ValueError:
        return grade
    return _GRADE_ORDER[max(0, min(len(_GRADE_ORDER) - 1, i - delta))]


def _comp_grade(pct_rank: float) -> str:
    """Higher competitive seats = better."""
    if pct_rank >= 95: return 'A'
    if pct_rank >= 64: return 'B'
    if pct_rank >= 5:  return 'C'
    return 'F'


def _directional_grade(pct_rank: float, higher_is_better: bool) -> str:
    """For compactness (higher=better) and splits (lower=better)."""
    rank = pct_rank if higher_is_better else (100 - pct_rank)
    if rank >= 95: return 'A'
    if rank >= 64: return 'B'
    if rank >= 5:  return 'C'
    return 'F'


def _seats_grade(pct_rank: float) -> str:
    """
    Seat-count grade (dem_seats).  Lower = Republican-biased; F only fires below the
    5th-percentile ensemble boundary so the individual card never contradicts a passing
    ensemble badge on the composite panel.
    """
    if pct_rank >= 50: return 'A'   # at or above neutral median — no partisan skew
    if pct_rank >= 20: return 'B'   # below median but well inside ensemble
    if pct_rank >= 5:  return 'C'   # in lower tail of ensemble
    return 'F'                       # below 5th-pct — statistical outlier


def _geo_grade(comp_g: str, splits_g: str) -> str:
    """Princeton geo combination: A+A=A, A+C or C+A=B, F+F=F, else C."""
    if comp_g == 'A' and splits_g == 'A':             return 'A'
    if comp_g == 'F' and splits_g == 'F':             return 'F'
    if {comp_g, splits_g} == {'A', 'C'}:              return 'B'
    return 'C'


def _histogram_data(dist: np.ndarray, enacted, n_bins: int = 40) -> dict:
    # Extend range to always include the enacted value — without this, an
    # enacted plan that falls outside the ensemble range produces no bin match
    # and the enacted marker disappears from the histogram.
    if enacted is not None:
        lo = min(float(dist.min()), float(enacted))
        hi = max(float(dist.max()), float(enacted))
        if lo == hi:
            lo -= 0.5; hi += 0.5
        counts, edges = np.histogram(dist, bins=n_bins, range=(lo, hi))
    else:
        counts, edges = np.histogram(dist, bins=n_bins)
    return {
        'edges':   [round(float(v), 4) for v in edges],
        'counts':  counts.tolist(),
        'enacted': round(float(enacted), 4) if enacted is not None else None,
        'p5':      round(float(np.percentile(dist, 5)),  4),
        'p50':     round(float(np.percentile(dist, 50)), 4),
        'p95':     round(float(np.percentile(dist, 95)), 4),
        'mean':    round(float(np.mean(dist)), 4),
    }


# ── Metric definitions ────────────────────────────────────────────────────────
def _generate_takeaway(key: str, enacted: float, pct_rank: float, histogram: dict) -> str:
    """
    Generate a factual, non-partisan takeaway for a metric result.
    States the finding and which party (if any) structurally benefits — as
    neutral observation, not endorsement.
    """
    p50  = histogram.get("p50", 0)
    p5   = histogram.get("p5", 0)
    p95  = histogram.get("p95", 0)
    diff = enacted - p50

    def _outlier_phrase(pr: float) -> str:
        if pr >= 97.5 or pr <= 2.5:
            return "an extreme outlier — this result would occur in fewer than 1 in 40 neutral maps"
        if pr >= 95 or pr <= 5:
            return "outside the normal range for neutral maps"
        if pr >= 90 or pr <= 10:
            return "toward the edge of the normal range"
        return "within the normal range for neutral maps"

    if key == "dem_seats":
        # Primary signal is pct_rank, which matches _seats_grade thresholds exactly.
        # (Using abs(diff) < 0.5 was misleading: a narrow distribution can produce
        #  a low pct_rank even when the enacted value is numerically near the median.)
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
        if abs(diff) < 0.005:
            return (f"Both parties convert votes to seats at nearly equal rates "
                    f"(mean–median: {enacted:.3f}, neutral median: {p50:.3f}). "
                    f"No systematic asymmetry detected.")
        elif enacted > p50:
            return (f"The mean–median difference ({enacted:.3f}) is above the neutral median "
                    f"({p50:.3f}), at the {pct_rank:.0f}th percentile — "
                    f"{_outlier_phrase(pct_rank)}. Democratic voters are disproportionately "
                    f"concentrated, giving Republicans a more efficient geographic spread of support.")
        else:
            return (f"The mean–median difference ({enacted:.3f}) is below the neutral median "
                    f"({p50:.3f}), at the {pct_rank:.0f}th percentile — "
                    f"{_outlier_phrase(pct_rank)}. Republican voters are disproportionately "
                    f"concentrated, giving Democrats a more efficient geographic spread of support.")

    elif key == "comp_seats":
        if enacted == 0:
            return (f"The enacted map has zero competitive districts. "
                    f"At the {pct_rank:.0f}th percentile, this is {_outlier_phrase(pct_rank)}. "
                    f"Every district has a predetermined partisan lean — voters have no "
                    f"meaningful choice in any race.")
        elif pct_rank < 25:
            return (f"The enacted map has just {enacted:.0f} competitive district(s) — "
                    f"fewer than {100-pct_rank:.0f}% of neutral maps. "
                    f"Most voters live in districts where outcomes are predetermined.")
        elif pct_rank > 75:
            return (f"The enacted map has {enacted:.0f} competitive districts — "
                    f"more than most neutral alternatives. "
                    f"Voters have meaningful choice in more races than typical.")
        else:
            return (f"The enacted map has {enacted:.0f} competitive district(s), "
                    f"within the typical range for neutral maps ({p5:.0f}–{p95:.0f}).")

    elif key == "partisan_bias":
        # Use the same leeway threshold as _normative_pass for consistency.
        n_leeway = max(1.0, 0.07 * N_DISTRICTS) / N_DISTRICTS
        if abs(enacted) <= n_leeway:
            return (f"At a tied 50/50 election, both parties would win seats at nearly "
                    f"equal rates (bias: {enacted:.3f}, within the ±{n_leeway:.2f} symmetry threshold). "
                    f"The map passes the cube-law normative test.")
        elif enacted > 0:
            return (f"At a tied 50/50 election, Republicans would win more seats than "
                    f"Democrats (bias: {enacted:.3f}, at the {pct_rank:.0f}th percentile — "
                    f"{_outlier_phrase(pct_rank)}). The map structurally favors Republicans.")
        else:
            return (f"At a tied 50/50 election, Democrats would win more seats than "
                    f"Republicans (bias: {enacted:.3f}, at the {pct_rank:.0f}th percentile — "
                    f"{_outlier_phrase(pct_rank)}). The map structurally favors Democrats.")

    elif key == "polsby_popper":
        if pct_rank > 75:
            return (f"Districts are compact (score: {enacted:.3f}) — more so than "
                    f"{pct_rank:.0f}% of neutral alternatives. Shape alone does not "
                    f"indicate manipulation.")
        elif pct_rank < 25:
            return (f"Districts are less compact than typical (score: {enacted:.3f}), "
                    f"below {100-pct_rank:.0f}% of neutral alternatives. "
                    f"Unusual shapes may warrant further scrutiny.")
        else:
            return (f"District compactness (score: {enacted:.3f}) is within the typical range. "
                    f"Shape alone does not indicate manipulation.")

    elif key in ("county_splits", "muni_splits"):
        unit = "county" if key == "county_splits" else "municipal"
        if pct_rank < 25:
            return (f"The enacted map splits {enacted:.0f} {unit} boundaries — "
                    f"fewer than most neutral alternatives. Communities are kept more intact.")
        elif pct_rank > 75:
            return (f"The enacted map splits {enacted:.0f} {unit} boundaries — "
                    f"more than most neutral alternatives ({pct_rank:.0f}th percentile). "
                    f"More communities are divided across multiple districts.")
        else:
            return (f"The enacted map splits {enacted:.0f} {unit} boundaries, "
                    f"within the typical range for neutral maps ({p5:.0f}–{p95:.0f}).")

    elif key == "maj_black":
        if pct_rank < 5:
            return (f"The enacted map has {enacted:.0f} majority-Black district(s) — "
                    f"fewer than {100-pct_rank:.0f}% of neutral maps "
                    f"(typical range: {p5:.0f}–{p95:.0f}). "
                    f"This falls far below what geography alone would support, "
                    f"raising serious Voting Rights Act concerns.")
        elif pct_rank < 50:
            return (f"The enacted map has {enacted:.0f} majority-Black district(s) — "
                    f"below the neutral median of {p50:.0f} (typical: {p5:.0f}–{p95:.0f}). "
                    f"Representation opportunity is below what neutral mapmaking would produce.")
        elif pct_rank >= 85:
            return (f"The enacted map has {enacted:.0f} majority-Black district(s) — "
                    f"more than {pct_rank:.0f}% of neutral maps (neutral median: {p50:.0f}). "
                    f"Black communities have stronger representation opportunity than "
                    f"neutral mapmaking alone would produce.")
        else:
            return (f"The enacted map has {enacted:.0f} majority-Black district(s), "
                    f"within the typical range ({p5:.0f}–{p95:.0f}) for neutral maps.")

    elif key in ("maj_hisp", "maj_aian", "maj_asian"):
        groups = {"maj_hisp": "Hispanic", "maj_aian": "Indigenous", "maj_asian": "Asian American"}
        group = groups.get(key, "minority")
        if pct_rank < 5:
            return (f"The enacted map has {enacted:.0f} majority-{group} district(s) — "
                    f"fewer than {100-pct_rank:.0f}% of neutral maps. "
                    f"This raises serious Voting Rights Act compliance concerns.")
        elif pct_rank < 50:
            return (f"The enacted map has {enacted:.0f} majority-{group} district(s) — "
                    f"below the neutral median of {p50:.0f} (typical: {p5:.0f}–{p95:.0f}). "
                    f"Representation opportunity is below what neutral mapmaking would support.")
        elif pct_rank >= 85:
            return (f"The enacted map has {enacted:.0f} majority-{group} district(s) — "
                    f"more than {pct_rank:.0f}% of neutral maps (neutral median: {p50:.0f}). "
                    f"{group} communities have stronger representation opportunity than "
                    f"neutral mapmaking alone would produce.")
        else:
            return (f"The enacted map has {enacted:.0f} majority-{group} district(s), "
                    f"within the typical range ({p5:.0f}–{p95:.0f}).")

    elif key == "min_coal":
        if pct_rank < 5:
            return (f"The enacted map has {enacted:.0f} minority-coalition district(s) — "
                    f"fewer than {100-pct_rank:.0f}% of neutral maps "
                    f"(typical: {p5:.0f}–{p95:.0f}). Communities of color have "
                    f"significantly less collective electoral influence than geography would support, "
                    f"raising Voting Rights Act concerns.")
        elif pct_rank < 50:
            return (f"The enacted map has {enacted:.0f} minority-coalition district(s) — "
                    f"below the neutral median of {p50:.0f} (typical: {p5:.0f}–{p95:.0f}). "
                    f"The collective political voice of communities of color is below "
                    f"what neutral mapmaking would produce.")
        elif pct_rank >= 85:
            return (f"The enacted map has {enacted:.0f} minority-coalition district(s) — "
                    f"more than {pct_rank:.0f}% of neutral maps (neutral median: {p50:.0f}). "
                    f"Communities of color have stronger collective electoral influence "
                    f"than neutral mapmaking alone would produce.")
        else:
            return (f"The enacted map has {enacted:.0f} minority-coalition district(s), "
                    f"within the typical range ({p5:.0f}–{p95:.0f}) for neutral maps.")

    else:
        return (f"Enacted: {enacted:.3f}. Neutral median: {p50:.3f} "
                f"(range: {p5:.3f}–{p95:.3f}). "
                f"Percentile rank: {pct_rank:.0f}th — {_outlier_phrase(pct_rank)}.")


_METRIC_META = {
    # key: (label, headline, category, description, higher_is_better)
    'dem_seats': (
        'Seat–Vote Proportionality', 'Does the seat count reflect how people actually voted?',
        'partisan',
        'In a fair map, the share of seats each party wins should reflect its share '
        'of statewide votes. This metric counts districts projected to lean Democratic '
        'based on each plan\'s vote patterns — not as a partisan goal, but as a '
        'measuring stick for proportionality. The histogram shows how many '
        'Democratic-leaning seats thousands of neutrally drawn alternative maps '
        'produce. If the enacted map falls far from this range, lines were likely '
        'drawn to systematically over- or under-represent one party.',
        None),
    'partisan_bias': (
        'Seat Symmetry at Equal Votes', 'Would both parties win equally if the vote were tied?',
        'partisan',
        'Partisan bias asks: if both parties received exactly 50% of the vote '
        'statewide, would they win the same number of seats? A value near zero '
        'means the map treats both parties symmetrically. A positive value means '
        'Republicans would win more seats than Democrats at equal vote shares; a '
        'negative value means the reverse. This is the Princeton Gerrymandering '
        'Project\'s normative (cube-law) symmetry test — it is not about who '
        'should win, but whether the map\'s structure gives either party a built-in '
        'advantage independent of how people vote.',
        None),   # symmetric: values near zero are best; both tails are bad
    'efficiency_gap': (
        'Wasted Votes Balance', 'Are both parties\' votes equally effective at winning seats?',
        'partisan',
        'Every election produces "wasted" votes — votes cast in losing districts '
        '(all wasted) and surplus votes beyond what was needed to win (also wasted). '
        'A fair map wastes votes at roughly equal rates for both parties. The '
        'Efficiency Gap measures the imbalance: a value far from zero means one '
        'party\'s votes are being systematically wasted at a higher rate than the '
        'other\'s — a sign that district lines are concentrating or dispersing that '
        'party\'s voters artificially. Developed by Stephanopoulos & McGhee; '
        'cited in federal gerrymandering litigation.',
        None),   # symmetric: values near zero are best; both tails are bad
    'mean_median': (
        'Vote Distribution Symmetry', 'Does each party need the same number of votes to win a district?',
        'partisan',
        'The Mean-Median difference reveals whether one party\'s votes are '
        'systematically spread more efficiently across districts than the other\'s. '
        'When one party wins many districts by modest margins while the other piles '
        'up large majorities in fewer districts, the map gives the first party a '
        'structural seat advantage — even when both parties receive equal votes '
        'statewide. A value near zero means both parties convert votes to seats '
        'at roughly the same rate. A large deviation in either direction signals '
        'asymmetric voter distribution — often a hallmark of deliberate mapmaking.',
        None),   # symmetric: values near zero are best; both tails are bad
    'comp_seats': (
        'Electoral Competitiveness', 'How many districts give voters a genuine choice?',
        'competitive',
        f'A competitive district is one where the outcome is genuinely uncertain — '
        f'the margin between the two parties is within '
        f'{COMPETITIVE_MARGIN*100:.0f} percentage points of 50/50. '
        f'Competitive districts force elected officials to be responsive to a '
        f'broad range of constituents, not just their party base. Maps designed '
        f'to protect incumbents — whether Republican or Democratic — tend to '
        f'minimize competitiveness. This metric asks whether the enacted map '
        f'produces fewer competitive districts than neutral alternatives would, '
        f'regardless of which party benefits from the reduced accountability.',
        True),
    'polsby_popper': (
        'Compactness (Polsby-Popper)', 'Are district shapes compact and geographically coherent?',
        'geographic',
        'The Polsby-Popper score measures how "normal" shaped each district is by '
        'comparing its area to the area of a circle with the same perimeter. '
        'Scores range from 0 to 1, with 1 being a perfect circle. Oddly shaped, '
        'contorted districts — nicknamed "salamander" districts after the original '
        'gerrymander of 1812 — can indicate that lines were drawn to include or '
        'exclude specific communities for partisan or racial reasons. More compact '
        'districts are generally easier for representatives to serve and for '
        'communities to organize around.',
        True),
    'county_splits': (
        'County Integrity', 'Are natural community boundaries being respected?',
        'geographic',
        'The number of counties divided across two or more districts. Counties '
        'represent natural community boundaries — shared local government, courts, '
        'schools, emergency services, and civic institutions built up over generations. '
        'Keeping counties intact preserves communities of interest and makes it easier '
        'for residents to understand who represents them. Unnecessarily splitting '
        'counties can divide communities and dilute their collective voice. Fewer '
        'splits generally indicates a more geographically coherent, community-respecting map.',
        False),
    'muni_splits': (
        'Split Cities & Municipalities', 'How many cities and towns are divided across different districts?',
        'geographic',
        'Counts incorporated municipalities (cities, towns) whose territory is split '
        'across two or more congressional districts. Urban cracking — dividing a city '
        'among multiple districts — dilutes its collective political voice and reduces '
        'the ability of city residents to elect a single representative who understands '
        'local concerns. The histogram shows how many municipal splits neutral, '
        'geography-driven redistricting plans typically produce. Fewer splits means '
        'more urban communities are kept intact.',
        False),
    'maj_black': (
        'Black Community Representation', 'Do Black voters have a fair opportunity to elect representatives of their choice?',
        'minority',
        f'This counts districts where Black citizens make up more than '
        f'{BVAP_THRESHOLD*100:.0f}% of the Voting Age Population. Under Section 2 of '
        f'the Voting Rights Act, mapmakers must not dilute minority communities\' '
        f'electoral influence. The histogram shows how many majority-Black districts '
        f'thousands of neutrally drawn maps produce. The Princeton ensemble test grades '
        f'statistical distance from the neutral range in either direction: too few '
        f'raises VRA dilution concerns; too many is equally anomalous as a statistical '
        f'outlier. The takeaway text explains the direction and meaning.',
        None),
    'maj_hisp': (
        'Hispanic Community Representation', 'Do Hispanic voters have a fair opportunity to elect their preferred candidates?',
        'minority',
        f'This counts districts where Hispanic citizens make up more than '
        f'{MINORITY_THRESHOLD*100:.0f}% of the Voting Age Population. The Voting '
        f'Rights Act protects Hispanic voters\' ability to elect representatives of '
        f'their choice. As Georgia\'s Hispanic population has grown significantly, '
        f'this metric compares the enacted map\'s minority district count against '
        f'what neutral, geography-based alternatives would naturally produce. '
        f'More districts than the neutral baseline indicates stronger representation '
        f'opportunity; significantly fewer raises Voting Rights Act concerns.',
        True),
    'maj_aian': (
        'Indigenous Community Representation', 'Do American Indian and Alaska Native voters have fair representation?',
        'minority',
        'This counts districts where American Indian and Alaska Native citizens '
        'make up more than 50% of the Voting Age Population. These communities '
        'have historically faced some of the most significant barriers to political '
        'representation in American history and are specifically protected under '
        'the Voting Rights Act. The comparison against neutral alternatives reveals '
        'whether the enacted map preserves or diminishes their electoral opportunity. '
        'More districts than the neutral baseline is the better outcome.',
        True),
    'maj_asian': (
        'Asian American Representation', 'Do Asian American voters have fair electoral opportunity?',
        'minority',
        'This counts districts where Asian American citizens make up more than '
        '50% of the Voting Age Population. As one of the fastest-growing communities '
        'in Georgia, Asian Americans\' representation opportunity is an increasingly '
        'important measure of map fairness. The comparison against neutral '
        'alternatives establishes whether the enacted map reflects what '
        'natural geography would support. More districts than the neutral baseline '
        'is the better outcome.',
        True),
    'min_coal': (
        'Minority Coalition Representation', 'Do communities of color collectively have a voice?',
        'minority',
        'This counts districts where voters of color — Black, Hispanic, Asian, and '
        'others — together make up more than 50% of the Voting Age Population '
        '(or Citizen VAP for GerryChain runs). Even when no single racial group '
        'holds a majority, communities of color can collectively determine electoral '
        'outcomes. The Princeton ensemble test grades statistical distance from neutral '
        'redistricting outcomes in either direction — the grade reflects how anomalous '
        'the enacted map is, not a policy judgment about the direction of that distance.',
        None),
}


# ── Data loading ──────────────────────────────────────────────────────────────

def _download_from_dataverse(filename: str, dest: Path):
    print(f'Fetching {filename} from ALARM Harvard Dataverse...')
    api = ('https://dataverse.harvard.edu/api/datasets/:persistentId/'
           f'versions/:latest/files?persistentId={_DATAVERSE_DOI}')
    files = requests.get(api, timeout=30).raise_for_status() or requests.get(api, timeout=30).json()
    resp = requests.get(api, timeout=30)
    resp.raise_for_status()
    match = next((f for f in resp.json()['data']
                  if f['dataFile']['filename'] == filename), None)
    if match is None:
        raise FileNotFoundError(f'{filename} not found on Dataverse')
    dl = requests.get(
        f'https://dataverse.harvard.edu/api/access/datafile/{match["dataFile"]["id"]}',
        stream=True, timeout=120)
    dl.raise_for_status()
    dest.write_bytes(dl.content)
    print(f'  Saved {dest} ({dest.stat().st_size / 1e6:.1f} MB)')


def _load_csv(csv_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.read_csv(csv_path, dtype={'draw': str})
    df.columns = df.columns.str.strip()
    mask    = df['draw'].str.strip() == ENACTED_PLAN_LABEL
    enacted = df[mask].copy()
    sampled = df[~mask].copy()
    sampled['draw'] = sampled['draw'].astype(int)
    return sampled, enacted


def _load_meta(meta_file: Path, csv_path: Path, run_id: str, sampled: pd.DataFrame) -> dict:
    meta = json.loads(meta_file.read_text()) if meta_file.exists() else {}
    meta.setdefault('id',          run_id)
    meta.setdefault('name',        run_id.replace('_', ' ').title())
    meta.setdefault('algorithm',   'SMC')
    meta.setdefault('date',        datetime.fromtimestamp(csv_path.stat().st_mtime).strftime('%Y-%m-%d'))
    meta.setdefault('n_plans',     int(sampled['draw'].nunique()))
    meta.setdefault('description', '')
    meta.setdefault('tags',        [])
    meta.setdefault('plans',       [{'id': 'enacted', 'label': f'{ENACTED_PLAN_LABEL} (enacted)'}])
    meta['id'] = run_id
    return meta


# ── Analysis ──────────────────────────────────────────────────────────────────

def _vap_shares(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    df = df.copy()
    tv = _col(df, mapping, 'vap_total')
    if tv is None:
        return df
    for key in ('vap_black', 'vap_hisp', 'vap_aian', 'vap_asian', 'vap_nhpi'):
        v = _col(df, mapping, key)
        if v is not None:
            df[f'{key}_share'] = v / tv
    white = df.get('vap_white')
    if white is not None:
        df['min_coal_share'] = 1.0 - white / tv
    return df


def compute_metrics(sampled: pd.DataFrame, enacted: pd.DataFrame, mapping: dict) -> dict:
    """
    Returns {metric_key: (sampled_plan_values: np.ndarray, enacted_value: float|None)}.
    All values are plan-level (one number per plan).
    """
    s = _vap_shares(sampled, mapping)
    e = _vap_shares(enacted, mapping)

    share_col = mapping.get('dem_share', _DEFAULT_COLS['dem_share'])
    half_margin = COMPETITIVE_MARGIN / 2.0

    raw: dict[str, tuple[np.ndarray, float | None]] = {}

    # Plan-level columns from ALARM (same value every row for a given draw → .first())
    for mkey, col_key in [
        ('dem_seats',      'dem_seats'),
        ('partisan_bias',  'partisan_bias'),
        ('efficiency_gap', 'efficiency_gap'),
        ('county_splits',  'county_splits'),
        ('muni_splits',    'muni_splits'),
    ]:
        col_name = mapping.get(col_key, _DEFAULT_COLS.get(col_key, col_key))
        if col_name not in s.columns:
            continue
        s_vals = s.groupby('draw')[col_name].first().to_numpy(dtype=float)
        e_val  = float(e[col_name].iloc[0]) if col_name in e.columns and len(e) else None
        raw[mkey] = (s_vals, e_val)

    # Polsby-Popper mean per plan
    pp_col = mapping.get('polsby_popper', _DEFAULT_COLS['polsby_popper'])
    if pp_col in s.columns:
        raw['polsby_popper'] = (
            s.groupby('draw')[pp_col].mean().to_numpy(dtype=float),
            float(e[pp_col].mean()) if pp_col in e.columns and len(e) else None,
        )

    # Computed per-plan from district-level dem_share
    if share_col in s.columns:
        # Competitive seats
        s['_comp'] = (s[share_col] - 0.5).abs() <= half_margin
        e['_comp'] = (e[share_col] - 0.5).abs() <= half_margin
        raw['comp_seats'] = (
            s.groupby('draw')['_comp'].sum().to_numpy(dtype=float),
            float(e['_comp'].sum()) if len(e) else None,
        )
        # Mean-median difference
        def _mm(x): return x.mean() - x.median()
        raw['mean_median'] = (
            s.groupby('draw')[share_col].apply(_mm).to_numpy(dtype=float),
            float(_mm(e[share_col])) if share_col in e.columns and len(e) else None,
        )

    # Minority district counts
    for mkey, share_col_name, thresh in [
        ('maj_black', 'vap_black_share', BVAP_THRESHOLD),
        ('maj_hisp',  'vap_hisp_share',  MINORITY_THRESHOLD),
        ('maj_aian',  'vap_aian_share',  MINORITY_THRESHOLD),
        ('maj_asian', 'vap_asian_share', MINORITY_THRESHOLD),
        ('min_coal',  'min_coal_share',  MINORITY_THRESHOLD),
    ]:
        if share_col_name not in s.columns:
            continue
        s[f'_{mkey}'] = s[share_col_name] > thresh
        e[f'_{mkey}'] = e[share_col_name] > thresh if share_col_name in e.columns else pd.Series(False)
        raw[mkey] = (
            s.groupby('draw')[f'_{mkey}'].sum().to_numpy(dtype=float),
            float(e[f'_{mkey}'].sum()) if len(e) else None,
        )

    return raw


def compute_princeton_grades(raw_metrics: dict, n_districts: int) -> dict:
    """
    Build per-metric grades + Princeton composite grades.
    Returns a flat dict of grade objects keyed by metric or composite name.
    """
    result = {}

    for key, (s_vals, e_val) in raw_metrics.items():
        if e_val is None:
            continue
        meta  = _METRIC_META.get(key)
        if meta is None:
            continue
        label, headline, category, desc, higher_is_better = meta
        dist  = np.array(s_vals, dtype=float)
        if np.std(dist) < 1e-6:
            continue
        pct  = _pct_rank(dist, e_val)
        hist = _histogram_data(dist, e_val)

        if key == 'dem_seats':
            grade = _seats_grade(pct)    # directional: fewer Dem seats = worse; F only below 5th pct
        elif key == 'comp_seats':
            grade = _comp_grade(pct)
        elif higher_is_better is None:
            grade = _simple_grade(pct)   # symmetric: both tails are bad; F only outside 5–95
        else:
            grade = _directional_grade(pct, higher_is_better)

        result[key] = {
            'label':       label,
            'headline':    headline,
            'category':    category,
            'description': desc,
            'takeaway':    _generate_takeaway(key, float(e_val), pct, hist),
            'grade':       grade,
            'enacted':     round(float(e_val), 4),
            'pct_rank':    round(pct, 1),
            'histogram':   hist,
        }

    # ── Princeton composite grades ──────────────────────────────────────────

    # Competitiveness
    comp_g = result.get('comp_seats', {}).get('grade')

    # Partisan fairness (dual test)
    partisan_g = None
    if 'dem_seats' in result:
        pbias_val = raw_metrics.get('partisan_bias', (None, None))[1]
        e_pass = _ensemble_pass(result['dem_seats']['pct_rank'])
        n_pass = _normative_pass(pbias_val, n_districts) if pbias_val is not None else True
        partisan_g = _partisan_grade(e_pass, n_pass)
        if comp_g == 'A': partisan_g = _adj(partisan_g, +1)
        if comp_g == 'F': partisan_g = _adj(partisan_g, -1)
        result['_partisan_fairness'] = {
            'label':          'Partisan Fairness',
            'grade':          partisan_g,
            'ensemble_pass':  e_pass,
            'normative_pass': n_pass,
            'description':    (
                'Assessed using the Princeton Gerrymandering Project\'s dual test. '
                'The ENSEMBLE test checks whether the enacted map falls within the '
                'normal range (5th–95th percentile) of outcomes for thousands of '
                'randomly drawn alternative maps — maps that follow all legal '
                'requirements but were drawn without partisan intent. '
                'The NORMATIVE test uses the mathematical "cube law" of elections '
                'to check whether both parties convert votes into seats at '
                'roughly the same rate (symmetry). A map must pass both tests '
                'for an A grade. '
                f'Ensemble: {"✓ PASS — the enacted map is within the normal range" if e_pass else "✗ FAIL — the enacted map produces unusually partisan outcomes compared to neutral alternatives"}, '
                f'Normative: {"✓ PASS" if n_pass else "✗ FAIL — the map systematically advantages one party at equal vote shares"}.'
            ),
        }

    # Geographic (compactness + county splits)
    comp_pp_g = result.get('polsby_popper', {}).get('grade')
    splits_g  = result.get('county_splits', {}).get('grade')
    geo_g = None
    if comp_pp_g and splits_g:
        geo_g = _geo_grade(comp_pp_g, splits_g)
        result['_geographic'] = {
            'label': 'Geographic',
            'grade': geo_g,
            'description': 'Combines compactness (Polsby-Popper) and county splits.',
        }

    # Overall
    if partisan_g:
        overall = partisan_g
        if geo_g == 'F':   overall = _adj(overall, -1)
        if comp_g == 'A':  overall = _adj(overall, +1)
        if comp_g == 'F':  overall = _adj(overall, -1)
        result['_overall'] = {
            'label': 'Overall',
            'grade': overall,
            'description': (
                'The Overall grade summarizes how the enacted map compares to '
                'thousands of alternative maps drawn without partisan intent. '
                'It starts from the Partisan Fairness grade and adjusts upward '
                'if the map is unusually competitive (more competitive districts '
                'than typical), or downward if it has zero competitive districts '
                'or poor geographic quality (irregular shapes, many county splits). '
                'An A means the enacted map performs as well as or better than '
                'neutral alternatives on all dimensions — it does not stand out '
                'as gerrymandered. An F means the map produces outcomes that are '
                'highly unlikely to occur by chance in a fair process.'
            ),
        }

    return result


def _simple_grade(pct_rank: float) -> str:
    """
    Center-band grade for symmetric metrics (minority counts, partisan bias, egap,
    mean-median).  Values near the neutral median are best; both tails are bad.
    F fires only outside the 5–95 ensemble boundary, consistent with _ensemble_pass.
    """
    dist = abs(pct_rank - 50.0)
    if dist <= 10: return 'A'   # pct 40–60: comfortably in the middle
    if dist <= 30: return 'B'   # pct 20–80: normal range
    if dist <= 45: return 'C'   # pct 5–95:  in ensemble but toward tails
    return 'F'                   # outside 5–95: statistical outlier


def _river_data(sampled: pd.DataFrame, mapping: dict, n_sample: int = 500) -> dict | None:
    share_col = mapping.get('dem_share', _DEFAULT_COLS['dem_share'])
    if share_col not in sampled.columns:
        return None
    draws = sampled['draw'].unique()
    rng   = np.random.default_rng(42)
    subset = rng.choice(draws, min(n_sample, len(draws)), replace=False)
    ribbons = []
    for d in subset:
        vals = np.sort(sampled.loc[sampled['draw'] == d, share_col].values)
        ribbons.append(vals.tolist())
    arr = np.array(ribbons)
    p5, p50, p95 = np.percentile(arr, [5, 50, 95], axis=0)
    return {
        'n_sample': len(subset),
        'n_districts': arr.shape[1] if arr.ndim == 2 else N_DISTRICTS,
        'p5':  [round(float(v), 4) for v in p5],
        'p50': [round(float(v), 4) for v in p50],
        'p95': [round(float(v), 4) for v in p95],
    }


def _build_analysis(run: dict) -> dict:
    meta    = run['meta']
    return {
        'summary': {
            'state':         STATE,
            'state_full':    STATE_FULL,
            'plan_type':     meta.get('chamber', PLAN_TYPE),
            'plan_year':     PLAN_YEAR,
            'n_districts':   N_DISTRICTS,
            'n_plans':       meta['n_plans'],
            'enacted_label': ENACTED_PLAN_LABEL,
            'story_html':    meta.get('story_html', None),
            'run':           {k: v for k, v in meta.items() if k != 'columns'},
        },
        'grades':  run['grades'],
        'river':   run['river'],
    }


# ── Run registry ──────────────────────────────────────────────────────────────

def _build_run(run_id: str, csv_path: Path, meta_file: Path) -> dict:
    if not csv_path.exists():
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        _download_from_dataverse(csv_path.name, csv_path)

    sampled, enacted = _load_csv(csv_path)
    meta             = _load_meta(meta_file, csv_path, run_id, sampled)
    mapping          = {**_DEFAULT_COLS, **meta.get('columns', {})}
    raw              = compute_metrics(sampled, enacted, mapping)
    grades           = compute_princeton_grades(raw, N_DISTRICTS)
    river            = _river_data(sampled, mapping)

    return {
        'meta':    meta,
        'sampled': sampled,
        'enacted': enacted,
        'grades':  grades,
        'river':   river,
        'raw':     raw,
    }


def _build_run_from_scorecard(scorecard_path: Path, election_idx: int = 0, plan_id: str = 'enacted') -> dict:
    """
    Load a canonical scorecard JSON (produced by fdp/scripts/build_scorecard.py)
    and return a run dict in the same shape as _build_run() for ALARM CSVs.

    The scorecard already contains pre-computed Princeton grades and river data,
    so no re-computation is needed. The returned 'grades' dict is in the same
    format that compute_princeton_grades() produces — fdensemble renders it unchanged.
    """
    sc = json.loads(scorecard_path.read_text())
    run_info = sc['run']

    # Select the requested election (clamp to valid range)
    elections = sc.get('elections', [])
    election_idx = max(0, min(election_idx, len(elections) - 1)) if elections else 0

    # Build grades dict for the selected election
    # Scorecard grades already include _partisan_fairness, _overall, and
    # demographics metrics (maj_black, min_coal).  Election-specific metrics
    # (dem_seats, efficiency_gap, mean_median, comp_seats) come from the selected
    # election's 'metrics' block.
    grades: dict = {}

    if elections:
        elec = elections[election_idx]
        for key, val in elec.get('metrics', {}).items():
            if val is not None:
                grades[key] = val

    # Merge in cross-election grades (composites, demographics)
    for key, val in sc.get('grades', {}).items():
        if val is not None:
            grades[key] = val

    # River for selected election
    river = None
    if elections:
        elec_river = elections[election_idx].get('river')
        if elec_river:
            river = {
                'n_sample':              elec_river.get('n_draws', 0),
                'n_districts':           elec_river.get('n_districts', run_info.get('n_districts', N_DISTRICTS)),
                'p5':                    elec_river.get('p5', []),
                'p50':                   elec_river.get('p50', []),
                'p95':                   elec_river.get('p95', []),
                'enacted':               elec_river.get('enacted'),
                'enacted_district_ids':  elec_river.get('enacted_district_ids'),
            }

    # Plans list — each plan is a named map that can be compared against this benchmark.
    # Currently scorecards have one plan (the enacted map, draw=1).
    # When a scorecard gains a 'plans' array, those are exposed here for the plan selector.
    default_plans = [{'id': 'enacted', 'label': sc.get('enacted_label', 'Enacted Map')}]
    plans = sc.get('plans') or default_plans

    # Build meta dict (fdensemble RunMeta shape + extra fields for UI)
    meta = {
        'id':          run_info['id'],
        'name':        run_info.get('name', run_info['id']),
        'algorithm':   run_info.get('algorithm', 'GerryChain ReCom'),
        'date':        run_info.get('date', ''),
        'n_plans':     run_info.get('n_plans', run_info.get('n_draws', 0)),
        'description': run_info.get('description', ''),
        'tags':        run_info.get('tags', []),
        'source':      run_info.get('source', 'scorecard'),
        'chamber':     run_info.get('chamber', ''),
        # Elections list — passed to frontend for the election selector
        'elections':   run_info.get('elections', []),
        'election_idx': election_idx,
        # Plans list — passed to frontend for the plan selector
        'plans':       plans,
        # LLM-generated narrative (populated by batch build process, optional)
        'story_html':  sc.get('story_html', None),
    }

    return {
        'meta':    meta,
        'grades':  grades,
        'river':   river,
        # These are unused by fdensemble render paths but kept for compat
        'sampled': None,
        'enacted': None,
        'raw':     {},
    }


def _discover_and_load_runs() -> dict:
    found = {}

    # ALARM CSV and legacy per-election runs are superseded by the composite
    # benchmark scorecards in input_data/.  Only scorecard JSON files are loaded.

    # Discover canonical scorecard JSON files in input_data/ and RUNS_DIR/
    input_data_dir = Path('input_data')
    scorecard_dirs = [input_data_dir, RUNS_DIR]
    for scan_dir in scorecard_dirs:
        if not scan_dir.exists():
            continue
        for sc_path in sorted(scan_dir.glob('*_scorecard.json')):
            rid = sc_path.stem.replace('_scorecard', '')
            if rid in found:
                continue  # don't overwrite ALARM CSV run with same id
            print(f'  Loading scorecard: {rid}')
            try:
                run = _build_run_from_scorecard(sc_path, election_idx=0)
                # Always use the filename-derived id as the canonical key so that
                # /api/analysis?run=<filename-id> resolves correctly regardless of
                # what internal run.id the scorecard JSON was built with.
                run['meta']['id'] = rid
                found[rid] = run
            except Exception as exc:
                print(f'  WARNING: failed to load scorecard {rid}: {exc}')

    return found


print('Loading runs...')
_runs = _discover_and_load_runs()
print(f'Ready — {len(_runs)} run(s): {list(_runs.keys())}')

# ── Map library (server-side persistent shapefile catalog) ────────────────────

def _map_slug(label: str) -> str:
    slug = ''.join(c if c.isalnum() else '_' for c in label.lower())
    slug = '_'.join(p for p in slug.split('_') if p)[:32]
    return (slug or 'map') + '_' + uuid.uuid4().hex[:6]


def _load_maps_catalog() -> list:
    catalog = MAPS_DIR / 'catalog.json'
    return json.loads(catalog.read_text()) if catalog.exists() else []


def _save_maps_catalog(maps: list):
    MAPS_DIR.mkdir(parents=True, exist_ok=True)
    (MAPS_DIR / 'catalog.json').write_text(json.dumps(maps, indent=2))


_maps_catalog: list = _load_maps_catalog()
print(f'Map library: {len(_maps_catalog)} map(s) in {MAPS_DIR}')

# ── VTD composite spatial index (lazy-loaded on first /api/score-plan request) ─
# Primary: bundled alongside the app (committed to fdensemble/data/, copied by Dockerfile)
# Fallback: local dev path relative to the fdp sibling directory
_VTD_COMPOSITE_PATH  = Path('data/vtd_composite.parquet')
_VTD_MUNI_PATH       = Path('data/vtd_muni.parquet')
_VTD_DEMO_PATH       = Path('data/vtd_demographics.parquet')
_vtd_df: pd.DataFrame | None = None
_vtd_tree: STRtree | None = None
_vtd_points: list | None = None  # parallel list of shapely Points
_vtd_muni_df:  pd.DataFrame | None = None  # GEOID → muni_id for municipal split scoring
_vtd_demo_df:  pd.DataFrame | None = None  # GEOID → racial/pop demographics


def _load_vtd_composite():
    global _vtd_df, _vtd_tree, _vtd_points
    if _vtd_df is not None:
        return
    path = _VTD_COMPOSITE_PATH
    if not path.exists():
        # Fallbacks for local dev (running from fgdp/ root or fdensemble/ subdirectory)
        for candidate in [
            Path('fdp/data/repos/main/vtd/vtd_composite.parquet'),
            Path('../fdp/data/repos/main/vtd/vtd_composite.parquet'),
            Path('fdensemble/data/vtd_composite.parquet'),
        ]:
            if candidate.exists():
                path = candidate
                break
        else:
            raise FileNotFoundError(
                'vtd_composite.parquet not found. '
                'Expected at data/vtd_composite.parquet (bundled) or '
                'fdp/data/repos/main/vtd/vtd_composite.parquet (local dev).'
            )

    _vtd_df = pd.read_parquet(path)
    _vtd_points = [Point(row.centroid_lon, row.centroid_lat) for row in _vtd_df.itertuples()]
    _vtd_tree = STRtree(_vtd_points)
    print(f'  VTD composite loaded: {len(_vtd_df):,} VTDs')


def _load_vtd_muni():
    global _vtd_muni_df
    if _vtd_muni_df is not None:
        return
    path = _VTD_MUNI_PATH
    if not path.exists():
        for candidate in [
            Path('fdensemble/data/vtd_muni.parquet'),
            Path('../fdensemble/data/vtd_muni.parquet'),
        ]:
            if candidate.exists():
                path = candidate
                break
        else:
            return   # non-fatal: muni_splits will be skipped
    _vtd_muni_df = pd.read_parquet(path)
    _vtd_muni_df['geoid'] = _vtd_muni_df['geoid'].astype(str)
    print(f'  VTD muni mapping loaded: {len(_vtd_muni_df):,} incorporated VTDs')


def _load_vtd_demo():
    global _vtd_demo_df
    if _vtd_demo_df is not None:
        return
    path = _VTD_DEMO_PATH
    if not path.exists():
        for candidate in [
            Path('fdensemble/data/vtd_demographics.parquet'),
            Path('../fdensemble/data/vtd_demographics.parquet'),
        ]:
            if candidate.exists():
                path = candidate
                break
        else:
            return   # non-fatal
    _vtd_demo_df = pd.read_parquet(path)
    _vtd_demo_df['geoid'] = _vtd_demo_df['geoid'].astype(str)
    print(f'  VTD demographics loaded: {len(_vtd_demo_df):,} VTDs')


def _score_geojson(features: list, run_id: str) -> dict:
    """
    Score a list of GeoJSON district polygon features against the composite benchmark.

    Returns a plan dict with aggregate metrics + per-district breakdown.
    """
    _load_vtd_composite()
    _load_vtd_muni()
    _load_vtd_demo()

    # Build shapely polygons for each district feature
    district_polygons = []
    for i, feat in enumerate(features):
        try:
            geom = shape(feat['geometry'])
            district_polygons.append((i, geom))
        except Exception:
            pass  # skip invalid geometries

    if not district_polygons:
        raise ValueError('No valid district polygons found in GeoJSON')

    n_districts = len(district_polygons)
    vtd = _vtd_df.copy()

    # Assign each VTD centroid to a district using STRtree candidate query + contains
    vtd_district = np.full(len(vtd), -1, dtype=int)
    for dist_idx, poly in district_polygons:
        cands = _vtd_tree.query(poly, predicate='within')
        vtd_district[cands] = dist_idx

    vtd['_dist_idx'] = vtd_district
    assigned = vtd[vtd['_dist_idx'] >= 0].copy()
    unassigned = (vtd_district == -1).sum()
    if unassigned > 0:
        print(f'  {unassigned} VTDs unassigned (may be on district boundaries)')

    # Per-district aggregation
    grouped = assigned.groupby('_dist_idx').agg(
        dem_votes=('composite_dem_pct', lambda s: (s * assigned.loc[s.index, 'VAP_MOD']).sum()),
        rep_votes=('composite_rep_pct', lambda s: (s * assigned.loc[s.index, 'VAP_MOD']).sum()),
        total_vap=('VAP_MOD', 'sum'),
        lat_wt=('centroid_lat', lambda s: (s * assigned.loc[s.index, 'VAP_MOD']).sum()),
        lon_wt=('centroid_lon', lambda s: (s * assigned.loc[s.index, 'VAP_MOD']).sum()),
    ).reset_index()

    grouped['dem_2pv'] = grouped['dem_votes'] / (grouped['dem_votes'] + grouped['rep_votes'])
    grouped['centroid_lat'] = (grouped['lat_wt'] / grouped['total_vap']).round(5)
    grouped['centroid_lon'] = (grouped['lon_wt'] / grouped['total_vap']).round(5)

    # ── Demographic aggregation per district ──────────────────────────────────
    demo_by_dist: dict = {}
    if _vtd_demo_df is not None:
        demo_cols = ['pop', 'vap', 'pop_black', 'pop_hisp', 'pop_white',
                     'pop_aian', 'pop_asian', 'vap_black', 'vap_hisp',
                     'vap_white', 'vap_aian', 'vap_asian']
        # Join assigned VTDs with demographics
        assigned['_geoid_str'] = vtd.loc[assigned.index, 'GEOID20'].astype(str)
        demo_join = assigned.merge(
            _vtd_demo_df[['geoid'] + demo_cols],
            left_on='_geoid_str', right_on='geoid', how='left'
        )
        demo_agg = demo_join.groupby('_dist_idx')[demo_cols].sum().reset_index()
        for _, row in demo_agg.iterrows():
            d_vap = max(float(row['vap']), 1)
            demo_by_dist[int(row['_dist_idx'])] = {
                'total_pop':   int(row['pop']),
                'vap_black':   int(row['vap_black']),
                'vap_hisp':    int(row['vap_hisp']),
                'vap_white':   int(row['vap_white']),
                'vap_aian':    int(row['vap_aian']),
                'vap_asian':   int(row['vap_asian']),
                'pct_black':   round(float(row['vap_black']) / d_vap, 4),
                'pct_hisp':    round(float(row['vap_hisp'])  / d_vap, 4),
                'pct_white':   round(float(row['vap_white']) / d_vap, 4),
                'pct_aian':    round(float(row['vap_aian'])  / d_vap, 4),
                'pct_asian':   round(float(row['vap_asian']) / d_vap, 4),
                'pct_minority': round(1.0 - float(row['vap_white']) / d_vap, 4),
            }

    district_dem_2pvs = grouped['dem_2pv'].sort_values().values

    # Municipal splits — count incorporated municipalities with VTDs in 2+ districts
    muni_splits_val: int | None = None
    if _vtd_muni_df is not None:
        # vtd_assignments: GEOID → district_num
        assigned_geoids = pd.Series(list(vtd_assignments.keys()), name='geoid')
        assigned_districts = pd.Series(list(vtd_assignments.values()), name='district')
        asgn_df = pd.DataFrame({'geoid': assigned_geoids.values, 'district': assigned_districts.values})
        muni_join = asgn_df.merge(_vtd_muni_df, on='geoid', how='inner')
        if not muni_join.empty:
            splits_per_muni = muni_join.groupby('muni_id')['district'].nunique()
            muni_splits_val = int((splits_per_muni > 1).sum())

    # Partisan metrics
    dem_seats    = int((district_dem_2pvs >= 0.5).sum())
    mean_val     = float(np.mean(district_dem_2pvs))
    median_val   = float(np.median(district_dem_2pvs))
    mean_median  = round(mean_val - median_val, 4)

    # Efficiency gap
    waste_dem = sum(
        max(0, v - 0.5) * total if v >= 0.5 else v * total
        for v, total in zip(grouped['dem_2pv'], grouped['total_vap'])
    )
    waste_rep = sum(
        max(0, (1 - v) - 0.5) * total if v < 0.5 else (1 - v) * total
        for v, total in zip(grouped['dem_2pv'], grouped['total_vap'])
    )
    total_votes_all = grouped['total_vap'].sum()
    efficiency_gap = round((waste_dem - waste_rep) / total_votes_all, 4) if total_votes_all > 0 else 0.0

    # Competitive seats (within 5pp of 50%)
    comp_seats = int(((district_dem_2pvs >= 0.45) & (district_dem_2pvs <= 0.55)).sum())

    # Look up pct_rank against stored ensemble histograms
    run_data = _runs.get(run_id)
    if run_data is None:
        raise HTTPException(404, f'Run {run_id!r} not found')

    grades = run_data['grades']

    def _rank_and_grade(metric_key: str, val: float) -> dict:
        g = grades.get(metric_key)
        if g is None or 'histogram' not in g:
            return {'value': round(val, 4), 'pct_rank': 50.0, 'grade': 'C'}
        hist = g['histogram']
        edges = hist['edges']
        counts = hist['counts']
        # Reconstruct approximate distribution from histogram bins
        centers = [(edges[i] + edges[i + 1]) / 2 for i in range(len(counts))]
        dist_approx = np.repeat(centers, counts)
        pct = float((dist_approx <= val).mean() * 100)

        if metric_key == 'dem_seats':
            if pct >= 50: grd = 'A'
            elif pct >= 20: grd = 'B'
            elif pct >= 5: grd = 'C'
            else: grd = 'F'
        elif metric_key == 'comp_seats':
            if pct >= 95: grd = 'A'
            elif pct >= 64: grd = 'B'
            elif pct >= 5: grd = 'C'
            else: grd = 'F'
        elif metric_key in ('muni_splits', 'county_splits'):
            # lower is better: rank = distance from low end
            rank = 100 - pct
            if rank >= 95: grd = 'A'
            elif rank >= 64: grd = 'B'
            elif rank >= 5: grd = 'C'
            else: grd = 'F'
        else:
            d = abs(pct - 50.0)
            if d <= 10: grd = 'A'
            elif d <= 30: grd = 'B'
            elif d <= 45: grd = 'C'
            else: grd = 'F'
        return {'value': round(val, 4), 'pct_rank': round(pct, 1), 'grade': grd}

    metrics = {
        'dem_seats':      _rank_and_grade('dem_seats',      float(dem_seats)),
        'efficiency_gap': _rank_and_grade('efficiency_gap', efficiency_gap),
        'mean_median':    _rank_and_grade('mean_median',    mean_median),
        'comp_seats':     _rank_and_grade('comp_seats',     float(comp_seats)),
    }
    if muni_splits_val is not None:
        metrics['muni_splits'] = _rank_and_grade('muni_splits', float(muni_splits_val))

    # Partisan fairness composite grade
    e_pass = 5.0 <= metrics['dem_seats']['pct_rank'] <= 95.0
    pf_grade = 'A' if e_pass else 'B'
    if metrics['comp_seats']['grade'] == 'F': pf_grade = _adj(pf_grade, -1)
    if metrics['comp_seats']['grade'] == 'A': pf_grade = _adj(pf_grade, +1)
    overall = pf_grade

    plan_grades = {
        '_partisan_fairness': {
            'label': 'Partisan Fairness', 'grade': pf_grade,
            'ensemble_pass': e_pass, 'normative_pass': True,
            'description': f'Ensemble: {"✓ PASS" if e_pass else "✗ FAIL"}',
        },
        '_overall': {'label': 'Overall', 'grade': overall, 'description': ''},
    }

    # Build per-district list sorted by partisan lean (ascending)
    dist_rows = []
    for _, row in grouped.sort_values('dem_2pv').iterrows():
        d_idx = int(row['_dist_idx'])
        entry = {
            'id':           str(d_idx + 1),
            'district_num': d_idx + 1,
            'dem_2pv':      round(float(row['dem_2pv']), 4),
            'total_vap':    int(row['total_vap']),
            'centroid_lat': float(row['centroid_lat']),
            'centroid_lon': float(row['centroid_lon']),
        }
        if d_idx in demo_by_dist:
            entry.update(demo_by_dist[d_idx])
        dist_rows.append(entry)

    # Build VTD-level assignment dicts for district drill-down in Compare tab
    vtd_a = vtd[vtd['_dist_idx'] >= 0]
    vtd_assignments = {
        str(g): int(d) + 1
        for g, d in zip(vtd_a['GEOID20'], vtd_a['_dist_idx'])
    }
    vtd_details = {
        str(g): {'dem_2pv': round(float(d), 4), 'total_vap': int(v)}
        for g, d, v in zip(
            vtd_a['GEOID20'],
            vtd_a['composite_dem_2pv'],
            vtd_a['VAP_MOD'],
        )
    }

    return {
        'id':              str(uuid.uuid4()),
        'label':           '',   # filled by caller
        'source':          'upload',
        'run_id':          run_id,
        'metrics':         metrics,
        'grades':          plan_grades,
        'districts':       dist_rows,
        'vtd_assignments': vtd_assignments,
        'vtd_details':     vtd_details,
    }


def _get_run(run_id: str | None) -> dict:
    rid = run_id or next(iter(_runs))
    if rid not in _runs:
        raise HTTPException(404, f'Run {rid!r} not found. Available: {list(_runs.keys())}')
    return _runs[rid]


# ── Matplotlib charts (CLI / export only — frontend uses Chart.js) ────────────

def _make_histograms(run: dict):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    grades  = run['grades']
    panels  = [k for k in grades if not k.startswith('_')]
    ncols   = 3
    nrows   = max(1, (len(panels) + ncols - 1) // ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(14, 4 * nrows))
    axes = np.array(axes).flatten()

    colors = {
        'partisan': 'steelblue', 'competitive': 'teal',
        'geographic': 'slategray', 'minority': 'mediumpurple',
    }
    for ax, key in zip(axes, panels):
        g   = grades[key]
        h   = g['histogram']
        col = colors.get(g.get('category', ''), 'steelblue')
        centers = [(h['edges'][i] + h['edges'][i+1]) / 2 for i in range(len(h['counts']))]
        ax.bar(centers, h['counts'], width=(h['edges'][1]-h['edges'][0])*0.9, color=col, alpha=0.6)
        if h['enacted'] is not None:
            ax.axvline(h['enacted'], color='black', lw=2, ls='--', label='Enacted')
        ax.axvline(h['p50'], color='gray', lw=1, ls=':', label='Median')
        ax.set_title(f'{g["label"]}  [{g["grade"]}]', fontsize=9)
        ax.legend(fontsize=7)

    for ax in axes[len(panels):]:
        ax.set_visible(False)

    meta = run['meta']
    fig.suptitle(
        f'{STATE} {PLAN_TYPE.upper()} {PLAN_YEAR} — Fairness Distributions\n'
        f'{meta["name"]} · {meta["date"]} · {meta["n_plans"]:,} plans',
        fontsize=11)
    fig.tight_layout()
    return fig


def _make_river(run: dict):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    river = run.get('river')
    if not river:
        return None

    x = list(range(1, river['n_districts'] + 1))
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.fill_between(x, river['p5'], river['p95'], alpha=0.2, color=DEM_COLOR, label='5–95th %ile')
    ax.plot(x, river['p50'], color=DEM_COLOR, lw=1.5, label='Median')

    share_col = run['meta'].get('columns', _DEFAULT_COLS).get('dem_share', 'ndshare')
    enacted   = run['enacted']
    if share_col in enacted.columns:
        ax.plot(x, np.sort(enacted[share_col].values),
                color='black', lw=2.5, label='Enacted', zorder=5)
    ax.axhline(0.5, color='gray', lw=0.8, ls=':')
    ax.set_xlabel('District rank (partisan lean)')
    ax.set_ylabel('Dem two-party share')
    ax.legend(fontsize=9)

    meta = run['meta']
    ax.set_title(
        f'{STATE} {PLAN_TYPE.upper()} {PLAN_YEAR} — River Chart\n'
        f'{meta["name"]} · {meta["date"]}', fontsize=11)
    fig.tight_layout()
    return fig


def _to_png(fig) -> io.BytesIO:
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=FIG_DPI, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf


# ── FastAPI ───────────────────────────────────────────────────────────────────
app = FastAPI(title=f'fdensemble — {STATE} {PLAN_TYPE.upper()} {PLAN_YEAR}')


@app.get('/api/health')
def get_health():
    """Liveness check — includes FDP API connectivity status."""
    return {
        "status": "ok",
        "runs_loaded": len(_runs),
        "data_mode": "fdp_api" if using_api() else "local_files",
        "fdp": _fdp_health(),
    }


@app.get('/api/runs')
def get_runs():
    return [r['meta'] for r in _runs.values()]


@app.get('/api/analysis')
def get_analysis(
    run: str = Query(default=None),
    election: int = Query(default=0),
    plan: str = Query(default='enacted'),
):
    """
    Return the full analysis for a run.

    - `election`: for scorecard-based runs, selects which election's metrics to display (0-indexed).
    - `plan`: selects which plan to compare against the benchmark. Currently each scorecard has
      one plan ('enacted'); future scorecards may expose additional named plans.
    """
    run_data = _get_run(run)

    # If this is a scorecard run and a different election or plan is requested,
    # reload the scorecard with the appropriate parameters
    if run_data['meta'].get('source') in ('gerrychain', 'scorecard'):
        if election != 0 or plan != 'enacted':
            sc_path = _find_scorecard_path(run_data['meta']['id'])
            if sc_path:
                run_data = _build_run_from_scorecard(sc_path, election_idx=election, plan_id=plan)

    return _build_analysis(run_data)


def _find_scorecard_path(run_id: str) -> Path | None:
    """Locate the scorecard JSON file for a given run_id."""
    for scan_dir in [Path('input_data'), RUNS_DIR]:
        p = scan_dir / f'{run_id}_scorecard.json'
        if p.exists():
            return p
    return None


@app.get('/api/maps')
def get_maps():
    """List all maps in the server-side map library."""
    return _maps_catalog


@app.post('/api/maps')
async def save_map(request: Request):
    """
    Save a GeoJSON map to the server-side library.

    Body: { "label": "My Map Name", "geojson": { "type": "FeatureCollection", "features": [...] } }
    Returns MapMeta: { "id", "label", "n_districts", "created" }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, 'Request body must be valid JSON')

    label    = body.get('label', 'Uploaded Map')
    geojson  = body.get('geojson', {})
    features = geojson.get('features', [])
    if not features:
        raise HTTPException(400, 'geojson.features must be a non-empty array')

    map_id   = _map_slug(label)
    MAPS_DIR.mkdir(parents=True, exist_ok=True)
    (MAPS_DIR / f'{map_id}.geojson').write_text(json.dumps(geojson))

    meta = {
        'id':          map_id,
        'label':       label,
        'n_districts': len(features),
        'created':     datetime.now().strftime('%Y-%m-%d'),
    }
    _maps_catalog.append(meta)
    _save_maps_catalog(_maps_catalog)
    print(f'  Map saved: {map_id} ({len(features)} districts)')
    return meta


@app.post('/api/score-map')
async def score_map_from_library(request: Request):
    """
    Score a stored library map against an ensemble benchmark.

    Body: { "map_id": "my_map_abc123", "run_id": "fdga_2026_benchmark_congress" }
    Returns a ScoredPlan object.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, 'Request body must be valid JSON')

    map_id = body.get('map_id')
    run_id = body.get('run_id') or next(iter(_runs))

    if not map_id:
        raise HTTPException(400, 'map_id is required')

    geojson_path = MAPS_DIR / f'{map_id}.geojson'
    if not geojson_path.exists():
        raise HTTPException(404, f'Map {map_id!r} not found in library')

    geojson  = json.loads(geojson_path.read_text())
    features = geojson.get('features', [])

    meta = next((m for m in _maps_catalog if m['id'] == map_id), {'label': map_id})

    try:
        result = _score_geojson(features, run_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError as e:
        raise HTTPException(500, str(e))

    result['label']  = meta['label']
    result['map_id'] = map_id
    return result


@app.delete('/api/maps/{map_id}')
def delete_map(map_id: str):
    """Remove a map from the library."""
    global _maps_catalog
    geojson_path = MAPS_DIR / f'{map_id}.geojson'
    if geojson_path.exists():
        geojson_path.unlink()
    _maps_catalog = [m for m in _maps_catalog if m['id'] != map_id]
    _save_maps_catalog(_maps_catalog)
    return {'deleted': map_id}


@app.get('/api/river')
def get_river(run: str = Query(default=None)):
    r = _get_run(run)
    return r['river'] or HTTPException(404, 'River data unavailable')


@app.get('/api/charts/histograms')
def chart_histograms(run: str = Query(default=None)):
    from fastapi.responses import StreamingResponse
    return StreamingResponse(_to_png(_make_histograms(_get_run(run))), media_type='image/png')


@app.get('/api/charts/river')
def chart_river(run: str = Query(default=None)):
    from fastapi.responses import StreamingResponse
    fig = _make_river(_get_run(run))
    if fig is None:
        raise HTTPException(404, 'River data unavailable')
    return StreamingResponse(_to_png(fig), media_type='image/png')


@app.post('/api/score-plan')
async def score_plan(request: Request):
    """
    Score an uploaded redistricting plan against the composite benchmark.

    Accepts JSON body:
      { "run_id": "fdga_2026_benchmark_congress",
        "label": "Proposed Map A",
        "geojson": { "type": "FeatureCollection", "features": [...district polygons...] } }

    Returns a ScoredPlan object with aggregate grades and per-district metrics.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, 'Request body must be valid JSON')

    run_id   = body.get('run_id') or next(iter(_runs))
    label    = body.get('label', 'Uploaded Plan')
    geojson  = body.get('geojson', {})
    features = geojson.get('features', [])

    if not features:
        raise HTTPException(400, 'geojson.features must be a non-empty array of district polygons')

    try:
        result = _score_geojson(features, run_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError as e:
        raise HTTPException(500, str(e))

    result['label'] = label
    return result


app.mount('/', StaticFiles(directory='frontend/dist', html=True), name='frontend')


# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='fdensemble — redistricting ensemble analysis')
    parser.add_argument('--run',    default=None,    help='Run ID (default: first loaded run)')
    parser.add_argument('--out',    default='output', help='Output directory')
    parser.add_argument('--fmt',    default='json',   choices=['json', 'yaml'])
    parser.add_argument('--charts', action='store_true', help='Save PNG charts')
    args = parser.parse_args()

    run  = _get_run(args.run)
    data = _build_analysis(run)
    slug = f'{STATE}_{PLAN_TYPE}_{PLAN_YEAR}_{run["meta"]["id"]}'
    out  = Path(args.out)
    out.mkdir(exist_ok=True)

    if args.fmt == 'yaml':
        import yaml
        path = out / f'{slug}.yaml'
        path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
    else:
        path = out / f'{slug}.json'
        path.write_text(json.dumps(data, indent=2))
    print(f'Saved {path}')

    if args.charts:
        for name, fn in [('histograms', _make_histograms), ('river', _make_river)]:
            fig = fn(run)
            if fig:
                import matplotlib.pyplot as plt
                img = out / f'{slug}_{name}.png'
                fig.savefig(img, dpi=FIG_DPI, bbox_inches='tight')
                plt.close(fig)
                print(f'Saved {img}')


if __name__ == '__main__':
    main()
