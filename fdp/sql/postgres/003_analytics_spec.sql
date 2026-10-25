-- ============================================================================
-- PostgreSQL analytics layer for the redistricting briefing specification.
--
-- This file adapts the views/aggregations described in the spec to the actual
-- FDP schema.  It is applied by scripts/cdm_to_postgres.py after the canonical
-- FDP DDL (sql/002_cdm.sql, sql/004_ensemble_scores.sql, sql/005_ensemble_runs.sql).
--
-- What is implemented
-- -------------------
-- 1. County population shift & 2020 demographic aggregates (Requirement 1)
-- 2. Partisan seat-count histogram bins (Requirement 2) — sourced from
--    fdp.ensemble_scores once ensemble plans are loaded.
-- 3. Competitive-district frequency distribution (Requirement 3)
-- 4. Minority-representation benchmarks (Requirement 4) — sourced from
--    analytics.ensemble_demographic_scores once demographic scoring is loaded.
-- 5. Master benchmark summary comparing enacted/actual vs. simulated ranges
--    (Requirement 5)
--
-- Empty-but-ready objects: everything that depends on fdp.ensemble_scores or
-- analytics.ensemble_demographic_scores will simply have zero rows until the
-- underlying ensemble data is loaded.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS analytics;

COMMENT ON SCHEMA analytics IS
    'Redistricting analytics and visualization layer matching the briefing specification.';


-- ----------------------------------------------------------------------------
-- Helper: map a plan_id string to a human chamber label.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION analytics.plan_id_to_chamber(plan_id TEXT)
RETURNS TEXT AS $$
BEGIN
    RETURN CASE
        WHEN plan_id ILIKE '%congress%' THEN 'US Congress'
        WHEN plan_id ILIKE '%senate%'  THEN 'State Senate'
        WHEN plan_id ILIKE '%house%'   THEN 'State House'
        ELSE 'Other'
    END;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION analytics.plan_id_to_chamber(TEXT) IS
    'Derive State House / State Senate / US Congress from a plan_id string.';


-- ----------------------------------------------------------------------------
-- 1. County reference and raw county census
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS analytics.county_reference (
    county_fips        CHAR(5) PRIMARY KEY,
    county_name        TEXT NOT NULL,
    is_metro_atlanta   BOOLEAN NOT NULL DEFAULT FALSE,
    is_metro_savannah  BOOLEAN NOT NULL DEFAULT FALSE
);

COMMENT ON TABLE analytics.county_reference IS
    'Georgia county names and metropolitan flags for dashboard labels and filters.';

COMMENT ON COLUMN analytics.county_reference.county_fips IS
    '5-character Georgia county FIPS code (state 13 + 3-digit county).';
COMMENT ON COLUMN analytics.county_reference.county_name IS
    'County name as it appears in the reference boundary file.';
COMMENT ON COLUMN analytics.county_reference.is_metro_atlanta IS
    'TRUE for counties in the Atlanta-Sandy Springs-Roswell MSA.';
COMMENT ON COLUMN analytics.county_reference.is_metro_savannah IS
    'TRUE for counties in the Savannah MSA (Bryan, Chatham, Effingham).';


CREATE TABLE IF NOT EXISTS analytics.raw_county_census (
    county_fips        CHAR(5) PRIMARY KEY
                       REFERENCES analytics.county_reference(county_fips),
    county_name        TEXT,
    is_metro_atlanta   BOOLEAN,
    is_metro_savannah  BOOLEAN,
    pop_2010           BIGINT,
    pop_2020           BIGINT,
    pop_white_2020     BIGINT,
    pop_black_2020     BIGINT,
    pop_hispanic_2020  BIGINT,
    pop_asian_2020     BIGINT,
    pop_other_2020     BIGINT
);

COMMENT ON TABLE analytics.raw_county_census IS
    'County-level 2010 Census population and 2020 decennial demographics. '
    'pop_2010 is sourced from the Census Bureau 2010-2019 estimates file; '
    '2020 figures are rolled up from 2020 Census VTD data in semantic.raw_vtd_demographics.';

