# FairDistricts GA — Technical Audit

**Prepared:** June 2026  
**Scope:** Full pipeline from raw Census/RDH data through ensemble generation, scoring, grading, and published results for Georgia congressional, state Senate, and state House redistricting.

---

## 1. Data Sources

### 1.1 Census and Demographic Sources

**2020 PL 94-171 VTD Shapefile (`ga_pl2020_vtd.zip`)**  
The primary geographic reference. Contains 2,698 VTDs (Voting Tabulation Districts) covering all 159 Georgia counties. EPSG:4269 (NAD83). Each VTD has an 11-character GEOID20 in the format `SS+CCC+VVVVVV` (e.g., `13001000002`). Provides population columns P0010001 (total population), P0040001 (total VAP), and P0050003 (group-quarters/correctional facility population). Total Georgia population: 10,711,908.

**2020 PL 94-171 Block-Level Data (`ga_pl2020_b.zip`)**  
Full block-level population file. 232,717 blocks, ~237 MB CSV. Used as a VAP weight source for disaggregation when needed. Block GEOIDs are 15 characters (`SS+CCC+TTTTTT+BBBB`).

**2024 ACS 5-Year CVAP Data (`ga_cvap_2024_2020_b_csv.zip`)**  
Citizen Voting-Age Population estimates disaggregated to 2020 Census blocks by the Redistricting Data Hub (RDH), sourced from the 2020–2024 ACS 5-year estimates. Retrieved February 17, 2026. Contains 33 CVAP columns including `CVAP_TOT24`, `CVAP_BLK24`, `CVAP_HSP24`, `CVAP_WHT24`, `CVAP_ASN24`. GEOIDs are 15-character block codes.

CVAP rather than raw VAP is used for minority representation analysis wherever possible. Under Section 2 of the Voting Rights Act, citizen population is the appropriate legal standard for majority-minority district analysis.

**VAP_MOD — Correctional Population Adjustment**

Throughout the pipeline, raw VAP is never used as a weighting denominator. Instead:

```
VAP_MOD = P0040001 - P0050003
```

This subtracts the institutionalized group-quarters population (primarily correctional facilities) from total voting-age population. Georgia has significant rural prison populations — Telfair, Stewart, and Wheeler counties in particular — which would artificially inflate the apparent voter-eligible population of otherwise low-population rural VTDs. Using VAP_MOD prevents prison gerrymandering effects from propagating through the weighting and scoring pipeline.

### 1.2 Election Data Sources

**ALARM Map Elections (2016–2020, VTD-level)**

The ALARM Project's `GA_cd_2020_map.rds` contains 12 elections already aggregated to the 2,698 VTD level. Used directly without additional processing:

| Columns | Election |
|---|---|
| `gov_18_rep_kem` / `gov_18_dem_abr` | 2018 Governor (Kemp/Abrams) |
| `pre_20_rep_tru` / `pre_20_dem_bid` | 2020 President (Trump/Biden) |
| `uss_20_rep_per` / `uss_20_dem_oss` | 2020 US Senate (Perdue/Ossoff) |
| `pre_16_rep_tru` / `pre_16_dem_cli` | 2016 President |
| `uss_16_rep_isa` / `uss_16_dem_bar` | 2016 US Senate |
| `atg_18_*`, `sos_18_*`, `sos_r18_*` | 2018 downballot + SOS runoff |

The 2018 Governor race is used directly from the ALARM map. The 2020 President result in the ALARM map is NOT used — it is re-sourced from the RDH block file to ensure VTD-level consistency with the 2021–2024 additions.

**RDH Block-Level Election Files**

Three block-level ZIP archives from the Redistricting Data Hub:

- `ga_2020gen_2021runoff_2020blocks_csv.zip` — Combined file containing the 2020 general election and January 5, 2021 Senate runoffs disaggregated to 232,717 2020-Census blocks. CSV format. Columns: `G20PREDBID`, `G20PRERTRU` (2020 President), `R21USSDOSS`, `R21USSRPER` (Ossoff/Perdue runoff), `R21USSDWAR`, `R21USSRLOE` (Warnock/Loeffler runoff).

