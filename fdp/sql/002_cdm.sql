-- FDP Common Data Model — geography-hierarchy-aware analytical schema.
-- Run via: fdp init-db
-- All CREATE statements are idempotent (IF NOT EXISTS / CREATE OR REPLACE).
--
-- Design principles:
--   • One row per natural business key — no one-table-per-year sprawl
--   • Any geography level — block, block_group, tract, vtd, precinct, county, district, state
--   • UPSERT-friendly — new data is always INSERT … ON CONFLICT DO UPDATE
--   • DELETE-friendly — remove by (state, year, geo_level) or (state, year, election_type)
--   • Extensible — new states, years, offices, geo levels require no schema changes
--   • Audit trail — every table has created_at, updated_at, update_count, loaded_by
--   • Self-documenting — every table and column carries a COMMENT
--
-- Migration note:
--   fdp.vtd is replaced by fdp.geography.  The old vtd rows become geography rows
--   with geo_level = 'vtd', geo_type = 'census'.  Any code that joined on fdp.vtd
--   should join on fdp.geography WHERE geo_level = 'vtd'.

-- ============================================================================
-- Audit trigger — applied to every table
-- ============================================================================

CREATE OR REPLACE FUNCTION fdp.touch_row()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at   := NOW();
    NEW.update_count := COALESCE(OLD.update_count, 0) + 1;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION fdp.touch_row() IS
'Reusable BEFORE UPDATE trigger that bumps updated_at to NOW() and increments '
'update_count on every row modification.  Applied to every FDP table so that '
'data-stability audits can detect rows that changed more times than expected.';


-- ============================================================================
-- Drop legacy table (replaced by fdp.geography)
-- ============================================================================

-- Views that reference fdp.vtd must be dropped before the table can be altered.
-- All views are recreated at the bottom of this file.
DROP VIEW IF EXISTS fdp.v_vtd_demographics;
DROP VIEW IF EXISTS fdp.v_election_2pv;
DROP VIEW IF EXISTS fdp.v_county_results;
DROP VIEW IF EXISTS fdp.v_statewide_results;

-- Drop old fdp.vtd (replaced by fdp.geography).
DROP TABLE IF EXISTS fdp.vtd CASCADE;

-- Drop fact tables when they still carry the old geoid20 primary key.
-- After the tables are recreated with 'geoid' as PK this block is a no-op.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'fdp'
          AND table_name   = 'election_results'
          AND column_name  = 'geoid20'
    ) THEN
        DROP TABLE IF EXISTS fdp.election_results CASCADE;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'fdp'
          AND table_name   = 'cvap'
          AND column_name  = 'geoid20'
    ) THEN
        DROP TABLE IF EXISTS fdp.cvap CASCADE;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'fdp'
          AND table_name   = 'ensemble_plans'
          AND column_name  = 'geoid20'
    ) THEN
        DROP TABLE IF EXISTS fdp.ensemble_plans CASCADE;
    END IF;
END$$;


-- ============================================================================
-- fdp.geography  — central register for every geographic unit at any level
-- ============================================================================

CREATE TABLE IF NOT EXISTS fdp.geography (
    geoid           TEXT        NOT NULL,
    geo_level       TEXT        NOT NULL,
    geo_type        TEXT        NOT NULL DEFAULT 'census',
    state           TEXT        NOT NULL,
    county_fips     TEXT,
    name            TEXT,
    vintage_year    INTEGER     NOT NULL DEFAULT 2020,
    source          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    update_count    INTEGER     NOT NULL DEFAULT 0,
    loaded_by       TEXT,
    PRIMARY KEY (geoid, vintage_year)
);

COMMENT ON TABLE fdp.geography IS
'Central register for every geographic unit used in the FDP — one row per '
'(geoid, vintage_year).  Replaces the old fdp.vtd table and extends it to any '
'level of the Census/political hierarchy: '
'block_fusion | block | block_group | tract | vtd | precinct | county | district | state. '
'Every geoid in every fact table (election_results, cvap, population, ensemble_plans) '
'must have a corresponding row here.  The vintage_year column distinguishes 2010 '
'boundaries from 2020 boundaries — a 2010 precinct and a 2020 precinct with the same '
'code are different rows.';

