# fdensemble — Redistricting Ensemble Benchmark App

Ensemble benchmark visualization for Fair Districts Georgia. Shows how Georgia's
enacted redistricting maps compare against thousands of algorithmically-neutral
plans drawn with no partisan intent — the standard Princeton Gerrymandering
Project methodology.

Live URL: deployed on Railway (auto-redeploys from `master`)

---

## What It Does

Answers the core question: *Is the enacted map an outlier?*

For each chamber (Congress, Senate, House), the app scores the enacted plan
against a pre-computed ensemble of thousands of neutral plans on:

- **Partisan fairness** — Democratic seats, efficiency gap, mean-median, partisan bias, competitive districts
- **Demographics** — Majority-Black, majority-white, minority-coalition, and minority-influence districts at adjustable thresholds
- **Compactness** — Polsby-Popper, county splits, municipality splits
- **Proportionality gap** — How much of the seat-share gap is geography (baseline) vs. deliberate manipulation

Every metric gets a **Princeton letter grade** (A–F). Princeton grades are independent of which party benefits — they measure statistical anomaly.

---

## Architecture

```
fdensemble/
├── main.py                ← FastAPI server (2,000+ lines): scoring engine, map library, API routes
├── fdp_client.py          ← FDP API client (currently falls back to local dataverse files)
├── input_data/            ← Pre-computed scorecard JSONs (committed to git)
│   ├── fdga_2026_benchmark_congress_scorecard.json
│   ├── fdga_2026_benchmark_congress_alarm_scorecard.json
│   └── senate_450K_2601_scorecard.json
├── data/                  ← VTD-level data files (committed to git)
│   ├── vtd_composite.parquet      ← VTD election composites (2018–2024)
│   ├── vtd_demographics.parquet   ← VTD-level VAP/BVAP/MVAP from Census PL 94-171
│   └── vtd_muni.parquet           ← VTD-to-municipality mapping (for muni splits)
├── dataverse_files/       ← ALARM/Harvard ensemble CSVs (committed; GA_cd_2020, GA_cd_2010)
├── runs/                  ← Legacy ALARM-format run directories (CSV + meta.json)
├── uploaded_maps/         ← Preloaded proposed maps (gitignored; Railway persistent volume)
├── scripts/
│   ├── build_vtd_inputs.py  ← Build vtd_composite.parquet + vtd_demographics.parquet
│   ├── add_map.py           ← CLI tool to add a map to the uploaded_maps/ library
│   └── export_static.py     ← Export scorecard data to static files
├── frontend/              ← Svelte 5 SPA
│   ├── src/
│   │   ├── App.svelte               ← Root: Story tab | Analyze tab
│   │   └── lib/
│   │       ├── components/
│   │       │   ├── EnsembleStoryTab.svelte    ← Narrative overview of ensemble findings
│   │       │   ├── AnalysisTab.svelte         ← Mode switcher: Benchmark | Compare
│   │       │   ├── ScoreTab.svelte            ← Full scorecard with grade panels
│   │       │   ├── BenchmarkTab.svelte        ← Princeton benchmark summary table
│   │       │   ├── CompareTab.svelte          ← District-by-district plan comparison
│   │       │   ├── MetricCard.svelte          ← Histogram + river chart + grade for any metric
│   │       │   ├── DemoMetricCard.svelte      ← 3-column threshold slider for demo metrics
│   │       │   ├── MetricsGlossary.svelte     ← Formula + grading method for every metric
│   │       │   ├── ProportionalityGapPanel.svelte ← Gap decomposition: baseline vs. manipulation
│   │       │   ├── UrbanCrackPanel.svelte     ← City splits vs. partisan outcome scatter
│   │       │   ├── CorrelationHeatmap.svelte  ← Cross-metric correlation heatmap
│   │       │   ├── CrossMetricScatter.svelte  ← Scatter plot for any two metrics
│   │       │   ├── RiverChart.svelte          ← All-districts partisan lean river chart
│   │       │   ├── GradePanel.svelte          ← Letter grade display with color coding
│   │       │   ├── MultiMapScorecard.svelte   ← Side-by-side scoring for multiple maps
│   │       │   ├── MapUploader.svelte         ← Upload a GeoJSON plan for scoring
│   │       │   ├── BenchmarkMethodology.svelte ← Methodology disclosure text
│   │       │   └── ...
│   │       ├── types.ts    ← TypeScript interfaces: RunMeta, Analysis, MetricGrade, ScoredPlan
│   │       ├── api.ts      ← apiGet / apiPost wrappers
│   │       └── db.ts       ← IndexedDB for locally-scored plan persistence
│   └── dist/              ← Pre-built production bundle (committed; served by FastAPI)
├── pyproject.toml
├── railway.toml
└── Dockerfile
```

