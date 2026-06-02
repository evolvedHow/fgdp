-- =============================================================================
-- 006_draw_stats.sql — Per-draw benchmark statistics
--
-- Two new tables:
--   fdp.ensemble_draw_stats    — partisan + competitiveness rollup, one row per
--                                (plan_id, draw, year, election_type, office)
--   fdp.ensemble_demographics  — CVAP-based district demographics, one row per
--                                (plan_id, draw, district)
--
-- Six new views:
--   v_partisan_distribution    — histogram data: how often did ensemble produce N dem seats?
--   v_competitive_distribution — histogram: N competitive districts across draws
--   v_demographic_distribution — histogram: N majority-minority districts across draws
--   v_demographic_draw_stats   — rollup: majority-X district counts per draw
--   v_enacted_vs_benchmark     — enacted plan position in every distribution (Princeton grading)
--   v_correlation_competitive_partisan — correlation between competitiveness and partisan lean
--
-- Apply with:
--   psql $DATABASE_URL -f fdp/sql/006_draw_stats.sql
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Table: fdp.ensemble_draw_stats
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fdp.ensemble_draw_stats (
    plan_id        TEXT    NOT NULL,
    draw           INT     NOT NULL,
    year           INT     NOT NULL,
    election_type  TEXT    NOT NULL,
    office         TEXT    NOT NULL,

    -- Seat counts
    dem_seats      INT,
    rep_seats      INT,
    tied_seats     INT,

    -- Partisan metrics
    avg_dem_2pv    NUMERIC(8,6),   -- mean Dem two-party vote share across districts
    efficiency_gap NUMERIC(8,6),   -- (wasted_dem - wasted_rep) / total_votes; + = R advantage
    mean_median    NUMERIC(8,6),   -- mean(dem_2pv) - median(dem_2pv); + = D skew

    -- Competitiveness (count of districts with win_margin <= threshold)
    -- win_margin = |dem_2pv - 0.5| × 2
    n_competitive_007  INT,        -- margin ≤ 7%
    n_competitive_010  INT,        -- margin ≤ 10%

    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (plan_id, draw, year, election_type, office)
);

COMMENT ON TABLE fdp.ensemble_draw_stats IS
    'Per-draw partisan rollup. One row per (plan_id, draw, year, office). '
    'Draw 1 = enacted plan. Compute with scripts/build_draw_stats.py.';

COMMENT ON COLUMN fdp.ensemble_draw_stats.efficiency_gap IS
    'Efficiency gap: positive = Republican advantage, negative = Democratic advantage. '
    'Thresholds: |EG| > 0.08 = substantial, > 0.10 = severe (SCOTUS level).';

COMMENT ON COLUMN fdp.ensemble_draw_stats.mean_median IS
    'Mean–median difference: positive = Democratic skew, negative = Republican skew. '
    'Values outside ±0.03 suggest systematic partisan advantage.';

COMMENT ON COLUMN fdp.ensemble_draw_stats.n_competitive_007 IS
    'Districts where the two-party winning margin is ≤ 7%. Primary competitiveness metric.';

COMMENT ON COLUMN fdp.ensemble_draw_stats.n_competitive_010 IS
    'Districts where the two-party winning margin is ≤ 10%. Secondary competitiveness metric.';


-- ---------------------------------------------------------------------------
-- Table: fdp.ensemble_demographics
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fdp.ensemble_demographics (
    plan_id        TEXT    NOT NULL,
    draw           INT     NOT NULL,
    district       INT     NOT NULL,

    -- Raw CVAP counts (from ACS 2024 5-yr estimates disaggregated to 2020 blocks)
    cvap_tot       INT,
    cvap_blk       INT,    -- Black or African American alone or in combination
    cvap_hsp       INT,    -- Hispanic or Latino
    cvap_wht       INT,    -- White non-Hispanic alone
    cvap_asn       INT,    -- Asian alone or in combination

    -- Percentages (0.0–1.0)
    pct_black      NUMERIC(7,5),
    pct_hispanic   NUMERIC(7,5),
    pct_white      NUMERIC(7,5),
    pct_asian      NUMERIC(7,5),
    pct_minority_coalition NUMERIC(7,5),   -- 1 – pct_white (all non-white CVAP)

    -- Majority flags (> 50% CVAP threshold)
    majority_black              BOOLEAN,
    majority_white              BOOLEAN,
    majority_hispanic           BOOLEAN,
    majority_minority_coalition BOOLEAN,

    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (plan_id, draw, district)
);

COMMENT ON TABLE fdp.ensemble_demographics IS
    'CVAP-based district demographics per ensemble draw. '
    'One row per (plan_id, draw, district). Draw 1 = enacted. '
    'Compute with scripts/score_ensemble_demographics.py.';

COMMENT ON COLUMN fdp.ensemble_demographics.majority_minority_coalition IS
    'True when 1 – pct_white > 0.50, i.e., combined non-white CVAP exceeds 50%.';


