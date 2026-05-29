# FDP — Fair Districts Data Platform
# Single image: run the CLI or serve the future API.
#
# Build:
#   docker build -t fdp .
#
# Run CLI:
#   docker run --env-file .env -v /path/to/data:/fdp-data fdp fdp status
#
# Run init-db (one-time setup against a new database):
#   docker run --env-file .env fdp fdp init-db
#
# Load parquets into PostgreSQL:
#   docker run --env-file .env -v /path/to/data:/fdp-data fdp fdp load-pg --geo vtd

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

# Install dependencies into the system Python (no venv inside container)
RUN uv pip install --system --no-cache .

# Copy source
COPY fdp/       ./fdp/
COPY config/    ./config/
COPY sql/       ./sql/

# Data volume — mount your local data/ folder here at runtime
VOLUME ["/fdp-data"]

ENV PYTHONUNBUFFERED=1
ENV FDP_ROOT=/fdp-data

# Default: run the CLI
ENTRYPOINT ["fdp"]
CMD ["--help"]