**Stack:** Python 3.12, FastAPI, NumPy, Pandas, GeoPandas, Shapely, DuckDB (via fdp), Svelte 5, Vite, TypeScript, Tailwind 4, Chart.js

---

## Dev Quick-Start

```bash
cd ~/codebox/fgdp/fdensemble
uv sync

# Run the server (serves frontend/dist/ as static files at /)
uv run uvicorn main:app --reload --port 8010
# → http://localhost:8010

# Frontend hot-reload (proxies /api/* to :8010 via vite.config.ts)
cd frontend && npm install && npm run dev
# → http://localhost:5174
```

When iterating on frontend code, run both — the dev server at :5174 gives
hot-reload while the API runs on :8010.

---

## API Reference

### Analysis & Runs

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Health check + FDP connection status |
| `GET` | `/api/runs` | List all available benchmark runs |
| `GET` | `/api/analysis` | Full scorecard for a run (grades, histograms, river data) |
| `GET` | `/api/analysis/correlations` | Cross-metric correlation data |
| `GET` | `/api/river` | River chart data for a run |
| `GET` | `/api/charts/histograms` | PNG histogram charts |
| `GET` | `/api/charts/river` | PNG river chart |

Query parameters for `/api/analysis`:

| Param | Type | Default | Description |
|---|---|---|---|
| `run` | string | first run | Benchmark run ID |
| `election` | int | `0` | Election index within the run's elections array |
| `plan` | string | `"enacted"` | Plan to score: `"enacted"` or a named plan |

### Map Library

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/maps` | Preload a validated GeoJSON plan into the library |
| `GET` | `/api/maps` | List all preloaded plans |
| `POST` | `/api/score-map` | Score a preloaded plan against any benchmark run |
| `DELETE` | `/api/maps/{map_id}` | Remove a plan from the library |
| `POST` | `/api/score-plan` | Score a GeoJSON plan inline (without saving to library) |

Map preloading is admin-only (no upload from public browser). Use the CLI or
the `POST /api/maps` endpoint directly with a valid GeoJSON feature collection
where each feature has a `district` property.

---

## Scorecard JSON Format

The pre-computed scorecard JSONs in `input_data/` are produced by
`fdp/scripts/build_scorecard.py`. They are the canonical data source for the
benchmark visualizations.

```
scorecard.json
├── run                    ← Run metadata
│   ├── id                 ← e.g. "fdga_2026_benchmark_congress"
│   ├── name               ← Display name
│   ├── chamber            ← "congress" | "senate" | "house"
│   ├── n_districts        ← 14 (congress), 56 (senate), 180 (house)
│   ├── n_draws            ← Number of neutral plans (e.g. 99001)
│   ├── n_plans            ← Same as n_draws (simulation draws)
│   ├── algorithm          ← "ReCom" | "SMC"
│   ├── date               ← ISO date of the run
│   └── config             ← Threshold and grading parameters (see below)
├── elections[]            ← One entry per election composite
│   ├── year               ← e.g. "2018–2024"
│   ├── election_type      ← "composite" | "general"
│   ├── label              ← Display label
│   └── metrics            ← {dem_seats, efficiency_gap, mean_median, comp_seats_7pt, ...}
│       └── <metric_key>
│           ├── grade           ← "A" | "B" | "C" | "F"
│           ├── enacted         ← Enacted plan value
│           ├── pct_rank        ← Percentile rank in ensemble (0–100)
│           ├── histogram       ← {counts[], bin_edges[], mean, std, ...}
│           ├── draw_values[]   ← Raw distribution array (for quality-filter slider)
│           └── takeaway        ← Pre-baked summary sentence
├── demographics           ← Demographic metrics
│   └── metrics
│       └── <metric_key>   ← maj_black, maj_white, min_coal, min_influence
│           ├── grade, enacted, pct_rank, grade_fn, higher_is_better
│           ├── histogram, draw_values_by_threshold   ← Keyed "0.20"…"0.50"
│           └── enacted_by_threshold                  ← Enacted count at each threshold
├── compactness            ← Compactness metrics
│   └── metrics            ← polsby_popper, county_splits, muni_splits
├── grades                 ← Flat index of all MetricGrade objects (for fast lookup)
├── plans                  ← Named plans (currently just "enacted")
├── correlations           ← Cross-metric Pearson r matrix
└── config                 ← Threshold and grading parameters
    ├── competitive_thresholds    ← [0.035, 0.05]  (7pt and 10pt margins)
    ├── majority_threshold        ← 0.20 (default for demo threshold slider start)
    ├── bvap_majority_threshold   ← 0.20
    ├── influence_min_threshold   ← 0.37
    └── influence_max_threshold   ← 0.50
