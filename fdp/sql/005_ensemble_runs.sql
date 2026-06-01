-- =============================================================================
-- 005_ensemble_runs.sql — Run catalog for ensemble benchmark runs
--
-- Every ensemble run (CLI or API) writes one row here before the chain starts
-- and updates it on completion or failure.  The 'params' column stores the
-- full resolved configuration (YAML defaults + CLI overrides merged), so any
-- run can be reproduced exactly from this table.
--
-- Apply with:
--   psql $DATABASE_URL -f fdp/sql/005_ensemble_runs.sql
-- =============================================================================

-- ----------------------------------------------------------------------------
-- Table
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fdp.ensemble_runs (
    -- Identity
    run_name        TEXT        PRIMARY KEY,       -- user-supplied; unique per run
    benchmark_id    TEXT        NOT NULL,           -- YAML config template used

    -- Lifecycle
    status          TEXT        NOT NULL DEFAULT 'pending',
    --  pending   → created via API before run starts
    --  running   → chain is executing
    --  completed → chain finished, assignments saved, scoring done
    --  failed    → chain or post-processing errored

    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,

    -- Full resolved parameters (YAML + CLI overrides, merged)
    -- Stored as JSONB so any run can be exactly reproduced.
    params          JSONB       NOT NULL DEFAULT '{}',

    -- Summary stats (populated on completion)
    n_draws         INT,                            -- plans actually saved (steps - burn_in)
    n_vtds          INT,                            -- number of geographic units
    n_chains_run    INT,                            -- chains actually completed
    runtime_seconds NUMERIC(10,1),

    -- Output file locations (relative to repo root)
    plans_file      TEXT,                           -- e.g. fdp/data/repos/main/ensemble/my_run_plans.parquet
    scores_file     TEXT,
    demographics_file TEXT,
    draw_stats_file TEXT,

    -- Error info (only set if status = 'failed')
    error_message   TEXT,

    -- Free-text notes
    notes           TEXT,

    -- Audit
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    loaded_by       TEXT        DEFAULT 'run_ensemble.py'
);

COMMENT ON TABLE fdp.ensemble_runs IS
    'Run catalog: one row per ensemble benchmark run. Stores all resolved params and output file paths.';

COMMENT ON COLUMN fdp.ensemble_runs.run_name      IS 'User-supplied unique run identifier. Becomes plan_id in ensemble_scores.';
COMMENT ON COLUMN fdp.ensemble_runs.benchmark_id  IS 'YAML template used (e.g. ga_congress_2026_v1).';
COMMENT ON COLUMN fdp.ensemble_runs.status        IS 'pending | running | completed | failed';
COMMENT ON COLUMN fdp.ensemble_runs.params        IS 'Full resolved config: YAML defaults merged with CLI overrides. Sufficient to reproduce the run.';
COMMENT ON COLUMN fdp.ensemble_runs.n_draws       IS 'Plans saved = n_steps - burn_in (per chain).';
COMMENT ON COLUMN fdp.ensemble_runs.plans_file    IS 'Path to parquet with columns [plan_id, draw, geoid, district, geo_level, state, chamber].';

-- ----------------------------------------------------------------------------
-- Auto-update trigger (keeps updated_at current)
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION fdp.touch_ensemble_runs()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_touch_ensemble_runs ON fdp.ensemble_runs;
CREATE TRIGGER trg_touch_ensemble_runs
    BEFORE UPDATE ON fdp.ensemble_runs
    FOR EACH ROW EXECUTE FUNCTION fdp.touch_ensemble_runs();

-- ----------------------------------------------------------------------------
-- Convenience view: recent runs with human-readable status
-- ----------------------------------------------------------------------------

CREATE OR REPLACE VIEW fdp.v_ensemble_runs AS
SELECT
    run_name,
    benchmark_id,
    status,
    started_at,
    completed_at,
    CASE
        WHEN completed_at IS NOT NULL AND started_at IS NOT NULL
        THEN ROUND(EXTRACT(EPOCH FROM (completed_at - started_at)) / 60.0, 1)
        ELSE NULL
    END                                     AS runtime_minutes,
    n_draws,
    n_vtds,
    n_chains_run,
    params -> 'chamber' ->> 'name'          AS chamber,
    params -> 'mcmc' ->> 'algorithm'        AS algorithm,
    (params -> 'mcmc' ->> 'n_steps')::INT   AS n_steps,
    (params -> 'mcmc' ->> 'burn_in')::INT   AS burn_in,
    plans_file,
    error_message,
    notes,
    created_at
FROM fdp.ensemble_runs
ORDER BY created_at DESC;

COMMENT ON VIEW fdp.v_ensemble_runs IS
    'Human-readable run catalog with key params extracted from the JSONB params column.';
