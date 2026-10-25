-- ============================================================================
-- Documentation for the raw tables loaded from DuckDB.
-- This file is applied by scripts/cdm_to_postgres.py.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- cdm.cdm_boundary_catalog
-- ----------------------------------------------------------------------------
COMMENT ON TABLE cdm.cdm_boundary_catalog IS
    'Inventory of boundary GeoJSON files available in data/repos/main/boundaries. '
    'Used by apps to resolve map layers and by the semantic plan_summary view.';

COMMENT ON COLUMN cdm.cdm_boundary_catalog.file_id IS
    'Unique identifier, usually "{chamber}/{filename_without_extension}".';
COMMENT ON COLUMN cdm.cdm_boundary_catalog.chamber IS
    'Legislative chamber or reference category (congress, house, senate, reference).';
COMMENT ON COLUMN cdm.cdm_boundary_catalog.filename IS
    'GeoJSON file name (no directory path).';
COMMENT ON COLUMN cdm.cdm_boundary_catalog.full_path IS
    'Absolute filesystem path to the source GeoJSON.';
COMMENT ON COLUMN cdm.cdm_boundary_catalog.file_size_kb IS
    'File size in kilobytes.';
COMMENT ON COLUMN cdm.cdm_boundary_catalog.label IS
    'Human-readable display label for the boundary file.';
COMMENT ON COLUMN cdm.cdm_boundary_catalog.era IS
    'Descriptive era tag such as 2024_enacted, cooper_proposed, remedy, proposed.';
COMMENT ON COLUMN cdm.cdm_boundary_catalog.in_app_config IS
    'True when the boundary is referenced by an app configuration file.';


-- ----------------------------------------------------------------------------
-- cdm.cdm_plan_catalog
-- ----------------------------------------------------------------------------
COMMENT ON TABLE cdm.cdm_plan_catalog IS
    'Catalog of redistricting plans exposed to apps. Each row maps a logical '
    'plan_id to a boundary file and a chamber.';

COMMENT ON COLUMN cdm.cdm_plan_catalog.plan_id IS
    'Unique logical plan identifier, conventionally "{app}/{plan_name}".';
COMMENT ON COLUMN cdm.cdm_plan_catalog.app IS
    'Application that owns this catalog entry (e.g. fdex, lrdb).';
COMMENT ON COLUMN cdm.cdm_plan_catalog.chamber IS
    'Chamber the plan applies to: congress, house, or senate.';
COMMENT ON COLUMN cdm.cdm_plan_catalog.label IS
    'Human-readable plan label.';
COMMENT ON COLUMN cdm.cdm_plan_catalog.filename IS
    'Relative path to the boundary file inside data/repos/main/boundaries.';


-- ----------------------------------------------------------------------------
-- cdm.cdm_redistricting_waves
-- ----------------------------------------------------------------------------
COMMENT ON TABLE cdm.cdm_redistricting_waves IS
    'Historical redistricting waves for Georgia: year, controlling party, reason, '
    'and how many districts changed.';

COMMENT ON COLUMN cdm.cdm_redistricting_waves.year IS
    'Year the redistricting cycle began.';
COMMENT ON COLUMN cdm.cdm_redistricting_waves.end_year IS
    'End year if the cycle spanned two calendar years; otherwise NULL.';
COMMENT ON COLUMN cdm.cdm_redistricting_waves.display_year IS
    'Formatted display string for the wave year(s).';
COMMENT ON COLUMN cdm.cdm_redistricting_waves.label IS
    'Short display name of the wave.';
COMMENT ON COLUMN cdm.cdm_redistricting_waves.party IS
    'Controlling party: R, D, or both.';
COMMENT ON COLUMN cdm.cdm_redistricting_waves.reason IS
    'Trigger for the wave (census, court order, litigation, etc.).';
COMMENT ON COLUMN cdm.cdm_redistricting_waves.legal_context IS
    'Court case or legislative action that produced the map.';
COMMENT ON COLUMN cdm.cdm_redistricting_waves.election_result IS
    'Associated election outcome summary.';
COMMENT ON COLUMN cdm.cdm_redistricting_waves.total_districts_changed IS
    'Total number of districts changed across all affected chambers.';
COMMENT ON COLUMN cdm.cdm_redistricting_waves.source IS
    'Citation or source for the wave record.';
COMMENT ON COLUMN cdm.cdm_redistricting_waves.author IS
    'Map author or responsible body.';


-- ----------------------------------------------------------------------------
-- cdm.cdm_wave_chambers
-- ----------------------------------------------------------------------------
COMMENT ON TABLE cdm.cdm_wave_chambers IS
    'Per-chamber detail for each redistricting wave: how many districts were '
    'drawn and whether the entire chamber was redrawn.';

