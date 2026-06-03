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
5. [Canonical Scorecard Format](#5-canonical-scorecard-format)
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
│  INPUT DATA                COMPUTE (Modal)        LOCAL PARQUET FILES       │
│  ──────────                ──────────────────     ─────────────────────     │
│  Census VTDs (2020)  ──→  GerryChain ReCom  ──→  *_plans.parquet           │
│  RDH Election blocks ──→  run_ensemble.py   ──→  (Modal volume)             │
│  RDH CVAP blocks     ──→  5 parallel chains                                 │
│  Enacted shapefiles  ──→                                                    │
│                            GRAPHS (Modal vol)                               │
│                            ga_congress.json                                 │
│                            ga_senate.json                                   │
│                            ga_house.json                                    │
│                                                                              │
│  SCORING PIPELINE (fdp/scripts/)              OUTPUT                        │
│  ────────────────────────────────             ──────                        │
│  score_ensemble_plans.py    ──────→           *_scores.parquet              │
│  score_ensemble_demographics.py ──→           *_demographics.parquet        │
│  build_draw_stats.py        ──────→           *_draw_stats.parquet          │
│  build_scorecard.py         ──────→           *_scorecard.json   ──→  UI   │
│  visualize_benchmark.py     ──────→           charts/*.png                  │
│                                                                              │
│  All aggregation: DuckDB in-process  (no database server)                  │
│  ALARM/Harvard data: fdensemble/dataverse_files/ (direct CSV read)         │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Technology Stack

### Core Languages

| Language | Where used | Version |
|---|---|---|
| Python | All backend scripts, fdp package, fdga-chain | 3.12 |
| SQL (DuckDB) | All analytics queries — runs in-process, no server | DuckDB 1.1+ |
| TypeScript/Svelte | fdensemble frontend, fdex, map-compare | Svelte 5, Vite |
| R | ALARM data exports (archived) | 4.x |

### Python Libraries

| Library | Purpose |
|---|---|
| `gerrychain 0.3` | ReCom MCMC algorithm, graph construction, partition management |
| `geopandas 1.1` | Spatial data processing, CRS management, geometry operations |
| `shapely 2.1` | Geometry predicates (used by geopandas) |
| `pyarrow 23` | Parquet I/O for plans files and scoring output |
| `duckdb 1.1+` | In-process OLAP engine — reads Parquet via `read_parquet(?)`, replaces PostgreSQL |
| `numpy` | Vectorized matrix operations for ensemble scoring |
| `pandas` | DataFrame manipulation |
| `matplotlib / seaborn` | Chart generation |
| `modal` | Serverless compute API |
| `uv` | Package manager and virtual environment management |

### Infrastructure

| Service | Role | Plan |
|---|---|---|
| **Modal** | Serverless compute for GerryChain runs; persistent volume for `*_plans.parquet` | Compute (pay-per-use) |
| **Local disk** | All scored Parquet files (`fdp/data/repos/main/ensemble/`) | Free — not committed to git |
| **GitHub Actions** | CI/CD for frontend apps (fdex, lrdb, map-compare) | Free |
| **GitHub Pages** | Static hosting for frontend apps | Free |
| **Railway** | fdensemble FastAPI backend (reads local dataverse CSV + scorecard JSON) | Hobby plan |

> **Note:** Supabase was used in earlier versions of this project. It has been eliminated entirely. All data is now stored as Parquet files on local disk / Modal volume and queried via DuckDB in-process.

---

## 3. Component Descriptions

### `fdp` — Fair Districts Data Platform

The shared data layer. A Python package used by all other components.

**Key responsibilities:**
- Owns the canonical copies of all reference data (VTD shapefiles, election Parquets, CVAP data)
- Provides typed loaders with built-in data quality checks
- Manages the benchmark config YAML hierarchy (`BenchmarkConfig` class)
- Contains all scoring and pipeline scripts
- Produces `*_scorecard.json` files (canonical format shared with fdensemble UI)

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
{run_name}_plans.parquet  (downloaded from Modal volume)
  ── plan_id, draw, geoid, district
           │
           ├─▶ score_ensemble_plans.py
           │     ├─ Load election_results_vtd.parquet via DuckDB
           │     ├─ Load plan matrix: DuckDB SQL index mapping (avoids 64M Python string objects)
           │     ├─ Vectorized numpy: boolean mask × matrix multiply per district
           │     └─ Write {run_name}_scores.parquet (dem_2pv, winner per draw×district×election)
           │
           ├─▶ score_ensemble_demographics.py
           │     ├─ Load cvap_vtd.parquet via pandas
           │     ├─ Same DuckDB plan matrix loader
           │     ├─ Vectorized numpy matrix multiply
           │     └─ Write {run_name}_demographics.parquet (CVAP, majority flags per draw×district)
           │
           ├─▶ build_draw_stats.py
           │     ├─ DuckDB aggregation on {run_name}_scores.parquet (in-process)
           │     ├─ Write {run_name}_draw_stats.parquet (EG, mean-median, seats per draw×election)
           │     └─ Write {run_name}_competitive_counts.parquet (n_competitive per threshold)
           │
           ├─▶ visualize_benchmark.py
           │     ├─ DuckDB reads all scored Parquets
           │     └─ Write charts/*.png (partisan, competitiveness, demographics, river per election)
           │
           └─▶ build_scorecard.py  ← NEW
                 ├─ DuckDB reads draw_stats, competitive_counts, demographics, scores
                 ├─ Computes Princeton grades + histograms + river chart per election
                 └─ Write {run_name}_scorecard.json  →  copy to fdensemble/input_data/
```

**Key:** All computation uses DuckDB in-process — no database server, no network calls. The entire pipeline runs from a WSL terminal with `uv run --project fdp python fdp/scripts/<script>.py`.

---

## 5. Canonical Scorecard Format

The canonical scorecard (`{run_name}_scorecard.json`) is the shared data model
that allows both GerryChain runs and ALARM/Harvard pre-computed ensembles to be
displayed in the same fdensemble UI.

**Produced by:** `fdp/scripts/build_scorecard.py` (GerryChain Parquets → scorecard)

**Consumed by:** `fdensemble/main.py` (`_build_run_from_scorecard()`)

### Parquet file schemas (on disk)

These are the intermediate files in `fdp/data/repos/main/ensemble/`. They are
**not committed to git** (excluded by `.gitignore`). They live on local disk and
Modal volume only.

| File | Key columns | Rows (congress 9.5k draws) |
|---|---|---|
| `{run}_plans.parquet` | plan_id, draw, geoid, district | 25.6M (2698×9501) |
| `{run}_scores.parquet` | plan_id, draw, district, year, office, dem_2pv, winner | ~798k (14×9501×6) |
| `{run}_draw_stats.parquet` | plan_id, draw, year, office, dem_seats, efficiency_gap, mean_median | ~57k (9501×6) |
| `{run}_competitive_counts.parquet` | plan_id, draw, year, office, threshold, n_competitive | ~57k (9501×6×1 threshold) |
| `{run}_demographics.parquet` | plan_id, draw, district, cvap_blk, pct_black, majority_black, … | ~133k (14×9501) |
| `{run}_scorecard.json` | Pre-computed Princeton grades + histograms + river per election | ~500 KB |

### Scorecard JSON structure

```json
{
  "run": {
    "id": "congress_2026_v2",
    "name": "Congress 2026 V2",
    "source": "gerrychain",
    "chamber": "congress",
    "n_districts": 14,
    "n_draws": 9501,
    "n_plans": 9501,
    "algorithm": "ReCom",
    "date": "2026-06-03",
    "description": "GerryChain ReCom MCMC ensemble — congress, 9,501 draws across 6 elections.",
    "elections": [
      {"year": 2022, "election_type": "general", "office": "governor", "label": "2022 Governor"},
      {"year": 2024, "election_type": "general", "office": "president", "label": "2024 President"}
    ]
  },
  "elections": [
    {
      "year": 2022, "election_type": "general", "office": "governor",
      "label": "2022 Governor",
      "metrics": {
        "dem_seats":      {"label": "Dem. Seats", "grade": "C", "enacted": 5, "pct_rank": 32.4, "histogram": {...}},
        "efficiency_gap": {"label": "Efficiency Gap", "grade": "F", "enacted": 0.089, ...},
        "mean_median":    {"label": "Mean–Median Diff.", "grade": "B", "enacted": -0.023, ...},
        "comp_seats":     {"label": "Competitive Seats", "grade": "D", "enacted": 2, "threshold": 0.05, ...},
        "partisan_bias":  null
      },
      "river": {
        "n_districts": 14, "n_draws": 9500,
        "p5": [...], "p50": [...], "p95": [...], "enacted": [...]
      }
    }
  ],
  "demographics": {
    "source": "cvap", "year": 2024,
    "metrics": {
      "maj_black": {"label": "Majority-Black Dist.", "grade": "B", "enacted": 1, ...},
      "min_coal":  {"label": "Minority Coalition", "grade": "A", "enacted": 5, ...}
    }
  },
  "compactness": {"polsby_popper": null, "county_splits": null, "muni_splits": null},
  "grades": {
    "maj_black":           {...},
    "min_coal":            {...},
    "_partisan_fairness":  {"grade": "C", "ensemble_pass": false, "normative_pass": true, ...},
    "_overall":            {"grade": "C", ...}
  }
}
```

### Metric coverage by source

| Metric | ALARM (CSV) | GerryChain (scorecard) |
|---|---|---|
| Dem seats | ✅ | ✅ |
| Efficiency gap | ✅ | ✅ |
| Mean-median | ✅ (computed) | ✅ |
| Partisan bias | ✅ `pbias` | ❌ null |
| Competitive seats | ✅ (7pp default) | ✅ (5pp default) |
| Polsby-Popper | ✅ | ❌ null |
| County/muni splits | ✅ | ❌ null |
| Majority-Black | ✅ (VAP) | ✅ (CVAP — more accurate) |
| Minority coalition | ✅ (VAP) | ✅ (CVAP) |
| Multiple elections | ❌ (one average) | ✅ (6 elections, selector in UI) |
| River chart enacted | ❌ (loaded from raw CSV at runtime) | ✅ (pre-computed in scorecard) |

`null` metrics are skipped by fdensemble — sections with no available metrics
(e.g., "Geographic" for GerryChain runs) are hidden automatically.

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
    ├─ modal_app.py             ← App definition: secrets, volume, functions
    ├─ scripts/run_ensemble.py  ← Mounted into container as /root/scripts/
    └─ api/                     ← Mounted as /root/api/

Modal Volume: fdga-chain-data
    /graphs/     ← ga_congress.json, ga_senate.json, ga_house.json (~4 MB)
    /ensemble/   ← {run}_plans.parquet files (~8–80 MB each)
    /raw/        ← Enacted district shapefiles (used by build_graph.py)
    /states/     ← GA state config JSON
```

**After any code change to `scripts/run_ensemble.py` or `modal_app.py`:**
```bash
cd ~/codebox/fgdp/fdga-chain
modal deploy modal_app.py
```

**Download plans after a run completes:**
```bash
modal volume get fdga-chain-data /ensemble/{run_name}_plans.parquet .
```

### fdensemble (visualization backend)

Runs on Railway (hobby plan) or locally. Reads two data sources:
1. **ALARM CSV** — `fdensemble/dataverse_files/GA_cd_2020/GA_cd_2020_stats.csv` (committed to repo)
2. **Canonical scorecard JSON** — `fdensemble/input_data/{run_name}_scorecard.json` (generated locally, committed to repo)

To add a new GerryChain run to fdensemble:
```bash
# 1. Build scorecard from scored Parquets
uv run --project fdp python fdp/scripts/build_scorecard.py --run-name congress_2026_v2

# 2. Copy to fdensemble input_data/
cp fdp/data/repos/main/ensemble/congress_2026_v2_scorecard.json fdensemble/input_data/

# 3. Commit and push → Railway redeploys automatically
git add fdensemble/input_data/congress_2026_v2_scorecard.json
git commit -m "Add congress_2026_v2 scorecard to fdensemble"
git push
```

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

### Why score in Python (locally), not in Modal?

The scoring step (matching plan VTD assignments to election vote totals) is
a data-join operation that runs against local Parquet files via DuckDB. Running
it locally means the developer can inspect, debug, and re-run individual steps
without re-running the ensemble. Scoring takes ~30s for congress (9,501 draws × 6 elections),
~90s for senate, and ~3 minutes for house (24,003 draws × 180 districts).

### Why DuckDB instead of PostgreSQL/Supabase?

The scoring pipeline produces large write-once, read-rarely datasets (e.g.,
`congress_2026_v2_scores.parquet` is ~60MB; the equivalent Supabase table was
~900MB due to PostgreSQL row overhead). DuckDB reads columnar Parquet directly
and runs analytical SQL in-process with zero server setup. For the scoring
pattern (one writer, infrequent reads), Parquet + DuckDB is 10–50× more compact
and requires no paid infrastructure. Supabase was eliminated after hitting the
500MB free-tier limit.

### Why pre-compute scorecard grades instead of computing at request time?

For house runs (24,003 draws × 180 districts × 6 elections = 25.9M rows of scored
data), computing histograms and percentile ranks at HTTP request time would take
30+ seconds. Pre-computing all metrics in `build_scorecard.py` reduces the
fdensemble API response to a simple JSON file read (<1ms).
