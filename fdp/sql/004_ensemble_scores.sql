-- =============================================================================
-- FDP Ensemble Scores — partisan scoring for redistricting ensemble analysis
-- Migration: 004_ensemble_scores.sql
-- Apply with: fdp init-db  OR  psql $DATABASE_URL -f sql/004_ensemble_scores.sql
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Table: fdp.ensemble_scores
--
-- Pre-computed partisan scores per draw × district × race.
-- Replaces the need to store 13.5M raw VTD assignments; instead we store
-- only the aggregated results (~910k rows for the GA 5001-draw ensemble).
--
-- Draw 1 = enacted plan. Draws 2–N = simulated ensemble.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fdp.ensemble_scores (
    plan_id       TEXT        NOT NULL,
    draw          INTEGER     NOT NULL,
    district      INTEGER     NOT NULL,
    year          INTEGER     NOT NULL,
    election_type TEXT        NOT NULL,
    office        TEXT        NOT NULL,
    dem_votes     BIGINT,
    rep_votes     BIGINT,
    total_votes   BIGINT,
    dem_2pv       NUMERIC(8, 6),   -- 0.000000–1.000000
    winner        TEXT,            -- 'dem' | 'rep' | 'tie'
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    loaded_by     TEXT,

    PRIMARY KEY (plan_id, draw, district, year, election_type, office)
);

COMMENT ON TABLE fdp.ensemble_scores IS
    'Pre-computed partisan scores per ensemble draw × district × race. '
    'Draw 1 = enacted plan. Compute with scripts/score_ensemble_plans.py.';

COMMENT ON COLUMN fdp.ensemble_scores.dem_2pv IS
    'Democratic two-party vote share: dem_votes / (dem_votes + rep_votes). '
    'NULL when both parties have zero votes in a district.';

COMMENT ON COLUMN fdp.ensemble_scores.winner IS
    'Winning party based on dem_2pv: dem if > 0.5, rep if < 0.5, tie if = 0.5.';


-- ---------------------------------------------------------------------------
-- View: fdp.v_ensemble_seat_counts
--
-- Seat counts (dem / rep wins) per draw × race.
-- Primary input for Princeton-style partisan fairness grading.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW fdp.v_ensemble_seat_counts AS
SELECT
    plan_id,
    draw,
    year,
    election_type,
    office,
    COUNT(*) FILTER (WHERE winner = 'dem')  AS dem_seats,
    COUNT(*) FILTER (WHERE winner = 'rep')  AS rep_seats,
    COUNT(*) FILTER (WHERE winner = 'tie')  AS tied_seats,
    COUNT(*)                                AS total_districts,
    ROUND(AVG(dem_2pv) * 100, 2)            AS avg_dem_2pv_pct
FROM fdp.ensemble_scores
GROUP BY plan_id, draw, year, election_type, office;

COMMENT ON VIEW fdp.v_ensemble_seat_counts IS
    'Seat counts per draw × race. Join draw=1 to the simulation distribution '
    'for Princeton-style ensemble grading.';