COMMENT ON COLUMN fdp.geography.geoid IS
'Geographic identifier.  For Census units: standard FIPS codes (2-char state, '
'5-char county, 11-char VTD/tract, 12-char block group, 15-char block). '
'For political units (precincts, districts): state-issued codes. '
'Census GEOIDs encode their own hierarchy — rollup is LEFT(geoid, N): '
'  2  chars → state '
'  5  chars → county '
'  11 chars → VTD or census tract '
'  12 chars → block group '
'  15 chars → census block '
'For political geographies this truncation trick does NOT apply — use geo_crosswalk.';

COMMENT ON COLUMN fdp.geography.geo_level IS
'Level of this geographic unit.  Canonical values: '
'block_fusion | block | block_group | tract | vtd | precinct | county | district | state. '
'block_fusion = a Census block that has been fused with an adjacent block to eliminate '
'zero-population slivers (used in some RDH disaggregation products).';

COMMENT ON COLUMN fdp.geography.geo_type IS
'Source classification: census (Census Bureau units) or political (election-board units). '
'Census units nest perfectly by design.  Political units may not align with Census '
'boundaries — use fdp.geo_crosswalk for cross-type joins.';

COMMENT ON COLUMN fdp.geography.state IS
'State abbreviation (GA, NC, …).';

COMMENT ON COLUMN fdp.geography.county_fips IS
'5-character county FIPS.  For Census units this is always LEFT(geoid, 5). '
'For political units it is the county in which the unit falls; NULL if multi-county.';

COMMENT ON COLUMN fdp.geography.name IS
'Human-readable label (e.g. "Fulton County", "VTD 000001", "District 5").';

COMMENT ON COLUMN fdp.geography.vintage_year IS
'Boundary year used for this geoid.  Default 2020.  '
'Set at load time via the FDP_VINTAGE_YEAR env var or the --vintage CLI flag. '
'A row with vintage_year=2010 and a row with vintage_year=2020 for the same geoid '
'represent different geographic boundaries and are stored as separate rows.';

COMMENT ON COLUMN fdp.geography.source IS
'Data source: Census | state_election_board | derived.';

COMMENT ON COLUMN fdp.geography.created_at IS 'Timestamp when this row was first inserted.';
COMMENT ON COLUMN fdp.geography.updated_at  IS 'Timestamp of the last UPDATE to this row.';
COMMENT ON COLUMN fdp.geography.update_count IS
'Number of times this row has been UPDATEd (not counting the initial INSERT). '
'A value > 0 on a supposedly write-once row is a signal worth investigating.';
COMMENT ON COLUMN fdp.geography.loaded_by IS
'CLI command or process that last wrote this row (e.g. "fdp load-pg").';

CREATE INDEX IF NOT EXISTS geo_state_level_idx
    ON fdp.geography (state, geo_level);
CREATE INDEX IF NOT EXISTS geo_county_fips_idx
    ON fdp.geography (county_fips);
CREATE INDEX IF NOT EXISTS geo_vintage_idx
    ON fdp.geography (vintage_year);

CREATE OR REPLACE TRIGGER trg_touch_geography
    BEFORE UPDATE ON fdp.geography
    FOR EACH ROW EXECUTE FUNCTION fdp.touch_row();


-- ============================================================================
-- fdp.geo_crosswalk  — political ↔ Census boundary bridge
-- ============================================================================

CREATE TABLE IF NOT EXISTS fdp.geo_crosswalk (
    from_geoid      TEXT        NOT NULL,
    to_geoid        TEXT        NOT NULL,
    from_level      TEXT        NOT NULL,
    to_level        TEXT        NOT NULL,
    method          TEXT        NOT NULL DEFAULT 'centroid',
    weight          NUMERIC(8,6) NOT NULL DEFAULT 1.0,
    vintage_year    INTEGER     NOT NULL DEFAULT 2020,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    update_count    INTEGER     NOT NULL DEFAULT 0,
    loaded_by       TEXT,
    PRIMARY KEY (from_geoid, to_geoid, vintage_year)
);

COMMENT ON TABLE fdp.geo_crosswalk IS
'Maps geographic units across boundary systems — primarily political units '
'(precincts, districts) to Census units (blocks, VTDs), but also Census-to-Census '
'crosswalks across decennial vintages (e.g. 2010 tract → 2020 tract). '
'This table is defined now to lock the schema design; it will be populated '
'when the disaggregation pipeline is built. '
'For any pair where one boundary perfectly contains the other, weight = 1.0. '
'For partial containments (a precinct that straddles two Census blocks), '
'weight is the fractional overlap (areal or dasymetric).  '
'SUM(weight) over all to_geoid for a given from_geoid should equal 1.0.';