COMMENT ON COLUMN analytics.raw_county_census.pop_2010 IS '2010 Census total population.';
COMMENT ON COLUMN analytics.raw_county_census.pop_2020 IS '2020 Census total population.';
COMMENT ON COLUMN analytics.raw_county_census.pop_white_2020 IS '2020 non-Hispanic White population.';
COMMENT ON COLUMN analytics.raw_county_census.pop_black_2020 IS '2020 Black/African American population.';
COMMENT ON COLUMN analytics.raw_county_census.pop_hispanic_2020 IS '2020 Hispanic/Latino population, any race.';
COMMENT ON COLUMN analytics.raw_county_census.pop_asian_2020 IS '2020 Asian population.';
COMMENT ON COLUMN analytics.raw_county_census.pop_other_2020 IS
    '2020 population not classified as White, Black, Hispanic, or Asian '
    '(includes AI/AN, Native Hawaiian/PI, multiracial, and other).';


-- ----------------------------------------------------------------------------
-- 1a. County population shifts & growth status
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analytics.v_county_population_shifts AS
WITH base AS (
    SELECT
        r.county_fips,
        ref.county_name,
        ref.is_metro_atlanta,
        ref.is_metro_savannah,
        r.pop_2010,
        r.pop_2020,
        (r.pop_2020 - r.pop_2010) AS pop_change_abs,
        ROUND(((r.pop_2020 - r.pop_2010)::NUMERIC / NULLIF(r.pop_2010, 0)) * 100, 2) AS pop_change_pct
    FROM analytics.raw_county_census r
    JOIN analytics.county_reference ref USING (county_fips)
    WHERE r.pop_2010 IS NOT NULL
      AND r.pop_2020 IS NOT NULL
),
quartiles AS (
    SELECT county_fips, NTILE(4) OVER (ORDER BY pop_change_pct) AS growth_quartile
    FROM base
)
SELECT
    b.*,
    CASE q.growth_quartile
        WHEN 1 THEN 'Shrinking'
        WHEN 2 THEN 'Stagnated'
        WHEN 3 THEN 'Growing'
        WHEN 4 THEN 'Fastest Growing'
    END AS growth_status
FROM base b
JOIN quartiles q USING (county_fips);

COMMENT ON VIEW analytics.v_county_population_shifts IS
    'County-level 2010-2020 population change with quartile-based growth status. '
    'The four categories are assigned by ranking the percent change across all Georgia counties.';

COMMENT ON COLUMN analytics.v_county_population_shifts.pop_change_abs IS
    'Absolute population change 2010-2020.';
COMMENT ON COLUMN analytics.v_county_population_shifts.pop_change_pct IS
    'Percent population change 2010-2020.';
COMMENT ON COLUMN analytics.v_county_population_shifts.growth_status IS
    'Quartile-based growth label: Shrinking, Stagnated, Growing, Fastest Growing.';


-- ----------------------------------------------------------------------------
-- 1b. Statewide 2020 demographic breakdown (donut chart)
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analytics.v_statewide_demographic_breakdown_2020 AS
SELECT
    SUM(pop_2020) AS total_pop,
    SUM(pop_white_2020)     AS pop_white,
    SUM(pop_black_2020)     AS pop_black,
    SUM(pop_hispanic_2020)  AS pop_hispanic,
    SUM(pop_asian_2020)     AS pop_asian,
    SUM(pop_other_2020)     AS pop_other,
    ROUND((100.0 * SUM(pop_white_2020))    / NULLIF(SUM(pop_2020), 0), 2) AS pct_white,
    ROUND((100.0 * SUM(pop_black_2020))    / NULLIF(SUM(pop_2020), 0), 2) AS pct_black,
    ROUND((100.0 * SUM(pop_hispanic_2020)) / NULLIF(SUM(pop_2020), 0), 2) AS pct_hispanic,
    ROUND((100.0 * SUM(pop_asian_2020))    / NULLIF(SUM(pop_2020), 0), 2) AS pct_asian,
    ROUND((100.0 * SUM(pop_other_2020))    / NULLIF(SUM(pop_2020), 0), 2) AS pct_other
FROM analytics.raw_county_census;

COMMENT ON VIEW analytics.v_statewide_demographic_breakdown_2020 IS
    'Statewide 2020 population by race/ethnicity for donut/pie charts.';


