# Fair Districts Georgia — Project Overview

> **For AI agents:** This is the top-level context file for the entire
> fairdistrictsga.org codebase. Read this first, then the README in whichever
> sub-project you need to work in.

## Documentation

| Guide | Audience | Contents |
|---|---|---|
| [`docs/ADMIN_GUIDE.md`](docs/ADMIN_GUIDE.md) | **Admins** | Running ensemble jobs, scoring pipeline, updating elections, DB migrations, secrets |
| [`docs/ANALYST_GUIDE.md`](docs/ANALYST_GUIDE.md) | **Analysts** | What data was used, every metric formula, how to interpret results, key findings |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | **Engineers** | System design, technology stack, data flow, DB schema, key decisions |
| [`TECHNICAL_GUIDE.md`](TECHNICAL_GUIDE.md) | **Engineers** | Full CDM schemas, all metric formulas, app-by-app metric mapping |

## Mission

Fair Districts Georgia produces tools that help citizens, local officials, and
advocates understand and participate in the redistricting process. All tools
are non-partisan and evidence-based.

---

## Project Map

All components live under a single monorepo root. Each app is its own
GitHub repository; `fgdp` holds git submodule pointers to all of them.

```
~/codebox/fgdp/                   ← monorepo root (github: evolvedHow/fgdp)
├── fdp/           ← Shared data platform (Python package + canonical data)
├── fdex/          ← Georgia Explorer — public-facing district map
├── fdga-chain/    ← Ensemble analysis API (GerryChain / statistics)
├── fdworkbench/   ← NLQ-to-SQL analytics workbench
├── lrdb/          ← Local Redistricting Database (county/city/school boards)
├── map-compare/   ← Plan comparison and metrics tool
├── scripts/
│   └── push_cdm.sh   ← Sync updated CDM data into all apps
├── TECHNICAL_GUIDE.md ← CDM schemas, all metric formulas, app-by-app mapping
└── README.md
```

All five apps depend on **fdp** for data. `fdworkbench` lives directly
inside `fgdp` (no separate GitHub repo). All others are git submodules.

---

## GitHub Repositories & Live URLs

| Component | GitHub repo | Live URL |
|---|---|---|
| fgdp (wrapper) | evolvedHow/fgdp | — |
| fdex | evolvedHow/fdex | https://evolvedhow.github.io/fdex/ |
| fdga-chain | evolvedHow/fdga-chain | https://evolvedhow.github.io/fdga-chain/ |
| lrdb | evolvedHow/lrdb | https://evolvedhow.github.io/lrdb/ |
| map-compare | evolvedHow/map-compare | https://evolvedhow.github.io/map-compare/ |

---

## Component Summary

### `fdp` — Fair Districts Data Platform

**Role:** Shared data management layer. Owns the canonical copies of all
GeoJSON boundaries, demographic files, election parquets, precinct shapefiles,
GerryChain ensemble outputs, LRDB data, and redistricting history.

- Python package (`from fdp import DataPlatform`)
- Hierarchical YAML config (`global.yml` → `defaults.yml` → `apps/<app>.yml`)
- Workspace isolation for testing new data without affecting other apps
- CLI: `fdp workspace create/list/delete`, `fdp catalog`, `fdp validate`, `fdp sync-app`
- **Stack:** Python 3.12, GeoPandas, PyArrow, PyYAML, Click, Rich
- **Data root:** `fdp/data/repos/main/`
- **Docs:** [fdp/README.md](fdp/README.md)

---

### `fdex` — Georgia Explorer

**Role:** Consumer-facing interactive map for exploring Georgia's redistricting
plans — enacted maps, historical maps, remedy plans, and demographic overlays.

- Static single-page app deployed to GitHub Pages
- Reads GeoJSON directly from `data/` (no backend at runtime)
- YAML config baked into `public/config.json` at build time
- **Displays:** Partisan Lean Index choropleth (4-election blend), Black/Hispanic/Asian VAP overlays, district tooltips
- **Audience:** General public, advocates, journalists
- **Stack:** Svelte 5, Vite, TypeScript, Tailwind 4, Mapbox GL JS 3.9
- **Dev:** `cd fdex/frontend && npm install && npm run dev` → http://localhost:5173
- **Deploy:** Push to `main` → GitHub Actions builds and deploys to Pages
- **Docs:** [fdex/README.md](fdex/README.md)

---

### `fdga-chain` — Ensemble Analysis API