COMMENT ON COLUMN fdp.geo_crosswalk.from_geoid IS 'Source geographic unit (e.g. precinct GEOID).';
COMMENT ON COLUMN fdp.geo_crosswalk.to_geoid   IS 'Target geographic unit (e.g. Census block GEOID).';
COMMENT ON COLUMN fdp.geo_crosswalk.from_level IS 'geo_level of from_geoid (e.g. precinct).';
COMMENT ON COLUMN fdp.geo_crosswalk.to_level   IS 'geo_level of to_geoid (e.g. block).';
COMMENT ON COLUMN fdp.geo_crosswalk.method IS
'Disaggregation method: exact | centroid | dasymetric | areal_interpolation. '
'exact = one-to-one boundary match.  centroid = block centroid falls within source unit. '
'dasymetric = VAP_MOD-weighted fractional overlap.  areal_interpolation = area-weighted.';
COMMENT ON COLUMN fdp.geo_crosswalk.weight IS
'Fractional weight 0.0–1.0.  For exact/centroid matches this is always 1.0. '
'For dasymetric splits this is the fraction of the source unit''s population '
'that falls within the target unit.';
COMMENT ON COLUMN fdp.geo_crosswalk.vintage_year IS
'Which vintage of boundaries both geoids belong to.';

COMMENT ON COLUMN fdp.geo_crosswalk.created_at   IS 'Timestamp when this row was first inserted.';
COMMENT ON COLUMN fdp.geo_crosswalk.updated_at   IS 'Timestamp of the last UPDATE to this row.';
COMMENT ON COLUMN fdp.geo_crosswalk.update_count IS 'Number of UPDATEs to this row.';
COMMENT ON COLUMN fdp.geo_crosswalk.loaded_by    IS 'CLI command or process that last wrote this row.';

CREATE INDEX IF NOT EXISTS xwalk_from_idx ON fdp.geo_crosswalk (from_geoid, from_level);
CREATE INDEX IF NOT EXISTS xwalk_to_idx   ON fdp.geo_crosswalk (to_geoid,   to_level);
CREATE INDEX IF NOT EXISTS xwalk_vintage_idx ON fdp.geo_crosswalk (vintage_year);

CREATE OR REPLACE TRIGGER trg_touch_geo_crosswalk
    BEFORE UPDATE ON fdp.geo_crosswalk
    FOR EACH ROW EXECUTE FUNCTION fdp.touch_row();


-- ============================================================================
-- fdp.population  — Decennial Census P.L. 94-171 demographic data
-- ============================================================================

CREATE TABLE IF NOT EXISTS fdp.population (
    geoid           TEXT        NOT NULL,
    geo_level       TEXT        NOT NULL,
    state           TEXT        NOT NULL,
    census_year     INTEGER     NOT NULL,
    pop_total       BIGINT,
    vap_total       BIGINT,
    vap_mod         BIGINT,
    pop_white       BIGINT,
    pop_black       BIGINT,
    pop_hispanic    BIGINT,
    pop_asian       BIGINT,
    pop_ami         BIGINT,
    pop_nhp         BIGINT,
    pop_multi       BIGINT,
    vap_white       BIGINT,
    vap_black       BIGINT,
    vap_hispanic    BIGINT,
    vap_asian       BIGINT,
    source          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    update_count    INTEGER     NOT NULL DEFAULT 0,
    loaded_by       TEXT,
    PRIMARY KEY (geoid, census_year)
);

COMMENT ON TABLE fdp.population IS
'Decennial Census P.L. 94-171 demographic data at any geographic level. '
'Kept separate from fdp.cvap because the sources, cadence, and methodology differ: '
'  • population = Census Bureau 100% count, released ~1 year after Census Day '
'  • cvap       = ACS 5-year estimate + Census Bureau CVAP special tabulation, '
'                 released annually, based on a sample survey '
'Both tables carry a year column, but their semantics differ: population.census_year '
'is always a decennial year (2010, 2020) whereas cvap.year is an ACS end year (2019–2024).';

