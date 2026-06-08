# fdp — Fair Districts Data Platform

Shared data management layer for all fairdistrictsga.org apps.
Used as a Python package by `fdga-chain` and as a data source
(via `fdp sync-app`) by `fdex`, `lrdb`, and `map-compare`.

---

## Purpose

Before fdp, each app maintained its own copy of the ~50 MB GeoJSON boundary
library, and each had its own Census/election fetch scripts.  fdp solves this:

- **Single source of truth** for all boundary GeoJSONs, demographic data,
  election parquets, precinct shapefiles, and ensemble outputs
- **Typed Python loaders** with built-in data quality checks
- **Hierarchical YAML config** — global locked settings, overridable defaults,
  and per-app overrides in one place
- **Workspace isolation** — test new data files privately without affecting other
  apps or developers
- **CLI** for workspace management, catalog inspection, validation, and
  app-specific data sync

---

## Directory Layout

```
fdp/
├── config/
│   ├── global.yml          ← LOCKED: platform, repos, data schema, quality checks
│   ├── defaults.yml        ← Overridable defaults: map, llm, chain, export
│   └── apps/
│       ├── fdex.yml        ← fdex overrides + plan catalogue + overlay definitions
│       ├── fdga_chain.yml  ← fdga-chain overrides + data paths
│       ├── lrdb.yml        ← lrdb overrides + filter field definitions
│       └── map_compare.yml ← map-compare overrides + plan catalogue
├── data/
│   ├── repos/
│   │   └── main/           ← Canonical shared data repository
│   │       ├── boundaries/
│   │       │   ├── congress/   ← congress_*.geojson
│   │       │   ├── house/      ← house_*.geojson
│   │       │   ├── senate/     ← senate_*.geojson
│   │       │   └── reference/  ← county.geojson, places_2020data.geojson
│   │       ├── demographics/   ← congress.json, house.json, senate.json
│   │       ├── elections/      ← dim_elections.parquet, dim_swings.parquet
│   │       ├── precincts/      ← MGGG shapefiles (see precincts/README.md)
│   │       ├── graphs/         ← GerryChain dual-graph JSON
│   │       ├── ensembles/      ← ReCom output parquets + meta + stability
│   │       └── lrdb/           ← lrdb_web_*.geojson + update_helper/
│   └── workspaces/         ← Private per-developer data overlays
├── fdp/                    ← Python package
│   ├── __init__.py         ← Exports DataPlatform
│   ├── platform.py         ← DataPlatform — main entry point
│   ├── config.py           ← Hierarchical YAML config loader
│   ├── repos.py            ← Repo + workspace registry
│   ├── catalog.py          ← Data inventory with rich table output
│   ├── cli.py              ← Click CLI (fdp command)
│   ├── loaders/
│   │   ├── base.py         ← BaseLoader ABC with quality hook
│   │   ├── boundaries.py   ← GeoJSON boundary loader
│   │   ├── demographics.py ← ACS/Census demographic loader
│   │   ├── elections.py    ← Election parquet/CSV loader
│   │   ├── precincts.py    ← MGGG shapefile loader + column normalisation
│   │   └── ensembles.py    ← GerryChain ensemble/graph/stability loader
│   └── quality/
│       └── checks.py       ← QualityReport, check_crs, check_geometry_validity, …
├── scripts/
│   ├── migrate_data.py     ← One-time migration from app directories into fdp
│   ├── fetch_boundaries.py ← Validate boundary presence + CRS
│   ├── fetch_demographics.py ← Pull ACS 5-year + PL 94-171 from Census API
│   ├── fetch_elections.py  ← Process SOS election CSVs → parquet
│   └── validate.py         ← Thin wrapper around `fdp validate`
├── pyproject.toml
├── .env.example
└── README.md
```

---

## Setup

```bash
cd ~/codebox/fdp
uv sync
uv pip install -e .     # install as editable package so apps can import fdp
cp .env.example .env    # add CENSUS_API_KEY if fetching fresh data
```

`.env` values:

```env
FDP_ROOT=/home/vgana/codebox/fgdp/fdp    # defaults to fdp project root
CENSUS_API_KEY=                     # required for fetch_demographics.py
GROQ_API_KEY=                       # for LLM-dependent apps
OLLAMA_HOST=http://localhost:11434
```

---

## Config Hierarchy

Resolution order (later wins, except for locked global keys):