-- ---------------------------------------------------------------------------
-- View: v_partisan_distribution
-- Histogram data for partisan lean — how often does the ensemble produce N dem seats?
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW fdp.v_partisan_distribution AS
SELECT
    plan_id,
    year,
    election_type,
    office,
    dem_seats,
    COUNT(*)                                                         AS n_draws,
    ROUND(COUNT(*) * 100.0
          / SUM(COUNT(*)) OVER (PARTITION BY plan_id, year, election_type, office),
          2)                                                         AS pct_draws
FROM fdp.ensemble_draw_stats
WHERE draw > 1
GROUP BY plan_id, year, election_type, office, dem_seats
ORDER BY plan_id, year, office, dem_seats;

COMMENT ON VIEW fdp.v_partisan_distribution IS
    'Partisan lean histogram: distribution of dem seat counts across simulated draws. '
    'Join enacted plan (draw=1) from ensemble_draw_stats to mark its position.';


-- ---------------------------------------------------------------------------
-- View: v_competitive_distribution
-- Histogram for competitive district counts at 7% and 10% thresholds
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW fdp.v_competitive_distribution AS
SELECT
    plan_id,
    year,
    election_type,
    office,
    n_competitive_007,
    n_competitive_010,
    COUNT(*) AS n_draws,
    ROUND(COUNT(*) * 100.0
          / SUM(COUNT(*)) OVER (PARTITION BY plan_id, year, election_type, office),
          2) AS pct_draws
FROM fdp.ensemble_draw_stats
WHERE draw > 1
GROUP BY plan_id, year, election_type, office, n_competitive_007, n_competitive_010
ORDER BY plan_id, year, office, n_competitive_007;

COMMENT ON VIEW fdp.v_competitive_distribution IS
    'Competitive district count distribution across simulated draws. '
    'Primary: 7% margin threshold. Secondary: 10%.';


-- ---------------------------------------------------------------------------
-- View: v_demographic_draw_stats
-- Per-draw count of majority-X districts
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW fdp.v_demographic_draw_stats AS
SELECT
    plan_id,
    draw,
    COUNT(*) FILTER (WHERE majority_black)              AS n_majority_black,
    COUNT(*) FILTER (WHERE majority_white)              AS n_majority_white,
    COUNT(*) FILTER (WHERE majority_hispanic)           AS n_majority_hispanic,
    COUNT(*) FILTER (WHERE majority_minority_coalition) AS n_majority_coalition
FROM fdp.ensemble_demographics
GROUP BY plan_id, draw;

COMMENT ON VIEW fdp.v_demographic_draw_stats IS
    'Per-draw count of majority-minority districts. '
    'Join draw=1 to see enacted plan; draw>1 for ensemble distribution.';


-- ---------------------------------------------------------------------------
-- View: v_demographic_distribution
-- Histogram for majority-minority district counts
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW fdp.v_demographic_distribution AS
SELECT
    plan_id,
    n_majority_black,
    n_majority_white,
    n_majority_hispanic,
    n_majority_coalition,
    COUNT(*) AS n_draws,
    ROUND(COUNT(*) * 100.0
          / SUM(COUNT(*)) OVER (PARTITION BY plan_id),
          2) AS pct_draws
FROM fdp.v_demographic_draw_stats
WHERE draw > 1
GROUP BY plan_id, n_majority_black, n_majority_white,
         n_majority_hispanic, n_majority_coalition
ORDER BY plan_id, n_majority_black DESC;

COMMENT ON VIEW fdp.v_demographic_distribution IS
    'Distribution of majority-minority district counts across simulated draws. '
    'Use for demographic histogram charts.';


