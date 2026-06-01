"""
FDP REST API — FastAPI router.

All read endpoints are open (no auth required) — the Supabase anon role
already grants SELECT on all fdp.* tables.

The POST /query endpoint executes raw SQL and requires the FDPAPI_SECRET
header.  This is used by fdworkbench for NLQ-to-SQL passthrough.

Route prefix /api/v1 is applied in server.py.

Endpoints
---------
GET  /health                    Liveness check
GET  /catalog                   List registered datasets (from fdp.datasets)
GET  /geography                 List geography rows (filterable)
GET  /elections                 Election results (filterable, aggregated per geoid+race)
GET  /elections/{geoid}         Full election history for one geographic unit
GET  /cvap                      CVAP rows (filterable)
GET  /cvap/{geoid}              CVAP for one geographic unit
GET  /districts/{state}         GeoJSON FeatureCollection of VTD geometries
POST /query                     Authenticated raw SQL passthrough (fdworkbench)
"""

from __future__ import annotations

import json
import os
from typing import Any

import psycopg
import psycopg.rows
from fastapi import APIRouter, HTTPException, Header, Query
from fastapi.responses import JSONResponse

router = APIRouter()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set.  "
            "Set it to your Supabase session-pooler connection string."
        )
    return url


def _connect() -> psycopg.Connection:
    return psycopg.connect(_db_url(), row_factory=psycopg.rows.dict_row)


def _secret_ok(token: str | None) -> bool:
    expected = os.environ.get("FDPAPI_SECRET")
    if not expected:
        return False  # secret not configured → write endpoints disabled
    return token == expected


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

@router.get("/health", summary="Liveness check")
def health() -> dict:
    """
    Returns HTTP 200 when the API is running and can reach the database.
    Returns HTTP 503 if the database is unreachable.
    """
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM fdp.geography")
                row = cur.fetchone()
        return {"status": "ok", "geography_rows": row["n"]}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Database unreachable: {exc}") from exc


# ---------------------------------------------------------------------------
# GET /catalog
# ---------------------------------------------------------------------------

@router.get("/catalog", summary="List registered datasets")
def catalog(
    state: str | None = Query(None, description="Filter by state (e.g. GA)"),
    category: str | None = Query(None, description="Filter by category (election | cvap | …)"),
    geography: str | None = Query(None, description="Filter by geography level (vtd | block | …)"),
    vintage: int | None = Query(None, description="Filter by data year"),
) -> list[dict]:
    """
    Return all registered datasets from fdp.datasets (the manifest registry).

    Datasets are registered by ``fdp scan`` and represent parquet files
    that have been processed and are ready to load or have been loaded.
    """
    clauses: list[str] = []
    params: list[Any] = []

    if state:
        clauses.append("state = %s")
        params.append(state.upper())
    if category:
        clauses.append("category = %s")
        params.append(category)
    if geography:
        clauses.append("geography = %s")
        params.append(geography)
    if vintage is not None:
        clauses.append("vintage = %s")
        params.append(vintage)

    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    sql = (
        "SELECT id, category, geography, vintage, state, source, "
        "election_type, row_count, loaded_at, notes "
        f"FROM fdp.datasets{where} "
        "ORDER BY state, vintage, category, geography"
    )

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


# ---------------------------------------------------------------------------
# GET /geography
# ---------------------------------------------------------------------------

@router.get("/geography", summary="List geography rows")
def geography(
    state: str | None = Query(None, description="Filter by state (e.g. GA)"),
    geo_level: str | None = Query("vtd", description="Geographic level (default: vtd)"),
    vintage_year: int | None = Query(2020, description="Boundary vintage year (default: 2020)"),
    county_fips: str | None = Query(None, description="Filter to a specific county (5-char FIPS)"),
    limit: int = Query(5000, le=10000, description="Max rows to return"),
) -> list[dict]:
    """
    Return geography dimension rows — one row per geographic unit.

    Filter by geo_level to switch between VTD, county, state, etc.
    The default returns all 2,698 Georgia VTDs at 2020 boundaries.
    """
    clauses: list[str] = []
    params: list[Any] = []

    if state:
        clauses.append("state = %s")
        params.append(state.upper())
    if geo_level:
        clauses.append("geo_level = %s")
        params.append(geo_level)
    if vintage_year is not None:
        clauses.append("vintage_year = %s")
        params.append(vintage_year)
    if county_fips:
        clauses.append("county_fips = %s")
        params.append(county_fips)

    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    sql = (
        "SELECT geoid, geo_level, geo_type, state, county_fips, name, "
        "vintage_year, source "
        f"FROM fdp.geography{where} "
        "ORDER BY geoid "
        "LIMIT %s"
    )
    params.append(limit)

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


