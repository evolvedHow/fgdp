-- Semantic layer: redistricting, demographic, and composite-partisan views
-- Target: data/semantic.duckdb
-- Sources:
--   * cdm.main.* (attached read-only as "cdm")
--   * raw_* tables loaded by build.py from fdensemble Parquet files and district JSONs
-- Build:  fdp/sql/semantic/build.py

-- ============================================================================
-- Redistricting history
-- ============================================================================

CREATE OR REPLACE VIEW v_redistricting_waves AS
SELECT
    year,
    end_year,
    display_year,
    label,
    party,
    CASE party
        WHEN 'R' THEN 'Republican'
        WHEN 'D' THEN 'Democratic'
        WHEN 'both' THEN 'Bipartisan'
    END AS party_label,
    end_year IS NOT NULL AS spans_two_years,
    total_districts_changed,
    reason,
    legal_context,
    election_result,
    source,
    author
FROM cdm.main.cdm_redistricting_waves;

CREATE OR REPLACE VIEW v_redistricting_chamber_changes AS
SELECT
    w.year,
    w.display_year,
    w.label AS wave_label,
    w.party,
    w.party_label,
    c.chamber,
    c.district_count,
    c.all_districts,
    c.districts_known,
    c.notes
FROM cdm.main.cdm_wave_chambers c
JOIN v_redistricting_waves w
    ON w.year = c.wave_year;

-- ============================================================================
-- Boundary / plan catalog
-- ============================================================================

CREATE OR REPLACE VIEW v_boundary_files AS
SELECT
    file_id,
    chamber,
    filename,
    label,
    era,
    try_cast(substr(era, 1, 4) AS INTEGER) AS era_year,
    CASE
        WHEN chamber = 'reference' THEN 'reference'
        WHEN era LIKE '%enacted%' THEN 'enacted'
        WHEN era LIKE '%remedy%' THEN 'remedy'
        WHEN era LIKE '%proposed%' THEN 'proposed'
        ELSE 'other'
    END AS plan_status,
    in_app_config,
    file_size_kb
FROM cdm.main.cdm_boundary_catalog;

CREATE OR REPLACE VIEW v_plan_summary AS
SELECT
    p.plan_id,
    split_part(p.plan_id, '/', 1) AS app_name,
    p.app,
    p.chamber,
    p.label AS plan_label,
    p.filename,
    b.file_id,
    b.label AS boundary_label,
    b.plan_status,
    b.era_year,
    b.in_app_config
FROM cdm.main.cdm_plan_catalog p
LEFT JOIN v_boundary_files b
    ON b.chamber = p.chamber
   AND b.filename = split_part(p.filename, '/', 3);

-- ============================================================================
-- District-level demographics from JSON files (congress / house / senate)
-- ============================================================================

CREATE OR REPLACE VIEW v_district_demographics AS
SELECT
    chamber,
    district,
    median_income,
    pct_poverty,
    poverty_count,
    pct_bachelors_plus,
    bachelors_plus_count,
    pct_male,
    pct_female,
    pct_married_family,
    married_hh_count,
    pct_single_parent,
    single_parent_count,
    pct_no_vehicle,
    no_vehicle_count,
    pct_uninsured,
    uninsured_count,
    pct_unemployed,
    unemployed_count,
    labor_force_count
FROM raw_district_demographics;

-- ============================================================================
-- VTD-level demographics and composite partisan lean (from fdensemble)
-- ============================================================================

CREATE OR REPLACE VIEW v_vtd_demographics AS
SELECT
    geoid,
    LEFT(geoid, 5) AS county_fips,
    pop AS total_pop,
    vap AS total_vap,
    pop_black,
    pop_hisp,
    pop_white,
    pop_aian,
    pop_asian,
    vap_black,
    vap_hisp,
    vap_white,
    vap_aian,
    vap_asian,
    ROUND(100.0 * pop_black / NULLIF(pop, 0), 1) AS pct_pop_black,
    ROUND(100.0 * pop_hisp / NULLIF(pop, 0), 1) AS pct_pop_hisp,
    ROUND(100.0 * pop_white / NULLIF(pop, 0), 1) AS pct_pop_white,
    ROUND(100.0 * vap_black / NULLIF(vap, 0), 1) AS pct_vap_black,
    ROUND(100.0 * vap_hisp / NULLIF(vap, 0), 1) AS pct_vap_hisp,
    ROUND(100.0 * vap_white / NULLIF(vap, 0), 1) AS pct_vap_white
FROM raw_vtd_demographics;

CREATE OR REPLACE VIEW v_vtd_composite_lean AS
SELECT
    GEOID20 AS geoid,
    LEFT(GEOID20, 5) AS county_fips,
    ROUND(100.0 * composite_dem_pct, 2) AS dem_pct,
    ROUND(100.0 * composite_rep_pct, 2) AS rep_pct,
    ROUND(100.0 * composite_other_pct, 2) AS other_pct,
    ROUND(100.0 * composite_dem_2pv, 2) AS dem_2pv,
    ROUND(100.0 * (1.0 - composite_dem_2pv), 2) AS rep_2pv,
    ROUND(100.0 * dem_pct_2018_gov, 2) AS dem_pct_2018_gov,
    ROUND(100.0 * dem_pct_2020_pres, 2) AS dem_pct_2020_pres,
    ROUND(100.0 * dem_pct_2021_war_runoff, 2) AS dem_pct_2021_war_runoff,
    ROUND(100.0 * dem_pct_2022_gov, 2) AS dem_pct_2022_gov,
    ROUND(100.0 * dem_pct_2022_uss, 2) AS dem_pct_2022_uss,
    ROUND(100.0 * dem_pct_2024_pres, 2) AS dem_pct_2024_pres,
    VAP_MOD AS vap_mod,
    bvap_tot,
    bvap_blk,
    bvap_wht,
    bvap_hsp,
    bvap_asn,
    bvap_coalition,
    centroid_lat,
    centroid_lon
FROM raw_vtd_composite_lean;