- `Copy_of_ga_2022_gen_2020_blocks.zip` — 2022 general election disaggregated to 2020 blocks. Shapefile format. 232,717 rows, 414 columns. Retrieved May 27, 2026. Contains Governor (Abrams/Kemp/Hazel), US Senate November 8 (Warnock/Walker/Oliver), Attorney General, Secretary of State, Lt. Governor.

- `Copy_of_ga_2024_gen_2020_blocks.zip` — 2024 general election disaggregated to 2020 blocks. Shapefile format. 232,717 rows, 394 columns. Retrieved May 27, 2026. Contains President (Harris/Trump/Oliver/Stein).

**What Is NOT Included**

- **2022 December 6 Senate runoff** (Warnock/Walker head-to-head). The November 8 general data is present but includes Libertarian Chase Oliver (~2.1% statewide), which forced the runoff. A separate RDH file for the December 6 head-to-head race has not yet been acquired.
- **2021 PSC races** are present in the block file but are not included in the six-election composite (election scope rule: president, governor, US Senate only).
- **2016 elections** are excluded by design — too temporally distant from the 2023-enacted maps to be a reliable indicator of the current partisan environment.

### 1.3 Geographic Sources

**VTD Reference Polygons**

`ga_pl2020_vtd.zip` serves as both the demographic source and the spatial reference, used in three distinct roles: (1) building the GerryChain dual graph in `build_graph.py`, (2) building the block-to-VTD spatial lookup in `build_vtd_inputs.py`, and (3) providing VTD centroids for `vtd_composite.parquet`.

**Enacted District Shapefiles**

Three shapefiles representing Georgia's current (2023-enacted) redistricting maps:
- Congressional: `Congress-2023 shape.shp` — 14 districts
- State Senate: `Senate-2023 shape file.shp` — 56 districts
- State House: `House-2023 shape.shp` — 180 districts

District assignments are joined to VTDs using largest-overlap area intersection, which correctly handles cases where State House districts are smaller than individual VTDs.

**GerryChain Dual Graph**

`fdga-chain/data/graphs/ga_congress.json` — Prebuilt GerryChain JSON graph representing the adjacency structure of the 2,698 Georgia VTDs. Edges represent rook adjacency (shared edges only; corner touches do not count). Each node carries `GEOID20`, `TOTPOP`, `VAP_MOD`, `COUNTYFP20`, and the enacted district assignment column. Built from the VTD shapefile by `scripts/build_graph.py`.

---

## 2. Ensemble Generation

### 2.1 Algorithm: GerryChain ReCom

The primary ensemble uses **ReCom** (Region-Combining Markov Chain Monte Carlo), implemented in the GerryChain library developed by the MGGG Redistricting Lab at Tufts University.

**How ReCom works:** Starting from the enacted redistricting plan, the algorithm repeatedly proposes a new plan by:
1. Selecting two adjacent districts at random
2. Merging their VTDs into a single region
3. Building a random spanning tree of that merged region
4. Cutting one edge of the spanning tree to split the region into two new districts with approximately equal population

This produces a sequence of redistricting plans connected to the starting plan through local modifications. After many thousands of steps, the ensemble approximates the space of "neutral" redistricting plans — plans that no partisan actor designed.

**Statistical note:** The current GerryChain runs use standard ReCom rather than `reversible_recom`. Standard ReCom does not satisfy detailed balance and does not draw from a well-defined probability distribution. This is adequate for advocacy and education purposes and is the most common choice in practice. For published academic benchmarks or legal filings, `reversible_recom` is recommended. The configuration YAML documents this distinction explicitly and marks the algorithm choice as pending review.

**Comparison: ALARM uses Sequential Monte Carlo (SMC).** SMC generates independent samples rather than a correlated Markov chain, which is statistically superior for ensemble analysis. ReCom is faster and more scalable to large chambers (180 House districts). For congressional redistricting, both methods cover similar territory; differences in their outputs are diagnostic, not contradictory.

### 2.2 Constraints

**Population balance** is the only explicit constraint. The chain rejects any proposed split outside ±2% of the ideal district population (total population / number of districts). **Note:** ±1% is the standard for congressional benchmarks under Princeton/MGGG methodology. The ±2% tolerance is flagged in the configuration YAML as requiring review before any legal submission.

