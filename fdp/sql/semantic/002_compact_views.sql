-- Compact semantic views for small local LLMs (e.g. gemma-3-1B-it).
-- These expose only the columns most useful for natural-language questions,
-- keeping WrenAI prompts short enough to fit in a ~4-8K context window.
-- The full views in 001_redistricting_views.sql remain available for larger models.

CREATE OR REPLACE VIEW v_redistricting_waves_compact AS
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
FROM cdm.main.cdm_redistricting_waves;

CREATE OR REPLACE VIEW v_redistricting_chamber_changes_compact AS
SELECT
    c.wave_year AS year,
    c.chamber,
    c.district_count,
    c.all_districts
FROM cdm.main.cdm_wave_chambers c;

CREATE OR REPLACE VIEW v_boundary_files_compact AS
SELECT
    file_id,
    chamber,
    try_cast(substr(era, 1, 4) AS INTEGER) AS era_year,
    CASE
        WHEN chamber = 'reference' THEN 'reference'
        WHEN era LIKE '%enacted%' THEN 'enacted'
        WHEN era LIKE '%remedy%' THEN 'remedy'
        WHEN era LIKE '%proposed%' THEN 'proposed'
        ELSE 'other'
    END AS plan_status
FROM cdm.main.cdm_boundary_catalog;

CREATE OR REPLACE VIEW v_plan_summary_compact AS
SELECT
    p.plan_id,
    split_part(p.plan_id, '/', 1) AS app_name,
    p.chamber,
    p.label AS plan_label,
    b.file_id,
    b.plan_status,
    b.era_year
FROM cdm.main.cdm_plan_catalog p
LEFT JOIN v_boundary_files b
    ON b.chamber = p.chamber
   AND b.filename = split_part(p.filename, '/', 3);

CREATE OR REPLACE VIEW v_district_demographics_compact AS
SELECT
    chamber,
    district,
    median_income,
    pct_poverty,
    pct_bachelors_plus
FROM raw_district_demographics;

CREATE OR REPLACE VIEW v_vtd_demographics_compact AS
SELECT
    geoid,
    LEFT(geoid, 5) AS county_fips,
    pop AS total_pop,
    vap AS total_vap,
    ROUND(100.0 * vap_black / NULLIF(vap, 0), 1) AS pct_vap_black,
    ROUND(100.0 * vap_hisp / NULLIF(vap, 0), 1) AS pct_vap_hisp,
    ROUND(100.0 * vap_white / NULLIF(vap, 0), 1) AS pct_vap_white
FROM raw_vtd_demographics;

CREATE OR REPLACE VIEW v_vtd_composite_lean_compact AS
SELECT
    GEOID20 AS geoid,
    LEFT(GEOID20, 5) AS county_fips,
    ROUND(100.0 * composite_dem_pct, 2) AS dem_pct,
    ROUND(100.0 * composite_rep_pct, 2) AS rep_pct,
    ROUND(100.0 * composite_dem_2pv, 2) AS dem_2pv,
    ROUND(100.0 * (1.0 - composite_dem_2pv), 2) AS rep_2pv
FROM raw_vtd_composite_lean;