# ---------------------------------------------------------------------------
# GET /elections
# ---------------------------------------------------------------------------

@router.get("/elections", summary="Election results (aggregated per VTD per race)")
def elections(
    state: str | None = Query(None, description="Filter by state (e.g. GA)"),
    year: int | None = Query(None, description="Election year (e.g. 2022)"),
    election_type: str | None = Query(None, description="general | runoff | special | primary"),
    office: str | None = Query(None, description="governor | president | senate | …"),
    geo_level: str | None = Query("vtd", description="Geographic level (default: vtd)"),
    county_fips: str | None = Query(None, description="Restrict to a single county"),
    limit: int = Query(10000, le=100000, description="Max rows returned"),
) -> list[dict]:
    """
    Return election results rows from fdp.election_results.

    Each row is one candidate's vote count in one geographic unit.
    To get two-party vote share, use the ``/v_election_2pv`` view via ``/query``,
    or filter to ``party IN ('dem','rep')`` and aggregate on the client.
    """
    clauses: list[str] = []
    params: list[Any] = []

    if state:
        clauses.append("er.state = %s")
        params.append(state.upper())
    if year is not None:
        clauses.append("er.year = %s")
        params.append(year)
    if election_type:
        clauses.append("er.election_type = %s")
        params.append(election_type)
    if office:
        clauses.append("er.office = %s")
        params.append(office)
    if geo_level:
        clauses.append("er.geo_level = %s")
        params.append(geo_level)
    if county_fips:
        clauses.append("LEFT(er.geoid, 5) = %s")
        params.append(county_fips)

    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    sql = (
        "SELECT er.geoid, er.geo_level, er.state, er.year, er.election_type, "
        "er.office, er.party, er.candidate, er.votes, er.source "
        f"FROM fdp.election_results er{where} "
        "ORDER BY er.geoid, er.year, er.office, er.party "
        "LIMIT %s"
    )
    params.append(limit)

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


# ---------------------------------------------------------------------------
# GET /elections/{geoid}
# ---------------------------------------------------------------------------

@router.get("/elections/{geoid}", summary="Full election history for one geographic unit")
def elections_by_geoid(geoid: str) -> list[dict]:
    """
    Return all election results for a single geoid (e.g. a VTD).

    Results span all years, offices, and parties loaded for that unit.
    """
    sql = (
        "SELECT geoid, geo_level, state, year, election_type, office, "
        "party, candidate, votes, source "
        "FROM fdp.election_results "
        "WHERE geoid = %s "
        "ORDER BY year, office, party"
    )
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (geoid,))
            rows = cur.fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail=f"No election data found for geoid={geoid!r}")
    return rows


# ---------------------------------------------------------------------------
# GET /cvap
# ---------------------------------------------------------------------------