COMMENT ON COLUMN cdm.cdm_wave_chambers.wave_year IS
    'Year of the redistricting wave.';
COMMENT ON COLUMN cdm.cdm_wave_chambers.chamber IS
    'Affected chamber: congress, house, or senate.';
COMMENT ON COLUMN cdm.cdm_wave_chambers.district_count IS
    'Number of districts in the chamber for that wave.';
COMMENT ON COLUMN cdm.cdm_wave_chambers.all_districts IS
    'True if every district in the chamber was redrawn.';
COMMENT ON COLUMN cdm.cdm_wave_chambers.districts_known IS
    'True if the specific district IDs affected are known.';
COMMENT ON COLUMN cdm.cdm_wave_chambers.notes IS
    'Free-form notes about the chamber-level changes.';


-- ----------------------------------------------------------------------------
-- cdm.cdm_schema_contracts
-- ----------------------------------------------------------------------------
COMMENT ON TABLE cdm.cdm_schema_contracts IS
    'Platform-level data-schema contracts: which fields are required for each '
    'data type and their expected types.';

COMMENT ON COLUMN cdm.cdm_schema_contracts.data_type IS
    'Data category the contract applies to (e.g. boundaries, elections).';
COMMENT ON COLUMN cdm.cdm_schema_contracts.field_name IS
    'Canonical field name governed by the contract.';
COMMENT ON COLUMN cdm.cdm_schema_contracts.required IS
    'True when the field is mandatory for that data type.';
COMMENT ON COLUMN cdm.cdm_schema_contracts.field_type IS
    'Expected data type of the field.';
COMMENT ON COLUMN cdm.cdm_schema_contracts.description IS
    'Human-readable description of the field.';


-- ----------------------------------------------------------------------------
-- cdm.cdm_displacement_metrics
-- ----------------------------------------------------------------------------
COMMENT ON TABLE cdm.cdm_displacement_metrics IS
    'Computed displacement statistics between two redistricting plans: how many '
    'people were forced into a new district and how that compares to the minimum '
    'required by population equality.';

COMMENT ON COLUMN cdm.cdm_displacement_metrics.id IS 'Unique metric row id.';
COMMENT ON COLUMN cdm.cdm_displacement_metrics.plan_a_id IS 'First plan in the comparison.';
COMMENT ON COLUMN cdm.cdm_displacement_metrics.plan_b_id IS 'Second plan in the comparison.';
COMMENT ON COLUMN cdm.cdm_displacement_metrics.chamber IS 'Chamber being compared.';
COMMENT ON COLUMN cdm.cdm_displacement_metrics.wave_year IS 'Redistricting wave year.';
COMMENT ON COLUMN cdm.cdm_displacement_metrics.total_pop IS 'Total population of the chamber.';
COMMENT ON COLUMN cdm.cdm_displacement_metrics.displaced_pop IS 'People assigned to a different district.';
COMMENT ON COLUMN cdm.cdm_displacement_metrics.displaced_pct IS 'Displaced population as a share of total population.';
COMMENT ON COLUMN cdm.cdm_displacement_metrics.min_required_displaced_pop IS
    'Smallest number of people that must move to equalize districts perfectly.';
COMMENT ON COLUMN cdm.cdm_displacement_metrics.min_required_displaced_pct IS
    'Minimum required displacement as a share of total population.';
COMMENT ON COLUMN cdm.cdm_displacement_metrics.excess_displaced_pop IS
    'People displaced beyond the theoretical minimum.';
COMMENT ON COLUMN cdm.cdm_displacement_metrics.excess_displaced_pct IS
    'Excess displacement as a share of total population.';
COMMENT ON COLUMN cdm.cdm_displacement_metrics.district_count IS 'Number of districts in the chamber.';
COMMENT ON COLUMN cdm.cdm_displacement_metrics.method IS 'Method used to compute displacement.';
COMMENT ON COLUMN cdm.cdm_displacement_metrics.computed_at IS 'Timestamp when the metric was computed.';


-- ----------------------------------------------------------------------------
-- manifest.datasets
-- ----------------------------------------------------------------------------
COMMENT ON TABLE manifest.datasets IS
    'FDP data manifest: every canonical dataset loaded into the platform, with '
    'provenance, row counts, and derived-from lineage.';