COMMENT ON COLUMN fdp.population.geoid       IS 'Geographic identifier — FK to fdp.geography.geoid.';
COMMENT ON COLUMN fdp.population.geo_level   IS 'Level of this row: block | vtd | county | state | …';
COMMENT ON COLUMN fdp.population.state       IS 'State abbreviation.';
COMMENT ON COLUMN fdp.population.census_year IS 'Decennial Census year: 2010 or 2020.';
COMMENT ON COLUMN fdp.population.pop_total   IS 'Total population (P0010001).';
COMMENT ON COLUMN fdp.population.vap_total   IS 'Total Voting Age Population 18+ (P0030001).';
COMMENT ON COLUMN fdp.population.vap_mod IS
'Modified VAP = P0040001 − P0050003 (total VAP minus persons in correctional '
'facilities for adults, juvenile facilities, etc.).  '
'Always use vap_mod as the disaggregation weight — never raw VAP — because '
'Georgia has significant prison populations in rural counties (Telfair, Stewart, '
'Wheeler) that inflate raw VAP and distort block-to-VTD aggregation.';
COMMENT ON COLUMN fdp.population.pop_white   IS 'White alone population (P0010003).';
COMMENT ON COLUMN fdp.population.pop_black   IS 'Black or African American alone population (P0010004).';
COMMENT ON COLUMN fdp.population.pop_hispanic IS 'Hispanic or Latino population, any race (P0020002).';
COMMENT ON COLUMN fdp.population.pop_asian   IS 'Asian alone population (P0010006).';
COMMENT ON COLUMN fdp.population.pop_ami     IS 'American Indian or Alaska Native alone (P0010005).';
COMMENT ON COLUMN fdp.population.pop_nhp     IS 'Native Hawaiian or Other Pacific Islander alone (P0010007).';
COMMENT ON COLUMN fdp.population.pop_multi   IS 'Two or more races population (P0010009).';
COMMENT ON COLUMN fdp.population.vap_white   IS 'White alone VAP (P0040005).';
COMMENT ON COLUMN fdp.population.vap_black   IS 'Black or African American alone VAP (P0040006).';
COMMENT ON COLUMN fdp.population.vap_hispanic IS 'Hispanic or Latino VAP, any race (P0040002).';
COMMENT ON COLUMN fdp.population.vap_asian   IS 'Asian alone VAP (P0040008).';
COMMENT ON COLUMN fdp.population.source      IS 'Data source: Census | derived.';

COMMENT ON COLUMN fdp.population.created_at   IS 'Timestamp when this row was first inserted.';
COMMENT ON COLUMN fdp.population.updated_at   IS 'Timestamp of the last UPDATE to this row.';
COMMENT ON COLUMN fdp.population.update_count IS 'Number of UPDATEs to this row.';
COMMENT ON COLUMN fdp.population.loaded_by    IS 'CLI command or process that last wrote this row.';

CREATE INDEX IF NOT EXISTS pop_state_level_idx
    ON fdp.population (state, geo_level);
CREATE INDEX IF NOT EXISTS pop_census_year_idx
    ON fdp.population (census_year);

CREATE OR REPLACE TRIGGER trg_touch_population
    BEFORE UPDATE ON fdp.population
    FOR EACH ROW EXECUTE FUNCTION fdp.touch_row();


-- ============================================================================
-- fdp.election_results  — All candidate vote totals, normalized, any geo level
-- ============================================================================

CREATE TABLE IF NOT EXISTS fdp.election_results (
    geoid                TEXT    NOT NULL,
    geo_level            TEXT    NOT NULL DEFAULT 'vtd',
    collection_geo_level TEXT,
    state                TEXT    NOT NULL DEFAULT 'GA',
    year                 INTEGER NOT NULL,
    election_type        TEXT    NOT NULL,
    office               TEXT    NOT NULL,
    party                TEXT    NOT NULL,
    candidate            TEXT    NOT NULL DEFAULT '',
    votes                BIGINT  NOT NULL DEFAULT 0,
    source               TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    update_count    INTEGER     NOT NULL DEFAULT 0,
    loaded_by       TEXT,
    PRIMARY KEY (geoid, year, election_type, office, party, candidate)
);

COMMENT ON TABLE fdp.election_results IS
'Normalized election results — one row per geoid × year × election_type × office × party × candidate. '
'All years, races, and geographic levels coexist in this single table. '
'Query by office, year, election_type, or geo_level without changing tables. '
'New elections are added via UPSERT (INSERT … ON CONFLICT DO UPDATE). '
'Delete a specific election: DELETE WHERE state=''GA'' AND year=2022 AND election_type=''general''. '
'Supports data at any geographic level (block through state) via the geo_level column.';

COMMENT ON COLUMN fdp.election_results.geoid IS
'Geographic identifier — FK to fdp.geography.geoid and join key to the ALARM redist_map.';

COMMENT ON COLUMN fdp.election_results.geo_level IS
'Level of the geoid in this row: block | vtd | precinct | county | district | state. '
'Most rows will be geo_level=''vtd'' or geo_level=''precinct''.';

