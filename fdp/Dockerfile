# FDP API — Fair Districts Data Platform
#
# Railway: Root Directory = fdp
# Build context = repo root (Railway sends full repo for Dockerfile builds)
# All COPY paths are relative to the repo root.

FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir uv

# Copy pyproject.toml from its repo-root-relative path
COPY fdp/pyproject.toml fdp/uv.lock* ./

# Install the package (fastapi + uvicorn via [api] extra)
RUN uv pip install --system --no-cache ".[api]"

# Copy the Python package source
COPY fdp/fdp/ ./fdp/

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

CMD ["sh", "-c", "uvicorn fdp.server:app --host 0.0.0.0 --port ${PORT:-8080}"]