A technical initialization adjustment is made: the script computes the maximum VTD-level population deviation in the enacted plan and sets the validity-check epsilon to `max(0.02, max_enacted_dev × 1.05)`. This 5% slack ensures the chain can initialize from the enacted plan without immediately failing its own validity test.

**Contiguity** is implicit in ReCom's design — the algorithm only merges adjacent districts and only cuts spanning trees, so all proposed plans are topologically contiguous by construction.

**What is NOT constrained:**
- Compactness (no Polsby-Popper constraints)
- County preservation (no explicit county-splitting penalty)
- Minority district preservation (no VRA hinge constraints; ALARM's SMC ensemble did include BVAP hinge constraints)
- Incumbent protection

### 2.3 Chain Configuration

Current production configuration (`ga_congress_2026_v1.yml`):

| Parameter | Value | Notes |
|---|---|---|
| `n_steps` | 10,000 | Steps per chain |
| `burn_in` | 0 | No steps discarded; 500 is "reasonable" per MGGG guidance |
| `n_chains` | 1 | Single chain; 5 chains needed for Gelman-Rubin R-hat diagnostic |
| `algorithm` | `recom` | Marked TBD; `reversible_recom` recommended for legal use |
| `pop_epsilon` | 0.02 | ±2% population tolerance |
| `random_seed` | null | Different seed each run |

With these settings the congressional ensemble produces **10,001 rows**: 1 enacted plan (draw=1) prepended to 10,000 chain draws.

**Error handling:** A `_safe()` iterator wraps the chain. Individual "Could not find a possible cut" errors are silently skipped and the chain retries from the same state. After 5 consecutive failures the chain stops early. The final draw count may be slightly less than `n_steps`.

### 2.4 Output Format

Two files are written per run to `fdp/data/repos/main/ensemble/`:

**`{run_name}_plans.parquet`** — Long-format assignment table, ZSTD-compressed. Schema:

| Column | Type | Description |
|---|---|---|
| `plan_id` | TEXT | Run name string |
| `draw` | INT32 | 1-indexed; draw=1 is always the enacted plan |
| `geoid` | TEXT | 11-character VTD GEOID20 |
| `district` | INT32 | District assignment (1–14 for Congress) |
| `geo_level` | TEXT | Always "vtd" |
| `state` | TEXT | Always "GA" |
| `chamber` | TEXT | "congress", "senate", or "house" |

Total rows for congressional ensemble: ~10,001 draws × 2,698 VTDs = ~27 million rows.

**`{run_name}_meta.json`** — Resolved configuration plus runtime summary (timestamp, runtime in seconds, draw count, VTD count, output file path).

### 2.5 Modal Cloud Execution

For long runs, the ensemble is dispatched to Modal cloud infrastructure. The orchestrator runs on a 2-core / 4 GB container with a 24-hour timeout. Each chain runs on a separate 4-core / 8 GB container with a 4-hour timeout. All output lands in a Modal persistent volume (`fdga-chain-data`) under `/data/ensemble/` and must be downloaded to local storage before scoring.

### 2.6 ALARM Comparison Ensemble

The ALARM (Automated Redistricting with Legal Algorithmic Maps) dataset from Harvard Dataverse (doi:10.7910/DVN/SLCD3E) provides an independent benchmark for Georgia congressional redistricting.

**What ALARM provides:**
- 5,001 plans (1 enacted + 5,000 SMC samples) for Georgia congressional districts
- Pre-computed statistics: Polsby-Popper compactness, county splits, municipal splits, demographic VAP counts, and election results (2016–2020 vintage)
- Generated in 2021 using SMC with BVAP hinge constraints ensuring VRA-compliant majority-Black districts

**How ALARM is used in this project:**  
`build_alarm_scorecard.py` re-scores the ALARM ensemble's plan assignments against the project's 2018–2024 composite electoral baseline (replacing the original 2016–2020 composite). This ensures both benchmarks are evaluated against identical electoral data, making their partisan metric results directly comparable. Only the non-partisan metrics (Polsby-Popper, county splits, municipal splits) and raw demographic VAP counts are taken unchanged from the ALARM stats CSV.

**Key differences from GerryChain:**

| Dimension | ALARM | GerryChain |
|---|---|---|
| Algorithm | SMC (independent samples) | ReCom (correlated Markov chain) |
| Sample size | 5,000 plans | 9,501–24,003 draws |
| VRA constraints | BVAP hinge constraints during sampling | None |
| Demographic data | 2020 Census VAP | 2024 ACS CVAP |
| Geographic metrics | Natively in stats CSV | Computed at score time |
| Chambers | Congress only | Congress, Senate, House |
| Electoral baseline | Re-scored with 2018–2024 composite | Native 2018–2024 composite |

---

## 3. Electoral Baseline

### 3.1 The Six Elections

The partisan scoring baseline is a composite of six elections spanning 2018–2024, each weighted equally (1/6):

| # | Year | Race | Candidates | Source |
|---|---|---|---|---|
| 1 | 2018 | Governor | Kemp (R) / Abrams (D) | ALARM map (VTD-level) |
| 2 | 2020 | President | Trump (R) / Biden (D) | RDH block file |
| 3 | 2021 | US Senate Runoff | Loeffler (R) / Warnock (D) | RDH block file |
| 4 | 2022 | Governor | Kemp (R) / Abrams (D) | RDH block file |
| 5 | 2022 | US Senate (Nov 8) | Walker (R) / Warnock (D) | RDH block file |
| 6 | 2024 | President | Trump (R) / Harris (D) | RDH block file |

**Rationale:**
- Six elections across four cycles (2018, 2020, 2021, 2022, 2024) captures both presidential and midterm partisan environments
- The 2021 Warnock/Loeffler runoff is included because Georgia's special runoffs have distinct mobilization dynamics — high Black voter turnout relative to normal midterm patterns
- The 2022 races each contribute 1/6 weight individually, meaning 2022 collectively contributes 2/6 (one-third). This is a deliberate design choice reflecting the recency and availability of 2022 data. See WORKAROUNDS.md §3.4.
- Third-party candidates are excluded from all two-party vote share calculations

**What is NOT included:** The 2021 Ossoff/Perdue runoff (high correlation with Warnock race; excluded to avoid double-weighting January 2021 environment), the 2022 December 6 Warnock/Walker runoff (data not yet acquired from RDH), and all downballot offices (AG, SoS, LtGov, PSC) per the election scope rule.

### 3.2 Block-to-VTD Aggregation

2020 Census blocks nest perfectly within 2020 VTDs by design. The aggregation method:

1. **Build lookup table** (once, cached as `block_vtd_lookup.parquet`): Load the 2022 block shapefile geometry, replace each block polygon with its centroid, spatial-join (`predicate="within"`) to VTD polygons. Maps each 15-character block GEOID20 to its parent VTD's 11-character GEOID20.

2. **For each election dataset:** Read only required vote columns (no geometry re-read for 2022/2024 using `ignore_geometry=True`), merge on block GEOID20, then `groupby("vtd_GEOID20").sum()` across all vote columns.

3. **Data quality fix:** GEOID20 values in CSV-format files can lose leading zeros. All GEOIDs are zero-padded to 15 characters with `.str.zfill(15)` before joining.

4. **Unmatched blocks** (blocks whose centroid falls outside all VTD polygons — typically water features or boundary slivers) are dropped with a warning. These consistently have VAP_MOD=0.

**Data quality verification:** After each aggregation, statewide vote totals are compared against Georgia Secretary of State certified results. A warning is raised if any race differs by more than 0.5%. All six elections validate within 0.04% of certified results.

### 3.3 Composite Score Calculation

Computed in two stages by `build_composite_score.py`.

**Stage 1 — Per-block composite (equal-weight average across 6 elections)**

For each of the 232,717 Census blocks, the 6 Democratic two-party vote shares are assembled into a matrix. The 2018 Governor result (VTD-level only) is broadcast to all blocks within that VTD. `np.nanmean` across the 6 elections produces a per-block average Democratic share. NaN values (zero-turnout blocks) are excluded from the mean.

**Stage 2 — Weighted aggregation of blocks to VTDs**

Blocks are aggregated to VTDs using a turnout-weighted average. The weight for each block is:

```
weight = (total_votes_2020 + total_votes_2021 + total_votes_gov22 +
          total_votes_uss22 + total_votes_2024) / 5.0
```

The 2018 Governor is excluded from this weight because it has no block-level vote count. VTD composite:

```
composite_dem_pct = Σ(avg_dem_pct × weight) / Σ(weight)
composite_dem_2pv = composite_dem_pct / (composite_dem_pct + composite_rep_pct)
```

Zero-VAP VTDs (military bases, water bodies) receive a neutral value of 0.5. VTDs with no block coverage are filled with the turnout-weighted county average.

**Output:** `fdp/data/repos/main/vtd/vtd_composite.parquet` — 2,698 rows with `composite_dem_2pv`, per-election transparency columns (`dem_pct_2018_gov`, `dem_pct_2020_pres`, `dem_pct_2021_war_runoff`, `dem_pct_2022_gov`, `dem_pct_2022_uss`, `dem_pct_2024_pres`), `VAP_MOD`, and VTD centroid coordinates.

**Statewide composite (VAP-weighted):** `_get_statewide_dem_2pv()` computes `Σ(composite_dem_pct × VAP_MOD) / Σ((composite_dem_pct + composite_rep_pct) × VAP_MOD)` ≈ **51.49%** Democratic two-party share.

---

## 4. Plan Scoring

### 4.1 Scoring Pipeline Overview

```
Stage 0: build_composite_score.py   → vtd_composite.parquet
Stage 1: score_ensemble_plans.py    → {run}_scores.parquet
Stage 2: build_draw_stats.py        → {run}_draw_stats.parquet
                                    → {run}_competitive_counts.parquet
Stage 3: build_scorecard.py         → {run}_scorecard.json  (GerryChain)
Stage 4: build_alarm_scorecard.py   → fdga_2026_benchmark_congress_alarm_scorecard.json
```

### 4.2 Stage 1 — Score Each Plan

`score_ensemble_plans.py` scores all plans in a single vectorized operation.

1. Load plan assignments via DuckDB. Build an (n_VTDs × n_draws) integer matrix.
2. Load election results from `election_results_vtd.parquet`, filtered to priority offices.
3. For each of the N districts: use a boolean mask and matrix-multiply against election matrix. Produces (n_draws × 2·N_races) district vote totals for all draws simultaneously.
4. Compute `dem_2pv = dem_votes / (dem_votes + rep_votes)` and winner for each (draw, district, election) triple.

Output: `{run_name}_scores.parquet` — long format, one row per (plan_id, draw, district, year, election_type, office).

### 4.3 Stage 2 — Draw-Level Statistics

`build_draw_stats.py` runs entirely in DuckDB. For each draw, computes:
- `dem_seats`, `rep_seats`, `tied_seats`
- `avg_dem_2pv` — mean Democratic two-party vote share across all districts
- `efficiency_gap`
- `mean_median`
- `n_competitive` at each configured threshold

### 4.4 Identifying the Enacted Plan

The enacted plan is always draw=1. For GerryChain runs, it is prepended before chain output begins. For ALARM, it is the `cd_2020` column of the plans matrix. All ensemble statistics (histograms, percentile ranks, p5/p50/p95) are computed over draws 2 through N. The enacted plan's metric value is then ranked against this distribution to produce the percentile rank.

---

## 5. Metrics Definitions

### 5.1 dem_seats — Seat-Vote Proportionality

**Formula:** Count of districts where Democratic two-party vote share ≥ 50%.

**Interpretation:** The number of districts the Democratic party "wins" under the composite baseline. The most direct measure of partisan outcome.

**Grading (directional, lower is worse for Democrats):**
- A: pct_rank ≥ 50 (at or above the neutral ensemble median)
- B: ≥ 20
- C: ≥ 5
- F: below the 5th percentile (statistical outlier unfavorable to Democrats)

### 5.2 efficiency_gap — Wasted Votes Balance

**Formula:**

```
wasted_dem_d = dem_votes_d               if Republicans win district d
             = dem_votes_d − total_d/2   if Democrats win district d

efficiency_gap = (Σ wasted_dem_d − Σ wasted_rep_d) / Σ total_votes_d
```

Positive = Republican structural advantage (Democratic votes wasted at higher rate).

**Limitations:** The efficiency gap conflates geographic self-sorting with deliberate manipulation. The ensemble comparison is essential — what matters is not the raw value but whether the enacted map is an outlier relative to neutral alternatives.

**Grading (symmetric, center is best):**
- A: |pct_rank − 50| ≤ 10
- B: ≤ 30
- C: ≤ 45
- F: outside the 5th–95th percentile band

### 5.3 mean_median — Vote Distribution Symmetry

**Formula:** `mean(dem_2pv_d) − median(dem_2pv_d)` across all districts.

**Interpretation:** If Democratic votes are heavily concentrated in landslide districts (cracking and packing), the median district's Democratic share will be lower than the mean — producing a positive mean-median difference indicating Republican structural advantage. Particularly sensitive to cracking.

**Grading:** Same symmetric thresholds as efficiency_gap.

### 5.4 comp_seats — Electoral Competitiveness

**Formula:** Count of districts where `|dem_2pv_d − 0.50| ≤ COMPETITIVE_MARGIN/2`.

With `COMPETITIVE_MARGIN = 0.07` (7%), this counts districts where Democratic share falls between 46.5% and 53.5%.

**Known inconsistency:** The scoring pipeline uses ±3.5pp. The `_score_geojson` function (for uploaded plans in the Compare tab) hardcodes ±5pp. These two code paths produce different `comp_seats` counts for any uploaded plan. See WORKAROUNDS.md §5.2.

**Grading (directional, higher is better):**
- A: pct_rank ≥ 95
- B: ≥ 64
- C: ≥ 5
- F: < 5

### 5.5 muni_splits — Split Cities and Municipalities

**Formula:** Count of municipalities where VTDs are assigned to more than one district.

**Data source:** `vtd_muni.parquet` — mapping from VTD GEOID to municipality identifier.

**Critical discrepancy:** GerryChain and ALARM scorecards use different municipality sets, producing incomparable baselines. GerryChain scores the enacted congressional map at 12 splits (Grade A — 0.1st percentile). ALARM scores it at 16 splits (Grade F — above the neutral range of ~3–11). These scores cannot be directly compared. See WORKAROUNDS.md §5.7.

**Grading (inverted ranking, lower is better):**
- A: inverted rank ≥ 95
- B: ≥ 64
- C: ≥ 5
- F: < 5

### 5.6 polsby_popper — Shape Compactness

**Formula:** `(4π × area_d) / perimeter_d²` per district, averaged across all districts.

Range [0, 1]. A value of 1 indicates a perfect circle.

**Availability:** Only from ALARM stats CSV. Not computed for GerryChain runs (null in all three GerryChain scorecards).

**Grading (higher is better):** A: pct_rank ≥ 95. B: ≥ 64. C: ≥ 5. F: < 5.

### 5.7 Minority Representation Metrics

- **`maj_black`** — Districts where Black (or African American) CVAP/VAP ≥ 50%
- **`min_coal`** — Districts where total minority (non-white) CVAP/VAP ≥ 50%
- **`maj_white`** — Districts where white CVAP/VAP ≥ 50%
- **`min_influence`** — Districts where minority CVAP/VAP is between 37% and 50%

**Important discrepancy:** `maj_black` is graded symmetrically in the main scorecard pipeline but directionally (higher is better) in the `_score_geojson` interactive scorer. See WORKAROUNDS.md §5.3.

**CVAP vs. VAP discrepancy between benchmarks:** GerryChain uses 2024 ACS CVAP; ALARM uses 2020 Census VAP. This drives a significant `maj_black` grade discrepancy for the congressional enacted map (GerryChain: F at 100th percentile; ALARM: B at ~60th percentile). The difference is entirely attributable to data vintage and measurement choice, not a factual disagreement about the map. See WORKAROUNDS.md §6.5.

### 5.8 Proportionality Gap

Decomposes the total gap between proportional representation and the enacted outcome:

```
proportional_target = statewide_dem_2pv × N_districts
structural_gap      = ensemble_median_dem_seats − proportional_target
manipulation_gap    = enacted_dem_seats − ensemble_median_dem_seats
total_gap           = enacted_dem_seats − proportional_target
```

**Structural gap:** How far below proportionality the neutral ensemble median falls, primarily from geographic self-sorting. This would exist regardless of who drew the map.

**Manipulation gap:** How far the enacted map falls below the neutral median. Attributable to deliberate redistricting choices. This is what the Princeton ensemble test actually grades.

**Implementation:** Computed at serve time in `fdensemble/main.py` → `_get_statewide_dem_2pv()` + `_build_proportionality_gap()`. Reads `vtd_composite.parquet` once and caches the result.

---

## 6. Grading Methodology

### 6.1 Percentile Rank Computation

Each metric's distribution is stored as a histogram (bin edges and counts) in the scorecard JSON. Percentile rank computation:

1. Expand histogram to approximate point distribution: `np.repeat(bin_centers, bin_counts)`
2. Compute: `pct_rank = (dist_approx ≤ enacted_value).mean() × 100`

If the enacted value falls outside the ensemble range, the histogram range is extended to include it so the marker renders correctly on the river chart.

### 6.2 Individual Metric Grading Functions

| Function | Used for | A threshold | B threshold | F threshold |
|---|---|---|---|---|
| `_seats_grade` | `dem_seats` | pct_rank ≥ 50 | ≥ 20 | < 5 |
| `_comp_grade` | `comp_seats` | pct_rank ≥ 95 | ≥ 64 | < 5 |
| `_directional_grade` | `polsby_popper`, splits, `min_influence` | eff_rank ≥ 95 | ≥ 64 | < 5 |
| `_simple_grade` | `efficiency_gap`, `mean_median`, `maj_black` | \|pct−50\| ≤ 10 | ≤ 30 | > 45 |

### 6.3 Composite Grade: Partisan Fairness

1. **Ensemble test (e_pass):** All three of `dem_seats`, `efficiency_gap`, and `mean_median` must individually pass (within the 5th–95th percentile band). If any one fails, e_pass = False.
2. **Normative test (n_pass):** Partisan bias must satisfy `|partisan_bias| ≤ max(1, 0.07 × N_districts) / N_districts`. Defaults to passing if partisan bias is unavailable (GerryChain runs).
3. **Base grade from 2×2 table:** e_pass + n_pass = A; e_pass only = B; n_pass only = C; neither = F.
4. **Severity downgrade:** If `efficiency_gap` or `mean_median` falls in the extreme tail (pct_rank > 97 or < 3), the grade worsens by one step.
5. **Competitiveness adjustment:** `comp_seats` grade A improves one step; grade F worsens one step.

### 6.4 Composite Grade: Overall

Starts from `_partisan_fairness` grade, then:
- Geographic grade F → worsen one step
- `comp_seats` A → improve one step
- `comp_seats` F → worsen one step

### 6.5 Design: Composite Grades Recomputed at Serve Time

Scorecard JSON files store only per-metric raw data. Any pre-computed composite grade keys are stripped when loading a scorecard. Composite grades are always recomputed by `_compute_composite_grades()` at serve time. This ensures exactly one implementation of grading logic propagates immediately to all four benchmarks without scorecard regeneration.

### 6.6 The "GIGO" Problem

The ensemble grade answers: **"Is this map an outlier relative to neutral redistricting?"** It does not answer: "Is this map proportional?" or "Is this map fair to all voters?"

A map can receive an A grade on `dem_seats` while still under-delivering Democratic representation relative to statewide vote share — if geographic sorting makes proportionality structurally difficult. Conversely, a map can receive an F grade while still producing more seats than strict proportionality implies.

The proportionality gap decomposition (Section 5.8) addresses this by separating structural geography from deliberate manipulation.

---

## 7. Results Summary

### 7.1 Congressional Districts (14 seats)

**Two independent ensembles confirm the same pattern:**

| Metric | Enacted | Ensemble p5/p50/p95 | Grade (GC / ALARM) |
|---|---|---|---|
| dem_seats | 5 | 5 / 6 / 8 | B / B |
| efficiency_gap | 0.171 | −0.04 / 0.10 / 0.17 | **F / F** |
| mean_median | 0.080 | 0.00 / 0.03 / 0.06 | **F / F** |
| comp_seats | 0 (GC) / 2 (ALARM) | 0 / 2 / 4 | C / C |
| muni_splits | 12 | 21 / 27 / 33 | **A** (GC) |
| county_splits | 15 | 7 / 10 / 12 | **F** (ALARM only) |

**Key findings:**

1. **Mean-median at the 100th percentile in both benchmarks.** The enacted map's vote distribution asymmetry exceeds every single plan in both ensembles.
2. **Efficiency gap at the 96th percentile** in both benchmarks. The enacted map wastes Democratic votes at an extreme rate.
3. **Zero competitive seats** under GerryChain baseline. Every district is predetermined.
4. **Municipal splits paradox:** Enacted map splits 12 municipalities — cleaner than 99.9% of neutral maps. Yet `muni_splits ↔ dem_seats` correlation across the ensemble is near zero (r = 0.026). Manipulation occurs sub-municipally, below the resolution of city-level metrics.
5. **Minority discrepancy:** GerryChain (2024 CVAP) finds 4 majority-Black districts (F). ALARM (2020 VAP) finds 2 (B). Entirely attributable to measurement methodology, not map design.

### 7.2 State Senate (56 seats)

| Metric | Enacted | Ensemble p5/p50/p95 | Grade |
|---|---|---|---|
| dem_seats | 23 | 24 / 26 / 28 | **F** |
| efficiency_gap | 0.114 | 0.03 / 0.06 / 0.10 | **F** |
| mean_median | 0.076 | 0.01 / 0.04 / 0.06 | **F** |
| comp_seats | 0 | 1 / 4 / 6 | **F** |
| rep_safe_seats | 29 | 23 / 25 / 27 | **F** |

**Most severely gerrymandered chamber.** Five of six partisan and competitive metrics are Grade F. `dem_seats` at the 3.3rd percentile (only 3.3% of neutral maps produce as few as 23 Democratic seats). Zero competitive seats in a 56-district chamber is the 0.1st percentile. `mean_median` at the 100th percentile. Overall grade: **F**.

### 7.3 State House (180 seats)

| Metric | Enacted | Ensemble p5/p50/p95 | Grade |
|---|---|---|---|
| dem_seats | 84 | 82 / 85 / 88 | B |
| efficiency_gap | 0.059 | 0.04 / 0.05 / 0.07 | B |
| mean_median | 0.057 | 0.02 / 0.04 / 0.05 | **F** |
| comp_seats | 6 | 6 / 10 / 13 | C |
| rep_safe_seats | 89 | 79 / 82 / 85 | **F** |
| maj_black | 50 | 35 / 37 / 40 | **F** |

**Split signal:** Efficiency gap receives B; mean-median is at the 100th percentile. The House map maintains a near-normal aggregate wasted-vote ratio through a specific mechanism: Democratic landslides substituted for competitive districts. Black voters are concentrated into 50 majority-Black districts (F grade, 100th percentile) — consistent with racial packing. Overall grade: **C**.

---

## Appendix: Known Issues and Outstanding Items

| Issue | Severity | Location |
|---|---|---|
| `comp_seats` margin inconsistency: scoring pipeline uses ±3.5pp, `_score_geojson` hardcodes ±5pp | Medium | `fdensemble/main.py` |
| `maj_black` grading inconsistency: symmetric in scorecard pipeline, directional in `_score_geojson` | Medium | `fdensemble/main.py` |
| `muni_splits` incompatible municipality sets between GerryChain and ALARM scorecards | High | Different `vtd_muni.parquet` files |
| `pop_epsilon = 0.02` too loose for legal use (±1% is Princeton/MGGG standard) | High | `ga_congress_2026_v1.yml` |
| `burn_in = 0` (500 recommended by MGGG) | Medium | `ga_congress_2026_v1.yml` |
| `n_chains = 1` (5 needed for Gelman-Rubin R-hat) | Medium | `ga_congress_2026_v1.yml` |
| `algorithm = recom` instead of `reversible_recom` | High (for legal/published use) | `ga_congress_2026_v1.yml` |
| 2022 December 6 runoff (Warnock/Walker head-to-head) absent from composite | Medium | Pipeline gap |
| `partisan_bias` null for GerryChain runs (normative test defaults to pass) | Low | `build_scorecard.py` |
| `polsby_popper` and `county_splits` null for all GerryChain runs | Medium | `build_scorecard.py` |
| `maj_black` CVAP vs. VAP discrepancy between GerryChain (F) and ALARM (B) needs disclosure in public-facing materials | Medium | Communication |