COMMENT ON COLUMN fdp.election_results.collection_geo_level IS
'The level at which votes were originally counted by the election board before any '
'disaggregation or aggregation.  For RDH block-disaggregated data this will be ''precinct''. '
'For data loaded directly from a VTD shapefile it will be ''vtd''. '
'Null means unknown/not recorded.  This is an audit field — it does not change the '
'analytical meaning of the row, but it lets you trace any dasymetric transformations '
'back to their source level.';

COMMENT ON COLUMN fdp.election_results.state IS
'State abbreviation. Allows multi-state use of this table without schema changes.';

COMMENT ON COLUMN fdp.election_results.year IS
'Election year (e.g. 2022). For runoffs that span calendar years (e.g. Jan 2021 Georgia '
'runoffs), use the year the race was originally scheduled (2020).';

COMMENT ON COLUMN fdp.election_results.election_type IS
'Election type: general | runoff | special | primary. '
'The 2022 November general and the 2022 December Warnock/Walker runoff are both year=2022 '
'but have different election_type values.';

COMMENT ON COLUMN fdp.election_results.office IS
'Office or race, lowercase canonical name: '
'governor | senate | president | attorney-general | secretary-of-state | '
'lt-governor | public-service-commission | insurance-commissioner | '
'labor-commissioner | agriculture-commissioner | superintendent | amendments. '
'Derived from RDH race code via race_registry.py.';

COMMENT ON COLUMN fdp.election_results.party IS
'Party abbreviation, lowercase: dem | rep | lib | grn | ind | other. '
'Derived from the RDH column party code: D→dem, R→rep, L→lib, G→grn, I→ind.';

COMMENT ON COLUMN fdp.election_results.candidate IS
'Candidate surname or RDH code in lowercase (e.g. abrams, kemp, warnock, walker). '
'Included in the primary key to support multi-candidate primaries where two candidates '
'from the same party run for the same office.';

COMMENT ON COLUMN fdp.election_results.votes IS
'Vote count for this candidate in this geographic unit. '
'When geo_level=''vtd'', aggregated from 2020 Census blocks using centroid-in-polygon '
'spatial join, weighted by vap_mod (not raw VAP).  Source: RDH block-level election files.';

COMMENT ON COLUMN fdp.election_results.source IS
'Data source: RDH | VEST | derived.';

COMMENT ON COLUMN fdp.election_results.created_at   IS 'Timestamp when this row was first inserted.';
COMMENT ON COLUMN fdp.election_results.updated_at   IS 'Timestamp of the last UPDATE to this row.';
COMMENT ON COLUMN fdp.election_results.update_count IS 'Number of UPDATEs to this row.';
COMMENT ON COLUMN fdp.election_results.loaded_by    IS 'CLI command or process that last wrote this row.';

-- Indexes for the most common query patterns
CREATE INDEX IF NOT EXISTS er_year_office_idx
    ON fdp.election_results (year, office);
CREATE INDEX IF NOT EXISTS er_office_party_idx
    ON fdp.election_results (office, party);
CREATE INDEX IF NOT EXISTS er_geoid_idx
    ON fdp.election_results (geoid);
CREATE INDEX IF NOT EXISTS er_county_idx
    ON fdp.election_results (LEFT(geoid, 5));
CREATE INDEX IF NOT EXISTS er_year_etype_idx
    ON fdp.election_results (year, election_type);
CREATE INDEX IF NOT EXISTS er_geo_level_idx
    ON fdp.election_results (geo_level);

CREATE OR REPLACE TRIGGER trg_touch_election_results
    BEFORE UPDATE ON fdp.election_results
    FOR EACH ROW EXECUTE FUNCTION fdp.touch_row();


-- ============================================================================
-- fdp.cvap  — Citizen Voting Age Population by geography and ACS year
-- ============================================================================

CREATE TABLE IF NOT EXISTS fdp.cvap (
    geoid           TEXT        NOT NULL,
    geo_level       TEXT        NOT NULL DEFAULT 'vtd',
    state           TEXT        NOT NULL DEFAULT 'GA',
    year            INTEGER     NOT NULL,
    cvap_tot        BIGINT,
    cvap_blk        BIGINT,
    cvap_hsp        BIGINT,
    cvap_wht        BIGINT,
    cvap_asn        BIGINT,
    cvap_ami        BIGINT,
    cvap_nhp        BIGINT,
    cvap_oth        BIGINT,
    source          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    update_count    INTEGER     NOT NULL DEFAULT 0,
    loaded_by       TEXT,
    PRIMARY KEY (geoid, year)
);

