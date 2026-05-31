# fdensemble — Redistricting Ensemble Analysis
#
# Self-contained: installs fdp directly from GitHub.
# Build context: fdensemble/ directory only.
#
# Railway setup:
#   Root directory  → fdensemble
#   Builder         → auto-detect (finds this Dockerfile)
#   Port            → 8010
#
# Optional env vars:
#   FDPAPI_BASE   https://fdp-api.up.railway.app  (enables FDP API mode)
#   DATA_DIR      path to ALARM CSV files (default: dataverse_files/GA_cd_2020)
#
# If your GitHub repo is private, also add:
#   GITHUB_TOKEN  a GitHub PAT with repo read scope

FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    ca-certificates git \
    libgdal-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Install fdp from GitHub (shared data platform) ─────────────────────────
# Public repo:
RUN pip install --no-cache-dir \
    "git+https://github.com/evolvedHow/fgdp.git#subdirectory=fdp"

# Private repo — uncomment and set GITHUB_TOKEN in Railway dashboard:
# ARG GITHUB_TOKEN
# RUN pip install --no-cache-dir \
#     "git+https://${GITHUB_TOKEN}@github.com/evolvedHow/fgdp.git#subdirectory=fdp"

# ── Install fdensemble dependencies ────────────────────────────────────────
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

# ── Copy application source ────────────────────────────────────────────────
COPY main.py ./
COPY fdp_client.py ./
# Pre-built frontend (run `npm run build` locally before docker build)
COPY frontend/dist/ ./frontend/dist/

# ALARM dataverse files can be baked into the image or fetched at startup.
# On Railway, mount via Railway Volumes if needed.
ENV PYTHONUNBUFFERED=1
EXPOSE 8010

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8010}"]