-- ----------------------------------------------------------------------------
-- 1c. County-level 2020 racial composition (convenience for maps/tables)
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analytics.v_county_demographics_2020 AS
SELECT
    r.county_fips,
    ref.county_name,
    ref.is_metro_atlanta,
    ref.is_metro_savannah,
    r.pop_2020 AS total_pop,
    r.pop_white_2020,
    r.pop_black_2020,
    r.pop_hispanic_2020,
    r.pop_asian_2020,
    r.pop_other_2020,
    ROUND((100.0 * r.pop_white_2020)    / NULLIF(r.pop_2020, 0), 2) AS pct_white,
    ROUND((100.0 * r.pop_black_2020)    / NULLIF(r.pop_2020, 0), 2) AS pct_black,
    ROUND((100.0 * r.pop_hispanic_2020) / NULLIF(r.pop_2020, 0), 2) AS pct_hispanic,
    ROUND((100.0 * r.pop_asian_2020)    / NULLIF(r.pop_2020, 0), 2) AS pct_asian,
    ROUND((100.0 * r.pop_other_2020)    / NULLIF(r.pop_2020, 0), 2) AS pct_other
FROM analytics.raw_county_census r
JOIN analytics.county_reference ref USING (county_fips);

COMMENT ON VIEW analytics.v_county_demographics_2020 IS
    'County-level 2020 racial/ethnic composition for choropleths and tables.';


-- ----------------------------------------------------------------------------
-- 2. Ensemble support: raw demographic scores table
--
-- score_ensemble_demographics.py writes {run_name}_demographics.parquet with
-- one row per draw x district. Load that parquet into this table to enable the
-- minority-representation benchmarks below.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analytics.ensemble_demographic_scores (
    plan_id                     TEXT    NOT NULL,
    draw                        INTEGER NOT NULL,
    district                    INTEGER NOT NULL,
    bvap_tot                    BIGINT,
    bvap_blk                    BIGINT,
    bvap_hsp                    BIGINT,
    bvap_wht                    BIGINT,
    bvap_asn                    BIGINT,
    pct_black                   NUMERIC(7,5),
    pct_hispanic                NUMERIC(7,5),
    pct_white                   NUMERIC(7,5),
    pct_asian                   NUMERIC(7,5),
    pct_minority_coalition      NUMERIC(7,5),
    majority_black              BOOLEAN,
    majority_white              BOOLEAN,
    majority_hispanic           BOOLEAN,
    majority_minority_coalition BOOLEAN,
    PRIMARY KEY (plan_id, draw, district)
);

COMMENT ON TABLE analytics.ensemble_demographic_scores IS
    'Per-draw district demographic scores. Populate by loading the output of '
    'scripts/score_ensemble_demographics.py.';

COMMENT ON COLUMN analytics.ensemble_demographic_scores.plan_id IS
    'Ensemble run identifier (e.g. ga_congress_2020_alarm_5001).';
COMMENT ON COLUMN analytics.ensemble_demographic_scores.draw IS
    'Draw number: 1 = enacted plan, 2+ = simulated maps.';
COMMENT ON COLUMN analytics.ensemble_demographic_scores.district IS
    'District number within the plan.';
COMMENT ON COLUMN analytics.ensemble_demographic_scores.bvap_tot IS
    'Total VAP in the district (source column name from the scoring script).';
COMMENT ON COLUMN analytics.ensemble_demographic_scores.bvap_blk IS
    'Black or African American VAP.';
COMMENT ON COLUMN analytics.ensemble_demographic_scores.bvap_hsp IS
    'Hispanic or Latino VAP.';
COMMENT ON COLUMN analytics.ensemble_demographic_scores.bvap_wht IS
    'White VAP.';
COMMENT ON COLUMN analytics.ensemble_demographic_scores.bvap_asn IS
    'Asian VAP.';
COMMENT ON COLUMN analytics.ensemble_demographic_scores.pct_black IS
    'Black VAP share of total VAP.';
COMMENT ON COLUMN analytics.ensemble_demographic_scores.pct_hispanic IS
    'Hispanic VAP share of total VAP.';
