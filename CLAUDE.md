# FairDistricts GA — Redistricting Ensemble Project

## Project Context
Building VTD-level redistricting ensembles for **FairDistricts GA** anti-gerrymandering work using:
- **GerryChain** (Princeton Gerrymandering Project, Python)
- **ALARM / redist** framework (Harvard, R)

Target geography: **2020 Census VTDs** (2,698 VTDs across 159 Georgia counties).
Primary use: congressional district ensemble benchmarks (14 districts).

---

## Files On Hand

### R Objects (ALARM format)
| File | Description |
|------|-------------|
| `GA_cd_2020_map.rds` | `redist_map`, 2698 VTDs × 55 cols. **The primary base map.** Has adjacency list (`adj`), `pseudo_county`, `cd_2010`, `cd_2020`. Total pop: 10,711,908. |
| `GA_cd_2020_plans.rds` | `redist_plans`, 5001 draws (draw 1 = enacted), 14 districts. Cols: draw, district, chain, total_pop, pop_overlap. |
| `GA_cd_2010_map.rds` | `redist_map`, 2961 VTDs (2010 boundaries), pop 9,685,176. For comparative/historical analysis. |
| `GA_cd_2010_plans.rds` | `redist_plans`, 5001 draws, 14 districts, 2010 cycle. |

### Census / Demographic (Block-level ZIPs → need VTD aggregation)
| File | Description |
|------|-------------|
| `ga_pl2020_vtd.zip` | **2020 PL 94-171 shapefile at VTD level** (2698 VTDs, EPSG:4269). Full P1–P5 tables. GEOID20 matches ALARM map GEOID directly. Geometry base for aggregation. |
| `ga_pl2020_b.zip` | 2020 PL 94-171 at **block level** (~232K blocks, 237MB CSV). Used as VAP weight source for disaggregation. |
| `ga_cvap_2024_2020_b_csv.zip` | 2024 ACS CVAP (2020–2024 5yr) **disaggregated to 2020 blocks** by RDH (retrieved 02/17/2026). 33 CVAP columns. GEOID20 = 15-char block code. |

### Election Results (Block-level ZIPs → need VTD aggregation)
| File | Description |
|------|-------------|
| `Copy_of_ga_2022_gen_2020_blocks.zip` | 2022 general election disaggregated to 2020 blocks. 232,717 rows, 414 cols. Full shapefile with geometry. Source: RDH (retrieved 05/27/2026). |
| `Copy_of_ga_2024_gen_2020_blocks.zip` | 2024 general election disaggregated to 2020 blocks. 232,717 rows, 394 cols. Full shapefile with geometry. Source: RDH (retrieved 05/27/2026). |

---

## Elections Already in the ALARM Map (GA_cd_2020_map.rds)
These are already at VTD level — no processing needed.

| Column(s) | Election |
|-----------|----------|
| `pre_16_rep_tru` / `pre_16_dem_cli` | 2016 President |
| `uss_16_rep_isa` / `uss_16_dem_bar` | 2016 US Senate (Isakson/Barksdale) |
| `gov_18_rep_kem` / `gov_18_dem_abr` | 2018 Governor (Kemp/Abrams) ✓ |
| `atg_18_rep_car` / `atg_18_dem_bai` | 2018 Attorney General |
| `sos_18_rep_raf` / `sos_18_dem_bar` | 2018 Secretary of State |
| `sos_r18_rep_raf` / `sos_r18_dem_bar` | 2018 SOS Runoff |
| `pre_20_rep_tru` / `pre_20_dem_bid` | 2020 President ✓ |
| `uss_20_rep_per` / `uss_20_dem_oss` | 2020 US Senate (Perdue/Ossoff) |
| `arv_16/adv_16`, `arv_18/adv_18`, `arv_20/adv_20` | Avg R/D vote by cycle |
| `nrv` / `ndv` | Overall avg R/D vote |

---

## Elections Still Needed (Acquire + Aggregate to VTD)

### Need to Acquire from RDH
1. **2021 Jan 5 Senate Runoffs** — Warnock/Loeffler + Ossoff/Perdue.
   - Check RDH for block-disaggregated version first (email info@redistrictingdatahub.org).
   - Fallback: RDH "2020 Georgia General/Special/Runoff/Recount Election Results and Precinct Boundaries" → process with maup.
   - Target columns: `uss_r21_dem_war`, `uss_r21_rep_loe`, `uss_r21b_dem_oss`, `uss_r21b_rep_per`

2. **2022 Dec 6 Senate Runoff** — Warnock/Walker head-to-head.
   - The 2022 block file has the Nov 8 general only (3-way race with Oliver Lib).
   - Check RDH for block-disaggregated runoff version.
   - Target columns: `uss_r22_dem_war`, `uss_r22_rep_wal`

### Aggregated to VTD — Done ✅
Script: `fdp/scripts/build_vtd_inputs.py`  
Block→VTD lookup cache: `fdp/data/repos/main/vtd/block_vtd_lookup.parquet` (232,717 blocks → 2,698 VTDs)

| Election | VTD output | Accuracy vs SOS certified |
|----------|------------|--------------------------|
| 2022 Gov (Abrams/Kemp) + USS + statewide | `election_results` parquet | 0.01–0.04% ✓ |
| 2024 President (Harris/Trump) | `election_results` parquet | 0.01–0.03% ✓ |
| 2021 USS Runoff (Warnock/Loeffler) | `election_results` parquet | 0.00% ✓ |
| CVAP 2024 ACS 5-yr | `cvap_vtd.parquet` | — |