@router.get("/cvap", summary="CVAP rows (filterable)")
def cvap(
    state: str | None = Query(None, description="Filter by state"),
    year: int | None = Query(None, description="ACS end year (e.g. 2024)"),
    geo_level: str | None = Query("vtd", description="Geographic level (default: vtd)"),
    county_fips: str | None = Query(None, description="Restrict to a single county"),
    limit: int = Query(5000, le=10000, description="Max rows returned"),
) -> list[dict]:
    """
    Return Citizen Voting Age Population rows from fdp.cvap.

    Use year=2024 for the 2020–2024 ACS 5-year CVAP estimates (most recent).
    """
    clauses: list[str] = []
    params: list[Any] = []

    if state:
        clauses.append("state = %s")
        params.append(state.upper())
    if year is not None:
        clauses.append("year = %s")
        params.append(year)
    if geo_level:
        clauses.append("geo_level = %s")
        params.append(geo_level)
    if county_fips:
        clauses.append("LEFT(geoid, 5) = %s")
        params.append(county_fips)

    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    sql = (
        "SELECT geoid, geo_level, state, year, cvap_tot, cvap_blk, cvap_hsp, "
        "cvap_wht, cvap_asn, cvap_ami, cvap_nhp, cvap_oth, source "
        f"FROM fdp.cvap{where} "
        "ORDER BY geoid "
        "LIMIT %s"
    )
    params.append(limit)

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


# ---------------------------------------------------------------------------
# GET /cvap/{geoid}
# ---------------------------------------------------------------------------

@router.get("/cvap/{geoid}", summary="CVAP for one geographic unit")
def cvap_by_geoid(geoid: str) -> list[dict]:
    """Return all CVAP years available for a single geoid."""
    sql = (
        "SELECT geoid, geo_level, state, year, cvap_tot, cvap_blk, cvap_hsp, "
        "cvap_wht, cvap_asn, cvap_ami, cvap_nhp, cvap_oth, source "
        "FROM fdp.cvap WHERE geoid = %s ORDER BY year"
    )
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (geoid,))
            rows = cur.fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail=f"No CVAP data found for geoid={geoid!r}")
    return rows


# ---------------------------------------------------------------------------
# GET /districts/{state}
# ---------------------------------------------------------------------------