COMMENT ON COLUMN analytics.ensemble_demographic_scores.pct_white IS
    'White VAP share of total VAP.';
COMMENT ON COLUMN analytics.ensemble_demographic_scores.pct_asian IS
    'Asian VAP share of total VAP.';
COMMENT ON COLUMN analytics.ensemble_demographic_scores.pct_minority_coalition IS
    'Non-White VAP share of total VAP (coalition-of-color).';
COMMENT ON COLUMN analytics.ensemble_demographic_scores.majority_black IS
    'TRUE when pct_black >= 0.50.';
COMMENT ON COLUMN analytics.ensemble_demographic_scores.majority_hispanic IS
    'TRUE when pct_hispanic >= 0.50.';
COMMENT ON COLUMN analytics.ensemble_demographic_scores.majority_minority_coalition IS
    'TRUE when pct_minority_coalition >= 0.50.';

CREATE INDEX IF NOT EXISTS idx_eds_plan_draw
    ON analytics.ensemble_demographic_scores (plan_id, draw);
CREATE INDEX IF NOT EXISTS idx_eds_pct_black
    ON analytics.ensemble_demographic_scores (plan_id, draw, pct_black);
CREATE INDEX IF NOT EXISTS idx_eds_pct_coalition
    ON analytics.ensemble_demographic_scores (plan_id, draw, pct_minority_coalition);


-- ----------------------------------------------------------------------------
-- Indexes to keep histogram queries fast once ensemble_scores is loaded.
-- ----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_es_plan_draw
    ON fdp.ensemble_scores (plan_id, draw);
CREATE INDEX IF NOT EXISTS idx_es_plan_district
    ON fdp.ensemble_scores (plan_id, draw, district);
CREATE INDEX IF NOT EXISTS idx_es_plan_year_office
    ON fdp.ensemble_scores (plan_id, year, election_type, office);
CREATE INDEX IF NOT EXISTS idx_es_d2pv
    ON fdp.ensemble_scores (plan_id, draw, dem_2pv);


-- ----------------------------------------------------------------------------
-- 2. Partisan outcome histogram bins
-- ----------------------------------------------------------------------------
DROP MATERIALIZED VIEW IF EXISTS analytics.agg_sim_partisan_outcomes CASCADE;

CREATE MATERIALIZED VIEW analytics.agg_sim_partisan_outcomes AS
WITH seat_counts AS (
    SELECT plan_id, year, election_type, office, dem_seats
    FROM fdp.v_ensemble_seat_counts
    WHERE draw > 1
),
bounds AS (
    SELECT
        plan_id,
        year,
        election_type,
        office,
        PERCENTILE_CONT(0.01) WITHIN GROUP (ORDER BY dem_seats)::NUMERIC AS pct01_dem_seats,
        PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY dem_seats)::NUMERIC AS pct99_dem_seats
    FROM seat_counts
    GROUP BY plan_id, year, election_type, office
),
grouped AS (
    SELECT
        plan_id,
        year,
        election_type,
        office,
        dem_seats AS dem_seats_count,
        COUNT(*) AS map_count
    FROM seat_counts
    GROUP BY plan_id, year, election_type, office, dem_seats
)
SELECT
    g.plan_id,
    analytics.plan_id_to_chamber(g.plan_id) AS chamber,
    g.year AS cycle_year,
    g.election_type,
    g.office,
    g.dem_seats_count,
    g.map_count,
    b.pct01_dem_seats,
    b.pct99_dem_seats,
    (g.dem_seats_count BETWEEN b.pct01_dem_seats AND b.pct99_dem_seats) AS is_98_percentile_range
FROM grouped g
JOIN bounds b
  ON b.plan_id = g.plan_id
 AND b.year = g.year
 AND b.election_type = g.election_type
 AND b.office = g.office;

CREATE UNIQUE INDEX idx_agg_sim_partisan_outcomes_u
    ON analytics.agg_sim_partisan_outcomes (plan_id, cycle_year, election_type, office, dem_seats_count);
CREATE INDEX idx_agg_sim_partisan_outcomes_range
    ON analytics.agg_sim_partisan_outcomes (plan_id, cycle_year, election_type, office, is_98_percentile_range);

