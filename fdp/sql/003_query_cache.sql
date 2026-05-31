-- ─────────────────────────────────────────────────────────────────────────────
-- FDP Query Cache + Question Library
-- Migration 003
--
-- Two tables:
--   fdp.question_library  — catalog of featured/bookmarked questions
--   fdp.query_cache       — cached results for any question
-- ─────────────────────────────────────────────────────────────────────────────

-- ── Question Library ─────────────────────────────────────────────────────────
-- Stores predefined (YAML-seeded) and organically bookmarked questions.
-- The YAML baseline is upserted here on every fdworkbench startup.

CREATE TABLE IF NOT EXISTS fdp.question_library (
    id             TEXT PRIMARY KEY,          -- slug: 'county_2024_president'
    question_text  TEXT NOT NULL,             -- display text shown in sidebar
    sql_query      TEXT,                      -- NULL = route through LLM
    source         TEXT NOT NULL DEFAULT 'predefined',  -- 'predefined' | 'bookmark'
    created_by     TEXT,                      -- bookmarker label (optional)
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    tags           TEXT[]       DEFAULT '{}',
    expires_hours  INTEGER,                   -- NULL = manual refresh only
    display_order  INTEGER      NOT NULL DEFAULT 0,
    is_active      BOOLEAN      NOT NULL DEFAULT TRUE
);

COMMENT ON TABLE  fdp.question_library                IS 'Catalog of featured and bookmarked policy questions with optional pre-written SQL.';
COMMENT ON COLUMN fdp.question_library.id             IS 'URL-safe slug. YAML-seeded entries keep stable IDs across restarts.';
COMMENT ON COLUMN fdp.question_library.sql_query      IS 'Pre-written SQL. NULL means the LLM generates SQL at query time.';
COMMENT ON COLUMN fdp.question_library.source         IS 'predefined = shipped in questions.yml; bookmark = promoted by an analyst at runtime.';
COMMENT ON COLUMN fdp.question_library.expires_hours  IS 'Auto-expire cache after N hours. NULL = never auto-expire (manual refresh only).';
COMMENT ON COLUMN fdp.question_library.display_order  IS 'Sidebar sort order. Lower = higher in list.';

CREATE TRIGGER trg_touch_question_library
    BEFORE UPDATE ON fdp.question_library
    FOR EACH ROW EXECUTE FUNCTION fdp.touch_row();


-- ── Query Cache ───────────────────────────────────────────────────────────────
-- Stores execution results for any question — library or ad-hoc.
-- Library questions are keyed by library_id; ad-hoc by question_hash.

CREATE TABLE IF NOT EXISTS fdp.query_cache (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    question_hash  TEXT        NOT NULL,   -- SHA-256 of normalized question text
    question_text  TEXT        NOT NULL,   -- original question as asked
    sql_query      TEXT,                   -- SQL that was executed
    result_rows    JSONB,                  -- full result set (up to max_rows)
    row_count      INTEGER,
    library_id     TEXT        REFERENCES fdp.question_library(id) ON DELETE SET NULL,
    source         TEXT        NOT NULL DEFAULT 'llm',  -- 'library' | 'llm'
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    refreshed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at     TIMESTAMPTZ,            -- NULL = never auto-expire
    hit_count      INTEGER     NOT NULL DEFAULT 0,
    is_valid       BOOLEAN     NOT NULL DEFAULT TRUE   -- FALSE = stale, re-run next time
);

COMMENT ON TABLE  fdp.query_cache              IS 'Cached query results for policy questions. Keyed by question_hash; library questions also carry library_id.';
COMMENT ON COLUMN fdp.query_cache.question_hash IS 'SHA-256 hex of lower-cased, whitespace-normalised question text.';
COMMENT ON COLUMN fdp.query_cache.result_rows   IS 'Full JSONB result set. Can be large — kept for instant retrieval without re-querying Supabase.';
COMMENT ON COLUMN fdp.query_cache.expires_at    IS 'Absolute expiry timestamp. NULL = never expires automatically.';
COMMENT ON COLUMN fdp.query_cache.is_valid       IS 'Set to FALSE by invalidate endpoint. Next request re-runs SQL and refreshes.';
COMMENT ON COLUMN fdp.query_cache.hit_count      IS 'Number of times this cache entry was served. Used for usage analytics.';

-- Fast lookups
CREATE UNIQUE INDEX IF NOT EXISTS idx_query_cache_hash   ON fdp.query_cache (question_hash) WHERE is_valid;
CREATE        INDEX IF NOT EXISTS idx_query_cache_lib    ON fdp.query_cache (library_id)    WHERE library_id IS NOT NULL;
CREATE        INDEX IF NOT EXISTS idx_query_cache_expiry ON fdp.query_cache (expires_at)    WHERE expires_at IS NOT NULL;
