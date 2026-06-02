# Fair Districts GA — Architecture Guide

**Audience:** Engineers and technical contributors who want to understand how
the redistricting ensemble pipeline is built, what each component does, and
how they connect.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Technology Stack](#2-technology-stack)
3. [Component Descriptions](#3-component-descriptions)
4. [Data Flow](#4-data-flow)
5. [Database Schema](#5-database-schema)
6. [Ensemble Pipeline Deep Dive](#6-ensemble-pipeline-deep-dive)
7. [Configuration System](#7-configuration-system)
8. [Deployment Architecture](#8-deployment-architecture)
9. [Key Design Decisions](#9-key-design-decisions)

---

## 1. System Overview

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        FAIR DISTRICTS GA SYSTEM                              │
│                                                                              │
│  INPUT DATA                COMPUTE (Modal)        STORAGE (Supabase)        │
│  ──────────                ──────────────────     ─────────────────         │
│  Census VTDs (2020)  ──→  GerryChain ReCom  ──→  fdp.ensemble_scores       │
│  RDH Election blocks ──→  run_ensemble.py   ──→  fdp.ensemble_draw_stats    │
│  RDH CVAP blocks     ──→  5 parallel chains ──→  fdp.ensemble_demographics  │
│  Enacted shapefiles  ──→                         fdp.ensemble_competitive_  │
│                            GRAPHS (Modal vol)         counts                │
│                            ga_congress.json   ──→  fdp.election_results     │
│                            ga_senate.json     ──→  fdp.ensemble_runs        │
│                            ga_house.json                                    │
│                                                                              │
│  LOCAL SCORING SCRIPTS               OUTPUT                                 │
│  ─────────────────────               ──────                                 │
│  score_ensemble_plans.py  ──────→    Charts (PNG)                           │
│  score_ensemble_demographics.py ──→  fdensemble frontend                    │
│  build_draw_stats.py       ──────→   v_enacted_vs_benchmark                 │
│  visualize_benchmark.py    ──────→                                          │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Technology Stack

### Core Languages

| Language | Where used | Version |
|---|---|---|
| Python | All backend scripts, fdp package, fdga-chain | 3.12 |
| SQL (PostgreSQL) | Supabase schema, all analytics | PostgreSQL 15 |
| TypeScript/Svelte | fdensemble frontend, fdex, map-compare | Svelte 5, Vite |
| R | ALARM data exports (archived) | 4.x |

### Python Libraries

| Library | Purpose |
|---|---|
| `gerrychain 0.3` | ReCom MCMC algorithm, graph construction, partition management |
| `geopandas 1.1` | Spatial data processing, CRS management, geometry operations |
| `shapely 2.1` | Geometry predicates (used by geopandas) |
| `pyarrow 23` | Parquet I/O for plans files and scoring output |
| `psycopg 3.x` | PostgreSQL driver (async-capable, psycopg3 style with `%s` params) |
| `numpy` | Vectorized matrix operations for ensemble scoring |
| `pandas` | DataFrame manipulation |
| `matplotlib / seaborn` | Chart generation |
| `modal` | Serverless compute API |
| `uv` | Package manager and virtual environment management |

### Infrastructure

| Service | Role | Plan |
|---|---|---|
| **Modal** | Serverless compute for GerryChain runs; persistent volume for plans parquets | Compute (pay-per-use) |
| **Supabase** | PostgreSQL database storing all scored results and run catalog | Free tier |
| **GitHub Actions** | CI/CD for frontend apps (fdex, lrdb, map-compare) | Free |
| **GitHub Pages** | Static hosting for frontend apps | Free |

---

## 3. Component Descriptions

### `fdp` — Fair Districts Data Platform

The shared data layer. A Python package used by all other components.

**Key responsibilities:**
- Owns the canonical copies of all data files (VTD shapefiles, election parquets, CVAP data)
- Provides typed loaders with built-in data quality checks
- Manages the benchmark config YAML hierarchy (`BenchmarkConfig` class)
- Contains all scoring and pipeline scripts
- Defines and manages the Supabase schema via numbered SQL migrations

**Important classes:**
- `fdp.benchmark_config.BenchmarkConfig` — loads YAML configs, resolves thresholds,
  provides `to_params_dict()` for Modal dispatch

**Directory:** `fdp/`

---

### `fdga-chain` — Ensemble Compute Layer

The compute layer that runs GerryChain on Modal and serves the API.

**Key responsibilities:**
- Builds VTD dual graphs from shapefiles (`build_graph.py`)
- Dispatches ensemble MCMC runs to Modal (`run_ensemble.py`)
- Manages Modal deployment and volume (`modal_app.py`, `upload_to_modal.py`)
- Serves the FastAPI ensemble results API (`api/main.py`)

**Important design:** Configs are fully resolved locally before dispatch.
The Modal function receives a plain Python dict — no YAML files needed in
the Modal container.

**Directory:** `fdga-chain/`

---

### `fdensemble` — Frontend Visualization

Svelte 5 frontend that displays ensemble benchmark results to end users.

**Key responsibilities:**
- Calls the fdga-chain FastAPI backend for ensemble statistics
- Displays partisan histograms, river charts, demographic charts
- Shows the Princeton grading results

**Directory:** `fdensemble/frontend/`

---

### `fdex` — Georgia Explorer

Consumer-facing interactive district map (static, no backend).

**Directory:** `fdex/`

---

### `fdworkbench` — Analytics Workbench

Natural language query interface over fdp data via DuckDB + LiteLLM.

**Directory:** `fdworkbench/`

---

## 4. Data Flow

### Input data preparation (one-time per election cycle)

```
Redistricting Data Hub (RDH)
  ga_2022_gen_2020_blocks.shp   (2.6 GB)
  ga_2024_gen_2020_blocks.shp   (2.6 GB)
  ga_cvap_2024_2020_b_csv.zip
           │
           ▼ fdp/scripts/build_vtd_inputs.py
           │
    Block → VTD aggregation
    (largest-overlap spatial join: each of 232,717 blocks assigned
     to 1 of 2,698 VTDs using intersection area)
           │
           ▼
    fdp.election_results (Supabase)
    ── geoid TEXT (11-char VTD GEOID20)
    ── year, election_type, office
    ── dem_votes, rep_votes
    ── CVAP_TOT, CVAP_BLK, CVAP_HSP, CVAP_WHT, CVAP_ASN
```

### Graph construction

```
Census 2020 VTD shapefile (ga_pl2020_vtd.zip)
  +
Enacted district shapefiles
  Congress-2023 shape.shp  (14 districts)
  Senate-2023 shape file.shp  (56 districts)
  House-2023 shape.shp  (180 districts)
           │
           ▼ fdga-chain/scripts/build_graph.py
           │
    For each VTD:
    1. Compute intersection area with each enacted district
    2. Assign VTD to district with largest intersection area
       (largest-overlap join — more accurate than centroid for
        small legislative districts like GA House)
    3. Build rook-adjacency dual graph
           │
           ▼
    fdga-chain/data/graphs/
      ga_congress.json  (2698 nodes, ~7705 edges)
      ga_senate.json
      ga_house.json
           │
           ▼ upload_to_modal.py
           │
    Modal volume /graphs/
```

### Ensemble run

```
BenchmarkConfig.from_yaml(config_path)
    │
    ├─ competitiveness.thresholds: [0.05]
    ├─ mcmc.n_steps: 10000
    ├─ mcmc.burn_in: 500 (congress) | 1000 (senate) | 2000 (house)
    ├─ mcmc.n_chains: 1 (congress/senate) | 5 (house)
    └─ mcmc.pop_epsilon: 0.01 (congress) | 0.05 (senate/house)
           │
           ▼ run_ensemble.py --modal-async
           │
    Modal: run_ensemble_on_modal()
      │
      ├─ For each chain (parallel):  run_single_chain_modal()
      │    1. Load graph from Modal volume
      │    2. Read enacted assignments from graph node attributes
      │    3. Compute actual max VTD-level pop deviation of enacted map
      │    4. Set constraint_epsilon = max(target_epsilon, max_dev × 1.05)
      │       [auto-widens to accept enacted plan as initial state]
      │    5. Run MarkovChain (ReCom, node_repeats=2, max_attempts=500)
      │    6. Row 0 = enacted plan (always)
      │    7. Rows 1+ = chain draws after burn-in
      │    8. Write {run_name}_chain{i}_plans.parquet to Modal volume
      │
      └─ Concatenate all chain parquets → {run_name}_plans.parquet
         Re-number draws globally: [1=enacted, 2..N=chain draws from all chains]
         Write to Modal volume + update fdp.ensemble_runs catalog
```

### Scoring pipeline

```
{run_name}_plans.parquet  (Modal volume)
  ── plan_id, draw, geoid, district
           │
           ├─▶ score_ensemble_plans.py
           │     ├─ Load election_results from Supabase for all 6 elections
           │     ├─ Build VTD→votes lookup dict
           │     ├─ Vectorized numpy: for each draw, sum votes per district
           │     └─ Upsert to fdp.ensemble_scores
           │
           ├─▶ score_ensemble_demographics.py
           │     ├─ Load CVAP columns from Supabase
           │     ├─ Vectorized numpy matrix multiply
           │     └─ Upsert to fdp.ensemble_demographics
           │
           └─▶ build_draw_stats.py
                 ├─ INSERT...SELECT (all computation server-side in PostgreSQL)
                 ├─ Writes fdp.ensemble_draw_stats (partisan rollup)
                 └─ Writes fdp.ensemble_competitive_counts (per threshold)
```

---

## 5. Database Schema

All tables live in the `fdp` schema in Supabase (PostgreSQL 15).

### `fdp.election_results`

VTD-level election results and CVAP data. One row per VTD per election.

```sql
CREATE TABLE fdp.election_results (
    geoid          TEXT NOT NULL,         -- 11-char Census VTD GEOID20
    year           INT  NOT NULL,         -- Election year (2018, 2020, 2021, 2022, 2024)
    election_type  TEXT NOT NULL,         -- 'general' | 'runoff'
    office         TEXT NOT NULL,         -- 'governor' | 'president' | 'senate'
    dem_votes      INT,
    rep_votes      INT,
    total_votes    INT,
    CVAP_TOT       INT,
    CVAP_BLK       INT,
    CVAP_HSP       INT,
    CVAP_WHT       INT,
    CVAP_ASN       INT,
    PRIMARY KEY (geoid, year, election_type, office)
);
```

### `fdp.ensemble_runs`

Catalog of all ensemble runs — one row per named run.

```sql
CREATE TABLE fdp.ensemble_runs (
    run_name       TEXT PRIMARY KEY,
    benchmark_id   TEXT,           -- YAML config name
    status         TEXT,           -- 'pending' | 'running' | 'completed' | 'failed'
    chamber        TEXT,           -- 'congress' | 'senate' | 'house'
    n_draws        INT,
    runtime_minutes NUMERIC,
    params         JSONB,          -- Full resolved config (reproducible)
    plans_file     TEXT,           -- Modal volume path
    started_at     TIMESTAMPTZ,
    updated_at     TIMESTAMPTZ
);
```

### `fdp.ensemble_scores`

Per-draw × district × election partisan scores. The largest table (~840k rows per run).

```sql
CREATE TABLE fdp.ensemble_scores (
    plan_id        TEXT NOT NULL,   -- = run_name
    draw           INT  NOT NULL,   -- 1 = enacted, 2..N = simulated
    district       INT  NOT NULL,   -- district number (1-indexed)
    year           INT  NOT NULL,
    election_type  TEXT NOT NULL,
    office         TEXT NOT NULL,
    dem_votes      INT,
    rep_votes      INT,
    total_votes    INT,
    dem_2pv        NUMERIC(8,6),    -- dem / (dem + rep), 0.0 to 1.0
    winner         TEXT,            -- 'dem' | 'rep' | 'tie'
    PRIMARY KEY (plan_id, draw, district, year, election_type, office)
);
```

### `fdp.ensemble_draw_stats`

Per-draw partisan rollup. Aggregated from ensemble_scores server-side.

```sql
CREATE TABLE fdp.ensemble_draw_stats (
    plan_id        TEXT NOT NULL,
    draw           INT  NOT NULL,
    year           INT  NOT NULL,
    election_type  TEXT NOT NULL,
    office         TEXT NOT NULL,
    dem_seats      INT,
    rep_seats      INT,
    tied_seats     INT,
    avg_dem_2pv    NUMERIC(8,6),
    efficiency_gap NUMERIC(8,6),   -- + = Republican advantage
    mean_median    NUMERIC(8,6),   -- + = Democratic skew
    PRIMARY KEY (plan_id, draw, year, election_type, office)
);
```

### `fdp.ensemble_competitive_counts`

Competitive district counts — normalized by threshold (no hardcoded column names).

```sql
CREATE TABLE fdp.ensemble_competitive_counts (
    plan_id        TEXT         NOT NULL,
    draw           INT          NOT NULL,
    year           INT          NOT NULL,
    election_type  TEXT         NOT NULL,
    office         TEXT         NOT NULL,
    threshold      NUMERIC(5,3) NOT NULL,   -- e.g. 0.050, 0.070
    n_competitive  INT          NOT NULL,
    PRIMARY KEY (plan_id, draw, year, election_type, office, threshold)
);
```

**Design note:** Thresholds are data values, not column names. Adding a new
threshold (e.g. 0.03) only requires updating the YAML config and rerunning
`build_draw_stats.py` — no schema changes needed.

### `fdp.ensemble_demographics`

CVAP-based district demographics per draw.

```sql
CREATE TABLE fdp.ensemble_demographics (
    plan_id                    TEXT NOT NULL,
    draw                       INT  NOT NULL,
    district                   INT  NOT NULL,
    cvap_tot                   INT,
    cvap_blk                   INT,
    cvap_hsp                   INT,
    cvap_wht                   INT,
    cvap_asn                   INT,
    pct_black                  NUMERIC(7,5),
    pct_hispanic               NUMERIC(7,5),
    pct_white                  NUMERIC(7,5),
    pct_asian                  NUMERIC(7,5),
    pct_minority_coalition     NUMERIC(7,5),
    majority_black             BOOLEAN,
    majority_white             BOOLEAN,
    majority_hispanic          BOOLEAN,
    majority_minority_coalition BOOLEAN,
    PRIMARY KEY (plan_id, draw, district)
);
```

### Key Views

| View | Purpose |
|---|---|
| `v_ensemble_runs` | Formatted run catalog with runtime in minutes |
| `v_partisan_distribution` | Histogram data: fraction of draws producing N dem seats |
| `v_competitive_distribution` | Histogram: competitive district counts by threshold |
| `v_demographic_draw_stats` | Per-draw majority-X district counts |
| `v_demographic_distribution` | Histogram: majority-minority district counts |
| `v_enacted_vs_benchmark` | **Main grading view** — enacted plan vs. ensemble on all metrics |
| `v_correlation_competitive_partisan` | Correlation between competitiveness and seat count |

---

## 6. Ensemble Pipeline Deep Dive

### GerryChain initialization

```python
# 1. Read enacted plan from graph (draw 1)
enacted_row = np.array([graph.nodes[n][district_col] for n in node_order])

# 2. Compute actual max VTD-level population deviation
dist_pop = defaultdict(int)
for n in node_order:
    dist_pop[graph.nodes[n][district_col]] += graph.nodes[n]['TOTPOP']
max_enacted_dev = max(abs(p - ideal_pop)/ideal_pop for p in dist_pop.values())

# 3. Auto-widen constraint epsilon
constraint_eps = max(epsilon, max_enacted_dev * 1.05)

# 4. Initialize from enacted plan (initial_state)
initial = GeographicPartition(graph, district_col, updaters=updaters)

# 5. Proposal: recom with capped max_attempts=500
fast_bipartition = partial(bipartition_tree, max_attempts=500)
proposal = partial(recom, ..., method=fast_bipartition)

# 6. Chain uses tight epsilon for proposals, wide constraint for acceptance
chain = MarkovChain(
    proposal    = proposal,                                    # epsilon=target
    constraints = [within_percent_of_ideal_population(initial, constraint_eps)],
    ...
)
```

**Why cap `max_attempts=500`?**

GerryChain's `bipartition_tree` emits a warning at 1,000 attempts and raises
`RuntimeError` at 10,000. Without the cap, chains can spin through 1,000–9,999
spanning tree attempts printing warnings but never raising the catchable error
— an infinite slow loop. Capping at 500 makes every failure fast, giving the
`_safe` handler control.

**Why auto-widen constraint epsilon?**

VTDs are larger than house districts in many parts of Georgia. Assigning a
whole VTD to one side of a district boundary introduces population rounding
error. The enacted maps were drawn at block precision; at VTD resolution, some
districts violate ±5% population equality. Without auto-widening, GerryChain
raises a `ValueError` before the chain starts. The proposals still enforce
the target epsilon; only the initial-state check uses the wider value.

### The `_safe` generator

```python
_MAX_CONSECUTIVE_FAILURES = 5

def _safe(c):
    """Skip stuck proposals; stop chain after 5 consecutive failures."""
    it = iter(c)
    consecutive = 0
    while True:
        try:
            consecutive = 0
            yield next(it)               # normal step — resets counter
        except RuntimeError as e:
            if "Could not find a possible cut" in str(e):
                consecutive += 1
                if consecutive >= _MAX_CONSECUTIVE_FAILURES:
                    return               # stop chain; keep draws collected so far
                # else: retry same state with new random spanning tree
            else:
                raise
        except StopIteration:
            return
```

**Key behavior:** A single `RuntimeError` from GerryChain means that particular
proposal attempt failed — the iterator is NOT corrupted. The chain resumes from
the same partition state, which usually finds a valid cut on the next try.
Only persistent consecutive failures (≥5) indicate a true dead-end.

### Vectorized scoring

Scoring 9,000 draws × 14 districts × 6 elections (756,000 combinations) uses
NumPy matrix multiplication rather than Python loops:

```python
# Build plan matrix: (n_draws, n_vtds) — district assignments
# Build votes matrix: (n_vtds,) — votes per VTD for one election

# For each district: sum votes across VTDs assigned to that district
# Using groupby equivalent via np.add.at:
dem_votes = np.zeros((n_draws, n_districts))
np.add.at(dem_votes, (draw_indices, district_indices), vtd_dem_votes)
```

This runs in seconds rather than the hours a pure Python loop would take.

---

## 7. Configuration System

### YAML benchmark configs

`fdp/configs/benchmarks/ga_{chamber}_2026_{version}.yml` defines everything
needed to reproduce a run:

```yaml
benchmark_id: ga_congress_2026_v2
chamber:
  name: congress
  n_districts: 14
  pop_epsilon: 0.01          # ±1% — Princeton/MGGG standard
elections:
  - {year: 2022, election_type: general, office: governor}
  - ...
competitiveness:
  thresholds: [0.05]         # threshold is DATA, not a column name
mcmc:
  algorithm: recom
  n_steps: 10000
  burn_in: 500
  n_chains: 1
```

`BenchmarkConfig.to_params_dict()` serializes the full config to a plain Python
dict that is sent to Modal as the job specification. No YAML files are needed
in the Modal container.

### Config naming convention

`ga_{chamber}_2026_v{N}.yml`

- `chamber`: `congress` | `senate` | `house`
- `2026`: redistricting cycle year
- `vN`: version number — increment when changing any parameter that affects
  comparability (ε, algorithm, elections list)

Runs from different versions should NOT be directly compared in visualizations
without noting the version difference.

---

## 8. Deployment Architecture

### Modal (ensemble compute)

```
fdga-chain/ repo
    │
    ├─ modal_app.py          ← App definition: secrets, volume, functions
    ├─ scripts/run_ensemble.py  ← Mounted into container as /root/scripts/
    └─ api/                  ← Mounted as /root/api/

Modal Volume: fdga-chain-data
    /graphs/     ← ga_congress.json, ga_senate.json, ga_house.json (~4 MB)
    /ensemble/   ← {run}_plans.parquet files (~8–80 MB each)
    /raw/        ← Enacted district shapefiles (used by build_graph.py)
    /states/     ← GA state config JSON

Modal Secrets:
    fdga-chain-db      → DATABASE_URL
    fdga-chain-secrets → MAPBOX_TOKEN
```

**After any code change to `scripts/run_ensemble.py` or `modal_app.py`:**
```bash
modal deploy modal_app.py
```

**After any change to the graphs or raw data:**
```bash
uv run python scripts/upload_to_modal.py
modal deploy modal_app.py
```

**After updating a Modal secret:**
```bash
modal secret create <name> <KEY>=<value> --force
modal deploy modal_app.py    # required — secret IDs change with --force
```

### Supabase (data storage)

Session pooler URL used by all scripts. The pooler handles connection multiplexing
for the serverless Modal containers. Direct connections can be used for migrations.

All writes use explicit `BEGIN READ WRITE` transactions because Supabase defaults
to read-only mode in some configurations.

### GitHub Actions (frontend CI/CD)

Each frontend app (fdex, lrdb, map-compare) has a `.github/workflows/` that
builds and deploys to GitHub Pages on every push to the main branch.

---

## 9. Key Design Decisions

### Why normalized competitive_counts table?

Hardcoding `n_competitive_007`, `n_competitive_010` as table columns meant
every new threshold required a schema migration AND code changes in 3 files.
The normalized `ensemble_competitive_counts(threshold, n_competitive)` approach
means adding any new threshold is one YAML config line; the scripts and
visualizations discover available thresholds at runtime from the data.

### Why `%s` not `%(name)s` for psycopg?

psycopg 3 (psycopg, not psycopg2) uses `%s` positional parameters, not
`%(name)s` named parameters. All SQL in this codebase uses positional `%s`.

### Why auto-widen constraint epsilon instead of recursive_tree_part?

`recursive_tree_part` was tried but fails for 180-district house maps because
the recursive bipartition algorithm itself hits the "no possible cut" error
during seed partition generation. The auto-widened constraint approach is simpler:
the constraint accepts the enacted plan (which violates ε at VTD resolution due
to large rural VTDs), while the proposal function still enforces the target ε
for all generated draws.

### Why draw=1 = enacted?

The convention `draw = 1 → enacted plan` is used throughout the scoring and
visualization code. It is enforced by prepending the enacted row before chain
draws in `run_chain()`, regardless of `burn_in`. This makes the enacted plan
trivially queryable in every SQL query: `WHERE draw = 1`.

### Why largest-overlap join for district assignment?

Centroid-in-polygon join assigns each VTD to the district containing its
centroid. For large rural VTDs, the centroid can be in a different district
than where most of the VTD's population lives — producing 88% max population
deviation for the GA House (180 districts × ~59k ideal pop).

The largest-overlap join assigns each VTD to the district it shares the most
geographic area with. This reduces the GA House max deviation from 88% to 33%.
The remaining deviation is irreducible at VTD resolution (VTDs genuinely span
multiple house districts in dense areas) and is handled by the auto-widened
constraint epsilon.

### Why Modal vs. local computation?

A single GA House run (10,000 steps × 5 chains) takes ~30 minutes on Modal
at ~30 steps/second. Locally on a laptop it would take 6+ hours. Modal's
serverless containers spin up in < 2 minutes and shut down automatically, with
no idle cost.

### Why score in Python, not in Modal?

The scoring step (matching plan VTD assignments to election vote totals) is
a data-join operation that runs against Supabase. Running it locally means the
developer can inspect, debug, and re-run individual scoring steps without
re-running the entire ensemble. Scoring takes ~30 seconds for a 10,000-draw run.
