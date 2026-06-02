# Fair Districts GA — Admin & Operations Guide

**Audience:** Technical admin running ensemble jobs, updating election data, managing the database, and maintaining the pipeline.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Environment Setup](#2-environment-setup)
3. [Running Ensemble Jobs](#3-running-ensemble-jobs)
4. [After a Run Completes — Scoring Pipeline](#4-after-a-run-completes--scoring-pipeline)
5. [Updating Election Data](#5-updating-election-data)
6. [Database Migrations](#6-database-migrations)
7. [Monitoring & Status Checks](#7-monitoring--status-checks)
8. [Handling Failed Runs](#8-handling-failed-runs)
9. [Generating Charts](#9-generating-charts)
10. [Secrets & Credentials](#10-secrets--credentials)
11. [Data Maintenance](#11-data-maintenance)

---

## 1. Prerequisites

| Tool | Purpose | Install |
|---|---|---|
| `uv` | Python package manager | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `modal` | Serverless compute for ensemble runs | `pip install modal && modal setup` |
| WSL 2 (Ubuntu) | Required — all scripts run in WSL | Windows feature |
| `psql` (optional) | Direct Supabase access for debugging | `sudo apt install postgresql-client` |

All commands below are run from **WSL** in the `~/codebox/fgdp` directory tree.

---

## 2. Environment Setup

### Install Python dependencies

```bash
cd ~/codebox/fgdp/fdp
uv sync
uv pip install -e .          # install fdp as editable package

cd ~/codebox/fgdp/fdga-chain
uv sync
```

### Set DATABASE_URL

The database URL must be set in the shell (or in `fdp/.env`) for all fdp scripts:

```bash
export DATABASE_URL="postgresql://postgres.<project>:<password>@aws-1-us-east-2.pooler.supabase.com:5432/postgres"
```

The connection string is the **session pooler** URL from the Supabase dashboard
(Project Settings → Database → Session pooler, port 5432).

Store it in `fdp/.env` so you don't have to export it each time:
```env
DATABASE_URL=postgresql://postgres.<project>:<password>@...
```

### Verify Modal secrets are current

```bash
cd ~/codebox/fgdp/fdga-chain
modal secret list
```

Required secrets:

| Secret name | Key | Purpose |
|---|---|---|
| `fdga-chain-db` | `DATABASE_URL` | Supabase connection from Modal containers |
| `fdga-chain-secrets` | `MAPBOX_TOKEN` | Map tile serving |

If `DATABASE_URL` changes (e.g. password rotation), update the Modal secret:
```bash
modal secret create fdga-chain-db DATABASE_URL="postgresql://..." --force
modal deploy modal_app.py    # MUST redeploy after secret change
```

> ⚠️ **Always redeploy after updating a Modal secret.** The deployed app
> caches secret references by ID; `--force` creates a new secret ID that
> the old deployment doesn't know about.

---

## 3. Running Ensemble Jobs

All ensemble runs use YAML benchmark configs in `fdp/configs/benchmarks/`.
Jobs are dispatched to Modal (serverless) and run asynchronously.

### Available configs

| File | Chamber | Districts | ε | Steps | Chains |
|---|---|---|---|---|---|
| `ga_congress_2026_v2.yml` | Congress | 14 | ±1% | 10,000 | 1 |
| `ga_senate_2026_v1.yml` | Senate | 56 | ±5% | 10,000 | 1 |
| `ga_house_2026_v1.yml` | House | 180 | ±5% | 10,000 | 5 |

### Fire a run (async — returns immediately)

```bash
cd ~/codebox/fgdp/fdga-chain

uv run python scripts/run_ensemble.py \
    --config ../fdp/configs/benchmarks/ga_congress_2026_v2.yml \
    --run-name congress_2026_v2 \
    --modal-async

# Senate
uv run python scripts/run_ensemble.py \
    --config ../fdp/configs/benchmarks/ga_senate_2026_v1.yml \
    --run-name senate_2026_v1 \
    --modal-async

# House
uv run python scripts/run_ensemble.py \
    --config ../fdp/configs/benchmarks/ga_house_2026_v1.yml \
    --run-name house_2026_v1 \
    --modal-async
```

### Fire a run (blocking — waits for completion)

Use `--modal` instead of `--modal-async`. Only practical for congress (≈17 min).

```bash
uv run python scripts/run_ensemble.py \
    --config ../fdp/configs/benchmarks/ga_congress_2026_v2.yml \
    --run-name congress_2026_v2 \
    --modal
```

### CLI parameter overrides

Any YAML value can be overridden at the CLI without editing the config:

```bash
# Quick test run — 500 steps, no DB write
uv run python scripts/run_ensemble.py \
    --chamber congress \
    --run-name test_500 \
    --n-steps 500 --burn-in 50 \
    --modal --no-db

# Re-run with different epsilon
uv run python scripts/run_ensemble.py \
    --config ../fdp/configs/benchmarks/ga_congress_2026_v2.yml \
    --run-name congress_v3_tight \
    --pop-epsilon 0.015 \
    --modal-async
```

### Dry-run (validate config without running)

```bash
uv run python scripts/run_ensemble.py \
    --config ../fdp/configs/benchmarks/ga_house_2026_v1.yml \
    --run-name dry_test \
    --dry-run
```

---

## 4. After a Run Completes — Scoring Pipeline

Once a run writes its plans parquet to the Modal volume, run these steps in order:

### Step 1 — Download plans from Modal

```bash
cd ~/codebox/fgdp/fdga-chain

modal volume get fdga-chain-data \
    /ensemble/congress_2026_v2_plans.parquet \
    ../congress_2026_v2_plans.parquet
```

### Step 2 — Score partisan metrics

Computes dem/rep votes, dem_2pv, winner per draw × district × election.
Writes to `fdp.ensemble_scores` in Supabase.

```bash
cd ~/codebox/fgdp

DATABASE_URL="..." uv run --project fdp python fdp/scripts/score_ensemble_plans.py \
    --run-name congress_2026_v2 \
    --plans-file congress_2026_v2_plans.parquet \
    --config fdp/configs/benchmarks/ga_congress_2026_v2.yml
```

### Step 3 — Score demographic metrics

Computes CVAP-based majority-minority flags per draw × district.
Writes to `fdp.ensemble_demographics` in Supabase.

```bash
DATABASE_URL="..." uv run --project fdp python fdp/scripts/score_ensemble_demographics.py \
    --run-name congress_2026_v2 \
    --plans-file congress_2026_v2_plans.parquet
```

### Step 4 — Build per-draw rollup stats

Aggregates seat counts, efficiency gap, mean-median, and competitive district
counts per draw. All computation happens server-side in PostgreSQL.

```bash
DATABASE_URL="..." uv run --project fdp python fdp/scripts/build_draw_stats.py \
    --run-name congress_2026_v2 \
    --config fdp/configs/benchmarks/ga_congress_2026_v2.yml
```

The `--config` flag reads `competitiveness.thresholds` from the YAML so no
threshold values are hardcoded. To use explicit thresholds instead:

```bash
DATABASE_URL="..." uv run --project fdp python fdp/scripts/build_draw_stats.py \
    --run-name congress_2026_v2 \
    --thresholds 0.05 0.07
```

### Step 5 — Generate charts

```bash
DATABASE_URL="..." uv run --project fdp python fdp/scripts/visualize_benchmark.py \
    --run-name congress_2026_v2 \
    --river-elections 2022_general_governor 2024_general_president 2021_runoff_senate
```

Charts are saved to `fdp/data/repos/main/ensemble/charts/`.

### Full pipeline (all chambers)

```bash
DB="postgresql://..."
RUNSCRIPTS="uv run --project fdp python"

for RUNNAME in congress_2026_v2 senate_2026_v1 house_2026_v1; do
    # Determine config
    CHAMBER=$(echo $RUNNAME | cut -d_ -f1)
    CONFIG="fdp/configs/benchmarks/ga_${CHAMBER}_2026_v1.yml"
    [ "$RUNNAME" = "congress_2026_v2" ] && CONFIG="fdp/configs/benchmarks/ga_congress_2026_v2.yml"

    # Download plans
    modal volume get fdga-chain-data /ensemble/${RUNNAME}_plans.parquet ./${RUNNAME}_plans.parquet

    # Score
    DATABASE_URL="$DB" $RUNSCRIPTS fdp/scripts/score_ensemble_plans.py \
        --run-name $RUNNAME --plans-file ./${RUNNAME}_plans.parquet --config $CONFIG

    DATABASE_URL="$DB" $RUNSCRIPTS fdp/scripts/score_ensemble_demographics.py \
        --run-name $RUNNAME --plans-file ./${RUNNAME}_plans.parquet

    DATABASE_URL="$DB" $RUNSCRIPTS fdp/scripts/build_draw_stats.py \
        --run-name $RUNNAME --config $CONFIG

    DATABASE_URL="$DB" $RUNSCRIPTS fdp/scripts/visualize_benchmark.py \
        --run-name $RUNNAME
done
```

---

## 5. Updating Election Data

### Adding a new election cycle (e.g. 2026)

New elections come from the **Redistricting Data Hub (RDH)** as block-level
shapefiles disaggregated to 2020 Census blocks.

1. **Download** from `redistrictingdatahub.org` — request or download the
   block-disaggregated shapefile for the target election year.

2. **Place** the shapefile in `fdensemble/input_data/` (gitignored).

3. **Add an entry** to `build_vtd_inputs.py` under the appropriate year
   section (follow the 2022/2024 pattern in the script).

4. **Run** the aggregation pipeline:
   ```bash
   cd ~/codebox/fgdp
   DATABASE_URL="..." uv run --project fdp python fdp/scripts/build_vtd_inputs.py \
       --only elections2026
   ```

5. **Verify** totals against GA Secretary of State certified results:
   ```bash
   # check_scores.py runs quick sanity queries
   DATABASE_URL="..." uv run --project fdp python fdp/scripts/check_scores.py
   ```

6. **Add the election** to the relevant YAML benchmark configs
   (`fdp/configs/benchmarks/ga_*_2026_*.yml`) and re-run the scoring pipeline.

### Updating CVAP data

CVAP (Citizen Voting Age Population) data is from the ACS 5-year estimates,
disaggregated to 2020 Census blocks by RDH.

```bash
# Re-run CVAP aggregation only
DATABASE_URL="..." uv run --project fdp python fdp/scripts/build_vtd_inputs.py \
    --only cvap
```

---

## 6. Database Migrations

All schema changes live in numbered SQL files in `fdp/sql/`.

### Apply a migration

```bash
cd ~/codebox/fgdp
DATABASE_URL="..." uv run --project fdp python fdp/scripts/apply_migration.py \
    fdp/sql/008_normalize_competitive_counts.sql
```

### Apply all migrations in order (first-time setup)

```bash
for f in fdp/sql/00*.sql; do
    echo "Applying $f..."
    DATABASE_URL="..." uv run --project fdp python fdp/scripts/apply_migration.py "$f"
done
```

### Migration history

| File | What it creates |
|---|---|
| `001_manifest.duckdb` | DuckDB manifest registry |
| `002_cdm.sql` | Core CDM tables (`election_results`, `district_demographics`) |
| `003_query_cache.sql` | LLM query cache |
| `004_ensemble_scores.sql` | `fdp.ensemble_scores` — per-draw partisan scores |
| `005_ensemble_runs.sql` | `fdp.ensemble_runs` catalog + `v_ensemble_runs` view |
| `006_draw_stats.sql` | `fdp.ensemble_draw_stats`, `fdp.ensemble_demographics`, views |
| `007_add_competitive_005.sql` | *(superseded by 008 — do not apply separately)* |
| `008_normalize_competitive_counts.sql` | Replaces hardcoded competitive columns with normalized `fdp.ensemble_competitive_counts` table |

---

## 7. Monitoring & Status Checks

### Check run catalog (from local machine)

```bash
cd ~/codebox/fgdp/fdga-chain
DATABASE_URL="..." modal run modal_app.py::list_runs
```

### Check run status via SQL

```sql
SELECT run_name, status, chamber, n_draws, runtime_minutes, started_at
FROM fdp.v_ensemble_runs
ORDER BY started_at DESC
LIMIT 20;
```

### Check Modal volume contents

```bash
modal volume ls fdga-chain-data /ensemble/
```

### Check scoring completeness

```sql
-- How many draws scored per run?
SELECT plan_id, COUNT(DISTINCT draw) AS n_draws, COUNT(DISTINCT year||office) AS n_races
FROM fdp.ensemble_scores
GROUP BY plan_id;

-- Quick distribution check
SELECT * FROM fdp.v_partisan_distribution
WHERE plan_id = 'congress_2026_v2'
ORDER BY year, office, dem_seats;

-- Enacted vs benchmark
SELECT * FROM fdp.v_enacted_vs_benchmark
WHERE plan_id = 'congress_2026_v2'
ORDER BY year, office;
```

### Check competitive counts are populated

```sql
SELECT plan_id, threshold, COUNT(*) AS rows
FROM fdp.ensemble_competitive_counts
GROUP BY plan_id, threshold
ORDER BY plan_id, threshold;
```

### Live Modal logs

```bash
cd ~/codebox/fgdp/fdga-chain
modal app logs fdga-chain --follow
```

---

## 8. Handling Failed Runs

### Identifying what went wrong

```bash
# Check catalog for failed runs
cd ~/codebox/fgdp/fdga-chain
DATABASE_URL="..." modal run modal_app.py::list_runs

# Tail recent logs (includes errors)
modal app logs fdga-chain 2>&1 | grep -E 'ERROR|Error|Traceback|failed' \
    | grep -v 'Runner failed\|secret\|fetch task' | tail -30
```

### Retrying a failed run

Simply refire with the same `--run-name`. The catalog upserts on conflict:

```bash
uv run python scripts/run_ensemble.py \
    --config ../fdp/configs/benchmarks/ga_house_2026_v1.yml \
    --run-name house_2026_v1 \
    --modal-async
```

### Clearing a run's data before a clean retry

```sql
-- Remove all data for a run (use with caution)
DELETE FROM fdp.ensemble_competitive_counts WHERE plan_id = 'house_2026_v1';
DELETE FROM fdp.ensemble_draw_stats       WHERE plan_id = 'house_2026_v1';
DELETE FROM fdp.ensemble_demographics     WHERE plan_id = 'house_2026_v1';
DELETE FROM fdp.ensemble_scores           WHERE plan_id = 'house_2026_v1';
DELETE FROM fdp.ensemble_runs             WHERE run_name = 'house_2026_v1';
```

### Partial retry (scoring only, plans already downloaded)

If the chain completed and the parquet is in the Modal volume but scoring failed:

```bash
# Download plans
modal volume get fdga-chain-data /ensemble/house_2026_v1_plans.parquet ./house_2026_v1_plans.parquet

# Run scoring steps only (skip chain generation)
DATABASE_URL="..." uv run --project fdp python fdp/scripts/score_ensemble_plans.py \
    --run-name house_2026_v1 \
    --plans-file ./house_2026_v1_plans.parquet \
    --config fdp/configs/benchmarks/ga_house_2026_v1.yml
```

---

## 9. Generating Charts

Charts are generated from data already in Supabase (draw stats must be built first).

```bash
cd ~/codebox/fgdp

# All charts for a run (partisan + competitiveness per threshold + demographics + river)
DATABASE_URL="..." uv run --project fdp python fdp/scripts/visualize_benchmark.py \
    --run-name congress_2026_v2

# Custom output directory
DATABASE_URL="..." uv run --project fdp python fdp/scripts/visualize_benchmark.py \
    --run-name congress_2026_v2 \
    --out-dir /tmp/charts

# Specify which elections to generate river charts for
DATABASE_URL="..." uv run --project fdp python fdp/scripts/visualize_benchmark.py \
    --run-name congress_2026_v2 \
    --river-elections 2022_general_governor 2024_general_president 2021_runoff_senate
```

Charts output to `fdp/data/repos/main/ensemble/charts/`:
- `{run}_partisan.png` — 2×3 histogram grid, one per election
- `{run}_competitiveness_{NN}pct.png` — one chart per threshold in the DB
- `{run}_demographics.png` — majority-minority district counts
- `{run}_river_{election}.png` — vote share band chart per election

---

## 10. Secrets & Credentials

### Current secrets

| Where | Name | What |
|---|---|---|
| `fdp/.env` | `DATABASE_URL` | Supabase session pooler URL |
| Modal | `fdga-chain-db` | `DATABASE_URL` for Modal containers |
| Modal | `fdga-chain-secrets` | `MAPBOX_TOKEN` |
| `fdga-chain/.env` | Various | Local dev only (not used in production) |

### Rotating the Supabase password

1. Rotate in Supabase dashboard (Project Settings → Database → Reset password)
2. Update `fdp/.env`
3. Update Modal secret and redeploy:
   ```bash
   modal secret create fdga-chain-db DATABASE_URL="postgresql://...new..." --force
   cd ~/codebox/fgdp/fdga-chain && modal deploy modal_app.py
   ```

### First-time Modal setup

```bash
pip install modal && modal setup   # opens browser for auth

modal secret create fdga-chain-db DATABASE_URL="postgresql://..."
modal secret create fdga-chain-secrets MAPBOX_TOKEN="pk.eyJ1..."

cd ~/codebox/fgdp/fdga-chain
uv run python scripts/upload_to_modal.py   # upload graphs + data to volume
modal deploy modal_app.py
```

---

## 11. Data Maintenance

### Rebuilding the VTD dual graphs

Required when:
- The enacted district shapefiles are replaced (new maps after redistricting)
- The VTD shapefile changes
- Population column changes

```bash
cd ~/codebox/fgdp/fdga-chain
uv run python scripts/build_graph.py      # rebuilds all three chambers

# Then upload the new graphs to Modal
uv run python scripts/upload_to_modal.py
modal deploy modal_app.py
```

### Validating election data against SOS certified results

After loading new elections, spot-check totals:

```sql
-- Total votes by candidate for a given election
SELECT office, candidate, SUM(votes) AS total_votes
FROM fdp.election_results
WHERE year = 2024 AND election_type = 'general'
GROUP BY office, candidate
ORDER BY office, total_votes DESC;
```

Compare against `sos.ga.gov/elections/election-results`.

### Disk / storage

| Location | What | Size |
|---|---|---|
| `fdensemble/input_data/` | Raw block shapefiles from RDH | ~5 GB |
| Modal volume `fdga-chain-data` | Graphs + plans parquets | ~50 MB |
| Supabase `fdp` schema | All scored data | ~2 GB |

`fdensemble/input_data/` is gitignored and does not need to be backed up —
source files can be re-downloaded from RDH.

### Checking Supabase table sizes

```sql
SELECT
    table_name,
    pg_size_pretty(pg_total_relation_size('fdp.' || table_name)) AS size,
    (SELECT COUNT(*) FROM fdp.ensemble_scores WHERE plan_id IS NOT NULL) AS rows
FROM information_schema.tables
WHERE table_schema = 'fdp'
ORDER BY pg_total_relation_size('fdp.' || table_name) DESC;
```
