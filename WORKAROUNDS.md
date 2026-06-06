# WORKAROUNDS.md

**Internal Technical Reference — FairDistricts GA Redistricting Ensemble Pipeline**

This document catalogs every known data anomaly, approximation, limitation, and workaround applied
in the ensemble benchmark pipeline. Entries are organized by pipeline stage. For each item: the
issue, the workaround applied, and the impact on downstream interpretation.

Last updated: 2026-06-07

---

## Architecture Note (2026-06-07)
Supabase has been ELIMINATED. The pipeline is now fully Parquet + DuckDB in-process. Historical Supabase references in this file are archive-only.

## Dead Code Removed (2026-06-07)
- EvaluateTab.svelte: orphaned component (zero imports in App.svelte or any other component). Deleted.
- PlanUploader.svelte: only used by the now-deleted EvaluateTab. Deleted.

---

## 1. Data Source Workarounds

### 1.1 ALARM RDS files not natively readable in Python

**Issue:** The ALARM Project distributes GA_cd_2020_plans.rds and GA_cd_2020_map.rds as R S3
objects (redist_plans / redist_map). Python has no native reader for these formats.

**Workaround:**
- R export scripts (`fdensemble/scripts/export_ensemble_plans.R`, `export_2018_governor.R`) were
  written to read both RDS files and export to CSV/Parquet:
  - Plans matrix: `GA_cd_2020_plans_matrix.csv` (2,698 VTDs × 5,001 plans, ~500 MB on disk)
  - 2018 election data: `vtd_elections_2018_governor.parquet`
  - Stats: `GA_cd_2020_stats.csv`
- `build_alarm_scorecard.py` calls `Rscript` inline via subprocess to extract just the GEOID column
  order from the RDS when needed.

**Impact:** The plans_matrix.csv is a large intermediate artifact that must remain in sync with the
original RDS. If the RDS is ever updated or re-exported, the CSV must be regenerated. Any mismatch
in row order between the CSV and `vtd_composite.parquet` would silently corrupt all ALARM partisan
scores.

---

### 1.2 VTD shapefile sourced from 2022 block file, not the canonical VTD zip

**Issue:** Building the block-to-VTD spatial lookup requires VTD polygon geometry. Two sources are
available: `ga_pl2020_vtd.zip` (the canonical VTD shapefile) and the 2022 block shapefile which
also carries VTD geometry.

**Workaround:** `build_vtd_inputs.py` uses the 2022 block file's geometry for the lookup build
(centroid-in-polygon join), not the VTD shapefile directly. This is because the 2022 block
shapefile was already being loaded for election data and avoids an extra large file read.

**Impact:** None in practice — both sources use identical 2020 Census VTD boundaries. This is a
performance convenience, not a correctness tradeoff.

---

### 1.3 2022 December Senate runoff data absent

**Issue:** The November 8, 2022 general Senate election (Warnock/Walker/Oliver) was a three-way
race. Libertarian Oliver (~2.1% statewide) forced a December 6 runoff. The project has block-level
data for the November general only; the December head-to-head runoff is not available.

**Workaround:** The November general is used for `uss_22` columns. The Libertarian vote is tracked
as a separate column (`G22USSLOLI`) and excluded from all two-party vote share calculations
(`dem_2pv_uss22 = Warnock / (Warnock + Walker)`). The runoff itself is logged as "still
outstanding" in CLAUDE.md.

**Impact:** The partisan score for the 2022 US Senate race reflects a three-candidate primary
context rather than the definitive two-candidate runoff. Warnock's two-party margin in the November
general (~50.5%) differs from his runoff result (~50.8%). The difference is small but could
matter for close competitive-seat threshold calls. No correction is applied.

---

### 1.4 2020 President and 2021 runoff elections from same ZIP file

**Issue:** The 2021 January 5 runoff data (Warnock/Loeffler, Ossoff/Perdue) was distributed by
RDH bundled with 2020 general election data in a single ZIP:
`ga_2020gen_2021runoff_2020blocks_csv.zip`. The inner CSV is named `ga_2020_gen_2020_blocks.csv`.

**Workaround:** `build_vtd_inputs.py` explicitly skips `G20*` and `S20*` columns from this file
(since 2020 elections are already in the ALARM map at VTD level) and reads only `R21*` columns for
the January 2021 runoffs. The 2020 President result is also re-aggregated from this same file for
completeness.

**Impact:** The 2020 President result is available from two sources (ALARM map VTD columns and the
RDH block file). The pipeline uses the RDH block file version, which should match the ALARM map
but has been independently aggregated. Any small discrepancies between the two would not affect
scoring because only the RDH block-aggregated version enters the composite.

---

### 1.5 Block file geometry loaded twice to avoid 2.6 GB simultaneous RAM load

**Issue:** The 2022 and 2024 block shapefiles are approximately 2.6 GB unzipped each (232,717
blocks with full geometry). Loading geometry and attribute columns together would require holding
the full file in RAM.

**Workaround:** The 2022 block file is loaded in two separate passes:
1. Geometry-only pass: loads polygon geometry, computes centroids, builds the block-to-VTD spatial
   lookup, saves to `block_vtd_lookup.parquet`, then discards the GeoDataFrame.
