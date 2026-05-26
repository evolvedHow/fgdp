"""
FD Workbench — FastAPI backend.

Endpoints:
  POST /api/nlq/process        NLQ → similarity check + SQL generation
  POST /api/query/execute      Execute arbitrary SQL
  GET  /api/queries            List saved queries
  POST /api/queries            Save a query
  GET  /api/queries/{id}       Get one saved query + cached results
  POST /api/queries/{id}/refresh  Re-run SQL, update cache
  DELETE /api/queries/{id}     Delete query + cache file
  GET  /api/schema             Data dictionary
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import duckdb
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from . import db, nlq, schema

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── paths ─────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent.parent
CACHE_DIR  = BASE_DIR / "data" / "cache"
DB_PATH    = os.environ.get("WORKBENCH_DB", str(BASE_DIR / "data" / "workbench.db"))
STATIC_DIR = BASE_DIR / "frontend"

CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── startup ────────────────────────────────────────────────────────────────────
db.init(DB_PATH)
_duck = schema.get_conn()   # warm up DuckDB / load data

app = FastAPI(title="FD Workbench", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── helpers ────────────────────────────────────────────────────────────────────

MAX_RESULT_ROWS = 500
CACHE_MAX_ROWS  = 2000


def _first_statement(sql: str) -> str:
    """Extract the first complete SQL statement, stripping trailing ones and comments."""
    import re
    # Remove line comments before splitting so comment text doesn't confuse the split
    no_comments = re.sub(r"--[^\n]*", "", sql)
    # Split on semicolons — take the first non-empty statement
    parts = [p.strip() for p in no_comments.split(";") if p.strip()]
    return parts[0] if parts else sql.strip()


def _execute_sql(sql: str) -> dict:
    """Run SQL against DuckDB; returns {columns, rows, row_count, truncated}."""
    conn = schema.get_conn()
    clean = _first_statement(sql)
    try:
        rel = conn.execute(clean)
        columns = [d[0] for d in rel.description]
        all_rows = rel.fetchall()
    except duckdb.Error as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    total = len(all_rows)
    truncated = total > MAX_RESULT_ROWS
    rows = all_rows[:MAX_RESULT_ROWS]
    # Serialize: convert any non-JSON-native types
    safe_rows = [
        [c if c is None or isinstance(c, (int, float, str, bool)) else str(c) for c in row]
        for row in rows
    ]
    return {
        "columns": columns,
        "rows": safe_rows,
        "row_count": total,
        "truncated": truncated,
    }


def _cache_path(query_id: int) -> Path:
    return CACHE_DIR / f"query_{query_id}.json"


def _write_cache(query_id: int, result: dict) -> str:
    p = _cache_path(query_id)
    # Cap cache at CACHE_MAX_ROWS
    cached = dict(result)
    if len(result["rows"]) > CACHE_MAX_ROWS:
        cached["rows"] = result["rows"][:CACHE_MAX_ROWS]
        cached["cache_truncated"] = True
    p.write_text(json.dumps(cached))
    return str(p.relative_to(BASE_DIR))


def _read_cache(query_id: int) -> dict | None:
    p = _cache_path(query_id)
    if p.exists():
        return json.loads(p.read_text())
    return None


# ── pydantic models ────────────────────────────────────────────────────────────

class NLQRequest(BaseModel):
    nlq: str
    force_new: bool = False   # skip similarity check

class ExecuteRequest(BaseModel):
    sql: str
    nlq: str | None = None

class SaveRequest(BaseModel):
    title: str
    nlq: str
    sql: str
    result_cache_path: str | None = None
    row_count: int | None = None


# ── API routes ─────────────────────────────────────────────────────────────────

@app.post("/api/nlq/process")
async def process_nlq(req: NLQRequest):
    """
    1. Check if a similar saved query exists.
    2. If yes, return it with cached results.
    3. If no, generate SQL from the NLQ.
    """
    nlq_text = req.nlq.strip()
    if not nlq_text:
        raise HTTPException(status_code=400, detail="nlq is required")

    saved = db.list_queries()

    # Step 1: similarity check (skipped if force_new)
    if saved and not req.force_new:
        matched_id = nlq.check_similarity(nlq_text, saved)
        if matched_id:
            matched = db.get_query(matched_id)
            cached = _read_cache(matched_id)
            return {
                "type": "match",
                "matched_query": matched,
                "cached_results": cached,
            }

    # Step 2: generate SQL
    try:
        generated_sql = nlq.nlq_to_sql(nlq_text)
    except Exception as exc:
        logger.error("NLQ→SQL failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"LLM error: {exc}")

    return {
        "type": "generated",
        "sql": generated_sql,
    }


@app.post("/api/query/execute")
async def execute_query(req: ExecuteRequest):
    result = _execute_sql(req.sql)
    return result


@app.get("/api/queries")
async def list_queries():
    return db.list_queries()


@app.post("/api/queries")
async def save_query(req: SaveRequest):
    record = db.create_query(
        title=req.title,
        nlq=req.nlq,
        sql=req.sql,
        result_cache_path=req.result_cache_path,
        row_count=req.row_count,
    )
    # If no cache yet, run the SQL now and cache it
    if not req.result_cache_path and record:
        try:
            result = _execute_sql(req.sql)
            cache_rel = _write_cache(record["id"], result)
            record = db.update_query_run(
                record["id"],
                result_cache_path=cache_rel,
                row_count=result["row_count"],
            )
        except Exception as exc:
            logger.warning("Could not cache result on save: %s", exc)
    return record


@app.get("/api/queries/{query_id}")
async def get_query(query_id: int):
    record = db.get_query(query_id)
    if not record:
        raise HTTPException(status_code=404, detail="Query not found")
    cached = _read_cache(query_id)
    return {"query": record, "cached_results": cached}


@app.post("/api/queries/{query_id}/refresh")
async def refresh_query(query_id: int):
    record = db.get_query(query_id)
    if not record:
        raise HTTPException(status_code=404, detail="Query not found")
    result = _execute_sql(record["sql"])
    cache_rel = _write_cache(query_id, result)
    updated = db.update_query_run(query_id, result_cache_path=cache_rel, row_count=result["row_count"])
    return {"query": updated, "result": result}


@app.delete("/api/queries/{query_id}")
async def delete_query(query_id: int):
    cache_path = db.delete_query(query_id)
    if cache_path:
        full = BASE_DIR / cache_path
        if full.exists():
            full.unlink()
    return {"ok": True}


@app.get("/api/schema")
async def get_schema():
    tables = schema.list_tables()
    return {"tables": tables, "data_dictionary": schema.DATA_DICTIONARY}


# ── static frontend ────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")

app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