COMMENT ON MATERIALIZED VIEW analytics.agg_sim_partisan_outcomes IS
    'Histogram bins of Democratic seat counts across simulated ensemble maps. '
    'is_98_percentile_range flags bins inside the 1st-99th percentile core range.';

COMMENT ON COLUMN analytics.agg_sim_partisan_outcomes.dem_seats_count IS
    'Number of Democratic seats in a simulated map.';
COMMENT ON COLUMN analytics.agg_sim_partisan_outcomes.map_count IS
    'How many simulated maps produced exactly this many Democratic seats.';
COMMENT ON COLUMN analytics.agg_sim_partisan_outcomes.is_98_percentile_range IS
    'TRUE when the seat count lies within the simulated 1st-99th percentile range.';


-- ----------------------------------------------------------------------------
-- 3. Competitive district frequency distribution
-- ----------------------------------------------------------------------------
DROP MATERIALIZED VIEW IF EXISTS analytics.agg_sim_competitiveness CASCADE;

CREATE MATERIALIZED VIEW analytics.agg_sim_competitiveness AS
WITH per_draw AS (
    SELECT
        plan_id,
        draw,
        year,
        election_type,
        office,
        COUNT(*) FILTER (WHERE dem_2pv BETWEEN 0.45 AND 0.55) AS competitive_district_count
    FROM fdp.ensemble_scores
    GROUP BY plan_id, draw, year, election_type, office
),
enacted AS (
    SELECT plan_id, year, election_type, office, competitive_district_count AS enacted_competitive_count
    FROM per_draw
    WHERE draw = 1
),
bounds AS (
    SELECT
        plan_id,
        year,
        election_type,
        office,
        PERCENTILE_CONT(0.01) WITHIN GROUP (ORDER BY competitive_district_count)::NUMERIC AS pct01,
        PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY competitive_district_count)::NUMERIC AS pct99
    FROM per_draw
    WHERE draw > 1
    GROUP BY plan_id, year, election_type, office
),
grouped AS (
    SELECT
        plan_id,
        year,
        election_type,
        office,
        competitive_district_count,
        COUNT(*) AS map_count
    FROM per_draw
    WHERE draw > 1
    GROUP BY plan_id, year, election_type, office, competitive_district_count
)
SELECT
    g.plan_id,
    analytics.plan_id_to_chamber(g.plan_id) AS chamber,
    g.year AS cycle_year,
    g.election_type,
    g.office,
    g.competitive_district_count,
    g.map_count,
    e.enacted_competitive_count,
    b.pct01,
    b.pct99,
    (g.competitive_district_count BETWEEN b.pct01 AND b.pct99) AS is_98_percentile_range
FROM grouped g
JOIN bounds b
  ON b.plan_id = g.plan_id
 AND b.year = g.year
 AND b.election_type = g.election_type
 AND b.office = g.office
LEFT JOIN enacted e
  ON e.plan_id = g.plan_id
 AND e.year = g.year
 AND e.election_type = g.election_type
 AND e.office = g.office;

CREATE UNIQUE INDEX idx_agg_sim_competitiveness_u
    ON analytics.agg_sim_competitiveness (plan_id, cycle_year, election_type, office, competitive_district_count);

COMMENT ON MATERIALIZED VIEW analytics.agg_sim_competitiveness IS
    'Frequency distribution of competitive district counts across simulated maps, '
    'with the enacted plan (draw=1) highlighted as a benchmark line.';

COMMENT ON COLUMN analytics.agg_sim_competitiveness.competitive_district_count IS
    'Number of districts with Democratic two-party vote share between 45% and 55%.';
COMMENT ON COLUMN analytics.agg_sim_competitiveness.enacted_competitive_count IS
    'Competitive district count in the enacted plan (draw=1) for the same race.';


-- ----------------------------------------------------------------------------
-- 4a. Minority representation per simulated map
-- ----------------------------------------------------------------------------
DROP MATERIALIZED VIEW IF EXISTS analytics.agg_sim_minority_representation CASCADE;

