"""
FDP read-only query executor.

Provides a thin, safe wrapper for running SELECT statements against any
PostgreSQL database (typically Supabase).  Handles connection, type
serialization, and row-count capping.

This module is intentionally minimal — it delegates connection management
to psycopg directly rather than going through DataManifest, so it can be
used standalone by any app that has DATABASE_URL set.

Usage
-----
    from fdp.query import execute_select

    rows = execute_select(
        db_url=os.environ["DATABASE_URL"],
        sql="SELECT geoid, cvap_tot FROM fdp.cvap WHERE state = %s LIMIT 100",
        params=["GA"],
    )
    # rows is a list[dict] ready for JSON serialization

Error handling
--------------
Raises ``QueryError`` (subclass of RuntimeError) on SQL errors so callers
can catch it without importing psycopg directly.
"""

from __future__ import annotations

import decimal
import datetime
from typing import Any

import psycopg
import psycopg.rows


# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------

class QueryError(RuntimeError):
    """Raised when execute_select encounters a SQL error."""


# ---------------------------------------------------------------------------
# Type serializer
# ---------------------------------------------------------------------------

def _to_json_safe(value: Any) -> Any:
    """Convert a psycopg value to a JSON-serializable Python type."""
    if value is None:
        return None
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return value.hex() if isinstance(value, (bytes, bytearray)) else bytes(value).hex()
    return value


# ---------------------------------------------------------------------------
# execute_select
# ---------------------------------------------------------------------------

def execute_select(
    db_url: str,
    sql: str,
    params: list | tuple | None = None,
    max_rows: int = 2000,
    read_only: bool = True,
) -> list[dict]:
    """
    Execute a single SELECT statement and return results as a list of dicts.

    Parameters
    ----------
    db_url:     PostgreSQL connection string.
    sql:        SQL query — must be a SELECT, WITH, or EXPLAIN statement.
    params:     Positional parameters for the query (%s placeholders).
    max_rows:   Maximum rows to return (hard cap — use LIMIT in your SQL
                for predictable results).
    read_only:  If True (default), sets the session to READ ONLY before
                executing.  Set False only for trusted internal callers.

    Returns
    -------
    list[dict]  — column names as keys, values JSON-serializable.

    Raises
    ------
    ValueError  — if ``sql`` does not start with SELECT/WITH/EXPLAIN.
    QueryError  — if psycopg raises a database error.
    """
    # Guard: only read statements
    first = sql.strip().split()[0].upper() if sql.strip() else ""
    if first not in ("SELECT", "WITH", "EXPLAIN"):
        raise ValueError(
            f"execute_select only permits SELECT/WITH/EXPLAIN; got {first!r}. "
            "Use psycopg directly for write operations."
        )

    try:
        with psycopg.connect(db_url, row_factory=psycopg.rows.dict_row) as conn:
            if read_only:
                conn.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
            with conn.cursor() as cur:
                cur.execute(sql, params or [])
                raw = cur.fetchmany(max_rows)
    except psycopg.Error as exc:
        raise QueryError(str(exc)) from exc

    return [
        {k: _to_json_safe(v) for k, v in row.items()}
        for row in raw
    ]


# ---------------------------------------------------------------------------
# column_names
# ---------------------------------------------------------------------------

def column_names(db_url: str, table: str, schema: str = "fdp") -> list[str]:
    """
    Return the column names for a table in a given schema.

    Useful for building SELECT lists or validating column references.
    """
    sql = """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
    """
    rows = execute_select(db_url, sql, [schema, table], max_rows=200, read_only=False)
    return [r["column_name"] for r in rows]
