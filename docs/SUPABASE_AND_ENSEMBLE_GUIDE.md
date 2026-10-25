# Supabase + GerryChain Ensemble User Guide

This guide walks through the full workflow from rebuilding GerryChain dual graphs
to loading scored ensemble data into Supabase and connecting Data Studio.

## Table of contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Rebuild the dual graphs](#rebuild-the-dual-graphs)
4. [Build scoring inputs](#build-scoring-inputs)
5. [Run a GerryChain ensemble](#run-a-gerrychain-ensemble)
6. [Score the ensemble](#score-the-ensemble)
7. [Load results into Supabase](#load-results-into-supabase)
8. [Connect Data Studio](#connect-data-studio)
9. [Migrate an existing local Postgres to Supabase](#migrate-an-existing-local-postgres-to-supabase)
10. [Switching back to local Postgres](#switching-back-to-local-postgres)
11. [Troubleshooting](#troubleshooting)

---

## Overview

The pipeline has three stages:

1. **Graphs** — build GerryChain dual graphs from Census VTDs + enacted maps.
2. **Ensemble** — run GerryChain, score plans, score demographics.
3. **Database** — load scores into Supabase so Data Studio can reach them.

Default target database is now **Supabase** (shared, IPv4-compatible via the
session pooler). The local Docker Postgres remains available for development
and heavy ensemble generation.

---

## Prerequisites

- Python 3.12+ with `uv` installed.
- The `ensemble/` and `fdp/` project directories.
- A Supabase project with the session pooler connection string.
- Local Postgres running (optional, for local-only work).

All commands assume you are in `/root/codebox/fgdp` or one of its
sub-projects. Adjust paths if your repo lives elsewhere.

---

## Rebuild the dual graphs

The graphs are built from the Census 2020 VTD shapefile plus enacted GeoJSON
plans. Population is joined from `fdensemble/data/vtd_demographics.parquet`
because the TIGER shapefile contains geometry but no population columns.

```bash
cd ensemble
uv run python scripts/build_graph.py --state ga --out-dir ../fdp/data/repos/main/graphs
```

Output:

```text
../fdp/data/repos/main/graphs/ga_congress.json   # 2,698 nodes, 14 districts
../fdp/data/repos/main/graphs/ga_senate.json     # 2,698 nodes, 56 districts
../fdp/data/repos/main/graphs/ga_house.json      # 2,698 nodes, 180 districts
```

If the VTD shapefile is missing, the script downloads the Census TIGER file to
`ensemble/data/raw/tl_2020_13_vtd20.zip` automatically.

### Verify the graph

```bash
uv run python - <<'PY'
import json
with open('../fdp/data/repos/main/graphs/ga_congress.json') as f:
    g = json.load(f)
print('nodes', len(g['nodes']))
print('edges', len(g['adjacency']))
print('sample node', g['nodes'][0])
PY
```

---

## Build scoring inputs

Two parquet files are required by the scorer:

1. `fdp/data/repos/main/election_results_vtd.parquet` — long-format votes.
2. `fdp/data/repos/main/vtd/bvap_vtd.parquet` — VAP demographics.

### Election results

```bash
cd ../fdp
uv run python scripts/build_election_results_vtd.py
```

This reads `fdensemble/data/vtd_composite.parquet` and writes the long-format
`election_results_vtd.parquet` with columns:
`geoid, year, election_type, office, party, votes`.

### Demographics (BVAP-style)

```bash
uv run python scripts/build_bvap_vtd.py
```

This reads `fdensemble/data/vtd_demographics.parquet` and writes
`vtd/bvap_vtd.parquet` with columns:
`GEOID20, bvap_tot, bvap_blk, bvap_wht, bvap_hsp, bvap_asn`.

---

## Run a GerryChain ensemble

Use a benchmark config. For Congress:

```bash
cd ../ensemble
uv run python scripts/run_ensemble.py \
    --run-name ga_congress_2026_v2 \
    --config ../fdp/configs/benchmarks/ga_congress_2026_v2.yml
```

The script will:

- Write `../fdp/data/repos/main/ensemble/ga_congress_2026_v2_plans.parquet`
- Write `../fdp/data/repos/main/ensemble/ga_congress_2026_v2_meta.json`
- Write a catalog record to Supabase (`fdp.ensemble_runs`)

Use `--no-db` to skip the Supabase catalog write (local-only generation).

### Quick test run

```bash
uv run python scripts/run_ensemble.py \
    --run-name congress_test_100 \
    --config ../fdp/configs/benchmarks/ga_congress_2026_v2.yml \
    --n-steps 100 --burn-in 0
```

---

## Score the ensemble

### Partisan / competitiveness scores

```bash
cd ../fdp
uv run --project fdp python fdp/scripts/score_ensemble_plans.py \
    --run-name ga_congress_2026_v2 \
    --config fdp/configs/benchmarks/ga_congress_2026_v2.yml
```

Output:

```text
fdp/data/repos/main/ensemble/ga_congress_2026_v2_scores.parquet
```

### Demographic scores

```bash
uv run --project fdp python fdp/scripts/score_ensemble_demographics.py \
    --run-name ga_congress_2026_v2 \
    --plans-file fdp/data/repos/main/ensemble/ga_congress_2026_v2_plans.parquet \
    --bvap-file fdp/data/repos/main/vtd/bvap_vtd.parquet \
    --config fdp/configs/benchmarks/ga_congress_2026_v2.yml
```

Output:

```text
fdp/data/repos/main/ensemble/ga_congress_2026_v2_demographics.parquet
```

---

## Load results into Supabase

`load_ensemble_scores.py` now defaults to the Supabase session pooler.

```bash
uv run python fdp/scripts/load_ensemble_scores.py --run-name ga_congress_2026_v2
```

This:

1. Loads `fdp.ensemble_scores`.
2. Loads `analytics.ensemble_demographic_scores`.
3. Upserts `fdp.ensemble_runs`.
4. Refreshes the analytics materialized views.

### Verify

```bash
uv run python - <<'PY'
import psycopg
DSN = (
    "postgresql://postgres.jzhxmnjmigfhggzfcwkv:fairdistrictsGA2026!"
    "@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
)
with psycopg.connect(DSN) as conn:
    cur = conn.cursor()
    cur.execute("SELECT * FROM analytics.v_redistricting_benchmark_summary WHERE office='composite'")
    for r in cur.fetchall(): print(r)
PY
```

---

## Connect Metabase (recommended over Looker Studio)

A Docker Compose file is provided for Metabase because it handles multiple
schemas and ad-hoc SQL much better than Looker Studio.

### Start Metabase

```bash
cd fdp
docker compose -f docker-compose.metabase.yml up -d
```

Wait ~30 seconds, then open: `http://localhost:3000`

Create the admin account in the UI.

### Add the local Postgres data source

1. In Metabase, go to **Admin settings → Databases → Add a database**.
2. Choose **PostgreSQL**.
3. Fill in:

| Setting | Value |
|---|---|
| Host | `host.docker.internal` |
| Port | `5432` |
| Database name | `fdga` |
| Username | `homelab` |
| Password | `homelab` |
| SSL | No (for local) |

4. Click **Save**.

If `host.docker.internal` does not work on Linux, use your machine's LAN IP
(e.g., `192.168.x.x`) or the Docker bridge gateway (`172.17.0.1`).

### Switch to Supabase

1. Go to **Admin settings → Databases**.
2. Either edit the existing database or add a new one.
3. Fill in the Supabase session pooler settings:

| Setting | Value |
|---|---|
| Host | `aws-0-us-east-1.pooler.supabase.com` |
| Port | `5432` |
| Database name | `postgres` |
| Username | `postgres.jzhxmnjmigfhggzfcwkv` |
| Password | `fairdistrictsGA2026!` |
| SSL | Yes / Require |

4. Save. All questions and dashboards will now query Supabase.

### Recommended Metabase starter questions

Create these questions using **Native query**:

1. **Benchmark summary**
   ```sql
   SELECT * FROM analytics.v_redistricting_benchmark_summary
   ORDER BY cycle_year, office;
   ```

2. **Competitiveness distribution**
   ```sql
   SELECT cycle_year, office, competitive_district_count, map_count
   FROM analytics.agg_sim_competitiveness
   ORDER BY cycle_year, office, competitive_district_count;
   ```

3. **County summary map**
   ```sql
   SELECT county_fips, total_pop, dem_vote_pct, centroid_lat, centroid_lon
   FROM dashboard.v_county_summary;
   ```

4. **Enacted vs ensemble**
   ```sql
   SELECT * FROM fdp.v_ensemble_vs_enacted
   ORDER BY year, office;
   ```

---

## Connect Data Studio

Use the **session pooler** settings:

| Setting | Value |
|---|---|
| Host | `aws-0-us-east-1.pooler.supabase.com` |
| Port | `5432` |
| Database | `postgres` |
| Username | `postgres.jzhxmnjmigfhggzfcwkv` |
| Password | `fairdistrictsGA2026!` |
| SSL | `Require` |

Full URI:

```txt
postgresql://postgres.jzhxmnjmigfhggzfcwkv:fairdistrictsGA2026!@aws-0-us-east-1.pooler.supabase.com:5432/postgres
```

### Supabase network settings

In the Supabase dashboard:

1. Go to **Project Settings → Database → Network Restrictions**.
2. Allow Data Studio’s IP ranges, or temporarily allow `0.0.0.0/0` for testing.

Recommended starter views for Data Studio:

- `analytics.v_redistricting_benchmark_summary`
- `dashboard.v_county_summary`
- `dashboard.v_county_competitiveness`
- `fdp.v_ensemble_vs_enacted`

---

## Migrate an existing local Postgres to Supabase

If you already have a populated local `fdga` database and want to copy it to
Supabase:

### 1. Build the schema in Supabase

```bash
cd fdp
POSTGRES_DSN='postgresql://postgres.jzhxmnjmigfhggzfcwkv:fairdistrictsGA2026!@aws-0-us-east-1.pooler.supabase.com:5432/postgres' \
  uv run python scripts/cdm_to_postgres.py
```

### 2. Copy ensemble tables from local Postgres

```bash
uv run python scripts/migrate_ensemble_to_supabase.py \
  --remote-dsn 'postgresql://postgres.jzhxmnjmigfhggzfcwkv:fairdistrictsGA2026!@aws-0-us-east-1.pooler.supabase.com:5432/postgres'
```

This copies:

- `fdp.ensemble_runs`
- `fdp.ensemble_scores`
- `analytics.ensemble_demographic_scores`

and refreshes all materialized views.

---

## Switching back to local Postgres

Set the `POSTGRES_DSN` environment variable (or `DATABASE_URL` for
`run_ensemble.py`):

```bash
export POSTGRES_DSN="host=localhost port=5432 dbname=fdga user=homelab password=homelab"

# Then run any loader/migration command normally
uv run python fdp/scripts/load_ensemble_scores.py --run-name ga_congress_2026_v2
```

For `run_ensemble.py`:

```bash
export DATABASE_URL="host=localhost port=5432 dbname=fdga user=homelab password=homelab"
uv run python scripts/run_ensemble.py --run-name local_test --config ../fdp/configs/benchmarks/ga_congress_2026_v2.yml
```

---

## Troubleshooting

### `password authentication failed for user "postgres"`

- Make sure you are using the **session pooler** URI, not the direct URI.
- The session pooler username is `postgres.<project-ref>` (with a dot).
- Copy the password fresh from **Project Settings → Database → Database password**.

### `Network is unreachable` on the direct URI

The direct Supabase endpoint is IPv6-only on free plans. Use the session pooler
(`aws-0-us-east-1.pooler.supabase.com:5432`) which is IPv4-compatible.

### Data Studio cannot connect

- Check **Project Settings → Database → Network Restrictions**.
- Temporarily allow `0.0.0.0/0` to confirm the issue is IP-based.
- Use SSL mode `Require`.

### `cannot adapt type 'dict'` during migration

If you write your own migration script, wrap Python dicts/lists with
`psycopg.types.json.Json` before inserting into JSON/JSONB columns.

### GerryChain stops early with few draws

The `recom` proposal can hit dead-ends, especially for House where VTDs are
large relative to districts. Options:

- Increase `--epsilon` / `pop_epsilon` in the config.
- Use a smaller geographic unit for House runs.
- Switch to `reversible_recom` in a future config version.

---

## Files referenced

| File | Purpose |
|---|---|
| `ensemble/scripts/build_graph.py` | Build dual graphs from VTD shapefile + enacted maps |
| `fdp/scripts/build_election_results_vtd.py` | Build votes parquet for scorer |
| `fdp/scripts/build_bvap_vtd.py` | Build demographics parquet for scorer |
| `ensemble/scripts/run_ensemble.py` | GerryChain runner |
| `fdp/scripts/score_ensemble_plans.py` | Partisan/competitiveness scoring |
| `fdp/scripts/score_ensemble_demographics.py` | Demographic scoring |
| `fdp/scripts/load_ensemble_scores.py` | Load scores into Supabase |
| `fdp/scripts/cdm_to_postgres.py` | Build full FDP schema in Postgres/Supabase |
| `fdp/scripts/migrate_ensemble_to_supabase.py` | Copy ensemble tables local → Supabase |
| `fdp/sql/postgres/003_analytics_spec.sql` | Analytics views and materialized views |
