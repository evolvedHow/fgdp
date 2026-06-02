-- =============================================================================
-- 008_normalize_competitive_counts.sql
--
-- Replaces hardcoded n_competitive_005/007/010 columns in ensemble_draw_stats
-- with a fully normalized ensemble_competitive_counts table.
--
--   Old: ensemble_draw_stats.n_competitive_005 / _007 / _010
--   New: ensemble_competitive_counts(plan_id, draw, year, election_type,
--                                    office, threshold, n_competitive)
--
-- Migrates any existing data, then drops the legacy columns.
-- Views that referenced the old columns are rebuilt here.
--
-- Apply:
--   uv run --project fdp python fdp/scripts/apply_migration.py \
--       fdp/sql/008_normalize_competitive_counts.sql
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. New normalized table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fdp.ensemble_competitive_counts (
    plan_id        TEXT         NOT NULL,
    draw           INT          NOT NULL,
    year           INT          NOT NULL,
    election_type  TEXT         NOT NULL,
    office         TEXT         NOT NULL,
    threshold      NUMERIC(5,3) NOT NULL,   -- e.g. 0.050, 0.070, 0.100
    n_competitive  INT          NOT NULL,

    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    PRIMARY KEY (plan_id, draw, year, election_type, office, threshold)
);

COMMENT ON TABLE fdp.ensemble_competitive_counts IS
    'Competitive district counts per (plan_id, draw, election, threshold). '
    'threshold = max two-party win margin for a district to be "competitive" '
    '(e.g. 0.05 = ≤5% margin). Replaces hardcoded n_competitive_NNN columns. '
    'Compute with scripts/build_draw_stats.py --thresholds 0.05 0.07.';

-- ---------------------------------------------------------------------------
-- 2. Migrate existing data from ensemble_draw_stats hardcoded columns
--    (safe to re-run — ON CONFLICT DO NOTHING)
-- ---------------------------------------------------------------------------
INSERT INTO fdp.ensemble_competitive_counts
    (plan_id, draw, year, election_type, office, threshold, n_competitive)
SELECT plan_id, draw, year, election_type, office, 0.050, n_competitive_005
FROM   fdp.ensemble_draw_stats
WHERE  n_competitive_005 IS NOT NULL
ON CONFLICT DO NOTHING;

INSERT INTO fdp.ensemble_competitive_counts
    (plan_id, draw, year, election_type, office, threshold, n_competitive)
SELECT plan_id, draw, year, election_type, office, 0.070, n_competitive_007
FROM   fdp.ensemble_draw_stats
WHERE  n_competitive_007 IS NOT NULL
ON CONFLICT DO NOTHING;

INSERT INTO fdp.ensemble_competitive_counts
    (plan_id, draw, year, election_type, office, threshold, n_competitive)
SELECT plan_id, draw, year, election_type, office, 0.100, n_competitive_010
FROM   fdp.ensemble_draw_stats
WHERE  n_competitive_010 IS NOT NULL
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3b. Drop dependent views before dropping legacy columns
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS fdp.v_correlation_competitive_partisan;
DROP VIEW IF EXISTS fdp.v_enacted_vs_benchmark;
DROP VIEW IF EXISTS fdp.v_competitive_distribution;

-- ---------------------------------------------------------------------------
-- 3c. Now safe to drop the legacy columns
-- ---------------------------------------------------------------------------
ALTER TABLE fdp.ensemble_draw_stats
    DROP COLUMN IF EXISTS n_competitive_005,
    DROP COLUMN IF EXISTS n_competitive_007,
    DROP COLUMN IF EXISTS n_competitive_010;

-- ---------------------------------------------------------------------------
-- 4. Rebuild views
-- ---------------------------------------------------------------------------

-- v_competitive_distribution — one row per (plan_id, year, office, threshold, n_competitive)
CREATE OR REPLACE VIEW fdp.v_competitive_distribution AS
SELECT
    c.plan_id,
    c.year,
    c.election_type,
    c.office,
    c.threshold,
    c.n_competitive,
    COUNT(*)                                                                AS n_draws,
    ROUND(COUNT(*) * 100.0
          / SUM(COUNT(*)) OVER (
              PARTITION BY c.plan_id, c.year, c.election_type, c.office, c.threshold
          ), 2)                                                             AS pct_draws
FROM fdp.ensemble_competitive_counts c
WHERE c.draw > 1
GROUP BY c.plan_id, c.year, c.election_type, c.office, c.threshold, c.n_competitive
ORDER BY c.plan_id, c.year, c.office, c.threshold, c.n_competitive;

COMMENT ON VIEW fdp.v_competitive_distribution IS
    'Histogram of competitive district counts across simulated draws. '
    'One threshold value per set of rows. Filter by threshold to pick the metric.';

