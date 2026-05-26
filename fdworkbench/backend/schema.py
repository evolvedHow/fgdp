"""
DuckDB in-memory database populated from FDP data files.

All tables are registered once at startup and shared (read-only) across requests.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

_conn: duckdb.DuckDBPyConnection | None = None

# Human-readable data dictionary exposed to the LLM and the /api/schema endpoint
DATA_DICTIONARY = """
AVAILABLE TABLES IN DUCKDB (use these exact table names in SQL):

────────────────────────────────────────────────────────────────────
TABLE: ensemble_congress   (~2,000 rows)
  GerryChain ReCom simulation of 2,000 random congressional plans.
  step INTEGER          — simulation step; step=0 is the GA enacted plan
  dem_seats INTEGER     — Democratic seats won
  efficiency_gap DOUBLE — partisan bias: >0 favors Republicans, <0 favors Democrats
  mean_median DOUBLE    — mean-median difference: >0 favors Republicans
  num_cut_edges INTEGER — boundary complexity (lower = simpler / more natural)
  polsby_popper_mean DOUBLE — average district compactness (0–1; 1 = perfect circle)
  polsby_popper_min  DOUBLE — least compact district
  majority_minority_districts INTEGER — districts with >50% minority VAP
  chamber VARCHAR       — always 'congress'

TABLE: ensemble_house   (~2,000 rows)
  Same schema as ensemble_congress but for 180 GA House districts, chamber='house'.

TABLE: ensemble_senate  (~2,000 rows)
  Same schema as ensemble_congress but for 56 GA Senate districts, chamber='senate'.

────────────────────────────────────────────────────────────────────
TABLE: demographics_congress  (14 rows — one per congressional district)
  ACS socioeconomic estimates per district.
  district_id INTEGER   — district number (1–14)
  chamber VARCHAR       — 'congress'
  median_income DOUBLE  — median household income ($)
  pct_poverty DOUBLE    — fraction below poverty line (0.0–1.0)
  poverty_count INTEGER
  pct_bachelors_plus DOUBLE — fraction with bachelor's degree or higher
  bachelors_plus_count INTEGER
  pct_male DOUBLE / pct_female DOUBLE
  pct_married_family DOUBLE — married family households fraction
  married_hh_count INTEGER
  pct_single_parent DOUBLE
  single_parent_count INTEGER
  pct_no_vehicle DOUBLE — households without a vehicle, fraction
  no_vehicle_count INTEGER
  pct_uninsured DOUBLE  — uninsured population fraction
  uninsured_count INTEGER
  pct_unemployed DOUBLE — unemployed labor force fraction
  unemployed_count INTEGER
  labor_force_count INTEGER

TABLE: demographics_house   (180 rows)  — same schema, chamber='house'
TABLE: demographics_senate  (56 rows)   — same schema, chamber='senate'

NOTE: demographics_* tables do NOT contain racial/VAP data. For Black VAP, Hispanic VAP,
      and total population by district, use the vap_districts table below.

────────────────────────────────────────────────────────────────────
TABLE: vap_districts  (250 rows — per chamber×district)
  Precinct-level Census data aggregated to district level from GerryChain graph files.
  chamber VARCHAR       — 'congress' | 'house' | 'senate'
  district_id INTEGER   — district number
  total_pop INTEGER     — 2020 Census total population (all persons)
  total_vap INTEGER     — Total Voting Age Population (18+)
  bvap INTEGER          — Black Voting Age Population
  dem_votes INTEGER     — 2020 presidential Democratic votes (Biden)
  rep_votes INTEGER     — 2020 presidential Republican votes (Trump)
  pct_bvap DOUBLE       — BVAP / total_vap (Black share of VAP, 0.0–1.0)
  dem_share DOUBLE      — dem_votes / (dem_votes + rep_votes)
  NOTE: Hispanic VAP is NOT available in this dataset. BVAP is the only racial VAP metric.

────────────────────────────────────────────────────────────────────
TABLE: ensemble_meta  (3 rows — one per chamber)
  Metadata about each GerryChain simulation run.
  chamber VARCHAR
  steps INTEGER              — number of plans simulated
  num_districts INTEGER
  total_population INTEGER   — GA 2020 Census total population
  epsilon DOUBLE             — population deviation tolerance (e.g. 0.07 = ±7%)
  enacted_dem_seats INTEGER  — Democratic seats in the enacted plan
  enacted_efficiency_gap DOUBLE
  enacted_mean_median DOUBLE
  enacted_polsby_popper_mean DOUBLE

