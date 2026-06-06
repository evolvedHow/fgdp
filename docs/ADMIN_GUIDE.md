# Fair Districts GA — Admin & Operations Guide

**Audience:** Technical admin running ensemble jobs, updating election data, and maintaining the pipeline.

## Architecture

The scoring pipeline is **Parquet-only** — no live database server is required:

```
Modal volume          Local Parquet files               Charts / static JSON
──────────────   →   ─────────────────────────────   →   ──────────────────
*_plans.parquet       election_results_vtd.parquet         *_partisan.png
                      cvap_vtd.parquet                     *_river_*.png
                      ensemble/{run}_scores.parquet         *_demographics.png
                      ensemble/{run}_draw_stats.parquet
                      ensemble/{run}_demographics.parquet
                      ensemble/{run}_competitive_counts.parquet
```

All aggregation runs in **DuckDB in-process** — no Supabase, no PostgreSQL server.
Supabase has been fully eliminated from the scoring pipeline.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Environment Setup](#2-environment-setup)
3. [Running Ensemble Jobs](#3-running-ensemble-jobs)
4. [After a Run Completes — Scoring Pipeline](#4-after-a-run-completes--scoring-pipeline)
5. [Map Library (Proposed Plans)](#5-map-library-proposed-plans)
6. [Updating Election Data](#6-updating-election-data)
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

**`DATABASE_URL` is no longer needed** for the scoring pipeline. DuckDB reads
directly from local Parquet files. The only remaining use for `DATABASE_URL` is
the one-time Supabase export (see below).

### One-time: Export reference data from Supabase

Run this **once** to export election results and CVAP from Supabase to local
Parquet files. After this, the scoring pipeline has zero database dependency.

```bash
cd ~/codebox/fgdp
DATABASE_URL="postgresql://..." uv run --project fdp \
    python fdp/scripts/export_supabase_to_parquet.py

# Also free Supabase storage (truncates large tables):
DATABASE_URL="postgresql://..." uv run --project fdp \
    python fdp/scripts/export_supabase_to_parquet.py --free-supabase
```

This creates:
- `fdp/data/repos/main/election_results_vtd.parquet` — VTD-level election data
- `fdp/data/repos/main/cvap_vtd.parquet` — Citizen Voting Age Population by VTD

These files are gitignored (large). Store them on the local machine or Google Drive.

### Verify Modal secrets are current

```bash
cd ~/codebox/fgdp/fdga-chain
modal secret list
```

Required Modal secret:

| Secret name | Key | Purpose |
|---|---|---|
| `fdga-chain-secrets` | `MAPBOX_TOKEN` | Map tile serving (if needed) |

> ℹ️ The `fdga-chain-db` (Supabase) Modal secret is no longer needed — Modal
> containers write plans directly to the Modal volume, not to Supabase.

> ⚠️ **Always redeploy after updating a Modal secret.** `--force` on
> `modal secret create` changes the internal secret ID; the running app still
> references the old ID and will crash-loop until you redeploy.

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

Once a run writes its plans parquet to the Modal volume, run these steps in order.
**No `DATABASE_URL` needed** — all steps read/write local Parquet files via DuckDB.

### Prerequisite: reference data must exist

Before scoring any run, confirm these files exist (created by the one-time export):
```
fdp/data/repos/main/election_results_vtd.parquet
fdp/data/repos/main/cvap_vtd.parquet
```

If missing, run `export_supabase_to_parquet.py` (see §2).

### Step 1 — Download plans from Modal

```bash
cd ~/codebox/fgdp

modal volume get fdga-chain-data \
    /ensemble/congress_2026_v2_plans.parquet \
    fdp/data/repos/main/ensemble/congress_2026_v2_plans.parquet
```

### Step 2 — Score partisan metrics

Computes dem/rep votes, dem_2pv, winner per draw × district × election.
Reads `election_results_vtd.parquet`; writes `congress_2026_v2_scores.parquet`.

```bash
cd ~/codebox/fgdp

uv run --project fdp python fdp/scripts/score_ensemble_plans.py \
    --run-name congress_2026_v2
# Plans file auto-discovered at fdp/data/repos/main/ensemble/congress_2026_v2_plans.parquet
```

Or with an explicit plans file path:
```bash
uv run --project fdp python fdp/scripts/score_ensemble_plans.py \
    --run-name congress_2026_v2 \
    --plans-file /path/to/congress_2026_v2_plans.parquet
```

### Step 3 — Score demographic metrics

Computes CVAP-based majority-minority flags per draw × district.
Reads `cvap_vtd.parquet`; writes `congress_2026_v2_demographics.parquet`.

```bash
uv run --project fdp python fdp/scripts/score_ensemble_demographics.py \
    --run-name congress_2026_v2 \
    --plans-file fdp/data/repos/main/ensemble/congress_2026_v2_plans.parquet
```

### Step 4 — Build per-draw rollup stats

Aggregates seat counts, efficiency gap, mean-median, and competitive district
counts per draw. All computation runs in DuckDB in-process — no database server.

Writes:
- `congress_2026_v2_draw_stats.parquet`
- `congress_2026_v2_competitive_counts.parquet`

```bash
uv run --project fdp python fdp/scripts/build_draw_stats.py \
    --run-name congress_2026_v2 \
    --config fdp/configs/benchmarks/ga_congress_2026_v2.yml
```

The `--config` flag reads `competitiveness.thresholds` from the YAML — no
threshold values are hardcoded. To use explicit thresholds instead:

```bash
uv run --project fdp python fdp/scripts/build_draw_stats.py \
    --run-name congress_2026_v2 \
    --thresholds 0.05 0.07
```

### Step 5 — Generate charts

```bash
uv run --project fdp python fdp/scripts/visualize_benchmark.py \
    --run-name congress_2026_v2
```

Charts are saved to `fdp/data/repos/main/ensemble/charts/`.

### Step 6 — Build the scorecard JSON and deploy to fdensemble

This is the final step. `build_scorecard.py` reads all scored Parquets and
produces the canonical `{run_name}_scorecard.json` consumed by the fdensemble UI.

```bash
# Build scorecard (congress example)
uv run --project fdp python fdp/scripts/build_scorecard.py \
    --run-name fdga_2026_benchmark_congress

# For ALARM benchmark:
uv run --project fdp python fdp/scripts/build_alarm_scorecard.py

# Copy to fdensemble input_data/
cp fdp/data/repos/main/ensemble/fdga_2026_benchmark_congress_scorecard.json \
   ~/codebox/fgdp/fdensemble/input_data/

# Rebuild frontend (Railway uses pre-built dist/)
cd ~/codebox/fgdp/fdensemble/frontend && npm run build

# Commit and push → Railway auto-redeploys
cd ~/codebox/fgdp
git add fdensemble/input_data/fdga_2026_benchmark_congress_scorecard.json \
        fdensemble/frontend/dist/
git commit -m "Update fdga_2026_benchmark_congress scorecard"
git push origin master
```

**⚠️ Push to master is blocked by auto-mode classifier in Claude Code.**
Run the `git push` manually in your WSL terminal.

### Full pipeline (all chambers)

```bash
cd ~/codebox/fgdp
SCRIPTS="uv run --project fdp python"

for RUNNAME in congress_2026_v2 senate_2026_v1 house_2026_v1; do
    CHAMBER=$(echo $RUNNAME | cut -d_ -f1)
    CONFIG="fdp/configs/benchmarks/ga_${CHAMBER}_2026_v1.yml"
    [ "$RUNNAME" = "congress_2026_v2" ] && CONFIG="fdp/configs/benchmarks/ga_congress_2026_v2.yml"

    # Download plans from Modal
    modal volume get fdga-chain-data /ensemble/${RUNNAME}_plans.parquet \
        fdp/data/repos/main/ensemble/${RUNNAME}_plans.parquet

    # Score (no DATABASE_URL needed)
    $SCRIPTS fdp/scripts/score_ensemble_plans.py     --run-name $RUNNAME
    $SCRIPTS fdp/scripts/score_ensemble_demographics.py \
        --run-name $RUNNAME \
        --plans-file fdp/data/repos/main/ensemble/${RUNNAME}_plans.parquet
    $SCRIPTS fdp/scripts/build_draw_stats.py         --run-name $RUNNAME --config $CONFIG
    $SCRIPTS fdp/scripts/visualize_benchmark.py      --run-name $RUNNAME
done
```

---

---

## 5. Map Library (Proposed Plans)

The fdensemble app maintains a library of proposed GeoJSON plans that can be
scored against the ensemble. Maps are **not** uploaded from the browser UI —
they must be preloaded via the REST API after manual QC validation.

**Storage:**
- Local dev: `fdensemble/uploaded_maps/` (gitignored)
- Railway: `/app/uploaded_maps/` (persistent Railway volume — survives redeploys)
- Override: set `MAPS_DIR` env var

**Contents:** `catalog.json` + one `{map_id}.geojson` per map.

### Preloading a map

```bash
# Read the GeoJSON into a variable and POST it
GJ=$(cat my_proposed_plan.geojson | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d))")

curl -X POST https://<railway-url>/api/maps \
  -H "Content-Type: application/json" \
  -d "{\"label\": \"Proposed Plan A\", \"geojson\": $GJ}"
# → {"map_id":"abc123","label":"Proposed Plan A","n_districts":14,...}
```

Or from Python:
```python
import requests, json

with open("my_proposed_plan.geojson") as f:
    geojson = json.load(f)

resp = requests.post("https://<railway-url>/api/maps",
    json={"label": "Proposed Plan A", "geojson": geojson})
print(resp.json())  # {"map_id": "abc123", ...}
```

### Scoring a preloaded map

```bash
curl -X POST https://<railway-url>/api/score-map \
  -H "Content-Type: application/json" \
  -d '{"map_id": "abc123", "run_id": "fdga_2026_benchmark_congress"}'
```

Returns per-metric grades + percentile ranks for the proposed plan, using the
same histogram-approximation method as `_rank_and_grade()` in `main.py`.

### Removing a map

```bash
curl -X DELETE https://<railway-url>/api/maps/abc123
```

---

## 6. Updating Election Data

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
   uv run --project fdp python fdp/scripts/build_vtd_inputs.py \
       --only elections2026
   ```

5. **Re-export** the election results Parquet (since new elections were added):
   ```bash
   # Only needed if Supabase still holds the canonical copy; otherwise skip.
   # If using Parquet files only, update election_results_vtd.parquet directly.
   ```

6. **Add the election** to the relevant YAML benchmark configs
   (`fdp/configs/benchmarks/ga_*_2026_*.yml`) and re-run the scoring pipeline.

### Updating CVAP data

CVAP (Citizen Voting Age Population) data is from the ACS 5-year estimates,
disaggregated to 2020 Census blocks by RDH.

```bash
# Re-run CVAP aggregation only
uv run --project fdp python fdp/scripts/build_vtd_inputs.py --only cvap
# Then re-export to update cvap_vtd.parquet:
#   python fdp/scripts/export_supabase_to_parquet.py  (if Supabase still available)
# Or update cvap_vtd.parquet directly from the VTD aggregation output.
```

---

## 7. Monitoring & Status Checks

### Check Modal volume contents

```bash
modal volume ls fdga-chain-data /ensemble/
```

### Check scoring completeness (local Parquet files)

```python
# Quick DuckDB inspection — run from Python or paste into a script
import duckdb, pathlib

data = pathlib.Path("fdp/data/repos/main/ensemble")
for f in sorted(data.glob("*_draw_stats.parquet")):
    run = f.stem.replace("_draw_stats", "")
    conn = duckdb.connect()
    r = conn.execute(
        "SELECT COUNT(DISTINCT draw) AS draws, COUNT(DISTINCT year||office) AS races "
        "FROM read_parquet(?)", [str(f)]
    ).fetchone()
    print(f"{run}: {r[0]} draws × {r[1]} races")
```

### Quick distribution check

```python
import duckdb
conn = duckdb.connect()
conn.execute("""
    SELECT year, office, dem_seats, COUNT(*) AS n_draws,
        ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (PARTITION BY year, office), 1) AS pct
    FROM read_parquet('fdp/data/repos/main/ensemble/congress_2026_v2_draw_stats.parquet')
    WHERE draw > 1
    GROUP BY year, office, dem_seats
    ORDER BY year, office, dem_seats
""").df()
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

Simply delete the run's Parquet files and re-run scoring:

```bash
cd ~/codebox/fgdp
DATA=fdp/data/repos/main/ensemble
rm -f $DATA/house_2026_v1_scores.parquet
rm -f $DATA/house_2026_v1_demographics.parquet
rm -f $DATA/house_2026_v1_draw_stats.parquet
rm -f $DATA/house_2026_v1_competitive_counts.parquet
```

### Partial retry (scoring only, plans already downloaded)

If the chain completed and the parquet is in the Modal volume but scoring failed:

```bash
# Download plans from Modal (if not already local)
modal volume get fdga-chain-data /ensemble/house_2026_v1_plans.parquet \
    fdp/data/repos/main/ensemble/house_2026_v1_plans.parquet

# Run scoring steps only (skip chain generation) — no DATABASE_URL needed
uv run --project fdp python fdp/scripts/score_ensemble_plans.py \
    --run-name house_2026_v1
uv run --project fdp python fdp/scripts/score_ensemble_demographics.py \
    --run-name house_2026_v1 \
    --plans-file fdp/data/repos/main/ensemble/house_2026_v1_plans.parquet
uv run --project fdp python fdp/scripts/build_draw_stats.py \
    --run-name house_2026_v1 --config fdp/configs/benchmarks/ga_house_2026_v1.yml
```

---

## 9. Generating Charts

Charts read from local Parquet files — draw stats must be built first (§4 Step 4).
No `DATABASE_URL` needed.

```bash
cd ~/codebox/fgdp

# All charts for a run (partisan + competitiveness per threshold + demographics + river)
uv run --project fdp python fdp/scripts/visualize_benchmark.py \
    --run-name congress_2026_v2

# Custom output directory
uv run --project fdp python fdp/scripts/visualize_benchmark.py \
    --run-name congress_2026_v2 \
    --out-dir /tmp/charts

# Specify which elections to generate river charts for
uv run --project fdp python fdp/scripts/visualize_benchmark.py \
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
| Modal | `fdga-chain-secrets` | `MAPBOX_TOKEN` (if map serving is needed) |
| `fdga-chain/.env` | Various | Local dev only |

**Supabase / `DATABASE_URL` is no longer used.** The scoring pipeline runs
fully local via DuckDB; Modal containers write plans to the Modal volume only.

### First-time Modal setup

```bash
pip install modal && modal setup   # opens browser for auth

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

After loading new elections, spot-check totals using DuckDB:

```python
import duckdb
conn = duckdb.connect()
conn.execute("""
    SELECT office, party, SUM(votes) AS total_votes
    FROM read_parquet('fdp/data/repos/main/election_results_vtd.parquet')
    WHERE year = 2024 AND election_type = 'general'
    GROUP BY office, party
    ORDER BY office, total_votes DESC
""").df()
```

Compare against `sos.ga.gov/elections/election-results`.

### Disk / storage

| Location | What | Size |
|---|---|---|
| `fdensemble/input_data/` | Raw block shapefiles from RDH | ~5 GB |
| Modal volume `fdga-chain-data` | Graphs + plans parquets | ~50 MB |
| `fdp/data/repos/main/` | Reference + scored Parquet files | ~500 MB |
| ~~Supabase~~ | ~~All scored data~~ | Eliminated |

`fdensemble/input_data/` is gitignored — source files can be re-downloaded from RDH.
`fdp/data/repos/main/` is gitignored — keep a local copy or on Google Drive.
