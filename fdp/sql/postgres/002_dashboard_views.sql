-- ============================================================================
-- Dashboard-oriented views and materialized views for Data Studio / Looker.
--
-- Materialized views (mv_*) pre-compute joins/aggregations for fast charting.
-- Regular views (v_*) are simple wrappers or filtered slices.
--
-- Run scripts/cdm_to_postgres.py to load data and rebuild everything.
-- ============================================================================

-- Drop dashboard materialized views (CASCADE so dependent views rebuild cleanly).
DROP MATERIALIZED VIEW IF EXISTS dashboard.mv_county_summary CASCADE;
DROP MATERIALIZED VIEW IF EXISTS dashboard.mv_county_election_trends CASCADE;
DROP MATERIALIZED VIEW IF EXISTS dashboard.mv_vtd_partisan_demographics CASCADE;


-- ============================================================================
-- County-level summary: demographics + partisan lean
-- ============================================================================
CREATE MATERIALIZED VIEW dashboard.mv_county_summary AS
WITH vtd AS (
    SELECT
        d.geoid,
        LEFT(d.geoid, 5) AS county_fips,
        d.pop,
        d.vap,
        d.pop_black, d.pop_hisp, d.pop_white, d.pop_aian, d.pop_asian,
        d.vap_black, d.vap_hisp, d.vap_white, d.vap_aian, d.vap_asian,
        l.composite_dem_pct,
        l.composite_rep_pct,
        l.composite_dem_2pv,
        l.composite_other_pct,
        l.actual_dem_votes,
        l.actual_total_votes,
        l.vap_mod,
        l.centroid_lat,
        l.centroid_lon
    FROM semantic.raw_vtd_demographics d
    JOIN semantic.raw_vtd_composite_lean l
        ON l.geoid20 = d.geoid
)
SELECT
    county_fips,
    COUNT(*) AS n_vtds,
    SUM(pop) AS total_pop,
    SUM(vap) AS total_vap,
    SUM(pop_black) AS pop_black,
    SUM(pop_hisp) AS pop_hisp,
    SUM(pop_white) AS pop_white,
    SUM(pop_aian) AS pop_aian,
    SUM(pop_asian) AS pop_asian,
    SUM(vap_black) AS vap_black,
    SUM(vap_hisp) AS vap_hisp,
    SUM(vap_white) AS vap_white,
    SUM(vap_aian) AS vap_aian,
    SUM(vap_asian) AS vap_asian,
    ROUND((100.0 * SUM(pop_black) / NULLIF(SUM(pop), 0))::numeric, 2) AS pct_pop_black,
    ROUND((100.0 * SUM(pop_hisp) / NULLIF(SUM(pop), 0))::numeric, 2) AS pct_pop_hisp,
    ROUND((100.0 * SUM(pop_white) / NULLIF(SUM(pop), 0))::numeric, 2) AS pct_pop_white,
    ROUND((100.0 * SUM(vap_black) / NULLIF(SUM(vap), 0))::numeric, 2) AS pct_vap_black,
    ROUND((100.0 * SUM(vap_hisp) / NULLIF(SUM(vap), 0))::numeric, 2) AS pct_vap_hisp,
    ROUND((100.0 * SUM(vap_white) / NULLIF(SUM(vap), 0))::numeric, 2) AS pct_vap_white,
    ROUND((100.0 * SUM(actual_dem_votes) / NULLIF(SUM(actual_total_votes), 0))::numeric, 2) AS dem_vote_pct,
    ROUND((100.0 * SUM(composite_dem_pct * vap_mod) / NULLIF(SUM(vap_mod), 0))::numeric, 4) AS wtd_dem_pct,
    ROUND((100.0 * SUM(composite_rep_pct * vap_mod) / NULLIF(SUM(vap_mod), 0))::numeric, 4) AS wtd_rep_pct,
    ROUND((100.0 * SUM(composite_dem_2pv * vap_mod) / NULLIF(SUM(vap_mod), 0))::numeric, 4) AS wtd_dem_2pv,
    ROUND((AVG(centroid_lat))::numeric, 6) AS centroid_lat,
    ROUND((AVG(centroid_lon))::numeric, 6) AS centroid_lon
FROM vtd
GROUP BY county_fips;

