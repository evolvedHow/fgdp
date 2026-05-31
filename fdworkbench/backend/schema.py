"""
fdworkbench schema module — thin wrapper around fdp.schema.data_dictionary.

All data dictionary logic lives in the fdp platform package so that other
apps (fdensemble, future analytics tools) can reuse it without duplicating
the Supabase introspection logic.

This module exists only to:
  1. Provide the DATABASE_URL plumbing from the app's environment
  2. Re-export execute_query for use by main.py
"""

from __future__ import annotations

import os

from fdp.schema.data_dictionary import get_data_dictionary as _get_dd
from fdp.query import execute_select, QueryError


def get_db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set.  "
            "Add it to .env or set it in your shell before starting fdworkbench."
        )
    return url


def get_data_dictionary() -> str:
    """
    Return the FDP schema data dictionary as a string for use in LLM prompts.

    Introspected from live Supabase on first call, cached for the process lifetime.
    """
    return _get_dd(db_url=get_db_url())


def execute_query(sql: str, params: list | None = None, max_rows: int = 2000) -> list[dict]:
    """
    Execute a read-only SELECT against the FDP Supabase database.

    Raises QueryError on SQL errors.
    """
    return execute_select(db_url=get_db_url(), sql=sql, params=params, max_rows=max_rows)