```
global.yml  ──────────────────── always wins for locked keys
   ↓ merged on top of ↓
defaults.yml  ─────────────────── overridable defaults
   ↓ merged on top of ↓
apps/<app>.yml  ────────────────── per-app overrides
   ↓ activates repo ↓
FDP_WORKSPACE env var  ─────────── workspace overlay (file-level fallback)
```

**Locked keys** (defined in `global.yml`, always restored after any merge):
`platform`, `repos`, `data_layout`, `data_schema`, `quality`

These control the physical data layout, schema contracts, and quality check
configuration.  No app config can change them.

**Overridable keys** (in `defaults.yml`, overridable in `apps/*.yml`):
`app`, `map`, `llm`, `chain`, `export`, `plans`, `overlays`, `reference_layers`,
`demographics`, `data`, `filters`

### Example: how `map.zoom` resolves for fdex

```
defaults.yml:      map.zoom = 6.0
apps/fdex.yml:     map.zoom = 5.5    (overrides default)
→ resolved value:  5.5
```

### Example: how `platform.state` is locked

```
global.yml:        platform.state = "GA"
apps/fdex.yml:     (any attempt to set platform.state is silently ignored)
→ resolved value:  "GA"  (always)
```

---

## Python Package Usage

```python
from fdp import DataPlatform

# Load with app config
p = DataPlatform(app="fdga_chain")

# Load a boundary GeoDataFrame (CRS auto-normalised to EPSG:4326)
gdf = p.boundaries.load("congress_enacted_24", chamber="congress")

# Load district demographics
demo = p.demographics.load("congress")   # → dict

# Load election results
df = p.elections.load("elections")       # → DataFrame

# Load MGGG precinct shapefile (columns auto-normalised)
gdf = p.precincts.load("congress")

# Load ensemble data
ensemble_df  = p.ensembles.load_ensemble("house")
meta         = p.ensembles.load_meta("house")
stability    = p.ensembles.load_stability("house")
graph        = p.ensembles.load_graph("house")

# Resolve a raw file path (workspace-aware)
path = p.resolve("boundaries/congress/congress_enacted_24_2024update.geojson")

# Data catalog
p.catalog.print_summary()

# Workspace management
ws = p.registry.create_workspace("test", base="main", description="testing")
p.registry.delete_workspace("test")
```

---

## Workspace Isolation

A workspace is a private overlay directory.  Files not present in the workspace
automatically fall back to the base repo (default: `main`).

```bash
# Create a workspace for testing a new congressional shapefile
fdp workspace create my_shapes --base main --desc "Testing 2026 remedial map"

# Copy only the file you're replacing (everything else falls through to main)
cp ~/new_congress.geojson \
   data/workspaces/my_shapes/boundaries/congress/congress_enacted_24_2024update.geojson

# Activate in your shell
export FDP_WORKSPACE=my_shapes

# Any app or script now uses your file for that one GeoJSON;
# all other requests fall through to data/repos/main/

# List workspaces
fdp workspace list

# Clean up when done
fdp workspace delete my_shapes
```

Workspace activation priority:
1. `DataPlatform(repo="my_shapes")` — explicit Python arg
2. `FDP_WORKSPACE=my_shapes` env var
3. `app.repo: my_shapes` in `apps/<app>.yml`
4. Default: `main` repo

---

## CLI Reference

```
fdp workspace create <name> [--base main] [--desc "..."]
fdp workspace list
fdp workspace delete <name> [--yes]

fdp catalog [--app <app>] [--repo <repo>]
fdp validate [--app <app>] [--repo <repo>] [--category boundaries] [--halt]
fdp sync-app <app> --dest <dir> [--repo <repo>] [--dry-run]
```

All commands accept `--fdp-root` to override `FDP_ROOT`.

---

## Data Loaders

### BoundaryLoader

Loads GeoJSON district boundaries.  Auto-reprojects to EPSG:4326.

```python
# By logical ID (from app config plan catalogue)
gdf = p.boundaries.load("congress_enacted_24", chamber="congress")

# By filename
gdf = p.boundaries.load("congress_enacted_24_2024update.geojson", chamber="congress")

# Reference layer
gdf = p.boundaries.load("county.geojson", chamber="reference")

# List all available
paths = p.boundaries.list_available(chamber="congress")
```

**Quality checks run:** CRS validation, geometry validity

### PrecinctLoader