────────────────────────────────────────────────────────────────────
TABLE: ensemble_stability  (varies — ~3 × steps rows)
  Per-step Democratic seat probability from the ensemble walk.
  chamber VARCHAR
  step INTEGER
  probability DOUBLE   — fraction of plans at this step with a majority of Dem seats

────────────────────────────────────────────────────────────────────
TABLE: lrdb  (441 rows — GA counties, cities, school boards)
  Local Redistricting Database tracking 2021 redistricting processes.
  name VARCHAR          — jurisdiction name (e.g. 'Fulton County', 'Atlanta')
  type VARCHAR          — 'County Commission' | 'City Council' | 'School Board'
  id DOUBLE             — FIPS-based jurisdiction ID
  pop20 DOUBLE          — 2020 Census population
  participation_w VARCHAR — 'yes'/'no'/null — had public participation
  guidelines_w VARCHAR  — had written redistricting guidelines
  gga_adjust_w VARCHAR  — GA legislature overrode the locally-drawn map
  requirements_w VARCHAR — had written requirements
  requirements_n VARCHAR — requirements description text
  guide_n VARCHAR       — guidelines description text
  dist_type VARCHAR     — district structure (e.g. '6 single-member districts')
  election_type VARCHAR — election method description
  date_loc_approve VARCHAR — date map was approved locally
  summary VARCHAR       — free-text summary of redistricting process
  shared_with VARCHAR   — if the map is shared with another governing body
  redist_coord VARCHAR  — who managed the redistricting process
  draft1_drew VARCHAR   — who drew the first draft map
  local_approval VARCHAR — who reviewed the map
  map_approval VARCHAR  — who had final approval
  local_vote VARCHAR    — vote description
  controversy VARCHAR   — description of any controversy
  controvery_w VARCHAR  — 'yes'/'no' — had controversy (note: field name has typo)
  gga_adjust VARCHAR    — description of state override
  nonpartisan_w VARCHAR — 'yes'/'no' — nonpartisan process
  prison_gerrymnadering VARCHAR — prison gerrymandering notes
  atlarge_w VARCHAR     — 'yes'/'no' — at-large (not district-based) election
  complete_w VARCHAR    — 'yes'/'no' — redistricting complete

────────────────────────────────────────────────────────────────────
DOMAIN GLOSSARY:
  Efficiency Gap     — measures wasted votes; a standard gerrymandering test
  Mean-Median        — another partisan bias metric; >0.05 is considered significant
  Polsby-Popper      — compactness score; below 0.15 often indicates manipulation
  Majority-Minority  — VRA-required districts protecting minority voting power
  BVAP               — Black Voting Age Population
  ReCom              — GerryChain's Recombination algorithm (random spanning trees)
  Enacted Plan       — the legally-adopted district map (step=0 in ensemble tables)
  Ensemble           — thousands of randomly-generated alternative maps for comparison
  Cut Edges          — precinct adjacency edges severed by district boundaries