CREATE INDEX idx_mv_county_summary_fips ON dashboard.mv_county_summary (county_fips);
CREATE INDEX idx_mv_county_summary_pop ON dashboard.mv_county_summary (total_pop);
CREATE INDEX idx_mv_county_summary_dem2pv ON dashboard.mv_county_summary (wtd_dem_2pv);
CREATE UNIQUE INDEX idx_mv_county_summary_u ON dashboard.mv_county_summary (county_fips);

COMMENT ON MATERIALIZED VIEW dashboard.mv_county_summary IS
    'County-level rollup of VTD demographics and composite partisan lean. '
    'Use for county choropleths, bar charts, and scatter plots in Data Studio.';

COMMENT ON COLUMN dashboard.mv_county_summary.county_fips IS '5-character county FIPS code.';
COMMENT ON COLUMN dashboard.mv_county_summary.n_vtds IS 'Number of VTDs in the county.';
COMMENT ON COLUMN dashboard.mv_county_summary.total_pop IS 'Total county population.';
COMMENT ON COLUMN dashboard.mv_county_summary.total_vap IS 'Total county voting-age population.';
COMMENT ON COLUMN dashboard.mv_county_summary.pop_black IS 'County Black population.';
COMMENT ON COLUMN dashboard.mv_county_summary.pop_hisp IS 'County Hispanic population.';
COMMENT ON COLUMN dashboard.mv_county_summary.pop_white IS 'County White population.';
COMMENT ON COLUMN dashboard.mv_county_summary.vap_black IS 'County Black VAP.';
COMMENT ON COLUMN dashboard.mv_county_summary.vap_hisp IS 'County Hispanic VAP.';
COMMENT ON COLUMN dashboard.mv_county_summary.vap_white IS 'County White VAP.';
COMMENT ON COLUMN dashboard.mv_county_summary.pct_pop_black IS 'Black population share (%).';
COMMENT ON COLUMN dashboard.mv_county_summary.pct_pop_hisp IS 'Hispanic population share (%).';
COMMENT ON COLUMN dashboard.mv_county_summary.pct_pop_white IS 'White population share (%).';
COMMENT ON COLUMN dashboard.mv_county_summary.pct_vap_black IS 'Black VAP share (%).';
COMMENT ON COLUMN dashboard.mv_county_summary.pct_vap_hisp IS 'Hispanic VAP share (%).';
COMMENT ON COLUMN dashboard.mv_county_summary.pct_vap_white IS 'White VAP share (%).';
COMMENT ON COLUMN dashboard.mv_county_summary.dem_vote_pct IS 'Democratic vote share from summed actual votes (%).';
COMMENT ON COLUMN dashboard.mv_county_summary.wtd_dem_pct IS 'vap_mod-weighted Democratic vote share (%).';
COMMENT ON COLUMN dashboard.mv_county_summary.wtd_rep_pct IS 'vap_mod-weighted Republican vote share (%).';
COMMENT ON COLUMN dashboard.mv_county_summary.wtd_dem_2pv IS 'vap_mod-weighted Democratic two-party vote share (%).';
COMMENT ON COLUMN dashboard.mv_county_summary.centroid_lat IS 'Average VTD centroid latitude.';
COMMENT ON COLUMN dashboard.mv_county_summary.centroid_lon IS 'Average VTD centroid longitude.';


-- ============================================================================
-- County-level election trends (long format for line charts)
-- ============================================================================
CREATE MATERIALIZED VIEW dashboard.mv_county_election_trends AS
SELECT
    LEFT(geoid20, 5) AS county_fips,
    '2018 Governor' AS election,
    ROUND((100.0 * SUM(dem_pct_2018_gov * vap_mod) / NULLIF(SUM(vap_mod), 0))::numeric, 2) AS dem_pct
FROM semantic.raw_vtd_composite_lean
GROUP BY LEFT(geoid20, 5)
UNION ALL
SELECT
    LEFT(geoid20, 5) AS county_fips,
    '2020 President' AS election,
    ROUND((100.0 * SUM(dem_pct_2020_pres * vap_mod) / NULLIF(SUM(vap_mod), 0))::numeric, 2) AS dem_pct
FROM semantic.raw_vtd_composite_lean
GROUP BY LEFT(geoid20, 5)
UNION ALL
SELECT
    LEFT(geoid20, 5) AS county_fips,
    '2021 Warnock Runoff' AS election,
    ROUND((100.0 * SUM(dem_pct_2021_war_runoff * vap_mod) / NULLIF(SUM(vap_mod), 0))::numeric, 2) AS dem_pct
