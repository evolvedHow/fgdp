# fdworkbench — FDP Policy Chat
#
# Railway: Root Directory = fdworkbench
# Build context = repo root (Railway sends full repo for Dockerfile builds)
# All COPY paths are relative to the repo root.
#
# Required env vars in Railway:
#   DATABASE_URL       postgresql://...supabase...
#   LLM_PROVIDER       anthropic/claude-sonnet-4-20250514
#   ANTHROPIC_API_KEY  sk-ant-...

FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install fdp from GitHub (shared data platform)
RUN pip install --no-cache-dir \
    "git+https://github.com/evolvedHow/fgdp.git#subdirectory=fdp"

# Install fdworkbench dependencies
RUN pip install --no-cache-dir \
    "fastapi>=0.110.0" \
    "uvicorn[standard]>=0.27.0" \
    "litellm>=1.30.0" \
    "anthropic>=0.25.0" \
    "python-dotenv>=1.0.0" \
    "psycopg[binary]>=3.1.0"

# Copy application source using repo-root-relative paths
COPY fdworkbench/backend/ ./backend/
RUN mkdir -p ./frontend
COPY fdworkbench/frontend/index.html ./frontend/index.html

ENV PYTHONUNBUFFERED=1
EXPOSE 8003

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8003}"]