COMMENT ON TABLE fdp.cvap IS
'Citizen Voting Age Population by geographic unit and ACS 5-year survey end year. '
'Source: U.S. Census Bureau ACS CVAP special tabulation, disaggregated to '
'2020 Census blocks by the Redistricting Data Hub (RDH), then aggregated to '
'VTDs using centroid-in-polygon spatial join weighted by vap_mod. '
'Multiple ACS years and multiple geographic levels coexist — add new years via UPSERT. '
'Kept separate from fdp.population: different source (ACS sample vs. Census 100%), '
'different cadence (annual vs. decennial), and different methodology.';

COMMENT ON COLUMN fdp.cvap.geoid     IS 'Geographic identifier — FK to fdp.geography.geoid.';
COMMENT ON COLUMN fdp.cvap.geo_level IS
'Level of this row: block | vtd | county | state | … '
'Most rows will be geo_level=''vtd''.';
COMMENT ON COLUMN fdp.cvap.state     IS 'State abbreviation.';
COMMENT ON COLUMN fdp.cvap.year IS
'ACS 5-year survey end year. Example: 2024 = ACS 2020–2024 5-year estimates. '
'Use the most recent available year for current demographic analysis.';
COMMENT ON COLUMN fdp.cvap.cvap_tot IS 'Total Citizen Voting Age Population (all races/ethnicities combined).';
COMMENT ON COLUMN fdp.cvap.cvap_blk IS 'Black or African American alone or in combination CVAP.';
COMMENT ON COLUMN fdp.cvap.cvap_hsp IS 'Hispanic or Latino CVAP (any race).';
COMMENT ON COLUMN fdp.cvap.cvap_wht IS 'White alone, non-Hispanic CVAP.';
COMMENT ON COLUMN fdp.cvap.cvap_asn IS 'Asian alone or in combination CVAP.';
COMMENT ON COLUMN fdp.cvap.cvap_ami IS 'American Indian or Alaska Native alone or in combination CVAP.';
COMMENT ON COLUMN fdp.cvap.cvap_nhp IS 'Native Hawaiian or Other Pacific Islander alone or in combination CVAP.';
COMMENT ON COLUMN fdp.cvap.cvap_oth IS 'All other CVAP not captured in the above categories (multiracial, other).';
COMMENT ON COLUMN fdp.cvap.source    IS 'Data source: RDH | derived.';

COMMENT ON COLUMN fdp.cvap.created_at   IS 'Timestamp when this row was first inserted.';
COMMENT ON COLUMN fdp.cvap.updated_at   IS 'Timestamp of the last UPDATE to this row.';
COMMENT ON COLUMN fdp.cvap.update_count IS 'Number of UPDATEs to this row.';
COMMENT ON COLUMN fdp.cvap.loaded_by    IS 'CLI command or process that last wrote this row.';

CREATE INDEX IF NOT EXISTS cvap_geoid_idx     ON fdp.cvap (geoid);
CREATE INDEX IF NOT EXISTS cvap_year_idx      ON fdp.cvap (year);
CREATE INDEX IF NOT EXISTS cvap_geo_level_idx ON fdp.cvap (geo_level);

CREATE OR REPLACE TRIGGER trg_touch_cvap
    BEFORE UPDATE ON fdp.cvap
    FOR EACH ROW EXECUTE FUNCTION fdp.touch_row();


-- ============================================================================
-- fdp.ensemble_plans  — Redistricting ensemble plan assignments
-- ============================================================================

CREATE TABLE IF NOT EXISTS fdp.ensemble_plans (
    plan_id         TEXT        NOT NULL,
    draw            INTEGER     NOT NULL,
    geoid           TEXT        NOT NULL,
    geo_level       TEXT        NOT NULL DEFAULT 'vtd',
    state           TEXT        NOT NULL DEFAULT 'GA',
    district        INTEGER     NOT NULL,
    chamber         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    update_count    INTEGER     NOT NULL DEFAULT 0,
    loaded_by       TEXT,
    PRIMARY KEY (plan_id, draw, geoid)
);

COMMENT ON TABLE fdp.ensemble_plans IS
'Redistricting ensemble plan assignments — one row per geographic unit per draw per plan set. '
'Join to fdp.election_results on geoid (filtered to the same geo_level) to score each draw '
'on partisan metrics. '
'Draw 1 is always the enacted/reference plan; draws 2..N are simulated. '
'Source: GerryChain (Python) or ALARM redist package (R).';

