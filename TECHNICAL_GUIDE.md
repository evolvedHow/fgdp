# Fair Districts GA — Technical Reference Guide

**Purpose:** This guide documents the Common Data Model (CDM), every metric and KPI formula, and how each calculation is displayed across the four Fair Districts apps. It is written for analysts who want to verify results by hand, check the raw data, or audit the code's accuracy. No programming knowledge is required to follow the formulas.

---

## Table of Contents

1. [Platform Overview](#1-platform-overview)
2. [CDM — Common Data Model](#2-cdm--common-data-model)
   - 2.1 [Boundary Files (GeoJSON)](#21-boundary-files-geojson)
   - 2.2 [Demographics JSON](#22-demographics-json)
   - 2.3 [Election Results (JSON)](#23-election-results-json)
   - 2.4 [Ensemble Parquet Files](#24-ensemble-parquet-files)
   - 2.5 [LRDB GeoJSON](#25-lrdb-geojson)
   - 2.6 [Redistricting History YAML](#26-redistricting-history-yaml)
3. [Metrics & KPI Formulas](#3-metrics--kpi-formulas)
   - 3.1 [Partisan Lean Index](#31-partisan-lean-index)
   - 3.2 [Competitive Race](#32-competitive-race)
   - 3.3 [Contested Race](#33-contested-race)
   - 3.4 [Safe Seat Percentage](#34-safe-seat-percentage)
   - 3.5 [Efficiency Gap](#35-efficiency-gap)
   - 3.6 [Mean-Median Difference](#36-mean-median-difference)
   - 3.7 [Partisan Bias](#37-partisan-bias)
   - 3.8 [Seats-Votes Responsiveness Curve](#38-seats-votes-responsiveness-curve)
   - 3.9 [Responsiveness Score](#39-responsiveness-score)
   - 3.10 [Polsby-Popper Compactness](#310-polsby-popper-compactness)
   - 3.11 [Convex Hull Ratio](#311-convex-hull-ratio)
   - 3.12 [County Splits](#312-county-splits)
   - 3.13 [Majority-Minority Districts](#313-majority-minority-districts)
   - 3.14 [VRA Influence Districts](#314-vra-influence-districts)
   - 3.15 [Population Deviation](#315-population-deviation)
   - 3.16 [Population Displacement (Voter Disruption)](#316-population-displacement-voter-disruption)
   - 3.17 [Proportionality Gap](#317-proportionality-gap)
   - 3.18 [Princeton A-Grade Benchmarks](#318-princeton-a-grade-benchmarks)
   - 3.19 [Partisan Safety Tiers](#319-partisan-safety-tiers)
4. [GerryChain Ensemble Analysis](#4-gerrychain-ensemble-analysis)
5. [How Metrics Appear in Each App](#5-how-metrics-appear-in-each-app)
   - 5.1 [fdex — District Explorer](#51-fdex--district-explorer)
   - 5.2 [map-compare — Plan Comparison Tool](#52-map-compare--plan-comparison-tool)
   - 5.3 [fdga-chain — Ensemble Analysis API](#53-fdga-chain--ensemble-analysis-api)
   - 5.4 [lrdb — Local Redistricting Database](#54-lrdb--local-redistricting-database)
6. [How to Verify Results Manually](#6-how-to-verify-results-manually)
7. [Data File Locations](#7-data-file-locations)

---

## 1. Platform Overview

The **Fair Districts Data Platform (FDP)** is a shared Python library and data store that all apps draw from. It enforces a single canonical dataset so that every app reports the same numbers from the same source files.

```
~/codebox/fgdp/
├── fdp/                  ← Shared data platform (Python package + data files)
│   ├── config/
│   │   ├── global.yml    ← Locked platform settings (state=GA, census_year=2020)
│   │   ├── defaults.yml  ← Default map/LLM/chain settings
│   │   └── apps/         ← Per-app config overrides
│   └── data/repos/main/  ← The CDM — all canonical data lives here
├── fdex/                 ← District Explorer (public-facing map)
├── map-compare/          ← Side-by-side plan comparison tool
├── fdga-chain/           ← Ensemble/GerryChain analysis API
└── lrdb/                 ← Local Redistricting Database
```

**State context:** All data is for **Georgia (GA)**, using the **2020 Decennial Census** for population, and **American Community Survey (ACS) 2022** for socioeconomic variables.

---

## 2. CDM — Common Data Model

### 2.1 Boundary Files (GeoJSON)

**Location:** `fdp/data/repos/main/boundaries/`

**Sub-directories:**

| Path | What it contains |
|---|---|
| `boundaries/congress/` | Congressional district GeoJSON files (14 districts) |
| `boundaries/house/` | GA House district GeoJSON files (180 districts) |
| `boundaries/senate/` | GA Senate district GeoJSON files (56 districts) |
| `boundaries/reference/` | County and places boundaries (context layers) |

**Named plans available:**

| ID | Label | Districts |
|---|---|---|
| `congress_enacted_24_2024update` | 2024 Enacted Congressional Map | 14 |
| `congress_remedy_a` / `congress_remedy_b` | Court remedy alternatives | 14 |
| `congress12_census20` | 2011 Congressional (re-expressed in 2020 Census) | 14 |
| `congress21_census20` | 2021 Congressional (re-expressed in 2020 Census) | 14 |
| `house_enacted_24_2024update` | 2024 Enacted House Map | 180 |
| `house_remedy_a` / `house_remedy_b` | Court remedy alternatives | 180 |
| `house15_census20` | 2015 House (re-expressed in 2020 Census) | 180 |
| `senate_enacted_24_2024update` | 2024 Enacted Senate Map | 56 |
| `senate_remedy` | Senate remedy map | 56 |
| `senate14_census20` | 2014 Senate (re-expressed in 2020 Census) | 56 |

**GeoJSON Feature Properties — all chambers share this schema:**

| Property | Type | Description |
|---|---|---|
| `district` | number | District number (1–14 Congress; 1–180 House; 1–56 Senate) |
| `pop` | number | Total population, 2020 Census PL 94-171 |
| `tvap` | number | Total Voting-Age Population (18+), 2020 Census |
| `pct_wvap_al` | 0–1 decimal | White alone VAP as fraction of total VAP |
| `pct_bvap_al` | 0–1 decimal | Black or African-American alone VAP as fraction of total VAP |
| `pct_avap_al` | 0–1 decimal | Asian alone VAP as fraction of total VAP |
| `pct_hvp` | 0–1 decimal | Hispanic or Latino VAP as fraction of total VAP |
| `pct_bp_` | 0–1 decimal | BIPOC (non-white) VAP as fraction of total VAP |
| `pct_bvp` | 0–1 decimal | Black VAP (including multiracial) as fraction of total VAP |
| `pct_avp` | 0–1 decimal | Asian VAP (including multiracial) as fraction of total VAP |
| `partisan` | 0–1 decimal | **Partisan Lean Index** — average Democratic % across four statewide elections (see §3.1) |
| `g18_pct_dem` | 0–1 decimal | 2018 Governor race Democratic % |
| `p20_pct_dem` | 0–1 decimal | 2020 Presidential race Democratic % |
| `r21_pct_dem` | 0–1 decimal | 2021 US Senate runoff Democratic % |
| `g22_pct_dem` | 0–1 decimal | 2022 Governor race Democratic % |
| `s22_pct_dem` | 0–1 decimal | 2022 US Senate race Democratic % |

**To convert fractions to percentages:** multiply by 100.  
Example: `pct_bvap_al = 0.479` → 47.9% Black VAP.

**Coordinate Reference System:** WGS84 (EPSG:4326) — longitude/latitude decimal degrees.

**Geometry types:** Polygon or MultiPolygon (for districts with non-contiguous land areas or islands).

---

### 2.2 Demographics JSON

**Location:** `fdp/data/repos/main/demographics/`

**Files:** `congress.json`, `house.json`, `senate.json`

**Structure:** A JSON object keyed by district number (as a string). Each district is an object with ACS 2022 socioeconomic fields.

**Schema per district:**

| Field | Type | Description |
|---|---|---|
| `median_income` | integer | Median household income (USD) |
| `pct_poverty` | 0–1 decimal | Population below federal poverty line |
| `poverty_count` | integer | Count of people below poverty line |
| `pct_bachelors_plus` | 0–1 decimal | Adults with bachelor's degree or higher |
| `bachelors_plus_count` | integer | Count of adults with bachelor's+ |
| `pct_male` | 0–1 decimal | Male population fraction |
| `pct_female` | 0–1 decimal | Female population fraction |
| `pct_married_family` | 0–1 decimal | Households that are married-couple families |
| `married_hh_count` | integer | Count of married-couple households |
| `pct_single_parent` | 0–1 decimal | Single-parent households |
| `single_parent_count` | integer | Count of single-parent households |
| `pct_no_vehicle` | 0–1 decimal | Households with no vehicle |
| `no_vehicle_count` | integer | Count of households with no vehicle |
| `pct_uninsured` | 0–1 decimal | Population without health insurance |
| `uninsured_count` | integer | Count of uninsured people |
| `pct_unemployed` | 0–1 decimal | Unemployment rate (labor force participants) |
| `unemployed_count` | integer | Count of unemployed people |
| `labor_force_count` | integer | Total labor force size |

**Source:** US Census Bureau, American Community Survey 5-year estimates, 2022.

---

### 2.3 Election Results (JSON)

**Location:** `fdga-chain/data/states/GA/{chamber}/{cycle_year}/elections.json`

**Example path:** `data/states/GA/house/2021/elections.json`

**Cycle years:** `2001`, `2005`, `2011`, `2021` — each corresponds to the redistricting cycle's first election.

**Top-level fields:**

| Field | Type | Description |
|---|---|---|
| `state` | string | State abbreviation (always `"GA"`) |
| `chamber` | string | `"house"`, `"senate"`, or `"congress"` |
| `cycle_year` | integer | Redistricting cycle year |
| `election_year` | integer | Year of first general election under that map |
| `num_districts` | integer | Total districts (14/56/180) |
| `total_votes` | integer | Total votes cast across all districts |
| `total_dem_votes` | integer | Total Democratic votes |
| `total_rep_votes` | integer | Total Republican votes |
| `dem_vote_share` | 0–1 decimal | Statewide Democratic 2-party vote share |
| `dem_seat_share` | 0–1 decimal | Democratic seat share (seats won / total) |
| `rep_seat_share` | 0–1 decimal | Republican seat share |
| `contested_districts` | integer | Districts where both parties had votes |
| `safe_districts` | integer | Districts with >7% margin (see §3.4) |
| `competitive_districts` | integer | Districts with ≤7% margin, both parties present |
| `safe_pct` | decimal | `safe_districts / num_districts × 100` |
| `districts` | array | Per-district records (see below) |

**Per-district fields (`districts` array):**

| Field | Type | Description |
|---|---|---|
| `district_id` | string | District number as a string |
| `dem_votes` | integer | Democratic votes in the general election |
| `rep_votes` | integer | Republican votes in the general election |
| `total_votes` | integer | All votes cast (including third party) |
| `dem_pct` | 0–1 decimal | Democratic share of the two-party vote |
| `winner` | `"D"` or `"R"` | Winning party |
| `margin` | 0–1 decimal | Absolute margin: `|dem_pct − 0.5| × 2` (e.g. 0.07 = 7%) |
| `contested` | boolean | `true` if both parties had votes > 0 |
| `safe` | boolean | `true` if `margin > 0.07` |

**Source:** OpenElections Georgia — `openelections-data-ga` on GitHub. Downloaded via `fdga-chain/scripts/fetch_elections.py`.

---

### 2.4 Ensemble Parquet Files

**Location:** `fdp/data/repos/main/ensembles/`

**Files per chamber:** `{chamber}_ensemble.parquet`, `{chamber}_meta.json`, `{chamber}_stability.json`

**Parquet schema** — each row is one accepted plan in the Markov chain:

| Column | Type | Description |
|---|---|---|
| `step` | integer | Step number in the chain (0 = enacted plan) |
| `dem_seats` | integer | Districts where Democrats won a majority |
| `competitive_districts` | integer | Districts with Dem vote share 46.5%–53.5% |
| `efficiency_gap` | float | Signed efficiency gap (positive = R advantage) |
| `mean_median` | float | Mean minus median Democratic vote share |
| `num_cut_edges` | integer | Number of precinct-level boundaries that cross district lines |
| `polsby_popper_mean` | float | Average Polsby-Popper score across all districts |
| `polsby_popper_min` | float | Minimum Polsby-Popper score (least compact district) |
| `majority_minority_districts` | integer | Districts where Black+Hispanic VAP > 50% |

**Current ensemble sizes:**

| Chamber | Steps | Epsilon | Districts | Total Population |
|---|---|---|---|---|
| House | 10,000 | ±7% | 180 | 10,711,902 |
| Senate | 10,000 | ±7% | 56 | 10,711,902 |
| Congress | 10,000 | ±7% | 14 | 10,711,902 |

**Meta JSON fields** (from `{chamber}_meta.json`):

| Field | Description |
|---|---|
| `enacted_metrics` | The metric values for the actual enacted plan (step 0) |
| `columns_used` | Which precinct-level columns map to population, votes, etc. |
| `data_sources` | Provenance: RDH precincts, 2020 Census PL 94-171 block data, enacted shapefiles |
| `algorithm` | ReCom algorithm details, library version, constraints |
| `epsilon` | Population deviation tolerance (0.07 = ±7%) |
| `ran_at` | Timestamp of run |

**Stability JSON** (`{chamber}_stability.json`): Maps each precinct node ID to a fraction (0–1) representing how often that precinct stayed in the same district across all ensemble plans. 1.0 = always same district (core). Near 0 = contested boundary.

**Election data used in ensemble:** 2020 US Presidential election results (Biden/Trump) at the precinct level. This is the vote data from which partisan metrics are derived during ensemble runs — not the general election results in `elections.json`.

---

### 2.5 LRDB GeoJSON

**Location:** `fdp/data/repos/main/lrdb/lrdb_web_20260216.geojson`

**What it is:** 441 features covering Georgia's local redistricting jurisdictions — county commissions, city councils, school boards, and other local governing bodies.

**Key property fields:**

| Field | Type | Description |
|---|---|---|
| `id` | number | Unique jurisdiction identifier |
| `name` | string | Jurisdiction name (e.g. "Johns Creek") |
| `type` | string | Body type: "City Council", "County Commission", "School Board", etc. |
| `dist_type` | string | Election structure: `"districts"`, `"at-large"`, `"mixed"` |
| `pop20` | number | 2020 Census population of the jurisdiction |
| `no_districts` | integer or null | Number of election districts |
| `status` | string | `"complete"` = redistricting done; `"in_progress"` = ongoing |
| `redist_complete` | string | `"yes"`, `"no"`, `"not required"` |
| `redistricted_w` | string | Whether redistricting was required per FDGA analysis |
| `requirements_w` | string | Whether written redistricting requirements exist |
| `guidelines_w` | string | Whether written guidelines exist |
| `lcro_w` | string | Whether local body (not state legislature) controlled the process |
| `gga_adjust_w` | string | Whether the Georgia General Assembly overrode a local plan |
| `participation_w` | string | Whether public participation was documented |
| `controvery_w` | string | Whether controversy was documented |
| `atlarge_w` | string | Whether elections are at-large (no districts) |
| `nonpartisan` | string | Whether elections are nonpartisan |
| `election_type` | string | Description of election structure |
| `terms` | string | Term length for elected positions |
| `website_link` | string | Official website URL |
| `source` | string | Data researcher who collected this entry |
| `summary` | string | Free-text summary (when available) |

**Note:** Many fields use `"yes"` / `"no"` / `"NA"` / `null` rather than booleans. Null means the field was not researched or does not apply.

---

### 2.6 Redistricting History YAML

**Location:** `fdp/data/repos/main/history/redistricting_waves.yml`

Documents Georgia's four mid-decade redistricting events (changes made between the standard decade redistrictings).

**Top-level fields:**

| Field | Description |
|---|---|
| `total_districts_changed` | 71 districts altered across all four waves |
| `additional_bills_not_passed` | 33 bills considered but not enacted |

**Per wave fields:**

| Field | Description |
|---|---|
| `year` | Year the redistricting was enacted |
| `party` | Which party drove the change: `R`, `D`, or `both` |
| `reason` | Stated rationale (often direct quotes from legislators) |
| `legal_context` | Court cases or depositions related to this wave |
| `election_result` | Observed election outcome after the maps took effect |
| `chambers` | List of chambers affected, with district counts |

**The four mid-decade waves:**

| Year | Party | Districts Changed | Key Outcome |
|---|---|---|---|
| 2005–2006 | R | 24 (all 13 Congress + 11 House) | Rs gained 10 House seats despite flat statewide vote share |
| 2012 | R | 23 (House only) | Rs achieved super-majority in Senate; 1 seat shy in House |
| 2015 | Both | 17 (House only) | Incumbents protected; both parties benefited |
| 2023 | R | 7 (1 Congress + 6 House) | Court-ordered VRA change + partisan take-backs |

---

## 3. Metrics & KPI Formulas

All formulas are written so that a non-programmer can follow them step by step. Where a formula divides, confirm the denominator is not zero first.

---

### 3.1 Partisan Lean Index

**Definition:** The average Democratic vote percentage across four specific statewide races within a district. This is the core measure of a district's political character, independent of any single election.

**The four races used:**

| Race | Field in GeoJSON |
|---|---|
| 2018 Governor (Abrams vs. Kemp) | `g18_pct_dem` |
| 2020 Presidential (Biden vs. Trump) | `p20_pct_dem` |
| 2021 US Senate Runoff (Warnock vs. Loeffler) | `r21_pct_dem` |
| 2022 Governor (Abrams vs. Kemp) | `g22_pct_dem` |

**Formula:**

```
partisan_lean = (g18_pct_dem + p20_pct_dem + r21_pct_dem + g22_pct_dem) / 4
```

This is stored as the `partisan` field in each boundary GeoJSON feature (0–1 scale).

**Verification example** — Congressional District 2 (from the CDM):
```
g18 = 0.551,  p20 = 0.552,  r21 = 0.562,  g22 = 0.516
average = (0.551 + 0.552 + 0.562 + 0.516) / 4 = 2.181 / 4 = 0.545 ✓  (stored: 0.548, minor rounding)
```

**Partisan Lean color bands (FDGA standard):**

| Band | Dem % range | Classification |
|---|---|---|
| Deep R | < 40% | Safe Republican |
| Lean R | 40% – 46.5% | Likely Republican |
| Competitive R | 46.5% – 50% | Toss-up (R-leaning) |
| Competitive D | 50% – 53.5% | Toss-up (D-leaning) |
| Lean D | 53.5% – 60% | Likely Democratic |
| Deep D | > 60% | Safe Democratic |

The dividing line at **46.5% / 53.5%** reflects a ±3.5-point band around 50%, which corresponds to a ±7-point margin of victory (see §3.2).

---

### 3.2 Competitive Race

**Definition:** A race (or district) is **competitive** when the margin of victory is 7 points or less — meaning the winner received 53.5% or less and the loser received 46.5% or more.

**Formula using two-party vote shares:**

```
margin = |dem_pct − rep_pct|

competitive = (margin ≤ 0.07)
```

Equivalently, using only the Democratic share:

```
competitive = (dem_pct ≥ 0.465) AND (dem_pct ≤ 0.535)
```

**In the CDM** this maps exactly to the `competitive_districts` count in `elections.json` and the `competitive_districts` column in ensemble parquet files.

**Verification example:**
- District with `dem_pct = 0.52` → `|0.52 − 0.48| = 0.04` → 4% margin → competitive ✓
- District with `dem_pct = 0.58` → `|0.58 − 0.42| = 0.16` → 16% margin → not competitive ✓

---

### 3.3 Contested Race

**Definition:** A race is **contested** when both a Democratic and a Republican candidate received votes. An uncontested race (one party only) is not competitive in any meaningful sense.

**Formula:**

```
contested = (dem_votes > 0) AND (rep_votes > 0)
```

**Note:** A contested race may still be non-competitive (e.g., token opposition). The `competitive` flag (§3.2) additionally requires the margin ≤ 7%.

---

### 3.4 Safe Seat Percentage

**Definition:** The fraction of districts won by a margin greater than 7 points. A "safe" district is one where the winner's vote share exceeded 53.5%. FDGA reported that 97% of Georgia legislative seats were safe in the 2024 elections.

**Formula:**

```
safe_districts = count of districts where margin > 0.07
safe_pct = (safe_districts / num_districts) × 100
```

**Equivalently using Partisan Lean (before election results are known):**

```
safe_districts = count of districts where partisan_lean < 0.465 OR partisan_lean > 0.535
```

**In the CDM:** `safe_pct` is stored in `elections.json` top-level. Each district has a `safe` boolean field.

**In map-compare:** The "Safe Seat %" ScoreCard sums the count of districts in the Safe R + Lean R + Lean D + Safe D tiers (the four non-competitive tiers) and divides by the total number of districts.

---

### 3.5 Efficiency Gap

**Definition:** A measure of partisan gerrymandering that compares how many votes each party "wasted." Wasted votes are: (a) all losing votes, and (b) all winning votes above the bare majority needed. A large efficiency gap means one party systematically wasted more votes than the other — the signature of packing and cracking.

**Step 1 — Wasted votes per district:**

For each district, determine the winner. Then:

```
threshold = floor(total_votes_in_district / 2) + 1   ← minimum votes to win

If Democrats won:
    wasted_dem = dem_votes − threshold      ← excess margin votes
    wasted_rep = rep_votes                  ← all losing votes

If Republicans won:
    wasted_rep = rep_votes − threshold
    wasted_dem = dem_votes
```

**Step 2 — Sum across all districts:**

```
total_wasted_dem = Σ wasted_dem (across all districts)
total_wasted_rep = Σ wasted_rep (across all districts)
total_votes = Σ (dem_votes + rep_votes) (across all districts)
```

**Step 3 — Efficiency Gap:**

```
efficiency_gap = (total_wasted_dem − total_wasted_rep) / total_votes
```

**Sign convention:**
- **Positive** → more Democratic waste → **Republican structural advantage**
- **Negative** → more Republican waste → **Democratic structural advantage**

**Interpretation thresholds:**
- |EG| < 5%: within competitive range
- |EG| 5%–8%: mild partisan lean
- |EG| > 8%: strong potential partisan gerrymander (used in some court analyses)

**Example** — single district with 100,000 total votes:
- Democrats won 60,000 to Republicans' 40,000
- `threshold = 50,001`
- `wasted_dem = 60,000 − 50,001 = 9,999`
- `wasted_rep = 40,000`
- Net advantage: Republicans wasted 40,000 vs. Democrats' 9,999 → Democrats "efficient," Republicans "packed"

**Code location:** `fdga-chain/scripts/compute_metrics.py` lines 33–63; `map-compare/src/lib/utils/fairnessMetrics.ts` lines 10–33.

---

### 3.6 Mean-Median Difference

**Definition:** The difference between the average (mean) Democratic vote share across all districts and the median Democratic vote share. If districts are shaped to "crack" Democratic voters, the mean will be pulled up by a few very high-Dem districts while the median district is more marginal.

**Formula:**

```
dem_vote_shares = [dem_pct for each district]

mean = sum(dem_vote_shares) / count(dem_vote_shares)
median = middle value when dem_vote_shares sorted ascending
         (if even count, average of two middle values)

mean_median = mean − median
```

**Sign convention:**
- **Positive** → mean > median → Democrats concentrated in a few landslide districts (potential packing)
- **Negative** → mean < median → Republicans have structural advantage (typical of a cracked map)

**Verification example** — 5 districts with Dem shares: 30%, 35%, 48%, 70%, 72%
```
sorted: 0.30, 0.35, 0.48, 0.70, 0.72
mean = (0.30 + 0.35 + 0.48 + 0.70 + 0.72) / 5 = 2.55 / 5 = 0.510
median = 0.48 (middle value)
mean_median = 0.510 − 0.480 = +0.030  (Democrats over-represented in mean = packed)
```

**Code location:** `fdga-chain/scripts/compute_metrics.py` lines 66–80; `map-compare/src/lib/utils/fairnessMetrics.ts` lines 36–52.

---

### 3.7 Partisan Bias

**Definition:** At a hypothetical statewide result of exactly 50%–50%, how many seats does each party win? Bias measures the structural tilt of the map independent of any actual election outcome.

**Method (uniform swing simulation):**

1. Calculate the current average partisan lean across all districts.
2. Compute the swing needed to bring that average to exactly 50%.
3. Apply that swing to every district's lean.
4. Count how many districts would flip to Democratic.
5. Express as percentage points above or below 50%.

**Formula:**

```
avg_lean = mean(partisan_lean for all districts)   ← in 0–100 scale
shift = 50 − avg_lean                              ← swing needed to reach 50-50

at_50_dem_seats = count of districts where (partisan_lean + shift) > 50
partisan_bias = (at_50_dem_seats / num_districts × 100) − 50
```

**Sign convention:**
- **Positive** → Democrats would win more than half the seats at 50% vote → Democratic structural advantage
- **Negative** → Republicans would win more than half the seats at 50% vote → Republican structural advantage

**Code location:** `map-compare/src/lib/utils/compactnessMetrics.ts` lines 136–145; `fdga-chain/scripts/compute_metrics.py` lines 109–118.

---

### 3.8 Seats-Votes Responsiveness Curve

**Definition:** A graph that shows how many seats each party would win at various hypothetical statewide vote totals. A perfectly proportional system would show a diagonal line through (50% votes, 50% seats). A gerrymandered map shows a curve that favors one party at the critical 50% mark.

**Method:**

For each hypothetical statewide swing `s` from −25% to +25% in 0.5% steps:

```
adjusted_lean[district] = partisan_lean[district] + s
dem_seats = count of districts where adjusted_lean > 50
vote_share = mean(adjusted_lean)   ← actual average after applying swing
seat_share = dem_seats / num_districts × 100
```

Plot each (vote_share, seat_share) point. The current enacted position is the dot at the plan's actual vote and seat share.

**Code location:** `fdga-chain/scripts/compute_metrics.py` lines 83–106; `map-compare/src/lib/utils/compactnessMetrics.ts` lines 119–133.

---

### 3.9 Responsiveness Score

**Definition:** The slope of the seats-votes curve near the 50% vote-share mark. Higher responsiveness means small changes in the statewide vote produce large changes in seat totals — the system is "sensitive" to voter preferences. Low responsiveness means the map is dominated by safe seats that change hands only in wave elections.

**Formula (linear regression slope near 50%):**

```
near_50 = all points in seats-votes curve where |vote_share − 50%| ≤ 5%
Sort near_50 by vote_share

x_mean = mean(vote_share values in near_50)
y_mean = mean(seat_share values in near_50)

numerator   = Σ (vote_share_i − x_mean) × (seat_share_i − y_mean)
denominator = Σ (vote_share_i − x_mean)²

responsiveness = numerator / denominator
```

**Interpretation:** A competitive system has responsiveness ~2–4 (seats change at roughly 2–4× the rate of votes). Very low responsiveness (< 1) indicates a locked map.

**Code location:** `fdga-chain/scripts/compute_metrics.py` lines 121–138.

---

### 3.10 Polsby-Popper Compactness

**Definition:** Measures how "round" a district is. A perfect circle scores 1.0; elongated, irregular shapes score close to 0. Low scores often indicate districts drawn to include/exclude specific communities.

**Formula:**

```
polsby_popper = (4 × π × Area) / (Perimeter²)
```

Where:
- **Area** is the geographic area of the district polygon (in km²)
- **Perimeter** is the total boundary length of the district (in km)

**Practical ranges for US districts:**
- > 0.40: reasonably compact
- 0.20–0.40: irregular but defensible
- < 0.20: highly irregular, possibly drawn to gerrymander

**Note:** Map-compare uses the Turf.js library to compute geodesic area and perimeter directly from the GeoJSON geometry. The ensemble runner uses the GerryChain library's built-in geographic partition measurements.

**Code location:** `map-compare/src/lib/utils/compactnessMetrics.ts` lines 17–32; `fdga-chain/scripts/run_ensemble.py` lines 137–145.

---

### 3.11 Convex Hull Ratio

**Definition:** The ratio of a district's actual area to the area of its convex hull (the smallest convex polygon that contains the entire district). A value of 1.0 means the district is already convex (no indentations). Lower values indicate concave, irregular shapes.

**Formula:**

```
convex_hull_ratio = district_area / convex_hull_area
```

**Difference from Polsby-Popper:** Polsby-Popper penalizes any boundary complexity, including natural features like rivers. Convex hull ratio specifically captures "concave peninsulas" — lobes and arms reaching out to include specific communities.

**Code location:** `map-compare/src/lib/utils/compactnessMetrics.ts` lines 34–47.

---

### 3.12 County Splits

**Definition:** The count of Georgia counties that are divided across two or more districts. Georgia's constitution requires that district lines avoid splitting counties unnecessarily. Each additional split makes it harder for voters to understand their representation.

**Method:**

For each of Georgia's 159 counties, check whether it intersects more than one district:

```
for each county:
    district_hits = count of districts whose boundary intersects this county
    if district_hits > 1:
        county_splits += 1
```

A bbox (bounding box) prefilter is applied first to skip obviously non-overlapping pairs, then a full polygon intersection test.

**Code location:** `map-compare/src/lib/utils/compactnessMetrics.ts` lines 79–115.

---

### 3.13 Majority-Minority Districts

**Definition:** Districts where non-white voters constitute more than 50% of the Voting Age Population (VAP). These districts are relevant to Voting Rights Act (VRA) analysis, as the VRA requires that minority voters have an adequate opportunity to elect representatives of their choice.

**Formula:**

```
minority_vap = black_vap + hispanic_vap + asian_vap + other_minority_vap

majority_minority = (minority_vap / total_vap) > 0.50
```

**Black VAP Majority (stricter VRA standard):**

```
bvap_majority = (black_vap / total_vap) > 0.50
```

This is the most legally significant threshold — courts have found that Black voters must be the majority of a district's VAP for the district to function as an effective minority-opportunity district.

**In the boundary GeoJSON:**
- `pct_bp_` = BIPOC (all non-white) fraction of VAP — use for majority-minority check
- `pct_bvap_al` = Black alone fraction of VAP — use for Black majority check

**Code location:** `map-compare/src/lib/components/ReportView.svelte` (planStats function); `fdga-chain/scripts/run_ensemble.py` lines 148–163.

---

### 3.14 VRA Influence Districts

**Definition:** Districts where a minority group makes up 37%–50% of VAP. At this level, minority voters can significantly influence election outcomes even without constituting a majority. Courts have recognized "influence districts" as a VRA consideration.

**Thresholds:**

| Category | VAP range |
|---|---|
| Majority district | ≥ 50% |
| Influence district | 37% – 49.9% |
| Below influence | < 37% |

**Applied to each demographic group separately:**

- BVAP Majority: `black_vap / total_vap ≥ 0.50`
- BVAP Influence: `0.37 ≤ black_vap / total_vap < 0.50`
- MVAP Majority: `minority_vap / total_vap ≥ 0.50`
- MVAP Influence: `0.37 ≤ minority_vap / total_vap < 0.50`
- HVAP Majority/Influence: same thresholds for Hispanic VAP
- AVAP Majority/Influence: same thresholds for Asian VAP

**Code location:** `map-compare/src/lib/utils/spatialAnalysis.ts` lines 256–298.

---

### 3.15 Population Deviation

**Definition:** How much a district's population differs from the ideal (equal) district size. Federal courts require congressional districts to have nearly exactly equal populations; state legislative districts may deviate up to ±10%.

**Formula:**

```
total_population = Σ pop (all districts in plan)
ideal_population = total_population / num_districts

deviation[district] = (district_pop − ideal_population) / ideal_population × 100%

max_population_deviation = max(|deviation[district]|) for all districts
```

**Legal standards:**
- Congressional districts: essentially zero deviation allowed (< 1 person in practice)
- State House/Senate: ±10% typically the legal maximum; ±5% is considered good practice

**In the CDM:** `pop` (from GeoJSON) is the 2020 Census population. For congressional districts, total GA population is 10,711,908; ideal = 764,422 per district.

**Code location:** `map-compare/src/lib/components/ReportView.svelte` (planStats function, `maxDev`).

---

### 3.16 Population Displacement (Voter Disruption)

**Definition:** When a redistricting plan is adopted, voters who are moved into a new district lose their existing relationship with their representative and must re-learn a new one. Displacement measures how many people were moved beyond what was strictly necessary for population equalization.

**Key concept — Minimum Required Displacement:**

```
ideal_population = total_population / num_districts

For each district in Plan A where pop > ideal:
    min_required_displaced += (district_pop − ideal_population)
```

This is the theoretical minimum number of people who had to move in any plan that achieves equal population — you can't equalize populations without moving at least this many.

**Total Displacement (area-weighted method for small plans ≤20 districts):**

For each Plan A district `i`, find which Plan B district `j` overlaps it most:

```
for each Plan A district i:
    for each Plan B district j:
        overlap_area[i][j] = area of intersection of district i and district j

    dominant_B = Plan B district with largest overlap_area
    displaced_area = area_i − overlap_area[i][dominant_B]
    displaced_pop[i] = pop_i × (displaced_area / area_i)

total_displaced = Σ displaced_pop[i]
```

**Total Displacement (centroid method for large plans >20 districts):**

```
for each Plan A district i:
    centroid_i = geographic center point of district i
    
    if centroid_i falls inside same-numbered Plan B district:
        displaced_pop[i] = 0
    else:
        displaced_pop[i] = pop_i   ← entire district treated as displaced

total_displaced = Σ displaced_pop[i]
```

**Excess Displacement:**

```
excess_displaced = total_displaced − min_required_displaced
excess_pct = excess_displaced / total_population × 100%
```

Excess displacement is the amount of voter disruption that went beyond population equalization — it represents a political choice about which communities to split and which to keep together.

**Code location:** `map-compare/src/lib/utils/displacementMetrics.ts`.

---

### 3.17 Proportionality Gap

**Definition:** The difference between a party's seat share and its vote share. In a proportional system, a party that wins 55% of statewide votes should win approximately 55% of seats. The gap measures how much the map diverges from this baseline.

**Formula:**

```
rep_proportionality_gap = rep_seat_share − rep_vote_share
```

**Sign convention:**
- **Positive** → Republicans win more seats than their vote share warrants → structural Republican advantage
- **Negative** → Republicans win fewer seats than their vote share warrants (rare in Georgia)

**Example:** If Republicans win 57% of statewide votes but hold 67% of seats:
```
rep_proportionality_gap = 0.67 − 0.57 = +0.10  → R wins 10 percentage points more seats than votes
```

**In the CDM:** Computed per cycle in `fdga-chain/api/main.py`'s `/proportionality` endpoint, which draws on `dem_seat_share` and `dem_vote_share` from `metrics.json` for each cycle year.

---

### 3.18 Princeton A-Grade Benchmarks

**Definition:** The Princeton Gerrymandering Project ran approximately 1 million simulated neutral maps for Georgia using only legal constraints (equal population, contiguous districts, no partisan intent). The "A-grade" range is the set of outcomes that appear with reasonable frequency in neutral maps. A plan falling outside these ranges is statistically unusual and likely reflects partisan intent.

**Georgia A-grade ranges (source: Princeton Gerrymandering Project, cited in FDGA Town Hall presentations):**

| Chamber | Total Districts | R Seats (A-grade) | D Seats (A-grade) | Competitive Districts (A-grade) |
|---|---|---|---|---|
| GA Senate | 56 | 29 – 31 | 25 – 27 | 2 – 6 |
| GA House | 180 | 94 – 97 | 83 – 86 | 11 – 20 |
| Congress | 14 | 8 | 6 | 0 – 2 |

**Grading logic used in fdga-chain:**

```
For each metric (dem_seats, competitive_districts):
    in_range = benchmark_min ≤ enacted_value ≤ benchmark_max

If all metrics in range:  grade = "A"
If all but one in range:  grade = "B"
If at least one in range: grade = "C"
If none in range:         grade = "F"
```

**How to verify manually:**
1. Count the actual number of Democratic seats in the enacted plan.
2. Check if that number falls between the min and max shown above.
3. Count competitive districts (those with partisan lean 46.5%–53.5%).
4. Check if that count falls in the competitive range.

**Code location:** `fdga-chain/api/main.py`, `PRINCETON_BENCHMARKS` constant and `_princeton_grade()` function.

---

### 3.19 Partisan Safety Tiers

**Definition:** Each district is classified into one of six tiers based on its Partisan Lean Index (§3.1). These tiers are used to color-code maps and count safe vs. competitive seats.

**Tier thresholds** (based on Partisan Lean as a 0–100 Dem percentage):

| Tier | Lean range | Description |
|---|---|---|
| Safe R | partisan_lean < 40% | Safe Republican; margin > 20% |
| Lean R | 40% ≤ lean < 46.5% | Likely Republican; margin 7–20% |
| Competitive R | 46.5% ≤ lean < 50% | Toss-up, slight Republican lean; margin ≤ 7% |
| Competitive D | 50% ≤ lean < 53.5% | Toss-up, slight Democratic lean; margin ≤ 7% |
| Lean D | 53.5% ≤ lean < 60% | Likely Democratic; margin 7–20% |
| Safe D | lean ≥ 60% | Safe Democratic; margin > 20% |

**The 7-point margin line:** The 46.5%/53.5% cutoffs are derived from the FDGA competitive threshold. If the Dem share is 53.5%, then Dem gets 53.5% and Rep gets 46.5%, meaning the winner's margin = 53.5% − 46.5% = 7.0%.

**Code location:** `map-compare/src/lib/utils/spatialAnalysis.ts`, `safetyTier()` function at line 218.

---

## 4. GerryChain Ensemble Analysis

### What is an ensemble?

An ensemble is a large collection of alternative redistricting maps generated by a computer algorithm that follows only the legal minimum rules: equal population, geographically contiguous districts. The algorithm does not know or care about partisan outcomes. By running tens of thousands of these maps, we get a picture of what "neutral" redistricting looks like — and we can then ask: where does the enacted plan fall in this distribution?

### The ReCom algorithm

GerryChain uses the **ReCom (Recombination)** algorithm:

1. **Start** with the enacted plan as the initial state.
2. **Select** two adjacent districts at random.
3. **Merge** them into a single region.
4. **Re-split** the merged region into two equal-population districts using a random spanning tree (a tree that connects all precincts with no loops).
5. **Accept** the new plan (in standard ReCom, always accept; in Reversible ReCom, sometimes reject to maintain statistical rigor).
6. **Repeat** 10,000 times, recording metrics at each step.

### What the ensemble measures

At each step, six metrics are recorded for the current plan:

| Metric | What it measures |
|---|---|
| `dem_seats` | How many districts Democrats would win based on 2020 Presidential vote |
| `competitive_districts` | Districts with Dem vote share 46.5%–53.5% |
| `efficiency_gap` | Partisan waste disparity (see §3.5) |
| `mean_median` | Mean-median Dem vote share difference (see §3.6) |
| `polsby_popper_mean` | Average compactness across all districts |
| `polsby_popper_min` | Worst-case (least compact) district |
| `majority_minority_districts` | VRA-relevant minority districts |
| `num_cut_edges` | Number of precinct boundaries that cross district lines |

### Interpreting percentile rank

After the ensemble runs, each enacted metric is compared against the distribution:

```
percentile_rank = (count of ensemble plans with value ≤ enacted_value) / total_plans × 100
```

- **Percentile 5 or lower**: The enacted plan is among the 5% most extreme on this metric. Flag as outlier.
- **Percentile 95 or higher**: Same — extreme in the opposite direction.
- **Percentile 5–95**: Within the normal range of neutral plans.

**Example:** If the enacted House plan has `dem_seats = 85` and 8.4% of ensemble plans also have ≤ 85 Democratic seats, then `enacted_percentile = 8.4`. This means the enacted plan is less favorable to Democrats than 91.6% of neutral maps — a statistically notable result.

### Election data caveat

The ensemble uses **2020 Presidential election results** at the precinct level as its measure of partisan lean during simulation. This is because Presidential results are available at very fine geographic resolution. The boundary GeoJSON files use a **4-election blend** (§3.1). These will produce slightly different seat counts from the same boundary file — this is expected and is a known difference between the two data streams.

---

## 5. How Metrics Appear in Each App

### 5.1 fdex — District Explorer

**URL:** https://evolvedhow.github.io/fdex/

**Purpose:** Public-facing map for Georgia voters to explore their district, see who represents them, and understand demographic and partisan context.

**Data sources used:**
- Boundary GeoJSON files (all plans)
- Demographics JSON (ACS fields per district)
- County and places reference layers

**What's displayed:**

| Feature | Data source | Metric used |
|---|---|---|
| Choropleth map — Partisan Lean | `partisan` field in boundary GeoJSON | Partisan Lean Index (§3.1) |
| Choropleth map — Black VAP % | `pct_bvap_al × 100` | Black Voting Age Population |
| Choropleth map — Hispanic VAP % | `pct_hvp × 100` | Hispanic Voting Age Population |
| Choropleth map — Asian VAP % | `pct_avap_al × 100` | Asian Voting Age Population |
| District tooltip — population | `pop` field | 2020 Census total population |
| Legend color bands | Partisan color breaks at 40%, 45%, 50%, 55%, 60% | Partisan Safety Tiers (§3.19) |

**What's NOT in fdex:** No comparative analysis, no fairness metrics, no ensemble data. fdex is intentionally a simple explorer — metric complexity lives in map-compare and fdga-chain.

---

### 5.2 map-compare — Plan Comparison Tool

**URL:** https://evolvedhow.github.io/map-compare/

**Purpose:** Side-by-side comparison of any two redistricting plans. Primary tool for analysts and advocates.

**How data enters map-compare:**

The user selects two plans from a preset library (loaded from boundary GeoJSON files synced from FDP) OR uploads custom GeoJSON files. Optionally, a crosswalk CSV (precinct → district mapping with vote and demographic columns) can be uploaded to populate metrics from raw precinct data instead of from GeoJSON properties.

**When using GeoJSON properties directly:** `metricsFromGeoJsonProperties()` extracts the `partisan` field and converts it: `demVotes = partisan × 1000`, `repVotes = (1 − partisan) × 1000`. The actual vote counts are synthetic; ratios are preserved. This is the "View Mode" path.

**When using crosswalk CSV:** `spatialJoin()` places each precinct centroid into a district polygon, sums real vote counts, and computes real Dem fractions. This gives actual vote totals rather than synthetic ratios.

**Metrics shown in the Report tab:**

#### Population & Compactness section

| ScoreCard label | Formula / source | Units |
|---|---|---|
| Max Population Deviation | `max(|district_pop − ideal| / ideal × 100)` | % |
| Polsby-Popper (avg) | `mean(4π × Area / Perimeter²)` for all districts | 0–1 |
| Convex Hull Ratio (avg) | `mean(district_area / hull_area)` for all districts | 0–1 |
| County Splits | count of counties intersecting > 1 district | integer |

#### Representation & Demographics section

| ScoreCard label | Formula / source | Units |
|---|---|---|
| Majority-Minority Districts | count of districts where minority_vap / total_vap > 50% | integer |
| Black VAP Majority Districts | count of districts where black_vap / total_vap > 50% | integer |
| Safe Seat % (>7% margin) | `(Safe R + Lean R + Lean D + Safe D tiers) / n × 100` | % |
| Competitive Districts | count of districts where partisan_lean ∈ [46.5%, 53.5%] | integer |

#### VRA Threshold Analysis table

Rows showing Plan A count vs. Plan B count vs. delta (Δ) for:
- Competitive Districts (46.5%–53.5% Dem)
- Democratic Districts (≥50% Dem)
- Republican Districts (<50% Dem)
- BVAP Majority (≥50%), BVAP Influence (37%–50%)
- MVAP Majority/Influence (same thresholds)
- HVAP Majority/Influence
- AVAP Majority/Influence

#### Partisan Safety Tiers table

Six-tier breakdown (Safe R through Safe D) showing count per plan.

#### Partisan Fairness section

| ScoreCard label | Formula | Units |
|---|---|---|
| Dem Seats (lean > 50%) | count of districts where partisan_lean > 50% | integer |
| Efficiency Gap | `(wasted_dem − wasted_rep) / total_votes × 100` | % |
| Mean-Median Difference | `mean(dem_share) − median(dem_share) × 100` | % |
| Partisan Bias | `(seats_at_50% / n − 0.5) × 100` | percentage points |

#### Seats-Votes Responsiveness Curve

SVG chart plotting (Dem vote share %, Dem seat share %) for swings from −25% to +25%, at 0.5% intervals. The gray diagonal = proportionality (seats = votes). Dots show the current position of each plan.

#### Voter Disruption section (when two plans are loaded)

| Stat | Formula |
|---|---|
| People Displaced | `total_displaced_pop` |
| Min. Required | `sum of over-ideal pop in each Plan A district` |
| Excess Displacement | `total_displaced − min_required` |

#### District-Level Comparison table

Per-district rows showing Plan A vs. Plan B for: population, population deviation %, partisan lean, partisan flip label, Black VAP %, minority VAP %, Polsby-Popper. Color coding highlights VRA-relevant changes (amber = minority VAP shift > 5pp).

#### Changed Districts Spotlight

Districts where `|Δ partisan_lean| > 5pp` OR `|Δ minority_vap| > 5pp` are shown with a choropleth delta map (blue = Dem gain, red = R gain, gray = stable).

#### Redistricting History tab

Timeline of mid-decade redistricting waves sourced from `redistricting_waves.yml` (§2.6), with color-coded markers and legal context.

---

### 5.3 fdga-chain — Ensemble Analysis API

**URL:** https://evolvedhow.github.io/fdga-chain/  
**API base:** configured per deployment (local: `http://localhost:8001`)

**Purpose:** Provides the GerryChain ensemble analysis backend. The frontend fetches data from the API to display histograms, enacted-vs-ensemble comparisons, and the Princeton grade.

**Key API endpoints and what they return:**

#### `GET /api/states/{state}/{chamber}/ensemble/enacted`

Returns the enacted plan compared against the ensemble distribution. Example response structure:

```json
{
  "chamber": "house",
  "state": "GA",
  "ensemble_size": 10000,
  "comparison": {
    "dem_seats": {
      "enacted_value": 85,
      "ensemble_median": 87.0,
      "ensemble_p5": 83,
      "ensemble_p95": 91,
      "percentile_rank": 8.4,
      "is_outlier": true,
      "interpretation": "Democrats win 2.0 fewer seats than the median neutral map."
    },
    "competitive_districts": { ... },
    "efficiency_gap": { ... },
    "mean_median": { ... },
    ...
  },
  "princeton_benchmark": {
    "source": "Princeton Gerrymandering Project (1 million simulation)",
    "grade": "F",
    "grade_note": "Enacted plan falls outside Princeton A-grade benchmark range on all checked metrics.",
    "metrics_in_range": 0,
    "metrics_checked": 2,
    "detail": {
      "dem_seats": {
        "enacted_value": 85,
        "benchmark_min": 83,
        "benchmark_max": 86,
        "in_range": false
      },
      "competitive_districts": {
        "enacted_value": 3,
        "benchmark_min": 11,
        "benchmark_max": 20,
        "in_range": false
      }
    }
  }
}
```

The `percentile_rank` tells you: out of 10,000 neutral maps, what fraction had this metric at or below the enacted value. If `is_outlier = true`, the enacted plan is in the extreme 5% of the distribution.

#### `GET /api/states/{state}/{chamber}/ensemble/histogram`

Returns histogram data for one metric. Used to draw the distribution charts. The enacted value and its percentile are also returned for overlay.

#### `GET /api/states/{state}/{chamber}/metrics/{year}`

Returns precomputed metrics from `metrics.json` for a specific redistricting cycle. Includes efficiency gap, mean-median, seats/votes, contested/safe/competitive district counts, safe_pct, and wasted vote details.

#### `GET /api/states/{state}/{chamber}/proportionality`

Returns seat share vs. vote share across all redistricting cycles for a chamber. Used to plot proportionality over time. Each cycle entry includes `rep_proportionality_gap` (the seats-minus-votes gap, §3.17).

**What the frontend displays:**

| View | Data source | What user sees |
|---|---|---|
| Ensemble histograms | `/ensemble/histogram` | Bar chart of how often each metric value appeared across 10,000 plans; red line = enacted plan position |
| Enacted comparison | `/ensemble/enacted` | Table of enacted metrics vs. ensemble median/P5/P95; percentile rank; is_outlier flag |
| Princeton grade | `/ensemble/enacted` (princeton_benchmark field) | Letter grade (A–F) + per-metric pass/fail detail |
| Stability map | `/maps/{chamber}/stability` | Precinct-level heatmap: green = stable core, red = contested boundary |

---

### 5.4 lrdb — Local Redistricting Database

**URL:** https://evolvedhow.github.io/lrdb/

**Purpose:** Tracks the redistricting status of all local governments in Georgia — counties, cities, school boards. This app does not show partisan or fairness metrics. It is a research and advocacy database.

**Data source:** `lrdb_web_20260216.geojson` (§2.5)

**What's displayed:**

| Feature | Data field | Description |
|---|---|---|
| Jurisdiction map | GeoJSON geometry | Polygon outlines of each local jurisdiction |
| Status filter | `status` field | Filter by redistricting complete / in progress / not required |
| Required redistricting filter | `redistricted_w` | Whether jurisdiction was required to redistrict |
| Written requirements filter | `requirements_w` | Has documented redistricting rules |
| Written guidelines filter | `guidelines_w` | Has documented best practices |
| Local process filter | `lcro_w` | Process controlled locally (not state-imposed) |
| State override filter | `gga_adjust_w` | GA General Assembly overrode local decision |
| Public participation filter | `participation_w` | Community engagement documented |
| Controversy filter | `controvery_w` | Documented controversy in the process |
| At-large filter | `atlarge_w` | Jurisdiction uses at-large (no district) elections |

**Completeness Scorecard:** The app includes a gamification layer (`CompletenessScorecard.svelte`) that tracks data completeness — what percentage of jurisdictions have been fully researched across all fields. This is a data quality tool for researchers, not a redistricting metric.

---

## 6. How to Verify Results Manually

This section walks through a complete manual verification for the most important metrics, starting from the raw GeoJSON files.

### Verifying Partisan Lean for a Single District

1. Open `fdp/data/repos/main/boundaries/congress/congress_enacted_24_2024update.geojson` in any text editor or GeoJSON viewer.
2. Find the feature with `"district": 2`.
3. Read the four election fields: `g18_pct_dem`, `p20_pct_dem`, `r21_pct_dem`, `g22_pct_dem`.
4. Calculate: `(g18 + p20 + r21 + g22) / 4`
5. Compare to the `partisan` field. They should match within small rounding.

### Verifying Competitive District Count

1. Open the boundary GeoJSON for the plan.
2. For each feature, read the `partisan` field.
3. If `0.465 ≤ partisan ≤ 0.535`, mark as competitive.
4. Count the total number of competitive districts.
5. Compare to the "Competitive Districts" value shown in map-compare's report.

### Verifying Efficiency Gap from elections.json

1. Open `fdga-chain/data/states/GA/house/2021/elections.json`.
2. For each district in the `districts` array, find `dem_votes` and `rep_votes`.
3. For each district, calculate:
   - `total = dem_votes + rep_votes`
   - `threshold = floor(total / 2) + 1`
   - If `dem_votes > rep_votes`: `wasted_dem = dem_votes − threshold`, `wasted_rep = rep_votes`
   - If `rep_votes > dem_votes`: `wasted_rep = rep_votes − threshold`, `wasted_dem = dem_votes`
4. Sum all `wasted_dem` and all `wasted_rep` across all districts.
5. Sum all `total` across all districts.
6. Calculate: `efficiency_gap = (total_wasted_dem − total_wasted_rep) / total_votes`
7. Compare to the `efficiency_gap` field in `metrics.json` for the same cycle.

### Verifying Polsby-Popper (requires geometry calculation)

1. Use any GIS tool (QGIS, ArcGIS) to open the boundary GeoJSON.
2. For each district, calculate the area in km² and the perimeter in km.
3. Apply: `PP = (4 × 3.14159 × area_km2) / (perimeter_km²)`
4. Average all district PP values.
5. Compare to `polsby_popper_mean` in the ensemble metadata or map-compare report.

### Verifying Princeton Grade

1. Count Democratic seats in the enacted plan (districts where `partisan > 0.5`).
2. Count competitive districts (districts where `0.465 ≤ partisan ≤ 0.535`).
3. Compare to the A-grade ranges from §3.18.
4. If both values are within range → Grade A. If one is within range → Grade B. Etc.

### Checking Safe Seat Percentage

1. For each district, determine the partisan lean from the `partisan` GeoJSON field.
2. Classify: competitive if lean ∈ [0.465, 0.535]; safe otherwise.
3. Count safe districts. Divide by total districts. Multiply by 100.
4. Compare to the "Safe Seat %" ScoreCard value in map-compare.

---

## 7. Data File Locations

### CDM root

```
fdp/data/repos/main/
├── boundaries/
│   ├── congress/     ← 14-district congressional GeoJSON files
│   ├── house/        ← 180-district GA House GeoJSON files
│   ├── senate/       ← 56-district GA Senate GeoJSON files
│   └── reference/    ← county.geojson, places_2020data.geojson
├── demographics/
│   ├── congress.json ← ACS 2022 per-district, 14 districts
│   ├── house.json    ← ACS 2022 per-district, 180 districts
│   └── senate.json   ← ACS 2022 per-district, 56 districts
├── elections/
│   └── (parquet files for fdworkbench queries)
├── ensembles/
│   ├── house_ensemble.parquet    ← 10,000 rows × 8 columns
│   ├── house_meta.json           ← run metadata + enacted_metrics
│   ├── house_stability.json      ← precinct stability scores
│   ├── senate_ensemble.parquet
│   ├── senate_meta.json
│   ├── senate_stability.json
│   ├── congress_ensemble.parquet
│   ├── congress_meta.json
│   └── congress_stability.json
├── graphs/                       ← GerryChain adjacency graphs (binary)
├── history/
│   └── redistricting_waves.yml   ← Mid-decade redistricting history
├── lrdb/
│   ├── lrdb_web_20260216.geojson ← 441 local jurisdictions
│   └── cc_sb_districts15q_nod.geojson
└── precincts/                    ← Precinct-level shapefiles for ensemble building
```

### Election results (fdga-chain)

```
fdga-chain/data/states/GA/
├── house/
│   ├── 2001/elections.json, metrics.json
│   ├── 2005/elections.json, metrics.json
│   ├── 2011/elections.json, metrics.json
│   └── 2021/elections.json, metrics.json
├── senate/
│   └── (same structure)
└── congress/
    └── (same structure)
```

### Configuration files

```
fdp/config/
├── global.yml          ← Locked: state=GA, census_year=2020, data layout, quality checks
├── defaults.yml        ← Defaults for map, LLM, chain settings
└── apps/
    ├── fdex.yml        ← fdex plan catalog, overlays, reference layers
    ├── map_compare.yml ← map-compare plan catalog, LLM providers
    ├── fdga_chain.yml  ← GerryChain chain config, data paths, metrics list
    ├── lrdb.yml        ← LRDB data files, sidebar filter fields
    └── fdworkbench.yml ← Workbench data paths (elections parquet, ensembles, boundaries)
```

---

*Generated from source code and CDM data — 2026-05-26. For questions about methodology, contact Fair Districts Georgia at fairdistrictsga.org.*
