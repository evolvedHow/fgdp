# Redistricting Ensemble Metrics Reference

All metrics are scored by comparing the **enacted plan** against the distribution of
**neutral ensemble plans** — maps drawn without partisan intent using GerryChain (ReCom
Markov chain, 9,501 draws) and/or ALARM/SMC (Harvard, 5,000 independent plans).

**Election baseline:** five-election composite — 2018 Governor, 2020 President, 2021
Warnock runoff (Jan 5), 2022 Governor + Senate average, 2024 President.  
**Vote share used:** two-party Democratic share `dem_2pv = dem_votes / (dem_votes + rep_votes)`.  
**Weight:** each VTD is weighted by `VAP_MOD = P0040001 − P0050003` (voting-age population
minus incarcerated population).

---

## Table of Contents

- [Partisan Fairness](#partisan-fairness)
  - [Seat–Vote Proportionality (`dem_seats`)](#1-seatvote-proportionality-dem_seats)
  - [Wasted Votes Balance (`efficiency_gap`)](#2-wasted-votes-balance-efficiency_gap)
  - [Vote Distribution Symmetry (`mean_median`)](#3-vote-distribution-symmetry-mean_median)
  - [Partisan Bias (`partisan_bias`)](#4-partisan-bias-partisan_bias)
- [Competitiveness](#competitiveness)
  - [Electoral Competitiveness (`comp_seats`)](#5-electoral-competitiveness-comp_seats)
  - [Safe Democratic Seats (`dem_safe_seats`)](#6-safe-democratic-seats-dem_safe_seats)
  - [Safe Republican Seats (`rep_safe_seats`)](#7-safe-republican-seats-rep_safe_seats)
- [Geographic Integrity](#geographic-integrity)
  - [Compactness (`polsby_popper`)](#8-compactness-polsby_popper)
  - [County Splits (`county_splits`)](#9-county-splits-county_splits)
  - [Split Cities (`muni_splits`)](#10-split-cities-muni_splits)
- [Minority Representation](#minority-representation)
  - [Majority-Black Districts (`maj_black`)](#11-majority-black-districts-maj_black)
  - [Minority Coalition Districts (`min_coal`)](#12-minority-coalition-districts-min_coal)
  - [Minority Influence Districts (`min_influence`)](#13-minority-influence-districts-min_influence)
  - [Majority-Hispanic Districts (`maj_hisp`)](#14-majority-hispanic-districts-maj_hisp)
  - [Majority-AIAN Districts (`maj_aian`)](#15-majority-aian-districts-maj_aian)
  - [Majority-Asian Districts (`maj_asian`)](#16-majority-asian-districts-maj_asian)
  - [Majority-White Districts (`maj_white`)](#17-majority-white-districts-maj_white)
- [Grading System](#grading-system)
- [Configurable Thresholds](#configurable-thresholds)

---

## Partisan Fairness

### 1. Seat–Vote Proportionality (`dem_seats`)

**Question:** Does the seat count reflect how people actually voted?

**Formula:**
```
dem_seats = count(d : dem_2pv_d ≥ 0.50)
```
where `dem_2pv_d = Σ dem_votes_vtd / Σ (dem_votes_vtd + rep_votes_vtd)` for all VTDs in district `d`.

**What it measures:** Number of districts projected to lean Democratic based on the
composite election baseline. In a fair map the share of seats each party wins should
reflect its share of statewide votes. The histogram shows how many Democratic-leaning
seats thousands of neutral alternative maps produce. If the enacted map falls far below
this range, lines were likely drawn to systematically under-represent one party.

**Data:** VTD composite — 2018–2024 five-election average.

**Grading:** Directional, one-sided (lower = worse). Only penalises having *too few*
Democratic seats.

| Grade | Percentile threshold |
|-------|---------------------|
| A | ≥ 50th pct of ensemble |
| B | ≥ 20th pct |
| C | ≥ 5th pct |
| F | < 5th pct |

---

### 2. Wasted Votes Balance (`efficiency_gap`)

**Question:** Are both parties' votes equally effective at winning representation?

**Formula:**
```
efficiency_gap = (Σ wasted_dem − Σ wasted_rep) / Σ total_votes   across all districts
```

**Wasted votes defined:**
- Losing district: *all* votes cast for the losing party are wasted
- Winning district: votes beyond 50% + 1 (the surplus margin) are wasted

Positive value → Democratic votes wasted at a higher rate → Republican structural
advantage. Negative value → reverse. A value near zero means both parties convert
votes to seats at roughly equal efficiency.

**Background:** Developed by Stephanopoulos & McGhee; cited in federal gerrymandering
litigation (*Gill v. Whitford*, *Common Cause v. Rucho*).

**Data:** VTD composite — 2018–2024 composite.

**Grading:** Symmetric (both tails bad — extreme in either direction signals a problem).

| Grade | Percentile range |
|-------|-----------------|
| A | 40th–60th pct (near neutral median) |
| B | 20th–80th pct |
| C | 5th–95th pct |
| F | outside 5th–95th pct |

---

### 3. Vote Distribution Symmetry (`mean_median`)

**Question:** Does each party need the same number of votes to win a district?

**Formula:**
```
mean_median = mean(dem_2pv_d) − median(dem_2pv_d)   across all districts d
```

**What it measures:** The Mean-Median difference reveals whether one party's votes are
systematically spread more efficiently across districts. When one party wins many
districts by modest margins while the other piles up large majorities in fewer
districts, the first party has a structural seat advantage even at equal statewide
vote totals. A value near zero means both parties convert votes to seats at roughly
equal rates.

Positive → Democratic mean exceeds median → Dem votes distributed less efficiently
(Republican structural advantage).  
Negative → reverse.

**Data:** VTD composite — 2018–2024 composite.

**Grading:** Symmetric (both tails bad).

| Grade | Percentile range |
|-------|-----------------|
| A | 40th–60th pct |
| B | 20th–80th pct |
| C | 5th–95th pct |
| F | outside 5th–95th pct |

---

### 4. Partisan Bias (`partisan_bias`)

**Question:** Which party would win more seats if both parties tied statewide?

**Formula (Princeton cube-law normative test):**
```
partisan_bias = seats_R(statewide_vote = 50%) − seats_D(statewide_vote = 50%)
```

**What it measures:** How many more seats one party would win compared to the other if
both received exactly 50% of the statewide vote. A value of 0 means neither party has
a structural advantage at a tied election. Non-zero values reveal the built-in tilt of
the map.

**Data:** VTD composite — 2018–2024 composite.

**Grading:** Normative pass/fail test (Princeton cube-law), not A/B/C/F. Reported
separately as `normative_pass` in the composite grade.

---

## Competitiveness

### 5. Electoral Competitiveness (`comp_seats`)

**Question:** How many districts give voters a meaningful choice?

**Formula:**
```
comp_seats = count(d : |dem_2pv_d − 0.50| ≤ competitive_margin)
```

**Default:** `competitive_margin = 0.05` (±5 percentage points of 50/50).  
**Configurable via:** `COMPETITIVE_THRESHOLD_DEFAULT` in `fdp/scripts/build_scorecard.py`  
**Env override (upload scorer):** `COMPETITIVE_MARGIN_MAIN` in `fdensemble/main.py`

**What it measures:** Districts where the outcome is genuinely uncertain. Competitive
districts force elected officials to be responsive to a broader range of constituents.
Maps designed to protect incumbents (from either party) minimise competitiveness.

**Data:** VTD composite — 2018–2024 composite.

**Grading:** Directional (higher = more competitive seats = better).

| Grade | Percentile threshold |
|-------|---------------------|
| A | ≥ 95th pct |
| B | ≥ 64th pct |
| C | ≥ 5th pct |
| F | < 5th pct |

---

### 6. Safe Democratic Seats (`dem_safe_seats`)

**Formula:**
```
dem_safe_seats = count(d : dem_2pv_d > 0.50 + competitive_margin)
```

Democratic-leaning districts outside the competitive zone. Together with safe
Republican seats and competitive seats, this completes the three-bucket political
balance picture.

**Default:** `competitive_margin = 0.05`.

**Grading:** Symmetric — unusually high (over-packing) or unusually low count both
signal that neutral redistricting has been departed from.

---

### 7. Safe Republican Seats (`rep_safe_seats`)

**Formula:**
```
rep_safe_seats = count(d : dem_2pv_d < 0.50 − competitive_margin)
```

Republican-leaning districts outside the competitive zone.

**Default:** `competitive_margin = 0.05`.

**Grading:** Symmetric (same as `dem_safe_seats`).

---

## Geographic Integrity

### 8. Compactness (`polsby_popper`)

**Question:** Are districts drawn in reasonably compact shapes?

**Formula:**
```
polsby_popper = mean_d( 4π × area_d / perimeter_d² )
```

Averaged across all districts. Score of 1.0 = perfect circle; values approach 0 as
shapes become more irregular or elongated. Higher is better.

**Data:** 2020 Census VTD geometries (TIGER/Line shapefiles, EPSG:4269 → projected
for area/perimeter calculation).

**Grading:** Directional (higher = more compact = better).

| Grade | Percentile threshold |
|-------|---------------------|
| A | ≥ 95th pct |
| B | ≥ 64th pct |
| C | ≥ 5th pct |
| F | < 5th pct |

---

### 9. County Splits (`county_splits`)

**Question:** How many counties are divided between districts?

**Formula:**
```
county_splits = count(counties c : ∃ VTDs v1, v2 ∈ c assigned to different districts)
```

A county is "split" when at least two of its VTDs are assigned to different
congressional or legislative districts. Fewer is better.

**Data:** 2020 Census county–VTD geographic assignment (GEOID nesting).

**Grading:** Directional (lower = fewer splits = better; inverted percentile rank used).

| Grade | Inverted pct threshold |
|-------|----------------------|
| A | ≥ 95th pct (fewest splits) |
| B | ≥ 64th pct |
| C | ≥ 5th pct |
| F | < 5th pct (most splits) |

---

### 10. Split Cities (`muni_splits`)

**Question:** How many cities and towns are divided across different districts?

**Formula:**
```
muni_splits = count(municipalities m : ∃ VTDs v1, v2 ∈ m assigned to different districts)
```

An incorporated municipality (city, town) is "split" when its VTDs are assigned to
two or more districts. This is an **urban cracking indicator** — splitting a city
dilutes its collective political voice.

**Key finding for Georgia Congress:** The enacted map splits only 12 municipalities —
fewer than 99.9% of the 9,501 neutral plans (grade A on this metric). Yet it produces
0 competitive seats. This paradox reveals that manipulation operates at the sub-municipal
VTD level, invisible to city-level split counts.

**Data:** 2020 Census VTD-to-municipality mapping (COUSUBFP field).

**Grading:** Directional (lower = fewer splits = better; inverted percentile rank).

---

## Minority Representation

> **VRA Floor Grading:** All minority-opportunity metrics (except `maj_white` and
> `min_influence`) use **floor-based grading**. The Voting Rights Act is a floor
> statute — it prohibits dilution of minority voting power but does not penalise maps
> that produce more minority-opportunity districts than neutral maps. Having MORE
> majority-minority districts is never a problem under VRA. A symmetric grade is also
> reported alongside the floor grade for comparison with the traditional Princeton
> methodology.

**CVAP vs VAP:** All GerryChain scorecard metrics use Citizen Voting Age Population
(CVAP, from 2024 ACS 5-year estimates disaggregated to 2020 blocks) for legal
precision under Section 2 VRA. CVAP excludes non-citizens, who cannot vote.
ALARM scorecard metrics use 2020 Census VAP as a fallback (CVAP not in the
ALARM dataverse files).

### 11. Majority-Black Districts (`maj_black`)

**Question:** Do Black voters have the opportunity to elect representatives of their choice?

**Formula:**
```
maj_black = count(d : black_CVAP_d / total_CVAP_d ≥ bvap_majority_threshold)
```

**Default:** `bvap_majority_threshold = 0.50` (50% Black CVAP).  
**Configurable via:** `BVAP_MAJORITY_THRESHOLD` in `fdp/scripts/build_scorecard.py`

**Data:**
- GerryChain: 2024 ACS 5-year CVAP disaggregated to 2020 blocks (RDH, retrieved 2026-02)
- ALARM: 2020 Census VAP (P0030003 Black alone or in combination)

**Grading:** VRA floor (one-sided).

| Grade | Meaning |
|-------|---------|
| A | ≥ 50th pct — at or above neutral median |
| B | ≥ 10th pct — at or above the race-neutral VRA floor |
| F | < 10th pct — below the VRA floor (dilution signal) |

*Symmetric grade also reported for comparison.*

---

### 12. Minority Coalition Districts (`min_coal`)

**Question:** Do communities of color collectively hold electoral influence?

**Formula:**
```
min_coal = count(d : (1 − white_CVAP_d / total_CVAP_d) ≥ majority_threshold)
```

Districts where voters of color — Black, Hispanic, Asian, and others combined —
together make up more than 50% of CVAP. Even when no single racial group holds a
majority, communities of color can collectively influence electoral outcomes.

**Default:** `majority_threshold = 0.50`.  
**Configurable via:** `MAJORITY_THRESHOLD` in `fdp/scripts/build_scorecard.py`

**Data:** 2024 ACS 5-year CVAP (GerryChain) / 2020 Census VAP (ALARM).

**Grading:** VRA floor (one-sided), same thresholds as `maj_black`.

---

### 13. Minority Influence Districts (`min_influence`)

**Question:** How many districts give communities of color meaningful influence without a majority?

**Formula:**
```
min_influence = count(d : influence_min ≤ (1 − white_CVAP_d / total_CVAP_d) < influence_max)
```

Districts where communities of color hold between the FDGA influence floor and the
majority threshold of CVAP — below the Section 2 VRA majority threshold but above the
level at which minority voters can meaningfully affect outcomes and hold candidates
accountable.

**Defaults:**
- `influence_min = 0.37` (37% minority CVAP) — FDGA influence floor  
- `influence_max = 0.50` (50% minority CVAP) — majority threshold upper bound

**Configurable via:** `INFLUENCE_MIN_THRESHOLD`, `INFLUENCE_MAX_THRESHOLD` in
`fdp/scripts/build_scorecard.py`

**Data:** 2024 ACS 5-year CVAP (GerryChain) / 2020 Census VAP (ALARM).

**Grading:** Directional (higher = more influence districts = better).

---

### 14. Majority-Hispanic Districts (`maj_hisp`)

**Formula:**
```
maj_hisp = count(d : hispanic_CVAP_d / total_CVAP_d ≥ majority_threshold)
```

**Default:** `majority_threshold = 0.50`.

**Grading:** VRA floor (one-sided), same thresholds as `maj_black`.

---

### 15. Majority-AIAN Districts (`maj_aian`)

**Formula:**
```
maj_aian = count(d : AIAN_CVAP_d / total_CVAP_d ≥ majority_threshold)
```

American Indian and Alaska Native Citizen VAP share per district.

**Default:** `majority_threshold = 0.50`.

**Grading:** VRA floor (one-sided).

---

### 16. Majority-Asian Districts (`maj_asian`)

**Formula:**
```
maj_asian = count(d : asian_CVAP_d / total_CVAP_d ≥ majority_threshold)
```

Asian American Citizen VAP share per district.

**Default:** `majority_threshold = 0.50`.

**Grading:** VRA floor (one-sided).

---

### 17. Majority-White Districts (`maj_white`)

**Formula:**
```
maj_white = count(d : white_CVAP_d / total_CVAP_d ≥ majority_threshold)
```

Districts where non-Hispanic white citizens are a majority of CVAP. Shown alongside
minority metrics to complete the full demographic picture of how the map distributes
political power across racial groups.

**Default:** `majority_threshold = 0.50`.

**Grading:** Symmetric (not floor-based — unusually high or unusually low count
compared to neutral maps both indicate departure from geography-driven redistricting).

---

## Grading System

### Standard Princeton Grades

For most metrics, grades are assigned based on the enacted plan's **percentile rank**
within the neutral ensemble distribution.

**Symmetric** (both tails bad — `efficiency_gap`, `mean_median`, `maj_white`,
`dem_safe_seats`, `rep_safe_seats`):

| Grade | Percentile range |
|-------|-----------------|
| A | 40th–60th pct (near neutral median) |
| B | 20th–80th pct |
| C | 5th–95th pct |
| F | outside 5th–95th pct |

**Directional, higher is better** (`comp_seats`, `polsby_popper`, `min_influence`):

| Grade | Percentile threshold |
|-------|---------------------|
| A | ≥ 95th pct |
| B | ≥ 64th pct |
| C | ≥ 5th pct |
| F | < 5th pct |

**Directional, lower is better** (`county_splits`, `muni_splits`):
Same thresholds, applied to the inverted (1 − pct_rank) distribution.

**Seats grade, one-sided** (`dem_seats`):

| Grade | Percentile threshold |
|-------|---------------------|
| A | ≥ 50th pct |
| B | ≥ 20th pct |
| C | ≥ 5th pct |
| F | < 5th pct |

### VRA Floor Grade

Applied to `maj_black`, `min_coal`, `maj_hisp`, `maj_aian`, `maj_asian`:

| Grade | Meaning |
|-------|---------|
| A | ≥ 50th pct — at or above the neutral ensemble median |
| B | ≥ 10th pct — at or above the race-neutral VRA floor |
| F | < 10th pct — below the VRA floor; potential dilution |

No Grade C — there is no "middle" concern for VRA floor metrics. The question is
simply whether the map meets the floor neutral redistricting would establish.

A **symmetric grade** (traditional Princeton method) is always reported alongside for
reference. The VRA floor grade is the operative grade for advocacy purposes.

### Composite Grades

| Composite | Metrics included |
|-----------|-----------------|
| `_overall` | Weighted average of all sub-grades |
| `_partisan_fairness` | `dem_seats`, `efficiency_gap`, `mean_median`, `partisan_bias` (normative) |
| `_geographic` | `polsby_popper`, `county_splits`, `muni_splits` |
| `comp_seats` | Reported standalone as the competitiveness indicator |

The `_partisan_fairness` composite requires **all three** ensemble metrics to pass
(5th–95th pct) for an ensemble pass. If any metric is an extreme outlier (>97th or
<3rd pct), the composite is downgraded one letter.

---

## Configurable Thresholds

All defaults are set in `fdp/scripts/build_scorecard.py`. The upload scorer in
`fdensemble/main.py` has an independent `COMPETITIVE_MARGIN` env var.

| Parameter | Default | Affects | Source constant |
|-----------|---------|---------|-----------------|
| `competitive_margin` | `0.05` (±5pp) | `comp_seats`, `dem_safe_seats`, `rep_safe_seats` | `COMPETITIVE_THRESHOLD_DEFAULT` |
| `majority_threshold` | `0.50` (50%) | `maj_hisp`, `maj_aian`, `maj_asian`, `min_coal`, `maj_white` | `MAJORITY_THRESHOLD` |
| `bvap_majority_threshold` | `0.50` (50%) | `maj_black` | `BVAP_MAJORITY_THRESHOLD` |
| `influence_min_threshold` | `0.37` (37%) | `min_influence` (lower bound) | `INFLUENCE_MIN_THRESHOLD` |
| `influence_max_threshold` | `0.50` (50%) | `min_influence` (upper bound) | `INFLUENCE_MAX_THRESHOLD` |

**CLI overrides** (when running `build_scorecard.py` directly):
```bash
uv run python fdp/scripts/build_scorecard.py \
  --competitive-threshold 0.07 \
  --influence-min 0.35 \
  --influence-max 0.50 \
  --majority-threshold 0.50
```

**Upload scorer env var:**
```
COMPETITIVE_MARGIN_MAIN=0.07   # overrides the ±3.5pp default in fdensemble/main.py
```

> ⚠️ **Known inconsistency:** The scorecard builder uses `competitive_margin = 0.05`
> (±5pp) while the upload scorer (`fdensemble/main.py`) uses `COMPETITIVE_MARGIN = 0.07`
> (±3.5pp half-margin, i.e., ±3.5pp). These should be unified. Tracked in WORKAROUNDS.md.

---

## Data Sources

| Dataset | Description | Used for |
|---------|-------------|---------|
| `GA_cd_2020_map.rds` | ALARM `redist_map`, 2,698 VTDs × 55 cols | ALARM ensemble base map |
| `GA_cd_2020_plans.rds` | ALARM `redist_plans`, 5,001 draws (draw 1 = enacted) | ALARM ensemble distribution |
| `ga_pl2020_vtd.zip` | 2020 Census PL 94-171 VTD shapefile, EPSG:4269 | VTD geometries, population |
| `ga_pl2020_b.zip` | 2020 PL 94-171 block-level (~232K blocks) | VAP_MOD disaggregation weights |
| `ga_cvap_2024_2020_b_csv.zip` | 2024 ACS CVAP disaggregated to 2020 blocks (RDH) | CVAP for all minority metrics |
| `ga_2022_gen_2020_blocks.zip` | 2022 general election disaggregated to 2020 blocks (RDH) | 2022 election composite |
| `ga_2024_gen_2020_blocks.zip` | 2024 general election disaggregated to 2020 blocks (RDH) | 2024 election composite |
| VTD composite (in ALARM map) | 2016–2020 elections at VTD level (ALARM pre-computed) | 2018, 2020, 2021 composite |

**Block → VTD aggregation:** 2020 Census blocks nest perfectly within 2020 VTDs.
Aggregation uses centroid-in-polygon spatial join. Weight: `VAP_MOD` (VAP minus
incarcerated, to correct for Georgia's large prison populations in rural counties).

---

*Generated from `fdp/scripts/build_scorecard.py` · `fdensemble/main.py` · `fgdp/CLAUDE.md`*  
*Last updated: 2026-06-07*