2. Attribute-only pass: reloads with `ignore_geometry=True` to read only election columns.

The `--skip-lookup` flag allows reusing the cached lookup on subsequent runs.

**Impact:** Correctness is preserved. Runtime on the first run is longer due to two file reads, but
peak RAM is approximately halved. Researchers re-running only specific elections can use
`--skip-lookup` to skip the expensive geometry pass.

---

### 1.6 Input files read from Google Drive mount

**Issue:** Large input files (block shapefiles, CVAP CSVs, VTD zip) are stored on Google Drive
rather than checked into the repository.

**Workaround:** `build_vtd_inputs.py` defaults input search to
`/mnt/g/My Drive/$FDGA/$fgdp/input_datasets/` with an `--input-dir` override flag. The
`build_graph.py` script searches four candidate paths in order for the VTD shapefile.

**Impact:** Pipeline requires the Google Drive mount to be active. Running in CI or on a remote
server without the mount requires manually passing `--input-dir` pointing to a local copy. No
automatic fallback or download mechanism exists.

---

### 1.7 GeoJSON graph built from VTD shapefile only (5 columns retained)

**Issue:** GerryChain requires a dual graph JSON built from a specific geometry source. Node
attributes must include `TOTPOP` and a district assignment column.

**Workaround:** `build_graph.py` loads the full VTD shapefile then immediately drops all columns
except `GEOID20`, `COUNTYFP20`, `TOTPOP`, `VAP_MOD`, and `geometry` before building the graph.
Election and demographic attributes are NOT embedded in the graph — they are joined at scoring
time from separate parquet files.

**Impact:** The graph file at `fdga-chain/data/graphs/ga_congress.json` is compact and portable.
However, it means any run that requires election-based constraints (e.g., majority-minority
enforcement) must join those attributes after the fact — they are not available inside the MCMC
proposal step itself.

---

## 2. Aggregation Approximations

### 2.1 Centroid-in-polygon spatial join for block-to-VTD assignment

**Issue:** 2020 Census blocks are geometrically nested within 2020 VTDs by design, but confirming
this via polygon containment is computationally expensive and occasionally fails on boundary blocks
whose polygons straddle VTD lines due to floating-point edge effects.

**Workaround:** Each block polygon is replaced with its centroid, and the centroid is spatially
joined to VTD polygons using `predicate="within"`. This leverages the fact that a block centroid
will always fall inside exactly one VTD if blocks are properly nested.

**Impact:** Water features, boundary slivers, and a small number of blocks with zero population
whose centroids happen to fall outside any VTD polygon will be unmatched. These are dropped with
a warning. In practice VAP_MOD for these blocks is zero, so their vote contribution is zero, and
dropping them introduces no error in aggregated vote totals.

---

### 2.2 VAP_MOD weighting for composite vote injection (not for raw vote aggregation)

**Issue:** Raw VAP overcounts prison-facility populations in rural Georgia counties (Telfair,
Stewart, Wheeler, and others). Neutral redistricting metrics computed using raw VAP would
artificially inflate the apparent electoral weight of these counties.

**Workaround:** `VAP_MOD = P0040001 - P0050003` (total VAP minus correctional facility population,
clipped to 0) is computed for every VTD in `build_graph.py` and carried through all pipeline
stages. In the composite score pipeline, synthetic vote counts injected into
`election_results_vtd.parquet` are computed as `composite_dem_pct * VAP_MOD` (and similarly for
rep), not `* raw_VAP`.

**Impact:** Partisan scores for districts containing large prison facilities are materially lower
than they would be with raw VAP. This is the correct behavior under the "prison gerrymandering"
doctrine: incarcerated persons are counted at the facility location by the Census but cannot vote,
so their census-count population should not drive redistricting weights. Using raw VAP would make
these VTDs appear more electorally significant than they are.

**Note:** VAP_MOD is NOT used as a disaggregation weight in `build_vtd_inputs.py` (which does
direct additive block summation of actual vote counts, not disaggregation). It is used as the
weighting denominator in the composite score injection and in the statewide dem_2pv computation.

---

### 2.3 2022 block shapefile geometry used as the canonical block universe for all years

**Issue:** The block-to-VTD lookup must be built once and reused for 2020, 2021, 2022, 2024 block
files and the CVAP CSV. Ideally the lookup would be built from the authoritative 2020 Census VTD
shapefile directly.

**Workaround:** The lookup is built from the 2022 block shapefile geometry (centroid-in-polygon
into VTD polygons). The same lookup is then applied to all other block-level files (2020/2021 CSV,
2024 block shapefile, CVAP CSV). This is valid because all four files use identical 2020 Census
block geography.

**Impact:** None — all block files are keyed to GEOID20 (15-char 2020 block codes) and the VTD
shapefile uses the same 2020 vintage. There is no geographic mismatch risk.

---

### 2.4 GEOID20 zero-padding for CSV-format files

**Issue:** CSV export tools sometimes drop leading zeros from FIPS codes. Georgia block GEOID20s
are 15-character strings (e.g., `130019501001000`); if leading zeros are stripped during export,
`13001` becomes `1300` for some FIPS codes (though Georgia state FIPS is `13`, not starting with 0,
this affects county and block segment codes).

