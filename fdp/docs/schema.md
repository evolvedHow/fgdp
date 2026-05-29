# FDP PostgreSQL Schema Reference

**Database:** `fdp` (PostgreSQL 16 + PostGIS)  
**Schema:** `fdp`  
**Last updated:** 2026-05-29  
**Maintained by:** `fdp/sql/002_cdm.sql` — apply with `fdp init-db`

---

## Overview

The FDP Common Data Model (CDM) stores redistricting data at any level of the
Census/political geography hierarchy — from individual Census blocks up to the
state level. All tables are designed for UPSERT-based loading, multi-year
coexistence, and analytical queries via SQL clients (DBeaver, Looker Studio,
Tableau, psql).

### Design principles

| Principle | Detail |
|-----------|--------|
| **Single fact tables** | All elections coexist in `election_results`. All CVAP years coexist in `cvap`. No per-year table sprawl. |
| **Geography agnostic** | Every fact table carries a `geo_level` column so data at block, VTD, precinct, county, or state level can coexist without schema changes. |
| **UPSERT-safe** | Every table has a natural primary key. New data is always `INSERT … ON CONFLICT DO UPDATE`. Re-running a load never duplicates rows. |
| **Audit trail** | Every table carries `created_at`, `updated_at`, `update_count`, and `loaded_by`. |
| **Self-documenting** | Every table and column has a PostgreSQL `COMMENT`. Viewable in DBeaver by hovering over any object. |

---

## Tables

### `fdp.geography`

Central register for every geographic unit used in the platform. One row per
`(geoid, vintage_year)`. All fact tables join here.

**Replaces the old `fdp.vtd` table.**

| Column | Type | Description |
|--------|------|-------------|
| `geoid` | TEXT | Geographic identifier. Census FIPS for Census units; state-issued code for political units. See GEOID encoding notes below. |
| `geo_level` | TEXT | Level: `block_fusion \| block \| block_group \| tract \| vtd \| precinct \| county \| district \| state` |
| `geo_type` | TEXT | `census` (Census Bureau units) or `political` (election-board units) |
| `state` | TEXT | State abbreviation (`GA`, `NC`, …) |
| `county_fips` | TEXT | 5-character county FIPS. For Census units: always `LEFT(geoid, 5)`. |
| `name` | TEXT | Human-readable label (county name, district number, etc.) |
| `vintage_year` | INT | Boundary year. Default `2020`. A 2010 VTD and a 2020 VTD with the same code are separate rows. |
| `source` | TEXT | `Census \| state_election_board \| derived` |
| `created_at` | TIMESTAMPTZ | When this row was first inserted |
| `updated_at` | TIMESTAMPTZ | When this row was last modified |
| `update_count` | INT | Number of UPDATEs to this row (0 = never updated after insert) |
| `loaded_by` | TEXT | CLI command that wrote this row (e.g. `fdp load-pg`) |

**Primary key:** `(geoid, vintage_year)`

**Currently populated:** 2,698 Georgia VTDs, `geo_level = 'vtd'`, `vintage_year = 2020`

---

### `fdp.election_results`

All election results, all years, all races — one row per candidate per VTD per election.

| Column | Type | Description |
|--------|------|-------------|
| `geoid` | TEXT | Geographic identifier — FK to `fdp.geography` |
| `geo_level` | TEXT | Level of this row: `vtd \| block \| precinct \| county \| state` |
| `collection_geo_level` | TEXT | Level at which votes were **originally counted** by the election board before any disaggregation. For RDH data: `precinct`. Audit metadata — does not change the row's analytical meaning. |
| `state` | TEXT | State abbreviation |
| `year` | INT | Election year. For January runoffs scheduled the prior year, use the original scheduled year (e.g. the Jan 2021 Georgia runoffs use `year = 2020`). |
| `election_type` | TEXT | `general \| runoff \| special \| primary` |
| `office` | TEXT | Canonical office name — see Office Values below |
| `party` | TEXT | `dem \| rep \| lib \| grn \| ind \| other` |
| `candidate` | TEXT | Candidate code in lowercase (e.g. `kemp`, `abrams`, `warnock`, `walker`) |
| `votes` | BIGINT | Vote count for this candidate in this geographic unit |
| `source` | TEXT | `RDH \| VEST \| derived` |
| `created_at` | TIMESTAMPTZ | First insert timestamp |
| `updated_at` | TIMESTAMPTZ | Last update timestamp |
| `update_count` | INT | Number of UPDATEs |
| `loaded_by` | TEXT | CLI command that wrote this row |