-- ---------------------------------------------------------------------------
-- View: v_enacted_vs_benchmark
-- Enacted plan percentile rank and Princeton grade across all metrics
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW fdp.v_enacted_vs_benchmark AS
WITH sim AS (
    -- Ensemble draws only (draw > 1)
    SELECT
        plan_id, year, election_type, office,
        PERCENTILE_CONT(0.05) WITHIN GROUP (ORDER BY dem_seats)::NUMERIC(6,2)  AS pct05_seats,
        PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY dem_seats)::NUMERIC(6,2)  AS pct25_seats,
        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY dem_seats)::NUMERIC(6,2)  AS median_seats,
        PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY dem_seats)::NUMERIC(6,2)  AS pct75_seats,
        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY dem_seats)::NUMERIC(6,2)  AS pct95_seats,
        ROUND(AVG(dem_seats)::NUMERIC, 2)                                       AS avg_seats,
        MIN(dem_seats)                                                           AS min_seats,
        MAX(dem_seats)                                                           AS max_seats,
        ROUND(AVG(efficiency_gap)::NUMERIC, 6)                                  AS avg_eg,
        ROUND(AVG(mean_median)::NUMERIC, 6)                                     AS avg_mm,
        ROUND(AVG(n_competitive_007)::NUMERIC, 2)                               AS avg_competitive_7,
        ROUND(AVG(n_competitive_010)::NUMERIC, 2)                               AS avg_competitive_10,
        COUNT(*)                                                                 AS n_draws
    FROM fdp.ensemble_draw_stats
    WHERE draw > 1
    GROUP BY plan_id, year, election_type, office
),
enacted AS (
    SELECT plan_id, year, election_type, office,
           dem_seats    AS enacted_dem_seats,
           efficiency_gap AS enacted_eg,
           mean_median  AS enacted_mm,
           n_competitive_007 AS enacted_competitive_7,
           n_competitive_010 AS enacted_competitive_10
    FROM fdp.ensemble_draw_stats
    WHERE draw = 1
),
pctile AS (
    SELECT
        s.plan_id, s.year, s.election_type, s.office,
        ROUND(100.0 * SUM(CASE WHEN s.dem_seats <= e.enacted_dem_seats THEN 1 ELSE 0 END)
              / NULLIF(COUNT(*), 0), 1)   AS seats_pctile,
        ROUND(100.0 * SUM(CASE WHEN s.n_competitive_007 <= e.enacted_competitive_7 THEN 1 ELSE 0 END)
              / NULLIF(COUNT(*), 0), 1)   AS competitive_pctile_7
    FROM fdp.ensemble_draw_stats s
    JOIN enacted e USING (plan_id, year, election_type, office)
    WHERE s.draw > 1
    GROUP BY s.plan_id, s.year, s.election_type, s.office
)
SELECT
    e.plan_id,
    e.year,
    e.election_type,
    e.office,
    -- Enacted values
    e.enacted_dem_seats,
    e.enacted_eg           AS enacted_efficiency_gap,
    e.enacted_mm           AS enacted_mean_median,
    e.enacted_competitive_7,
    e.enacted_competitive_10,
    -- Ensemble benchmarks
    s.avg_seats,
    s.median_seats,
    s.pct05_seats,
    s.pct25_seats,
    s.pct75_seats,
    s.pct95_seats,
    s.avg_eg               AS ensemble_avg_eg,
    s.avg_mm               AS ensemble_avg_mm,
    s.avg_competitive_7    AS ensemble_avg_competitive_7,
    s.n_draws,
    -- Percentile ranks
    p.seats_pctile,
    p.competitive_pctile_7,
    -- Princeton grade (based on seat percentile)
    CASE
        WHEN p.seats_pctile BETWEEN 25 AND 75 THEN 'A'
        WHEN p.seats_pctile BETWEEN 10 AND 90 THEN 'B'
        WHEN p.seats_pctile BETWEEN  5 AND 95 THEN 'C'
        WHEN p.seats_pctile BETWEEN  1 AND 99 THEN 'F'
        ELSE 'FAIL'
    END AS princeton_grade,
    CASE
        WHEN p.seats_pctile BETWEEN 1 AND 99 THEN 'PASS'
        ELSE 'FAIL'
    END AS pass_fail
FROM enacted e
JOIN sim     s USING (plan_id, year, election_type, office)
JOIN pctile  p USING (plan_id, year, election_type, office);

COMMENT ON VIEW fdp.v_enacted_vs_benchmark IS
    'Enacted plan vs. benchmark ensemble on all metrics. '
    'seats_pctile: percentile rank of enacted seat count in ensemble distribution. '
    'Princeton grade: A = within IQR (center 50%), F = outside 5-95th pct.';


-- ---------------------------------------------------------------------------
-- View: v_correlation_competitive_partisan
-- Answers: is a map with more competitive districts also fairer on partisan lean?
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW fdp.v_correlation_competitive_partisan AS
SELECT
    plan_id,
    year,
    election_type,
    office,
    ROUND(CORR(n_competitive_007, dem_seats)::NUMERIC,     4) AS r_competitive7_dem_seats,
    ROUND(CORR(n_competitive_007, efficiency_gap)::NUMERIC, 4) AS r_competitive7_eg,
    ROUND(CORR(n_competitive_007, mean_median)::NUMERIC,    4) AS r_competitive7_mm,
    ROUND(CORR(n_competitive_010, dem_seats)::NUMERIC,     4) AS r_competitive10_dem_seats,
    COUNT(*) AS n_draws
FROM fdp.ensemble_draw_stats
WHERE draw > 1
GROUP BY plan_id, year, election_type, office
ORDER BY plan_id, year, office;

COMMENT ON VIEW fdp.v_correlation_competitive_partisan IS
    'Correlation between competitiveness and partisan fairness across ensemble draws. '
    'r_competitive7_dem_seats: does more competitive → more Dem seats? '
    'r_competitive7_eg: does more competitive → smaller efficiency gap? '
    'Positive r means they move together; negative means trade-off.';