**Role:** Generates and serves GerryChain ensemble statistics — thousands of
algorithmically-drawn "neutral" maps used as a mathematical baseline to detect
gerrymandering.

- FastAPI backend with in-memory caching
- GerryChain ReCom / Reversible ReCom algorithm for ensemble generation
  (run offline once; serve the parquet results)
- Supports all three chambers: Congress (14), Senate (56), House (180)
- State-agnostic API design (`/api/states/{state}/{chamber}/...`)

**Key metrics computed:**

| Metric | What it measures |
|---|---|
| `dem_seats` | Democratic seat count |
| `competitive_districts` | Districts with Dem vote share 46.5%–53.5% (≤7% margin) |
| `efficiency_gap` | Partisan waste disparity (positive = R advantage) |
| `mean_median` | Mean minus median Dem vote share across districts |
| `polsby_popper_mean` / `_min` | Average and worst-case compactness |
| `majority_minority_districts` | Districts with minority VAP > 50% |
| `num_cut_edges` | Precinct boundaries crossing district lines |

**Key API endpoints:**

| Endpoint | Returns |
|---|---|
| `GET /api/states/{state}/{chamber}/ensemble/enacted` | Enacted plan vs. ensemble + **Princeton A-grade benchmark** (letter grade A–F) |
| `GET /api/states/{state}/{chamber}/ensemble/histogram` | Histogram data for any metric |
| `GET /api/states/{state}/{chamber}/ensemble/summary` | Full distribution stats for all metrics |
| `GET /api/states/{state}/{chamber}/proportionality` | Seat share vs. vote share across all redistricting cycles |
| `GET /api/states/{state}/{chamber}/metrics/{year}` | Precomputed metrics for a single election cycle (includes `contested_districts`, `safe_districts`, `safe_pct`) |
| `POST /api/states/{state}/{chamber}/ensemble/run` | Trigger a new GerryChain run in the background |
| `GET /api/maps/{state}/{chamber}/stability` | Precinct stability heatmap |

**Princeton A-grade benchmarks** (from Princeton Gerrymandering Project, 1M simulations):

| Chamber | D Seats (A) | R Seats (A) | Competitive (A) |
|---|---|---|---|
| GA Senate (56) | 25–27 | 29–31 | 2–6 |
| GA House (180) | 83–86 | 94–97 | 11–20 |
| Congress (14) | 6 | 8 | 0–2 |

- **Audience:** Researchers, data-savvy advocates; powers ensemble API used by other apps
- **Stack:** Python 3.12, FastAPI, GerryChain 0.3, GeoPandas, PyArrow, Modal
- **Dev:** `cd fdga-chain && uv sync && uv run uvicorn api.main:app --reload --port 8001`
- **Deploy:** `modal deploy modal_app.py` (serverless) or GitHub Pages (static frontend)
- **Docs:** [fdga-chain/README.md](fdga-chain/README.md)

---

### `fdworkbench` — Analytics Workbench