FROM semantic.raw_vtd_composite_lean
GROUP BY LEFT(geoid20, 5)
UNION ALL
SELECT
    LEFT(geoid20, 5) AS county_fips,
    '2022 Governor' AS election,
    ROUND((100.0 * SUM(dem_pct_2022_gov * vap_mod) / NULLIF(SUM(vap_mod), 0))::numeric, 2) AS dem_pct
FROM semantic.raw_vtd_composite_lean
GROUP BY LEFT(geoid20, 5)
UNION ALL
SELECT
    LEFT(geoid20, 5) AS county_fips,
    '2022 U.S. Senate' AS election,
    ROUND((100.0 * SUM(dem_pct_2022_uss * vap_mod) / NULLIF(SUM(vap_mod), 0))::numeric, 2) AS dem_pct
FROM semantic.raw_vtd_composite_lean
GROUP BY LEFT(geoid20, 5)
UNION ALL
SELECT
    LEFT(geoid20, 5) AS county_fips,
    '2024 President' AS election,
    ROUND((100.0 * SUM(dem_pct_2024_pres * vap_mod) / NULLIF(SUM(vap_mod), 0))::numeric, 2) AS dem_pct
FROM semantic.raw_vtd_composite_lean
GROUP BY LEFT(geoid20, 5);

CREATE INDEX idx_mv_county_trends_fips ON dashboard.mv_county_election_trends (county_fips);
CREATE INDEX idx_mv_county_trends_election ON dashboard.mv_county_election_trends (election);
CREATE UNIQUE INDEX idx_mv_county_trends_u ON dashboard.mv_county_election_trends (county_fips, election);

COMMENT ON MATERIALIZED VIEW dashboard.mv_county_election_trends IS
    'Long-format county-level Democratic vote share by election, weighted by vap_mod. '
    'Ideal for line charts and slope graphs in Data Studio.';

COMMENT ON COLUMN dashboard.mv_county_election_trends.county_fips IS '5-character county FIPS code.';
COMMENT ON COLUMN dashboard.mv_county_election_trends.election IS 'Election race label.';
COMMENT ON COLUMN dashboard.mv_county_election_trends.dem_pct IS 'Democratic vote share for that race (%).';


-- ============================================================================
-- VTD-level partisan + demographics (one row per VTD)
-- ============================================================================
CREATE MATERIALIZED VIEW dashboard.mv_vtd_partisan_demographics AS
SELECT
    d.geoid,
    LEFT(d.geoid, 5) AS county_fips,
    d.pop AS total_pop,
    d.vap AS total_vap,
    d.pop_black,
    d.pop_hisp,
    d.pop_white,
    d.pop_aian,
    d.pop_asian,
    d.vap_black,
    d.vap_hisp,
    d.vap_white,
    d.vap_aian,
    d.vap_asian,
    ROUND((100.0 * d.pop_black / NULLIF(d.pop, 0))::numeric, 2) AS pct_pop_black,
    ROUND((100.0 * d.pop_hisp / NULLIF(d.pop, 0))::numeric, 2) AS pct_pop_hisp,
    ROUND((100.0 * d.pop_white / NULLIF(d.pop, 0))::numeric, 2) AS pct_pop_white,
    ROUND((100.0 * d.vap_black / NULLIF(d.vap, 0))::numeric, 2) AS pct_vap_black,
    ROUND((100.0 * d.vap_hisp / NULLIF(d.vap, 0))::numeric, 2) AS pct_vap_hisp,
    ROUND((100.0 * d.vap_white / NULLIF(d.vap, 0))::numeric, 2) AS pct_vap_white,
    ROUND((100.0 * l.composite_dem_pct)::numeric, 2) AS dem_pct,
    ROUND((100.0 * l.composite_rep_pct)::numeric, 2) AS rep_pct,
    ROUND((100.0 * l.composite_other_pct)::numeric, 2) AS other_pct,
    ROUND((100.0 * l.composite_dem_2pv)::numeric, 2) AS dem_2pv,
    ROUND((100.0 * (1.0 - l.composite_dem_2pv))::numeric, 2) AS rep_2pv,
    l.vap_mod AS vap_mod,
    l.bvap_tot,
    l.bvap_blk,
    l.bvap_wht,
    l.bvap_hsp,
    l.bvap_asn,
    l.bvap_coalition,
    l.actual_dem_votes,
    l.actual_total_votes,
    ROUND((100.0 * l.actual_dem_votes / NULLIF(l.actual_total_votes, 0))::numeric, 2) AS actual_dem_pct,
    ROUND((ABS(l.composite_dem_2pv - 0.5) * 200.0)::numeric, 2) AS win_margin_pct,
    (ABS(l.composite_dem_2pv - 0.5) * 2.0 <= 0.07) AS is_competitive_7,
    (ABS(l.composite_dem_2pv - 0.5) * 2.0 <= 0.10) AS is_competitive_10,
    CASE
        WHEN d.pop > 0
             AND (d.pop_black + d.pop_hisp + d.pop_aian + d.pop_asian)::NUMERIC / d.pop > 0.5
        THEN TRUE ELSE FALSE
    END AS majority_minority_pop,
    CASE
        WHEN d.vap > 0
             AND (d.vap_black + d.vap_hisp + d.vap_aian + d.vap_asian)::NUMERIC / d.vap > 0.5
        THEN TRUE ELSE FALSE
    END AS majority_minority_vap,
    l.centroid_lat,
    l.centroid_lon
