# Postgres CDM mirror

This folder contains an idempotent migration that copies the Fair Districts Data
Platform CDM from the DuckDB files in `fdp/data/` into the Postgres server
defined in `docker/postgres/docker-compose.yml`, then builds a dashboard-oriented
semantic layer on top.

## Quick start

Make sure the Postgres container is running:

```bash
cd ~/docker/postgres
docker compose up -d
```

Then run the migration:

```bash
cd ~/codebox/fgdp/fdp
uv run python scripts/cdm_to_postgres.py
```

The script is safe to re-run: it drops and recreates the objects it owns while
leaving other schemas untouched.

## What gets created

| Schema | Contents |
|--------|----------|
| `cdm` | Tables copied from `data/cdm.duckdb`: boundary catalog, plan catalog, redistricting waves, wave chambers, schema contracts, displacement metrics. |
| `manifest` | `datasets` table copied from `data/manifest.duckdb`. |
| `semantic` | Raw VTD/district tables from `data/semantic.duckdb` plus full and compact semantic views (the same views WrenAI uses). |
| `fdp` | The canonical FDP Common Data Model DDL from `sql/002_cdm.sql` (geography, population, election_results, cvap, ensemble_plans, etc.). These tables are currently empty until normalized fact data is loaded; the schema and its analytical views are ready for that data. |
| `dashboard` | Materialized views and views designed for Data Studio / Looker Studio. |
| `analytics` | Spec-driven analytics layer: county population shifts, statewide demographics, and ensemble-based partisan / competitiveness / minority-representation benchmarks. |

## Connection info

```text
Host:     localhost
Port:     5432
Database: fdga
User:     homelab
Password: homelab
```

PgAdmin is also running at http://localhost:5050.

## Dashboard objects

The `dashboard` schema is the main output for charting tools.

### Materialized views (pre-computed, fast)

| Object | Purpose |
|--------|---------|
| `dashboard.mv_county_summary` | One row per Georgia county with population, VAP, racial shares, and composite partisan lean. |
| `dashboard.mv_county_election_trends` | Long-format county Democratic vote share by election (2018 Gov → 2024 Pres). |
| `dashboard.mv_vtd_partisan_demographics` | One row per VTD with demographics, partisan lean, competitiveness flags, and centroid coordinates. |

You can refresh them concurrently after new data loads:

```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY dashboard.mv_county_summary;
REFRESH MATERIALIZED VIEW CONCURRENTLY dashboard.mv_county_election_trends;
REFRESH MATERIALIZED VIEW CONCURRENTLY dashboard.mv_vtd_partisan_demographics;
```

### Regular views

| Object | Purpose |
|--------|---------|
| `dashboard.v_county_summary` | Alias for `mv_county_summary`. |
| `dashboard.v_county_election_trends` | Alias for `mv_county_election_trends`. |
| `dashboard.v_vtd_partisan_demographics` | Alias for `mv_vtd_partisan_demographics`. |
| `dashboard.v_statewide_totals` | Georgia-wide population and vote totals (good for scorecards). |
| `dashboard.v_competitive_vtds` | Swing VTDs with a two-party margin ≤ 7%. |
| `dashboard.v_county_competitiveness` | Number and share of competitive VTDs per county. |
| `dashboard.v_county_race_partisan` | Racial composition vs. Democratic vote share per county. |
| `dashboard.v_district_demographics` | District-level ACS socioeconomic metrics. |
| `dashboard.v_redistricting_waves` | Historical redistricting waves. |
| `dashboard.v_plan_summary` | Plan catalog joined to boundary file status. |

## Analytics objects (briefing specification layer)

The `analytics` schema mirrors the analyses described in the redistricting
analytics specification.  County-level objects are populated immediately;
ensemble-based objects are empty until ensemble scores are loaded.

### Demographic / population change

| Object | Purpose |
|--------|---------|
| `analytics.county_reference` | Georgia county names and metro flags. |
| `analytics.raw_county_census` | County 2010 population + 2020 racial counts. |
| `analytics.v_county_population_shifts` | 2010-2020 absolute/percent change with quartile-based growth status. |
| `analytics.v_statewide_demographic_breakdown_2020` | Statewide 2020 donut-chart demographics. |
| `analytics.v_county_demographics_2020` | County-level 2020 racial composition. |

### Ensemble histograms / benchmarks

| Object | Purpose |
|--------|---------|
| `analytics.agg_sim_partisan_outcomes` | Democratic seat-count histogram bins with 98% percentile flag. |
| `analytics.agg_sim_competitiveness` | Competitive-district count frequency distribution with enacted benchmark. |
| `analytics.agg_sim_minority_representation` | Per-map Black/Hispanic/coalition district counts. |
| `analytics.v_minority_representation_benchmarks` | Min, median, max, and 1st/99th percentile boundaries. |
| `analytics.v_redistricting_benchmark_summary` | Master benchmark/actuals summary per chamber/cycle/race. |

Refresh ensemble materialized views after loading new scores:

```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY analytics.agg_sim_partisan_outcomes;
REFRESH MATERIALIZED VIEW CONCURRENTLY analytics.agg_sim_competitiveness;
REFRESH MATERIALIZED VIEW CONCURRENTLY analytics.agg_sim_minority_representation;
```

## Documentation

Every table, materialized view, view, and column in the migrated schemas has a
`COMMENT ON` description. PgAdmin, Data Studio, and `psql \d+` will all show
 them.

## File reference

| File | Role |
|------|------|
| `scripts/cdm_to_postgres.py` | Main migration script. |
| `sql/postgres/000_comments.sql` | Table and column documentation for the raw migrated tables. |
| `sql/postgres/001_semantic_views.sql` | Semantic-layer views (full + compact). |
| `sql/postgres/002_dashboard_views.sql` | Dashboard materialized views and views. |
| `sql/postgres/003_analytics_spec.sql` | Spec-driven analytics views and aggregates. |
