-- ============================================================================
-- Semantic layer views for Postgres.
-- These mirror the DuckDB semantic views in sql/semantic/*.sql and expose the
-- CDM catalog tables and raw fdensemble VTD data in a dashboard-friendly shape.
-- ============================================================================

-- Safe integer cast used when parsing year prefixes out of era tags.
CREATE OR REPLACE FUNCTION cdm.safe_cast_int(input TEXT)
RETURNS INTEGER AS $$
BEGIN
    RETURN input::INTEGER;
EXCEPTION WHEN OTHERS THEN
    RETURN NULL;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION cdm.safe_cast_int(TEXT) IS
    'Cast text to integer, returning NULL on failure instead of raising.';


-- ============================================================================
-- Full semantic views
-- ============================================================================

CREATE OR REPLACE VIEW semantic.v_redistricting_waves AS
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
FROM cdm.cdm_redistricting_waves;

COMMENT ON VIEW semantic.v_redistricting_waves IS
    'Historical redistricting waves with a human-readable party_label.';


CREATE OR REPLACE VIEW semantic.v_redistricting_chamber_changes AS
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
FROM cdm.cdm_wave_chambers c
JOIN semantic.v_redistricting_waves w
    ON w.year = c.wave_year;

COMMENT ON VIEW semantic.v_redistricting_chamber_changes IS
    'Per-chamber redistricting changes joined to wave metadata.';


CREATE OR REPLACE VIEW semantic.v_boundary_files AS
SELECT
    file_id,
    chamber,
    filename,
    label,
    era,
    cdm.safe_cast_int(substr(era, 1, 4)) AS era_year,
    CASE
        WHEN chamber = 'reference' THEN 'reference'
        WHEN era LIKE '%enacted%' THEN 'enacted'
        WHEN era LIKE '%remedy%' THEN 'remedy'
        WHEN era LIKE '%proposed%' THEN 'proposed'
        ELSE 'other'
    END AS plan_status,
    in_app_config,
    file_size_kb
FROM cdm.cdm_boundary_catalog;

COMMENT ON VIEW semantic.v_boundary_files IS
    'Boundary file inventory with parsed era year and plan status.';


CREATE OR REPLACE VIEW semantic.v_plan_summary AS
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
FROM cdm.cdm_plan_catalog p
LEFT JOIN semantic.v_boundary_files b
    ON b.chamber = p.chamber
   AND b.filename = split_part(p.filename, '/', 3);

COMMENT ON VIEW semantic.v_plan_summary IS
    'Plans joined to their boundary files and status tags.';


CREATE OR REPLACE VIEW semantic.v_district_demographics AS
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
FROM semantic.raw_district_demographics;

COMMENT ON VIEW semantic.v_district_demographics IS
    'District-level socioeconomic metrics for enacted GA plans.';


CREATE OR REPLACE VIEW semantic.v_vtd_demographics AS
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
    ROUND((100.0 * pop_black / NULLIF(pop, 0))::numeric, 1) AS pct_pop_black,
    ROUND((100.0 * pop_hisp / NULLIF(pop, 0))::numeric, 1) AS pct_pop_hisp,
    ROUND((100.0 * pop_white / NULLIF(pop, 0))::numeric, 1) AS pct_pop_white,
    ROUND((100.0 * vap_black / NULLIF(vap, 0))::numeric, 1) AS pct_vap_black,
    ROUND((100.0 * vap_hisp / NULLIF(vap, 0))::numeric, 1) AS pct_vap_hisp,
    ROUND((100.0 * vap_white / NULLIF(vap, 0))::numeric, 1) AS pct_vap_white
FROM semantic.raw_vtd_demographics;

COMMENT ON VIEW semantic.v_vtd_demographics IS
    'VTD-level decennial Census demographics with racial percentage columns.';


CREATE OR REPLACE VIEW semantic.v_vtd_composite_lean AS
SELECT
    geoid20 AS geoid,
    LEFT(geoid20, 5) AS county_fips,
    ROUND((100.0 * composite_dem_pct)::numeric, 2) AS dem_pct,
    ROUND((100.0 * composite_rep_pct)::numeric, 2) AS rep_pct,
    ROUND((100.0 * composite_other_pct)::numeric, 2) AS other_pct,
    ROUND((100.0 * composite_dem_2pv)::numeric, 2) AS dem_2pv,
    ROUND((100.0 * (1.0 - composite_dem_2pv))::numeric, 2) AS rep_2pv,
    ROUND((100.0 * dem_pct_2018_gov)::numeric, 2) AS dem_pct_2018_gov,
    ROUND((100.0 * dem_pct_2020_pres)::numeric, 2) AS dem_pct_2020_pres,
    ROUND((100.0 * dem_pct_2021_war_runoff)::numeric, 2) AS dem_pct_2021_war_runoff,
    ROUND((100.0 * dem_pct_2022_gov)::numeric, 2) AS dem_pct_2022_gov,
    ROUND((100.0 * dem_pct_2022_uss)::numeric, 2) AS dem_pct_2022_uss,
    ROUND((100.0 * dem_pct_2024_pres)::numeric, 2) AS dem_pct_2024_pres,
    vap_mod AS vap_mod,
    bvap_tot,
    bvap_blk,
    bvap_wht,
    bvap_hsp,
    bvap_asn,
    bvap_coalition,
    actual_dem_votes,
    actual_total_votes,
    centroid_lat,
    centroid_lon
FROM semantic.raw_vtd_composite_lean;

COMMENT ON VIEW semantic.v_vtd_composite_lean IS
    'VTD-level composite partisan lean and VAP counts with percentages scaled to 0-100.';


-- ============================================================================
-- Compact semantic views (smaller column sets for narrow contexts)
-- ============================================================================

CREATE OR REPLACE VIEW semantic.v_redistricting_waves_compact AS
SELECT
    year,
    label,
    CASE party
        WHEN 'R' THEN 'Republican'
        WHEN 'D' THEN 'Democratic'
        WHEN 'both' THEN 'Bipartisan'
    END AS party_label,
    total_districts_changed,
    reason
FROM cdm.cdm_redistricting_waves;

COMMENT ON VIEW semantic.v_redistricting_waves_compact IS
    'Compact redistricting wave summary.';


CREATE OR REPLACE VIEW semantic.v_redistricting_chamber_changes_compact AS
SELECT
    c.wave_year AS year,
    c.chamber,
    c.district_count,
    c.all_districts
FROM cdm.cdm_wave_chambers c;

COMMENT ON VIEW semantic.v_redistricting_chamber_changes_compact IS
    'Compact per-chamber redistricting changes.';


CREATE OR REPLACE VIEW semantic.v_boundary_files_compact AS
SELECT
    file_id,
    chamber,
    cdm.safe_cast_int(substr(era, 1, 4)) AS era_year,
    CASE
        WHEN chamber = 'reference' THEN 'reference'
        WHEN era LIKE '%enacted%' THEN 'enacted'
        WHEN era LIKE '%remedy%' THEN 'remedy'
        WHEN era LIKE '%proposed%' THEN 'proposed'
        ELSE 'other'
    END AS plan_status
FROM cdm.cdm_boundary_catalog;

COMMENT ON VIEW semantic.v_boundary_files_compact IS
    'Compact boundary file inventory.';


CREATE OR REPLACE VIEW semantic.v_plan_summary_compact AS
SELECT
    p.plan_id,
    split_part(p.plan_id, '/', 1) AS app_name,
    p.chamber,
    p.label AS plan_label,
    b.file_id,
    b.plan_status,
    b.era_year
FROM cdm.cdm_plan_catalog p
LEFT JOIN semantic.v_boundary_files b
    ON b.chamber = p.chamber
   AND b.filename = split_part(p.filename, '/', 3);

COMMENT ON VIEW semantic.v_plan_summary_compact IS
    'Compact plan catalog joined to boundary status.';


CREATE OR REPLACE VIEW semantic.v_district_demographics_compact AS
SELECT
    chamber,
    district,
    median_income,
    pct_poverty,
    pct_bachelors_plus
FROM semantic.raw_district_demographics;

COMMENT ON VIEW semantic.v_district_demographics_compact IS
    'Compact district socioeconomic summary.';


CREATE OR REPLACE VIEW semantic.v_vtd_demographics_compact AS
SELECT
    geoid,
    LEFT(geoid, 5) AS county_fips,
    pop AS total_pop,
    vap AS total_vap,
    ROUND((100.0 * vap_black / NULLIF(vap, 0))::numeric, 1) AS pct_vap_black,
    ROUND((100.0 * vap_hisp / NULLIF(vap, 0))::numeric, 1) AS pct_vap_hisp,
    ROUND((100.0 * vap_white / NULLIF(vap, 0))::numeric, 1) AS pct_vap_white
FROM semantic.raw_vtd_demographics;

COMMENT ON VIEW semantic.v_vtd_demographics_compact IS
    'Compact VTD demographic summary.';


CREATE OR REPLACE VIEW semantic.v_vtd_composite_lean_compact AS
SELECT
    geoid20 AS geoid,
    LEFT(geoid20, 5) AS county_fips,
    ROUND((100.0 * composite_dem_pct)::numeric, 2) AS dem_pct,
    ROUND((100.0 * composite_rep_pct)::numeric, 2) AS rep_pct,
    ROUND((100.0 * composite_dem_2pv)::numeric, 2) AS dem_2pv,
    ROUND((100.0 * (1.0 - composite_dem_2pv))::numeric, 2) AS rep_2pv
FROM semantic.raw_vtd_composite_lean;

COMMENT ON VIEW semantic.v_vtd_composite_lean_compact IS
    'Compact VTD partisan lean summary.';