-- ---------------------------------------------------------------------------
-- View: fdp.v_ensemble_vs_enacted
--
-- Princeton-style comparison: enacted plan (draw=1) vs. simulated ensemble.
-- Computes where the enacted map falls in the ensemble distribution for each
-- election, and quantifies partisan bias (seats vs. votes).
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW fdp.v_ensemble_vs_enacted AS
WITH seat_counts AS (
    -- All draws, all races
    SELECT
        plan_id, draw, year, election_type, office,
        dem_seats, rep_seats, total_districts, avg_dem_2pv_pct
    FROM fdp.v_ensemble_seat_counts
),
enacted AS (
    SELECT plan_id, year, election_type, office,
           dem_seats    AS enacted_dem_seats,
           rep_seats    AS enacted_rep_seats,
           avg_dem_2pv_pct AS enacted_avg_dem_2pv_pct
    FROM seat_counts
    WHERE draw = 1
),
sim_stats AS (
    -- Ensemble distribution (simulated draws only)
    SELECT
        plan_id, year, election_type, office,
        COUNT(*)                                                     AS n_simulated,
        ROUND(AVG(dem_seats)::NUMERIC, 3)                           AS mean_dem_seats,
        PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY dem_seats)::NUMERIC(6,2) AS median_dem_seats,
        PERCENTILE_CONT(0.05) WITHIN GROUP (ORDER BY dem_seats)::NUMERIC(6,2) AS pct05_dem_seats,
        PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY dem_seats)::NUMERIC(6,2) AS pct25_dem_seats,
        PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY dem_seats)::NUMERIC(6,2) AS pct75_dem_seats,
        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY dem_seats)::NUMERIC(6,2) AS pct95_dem_seats,
        MIN(dem_seats)                                               AS min_dem_seats,
        MAX(dem_seats)                                               AS max_dem_seats
    FROM seat_counts
    WHERE draw > 1
    GROUP BY plan_id, year, election_type, office
),
pctile AS (
    -- Where does the enacted seat count land in the ensemble?
    SELECT
        s.plan_id, s.year, s.election_type, s.office,
        ROUND(
            100.0 * SUM(CASE WHEN s.dem_seats <= e.enacted_dem_seats THEN 1 ELSE 0 END)
            / NULLIF(COUNT(*), 0),
        1) AS enacted_pctile
    FROM seat_counts s
    JOIN enacted e USING (plan_id, year, election_type, office)
    WHERE s.draw > 1
    GROUP BY s.plan_id, s.year, s.election_type, s.office
)
SELECT
    e.plan_id,
    e.year,
    e.election_type,
    e.office,
    e.enacted_dem_seats,
    e.enacted_rep_seats,
    e.enacted_avg_dem_2pv_pct,
    ss.mean_dem_seats,
    ss.median_dem_seats,
    ss.pct05_dem_seats,
    ss.pct25_dem_seats,
    ss.pct75_dem_seats,
    ss.pct95_dem_seats,
    ss.min_dem_seats,
    ss.max_dem_seats,
    ss.n_simulated,
    p.enacted_pctile,
    -- Seat bias: enacted minus ensemble median (+ = favors Republicans)
    ROUND((ss.median_dem_seats - e.enacted_dem_seats)::NUMERIC, 2) AS dem_seat_bias,
    -- Princeton grade bucket
    CASE
        WHEN p.enacted_pctile BETWEEN 25 AND 75 THEN 'A  (within IQR)'
        WHEN p.enacted_pctile BETWEEN 10 AND 90 THEN 'B  (within 10–90th pct)'
        WHEN p.enacted_pctile BETWEEN  5 AND 95 THEN 'C  (within 5–95th pct)'
        ELSE                                          'F  (outside 5–95th pct)'
    END AS princeton_grade
FROM enacted e
JOIN sim_stats ss USING (plan_id, year, election_type, office)
JOIN pctile    p  USING (plan_id, year, election_type, office);

COMMENT ON VIEW fdp.v_ensemble_vs_enacted IS
    'Princeton-style ensemble comparison. For each race, shows where the enacted '
    'plan (draw=1) sits in the simulated distribution. enacted_pctile near 0 means '
    'the enacted map produces unusually few Dem seats (Republican gerrymander); '
    'near 100 means unusually many. IQR = 25th–75th percentile of the ensemble.';


-- ---------------------------------------------------------------------------
-- View: fdp.v_ensemble_district_scores  (convenience — enacted plan only)
--
-- District-level scores for the enacted plan across all scored elections.
-- Useful for choropleth maps and district detail panels.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW fdp.v_ensemble_district_scores AS
SELECT
    es.plan_id,
    es.district,
    es.year,
    es.election_type,
    es.office,
    es.dem_votes,
    es.rep_votes,
    es.total_votes,
    ROUND(es.dem_2pv * 100, 2) AS dem_2pv_pct,
    es.winner,
    g.county_fips                             -- representative county (majority VTD)
FROM fdp.ensemble_scores es
LEFT JOIN LATERAL (
    -- Pick one county_fips to label the district (most common in ensemble geography)
    SELECT county_fips
    FROM fdp.geography
    WHERE geo_level = 'vtd'
    GROUP BY county_fips
    ORDER BY COUNT(*) DESC
    LIMIT 1
) g ON TRUE
WHERE es.draw = 1;

COMMENT ON VIEW fdp.v_ensemble_district_scores IS
    'Enacted plan (draw=1) district scores for all scored elections. '
    'Use for district detail panels and choropleth maps.';