**Role:** Natural language query (NLQ) to SQL interface over the FDP data.
Lets analysts ask questions in plain English ("Which house districts have the
highest efficiency gap?") and get SQL-generated answers against the CDM data.

- FastAPI backend + DuckDB for in-process SQL over parquet files
- LiteLLM routing to multiple LLM providers (Groq, Ollama, etc.)
- Queryable data: elections parquet, ensemble parquets, boundary GeoJSON,
  demographics JSON
- **Audience:** Analysts who want ad-hoc queries without writing code
- **Stack:** Python 3.12, FastAPI, DuckDB, LiteLLM
- **Dev:** `cd fdworkbench && uv sync && ./start.sh` → http://localhost:8003
- **Note:** Lives directly in the fgdp repo (not a git submodule)
- **Docs:** [fdworkbench/README.md](fdworkbench/README.md)

---

### `lrdb` — Local Redistricting Database

**Role:** Interactive map showing every county commission, city council, and
school board in Georgia along with their redistricting process metadata —
whether they had written requirements, public participation, controversy, etc.

- Entirely static: a Leaflet map serving pre-built GeoJSON
- No backend; data sourced from FDGA manual research
- Covers 441 local jurisdictions across all 159 Georgia counties
- **Audience:** Advocates, researchers tracking local redistricting processes
- **Stack:** Svelte 3, Rollup, Leaflet 1.7
- **Dev:** `cd lrdb && npm install && npm run dev` → http://localhost:5000
- **Deploy:** Push to `main` → GitHub Actions builds and deploys to Pages
- **Docs:** [lrdb/README.md](lrdb/README.md)

---

### `map-compare` — Redistricting Plan Comparison

**Role:** Side-by-side comparison of any two redistricting plans with a full
suite of computed fairness, compactness, demographic, and displacement metrics.
Users can load preset plans or upload their own GeoJSON/shapefiles.

**Metrics computed entirely in the browser:**

| Category | Metrics |
|---|---|
| Population | Max deviation %, per-district deviation |
| Compactness | Polsby-Popper (avg), Convex Hull Ratio (avg), County Splits |
| Representation | Majority-Minority districts, Black VAP Majority districts, **Safe Seat %**, **Competitive Districts** |
| VRA Thresholds | BVAP/MVAP/HVAP/AVAP majority and influence district counts |
| Partisan Safety | Six-tier classification (Safe R → Safe D) with counts per tier |
| Partisan Fairness | Dem Seats, Efficiency Gap, Mean-Median Difference, Partisan Bias |
| Seats-Votes | Responsiveness curve (±25% uniform swing), current position dot |
| Displacement | Total displaced population, minimum required, excess displacement |

**Safe Seat %:** Districts won by >7% margin. FDGA reported 97% of 2024 GA
legislative seats were safe.

**FDGA A-grade reference:** Competitive Districts ScoreCard shows the Princeton
A-grade range as a reference tooltip (Senate: 2–6, House: 11–20, Congress: 0–2).

- Browser-only — all computation is client-side (Turf.js geometry, TypeScript formulas)
- Plans stored in IndexedDB for persistence across sessions
- AI narrative calls go directly from the browser to LLM providers (Groq, Anthropic, OpenAI, Gemini)
- Redistricting History tab shows Georgia's four mid-decade redistricting waves
- **Audience:** Researchers, advocates comparing specific maps
- **Stack:** Svelte 5, Vite, TypeScript, Tailwind 4, Leaflet 1.9, Turf.js 7, shpjs 6, IndexedDB
- **Dev:** `cd map-compare && npm install && npm run dev` → http://localhost:5174
- **Deploy:** Push to `master` → GitHub Actions builds and deploys to Pages
- **Docs:** [map-compare/README.md](map-compare/README.md)

---

## Data Flow

```
Census PL 94-171 (2020) ───┐
ACS 5-year 2022 ────────────┤
GA General Assembly GeoJSON ┼──→  fdp/data/repos/main/   ← canonical CDM
OpenElections GA CSV ───────┤         │
MGGG precinct shapefiles ───┘         │
                                       │  scripts/push_cdm.sh
                     ┌─────────────────┼──────────────────────┐
                     ▼                 ▼           ▼           ▼
              fdga-chain/data/   fdex/data/   lrdb/public/  map-compare/
              (Python import +   (sync_data   assets/       public/data/
               sync_data.sh)      .sh)        (sync_data    (sync_data
                                               .sh)          .sh)
                                                        ▼
                                               fdworkbench/data/
                                               (sync_data.sh)
```

**Syncing CDM data to apps:**

```bash
# Sync all apps at once
./scripts/push_cdm.sh

# Sync one app
./scripts/push_cdm.sh fdex

# Preview without copying
./scripts/push_cdm.sh --dry-run
```

Each app's `scripts/sync_data.sh` calls `uv run --directory "$FDP_ROOT" python -m fdp.cli sync-app <appname>`.
All sync scripts skip silently in CI environments (`$CI` env var set).

---

## Quick-Start per App

```bash
# ── 1. Set up the data platform (do this once) ──────────────────────────────
cd ~/codebox/fgdp/fdp
uv sync && uv pip install -e .

# ── 2. fdex — Georgia Explorer ───────────────────────────────────────────────
cd ~/codebox/fgdp/fdex/frontend
npm install && npm run dev            # → http://localhost:5173

# ── 3. fdga-chain — Ensemble Analysis API ────────────────────────────────────
cd ~/codebox/fgdp/fdga-chain
uv sync
uv run uvicorn api.main:app --reload --port 8001

# ── 4. lrdb — Local Redistricting Database ───────────────────────────────────
cd ~/codebox/fgdp/lrdb
npm install && npm run dev            # → http://localhost:5000

# ── 5. map-compare — Plan Comparison ─────────────────────────────────────────
cd ~/codebox/fgdp/map-compare
npm install && npm run dev            # → http://localhost:5174

# ── 6. fdworkbench — Analytics Workbench ─────────────────────────────────────
cd ~/codebox/fgdp/fdworkbench
uv sync && ./start.sh                 # → http://localhost:8003
```

---

## Shared Configuration

Apps share a three-layer YAML config in `fdp/config/`:

| File | Scope | Overridable? |
|---|---|---|
| `global.yml` | Platform-wide: state=GA, census_year=2020, repo registry, data layout, data schema, quality checks | Never |
| `defaults.yml` | Sensible defaults: map center/zoom, LLM settings, chain parameters, export formats | Yes, by apps |
| `apps/{app}.yml` | Per-app overrides + data catalogues (plan lists, overlays, data paths) | Overrides defaults only |

**Locked keys** (from `global.yml`): `platform`, `repos`, `data_layout`, `data_schema`, `quality` — these always win regardless of app config.

---

## Workspace Isolation

Test new data files without affecting other apps or developers:

```bash
fdp workspace create my_test_shapes --base main
cp ~/new_congress.geojson  fdp/data/workspaces/my_test_shapes/boundaries/congress/
export FDP_WORKSPACE=my_test_shapes   # activates only in this shell

# Run fdex against the workspace data
cd fdex/frontend && FDP_WORKSPACE=my_test_shapes npm run sync && npm run dev
```

---

## Key Environment Variables

| Variable | Used by | Purpose |
|---|---|---|
| `FDP_ROOT` | All | Path to `fdp/` directory (auto-detected from `../fdp` by sync scripts) |
| `FDP_WORKSPACE` | All | Activate a named workspace overlay |
| `CENSUS_API_KEY` | fdp scripts | Fetch ACS + PL 94-171 data from Census Bureau |
| `MAPBOX_TOKEN` | fdex | Mapbox GL JS map tiles and tilesets |
| `GROQ_API_KEY` | fdga-chain, map-compare, fdworkbench | LLM narrative and NLQ generation |
| `ANTHROPIC_API_KEY` | map-compare | Claude narrative generation |
| `OPENAI_API_KEY` | map-compare | GPT-4o narrative generation |
| `OLLAMA_HOST` | fdworkbench | Local Ollama instance for NLQ |
| `ACTIVE_STATE` | fdga-chain | State context for API (default: `GA`) |

---

## Data Sources

| Dataset | Source | Frequency |
|---|---|---|
| District boundary GeoJSON | Georgia General Assembly redistricting portal | Per redistricting cycle |
| Census VAP by race (PL 94-171) | 2020 US Census (Census API) | Decennial |
| ACS socioeconomic data | ACS 5-year 2022 (Census API) | Annual update |
| Election results (district-level) | OpenElections Georgia (openelections-data-ga) | Per election |
| Precinct shapefiles | RDH / MGGG-States GitHub | Per cycle |
| Ensemble parquets | GerryChain ReCom runs (10,000 steps per chamber) | On demand |
| Local redistricting metadata | Manual research by FDGA staff | Per cycle |
| Princeton benchmarks | Princeton Gerrymandering Project (1M simulations) | Static reference |

---

## Deployment

| App | Platform | Branch | Trigger |
|---|---|---|---|
| fdex | GitHub Pages | `main` | Push → GitHub Actions |
| fdga-chain | GitHub Pages (frontend) + Modal (API) | `master` | Push → GitHub Actions; `modal deploy` for API |
| lrdb | GitHub Pages | `main` | Push → GitHub Actions |
| map-compare | GitHub Pages | `master` | Push → GitHub Actions |
| fdworkbench | Local / self-hosted | — | `./start.sh` |
| fdp | Local / CI only | — | Not deployed; used as Python package |

**Submodule commits:** After committing changes inside any app repo and pushing,
update the fgdp submodule pointer:

```bash
git -C ~/codebox/fgdp add fdex   # (or fdga-chain, lrdb, map-compare)
git -C ~/codebox/fgdp commit -m "Update submodule pointer: <description>"
git -C ~/codebox/fgdp push
```

---

## Reference

- **Full metric formulas + CDM schemas:** [TECHNICAL_GUIDE.md](TECHNICAL_GUIDE.md)
- **VS Code workspace:** `~/codebox/code-workspace.code-workspace`
- **FDGA website:** https://fairdistrictsga.org
