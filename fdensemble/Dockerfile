# fdensemble — Redistricting Ensemble Analysis
#
# Railway: Root Directory = fdensemble
# Build context = repo root (Railway sends full repo for Dockerfile builds)
# All COPY paths are relative to the repo root.
#
# Multi-stage: Node builds the Svelte frontend, Python runs the API.

# ── Stage 1: build Svelte frontend ───────────────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /build
COPY fdensemble/frontend/package*.json ./
RUN npm ci
COPY fdensemble/frontend/ ./
RUN npm run build

# ── Stage 2: Python API server ────────────────────────────────────────────────
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    ca-certificates git libgdal-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install fdp from GitHub (shared data platform)
RUN pip install --no-cache-dir \
    "git+https://github.com/evolvedHow/fgdp.git#subdirectory=fdp"

# Install fdensemble dependencies
RUN pip install --no-cache-dir \
    "fastapi" \
    "uvicorn[standard]" \
    "pandas" \
    "numpy" \
    "matplotlib" \
    "python-dotenv" \
    "requests" \
    "httpx>=0.27.0" \
    "geopandas>=1.0.0" \
    "pyogrio>=0.7.0" \
    "pyarrow>=14.0.0" \
    "shapely>=2.0.0"

# Copy application source using repo-root-relative paths
COPY fdensemble/main.py ./
COPY fdensemble/fdp_client.py ./

# Copy ALARM dataverse files (GA_cd_2020_stats.csv etc.)
COPY fdensemble/dataverse_files/ ./dataverse_files/

# Copy canonical scorecard JSONs (GerryChain runs — pre-computed, small)
COPY fdensemble/input_data/ ./input_data/

# Copy built frontend from Stage 1
COPY --from=frontend-builder /build/dist/ ./frontend/dist/

ENV PYTHONUNBUFFERED=1
EXPOSE 8010

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8010}"]
