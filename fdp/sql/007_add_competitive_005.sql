-- =============================================================================
-- 007_add_competitive_005.sql
--
-- Adds n_competitive_005 column to fdp.ensemble_draw_stats (5% win margin).
-- Updates dependent views to expose the new column.
--
-- Apply with:
--   psql $DATABASE_URL -f fdp/sql/007_add_competitive_005.sql
-- Or:
--   uv run --project fdp python fdp/scripts/apply_migration.py fdp/sql/007_add_competitive_005.sql
-- =============================================================================

ALTER TABLE fdp.ensemble_draw_stats
    ADD COLUMN IF NOT EXISTS n_competitive_005 INT;

COMMENT ON COLUMN fdp.ensemble_draw_stats.n_competitive_005 IS
    'Districts where the two-party winning margin is ≤ 5%. Tightest competitiveness metric.';

-- Drop dependent views before recreating with new column signatures.
DROP VIEW IF EXISTS fdp.v_correlation_competitive_partisan;
DROP VIEW IF EXISTS fdp.v_enacted_vs_benchmark;
DROP VIEW IF EXISTS fdp.v_competitive_distribution;

-- v_competitive_distribution: add n_competitive_005 to GROUP BY and SELECT.
CREATE OR REPLACE VIEW fdp.v_competitive_distribution AS
SELECT
    plan_id,
    year,
    election_type,
    office,
    n_competitive_005,
    n_competitive_007,
    n_competitive_010,
    COUNT(*) AS n_draws,
    ROUND(COUNT(*) * 100.0
          / SUM(COUNT(*)) OVER (PARTITION BY plan_id, year, election_type, office),
          2) AS pct_draws
FROM fdp.ensemble_draw_stats
WHERE draw > 1
GROUP BY plan_id, year, election_type, office,
         n_competitive_005, n_competitive_007, n_competitive_010
ORDER BY plan_id, year, office, n_competitive_005;

-- v_enacted_vs_benchmark: add enacted_competitive_5 and ensemble_avg_competitive_5.
CREATE OR REPLACE VIEW fdp.v_enacted_vs_benchmark AS
WITH sim AS (
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
        ROUND(AVG(n_competitive_005)::NUMERIC, 2)                               AS avg_competitive_5,
        ROUND(AVG(n_competitive_007)::NUMERIC, 2)                               AS avg_competitive_7,
        ROUND(AVG(n_competitive_010)::NUMERIC, 2)                               AS avg_competitive_10,
        COUNT(*)                                                                 AS n_draws
    FROM fdp.ensemble_draw_stats
    WHERE draw > 1
    GROUP BY plan_id, year, election_type, office
),
enacted AS (
    SELECT plan_id, year, election_type, office,
           dem_seats          AS enacted_dem_seats,
           efficiency_gap     AS enacted_eg,
           mean_median        AS enacted_mm,
           n_competitive_005  AS enacted_competitive_5,
           n_competitive_007  AS enacted_competitive_7,
           n_competitive_010  AS enacted_competitive_10
    FROM fdp.ensemble_draw_stats
    WHERE draw = 1
),
pctile AS (
    SELECT
        s.plan_id, s.year, s.election_type, s.office,
        ROUND(100.0 * SUM(CASE WHEN s.dem_seats <= e.enacted_dem_seats THEN 1 ELSE 0 END)
              / NULLIF(COUNT(*), 0), 1)   AS seats_pctile,
        ROUND(100.0 * SUM(CASE WHEN s.n_competitive_005 <= e.enacted_competitive_5 THEN 1 ELSE 0 END)
              / NULLIF(COUNT(*), 0), 1)   AS competitive_pctile_5,
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
    e.enacted_competitive_5,
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
    s.avg_competitive_5    AS ensemble_avg_competitive_5,
    s.avg_competitive_7    AS ensemble_avg_competitive_7,
    s.n_draws,
    -- Percentile ranks
    p.seats_pctile,
    p.competitive_pctile_5,
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

-- v_correlation_competitive_partisan: add n_competitive_005 correlations.
CREATE OR REPLACE VIEW fdp.v_correlation_competitive_partisan AS
SELECT
    plan_id,
    year,
    election_type,
    office,
    ROUND(CORR(n_competitive_005, dem_seats)::NUMERIC,     4) AS r_competitive5_dem_seats,
    ROUND(CORR(n_competitive_005, efficiency_gap)::NUMERIC, 4) AS r_competitive5_eg,
    ROUND(CORR(n_competitive_007, dem_seats)::NUMERIC,     4) AS r_competitive7_dem_seats,
    ROUND(CORR(n_competitive_007, efficiency_gap)::NUMERIC, 4) AS r_competitive7_eg,
    ROUND(CORR(n_competitive_007, mean_median)::NUMERIC,    4) AS r_competitive7_mm,
    COUNT(*) AS n_draws
FROM fdp.ensemble_draw_stats
WHERE draw > 1
GROUP BY plan_id, year, election_type, office
ORDER BY plan_id, year, office;