```

### `grade_fn` values

| Value | Metric type | Grade logic |
|---|---|---|
| `"directional"` | Higher or lower is unambiguously better | `higher_is_better=true/false` → pct rank direction |
| `"simple"` | Symmetric: too far in *either* direction is anomalous | Distance from 50th percentile → A≤10, B≤30, C≤45, F |
| `"seats"` | Democratic seat count | A≥50th, B≥20th, C≥5th, F else |
| `"comp"` | Competitive seats | A≥95th, B≥64th, C≥5th, F else |

---

## How to Rebuild a Scorecard

Scorecards are pre-computed by `fdp/scripts/build_scorecard.py`. They are
committed to `input_data/` and served statically — the server does not
recompute them at runtime.

```bash
# Rebuild the GerryChain congress scorecard
cd ~/codebox/fgdp
uv run --directory fdp python fdp/scripts/build_scorecard.py \
    --config fdp/configs/benchmarks/ga_congress_2026_v1.yml \
    --plans fdga-chain/runs/congress_2026_v1/plans.parquet \
    --vtd-composite fdensemble/data/vtd_composite.parquet \
    --vtd-demographics fdensemble/data/vtd_demographics.parquet \
    --vtd-muni fdensemble/data/vtd_muni.parquet \
    --output fdensemble/input_data/fdga_2026_benchmark_congress_scorecard.json

