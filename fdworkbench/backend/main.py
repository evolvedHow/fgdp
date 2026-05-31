"""
FDP Policy Chat — FastAPI backend.

Endpoints:
  POST /api/chat          Main chat endpoint — full 3-stage pipeline, SSE streaming
  POST /api/query/execute Execute raw SQL (power-user endpoint, authenticated)
  GET  /api/schema        Data dictionary (tables, columns, row counts)
  GET  /api/health        Liveness check
  GET  /                  Serve static chat frontend
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="FDP Policy Chat",
    description="AI chat engine for Georgia redistricting data",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _admin_ok(token: str | None) -> bool:
    secret = os.environ.get("WORKBENCH_SECRET")
    if not secret:
        return False
    return token == secret


def _sse_line(event_dict: dict) -> str:
    """Format a dict as a Server-Sent Events data line."""
    return f"data: {json.dumps(event_dict)}\n\n"


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    """Liveness + database reachability check."""
    from .schema import execute_query  # noqa: PLC0415
    try:
        rows = execute_query("SELECT COUNT(*) AS n FROM fdp.geography", max_rows=1)
        return {"status": "ok", "geography_rows": rows[0]["n"]}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# GET /api/schema
# ---------------------------------------------------------------------------

@app.get("/api/schema")
def schema():
    """
    Return the FDP data dictionary — tables, columns, row counts, descriptions.

    Useful for the power-user SQL mode and for debugging prompt context.
    """
    from .schema import get_data_dictionary  # noqa: PLC0415
    return {"data_dictionary": get_data_dictionary()}


# ---------------------------------------------------------------------------
# POST /api/chat   — main SSE streaming endpoint
# ---------------------------------------------------------------------------

@app.post("/api/chat")
async def chat(body: dict):
    """
    Full 3-stage pipeline with SSE streaming.

    Request body:
        {
          "message": "How did Harris vs Trump break down by county?",
          "history": [
            {"role": "user",      "content": "..."},
            {"role": "assistant", "content": "..."}
          ]
        }

    SSE event stream:
        data: {"event": "sql",     "data": "SELECT ..."}
        data: {"event": "rows",    "data": [...], "row_count": N}
        data: {"event": "token",   "data": "word "}
        data: {"event": "chart",   "data": {...} or null}
        data: {"event": "finding", "data": "9 of 14 districts..."}
        data: {"event": "done",    "data": ""}
        data: {"event": "error",   "data": "message"}   ← on failure
    """
    message: str = body.get("message", "").strip()
    history: list[dict] = body.get("history", [])

    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    from .pipeline import run_pipeline_stream  # noqa: PLC0415

    async def event_generator():
        async for event in run_pipeline_stream(message, history):
            yield _sse_line(event)
            # Small yield to ensure the event is flushed immediately
            await asyncio.sleep(0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable Nginx buffering
        },
    )


# ---------------------------------------------------------------------------
# POST /api/query/execute   — power-user direct SQL (authenticated)
# ---------------------------------------------------------------------------

@app.post("/api/query/execute")
def execute_query_endpoint(
    body: dict,
    x_workbench_secret: str | None = Header(default=None, alias="X-Workbench-Secret"),
):
    """
    Execute arbitrary SQL directly (power-user endpoint).

    Requires X-Workbench-Secret header matching WORKBENCH_SECRET env var.
    Returns up to 2000 rows.

    Request body: { "sql": "SELECT ..." }
    """
    if not _admin_ok(x_workbench_secret):
        raise HTTPException(status_code=401, detail="Missing or invalid X-Workbench-Secret")

    sql: str = body.get("sql", "").strip()
    if not sql:
        raise HTTPException(status_code=400, detail="sql is required")

    from .schema import execute_query  # noqa: PLC0415
    from fdp.query import QueryError  # noqa: PLC0415

    try:
        rows = execute_query(sql)
        return {"rows": rows, "row_count": len(rows)}
    except QueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Static frontend — serve index.html + assets
# ---------------------------------------------------------------------------

_FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

if _FRONTEND_DIR.exists():
    # Serve /static/* for JS/CSS assets referenced by index.html
    _STATIC_DIR = _FRONTEND_DIR / "static"
    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (_FRONTEND_DIR / "index.html").read_text()