"""


def _fdp_data_root() -> Path:
    root = os.environ.get("FDP_ROOT", "../fdp")
    return (Path(__file__).parent.parent / root).resolve() / "data/repos/main"


def build_connection() -> duckdb.DuckDBPyConnection:
    data = _fdp_data_root()
    conn = duckdb.connect(":memory:")

    # Ensemble parquets — DuckDB reads these natively
    for chamber in ("congress", "house", "senate"):
        p = data / f"ensembles/{chamber}_ensemble.parquet"
        if p.exists():
            conn.execute(f"""
                CREATE OR REPLACE VIEW ensemble_{chamber} AS
                SELECT *, '{chamber}' AS chamber
                FROM read_parquet('{p}')
            """)
            logger.info("Loaded ensemble_%s (%s)", chamber, p)
        else:
            logger.warning("ensemble_%s parquet not found at %s", chamber, p)

    # Demographics JSON → DataFrames → DuckDB tables
    _demo_dfs: dict[str, pd.DataFrame] = {}
    for chamber in ("congress", "house", "senate"):
        jp = data / f"demographics/{chamber}.json"
        if jp.exists():
            with open(jp) as f:
                raw = json.load(f)
            rows = [{"district_id": int(k), "chamber": chamber, **v} for k, v in raw.items()]
            df = pd.DataFrame(rows)
            _demo_dfs[chamber] = df
            conn.register(f"demographics_{chamber}", df)
            logger.info("Loaded demographics_%s (%d districts)", chamber, len(df))

    # Ensemble meta JSON → table
    meta_rows = []
    for chamber in ("congress", "house", "senate"):
        mp = data / f"ensembles/{chamber}_meta.json"
        if mp.exists():
            with open(mp) as f:
                m = json.load(f)
            enacted = m.get("enacted_metrics", {})
            meta_rows.append({
                "chamber": chamber,
                "steps": m.get("steps"),
                "num_districts": m.get("num_districts"),
                "total_population": m.get("total_population"),
                "epsilon": m.get("epsilon"),
                "enacted_dem_seats": enacted.get("dem_seats"),
                "enacted_efficiency_gap": enacted.get("efficiency_gap"),
                "enacted_mean_median": enacted.get("mean_median"),
                "enacted_polsby_popper_mean": enacted.get("polsby_popper_mean"),
            })
    if meta_rows:
        _meta_df = pd.DataFrame(meta_rows)
        conn.register("ensemble_meta", _meta_df)

    # Ensemble stability JSON → table
    stability_rows = []
    for chamber in ("congress", "house", "senate"):
        sp = data / f"ensembles/{chamber}_stability.json"
        if sp.exists():
            with open(sp) as f:
                stab = json.load(f)
            for step_str, prob in stab.items():
                stability_rows.append({"chamber": chamber, "step": int(step_str), "probability": prob})
    if stability_rows:
        _stab_df = pd.DataFrame(stability_rows)
        conn.register("ensemble_stability", _stab_df)

    # VAP by district — aggregated from graph node precincts
    _vap_rows = []
    for chamber, dist_col, graph_name in [
        ("congress", "CDIST", "ga_congress"),
        ("house",    "HDIST", "ga_house"),
        ("senate",   "SDIST", "ga_senate"),
    ]:
        gp = data / f"graphs/{graph_name}.json"
        if not gp.exists():
            continue
        with open(gp) as f:
            graph = json.load(f)
        nodes = graph.get("nodes", [])
        by_district: dict[str, dict] = {}
        for node in nodes:
            dist = node.get(dist_col)
            if dist is None:
                continue
            d = by_district.setdefault(str(dist), {"bvap": 0, "hvap": 0, "totpop": 0, "dem": 0, "rep": 0})
            d["bvap"]   += node.get("BVAP", 0) or 0
            d["hvap"]   += node.get("HVAP", 0) or 0
            d["totpop"] += node.get("TOTPOP", 0) or 0
            d["dem"]    += node.get("DEM_VOTES", 0) or 0
            d["rep"]    += node.get("REP_VOTES", 0) or 0
        for dist_str, v in by_district.items():
            total = v["totpop"] or 1
            votes = (v["dem"] + v["rep"]) or 1
            try:
                dist_id = int(dist_str)
            except (ValueError, TypeError):
                continue
            vap = v["hvap"] or total   # HVAP in this dataset = total Voting Age Population
            _vap_rows.append({
                "chamber":    chamber,
                "district_id": dist_id,
                "total_pop":  v["totpop"],
                "total_vap":  vap,
                "bvap":       v["bvap"],
                "dem_votes":  v["dem"],
                "rep_votes":  v["rep"],
                "pct_bvap":   round(v["bvap"] / vap, 4) if vap else 0,
                "dem_share":  round(v["dem"] / votes, 4),
            })
    if _vap_rows:
        _vap_df = pd.DataFrame(_vap_rows)
        conn.register("vap_districts", _vap_df)
        logger.info("Loaded vap_districts (%d rows)", len(_vap_df))

    # LRDB GeoJSON properties (geometry stripped)
    lrdb_path = data / "lrdb/lrdb_web_20260216.geojson"
    if lrdb_path.exists():
        with open(lrdb_path) as f:
            geo = json.load(f)
        props = [feat["properties"] for feat in geo.get("features", []) if feat.get("properties")]
        if props:
            _lrdb_df = pd.DataFrame(props)
            conn.register("lrdb", _lrdb_df)
            logger.info("Loaded lrdb (%d jurisdictions)", len(_lrdb_df))

    return conn


def get_conn() -> duckdb.DuckDBPyConnection:
    global _conn
    if _conn is None:
        _conn = build_connection()
    return _conn


def list_tables() -> list[str]:
    conn = get_conn()
    rows = conn.execute("SHOW TABLES").fetchall()
    return [r[0] for r in rows]
