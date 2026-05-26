# Fair Districts Georgia — Project Overview

> **For AI agents:** This is the top-level context file for the entire
> fairdistrictsga.org codebase. Read this first, then the README in whichever
> sub-project you need to work in.

## Mission

Fair Districts Georgia produces tools that help citizens, local officials, and
advocates understand and participate in the redistricting process.  All tools
are non-partisan and evidence-based.

---

## Project Map

```
~/codebox/
├── fdp/           ← Shared data platform (Python package + canonical data)
├── fdex/          ← Georgia Explorer — public-facing district map
├── fdga-chain/    ← Ensemble analysis API (GerryChain / statistics)
├── lrdb/          ← Local Redistricting Database (county/city/school boards)
└── map-compare/   ← Plan comparison and metrics tool
```

Each app is independently deployable.  All four depend on **fdp** for data.

---

## Component Summary

### `fdp` — Fair Districts Data Platform
**Role:** Shared data management layer.  Owns the canonical copies of all
GeoJSON boundaries, demographic files, election parquets, precinct shapefiles,
and GerryChain ensemble outputs.

- Python package (`from fdp import DataPlatform`)
- Hierarchical YAML config (`global.yml` → `defaults.yml` → `apps/<app>.yml`)
- Workspace isolation for testing new data without affecting other apps
- CLI: `fdp workspace create/list/delete`, `fdp catalog`, `fdp validate`, `fdp sync-app`
- **Stack:** Python 3.12, GeoPandas, PyArrow, PyYAML, Click, Rich
- **Docs:** [fdp/README.md](fdp/README.md)

---

### `fdex` — Georgia Explorer
**Role:** Consumer-facing interactive map for exploring Georgia's redistricting
plans — enacted maps, historical maps, remedy plans, and demographic overlays.

- Static single-page app deployed to GitHub Pages
- Reads GeoJSON directly from `/data/` (no backend at runtime)
- YAML config baked into `public/config.json` at build time
- **Audience:** General public, advocates, journalists
- **Stack:** Svelte 5, Vite, TypeScript, Tailwind 4, Mapbox GL JS 3.9
- **Dev port:** 5173
- **Docs:** [fdex/README.md](fdex/README.md)

---

### `fdga-chain` — Ensemble Analysis API
**Role:** Generates and serves GerryChain ensemble statistics — thousands of
algorithmically-drawn "neutral" maps used as a mathematical baseline to detect
gerrymandering.

- FastAPI backend with in-memory caching
- GerryChain ReCom algorithm for ensemble generation (offline, computationally
  intensive — run once, serve forever)
- Deployed to Modal (serverless) for production; run locally for development
- Also imports `fdp` directly for path resolution
- **Audience:** Researchers, data-savvy advocates; powers ensemble API used by
  other apps
- **Stack:** Python 3.12, FastAPI, GerryChain, GeoPandas, PyArrow, Modal
- **Dev port:** 8001
- **Docs:** [fdga-chain/README.md](fdga-chain/README.md)

---

### `lrdb` — Local Redistricting Database
**Audience:** Advocates, researchers tracking local redistricting processes
**Role:** Interactive map showing every county commission, city council, and
school board in Georgia along with their redistricting process metadata —
whether they had written requirements, public participation, controversy, etc.

- Entirely static: a Leaflet map serving pre-built GeoJSON
- No backend; data updated by running R scripts against source shapefiles
- **Stack:** Svelte 3, Rollup, Leaflet 1.7, R (data processing)
- **Dev port:** 5000 (sirv)
- **Docs:** [lrdb/README.md](lrdb/README.md)

---

### `map-compare` — Redistricting Plan Comparison
**Role:** Side-by-side comparison of any two redistricting plans with computed
fairness metrics (efficiency gap, mean-median, compactness) and optional
AI-generated narratives.  Users can load preset plans or upload their own
shapefiles.

- Browser-only app — all computation happens client-side
- Plans stored in IndexedDB for persistence across sessions
- AI narrative calls go directly from the browser to LLM providers (Groq,
  Anthropic, OpenAI, Gemini)
- **Audience:** Researchers, advocates comparing specific maps
- **Stack:** Svelte 5, Vite, TypeScript, Tailwind 4, Leaflet 1.9, Turf.js 7,
  shpjs 6, IndexedDB
- **Dev port:** 5174
- **Docs:** [map-compare/README.md](map-compare/README.md)

---

## Data Flow