**Primary key:** `(geoid, year, election_type, office, party, candidate)`

**Currently populated:**

| Year | Type | Offices |
|------|------|---------|
| 2022 | general | governor, senate, attorney-general, secretary-of-state, lt-governor, labor-commissioner, insurance-commissioner, agriculture-commissioner, superintendent |
| 2024 | general | president |

#### Office canonical values

| Value | Full name |
|-------|-----------|
| `governor` | Governor |
| `senate` | U.S. Senate |
| `president` | President of the United States |
| `attorney-general` | Attorney General |
| `secretary-of-state` | Secretary of State |
| `lt-governor` | Lieutenant Governor |
| `labor-commissioner` | Labor Commissioner |
| `insurance-commissioner` | Insurance Commissioner |
| `agriculture-commissioner` | Agriculture Commissioner |
| `superintendent` | State School Superintendent |
| `other_*` | Unrecognised RDH race code (e.g. `other_agrl` = unmatched agriculture-related code) |

#### Party canonical values

| Value | Party |
|-------|-------|
| `dem` | Democrat |
| `rep` | Republican |
| `lib` | Libertarian |
| `grn` | Green |
| `ind` | Independent |
| `other` | Other / write-in |

---

### `fdp.cvap`

Citizen Voting Age Population by geographic unit and ACS 5-year survey end year.
One row per `(geoid, year)`.

| Column | Type | Description |
|--------|------|-------------|
| `geoid` | TEXT | Geographic identifier — FK to `fdp.geography` |
| `geo_level` | TEXT | Level of this row (currently: `vtd`) |
| `state` | TEXT | State abbreviation |
| `year` | INT | ACS 5-year end year. `2024` = ACS 2020–2024 estimates. |
| `cvap_tot` | BIGINT | Total CVAP (all races) |
| `cvap_blk` | BIGINT | Black or African American alone or in combination |
| `cvap_hsp` | BIGINT | Hispanic or Latino (any race) |
| `cvap_wht` | BIGINT | White alone, non-Hispanic |
| `cvap_asn` | BIGINT | Asian alone or in combination |
| `cvap_ami` | BIGINT | American Indian or Alaska Native alone or in combination |
| `cvap_nhp` | BIGINT | Native Hawaiian or Other Pacific Islander alone or in combination |
| `cvap_oth` | BIGINT | All other (multiracial, other) |
| `source` | TEXT | `RDH \| derived` |
| `created_at` / `updated_at` / `update_count` / `loaded_by` | — | Audit columns |

**Primary key:** `(geoid, year)`

**Currently populated:** 2,698 Georgia VTDs, ACS 2024 (2020–2024 5-year estimates)

---

### `fdp.geo_crosswalk`

Maps geographic units across boundary systems — primarily political units
(precincts, districts) to Census units (blocks, VTDs). Also handles
Census-to-Census crosswalks across decennial vintages (2010 → 2020).

**Currently empty.** Defined now to lock the schema; populated when the
dasymetric disaggregation pipeline is built.

| Column | Type | Description |
|--------|------|-------------|
| `from_geoid` | TEXT | Source geographic unit |
| `to_geoid` | TEXT | Target geographic unit |
| `from_level` | TEXT | `geo_level` of `from_geoid` |
| `to_level` | TEXT | `geo_level` of `to_geoid` |
| `method` | TEXT | `exact \| centroid \| dasymetric \| areal_interpolation` |
| `weight` | NUMERIC(8,6) | Fractional overlap 0.0–1.0. For exact matches: always `1.0`. `SUM(weight)` over all `to_geoid` for a given `from_geoid` should equal `1.0`. |
| `vintage_year` | INT | Which year's boundaries both geoids belong to |
| audit cols | — | `created_at`, `updated_at`, `update_count`, `loaded_by` |

**Primary key:** `(from_geoid, to_geoid, vintage_year)`

---

### `fdp.population`