FROM semantic.raw_vtd_demographics d
JOIN semantic.raw_vtd_composite_lean l
    ON l.geoid20 = d.geoid;

CREATE INDEX idx_mv_vtd_pd_geoid ON dashboard.mv_vtd_partisan_demographics (geoid);
CREATE INDEX idx_mv_vtd_pd_county ON dashboard.mv_vtd_partisan_demographics (county_fips);
CREATE INDEX idx_mv_vtd_pd_dem2pv ON dashboard.mv_vtd_partisan_demographics (dem_2pv);
CREATE INDEX idx_mv_vtd_pd_competitive ON dashboard.mv_vtd_partisan_demographics (is_competitive_7);
CREATE UNIQUE INDEX idx_mv_vtd_pd_u ON dashboard.mv_vtd_partisan_demographics (geoid);

COMMENT ON MATERIALIZED VIEW dashboard.mv_vtd_partisan_demographics IS
    'One row per VTD with decennial Census demographics, composite partisan lean, '
    'competitiveness flags, and majority-minority flags. '
    'Use for point maps, scatter plots, and drill-through tables.';

COMMENT ON COLUMN dashboard.mv_vtd_partisan_demographics.geoid IS '2020 Census VTD GEOID.';
COMMENT ON COLUMN dashboard.mv_vtd_partisan_demographics.county_fips IS '5-character county FIPS.';
COMMENT ON COLUMN dashboard.mv_vtd_partisan_demographics.total_pop IS 'VTD total population.';
COMMENT ON COLUMN dashboard.mv_vtd_partisan_demographics.total_vap IS 'VTD total voting-age population.';
COMMENT ON COLUMN dashboard.mv_vtd_partisan_demographics.dem_pct IS 'Composite Democratic vote share (%).';
COMMENT ON COLUMN dashboard.mv_vtd_partisan_demographics.rep_pct IS 'Composite Republican vote share (%).';
COMMENT ON COLUMN dashboard.mv_vtd_partisan_demographics.dem_2pv IS 'Composite Democratic two-party vote share (%).';
COMMENT ON COLUMN dashboard.mv_vtd_partisan_demographics.rep_2pv IS 'Composite Republican two-party vote share (%).';
COMMENT ON COLUMN dashboard.mv_vtd_partisan_demographics.win_margin_pct IS 'Two-party winning margin (% points).';
COMMENT ON COLUMN dashboard.mv_vtd_partisan_demographics.is_competitive_7 IS 'True when two-party margin <= 7%.';
COMMENT ON COLUMN dashboard.mv_vtd_partisan_demographics.is_competitive_10 IS 'True when two-party margin <= 10%.';
COMMENT ON COLUMN dashboard.mv_vtd_partisan_demographics.majority_minority_pop IS 'True when non-White population share > 50%.';
COMMENT ON COLUMN dashboard.mv_vtd_partisan_demographics.majority_minority_vap IS 'True when non-White VAP share > 50%.';
COMMENT ON COLUMN dashboard.mv_vtd_partisan_demographics.centroid_lat IS 'VTD centroid latitude.';
COMMENT ON COLUMN dashboard.mv_vtd_partisan_demographics.centroid_lon IS 'VTD centroid longitude.';


-- ============================================================================
-- Simple dashboard views (wrappers / filtered slices / statewide totals)
-- ============================================================================