**Election scope rule:** Score president, governor, senate, us-house, state-rep only — exclude AG, SoS, LtGov, PSC etc.

---

## Key Technical Notes

### GEOID Formats
- **ALARM map GEOID**: 11-char `SS+CCC+VVVVVV` (e.g., `13001000002`). Matches `GEOID20` in VTD shapefile directly.
- **Block GEOID20**: 15-char `SS+CCC+TTTTTT+BBBB` (e.g., `130019501001000`). Cannot be string-truncated to VTD GEOID — needs spatial join or Census BAF.
- **VTD shapefile GEOID20**: Same 11-char format as ALARM GEOID. Direct join key.

### VAP_MOD (Critical)
Both 2022 and 2024 block files use `VAP_MOD = P0040001 - P0050003` (total VAP minus correctional facility population). **Always use VAP_MOD as disaggregation weights**, not raw VAP. Georgia has significant prison populations in rural counties (Telfair, Stewart, Wheeler, etc.) that inflate raw VAP.

### Block→VTD Aggregation Method
Census 2020 blocks nest perfectly within 2020 VTDs by design. Use centroid-in-polygon spatial join:
```python
blocks_ctr = blocks.copy()
blocks_ctr.geometry = blocks.centroid
joined = gpd.sjoin(blocks_ctr, vtds[["GEOID20","geometry"]], 
                   how="left", predicate="within")
vtd_agg = joined.groupby("GEOID20_right")[election_cols].sum()
```
Alternative: Census 2020 Block Assignment File (BAF) for Georgia at:
`census.gov/geographies/reference-files/time-series/geo/block-assignment-files.html`

### CVAP Aggregation
Same block→VTD join, then sum these key columns:
- `CVAP_TOT24` — Total CVAP
- `CVAP_BLK24` — Black/AA alone or in combination CVAP
- `CVAP_HSP24` — Hispanic CVAP
- `CVAP_WHT24` — White alone CVAP
- `CVAP_ASN24` — Asian alone or in combination CVAP

### Two-Party Vote Share
For races with third-party candidates (2022 USS has Oliver Lib), compute:
`dem_2pv = G22USSDWAR / (G22USSDWAR + G22USSRWAL)`
Exclude Libertarian/Green from denominator.

### File Size Warning
2022 and 2024 shapefiles are ~2.6GB unzipped each. Load only needed columns:
```python
gpd.read_file("ga_2022_gen_2020_blocks.shp", 
              columns=["GEOID20","VAP_MOD","G22GOVDABR","G22GOVRKEM",...])
```
Or extract DBF to Parquet first to avoid re-reading geometry.

---

## Still Outstanding

| Item | Action |
|------|--------|
| 2022 Dec 6 runoff (block-level) | Request from RDH — Nov 8 general already aggregated; Dec 6 head-to-head separate file |
| 2021 Jan 5 runoff (block-level) | Request from RDH — Warnock/Loeffler race (already have R21USSDWAR/R21USSRLOE from gen) |
| 2026 precinct boundaries | Download from GA Reapportionment Office: `legis.ga.gov/joint-office/reapportionment` |
| House GerryChain run | Config built (`ga_house_2026_v1.yml`), not yet run on Modal |
| House ALARM ensemble | `build_house_map.R` not written yet |

---

## Data Sources & Citations
- ALARM Project (Kenny, McCartan, Simko, et al.): `alarm-redist.org` / Harvard Dataverse `doi:10.7910/DVN/SLCD3E`
- Redistricting Data Hub (RDH): `redistrictingdatahub.org`
- Voting and Election Science Team (VEST): `dataverse.harvard.edu/dataverse/electionscience` (CC-4.0)
- U.S. Census Bureau PL 94-171: `census.gov`
- Processing: RDH pipeline using `maup` (MGGG), VAP_MOD weights, Hamilton rounding

---

## Active Benchmark Scorecards

Four production scorecards in `fdensemble/input_data/`, all using 2024 ACS CVAP for demographics:

| File | Algorithm | Draws | Chamber |
|------|-----------|-------|---------|
| `fdga_baseline_benchmarks_2601_congress_scorecard.json` | GerryChain/ReCom | 99,001 | Congress (14D) |
| `fdga_baseline_benchmarks_2601_congress_alarm_scorecard.json` | ALARM/SMC | 100,001 | Congress (14D) |
| `fdga_baseline_benchmarks_2601_senate_scorecard.json` | GerryChain/ReCom | ~450,000 | Senate (56D) |
| `fdga_baseline_benchmarks_2601_senate_alarm_scorecard.json` | ALARM/SMC | 100,001 | Senate (56D) |

Configs: `fdp/configs/benchmarks/ga_{congress,senate}_2026{_v3,_alarm}.yml`  
Rebuild pipeline: `bash rebuild_pipeline.sh` (from fgdp/ root)

## Next Steps

1. Acquire 2022 Dec 6 runoff + 2021 Jan 5 runoff block files from RDH
2. Run House GerryChain ensemble on Modal (`ga_house_2026_v1.yml`)
3. Build `build_house_map.R` for ALARM house ensemble
4. Tighten congress pop_epsilon 0.02 → 0.01 for published legal use
5. Switch GerryChain from `recom` to `reversible_recom` for published runs
6. Acquire 2026 precinct boundaries from GA Reapportionment Office