@router.get(
    "/districts/{state}",
    summary="VTD geometries as GeoJSON FeatureCollection",
    response_class=JSONResponse,
)
def districts(
    state: str,
    vintage_year: int = Query(2020, description="Boundary vintage year"),
    county_fips: str | None = Query(None, description="Restrict to one county"),
) -> JSONResponse:
    """
    Return a GeoJSON FeatureCollection of VTD boundaries.

    Each Feature's ``properties`` includes geoid, county_fips, name, and
    the latest available CVAP data joined from fdp.cvap.

    Note: geometry is NOT stored in the PostgreSQL fdp schema.  This endpoint
    returns attribute data only (no geometry column).  To serve geometries,
    load the VTD shapefile into PostGIS or serve the static GeoJSON files
    from fdex/data/ directly.  The properties payload is designed to be
    merged client-side with a separately fetched GeoJSON geometry file.
    """
    clauses = ["g.state = %s", "g.geo_level = 'vtd'", "g.vintage_year = %s"]
    params: list[Any] = [state.upper(), vintage_year]

    if county_fips:
        clauses.append("g.county_fips = %s")
        params.append(county_fips)

    where = " WHERE " + " AND ".join(clauses)

    sql = f"""
        SELECT
            g.geoid,
            g.county_fips,
            g.name,
            g.geo_level,
            c.cvap_tot,
            c.cvap_blk,
            c.cvap_hsp,
            c.cvap_wht,
            c.cvap_asn,
            ROUND(100.0 * c.cvap_blk::NUMERIC / NULLIF(c.cvap_tot, 0), 1) AS pct_blk,
            ROUND(100.0 * c.cvap_hsp::NUMERIC / NULLIF(c.cvap_tot, 0), 1) AS pct_hsp,
            ROUND(100.0 * c.cvap_wht::NUMERIC / NULLIF(c.cvap_tot, 0), 1) AS pct_wht
        FROM fdp.geography g
        LEFT JOIN fdp.cvap c
            ON c.geoid = g.geoid
            AND c.year = (SELECT MAX(year) FROM fdp.cvap WHERE state = g.state AND geo_level = 'vtd')
        {where}
        ORDER BY g.geoid
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    features = [
        {
            "type": "Feature",
            "id": row["geoid"],
            "geometry": None,   # geometry not stored in fdp schema; merge client-side
            "properties": {k: v for k, v in row.items()},
        }
        for row in rows
    ]
    fc = {"type": "FeatureCollection", "features": features}
    return JSONResponse(content=fc)


# ---------------------------------------------------------------------------
# GET /schema
# ---------------------------------------------------------------------------

@router.get("/schema", summary="Data dictionary — tables, columns, row counts")
def schema() -> dict:
    """
    Return a data dictionary describing all FDP tables and their row counts.
    Useful for NLQ systems (fdworkbench) to understand queryable data.
    """
    sql = """
        SELECT
            t.table_name,
            obj_description(
                ('"fdp".' || quote_ident(t.table_name))::regclass, 'pg_class'
            ) AS table_comment,
            COUNT(c.column_name) AS column_count
        FROM information_schema.tables t
        JOIN information_schema.columns c
            ON c.table_schema = t.table_schema AND c.table_name = t.table_name
        WHERE t.table_schema = 'fdp'
          AND t.table_type = 'BASE TABLE'
        GROUP BY t.table_name
        ORDER BY t.table_name
    """
    col_sql = """
        SELECT column_name, data_type, col_description(
            ('"fdp".' || quote_ident(%s))::regclass,
            ordinal_position
        ) AS description
        FROM information_schema.columns
        WHERE table_schema = 'fdp' AND table_name = %s
        ORDER BY ordinal_position
    """
    count_sql = "SELECT COUNT(*) AS n FROM fdp.{}"

    result: dict[str, Any] = {}
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            tables = cur.fetchall()

            for tbl in tables:
                tname = tbl["table_name"]
                cur.execute(col_sql, (tname, tname))
                cols = cur.fetchall()
                try:
                    cur.execute(count_sql.format(tname))
                    row_count = cur.fetchone()["n"]
                except Exception:  # noqa: BLE001
                    row_count = None
                result[tname] = {
                    "description": tbl["table_comment"],
                    "row_count": row_count,
                    "columns": cols,
                }
    return result


# ---------------------------------------------------------------------------
# POST /query  (authenticated — fdworkbench / internal use only)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# GET /ensemble/runs
# ---------------------------------------------------------------------------

@router.get("/ensemble/runs", summary="List ensemble run catalog")
def ensemble_runs(
    status:       str | None = Query(None, description="Filter by status: pending|running|completed|failed"),
    benchmark_id: str | None = Query(None, description="Filter by benchmark template ID"),
    chamber:      str | None = Query(None, description="Filter by chamber: congress|senate|house"),
    limit:        int        = Query(50, le=500, description="Max rows returned"),
) -> list[dict]:
    """
    Return the ensemble run catalog from fdp.ensemble_runs.

    Each row represents one ensemble run (CLI or API-triggered).
    Key fields: run_name, benchmark_id, status, started_at, completed_at,
    runtime_minutes, n_draws, n_vtds, algorithm, plans_file.
    """
    clauses: list[str] = []
    params:  list[Any] = []

    if status:
        clauses.append("status = %s")
        params.append(status)
    if benchmark_id:
        clauses.append("benchmark_id = %s")
        params.append(benchmark_id)
    if chamber:
        clauses.append("params -> 'chamber' ->> 'name' = %s")
        params.append(chamber)

    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    sql = (
        f"SELECT * FROM fdp.v_ensemble_runs{where} "
        "ORDER BY created_at DESC LIMIT %s"
    )
    params.append(limit)

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


# ---------------------------------------------------------------------------
# GET /ensemble/runs/{run_name}
# ---------------------------------------------------------------------------

@router.get("/ensemble/runs/{run_name}", summary="Get one ensemble run by name")
def ensemble_run_detail(run_name: str) -> dict:
    """
    Return full detail for one ensemble run, including the complete params JSONB.
    """
    sql = (
        "SELECT run_name, benchmark_id, status, started_at, completed_at, "
        "params, n_draws, n_vtds, n_chains_run, runtime_seconds, "
        "plans_file, scores_file, demographics_file, draw_stats_file, "
        "error_message, notes, created_at, updated_at, loaded_by "
        "FROM fdp.ensemble_runs WHERE run_name = %s"
    )
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (run_name,))
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Run '{run_name}' not found")
    return row


# ---------------------------------------------------------------------------
# POST /ensemble/runs  (create / register a run)
# ---------------------------------------------------------------------------

@router.post("/ensemble/runs", summary="Register a new ensemble run", status_code=201)
def ensemble_run_create(
    body: dict,
    x_fdpapi_secret: str | None = Header(default=None, alias="X-FDPAPI-Secret"),
) -> dict:
    """
    Register a new ensemble run in the catalog.

    This creates a 'pending' catalog entry.  The actual chain execution is
    triggered separately (via CLI or Modal).  Use this endpoint to pre-register
    a run from an orchestration system, or to check that a run_name is available
    before starting a long compute job.

    Requires the ``X-FDPAPI-Secret`` header.

    Request body
    ------------
    {
        "run_name":     "congress_baseline_v1",       // required
        "benchmark_id": "ga_congress_2026_v1",        // required
        "params":       { ... },                       // optional — full params dict
        "notes":        "test run with 500 steps"      // optional
    }

    Response
    --------
    The created catalog row (status='pending').
    """
    if not _secret_ok(x_fdpapi_secret):
        raise HTTPException(status_code=401, detail="Missing or invalid X-FDPAPI-Secret header")

    run_name     = body.get("run_name", "").strip()
    benchmark_id = body.get("benchmark_id", "").strip()
    params       = body.get("params", {})
    notes        = body.get("notes")

    if not run_name:
        raise HTTPException(status_code=400, detail="'run_name' is required")
    if not benchmark_id:
        raise HTTPException(status_code=400, detail="'benchmark_id' is required")

    import json as _json
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO fdp.ensemble_runs
                        (run_name, benchmark_id, status, params, notes, loaded_by)
                    VALUES (%s, %s, 'pending', %s, %s, 'api')
                    RETURNING run_name, benchmark_id, status, params, notes, created_at
                    """,
                    (run_name, benchmark_id, _json.dumps(params), notes),
                )
                row = cur.fetchone()
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        if "duplicate key" in str(exc).lower():
            raise HTTPException(
                status_code=409,
                detail=f"Run name '{run_name}' already exists.  Choose a different name.",
            ) from exc
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return row


