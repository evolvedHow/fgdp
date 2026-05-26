"""
SQLite workbench database — saved queries, metadata, cache pointers.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DB_PATH: Path | None = None


def init(db_path: str | Path) -> None:
    global _DB_PATH
    _DB_PATH = Path(db_path)
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS saved_queries (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                title             TEXT    NOT NULL,
                nlq               TEXT    NOT NULL,
                sql               TEXT    NOT NULL,
                result_cache_path TEXT,
                row_count         INTEGER,
                created_at        TEXT    NOT NULL,
                last_run_at       TEXT,
                use_count         INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.commit()


@contextmanager
def _connect():
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


# ── queries ──────────────────────────────────────────────────────────────────

def list_queries() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM saved_queries ORDER BY last_run_at DESC, created_at DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_query(query_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM saved_queries WHERE id = ?", (query_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def create_query(
    title: str,
    nlq: str,
    sql: str,
    result_cache_path: str | None = None,
    row_count: int | None = None,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO saved_queries
               (title, nlq, sql, result_cache_path, row_count, created_at, last_run_at, use_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
            (title, nlq, sql, result_cache_path, row_count, now, now),
        )
        conn.commit()
        new_id = cur.lastrowid
    return get_query(new_id)


def update_query_run(
    query_id: int,
    result_cache_path: str | None = None,
    row_count: int | None = None,
) -> dict | None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            """UPDATE saved_queries SET
               use_count         = use_count + 1,
               last_run_at       = ?,
               result_cache_path = COALESCE(?, result_cache_path),
               row_count         = COALESCE(?, row_count)
               WHERE id = ?""",
            (now, result_cache_path, row_count, query_id),
        )
        conn.commit()
    return get_query(query_id)


def delete_query(query_id: int) -> str | None:
    """Delete a saved query; returns its cache path so the caller can remove the file."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT result_cache_path FROM saved_queries WHERE id = ?", (query_id,)
        ).fetchone()
        cache_path = row["result_cache_path"] if row else None
        conn.execute("DELETE FROM saved_queries WHERE id = ?", (query_id,))
        conn.commit()
    return cache_path
