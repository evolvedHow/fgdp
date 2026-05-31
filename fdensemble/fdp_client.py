"""
fdensemble → FDP API client
============================
Thin abstraction layer that reads ensemble and election data from either:

  A) The hosted FDP REST API  (when FDPAPI_BASE env var is set)
  B) Local ALARM dataverse CSV files  (current default, no env var needed)

This module is the migration seam.  Today, all callers use path B (local files).
Once ensemble plans are loaded into Supabase via `fdp load-pg`, set FDPAPI_BASE
and callers can switch to path A without changing their business logic.

Environment variables
---------------------
FDPAPI_BASE   Base URL of the FDP API, e.g. https://fdp-api.up.railway.app
              Leave unset to use local files (current default).
FDPAPI_SECRET Optional API secret for authenticated endpoints.

Usage (future — not yet active)
--------------------------------
from fdp_client import get_election_data, get_ensemble_plans

# Returns list[dict] regardless of data source
elections = get_election_data(state="GA", year=2024, office="president")
plans     = get_ensemble_plans(run_id="GA_cd_2020")
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

FDPAPI_BASE: str | None = os.environ.get("FDPAPI_BASE", "").strip() or None
FDPAPI_SECRET: str | None = os.environ.get("FDPAPI_SECRET", "").strip() or None

_api_mode = FDPAPI_BASE is not None


def using_api() -> bool:
    """Return True when FDPAPI_BASE is configured and API mode is active."""
    return _api_mode


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _headers() -> dict[str, str]:
    h: dict[str, str] = {"Accept": "application/json"}
    if FDPAPI_SECRET:
        h["X-FDPAPI-Secret"] = FDPAPI_SECRET
    return h


def _get(path: str, params: dict | None = None) -> Any:
    """Synchronous GET against the FDP API."""
    import httpx  # noqa: PLC0415 — optional at import time when not in API mode

    url = f"{FDPAPI_BASE}{path}"
    r = httpx.get(url, params=params, headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


# ── Public API ────────────────────────────────────────────────────────────────

def get_election_data(
    state: str = "GA",
    year: int | None = None,
    office: str | None = None,
    geo_level: str = "vtd",
) -> list[dict]:
    """
    Fetch election results.

    When FDPAPI_BASE is set → calls GET /api/v1/elections
    Otherwise             → raises NotImplementedError (local path goes through main.py directly)
    """
    if not _api_mode:
        raise NotImplementedError(
            "get_election_data() requires FDPAPI_BASE.  "
            "Local file loading is handled directly in main.py._load_csv()."
        )
    params: dict[str, Any] = {"state": state, "geo_level": geo_level}
    if year:
        params["year"] = year
    if office:
        params["office"] = office
    data = _get("/api/v1/elections", params=params)
    return data if isinstance(data, list) else data.get("items", [])


def get_ensemble_plans(
    run_id: str,
    geo_level: str = "vtd",
) -> list[dict]:
    """
    Fetch ensemble plan assignments from the FDP API.

    When FDPAPI_BASE is set → calls GET /api/v1/ensemble/{run_id}
    Otherwise             → raises NotImplementedError

    NOTE: The /api/v1/ensemble endpoint does not yet exist in the FDP API.
    It will be added once ensemble plans are loaded into fdp.ensemble_plans
    via the scoring pipeline.  See CLAUDE.md "Next Steps" for the pipeline order.
    """
    if not _api_mode:
        raise NotImplementedError(
            "get_ensemble_plans() requires FDPAPI_BASE + ensemble data in Supabase.  "
            "Run the ensemble scoring pipeline first (see CLAUDE.md)."
        )
    data = _get(f"/api/v1/ensemble/{run_id}", params={"geo_level": geo_level})
    return data if isinstance(data, list) else data.get("items", [])


def get_geography(
    state: str = "GA",
    geo_level: str = "vtd",
) -> list[dict]:
    """
    Fetch geography rows (geoid, name, county_fips, …) from the FDP API.
    """
    if not _api_mode:
        raise NotImplementedError("get_geography() requires FDPAPI_BASE.")
    params = {"state": state, "geo_level": geo_level}
    data = _get("/api/v1/geography", params=params)
    return data if isinstance(data, list) else data.get("items", [])


def health_check() -> dict:
    """Check FDP API liveness."""
    if not _api_mode:
        return {"status": "local_mode", "fdpapi_base": None}
    try:
        return _get("/api/v1/health")
    except Exception as exc:  # noqa: BLE001
        return {"status": "unreachable", "error": str(exc)}