Decennial Census P.L. 94-171 demographic data at any geographic level.
Kept separate from `fdp.cvap` — different source (100% count vs. ACS sample),
different cadence (decennial vs. annual), different methodology.

**Currently empty.** Loaded by `fdp load-population` (future command).

| Column | Type | Description |
|--------|------|-------------|
| `geoid` | TEXT | Geographic identifier |
| `geo_level` | TEXT | Level of this row |
| `state` | TEXT | State abbreviation |
| `census_year` | INT | Decennial Census year: `2010` or `2020` |
| `pop_total` | BIGINT | Total population (P0010001) |
| `vap_total` | BIGINT | Total Voting Age Population 18+ (P0030001) |
| `vap_mod` | BIGINT | VAP minus persons in correctional facilities (P0040001 − P0050003). **Always use this as disaggregation weight**, not raw VAP. |
| `pop_white` / `pop_black` / `pop_hispanic` / `pop_asian` / `pop_ami` / `pop_nhp` / `pop_multi` | BIGINT | Population by race/ethnicity |
| `vap_white` / `vap_black` / `vap_hispanic` / `vap_asian` | BIGINT | VAP by race/ethnicity |
| `source` | TEXT | `Census \| derived` |
| audit cols | — | `created_at`, `updated_at`, `update_count`, `loaded_by` |

**Primary key:** `(geoid, census_year)`

---

### `fdp.ensemble_plans`

Redistricting ensemble plan assignments — one row per geographic unit per draw
per plan set. Join to `election_results` on `geoid` to score draws on partisan metrics.

**Currently empty.** Loaded by `fdp load-ensemble` (future command).

| Column | Type | Description |
|--------|------|-------------|
| `plan_id` | TEXT | Plan set identifier. Convention: `{state}_{chamber}_{census_year}_{method}_{n_draws}`. Example: `ga_congress_2020_alarm_5001` |
| `draw` | INT | Draw index (1-based). Draw 1 = enacted/reference plan. Draws 2..N = simulated. |
| `geoid` | TEXT | Geographic unit — FK to `fdp.geography` |
| `geo_level` | TEXT | Level of the geoid (typically `vtd`) |
| `state` | TEXT | State abbreviation |
| `district` | INT | District number assigned to this unit in this draw (1-indexed) |
| `chamber` | TEXT | `congress \| senate \| house` |
| audit cols | — | `created_at`, `updated_at`, `update_count`, `loaded_by` |

**Primary key:** `(plan_id, draw, geoid)`

---

## Views

Pre-joined analytical views — use these in Looker Studio, Tableau, or quick SQL queries.
All views filter on `geo_level = 'vtd'` to avoid double-counting when data exists at
multiple geographic levels.

### `fdp.v_election_2pv`

Two-party vote share per VTD per race. The primary view for choropleth maps and partisan analysis.

Key columns: `geoid`, `year`, `election_type`, `office`, `dem_votes`, `rep_votes`,
`lib_votes`, `other_votes`, `total_votes`, `dem_2pv`, `county_fips`, `geo_name`, `vap_mod`

`dem_2pv` = `dem_votes / (dem_votes + rep_votes) × 100`
Libertarian and third-party votes are tracked separately but excluded from the two-party denominator.

### `fdp.v_county_results`

County-level election results aggregated from VTD-level rows.

Key columns: `county_fips`, `county_name`, `state`, `year`, `election_type`, `office`, `party`, `votes`

### `fdp.v_statewide_results`

State totals per race. Primary validation tool — compare against Secretary of State
certified results to verify aggregation is correct.

Key columns: `state`, `year`, `election_type`, `office`, `party`, `candidates`, `votes`, `pct_of_total`

### `fdp.v_vtd_demographics`

VTD demographics using the most recent CVAP year available for each state. Includes
counts and percentages for each racial/ethnic group. Use for majority-minority district
analysis under Section 2 of the Voting Rights Act.

Key columns: `geoid`, `cvap_year`, `cvap_tot`, `cvap_blk`, `pct_blk`, `cvap_hsp`,
`pct_hsp`, `cvap_wht`, `pct_wht`, `cvap_asn`, `pct_asn`, `county_fips`, `vap_mod`

---

## GEOID Encoding

Census GEOIDs encode their own hierarchy in the string length:

