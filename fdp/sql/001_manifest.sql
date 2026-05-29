-- FDP manifest schema — run once on a fresh PostgreSQL database.
-- DataManifest._init_db() runs this automatically on first connection.
-- Safe to re-run: all statements use IF NOT EXISTS / ON CONFLICT guards.

CREATE SCHEMA IF NOT EXISTS fdp;

CREATE TABLE IF NOT EXISTS fdp.datasets (
    id             TEXT        PRIMARY KEY,
    category       TEXT        NOT NULL,
    geography      TEXT        NOT NULL,
    vintage        INTEGER,
    state          TEXT        DEFAULT 'GA',
    source         TEXT,
    source_url     TEXT,
    election_type  TEXT,
    raw_file       TEXT,
    output_file    TEXT        NOT NULL,
    row_count      INTEGER,
    columns_json   TEXT,
    loaded_at      TEXT,
    checksum       TEXT,
    derived_from   TEXT,
    notes          TEXT
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS datasets_category_idx       ON fdp.datasets (category);
CREATE INDEX IF NOT EXISTS datasets_geography_idx      ON fdp.datasets (geography);
CREATE INDEX IF NOT EXISTS datasets_state_vintage_idx  ON fdp.datasets (state, vintage);
CREATE INDEX IF NOT EXISTS datasets_election_type_idx  ON fdp.datasets (election_type);