# Rebuild VTD inputs first (if demographics or election data changed)
cd ~/codebox/fgdp/fdensemble
uv run python scripts/build_vtd_inputs.py
```

After rebuilding, commit `input_data/*_scorecard.json` and `data/*.parquet`
and push to `master` — Railway redeploys automatically.

---

## Key Metrics

### Partisan Fairness

| Metric key | What it measures | Grade method |
|---|---|---|
| `dem_seats` | Dem seat count vs. ensemble | `seats`: higher is better, symmetric |
| `efficiency_gap` | Partisan waste disparity | `simple`: symmetric around 0 |
| `mean_median` | Mean minus median Dem vote share | `simple`: symmetric around 0 |
| `comp_seats_7pt` | Competitive districts (±7% margin) | `comp`: higher is better |
| `comp_seats_10pt` | Competitive districts (±10% margin) | `comp`: higher is better |
| `partisan_bias` | Seat advantage at 50/50 vote split | `simple`: symmetric around 0 |

### Demographics

All demographic metrics use a **threshold slider** (20%–50%) in the UI.
The scorecard stores distributions at every 5% interval so the frontend can
update grades and histograms interactively without an API call.

| Metric key | What it counts | Grade method |
|---|---|---|
| `maj_black` | Districts with Black VAP ≥ threshold | `simple`: symmetric |
| `maj_white` | Districts with white VAP ≥ threshold | `simple`: symmetric |
| `min_coal` | Districts with non-white VAP ≥ threshold | `simple`: symmetric |
| `min_influence` | Districts with minority VAP in [37%, 50%) | `directional`: higher is better |

Data source: 2020 Census PL 94-171 Table P4 (VTD-level VAP headcounts).

### Compactness

| Metric key | What it measures | Grade method |
|---|---|---|
| `polsby_popper` | Mean of 4π×area/perimeter² across districts | `directional`: higher is better |
| `county_splits` | Counties split across district lines | `directional`: lower is better |
| `muni_splits` | Municipalities split across district lines | `directional`: lower is better |

### Urban Cracking

`muni_splits` (municipality splits) is the key urban cracking indicator.
The Urban Cracking panel tests whether splitting cities correlates with partisan
outcome in the ensemble — if the correlation is near zero, cracking is
sub-municipal (boundaries drawn within cities, not just around them).

---

## Proportionality Gap

The proportionality gap measures the difference between a party's seat share and
their vote share. The app decomposes this into:

- **Geographic baseline**: the gap attributable to natural geographic sorting
  (Democrats clustering in cities), measured as the ensemble median
- **Manipulation premium**: the additional gap in the enacted map beyond the
  geographic baseline (enacted gap minus ensemble median)

This decomposition is the key advocacy message: even accounting for Georgia's
natural geography, the enacted Congressional map delivers an additional partisan
advantage beyond what neutral plans produce.

---

## Benchmark Runs (Current)

| Run ID | Chamber | Algorithm | Plans | Status |
|---|---|---|---|---|
| `fdga_2026_benchmark_congress` | Congress (14) | GerryChain ReCom | 99,001 | Active |
| `fdga_2026_benchmark_congress_alarm` | Congress (14) | ALARM SMC | 5,000 | Active |
| `senate_450K_2601` | Senate (56) | GerryChain ReCom | 450,000 | Active |

---

## Deployment

Railway auto-redeploys on every push to `master`. The frontend must be
pre-built before pushing because Railway runs the Dockerfile which does not
install Node:

```bash
# Build frontend before deploying
cd frontend && npm run build
cd ..
git add frontend/dist
git commit -m "chore: rebuild frontend for deploy"
git push
```

Railway config (`railway.toml`):
- Builder: Dockerfile
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Health check: `GET /api/health`
- Persistent volume: mount at `/app/uploaded_maps` for preloaded maps to
  survive redeploys (create in Railway dashboard under Service → Volumes)

### Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | Railway-assigned | Server port |
| `FDPAPI_BASE` | unset | FDP API URL — if set, switches from local dataverse files to API mode |
| `DATA_DIR` | `dataverse_files/GA_cd_2020` | ALARM dataverse CSV directory |
| `MAPS_DIR` | `uploaded_maps` | Preloaded map directory (override if volume path differs) |
| `BVAP_MAJORITY_THRESHOLD` | `0.50` | Default threshold for maj_black scoring (must match `DEMO_DEFAULT_THRESHOLD` in build_scorecard.py) |
| `MAJORITY_THRESHOLD` | `0.50` | Default threshold for min_coal / maj_white scoring |
| `INFLUENCE_MIN_THRESHOLD` | `0.37` | Lower bound for minority-influence districts |
| `INFLUENCE_MAX_THRESHOLD` | `0.50` | Upper bound for minority-influence districts |
| `COMPETITIVE_MARGIN_MAIN` | `0.10` | ±margin defining a competitive district (10pt threshold) |

---

## Related Docs

| Document | Contents |
|---|---|
| [`../METRICS.md`](../METRICS.md) | All 17 metrics: formula, data source, grading method |
| [`../TECHNICAL_GUIDE.md`](../TECHNICAL_GUIDE.md) | CDM schemas, full formula derivations, app-by-app metric mapping |
| [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) | System design, data flow, scorecard format detail, key design decisions |
| [`../fdp/README.md`](../fdp/README.md) | FDP data platform: loaders, CLI, workspace isolation |
| [`../fdga-chain/README.md`](../fdga-chain/README.md) | GerryChain/Modal ensemble generation pipeline |