# ---------------------------------------------------------------------------
# POST /query  (authenticated — fdworkbench / internal use only)
# ---------------------------------------------------------------------------

@router.post(
    "/query",
    summary="Raw SQL passthrough (requires FDPAPI_SECRET header)",
)
def query(
    body: dict,
    x_fdpapi_secret: str | None = Header(default=None, alias="X-FDPAPI-Secret"),
) -> dict:
    """
    Execute arbitrary read-only SQL against the fdp schema.

    Used by fdworkbench for NLQ-generated SQL queries.  Requires the
    ``X-FDPAPI-Secret`` header to match the ``FDPAPI_SECRET`` env var.

    Request body:
        { "sql": "SELECT ...", "params": [] }

    Only SELECT statements are permitted.  The connection is opened in
    read-only transaction mode.

    Response:
        { "rows": [...], "row_count": N, "columns": [...] }
    """
    if not _secret_ok(x_fdpapi_secret):
        raise HTTPException(status_code=401, detail="Missing or invalid X-FDPAPI-Secret header")

    sql_text: str = body.get("sql", "").strip()
    params: list = body.get("params", [])

    if not sql_text:
        raise HTTPException(status_code=400, detail="Request body must include a 'sql' key")

    # Guard: only SELECT is allowed
    first_token = sql_text.split()[0].upper() if sql_text else ""
    if first_token not in ("SELECT", "WITH", "EXPLAIN"):
        raise HTTPException(
            status_code=400,
            detail=f"Only SELECT/WITH/EXPLAIN statements are permitted; got {first_token!r}",
        )

    try:
        with _connect() as conn:
            # Read-only transaction for safety
            conn.execute("SET TRANSACTION READ ONLY")
            with conn.cursor() as cur:
                cur.execute(sql_text, params)
                rows = cur.fetchall()
                columns = [desc.name for desc in cur.description] if cur.description else []
    except psycopg.Error as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"rows": rows, "row_count": len(rows), "columns": columns}