COMMENT ON COLUMN fdp.ensemble_plans.plan_id IS
'Ensemble plan set identifier. Convention: {state}_{chamber}_{census_year}_{method}_{n_draws}. '
'Example: ga_congress_2020_alarm_5001.';

COMMENT ON COLUMN fdp.ensemble_plans.draw IS
'Draw index within the ensemble (1-based). '
'Draw 1 = enacted/reference plan. Draws 2..N = simulated draws from the Markov chain.';

COMMENT ON COLUMN fdp.ensemble_plans.geoid IS
'Geographic unit GEOID — FK to fdp.geography.geoid and fdp.election_results.geoid. '
'Ensemble plans are most commonly at geo_level=''vtd'' (2,698 rows per draw for GA congress).';

COMMENT ON COLUMN fdp.ensemble_plans.geo_level IS
'Level of the geoid: vtd | block | precinct. '
'Must match the geo_level used in fdp.election_results for scoring to be valid.';

COMMENT ON COLUMN fdp.ensemble_plans.district IS
'District number assigned to this geographic unit in this draw (1-indexed).';

COMMENT ON COLUMN fdp.ensemble_plans.chamber IS
'Legislative chamber: congress | senate | house.';

COMMENT ON COLUMN fdp.ensemble_plans.created_at   IS 'Timestamp when this row was first inserted.';
COMMENT ON COLUMN fdp.ensemble_plans.updated_at   IS 'Timestamp of the last UPDATE to this row.';
COMMENT ON COLUMN fdp.ensemble_plans.update_count IS 'Number of UPDATEs to this row.';
COMMENT ON COLUMN fdp.ensemble_plans.loaded_by    IS 'CLI command or process that last wrote this row.';

CREATE INDEX IF NOT EXISTS ep_plan_draw_idx  ON fdp.ensemble_plans (plan_id, draw);
CREATE INDEX IF NOT EXISTS ep_geoid_idx      ON fdp.ensemble_plans (geoid);
CREATE INDEX IF NOT EXISTS ep_chamber_idx    ON fdp.ensemble_plans (chamber);
CREATE INDEX IF NOT EXISTS ep_geo_level_idx  ON fdp.ensemble_plans (geo_level);

CREATE OR REPLACE TRIGGER trg_touch_ensemble_plans
    BEFORE UPDATE ON fdp.ensemble_plans
    FOR EACH ROW EXECUTE FUNCTION fdp.touch_row();


-- ============================================================================
-- Views — pre-joined, analytical-ready, Looker Studio / Tableau compatible
-- ============================================================================

-- v_election_2pv: Two-party vote share per VTD per race per year
-- Filtered to geo_level='vtd' by default — the most common analytical grain.
CREATE OR REPLACE VIEW fdp.v_election_2pv AS
SELECT
    er.geoid,
    er.geo_level,
    er.state,
    er.year,
    er.election_type,
    er.office,
    SUM(CASE WHEN er.party = 'dem' THEN er.votes ELSE 0 END)  AS dem_votes,
    SUM(CASE WHEN er.party = 'rep' THEN er.votes ELSE 0 END)  AS rep_votes,
    SUM(CASE WHEN er.party = 'lib' THEN er.votes ELSE 0 END)  AS lib_votes,
    SUM(CASE WHEN er.party NOT IN ('dem','rep','lib') THEN er.votes ELSE 0 END) AS other_votes,
    SUM(er.votes)                                              AS total_votes,
    ROUND(
        100.0 * SUM(CASE WHEN er.party = 'dem' THEN er.votes ELSE 0 END)::NUMERIC
        / NULLIF(
            SUM(CASE WHEN er.party IN ('dem','rep') THEN er.votes ELSE 0 END), 0
          ),
        2
    ) AS dem_2pv,
    g.county_fips,
    g.name        AS geo_name,
    p.vap_mod
FROM fdp.election_results er
LEFT JOIN fdp.geography g
    ON g.geoid = er.geoid AND g.vintage_year = 2020
LEFT JOIN fdp.population p
    ON p.geoid = er.geoid AND p.census_year = 2020
WHERE er.geo_level = 'vtd'
GROUP BY er.geoid, er.geo_level, er.state, er.year, er.election_type, er.office,
         g.county_fips, g.name, p.vap_mod;

