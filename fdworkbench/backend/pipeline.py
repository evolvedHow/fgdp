"""
FDP Policy Chat — 3-stage NLQ pipeline.

Stage 1: NLQ → SQL      (LiteLLM → Claude/Groq, non-streaming)
Stage 2: SQL → Execute  (fdp.query.execute_select → Supabase)
Stage 3: Results → Insight + Chart  (Claude, streaming SSE)

Each stage is a separate function so stages can be tested independently
and so the caller (main.py) can emit SSE events between stages.

SSE event sequence emitted by run_pipeline_stream():
  {"event": "sql",     "data": "<SELECT ...>"}
  {"event": "rows",    "data": [...],  "row_count": N}
  {"event": "token",   "data": "<word>"}   ← repeated for narrative tokens
  {"event": "chart",   "data": {...}}      ← Vega-Lite spec or null
  {"event": "finding", "data": "<bold stat>"}
  {"event": "done",    "data": ""}
  {"event": "error",   "data": "<message>"}  ← on failure
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import AsyncIterator

import litellm

from .schema import execute_query, get_data_dictionary
from .prompts import build_sql_prompt, INSIGHT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

litellm.set_verbose = False


# ---------------------------------------------------------------------------
# Model selection
# ---------------------------------------------------------------------------

def _sql_model() -> str:
    """LLM for Stage 1 (SQL generation) — prefers Claude for accuracy."""
    return os.environ.get(
        "SQL_LLM_PROVIDER",
        os.environ.get("LLM_PROVIDER", "anthropic/claude-sonnet-4-20250514"),
    )


def _insight_model() -> str:
    """LLM for Stage 3 (insight generation) — Claude preferred for policy framing."""
    return os.environ.get(
        "INSIGHT_LLM_PROVIDER",
        os.environ.get("LLM_PROVIDER", "anthropic/claude-sonnet-4-20250514"),
    )


# ---------------------------------------------------------------------------
# Stage 1 — NLQ → SQL
# ---------------------------------------------------------------------------

def generate_sql(
    question: str,
    history: list[dict] | None = None,
) -> str:
    """
    Convert a natural language question to a PostgreSQL SELECT statement.

    Parameters
    ----------
    question:   The user's current question in plain English.
    history:    Prior conversation turns [{"role": "user"|"assistant", "content": ...}].
                Used to resolve anaphoric references ("show that by county").

    Returns
    -------
    str — a PostgreSQL SELECT statement ready to execute.
    """
    data_dict = get_data_dictionary()
    system_prompt = build_sql_prompt(data_dict)

    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    # Inject conversation history (last 6 turns to stay within context limits)
    if history:
        for turn in history[-6:]:
            messages.append({"role": turn["role"], "content": turn["content"]})

    messages.append({"role": "user", "content": question})

    resp = litellm.completion(
        model=_sql_model(),
        messages=messages,
        max_tokens=2048,
        temperature=0,
    )
    raw = resp.choices[0].message.content.strip()

    # Strip accidental markdown fences
    raw = re.sub(r"^```\w*\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw.strip())

    # Extract first SQL statement (safety)
    statements = [s.strip() for s in raw.split(";") if s.strip()]
    sql = statements[0] if statements else raw

    logger.debug("Stage 1 SQL: %s", sql[:200])
    return sql


# ---------------------------------------------------------------------------
# Stage 2 — Execute SQL
# ---------------------------------------------------------------------------

def execute_sql(sql: str, max_rows: int = 2000) -> tuple[list[dict], int]:
    """
    Execute a SELECT against Supabase and return (rows, total_row_count).

    Returns a display-safe sample (≤ max_rows) plus the count of all rows.
    """
    from fdp.query import QueryError  # noqa: PLC0415

    rows = execute_query(sql, max_rows=max_rows)
    return rows, len(rows)


# ---------------------------------------------------------------------------
# Stage 3 — Insight + Chart (streaming)
# ---------------------------------------------------------------------------

async def generate_insight_stream(
    question: str,
    sql: str,
    rows: list[dict],
    row_count: int,
) -> AsyncIterator[dict]:
    """
    Async generator that yields SSE event dicts for Stage 3.

    Yields:
        {"event": "token",   "data": "<word>"}  — narrative tokens (streamed)
        {"event": "chart",   "data": {...}}      — Vega-Lite spec or null
        {"event": "finding", "data": "<text>"}  — key finding stat
    """
    # Prepare context for the insight LLM — use first 50 rows to stay concise
    sample = rows[:50]
    columns = list(sample[0].keys()) if sample else []

    user_content = f"""Question: {question}