**Workaround:** `build_vtd_inputs.py` applies `.str.zfill(15)` to GEOID20 columns in all CSV-
format source files (2021 runoff, CVAP) at load time. Shapefile-based files (2022 and 2024 block
shapefiles) retain correct zero-padding natively.

**Impact:** Without this fix, blocks in counties with leading-zero county FIPS (counties 001-099)
would fail to join, producing silent undercounts in those counties. The fix has no correctness
cost.

---

### 2.5 Two-party vote share excludes all third-party candidates

**Issue:** Several elections in the composite have significant third-party vote shares that affect
the interpretation of "competitive":
- 2022 USS: Libertarian Chase Oliver ~2.1% (forced the December runoff)
- 2022 Governor: Libertarian Shane Hazel ~1%
- 2024 President: Libertarian Chase Oliver, Green Jill Stein, independents Cruz/West (combined ~1-2%)

**Workaround:** All two-party vote share (2pv) calculations use only D + R as the denominator:
`dem_2pv = D / (D + R)`. Third-party raw vote columns are retained in output parquets for
transparency but are excluded from all competitive and partisan metrics calculations.

**Impact:** 2pv values are inflated slightly relative to raw share for elections with significant
third-party presence. In the 2022 USS race, Walker's 2pv is slightly higher than his raw vote
percentage. The competitive threshold (|2pv - 0.5| <= 0.035) therefore applies to a rescaled metric.
For the purpose of ensemble comparison, this is consistent — both enacted and simulated plans use
the same 2pv calculation, so relative rankings are unaffected.

---

### 2.6 2018 Governor broadcast from VTD to block level in composite computation

**Issue:** The 2018 Governor election (Kemp/Abrams) is available at VTD level in the ALARM map
but not at block level. The `build_composite_score.py` pipeline averages six elections, with the
other five available at block level.

**Workaround:** The VTD-level 2018 dem_pct value is broadcast (replicated) down to every block
in that VTD via a left-merge on `vtd_GEOID20` before the per-block nanmean calculation. This
assigns every block within a VTD the same 2018 partisan value. For the aggregation weighting
step (blocks back to VTDs), 2018 is excluded from the weight calculation (weight = average of
the five block-level election totals only) because no block-level vote count is available.

**Impact:** The 2018 contribution to the composite is effectively VTD-level averaged. Blocks
within the same VTD that may have meaningfully different 2018 partisan lean (e.g., a block
containing a university versus a rural block in the same VTD) receive the same 2018 value.
For congressional redistricting (14 large districts), this is unlikely to matter because
most VTDs are entirely within a single congressional district. For state House redistricting
(180 smaller districts), some large VTDs span district boundaries and the within-VTD
broadcast could introduce minor precision loss.

---

### 2.7 Equal weighting of six elections in composite

**Issue:** The six elections in the composite (2018 Gov, 2020 Pres, 2021 War runoff, 2022 Gov,
2022 USS, 2024 Pres) span different political contexts. Runoff elections have lower and
demographically different turnout than general elections. Using equal weights makes 2022 contribute
twice the weight of any other year (two 2022 elections).

**Workaround:** Equal 1/6 weighting is applied to all six elections. No turnout normalization or
temporal discounting is applied. The 2022 dual-election double-weighting is an explicit design
choice noted in the code comments, not an oversight.

**Impact:** 2022 Georgia results (a strong Kemp year with both gubernatorial and Senate races)
have more influence on VTD-level composite partisan lean than any other year. Researchers testing
sensitivity to this weighting assumption should re-run `build_composite_score.py` with alternative
weights and compare `vtd_composite.parquet` outputs.

---

## 3. Election Scope Decisions

### 3.1 Six elections selected, 2016 excluded

**Issue:** The ALARM map includes 2016 election columns (`pre_16_rep_tru`, `uss_16_rep_isa`,
etc.) which could be included in the composite.

**Decision:** 2016 is excluded. The six-election composite spans 2018–2024 (three election cycles).
2016 represents a distinctly different partisan environment pre-2018 Democratic realignment in
Georgia suburbs.

**Impact:** The composite skews toward the 2018–2024 era, which is more predictive of current
political geography. Including 2016 would shift composite Republican lean in suburban districts
where realignment has been strongest. Researchers assessing the sensitivity of ensemble grades to
this choice should note that adding 2016 would likely increase Republican composite margins in
GA-06, GA-07, and similar districts.

---

### 3.2 2021 January runoffs included; 2021 PSC District 1 retained in pipeline but not in composite

**Issue:** The January 5, 2021 runoff ZIP contains three races: two Senate runoffs (Warnock/Loeffler
and Ossoff/Perdue) plus a Public Service Commission District 1 race (Blackman vs. McDonald).

**Decision:** Only the Warnock/Loeffler runoff is included in the six-election composite (as
`uss_2021_war`). The Ossoff/Perdue runoff and the PSC race are aggregated into their respective
output parquets but are not in `BenchmarkConfig`'s elections list and do not enter composite
scoring.

**Impact:** The choice to use Warnock/Loeffler over Ossoff/Perdue is arbitrary from a statistical
standpoint — both took place on the same day with near-identical turnout. Either would produce
essentially the same composite VTD lean. Using both would double-weight January 2021.