| Length | Level | Example | Notes |
|--------|-------|---------|-------|
| 2 | State | `13` | Georgia |
| 5 | County | `13121` | Fulton County, GA |
| 11 | VTD or Tract | `13121000001` | Fulton Co VTD 000001 |
| 12 | Block Group | `131210001001` | |
| 15 | Census Block | `131210001001000` | |

For Census units, county rollup is always `LEFT(geoid, 5)`. No join required.

For **political units** (precincts, districts), this string-truncation trick
**does not apply** — use `fdp.geo_crosswalk` for cross-type joins.

---

## Key Relationships

```
fdp.geography (geoid, vintage_year)
    ↑ FK: geoid
    ├── fdp.election_results  (geoid, year, election_type, office, party, candidate)
    ├── fdp.cvap              (geoid, year)
    ├── fdp.population        (geoid, census_year)
    └── fdp.ensemble_plans    (plan_id, draw, geoid)

fdp.geo_crosswalk  (from_geoid, to_geoid, vintage_year)
    Used for political→census joins when boundaries don't align
```

---

## Audit Columns

Every table has these four columns:

| Column | Behaviour |
|--------|-----------|
| `created_at` | Set once at INSERT. Never overwritten by subsequent UPSERTs. |
| `updated_at` | Bumped to `NOW()` on every UPDATE by the `fdp.touch_row()` trigger. |
| `update_count` | Incremented by the trigger on every UPDATE. A value > 0 on a supposedly write-once dataset signals unexpected changes. |
| `loaded_by` | Set by the CLI command (e.g. `fdp load-pg`). Not overwritten after first insert. |

---

## Common SQL Patterns

```sql
-- Statewide 2022 results (use the validation view)
SELECT * FROM fdp.v_statewide_results WHERE year = 2022;

-- 2022 Governor two-party vote share by VTD
SELECT geoid, dem_2pv, rep_votes, dem_votes
FROM fdp.v_election_2pv
WHERE year = 2022 AND office = 'governor'
ORDER BY dem_2pv DESC;

-- County-level 2024 president results
SELECT county_fips, party, votes
FROM fdp.v_county_results
WHERE year = 2024 AND office = 'president'
ORDER BY county_fips, votes DESC;

-- VTDs where Black CVAP > 50% (Section 2 analysis)
SELECT geoid, pct_blk, cvap_tot, county_fips
FROM fdp.v_vtd_demographics
WHERE pct_blk > 50
ORDER BY pct_blk DESC;

-- Join election results to demographics
SELECT er.geoid, er.office, er.party, er.votes,
       c.cvap_tot, c.cvap_blk,
       ROUND(100.0 * c.cvap_blk::numeric / NULLIF(c.cvap_tot, 0), 1) AS pct_blk
FROM fdp.election_results er
JOIN fdp.cvap c ON c.geoid = er.geoid AND c.year = 2024
WHERE er.year = 2022
  AND er.office = 'governor'
  AND er.geo_level = 'vtd';

-- All races in a specific county (Fulton = 13121)
SELECT year, office, party, SUM(votes) AS votes
FROM fdp.election_results
WHERE LEFT(geoid, 5) = '13121'
  AND geo_level = 'vtd'
GROUP BY year, office, party
ORDER BY year, office, votes DESC;
```

---

## Loading Data

```bash
# 1. Apply / refresh schema (idempotent — safe to re-run)
fdp init-db

# 2. Ingest raw source files
fdp ingest election --year 2022 --state GA --file path/to/ga_2022_gen_2020_blocks.zip
fdp ingest cvap     --year 2024 --state GA --file path/to/ga_cvap_2024_2020_b_csv.zip

# 3. Aggregate blocks → VTDs
fdp aggregate election --year 2022 --state GA
fdp aggregate cvap     --year 2024 --state GA

# 4. Load into PostgreSQL CDM
fdp load-pg --state GA

# 5. Validate
SELECT * FROM fdp.v_statewide_results WHERE year = 2022;
```

---

## Connection Details (local development)

```
Host:     localhost
Port:     5432
Database: fdp
User:     fdp
Password: fdp_local
URL:      postgresql://fdp:fdp_local@localhost:5432/fdp
```

Started with: `docker compose up -d postgres`
