# fdensemble — Redistricting Ensemble Analysis
# Multi-stage build: Node builds the Svelte frontend, Python runs the API.
#
# Railway setup:
#   Root directory  → fdensemble
#   Builder         → auto-detect (finds this Dockerfile)
#   Port            → 8010
#
# Optional env vars:
#   FDPAPI_BASE   https://fdp-api.up.railway.app  (enables FDP API mode)
#   DATA_DIR      path to ALARM CSV files (default: dataverse_files/GA_cd_2020)

# ── Stage 1: build Svelte frontend ────────────────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
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

# Copy application source
COPY main.py ./
COPY fdp_client.py ./

# Copy built frontend from Stage 1
COPY --from=frontend-builder /build/dist/ ./frontend/dist/

ENV PYTHONUNBUFFERED=1
EXPOSE 8010

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8010}"]