CREATE MATERIALIZED VIEW analytics.agg_sim_minority_representation AS
SELECT
    plan_id,
    draw,
    analytics.plan_id_to_chamber(plan_id) AS chamber,
    COUNT(*) FILTER (WHERE pct_black > 0.50)                         AS black_majority_districts_count,
    COUNT(*) FILTER (WHERE pct_black BETWEEN 0.37 AND 0.50)          AS black_influence_districts_count,
    COUNT(*) FILTER (WHERE pct_hispanic > 0.50)                      AS hispanic_majority_districts_count,
    COUNT(*) FILTER (WHERE pct_minority_coalition > 0.50)            AS coalition_districts_count
FROM analytics.ensemble_demographic_scores
GROUP BY plan_id, draw;

CREATE UNIQUE INDEX idx_agg_sim_minority_representation_u
    ON analytics.agg_sim_minority_representation (plan_id, draw);

COMMENT ON MATERIALIZED VIEW analytics.agg_sim_minority_representation IS
    'Per-map counts of majority-Black, influence-Black, majority-Hispanic, and '
    'minority-coalition districts.';


-- ----------------------------------------------------------------------------
-- 4b. Minority representation benchmark summary
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analytics.v_minority_representation_benchmarks AS
SELECT
    plan_id,
    analytics.plan_id_to_chamber(plan_id) AS chamber,
    MIN(black_majority_districts_count)    AS min_black_majority,
    PERCENTILE_CONT(0.01) WITHIN GROUP (ORDER BY black_majority_districts_count)::NUMERIC AS pct01_black_majority,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY black_majority_districts_count)::NUMERIC AS median_black_majority,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY black_majority_districts_count)::NUMERIC AS pct99_black_majority,
    MAX(black_majority_districts_count)    AS max_black_majority,

    MIN(black_influence_districts_count)   AS min_black_influence,
    PERCENTILE_CONT(0.01) WITHIN GROUP (ORDER BY black_influence_districts_count)::NUMERIC AS pct01_black_influence,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY black_influence_districts_count)::NUMERIC AS median_black_influence,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY black_influence_districts_count)::NUMERIC AS pct99_black_influence,
    MAX(black_influence_districts_count)   AS max_black_influence,

    MIN(hispanic_majority_districts_count) AS min_hispanic_majority,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY hispanic_majority_districts_count)::NUMERIC AS median_hispanic_majority,
    MAX(hispanic_majority_districts_count) AS max_hispanic_majority,

    MIN(coalition_districts_count)         AS min_coalition,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY coalition_districts_count)::NUMERIC AS median_coalition,
    MAX(coalition_districts_count)         AS max_coalition
FROM analytics.agg_sim_minority_representation
WHERE draw > 1
GROUP BY plan_id;

COMMENT ON VIEW analytics.v_minority_representation_benchmarks IS
    'Min, median, max, and 1st/99th percentile boundaries for minority representation '
    'across simulated maps per plan.';


