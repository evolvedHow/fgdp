# fdworkbench — FDP Policy Chat
#
# Self-contained: installs fdp directly from GitHub.
# Build context: fdworkbench/ directory only.
#
# Railway setup:
#   Root directory  → fdworkbench
#   Builder         → auto-detect (finds this Dockerfile)
#   Port            → 8003
#
# Required env vars in Railway dashboard:
#   DATABASE_URL       postgresql://postgres.[ref]:password@aws-1-us-east-2.pooler.supabase.com:5432/postgres
#   LLM_PROVIDER       anthropic/claude-sonnet-4-20250514
#   ANTHROPIC_API_KEY  sk-ant-...
#
# Optional:
#   GROQ_API_KEY        fallback LLM
#   WORKBENCH_SECRET    enables POST /api/query/execute
#
# If your GitHub repo is private, also add:
#   GITHUB_TOKEN        a GitHub PAT with repo read scope
#   (and uncomment the ARG/RUN lines below)

FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates git \
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

# ── Install fdworkbench dependencies ───────────────────────────────────────
RUN pip install --no-cache-dir \
    "fastapi>=0.110.0" \
    "uvicorn[standard]>=0.27.0" \
    "litellm>=1.30.0" \
    "anthropic>=0.25.0" \
    "python-dotenv>=1.0.0" \
    "psycopg[binary]>=3.1.0"

# ── Copy application source ────────────────────────────────────────────────
COPY backend/ ./backend/
RUN mkdir -p ./frontend
COPY frontend/index.html ./frontend/index.html

ENV PYTHONUNBUFFERED=1
EXPOSE 8003

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8003}"]