---

### 3.3 2022 December runoff absent from composite

**Issue:** The definitive 2022 Senate result — the December 6 runoff — is the two-candidate
Warnock/Walker head-to-head. The November 8 general included Oliver (Lib) and is the version
in the composite.

**Decision:** November 8 general is used. December 6 runoff data has not been acquired from RDH.

**Impact:** Competitiveness and partisan lean calculations for the 2022 USS cycle reflect a
slightly different electorate (higher third-party presence in November, higher partisan polarization
in the December runoff). Given the small Oliver vote share (~2.1%), the two-party share values
for November and December would differ by less than 1pp in most VTDs. The 0.5% statewide
certified threshold check is against the November general totals.

---

### 3.4 Composite labeled as "2018-2024 composite" but 2019, 2021 special elections, 2023 excluded

**Issue:** Georgia holds various special elections and off-cycle primaries. The composite label
implies coverage across years but only covers six specific contests.

**Decision:** Only high-turnout statewide general/runoff elections are included. Local specials and
primaries are excluded. The six chosen elections span gubernatorial, presidential, and Senate
contexts deliberately to produce a politically diverse composite.

**Impact:** The composite reflects statewide-office partisan behavior and will not capture
localized political geography driven by state legislative or judicial elections.

---

## 4. Ensemble Methodology Limitations

### 4.1 ReCom algorithm is not statistically rigorous (not a proper random sample)

**Issue:** The GerryChain ReCom algorithm is used for congressional, senate, and house ensembles.
ReCom is a random walk (Markov chain) with `always_accept` (no Metropolis-Hastings rejection). It
is described in the code comments as "fast (~500 steps/s, widely used, not statistically rigorous."

**Workaround:** The `reversible_recom` algorithm is available via `--algorithm` flag and satisfies
detailed balance (a proper random sample). The config file (`ga_congress_2026_v1.yml`) marks the
algorithm choice as TBD and notes `reversible_recom` is recommended for legal/published benchmarks.
The current production runs use `recom`.

**Impact:** The ensemble does not constitute a formal statistical sample from the space of valid
plans. Plans drawn by ReCom are correlated with their neighbors in the chain (autocorrelation).
The effective sample size is smaller than the 9,501 nominal draw count. For advocacy purposes
this is standard practice in the field; for legal testimony, `reversible_recom` or the ALARM SMC
ensemble should be cited instead. The ALARM SMC ensemble (5,000 plans) does satisfy the proper
sampling requirement.

---

### 4.2 Population tolerance set at 2% (too loose for congressional benchmarks)

**Issue:** The `ga_congress_2026_v1.yml` config sets `pop_epsilon = 0.02` (±2% of ideal
population). The config comments explicitly note: "±1% is the standard for congressional
benchmarks (Princeton/MGGG); ±2% is too loose for legal use."

**Workaround:** The 2% value is in use pending review. A tighter epsilon tightens the
constraint during proposal generation and would reduce the acceptance rate of proposed splits.

**Impact:** The GerryChain ensemble contains plans that deviate up to ±2% from equal population.
Congressional maps are subject to strict "one person, one vote" requirements (Wesberry v. Sanders)
and are expected to achieve near-exact equality. Plans with 2% deviation would likely fail legal
scrutiny. Benchmark comparisons that include these plans in the reference distribution may
understate how extreme the enacted plan is relative to legally valid plans only.

---

### 4.3 Constraint epsilon auto-widened at initialization

**Issue:** The enacted Georgia congressional map has VTD-level population deviations that, at
strict epsilon settings, would cause the GerryChain initialization from the enacted plan to
immediately fail the validity check.