```
Census API ──────────────┐
Georgia SOS (elections) ─┤
MGGG precinct shapefiles ┼──→  fdp/data/repos/main/   ←── canonical data store
GA General Assembly GeoJSON ┘         │
                                       │
                     ┌─────────────────┼─────────────────┐
                     ▼                 ▼                 ▼
              fdga-chain           fdex/data/       lrdb/public/assets/
           (Python import)     (synced via         (synced via
                     │          sync_data.sh)       sync_data.sh)
                     │                 │
                     └────────────┬───┘
                                  ▼
                           map-compare/public/data/
                           (synced via sync_data.sh)
```

---

## Quick-Start per App

```bash
# 1. Set up the data platform first
cd ~/codebox/fdp
uv sync && uv pip install -e .
cp .env.example .env        # add CENSUS_API_KEY if fetching fresh data

# 2. Migrate existing app data into fdp (dry run first, then execute)
uv run python scripts/migrate_data.py
uv run python scripts/migrate_data.py --execute --validate

# 3. fdex (Georgia Explorer)
cd ~/codebox/fgdp/fdex/frontend
npm install
npm run dev                 # → http://localhost:5173

# 4. fdga-chain (Ensemble API)
cd ~/codebox/fdga-chain
uv sync
uv run uvicorn api.main:app --reload --port 8001

# 5. lrdb (Local Redistricting DB)
cd ~/codebox/lrdb
npm install
npm run dev                 # → http://localhost:5000

# 6. map-compare (Plan Comparison)
cd ~/codebox/map-compare
npm install
npm run dev                 # → http://localhost:5174
```

---

## Shared Configuration

Apps share a three-layer YAML config in `fdp/config/`:

| File | Scope | Overridable? |
|---|---|---|
| `global.yml` | Platform-wide: state=GA, census_year, repo registry, data schema, quality checks | Never |
| `defaults.yml` | Sensible defaults: map center/zoom, LLM settings, chain parameters | Yes, by apps |
| `apps/{app}.yml` | Per-app overrides + data catalogues (plan lists, overlays, etc.) | Overrides defaults only |

Lock enforced at runtime: `platform`, `repos`, `data_layout`, `data_schema`, `quality` keys
from `global.yml` always win regardless of app config.

---

## Workspace Isolation

Test new data files without affecting other apps or developers:

```bash
fdp workspace create my_test_shapes --base main
cp ~/new_congress.geojson  fdp/data/workspaces/my_test_shapes/boundaries/congress/
export FDP_WORKSPACE=my_test_shapes   # activates only in this shell

# Run fdex dev server against the workspace data
cd fdex/frontend && FDP_WORKSPACE=my_test_shapes npm run sync && npm run dev
```

---

## Key Environment Variables

| Variable | Used by | Purpose |
|---|---|---|
| `FDP_ROOT` | All | Path to fdp/ directory |
| `FDP_WORKSPACE` | All | Activate a named workspace |
| `CENSUS_API_KEY` | fdp scripts | Fetch ACS + PL 94-171 data |
| `MAPBOX_TOKEN` | fdex | Mapbox GL JS map tiles |
| `GROQ_API_KEY` | fdga-chain, map-compare | LLM narrative generation |
| `ANTHROPIC_API_KEY` | map-compare | Claude narrative generation |
| `OPENAI_API_KEY` | map-compare | GPT-4 narrative generation |
| `OLLAMA_HOST` | fdga-chain | Local Ollama instance |

---

## Data Sources

| Dataset | Source | Updated |
|---|---|---|
| District boundaries (GeoJSON) | Georgia General Assembly redistricting portal | Per cycle |
| Census VAP by race | 2020 Census PL 94-171 (Census API) | Decennial |
| ACS socioeconomic | ACS 5-year 2022 (Census API) | Annually |
| Election results | Georgia Secretary of State (via VEST/RDH) | Per election |
| Precinct shapefiles | MGGG-States GitHub | Per cycle |
| Local redistricting metadata | Manual research by FDGA staff (R scripts) | Per cycle |
| Ensemble outputs | GerryChain ReCom runs (local, uploaded to Modal) | On demand |

---

## Deployment

| App | Platform | Trigger |
|---|---|---|
| fdex | GitHub Pages | Push to main → GitHub Actions |
| fdga-chain | Modal (serverless) | `modal deploy modal_app.py` |
| lrdb | GitHub Pages (or static host) | Manual build + push |
| map-compare | GitHub Pages | Push to main → GitHub Actions |
| fdp | Local / CI only | Not deployed; used as a package |
