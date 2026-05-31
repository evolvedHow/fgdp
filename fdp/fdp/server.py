"""
FDP API server — FastAPI app factory.

Start locally:
    DATABASE_URL='postgresql://...' uvicorn fdp.server:app --reload --port 8080

Or via the fdp CLI (after installing with the api extra):
    uv run --extra api uvicorn fdp.server:app --host 0.0.0.0 --port 8080

Environment variables
---------------------
DATABASE_URL    PostgreSQL connection string (required)
FDPAPI_SECRET   Secret token for write/query endpoints (optional; set to enable)
FDPAPI_ORIGINS  Comma-separated list of allowed CORS origins
                (default: * — open for public non-profit data)
FDP_ROOT        FDP data root directory (for catalog/scan operations)
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fdp.api import router


def create_app() -> FastAPI:
    """Create and configure the FDP FastAPI application."""
    app = FastAPI(
        title="Fair Districts Data Platform API",
        description=(
            "REST API for Georgia redistricting data — election results, "
            "CVAP demographics, and geography at the VTD level."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS — permissive by default (public non-profit data).
    # Override FDPAPI_ORIGINS to restrict to specific domains in production.
    raw_origins = os.environ.get("FDPAPI_ORIGINS", "*")
    if raw_origins == "*":
        allow_origins = ["*"]
    else:
        allow_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.include_router(router, prefix="/api/v1")

    return app


# Module-level app instance — used by uvicorn/gunicorn:
#   uvicorn fdp.server:app
app = create_app()