**Workaround:** At startup, the script computes the maximum VTD-level population deviation in the
enacted plan, then sets `constraint_eps = max(epsilon, max_enacted_dev * 1.05)` (5% slack above
the enacted map's actual deviation). The chain initializes successfully and the proposal
continues to target the tighter `epsilon`.

**Impact:** The chain starts from the enacted plan as draw=1 but begins the random walk with a
slightly relaxed validity boundary. Plans in the early chain may have population deviations
between `epsilon` and `constraint_eps`. Since burn_in=0 in current config, these early plans are
included in the output. With burn_in=500 (recommended), early high-deviation plans would be
discarded.

---

### 4.4 Burn-in set to 0 (no burn-in applied)

**Issue:** MCMC chains should discard early draws before the chain reaches its stationary
distribution. The config notes "500 is reasonable for Congress" but the current value is 0.

**Workaround:** None applied. All 10,000 chain steps are included in the output. Enacted plan is
always prepended as draw=1 (row 0) regardless of burn_in value.

**Impact:** Early chain draws are more similar to the enacted plan than draws from a converged
chain would be. This biases the reference distribution slightly toward the enacted map's
characteristics, potentially making the enacted plan appear less extreme than it actually is.

---

### 4.5 Single chain run (no Gelman-Rubin convergence diagnostic)

**Issue:** The config runs `n_chains=1`. The config notes "5 chains enables Gelman-Rubin R-hat
diagnostic." With one chain there is no way to assess whether the chain has converged or is
stuck in a region of plan space.

**Workaround:** None. Single-chain output is used as-is.

**Impact:** The ensemble may not adequately explore the full space of valid plans. In particular,
for politically constrained states like Georgia, the chain may have difficulty transitioning
between plan topologies with different numbers of minority-majority districts. Convergence cannot
be formally verified.

---

### 4.6 No explicit compactness or minority-district constraints in GerryChain runner

**Issue:** The runner applies only a population constraint. No compactness requirement, no
county-preservation, and no VRA minority-district constraint are enforced during plan generation.

**Impact:** The ensemble reference distribution includes plans that may be legally invalid (too
non-compact, fails VRA Section 2 requirements, splits counties unnecessarily). Comparisons against
this distribution overstate the universe of legally permissible plans. The ALARM ensemble applied
BVAP hinge constraints during sampling, making it a tighter reference for VRA analysis.

---

### 4.7 Silent error handling for bipartition failures

**Issue:** GerryChain's `bipartition_tree` algorithm with `max_attempts=500` occasionally cannot
find a valid cut for a proposed merge region and raises `RuntimeError: Could not find a possible cut`.

**Workaround:** A `_safe()` iterator silently skips individual step failures. After 5 consecutive
failures the chain stops early with whatever draws it has accumulated.

**Impact:** The output may contain fewer draws than `n_steps` if many consecutive failures
occurred. The `_meta.json` file records actual `n_draws`. Steps following a skipped failure
start from the same state as before the failure, creating a slight autocorrelation increase at
those points.

---

### 4.8 ALARM ensemble is congress-only and from 2021 (stale)

**Issue:** The ALARM Project dataset covers only the congressional chamber (14 districts) and was
generated in 2021 using 2016–2020 elections. There are no ALARM RDS files for Georgia state Senate
(56 districts) or state House (180 districts).

**Impact:** For Senate and House, only the GerryChain ensemble is available. The statistically
rigorous SMC benchmark exists only for Congress. Cross-chamber comparisons of ensemble quality
are not possible.

---

## 5. Metrics Calculation Approximations

### 5.1 Histogram-based percentile rank approximation in _score_geojson

**Issue:** The `_score_geojson` endpoint scores uploaded GeoJSON plans. It does not have access
to the raw ensemble plan matrix (which would be too large to keep in memory per request). Percentile
ranking must use the pre-computed histogram stored in the scorecard JSON.

**Workaround:** `_rank_and_grade()` reconstructs an approximate distribution by calling
`np.repeat(bin_centers, bin_counts)`, producing a synthetic array of ~N values (where N =
total ensemble draws). Percentile rank is then `(approx_dist <= value).mean() * 100`.

**Impact:** For continuous metrics (efficiency gap, mean-median), this approximation loses
precision proportional to bin width. A value that lands near a bin boundary may receive a
rank ±1–2 percentage points from the true rank. For integer metrics (dem_seats, comp_seats),
the histogram is exact and no approximation error occurs. The approximation does not affect
letter grade assignments in most cases — grade transitions occur at coarse thresholds (5th, 20th,
50th, 64th, 95th percentiles) and are unlikely to be affected by ±2pp approximation error.

---

### 5.2 comp_seats competitive margin inconsistency between benchmark build and score endpoint

**[RESOLVED 2026-06-07] Fixed: changed 0.45/0.55 hardcode to use half_margin_score = COMPETITIVE_MARGIN/2.0**
**[RESOLVED 2026-06-07] Fixed: changed COMPETITIVE_MARGIN default from 0.07 to 0.10 to match scorecard threshold (half = 0.05 = ±5pp)**

**Issue (archived):** Two different competitive-seat definitions were used in different code paths:
- `build_draw_stats.py` and `compute_metrics()`: `|dem_2pv - 0.5| <= COMPETITIVE_MARGIN/2`
  where `COMPETITIVE_MARGIN = 0.07` (default), giving a ±3.5pp window (seats between 46.5% and
  53.5% dem_2pv are competitive).
- `_score_geojson()` (line 1546 in `fdensemble/main.py`): hardcoded `[0.45, 0.55]` (±5pp window).

**Cross-system issue (archived):** After the first fix, `_score_geojson` was internally consistent but
the default `COMPETITIVE_MARGIN = 0.07` (half = 0.035, ±3.5pp) still differed from the scorecard
parquets which were built with `competitive_threshold = 0.05` (±5pp). Uploaded plans were scored
on a ±3.5pp window while the ensemble benchmark used ±5pp, producing misleading comp_seats
pct_rank values.

**Resolution:** `COMPETITIVE_MARGIN` default changed to `0.10` (half = 0.05 = ±5pp), matching
`build_scorecard.py`'s `COMPETITIVE_THRESHOLD_DEFAULT = 0.05`. Description strings in `main.py`
updated to use `COMPETITIVE_MARGIN / 2 * 100` for human-readable "5pp" output. The env var
`COMPETITIVE_MARGIN_MAIN` remains available to override if needed.

**Impact (archived):** When `COMPETITIVE_MARGIN = 0.10` (which equals a ±5pp window), the two definitions
agreed. At the default of `COMPETITIVE_MARGIN = 0.07`, `_score_geojson` used a wider window than
the benchmark. A district at 46.8% dem_2pv would be counted as competitive by the scoring endpoint
but not by the benchmark builder, producing a score discrepancy for uploaded plans. This bug did
not affect the pre-computed benchmark scorecards, only interactive scoring of user-uploaded plans.

**Severity:** Moderate. For Georgia congressional (14 districts), the difference between the two
definitions typically affected 0–1 district in practice.

---

### 5.3 maj_black grading inconsistency between compute_princeton_grades and _score_geojson

**[RESOLVED 2026-06-07] Fixed: floor-based grading implemented. grade_symmetric retained alongside grade for lineage.**

**Issue (archived):** Two grading paths applied different logic to `maj_black` (majority-Black districts):
- `compute_princeton_grades()` (line 938): took the `higher_is_better is None` branch, applying
  symmetric `_simple_grade` (center of the distribution is best; both too-few and too-many are
  anomalous).
- `_rank_and_grade()` in `_score_geojson` (line 1583): listed `maj_black` as "higher is better"
  (directional), applying `_comp_grade` thresholds.

**Impact (archived):** For the same plan, the standalone `maj_black` card shown in the benchmark
scorecard could receive a different letter grade than the `maj_black` card shown in the interactive
GeoJSON scorer. For Georgia, the enacted congressional map has 4 majority-Black districts at the
100th percentile of the ensemble (pct_rank = 100). Under symmetric grading this was F; under
"higher is better" grading this would be A. This was a significant discrepancy.

**Resolution details:** Floor-based grading is now applied to `maj_black` and `min_coal` across
`build_scorecard.py`, `build_alarm_scorecard.py`, and `fdensemble/main.py`. The `grade_symmetric`
field is retained in scorecard JSON alongside `grade` for lineage/audit purposes.

---

### 5.4 Efficiency gap formula uses 50%+1 threshold (not weighted-median threshold)

**Issue:** The efficiency gap formula defines "wasted votes in a winning district" as votes above
50% of the total votes in that district (the bare-majority threshold). Some scholars use a
median-voter or supermajority threshold instead.

**Workaround:** The standard Stephanopoulos-McGhee formula is used: wasted in wins =
`dem_votes - total_votes/2`; wasted in losses = `dem_votes`. Positive EG = Republican structural
advantage.

**Impact:** This is the canonical academic definition. No deviation from standard practice.

---

### 5.5 Polsby-Popper is plan-level mean from ALARM CSV (double-averaging risk)

**Issue:** The ALARM stats CSV column `comp_polsby` is already a per-plan-level mean (one value
per district per draw). When `build_alarm_scorecard.py` reads the enacted plan row, it computes
`e[pp_col].mean()` across the 14 district rows. Since `comp_polsby` is already a per-district
value (not a plan-level scalar), this is computing the mean of per-district Polsby-Popper values,
which is correct. However, a future analyst reading the code may expect `comp_polsby` to be
a plan-level summary and avoid the `.mean()` call — which would be wrong.

**Impact:** No current correctness issue. Risk of future regression if the ALARM CSV format
changes or if the column meaning is misread.

---

### 5.6 Partisan bias (pbias) passed through without recomputation

**Issue:** `pbias` (partisan bias via cube-law) is read from the ALARM stats CSV for the ALARM
benchmark path. For GerryChain runs, `partisan_bias` is null. The metric appears in the normative
test within `_compute_composite_grades()` (pass if `|pbias| <= max(1, 0.07*N)/N`) but is not
included in `_METRIC_META` dict and does not get a histogram or grade card.

**Impact:** The normative test in the partisan fairness composite effectively defaults to "pass"
for all GerryChain runs (since pbias is unavailable). The partisan fairness composite grade for
GerryChain runs is determined entirely by the ensemble test (whether dem_seats, efficiency_gap,
and mean_median pass the 5th–95th percentile band). This weakens the partisan fairness grade
for GerryChain benchmarks relative to what a full Princeton test would produce.

---

### 5.7 ALARM muni_splits incompatible with GerryChain muni_splits

**Issue:** The ALARM stats CSV `muni_splits` column counts municipalities tracked under ALARM's
own municipality definition. The GerryChain pipeline computes muni_splits using `vtd_muni.parquet`
(the project's own VTD-to-municipality mapping). These two municipality sets are different in size
and composition.

**Concrete discrepancy:**
- GerryChain congressional: enacted = 12 splits, ensemble median = 27, Grade = A
- ALARM congressional: enacted = 16 splits, ensemble median = 6, Grade = F

**Impact:** The two scorecards cannot be directly compared on muni_splits. The ALARM scorecard's
muni_splits F grade does not contradict the GerryChain scorecard's A grade — they are measuring
different things with different reference distributions. Users viewing both scorecards must be
warned that this metric is not cross-benchmark comparable. The fdensemble UI should note this
discrepancy when displaying ALARM vs. GerryChain side-by-side.

---

### 5.8 Proportionality gap uses VAP-weighted statewide dem_2pv, not actual vote share

**Issue:** The proportionality gap requires a statewide Democratic vote share to compute the
"proportional target" (statewide_dem_2pv * n_districts). This could be sourced from:
(a) actual total votes across all six elections, or
(b) VAP-weighted composite dem_2pv from `vtd_composite.parquet`.

**Decision:** Option (b) is used. `_get_statewide_dem_2pv()` computes
`sum(composite_dem_pct * VAP_MOD) / sum((composite_dem_pct + composite_rep_pct) * VAP_MOD)`.

**Impact:** The VAP-weighted composite reflects the underlying partisan lean of eligible voters,
not actual turnout. In high-turnout elections, actual vote share may differ from VAP-weighted
composite share by 1–2pp. The structural_gap and manipulation_gap quantities are approximations
of the true proportionality decomposition.

---

## 6. Known Data Quality Issues

### 6.1 Statewide vote total validation thresholds

**Issue:** After each block-to-VTD aggregation, statewide totals are compared to Georgia SOS
certified results. A 0.5% discrepancy threshold triggers a warning.

**Reference certified totals used:**
- 2020 Pres: Biden 2,473,633 / Trump 2,461,854
- 2021 Runoff: Ossoff 2,269,923 / Perdue 2,195,359 / Warnock 2,288,923 / Loeffler 2,195,130
- 2022 General: Abrams 1,326,916 / Kemp 2,112,319 / Warnock 1,945,370 / Walker 1,908,442
- 2024 Pres: Harris 2,197,292 / Trump 2,209,525

**Impact:** The 0.5% threshold is a sanity check, not a hard error. Discrepancies below 0.5% can
arise from: blocks with centroids on VTD boundaries landing in an adjacent VTD, blocks with no
votes but nonzero geometry (water features, special land areas), or minor rounding differences
between the RDH disaggregation and actual precinct totals. These are expected and acceptable.
Discrepancies above 0.5% would indicate a systematic join error.

---

### 6.2 Zero-VAP VTDs receive neutral 0.5 composite dem_pct

**Issue:** Some VTDs have VAP_MOD = 0 (military bases, monuments, water features, cemeteries,
Fulton County administrative polygons, etc.). These VTDs have no voters and no turnout in any
election. Dividing vote totals by zero VAP produces undefined composite shares.

**Workaround:** Zero-VAP VTDs are explicitly detected (`VAP_MOD == 0`) and filled with
`composite_dem_pct = 0.5`, `composite_rep_pct = 0.5`, `composite_other_pct = 0.0`.

**Impact:** These VTDs contribute zero synthetic votes to any district (since votes = share *
VAP_MOD = 0.5 * 0 = 0). The 0.5 fill value does not affect scoring. However, if a future pipeline
change uses composite_dem_pct without multiplying by VAP_MOD, zero-VAP VTDs would appear to be
perfectly competitive, which is misleading.

---

### 6.3 Low-VAP VTDs with no block coverage filled with county-average composite

**Issue:** A small number of VTDs have nonzero VAP_MOD but no blocks from any of the five block-
level elections landed in them after the centroid-in-polygon join. This can happen for very small
administrative VTDs, VTDs that are entirely within a special land-use area, or boundary VTDs whose
blocks' centroids fell outside the VTD polygon.

**Workaround:** After the zero-VAP fill, any remaining NaN composite values are filled with the
weighted county-average composite, keyed on the first 5 characters of GEOID20 (state+county FIPS).

**Impact:** Affected VTDs receive a county-average partisan lean rather than their actual lean.
For very small VTDs (VAP 2–11), this approximation is inconsequential in district-level scoring.
A final hard assertion (`composite_dem_pct.isna().sum() == 0`) verifies no NaN values escape.

---

### 6.4 Unmatched blocks in centroid-in-polygon join dropped silently

**Issue:** Some blocks (predominantly water features, island blocks, or boundary slivers) have
centroids that do not fall within any VTD polygon. These are dropped from the join with a warning
log message.

**Impact:** Dropped blocks carry VAP_MOD=0 in virtually all cases, meaning they contribute no
vote data. If a non-zero-VAP block is dropped, its votes are lost from the VTD total. Because
the statewide total validation check runs after aggregation, any systematic drop of populated
blocks would show up as a >0.5% discrepancy. The validation check is the backstop for this
scenario.

---

### 6.5 ALARM maj_black counts use 2020 Census VAP; GerryChain uses 2024 ACS CVAP

**Issue:** The two benchmarks use different demographic data for minority-district counting:
- ALARM: 2020 Census VAP directly from `GA_cd_2020_stats.csv` (raw population, includes
  non-citizens)
- GerryChain: 2024 ACS 5-year CVAP estimates (citizen voting-age population, RDH-disaggregated
  to 2020 blocks)

**Concrete discrepancy (congressional):**
- ALARM: 2–3 majority-Black districts in ensemble; enacted = 2 (Grade: B)
- GerryChain: 1–3 majority-Black districts in ensemble; enacted = 4 (Grade: F)

**Impact:** The discrepancy arises from two independent factors: (1) data vintage (2020 Census vs.
2024 ACS — population shifts over 4 years), and (2) VAP vs. CVAP (CVAP is more legally precise
under VRA Section 2 because it counts only citizens). The GerryChain result (4 majority-Black
districts as a statistical outlier) is the more legally relevant finding for VRA analysis.
The ALARM result reflects an earlier and less precise demographic baseline.

---

### 6.6 ALARM electoral baseline is 2016-2020; re-scored to 2018-2024

**Issue:** The ALARM dataset was generated in 2021 using 2016–2020 cycle election averages. For
cross-benchmark comparisons with GerryChain (which natively uses 2018–2024 composite), the ALARM
ensemble must be re-scored.

**Workaround:** `build_alarm_scorecard.py` replaces the ALARM stats CSV's electoral columns with
the project's `vtd_composite.parquet` (2018–2024 composite), aligning GEOID row order via the
R-exported GEOID sequence, then recomputes all partisan metrics from scratch. The re-scored ALARM
values are what appear in `fdga_2026_benchmark_congress_alarm_scorecard.json`.

**Impact:** The re-scoring requires exact GEOID row alignment between the RDS row order and
`vtd_composite.parquet`. This alignment is critical — a one-row offset would corrupt all ALARM
partisan scores. The alignment is validated by checking that total weighted population matches
the expected statewide total, but there is no per-VTD cross-validation step.

---

### 6.7 GerryChain runs have null polsby_popper and county_splits

**Issue:** The GerryChain runner outputs only district assignment matrices. Computing Polsby-
Popper requires district geometries (not just VTD assignments), and computing county splits
requires a VTD-to-county mapping that was not implemented in the scoring pipeline.

**Workaround:** `polsby_popper` and `county_splits` are null in all three GerryChain scorecards
(congress, senate, house). Only the ALARM congressional scorecard has these values (from the
ALARM stats CSV).

**Impact:** The `_geographic` composite grade (which combines polsby_popper and county_splits)
cannot be computed for GerryChain runs. The `_overall` composite therefore lacks the geographic
component adjustment for all GerryChain benchmarks.

---

## 7. Deployment Workarounds

### 7.1 NaN/Inf floats in _score_geojson JSON response (fixed)

**Issue:** Edge-case districts with zero composite votes (e.g., a district assignment polygon that
captures only zero-VAP VTDs, or a district so partisan that efficiency gap arithmetic produces
infinity) generated Python `float('nan')` or `float('inf')` values. Python's `json.dumps()`
does not serialize these values; they cause a 500 error in the API response.

**Fix applied:** A `_sanitize_for_json()` recursive function was added to the endpoint. It walks
the entire response dict tree and replaces any `float('nan')` or `float('inf')` values with
`None` (JSON null) before serialization. This is commit `3ceb9ab`.

**Impact:** Resolved. Previously, uploading a GeoJSON plan with unusual district topology could
crash the scoring endpoint. The null substitution is correct behavior — a null metric value is
more informative than a server error.

---

### 7.2 Frontend dist/ assets committed to repository for Railway deployment

**Issue:** Railway's free-tier build environment does not have sufficient RAM to run a full
`npm run build` during Docker image construction for the fdensemble frontend (Svelte 5 + Vite).

**Workaround:** The compiled `frontend/dist/` assets are committed to the git repository and
served directly from the container without a build step. The Dockerfile copies the pre-built
dist/ directory into the image.

**Impact:** Frontend changes require a local build step followed by committing dist/ assets before
deployment. If a developer modifies Svelte source files and pushes without rebuilding, the
deployed app will show stale frontend code. There is no automated check that dist/ is in sync
with source. This is commit `547038b`.

---

### 7.3 Supabase run catalog requires DATABASE_URL env var; skippable with --no-db

**Issue:** The ensemble runner tracks run status in `fdp.ensemble_runs` via psycopg. In local
development or Modal cloud runs where DATABASE_URL is not set, the tracker would fail.

**Workaround:** The `--no-db` flag skips all Supabase catalog writes. Modal cloud runs default
to `--no-db` unless DATABASE_URL is explicitly passed as a Modal secret.

**Impact:** Runs executed with `--no-db` do not appear in the Supabase catalog and cannot be
discovered via the catalog query. Run metadata is still written to `{run_name}_meta.json` locally.

---

### 7.4 Modal cloud plans require manual download before scoring

**Issue:** When `--modal` or `--modal-async` is used, plan files are written to a Modal volume
(cloud storage) rather than the local filesystem. The scoring pipeline (`score_ensemble_plans.py`)
reads plans from local disk.

**Workaround:** After a Modal run completes, plans must be manually downloaded from the Modal
volume to `fdp/data/repos/main/ensemble/` before running `score_ensemble_plans.py`. No automated
download step exists.

**Impact:** Modal asynchronous runs (`--modal-async`) fire-and-forget, meaning the researcher
must poll for completion (via Modal dashboard or `modal volume ls`) before downloading. There is
no notification mechanism integrated with the scoring pipeline.

---

### 7.5 UnboundLocalError in _score_geojson muni splits calculation (fixed)

**Issue:** The muni splits calculation in `_score_geojson` had a code path where `muni_splits_count`
could be referenced before assignment if `vtd_muni.parquet` was unavailable or the join returned
an empty result.

**Fix applied:** Commit `85293b4` resolved the `UnboundLocalError`. The variable is now
initialized to a default value before the conditional block.

**Impact:** Resolved. Uploading GeoJSON plans to the interactive scorer no longer crashes when
the municipality data join produces unexpected results.

---

*End of WORKAROUNDS.md*