SQL executed:
{sql}

Result: {row_count} total rows. Showing first {len(sample)}:
Columns: {columns}

{json.dumps(sample, indent=2, default=str)}
"""

    messages = [
        {"role": "system", "content": INSIGHT_SYSTEM_PROMPT},
        {"role": "user",   "content": user_content},
    ]

    # Stream the response
    accumulated = ""
    try:
        stream = litellm.completion(
            model=_insight_model(),
            messages=messages,
            max_tokens=2048,
            temperature=0.3,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            accumulated += delta
            # Emit tokens as they arrive (but only actual word characters to reduce noise)
            if delta:
                yield {"event": "token", "data": delta}

    except Exception as exc:  # noqa: BLE001
        logger.error("Stage 3 LLM error: %s", exc)
        yield {"event": "error", "data": f"Insight generation failed: {exc}"}
        return

    # Parse the completed JSON response
    try:
        # Claude sometimes wraps in ```json ... ``` — strip it
        clean = re.sub(r"^```json\s*", "", accumulated.strip(), flags=re.MULTILINE)
        clean = re.sub(r"\s*```$", "", clean.strip())
        parsed = json.loads(clean)
        yield {"event": "chart",   "data": parsed.get("chart")}
        yield {"event": "finding", "data": parsed.get("key_finding", "")}
    except json.JSONDecodeError as exc:
        logger.warning("Stage 3 JSON parse error: %s — raw: %s", exc, accumulated[:200])
        # Graceful degradation: no chart, no finding — narrative tokens already streamed
        yield {"event": "chart",   "data": None}
        yield {"event": "finding", "data": ""}


# ---------------------------------------------------------------------------
# Full pipeline (for use by main.py SSE endpoint)
# ---------------------------------------------------------------------------

async def run_pipeline_stream(
    question: str,
    history: list[dict] | None = None,
) -> AsyncIterator[dict]:
    """
    Run the full 3-stage pipeline and yield SSE event dicts.

    Yields events in this order:
      sql → rows → token (×N) → chart → finding → done

    On error at any stage: yields error event and stops.
    """
    # Stage 1
    try:
        sql = generate_sql(question, history)
    except Exception as exc:  # noqa: BLE001
        logger.error("Stage 1 failed: %s", exc)
        yield {"event": "error", "data": f"Could not generate SQL: {exc}"}
        return

    yield {"event": "sql", "data": sql}

    # Stage 2
    try:
        rows, row_count = execute_sql(sql)
    except Exception as exc:  # noqa: BLE001
        logger.error("Stage 2 failed: %s", exc)
        yield {"event": "error", "data": f"Query failed: {exc}"}
        return

    yield {"event": "rows", "data": rows[:100], "row_count": row_count}

    if not rows:
        yield {"event": "token", "data": "The query returned no results for this question. "}
        yield {"event": "token", "data": "This may mean the data isn't available yet, "}
        yield {"event": "token", "data": "or the question needs to be refined."}
        yield {"event": "chart",   "data": None}
        yield {"event": "finding", "data": "No data found"}
        yield {"event": "done",    "data": ""}
        return

    # Stage 3
    async for event in generate_insight_stream(question, sql, rows, row_count):
        yield event

    yield {"event": "done", "data": ""}
