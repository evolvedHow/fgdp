"""
FDP Policy Chat — Query Cache + Question Library
=================================================
Supabase-backed cache for query results and a library of featured/bookmarked
policy questions.

Cache lookup order (for any question):
  1. Normalize question text → SHA-256 hash
  2. Check fdp.query_cache WHERE question_hash = ? AND is_valid AND (expires_at IS NULL OR expires_at > NOW())
  3. Hit  → increment hit_count, return cached rows
  4. Miss → run pipeline, store result, return rows

Library management:
  - fdp.question_library holds predefined (YAML-seeded) + bookmarked questions
  - YAML is upserted on startup; runtime bookmarks added via /api/questions/bookmark
  - Invalidation sets is_valid = FALSE on the cache row (NOT deleted — preserves history)

Auth:
  - Read operations (cache lookup, library list) — open
  - Write operations (invalidate, bookmark) — require WORKBENCH_SECRET header
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import psycopg
import psycopg.rows

logger = logging.getLogger(__name__)

_LLM_CACHE_TTL_HOURS = int(os.environ.get("LLM_CACHE_TTL_HOURS", "168"))  # 7 days default


# ── Helpers ────────────────────────────────────────────────────────────────────

def _db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def _hash(text: str) -> str:
    """SHA-256 of lower-cased, whitespace-normalised question text."""
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()


def _conn():
    return psycopg.connect(_db_url(), row_factory=psycopg.rows.dict_row)


# ── Cache lookup ───────────────────────────────────────────────────────────────

def get_cached(question: str) -> dict | None:
    """
    Return a valid cache entry for this question, or None if not cached.

    Also increments hit_count on cache hit.
    """
    q_hash = _hash(question)
    try:
        with _conn() as conn:
            row = conn.execute(
                """
                UPDATE fdp.query_cache
                SET    hit_count = hit_count + 1
                WHERE  question_hash = %s
                  AND  is_valid = TRUE
                  AND  (expires_at IS NULL OR expires_at > NOW())
                RETURNING id, question_text, sql_query, result_rows,
                          row_count, library_id, source,
                          refreshed_at, hit_count, expires_at
                """,
                (q_hash,),
            ).fetchone()
            return dict(row) if row else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cache lookup failed: %s", exc)
        return None


def store_cache(
    question: str,
    sql: str,
    rows: list[dict],
    row_count: int,
    library_id: str | None = None,
    expires_hours: int | None = None,
) -> None:
    """
    Store query results in the cache.

    expires_hours:
      - None (library predefined with no expiry) → NULL in DB
      - int → absolute timestamp NOW() + interval
      - For ad-hoc LLM questions, defaults to _LLM_CACHE_TTL_HOURS
    """
    q_hash = _hash(question)
    source = "library" if library_id else "llm"

    if expires_hours is None and library_id is None:
        # Ad-hoc LLM question — use default TTL
        expires_hours = _LLM_CACHE_TTL_HOURS

    expires_sql = (
        f"NOW() + INTERVAL '{expires_hours} hours'" if expires_hours else "NULL"
    )

    try:
        with _conn() as conn:
            conn.execute(
                f"""
                INSERT INTO fdp.query_cache
                    (question_hash, question_text, sql_query, result_rows,
                     row_count, library_id, source, refreshed_at, expires_at)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, NOW(), {expires_sql})
                ON CONFLICT (question_hash) WHERE is_valid DO UPDATE SET
                    sql_query    = EXCLUDED.sql_query,
                    result_rows  = EXCLUDED.result_rows,
                    row_count    = EXCLUDED.row_count,
                    library_id   = EXCLUDED.library_id,
                    source       = EXCLUDED.source,
                    refreshed_at = NOW(),
                    expires_at   = {expires_sql},
                    is_valid     = TRUE
                """,
                (
                    q_hash,
                    question,
                    sql,
                    json.dumps(rows, default=str),
                    row_count,
                    library_id,
                    source,
                ),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cache store failed (non-fatal): %s", exc)


def invalidate_cache(library_id: str | None = None, question: str | None = None) -> int:
    """
    Mark cache entries as invalid. Returns the number of rows invalidated.

    Pass library_id to invalidate all entries for a library question.
    Pass question text to invalidate by exact question hash.
    """
    try:
        with _conn() as conn:
            if library_id:
                result = conn.execute(
                    "UPDATE fdp.query_cache SET is_valid = FALSE WHERE library_id = %s AND is_valid = TRUE RETURNING id",
                    (library_id,),
                )
            elif question:
                result = conn.execute(
                    "UPDATE fdp.query_cache SET is_valid = FALSE WHERE question_hash = %s AND is_valid = TRUE RETURNING id",
                    (_hash(question),),
                )
            else:
                return 0
            return len(result.fetchall())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cache invalidation failed: %s", exc)
        return 0


# ── Question Library ───────────────────────────────────────────────────────────

def get_library() -> list[dict]:
    """
    Return all active library questions with their cache status.

    Each item includes:
      id, question_text, sql_query, source, created_at, tags,
      expires_hours, display_order,
      cache_refreshed_at, cache_hit_count, cache_is_valid, cache_expires_at
    """
    try:
        with _conn() as conn:
            rows = conn.execute(
                """
                SELECT
                    ql.id,
                    ql.question_text,
                    ql.sql_query IS NOT NULL        AS has_predefined_sql,
                    ql.source,
                    ql.created_by,
                    ql.created_at,
                    ql.tags,
                    ql.expires_hours,
                    ql.display_order,
                    qc.refreshed_at                 AS cache_refreshed_at,
                    qc.hit_count                    AS cache_hit_count,
                    qc.is_valid                     AS cache_is_valid,
                    qc.expires_at                   AS cache_expires_at
                FROM fdp.question_library ql
                LEFT JOIN fdp.query_cache qc
                  ON qc.library_id = ql.id AND qc.is_valid = TRUE
                WHERE ql.is_active = TRUE
                ORDER BY ql.display_order ASC, ql.created_at ASC
                """
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Library fetch failed: %s", exc)
        return []


def get_library_question(library_id: str) -> dict | None:
    """Return a single library question by id."""
    try:
        with _conn() as conn:
            row = conn.execute(
                "SELECT * FROM fdp.question_library WHERE id = %s AND is_active = TRUE",
                (library_id,),
            ).fetchone()
            return dict(row) if row else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Library question fetch failed: %s", exc)
        return None


def upsert_library_question(
    id: str,
    question_text: str,
    sql_query: str | None,
    source: str = "predefined",
    created_by: str | None = None,
    tags: list[str] | None = None,
    expires_hours: int | None = None,
    display_order: int = 999,
) -> None:
    """Insert or update a library question. Used for YAML seeding and bookmarking."""
    try:
        with _conn() as conn:
            conn.execute(
                """
                INSERT INTO fdp.question_library
                    (id, question_text, sql_query, source, created_by,
                     tags, expires_hours, display_order, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                ON CONFLICT (id) DO UPDATE SET
                    question_text = EXCLUDED.question_text,
                    sql_query     = EXCLUDED.sql_query,
                    tags          = EXCLUDED.tags,
                    expires_hours = EXCLUDED.expires_hours,
                    display_order = EXCLUDED.display_order,
                    updated_at    = NOW()
                """,
                (
                    id,
                    question_text,
                    sql_query,
                    source,
                    created_by,
                    tags or [],
                    expires_hours,
                    display_order,
                ),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Library upsert failed for %s: %s", id, exc)