COMMENT ON COLUMN manifest.datasets.id IS 'Unique dataset slug.';
COMMENT ON COLUMN manifest.datasets.category IS 'Data category: election, cvap, lookup, alarm_combined, etc.';
COMMENT ON COLUMN manifest.datasets.geography IS 'Geographic level: block, vtd, county, state, etc.';
COMMENT ON COLUMN manifest.datasets.vintage IS 'Dataset vintage year.';
COMMENT ON COLUMN manifest.datasets.state IS 'State abbreviation, default GA.';
COMMENT ON COLUMN manifest.datasets.source IS 'Original data source: RDH, Census, derived.';
COMMENT ON COLUMN manifest.datasets.source_url IS 'URL to the original source, if any.';
COMMENT ON COLUMN manifest.datasets.election_type IS 'For elections: general, runoff, special, primary.';
COMMENT ON COLUMN manifest.datasets.raw_file IS 'Path to the raw downloaded file.';
COMMENT ON COLUMN manifest.datasets.output_file IS 'Path to the canonical Parquet output.';
COMMENT ON COLUMN manifest.datasets.row_count IS 'Number of rows in the canonical output.';
COMMENT ON COLUMN manifest.datasets.columns_json IS 'JSON array of output column names.';
COMMENT ON COLUMN manifest.datasets.loaded_at IS 'ISO timestamp when the dataset was loaded.';
COMMENT ON COLUMN manifest.datasets.checksum IS 'SHA-256 checksum of the raw file.';
COMMENT ON COLUMN manifest.datasets.derived_from IS 'JSON array of upstream dataset ids.';
COMMENT ON COLUMN manifest.datasets.notes IS 'Free-form notes.';


-- ----------------------------------------------------------------------------
-- semantic.raw_vtd_demographics
-- ----------------------------------------------------------------------------
COMMENT ON TABLE semantic.raw_vtd_demographics IS
    'VTD-level decennial Census P.L. 94-171 population and voting-age population '
    'by race/ethnicity. One row per 2020 Census VTD in Georgia.';

COMMENT ON COLUMN semantic.raw_vtd_demographics.geoid IS '2020 Census VTD GEOID.';
COMMENT ON COLUMN semantic.raw_vtd_demographics.pop IS 'Total population.';
COMMENT ON COLUMN semantic.raw_vtd_demographics.vap IS 'Total voting-age population (18+).';
COMMENT ON COLUMN semantic.raw_vtd_demographics.pop_black IS 'Black or African American alone population.';
COMMENT ON COLUMN semantic.raw_vtd_demographics.pop_hisp IS 'Hispanic or Latino population, any race.';
COMMENT ON COLUMN semantic.raw_vtd_demographics.pop_white IS 'White alone population.';
COMMENT ON COLUMN semantic.raw_vtd_demographics.pop_aian IS 'American Indian / Alaska Native alone population.';
COMMENT ON COLUMN semantic.raw_vtd_demographics.pop_asian IS 'Asian alone population.';
COMMENT ON COLUMN semantic.raw_vtd_demographics.vap_black IS 'Black or African American alone VAP.';
COMMENT ON COLUMN semantic.raw_vtd_demographics.vap_hisp IS 'Hispanic or Latino VAP, any race.';
COMMENT ON COLUMN semantic.raw_vtd_demographics.vap_white IS 'White alone VAP.';
COMMENT ON COLUMN semantic.raw_vtd_demographics.vap_aian IS 'American Indian / Alaska Native alone VAP.';
COMMENT ON COLUMN semantic.raw_vtd_demographics.vap_asian IS 'Asian alone VAP.';


-- ----------------------------------------------------------------------------
-- semantic.raw_vtd_composite_lean
-- ----------------------------------------------------------------------------
COMMENT ON TABLE semantic.raw_vtd_composite_lean IS
    'VTD-level composite partisan lean and VAP-by-race counts derived from '
    'the fdensemble VTD composite file. Includes historical election vote shares '
    'and centroid coordinates.';

COMMENT ON COLUMN semantic.raw_vtd_composite_lean.geoid20 IS '2020 Census VTD GEOID.';
COMMENT ON COLUMN semantic.raw_vtd_composite_lean.composite_dem_pct IS
    'Estimated Democratic vote share (all votes) from the composite model.';
COMMENT ON COLUMN semantic.raw_vtd_composite_lean.composite_rep_pct IS
    'Estimated Republican vote share (all votes) from the composite model.';
COMMENT ON COLUMN semantic.raw_vtd_composite_lean.composite_other_pct IS
    'Estimated other-party vote share from the composite model.';
COMMENT ON COLUMN semantic.raw_vtd_composite_lean.composite_dem_2pv IS
    'Estimated Democratic two-party vote share from the composite model.';
COMMENT ON COLUMN semantic.raw_vtd_composite_lean.dem_pct_2018_gov IS
    'Estimated Democratic vote share in the 2018 governor race.';
COMMENT ON COLUMN semantic.raw_vtd_composite_lean.dem_pct_2020_pres IS
    'Estimated Democratic vote share in the 2020 presidential race.';
COMMENT ON COLUMN semantic.raw_vtd_composite_lean.dem_pct_2021_war_runoff IS
    'Estimated Democratic vote share in the 2021 Warnock runoff.';