COMMENT ON VIEW fdp.v_election_2pv IS
'Two-party vote share per VTD per race.  Filtered to geo_level=''vtd''. '
'dem_2pv = dem_votes / (dem_votes + rep_votes) × 100. '
'Libertarian and other party votes are tracked separately but excluded from the '
'two-party denominator.  Use this view for choropleth maps and partisan analysis. '
'For other levels, query fdp.election_results directly and filter by geo_level.';


-- v_county_results: County-level election aggregation
CREATE OR REPLACE VIEW fdp.v_county_results AS
SELECT
    LEFT(er.geoid, 5)   AS county_fips,
    MIN(g.name)         AS county_name,
    er.state,
    er.year,
    er.election_type,
    er.office,
    er.party,
    SUM(er.votes)       AS votes
FROM fdp.election_results er
LEFT JOIN fdp.geography g
    ON g.geoid = LEFT(er.geoid, 5) AND g.geo_level = 'county' AND g.vintage_year = 2020
WHERE er.geo_level = 'vtd'
GROUP BY LEFT(er.geoid, 5), er.state, er.year, er.election_type, er.office, er.party;

COMMENT ON VIEW fdp.v_county_results IS
'County-level election results aggregated from VTD-level data (geo_level=''vtd''). '
'county_fips = LEFT(geoid, 5) — works for all Census GEOIDs. '
'Use for county choropleth maps or to compare against county-level certified results.';


-- v_statewide_results: State totals per race (for SoS validation)
CREATE OR REPLACE VIEW fdp.v_statewide_results AS
SELECT
    er.state,
    er.year,
    er.election_type,
    er.office,
    er.party,
    STRING_AGG(DISTINCT er.candidate, ' / ' ORDER BY er.candidate) AS candidates,
    SUM(er.votes) AS votes,
    ROUND(
        100.0 * SUM(er.votes)::NUMERIC
        / NULLIF(SUM(SUM(er.votes)) OVER (
            PARTITION BY er.state, er.year, er.election_type, er.office
          ), 0),
        2
    ) AS pct_of_total
FROM fdp.election_results er
WHERE er.geo_level = 'vtd'
GROUP BY er.state, er.year, er.election_type, er.office, er.party
ORDER BY er.year, er.election_type, er.office, votes DESC;

COMMENT ON VIEW fdp.v_statewide_results IS
'Statewide vote totals per race — the first stop for validating aggregated data '
'against Georgia Secretary of State certified election results. '
'pct_of_total is each party''s share of all votes cast in that race (not two-party share). '
'Filtered to geo_level=''vtd'' to avoid double-counting if data exists at multiple levels.';


-- v_vtd_demographics: VTD with latest CVAP percentages
CREATE OR REPLACE VIEW fdp.v_vtd_demographics AS
SELECT
    c.geoid,
    c.state,
    c.year                                                                  AS cvap_year,
    c.cvap_tot,
    c.cvap_blk,
    ROUND(100.0 * c.cvap_blk::NUMERIC / NULLIF(c.cvap_tot, 0), 1)         AS pct_blk,
    c.cvap_hsp,
    ROUND(100.0 * c.cvap_hsp::NUMERIC / NULLIF(c.cvap_tot, 0), 1)         AS pct_hsp,
    c.cvap_wht,
    ROUND(100.0 * c.cvap_wht::NUMERIC / NULLIF(c.cvap_tot, 0), 1)         AS pct_wht,
    c.cvap_asn,
    ROUND(100.0 * c.cvap_asn::NUMERIC / NULLIF(c.cvap_tot, 0), 1)         AS pct_asn,
    c.cvap_ami,
    c.cvap_nhp,
    g.county_fips,
    g.name   AS geo_name,
    p.vap_mod
FROM fdp.cvap c
LEFT JOIN fdp.geography g
    ON g.geoid = c.geoid AND g.vintage_year = 2020
LEFT JOIN fdp.population p
    ON p.geoid = c.geoid AND p.census_year = 2020
WHERE c.geo_level = 'vtd'
  AND c.year = (SELECT MAX(year) FROM fdp.cvap WHERE state = c.state AND geo_level = 'vtd');

COMMENT ON VIEW fdp.v_vtd_demographics IS
'VTD demographics using the most recent CVAP year available for each state. '
'Filtered to geo_level=''vtd''.  Includes racial/ethnic CVAP counts and percentages. '
'pct_blk / pct_hsp / pct_wht / pct_asn are percent of total CVAP. '
'vap_mod comes from fdp.population (decennial Census) — more reliable than CVAP totals '
'for use as disaggregation weights. '
'Used for majority-minority district analysis under Section 2 of the Voting Rights Act.';