CREATE OR REPLACE VIEW dashboard.v_county_summary AS
SELECT * FROM dashboard.mv_county_summary;

COMMENT ON VIEW dashboard.v_county_summary IS
    'Read-friendly alias for dashboard.mv_county_summary.';


CREATE OR REPLACE VIEW dashboard.v_county_election_trends AS
SELECT * FROM dashboard.mv_county_election_trends;

COMMENT ON VIEW dashboard.v_county_election_trends IS
    'Read-friendly alias for dashboard.mv_county_election_trends.';


CREATE OR REPLACE VIEW dashboard.v_vtd_partisan_demographics AS
SELECT * FROM dashboard.mv_vtd_partisan_demographics;

COMMENT ON VIEW dashboard.v_vtd_partisan_demographics IS
    'Read-friendly alias for dashboard.mv_vtd_partisan_demographics.';


CREATE OR REPLACE VIEW dashboard.v_statewide_totals AS
SELECT
    SUM(d.pop) AS total_pop,
    SUM(d.vap) AS total_vap,
    SUM(d.pop_black) AS pop_black,
    SUM(d.pop_hisp) AS pop_hisp,
    SUM(d.pop_white) AS pop_white,
    SUM(d.pop_asian) AS pop_asian,
    SUM(d.pop_aian) AS pop_aian,
    SUM(l.actual_dem_votes) AS dem_votes,
    SUM(l.actual_total_votes) AS total_votes,
    ROUND((100.0 * SUM(l.actual_dem_votes) / NULLIF(SUM(l.actual_total_votes), 0))::numeric, 2) AS dem_pct,
    COUNT(*) AS n_vtds
FROM semantic.raw_vtd_demographics d
JOIN semantic.raw_vtd_composite_lean l
    ON l.geoid20 = d.geoid;

COMMENT ON VIEW dashboard.v_statewide_totals IS
    'Georgia statewide population and composite-vote totals for top-line KPIs.';


CREATE OR REPLACE VIEW dashboard.v_competitive_vtds AS
SELECT *
FROM dashboard.mv_vtd_partisan_demographics
WHERE is_competitive_7 = TRUE;

COMMENT ON VIEW dashboard.v_competitive_vtds IS
    'VTDs with a two-party margin of 7% or less — the swing-VTD list.';


CREATE OR REPLACE VIEW dashboard.v_county_competitiveness AS
SELECT
    county_fips,
    COUNT(*) AS n_vtds,
    COUNT(*) FILTER (WHERE is_competitive_7) AS n_competitive_7,
    COUNT(*) FILTER (WHERE is_competitive_10) AS n_competitive_10,
    ROUND((
        100.0 * COUNT(*) FILTER (WHERE is_competitive_7) / NULLIF(COUNT(*), 0))::numeric,
        2
    ) AS pct_competitive_7,
    ROUND((
        100.0 * COUNT(*) FILTER (WHERE is_competitive_10) / NULLIF(COUNT(*), 0))::numeric,
        2
    ) AS pct_competitive_10
FROM dashboard.mv_vtd_partisan_demographics
GROUP BY county_fips;

COMMENT ON VIEW dashboard.v_county_competitiveness IS
    'Number and share of competitive VTDs per county.';


CREATE OR REPLACE VIEW dashboard.v_county_race_partisan AS
SELECT
    county_fips,
    pct_vap_black,
    pct_vap_hisp,
    pct_vap_white,
    wtd_dem_2pv
FROM dashboard.mv_county_summary;

COMMENT ON VIEW dashboard.v_county_race_partisan IS
    'County racial composition vs. Democratic two-party share for scatter plots.';


CREATE OR REPLACE VIEW dashboard.v_district_demographics AS
SELECT
    chamber,
    district,
    chamber || ' ' || district AS chamber_district,
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

COMMENT ON VIEW dashboard.v_district_demographics IS
    'District socioeconomic metrics with a combined chamber_district label.';


CREATE OR REPLACE VIEW dashboard.v_redistricting_waves AS
SELECT * FROM semantic.v_redistricting_waves;

COMMENT ON VIEW dashboard.v_redistricting_waves IS
    'Dashboard wrapper for the semantic redistricting waves view.';


CREATE OR REPLACE VIEW dashboard.v_plan_summary AS
SELECT * FROM semantic.v_plan_summary;

COMMENT ON VIEW dashboard.v_plan_summary IS
    'Dashboard wrapper for the semantic plan summary view.';