COMMENT ON COLUMN semantic.raw_vtd_composite_lean.dem_pct_2022_gov IS
    'Estimated Democratic vote share in the 2022 governor race.';
COMMENT ON COLUMN semantic.raw_vtd_composite_lean.dem_pct_2022_uss IS
    'Estimated Democratic vote share in the 2022 U.S. Senate race.';
COMMENT ON COLUMN semantic.raw_vtd_composite_lean.dem_pct_2024_pres IS
    'Estimated Democratic vote share in the 2024 presidential race.';
COMMENT ON COLUMN semantic.raw_vtd_composite_lean.vap_mod IS
    'Modified voting-age population used as the disaggregation weight.';
COMMENT ON COLUMN semantic.raw_vtd_composite_lean.bvap_tot IS 'Total VAP (despite the source column name).';
COMMENT ON COLUMN semantic.raw_vtd_composite_lean.bvap_blk IS 'Black or African American VAP.';
COMMENT ON COLUMN semantic.raw_vtd_composite_lean.bvap_wht IS 'White VAP.';
COMMENT ON COLUMN semantic.raw_vtd_composite_lean.bvap_hsp IS 'Hispanic or Latino VAP.';
COMMENT ON COLUMN semantic.raw_vtd_composite_lean.bvap_asn IS 'Asian VAP.';
COMMENT ON COLUMN semantic.raw_vtd_composite_lean.bvap_coalition IS
    'Coalition-of-color VAP used for opportunity-district analysis.';
COMMENT ON COLUMN semantic.raw_vtd_composite_lean.actual_dem_votes IS
    'Sum of Democratic votes across elections used in the composite.';
COMMENT ON COLUMN semantic.raw_vtd_composite_lean.actual_total_votes IS
    'Sum of total votes across elections used in the composite.';
COMMENT ON COLUMN semantic.raw_vtd_composite_lean.centroid_lat IS 'VTD centroid latitude (WGS84).';
COMMENT ON COLUMN semantic.raw_vtd_composite_lean.centroid_lon IS 'VTD centroid longitude (WGS84).';


-- ----------------------------------------------------------------------------
-- semantic.raw_district_demographics
-- ----------------------------------------------------------------------------
COMMENT ON TABLE semantic.raw_district_demographics IS
    'District-level American Community Survey (ACS) socioeconomic metrics for '
    'enacted Georgia congressional, house, and senate districts.';

COMMENT ON COLUMN semantic.raw_district_demographics.chamber IS
    'Legislative chamber: congress, house, or senate.';
COMMENT ON COLUMN semantic.raw_district_demographics.district IS 'District number.';
COMMENT ON COLUMN semantic.raw_district_demographics.median_income IS 'District median household income.';
COMMENT ON COLUMN semantic.raw_district_demographics.pct_poverty IS 'Share of population in poverty (0-1).';
COMMENT ON COLUMN semantic.raw_district_demographics.poverty_count IS 'Count of people in poverty.';
COMMENT ON COLUMN semantic.raw_district_demographics.pct_bachelors_plus IS
    'Share of population 25+ with a bachelors degree or higher (0-1).';
COMMENT ON COLUMN semantic.raw_district_demographics.bachelors_plus_count IS 'Count of people 25+ with bachelors degree or higher.';
COMMENT ON COLUMN semantic.raw_district_demographics.pct_male IS 'Share male (0-1).';
COMMENT ON COLUMN semantic.raw_district_demographics.pct_female IS 'Share female (0-1).';
COMMENT ON COLUMN semantic.raw_district_demographics.pct_married_family IS 'Share married-couple families (0-1).';
COMMENT ON COLUMN semantic.raw_district_demographics.married_hh_count IS 'Count of married-couple households.';
COMMENT ON COLUMN semantic.raw_district_demographics.pct_single_parent IS 'Share single-parent households (0-1).';
COMMENT ON COLUMN semantic.raw_district_demographics.single_parent_count IS 'Count of single-parent households.';
COMMENT ON COLUMN semantic.raw_district_demographics.pct_no_vehicle IS 'Share households with no vehicle (0-1).';
COMMENT ON COLUMN semantic.raw_district_demographics.no_vehicle_count IS 'Count of households with no vehicle.';
COMMENT ON COLUMN semantic.raw_district_demographics.pct_uninsured IS 'Share population without health insurance (0-1).';
COMMENT ON COLUMN semantic.raw_district_demographics.uninsured_count IS 'Count of uninsured people.';
COMMENT ON COLUMN semantic.raw_district_demographics.pct_unemployed IS 'Share of labor force unemployed (0-1).';
COMMENT ON COLUMN semantic.raw_district_demographics.unemployed_count IS 'Count of unemployed people.';
COMMENT ON COLUMN semantic.raw_district_demographics.labor_force_count IS 'Size of the labor force.';
