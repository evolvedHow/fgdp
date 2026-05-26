#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "→ Creating virtual environment..."
  uv sync
fi

echo "→ Starting FD Workbench at http://localhost:8003"
uv run uvicorn backend.main:app --reload --port 8003 --host 0.0.0.0