Loads MGGG precinct shapefiles with automatic column normalisation.  Canonical
column names: `TOTPOP`, `BVAP`, `HVAP`, `AVAP`, `DEM_VOTES`, `REP_VOTES`,
`HDIST`, `SDIST`, `CDIST`.

```python
gdf = p.precincts.load("congress")
```

**Quality checks run:** CRS, geometry validity, required columns present, no
negative population values

### EnsembleLoader

Loads GerryChain outputs by chamber name.

```python
df       = p.ensembles.load_ensemble("house")    # 10,000 × metrics DataFrame
meta     = p.ensembles.load_meta("house")         # dict: algorithm, steps, runtime
stability = p.ensembles.load_stability("house")   # dict: precinct → stability score
graph    = p.ensembles.load_graph("house")        # GerryChain adjacency JSON
```

**Quality checks run:** Required metric columns present

---

## Quality Checks

All loaders run quality checks via `fdp/quality/checks.py`.  Results are emitted
as `warnings.warn()` by default; set `halt_on_error=True` to raise instead.

| Check | What it validates |
|---|---|
| `crs_is_wgs84` | GeoDataFrame CRS is EPSG:4326 |
| `no_invalid_geometries` | No null or topologically invalid geometries |
| `no_null_required_columns` | Required columns present and non-null |
| `population_totals_reasonable` | Total population not suspiciously low; no zero-pop rows |
| `no_overlapping_districts` | Districts don't overlap significantly |
| `districts_fully_cover_state` | Districts cover ≥99% of state area |

Run all checks against a repo:

```bash
fdp validate --repo main --category boundaries
fdp validate --halt     # exit non-zero on first error
```

---

## Data Migration (One-Time)

Migrate all GeoJSON files from the existing app directories into fdp:

```bash
cd ~/codebox/fdp

# Dry run first — shows exactly what would be copied
uv run python scripts/migrate_data.py

# Execute the migration
uv run python scripts/migrate_data.py --execute

# With conflict resolution and post-migration validation
uv run python scripts/migrate_data.py --execute --overwrite --validate
```

Sources scanned:
- `fdex/data/` → boundaries + demographics
- `map-compare/public/data/` → boundaries (deduplicated against fdex)
- `lrdb/public/assets/` → lrdb GeoJSON + helper CSVs
- `fdga-chain/data/graphs/` → GerryChain graphs
- `fdga-chain/data/ensembles/` → ensemble parquets + meta + stability

---

## Populating Data from Scratch

If starting fresh (no existing app data to migrate):

```bash
# 1. Boundaries — manually copy GeoJSON from GA General Assembly portal
#    https://redistrictingdatahub.org/state/georgia/
#    → data/repos/main/boundaries/{congress,house,senate,reference}/
python scripts/fetch_boundaries.py    # validates presence + CRS

# 2. Demographics — fetch from Census API (requires CENSUS_API_KEY)
python scripts/fetch_demographics.py

# 3. Elections — place raw CSVs in data/repos/main/elections/raw/, then:
python scripts/fetch_elections.py

# 4. Precincts — see data/repos/main/precincts/README.md

# 5. LRDB — copy from lrdb project
cp ../lrdb/public/assets/*.geojson     data/repos/main/lrdb/
cp -r ../lrdb/public/assets/update_helper/ data/repos/main/lrdb/

# 6. Ensembles + graphs — copy from fdga-chain project
cp ../fdga-chain/data/graphs/*.json     data/repos/main/graphs/
cp ../fdga-chain/data/ensembles/*.parquet data/repos/main/ensembles/
cp ../fdga-chain/data/ensembles/*.json  data/repos/main/ensembles/
```

---

## Syncing Data to Apps

After populating `data/repos/main/`, push data to each app:

```bash
fdp sync-app fdex        --dest ../fdex/data/
fdp sync-app map_compare --dest ../map-compare/public/data/
fdp sync-app lrdb        --dest ../lrdb/public/assets/

# Or use each app's npm script
cd ../fdex/frontend    && npm run sync
cd ../map-compare      && npm run sync
cd ../lrdb             && npm run sync
```

`sync-app` reads the app's `config/apps/{app}.yml` to determine which files
are needed, then copies them from the active repo (workspace-aware).

---

## Adding a New App