-- v_enacted_vs_benchmark — pivot competitive thresholds as separate columns per threshold
-- (uses conditional aggregation so arbitrary thresholds work)
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
        COUNT(*)                                                                 AS n_draws
    FROM fdp.ensemble_draw_stats
    WHERE draw > 1
    GROUP BY plan_id, year, election_type, office
),
enacted AS (
    SELECT plan_id, year, election_type, office,
           dem_seats    AS enacted_dem_seats,
           efficiency_gap AS enacted_eg,
           mean_median  AS enacted_mm
    FROM fdp.ensemble_draw_stats
    WHERE draw = 1
),
-- Competitive stats aggregated per (plan_id, year, office) across thresholds
comp_sim AS (
    SELECT plan_id, year, election_type, office, threshold,
           ROUND(AVG(n_competitive)::NUMERIC, 2)  AS avg_competitive,
           MIN(n_competitive)                      AS min_competitive,
           MAX(n_competitive)                      AS max_competitive
    FROM fdp.ensemble_competitive_counts
    WHERE draw > 1
    GROUP BY plan_id, year, election_type, office, threshold
),
comp_enacted AS (
    SELECT plan_id, year, election_type, office, threshold,
           n_competitive AS enacted_competitive
    FROM fdp.ensemble_competitive_counts
    WHERE draw = 1
),
pctile AS (
    SELECT
        s.plan_id, s.year, s.election_type, s.office,
        ROUND(100.0 * SUM(CASE WHEN s.dem_seats <= e.enacted_dem_seats THEN 1 ELSE 0 END)
              / NULLIF(COUNT(*), 0), 1)   AS seats_pctile
    FROM fdp.ensemble_draw_stats s
    JOIN enacted e USING (plan_id, year, election_type, office)
    WHERE s.draw > 1
    GROUP BY s.plan_id, s.year, s.election_type, s.office
),
-- Competitive percentile: what fraction of simulated draws have <= enacted competitive count?
-- (lower enacted = more packed = worse for democracy → enacted_pctile near 0% is bad)
comp_pctile AS (
    SELECT
        c.plan_id, c.year, c.election_type, c.office, c.threshold,
        ROUND(100.0 * SUM(CASE WHEN c.n_competitive >= ce.enacted_competitive THEN 1 ELSE 0 END)
              / NULLIF(COUNT(*), 0), 1)  AS competitive_pctile
        -- "pct of simulated maps with AT LEAST as many competitive districts as enacted"
        -- 100% = enacted is maximally uncompetitive (all simulated maps beat it)
    FROM fdp.ensemble_competitive_counts c
    JOIN comp_enacted ce USING (plan_id, year, election_type, office, threshold)
    WHERE c.draw > 1
    GROUP BY c.plan_id, c.year, c.election_type, c.office, c.threshold
)
SELECT
    e.plan_id,
    e.year,
    e.election_type,
    e.office,
    -- Enacted partisan values
    e.enacted_dem_seats,
    e.enacted_eg       AS enacted_efficiency_gap,
    e.enacted_mm       AS enacted_mean_median,
    -- Ensemble partisan benchmarks
    s.avg_seats,
    s.median_seats,
    s.pct05_seats,
    s.pct25_seats,
    s.pct75_seats,
    s.pct95_seats,
    s.avg_eg           AS ensemble_avg_eg,
    s.avg_mm           AS ensemble_avg_mm,
    s.n_draws,
    -- Partisan percentile + Princeton grade
    p.seats_pctile,
    CASE
        WHEN p.seats_pctile BETWEEN 25 AND 75 THEN 'A'
        WHEN p.seats_pctile BETWEEN 10 AND 90 THEN 'B'
        WHEN p.seats_pctile BETWEEN  5 AND 95 THEN 'C'
        WHEN p.seats_pctile BETWEEN  1 AND 99 THEN 'F'
        ELSE 'FAIL'
    END AS princeton_grade,
    CASE WHEN p.seats_pctile BETWEEN 1 AND 99 THEN 'PASS' ELSE 'FAIL' END AS pass_fail
FROM enacted e
JOIN sim     s USING (plan_id, year, election_type, office)
JOIN pctile  p USING (plan_id, year, election_type, office);
-- Note: competitive counts are in v_competitive_distribution / ensemble_competitive_counts.
-- Join them separately by threshold when needed.

COMMENT ON VIEW fdp.v_enacted_vs_benchmark IS
    'Enacted plan vs. benchmark ensemble on partisan metrics. '
    'Competitive counts are in ensemble_competitive_counts (join by threshold). '
    'Princeton grade based on seats_pctile: A=25–75, B=10–90, C=5–95, F=1–99.';

-- v_correlation_competitive_partisan — corr between competitiveness and partisan lean per threshold
CREATE OR REPLACE VIEW fdp.v_correlation_competitive_partisan AS
SELECT
    c.plan_id,
    c.year,
    c.election_type,
    c.office,
    c.threshold,
    ROUND(CORR(c.n_competitive, d.dem_seats)::NUMERIC,      4) AS r_competitive_dem_seats,
    ROUND(CORR(c.n_competitive, d.efficiency_gap)::NUMERIC,  4) AS r_competitive_eg,
    ROUND(CORR(c.n_competitive, d.mean_median)::NUMERIC,     4) AS r_competitive_mm,
    COUNT(*)                                                     AS n_draws
FROM fdp.ensemble_competitive_counts c
JOIN fdp.ensemble_draw_stats          d
     USING (plan_id, draw, year, election_type, office)
WHERE c.draw > 1
GROUP BY c.plan_id, c.year, c.election_type, c.office, c.threshold
ORDER BY c.plan_id, c.year, c.office, c.threshold;

COMMENT ON VIEW fdp.v_correlation_competitive_partisan IS
    'Correlation between competitive district count and partisan metrics, per threshold. '
    'r_competitive_dem_seats > 0: more competitive → more Dem seats. '
    'Filter by threshold to compare across margin definitions.';