-- ----------------------------------------------------------------------------
-- 5. Master benchmark summary: enacted/actual vs. simulated ranges
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analytics.v_redistricting_benchmark_summary AS
WITH seat_bounds AS (
    SELECT
        plan_id,
        year,
        election_type,
        office,
        MAX(total_districts) AS total_districts,
        COUNT(*) FILTER (WHERE draw > 1) AS n_simulated,
        PERCENTILE_CONT(0.01) WITHIN GROUP (ORDER BY dem_seats)::NUMERIC AS dem_seats_01,
        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY dem_seats)::NUMERIC AS dem_seats_median,
        PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY dem_seats)::NUMERIC AS dem_seats_99
    FROM fdp.v_ensemble_seat_counts
    GROUP BY plan_id, year, election_type, office
),
comp_bounds AS (
    SELECT
        plan_id,
        year,
        election_type,
        office,
        PERCENTILE_CONT(0.01) WITHIN GROUP (ORDER BY comp_count)::NUMERIC AS comp_01,
        PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY comp_count)::NUMERIC AS comp_99
    FROM (
        SELECT
            plan_id,
            draw,
            year,
            election_type,
            office,
            COUNT(*) FILTER (WHERE dem_2pv BETWEEN 0.45 AND 0.55) AS comp_count
        FROM fdp.ensemble_scores
        GROUP BY plan_id, draw, year, election_type, office
    ) t
    WHERE draw > 1
    GROUP BY plan_id, year, election_type, office
),
minority_bounds AS (
    SELECT
        plan_id,
        MIN(black_majority_districts_count) AS min_black_majority,
        PERCENTILE_CONT(0.01) WITHIN GROUP (ORDER BY black_majority_districts_count)::NUMERIC AS bm_01,
        PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY black_majority_districts_count)::NUMERIC AS bm_99,
        PERCENTILE_CONT(0.01) WITHIN GROUP (ORDER BY black_influence_districts_count)::NUMERIC AS bi_01,
        PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY black_influence_districts_count)::NUMERIC AS bi_99
    FROM analytics.agg_sim_minority_representation
    WHERE draw > 1
    GROUP BY plan_id
),
enacted AS (
    SELECT
        plan_id,
        year,
        election_type,
        office,
        dem_seats  AS actual_dem_seats_held,
        rep_seats  AS actual_gop_seats_held
    FROM fdp.v_ensemble_seat_counts
    WHERE draw = 1
),
enacted_minority AS (
    SELECT
        plan_id,
        black_majority_districts_count  AS enacted_black_majority_count,
        black_influence_districts_count AS enacted_black_influence_count
    FROM analytics.agg_sim_minority_representation
    WHERE draw = 1
)
SELECT
    analytics.plan_id_to_chamber(sb.plan_id) AS chamber,
    sb.year AS cycle_year,
    sb.plan_id,
    sb.election_type,
    sb.office,
    sb.n_simulated,
    sb.dem_seats_01 || '-' || sb.dem_seats_99  AS expected_dem_range,
    (sb.total_districts - sb.dem_seats_99) || '-' || (sb.total_districts - sb.dem_seats_01) AS expected_gop_range,
    COALESCE(cb.comp_01 || '-' || cb.comp_99, 'N/A') AS expected_competitive_range,
    COALESCE(mb.min_black_majority::TEXT, 'N/A')     AS expected_black_majority_min,
    COALESCE(mb.bi_01 || '-' || mb.bi_99, 'N/A')     AS expected_black_influence_range,
    e.actual_dem_seats_held,
    e.actual_gop_seats_held,
    em.enacted_black_majority_count,
    em.enacted_black_influence_count,
    sb.dem_seats_median
FROM seat_bounds sb
LEFT JOIN comp_bounds cb
  ON cb.plan_id = sb.plan_id
 AND cb.year = sb.year
 AND cb.election_type = sb.election_type
 AND cb.office = sb.office
LEFT JOIN minority_bounds mb
  ON mb.plan_id = sb.plan_id
LEFT JOIN enacted e
  ON e.plan_id = sb.plan_id
 AND e.year = sb.year
 AND e.election_type = sb.election_type
 AND e.office = sb.office
LEFT JOIN enacted_minority em
  ON em.plan_id = sb.plan_id;

COMMENT ON VIEW analytics.v_redistricting_benchmark_summary IS
    'One-row-per-race benchmark summary comparing the enacted plan (draw=1) to '
    'the simulated ensemble distribution: expected Dem/GOP/competitive ranges, '
    'minority representation ranges, and actual enacted seat counts.';

COMMENT ON COLUMN analytics.v_redistricting_benchmark_summary.expected_dem_range IS
    '1st-99th percentile range of Democratic seats across simulated maps.';
COMMENT ON COLUMN analytics.v_redistricting_benchmark_summary.expected_gop_range IS
    'Implied Republican seat range from the Democratic percentile range.';
COMMENT ON COLUMN analytics.v_redistricting_benchmark_summary.expected_black_majority_min IS
    'Minimum number of Black-majority districts observed across simulations.';
COMMENT ON COLUMN analytics.v_redistricting_benchmark_summary.actual_dem_seats_held IS
    'Democratic seats in the enacted plan (draw=1) for this race.';
COMMENT ON COLUMN analytics.v_redistricting_benchmark_summary.actual_gop_seats_held IS
    'Republican seats in the enacted plan (draw=1) for this race.';
