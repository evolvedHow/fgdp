# FDP — Fair Districts Data Platform
# Serves the FDP REST API (FastAPI/uvicorn) by default.
# Can also run the CLI by overriding ENTRYPOINT/CMD at launch.
#
# Build:
#   docker build -t fdp-api .
#
# Run API server (production):
#   docker run -e DATABASE_URL='postgresql://...' -e FDPAPI_SECRET='...' \
#              -p 8080:8080 fdp-api
#
# Run API server with local data for CLI commands:
#   docker run -e DATABASE_URL='postgresql://...' \
#              -v /path/to/data:/fdp-data -p 8080:8080 fdp-api
#
# Override to run CLI instead:
#   docker run --env-file .env -v /path/to/data:/fdp-data \
#              --entrypoint fdp fdp-api status

FROM python:3.12-slim

# psycopg[binary] bundles its own libpq — no apt install needed.
# Only install ca-certificates for TLS connections to cloud DBs (Supabase etc.)
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv (fast dependency resolver / venv manager)
RUN pip install --no-cache-dir uv

# Copy dependency manifests first (layer-cache friendly)
COPY pyproject.toml uv.lock* ./

# Install core + api extras (fastapi + uvicorn) into the system Python
RUN uv pip install --system --no-cache --extra api .

# Copy source
COPY fdp/       ./fdp/
COPY config/    ./config/
COPY sql/       ./sql/

# FDP_ROOT: CLI commands look here for local data files.
# On Railway, data is in Supabase — this path is unused but harmless.
ENV PYTHONUNBUFFERED=1
ENV FDP_ROOT=/fdp-data

EXPOSE 8080

# Default: serve the API.
# Override ENTRYPOINT to "fdp" for CLI use.
CMD ["uvicorn", "fdp.server:app", "--host", "0.0.0.0", "--port", "8080"]