1. Create `config/apps/{new_app}.yml` with overrides and data catalogue
2. Add the app's data paths to the loaders (or use `p.resolve(rel_path)` directly)
3. Create `{new_app}/scripts/sync_data.sh` calling `fdp sync-app {new_app} --dest ...`
4. Add `"sync": "bash scripts/sync_data.sh"` to `{new_app}/package.json`
5. For Python apps, add `fdp = { path = "../fdp", editable = true }` to
   `pyproject.toml`

---

## Benchmark Scoring Pipeline

The scoring pipeline converts GerryChain ensemble parquets into a **scorecard
JSON** that fdensemble reads directly. All scripts accept a `--config` argument
pointing to a YAML file in `configs/benchmarks/`.

### Step 1: Build VTD inputs (run once per election cycle)

```bash
# Aggregate block-level data to VTD level → vtd_composite.parquet + vtd_demographics.parquet
python scripts/build_vtd_inputs.py \
    --config configs/benchmarks/ga_congress_2026_v1.yml
```

This produces the VTD-level election composites and demographics files consumed
by all downstream scoring scripts.

### Step 2: Score ensemble plans

```bash
# Compute partisan metrics per draw
python scripts/score_ensemble_plans.py \
    --config configs/benchmarks/ga_congress_2026_v1.yml \
    --plans /path/to/congress_plans.parquet

# Compute demographic metrics per draw
python scripts/score_ensemble_demographics.py \
    --config configs/benchmarks/ga_congress_2026_v1.yml \
    --plans /path/to/congress_plans.parquet
```

### Step 3: Build the scorecard JSON

```bash
python scripts/build_scorecard.py \
    --config configs/benchmarks/ga_congress_2026_v1.yml \
    --scores /path/to/scored_plans.parquet \
    --vtd-composite ../fdensemble/data/vtd_composite.parquet \
    --vtd-demographics ../fdensemble/data/vtd_demographics.parquet \
    --vtd-muni ../fdensemble/data/vtd_muni.parquet \
    --output ../fdensemble/input_data/fdga_2026_benchmark_congress_scorecard.json
```

The output JSON contains pre-computed Princeton grades, histograms, river data,
proportionality gap, correlation matrix, and demographic threshold arrays for
every metric. fdensemble reads it at startup — no database required.

### Benchmark Config YAML

Every benchmark run is fully described by a YAML file in `configs/benchmarks/`.
Nothing is hardcoded in the scoring scripts.

```
configs/benchmarks/
├── ga_congress_2026_v1.yml    ← GerryChain ReCom, 99K draws
├── ga_congress_2026_alarm.yml ← ALARM SMC, 5K draws
├── ga_senate_2026_v1.yml      ← Senate 56 districts
└── ga_house_2026_v1.yml       ← House 180 districts
```

Key YAML sections:

```yaml
benchmark_id: ga_congress_2026_v1
chamber:
  name: congress
  n_districts: 14
geography:
  state: GA
  geo_level: vtd
  vintage_year: 2020
elections:
  - label: "2018–2024 Composite"
    composite: true
    years: [2018, 2020, 2022, 2024]
demographics:
  thresholds: [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]
  default_threshold: 0.50
competitiveness:
  thresholds: [0.035, 0.05]   # 7pt and 10pt margins
grading:
  ensemble_pass_lo: 5
  ensemble_pass_hi: 95
```

The `BenchmarkConfig` dataclass in `fdp/benchmark_config/benchmark.py` loads
these YAMLs and is the single source of truth for all parameters. Import it
from any scoring script:

```python
from fdp.benchmark_config.benchmark import BenchmarkConfig
cfg = BenchmarkConfig.from_yaml("configs/benchmarks/ga_congress_2026_v1.yml")
print(cfg.chamber.n_districts)   # 14
print(cfg.benchmark_id)          # "ga_congress_2026_v1"
```

---

## Related Projects

| Project | How it uses fdp |
|---|---|
| **fdex** | `npm run sync` copies GeoJSON from fdp; reads `fdp/config/apps/fdex.yml` |
| **fdga-chain** | Python import; `DataPlatform(app="fdga_chain")` resolves all data paths |
| **lrdb** | `npm run sync` copies GeoJSON + helper CSVs from fdp |
| **map-compare** | `npm run sync` copies GeoJSON from fdp |
| **fdensemble** | Reads scorecard JSONs from `input_data/` (built by `build_scorecard.py`); reads VTD parquets from `data/` |
