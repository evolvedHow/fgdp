# fdensemble — Redistricting Ensemble Analysis
#
# Railway: Root Directory = fdensemble
# Build context = repo root (Railway sends full repo for Dockerfile builds)
# All COPY paths are relative to the repo root.
#
# Multi-stage: Node builds the Svelte frontend, Python runs the API.

# ── Stage 1: Build Svelte frontend ───────────────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /build
COPY fdensemble/frontend/package.json fdensemble/frontend/package-lock.json ./
RUN npm ci

COPY fdensemble/frontend/ ./
RUN npm run build
# Output: /build/dist/

# ── Stage 2: Python API server ───────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    "fastapi" \
    "uvicorn[standard]" \
    "pandas" \
    "numpy" \
    "matplotlib" \
    "python-dotenv" \
    "requests" \
    "httpx>=0.27.0" \
    "shapely>=2.0.0" \
    "pyarrow>=14.0.0"

# Copy application source
COPY fdensemble/main.py ./
COPY fdensemble/fdp_client.py ./

# Copy frontend built in stage 1 (never depends on committed dist/)
COPY --from=frontend-builder /build/dist/ ./frontend/dist/

# Copy ALARM dataverse files (GA_cd_2020_stats.csv etc.)
COPY fdensemble/dataverse_files/ ./dataverse_files/

# Copy canonical scorecard JSONs (GerryChain runs — pre-computed, small)
COPY fdensemble/input_data/ ./input_data/

# Copy VTD composite parquet (required for map scoring — 287KB, bundled for Railway)
COPY fdensemble/data/ ./data/

# Copy seeded enacted GeoJSONs so _preload_enacted_districts() can score them at startup
COPY fdensemble/uploaded_maps/ ./uploaded_maps/

ENV PYTHONUNBUFFERED=1
EXPOSE 8010

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8010}"]
