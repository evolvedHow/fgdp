"""
Export the FDP Common Data Model to a DuckDB database for inspection
in DBeaver, DB Browser, or any SQL client.

Output: fdp/data/cdm.duckdb

Tables
------
  cdm_redistricting_waves    One row per mid-decade redistricting wave
  cdm_wave_chambers          Per-wave / per-chamber district count breakdown
  cdm_boundary_catalog       All boundary GeoJSON files in the active repo
  cdm_plan_catalog           Plans registered in app configs (map_compare, fdex)
  cdm_displacement_metrics   Results from displacement analyses (empty until run)
  cdm_schema_contracts       Schema field contracts from global.yml / schema YAMLs

Usage
-----
    uv run python scripts/export_cdm.py
    uv run python scripts/export_cdm.py --db /path/to/custom.duckdb
    uv run python scripts/export_cdm.py --repo my_workspace

DBeaver connection
------------------
    Driver: DuckDB  (install via Help > Driver Manager if missing)
    Database file: <path printed by this script>
    No username / password required.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click
import duckdb
import yaml

# Resolve package root
_SCRIPT_DIR = Path(__file__).parent
_FDP_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_FDP_ROOT))

from fdp.schema.models import RedistrictingHistory


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = """
-- Mid-decade redistricting events (Jane Branscomb, 2026-02-16)
CREATE OR REPLACE TABLE cdm_redistricting_waves (
    year                    INTEGER PRIMARY KEY,
    end_year                INTEGER,
    display_year            VARCHAR,
    label                   VARCHAR NOT NULL,
    party                   VARCHAR NOT NULL,  -- R | D | both
    reason                  VARCHAR,
    legal_context           VARCHAR,
    election_result         VARCHAR,
    total_districts_changed INTEGER NOT NULL,
    source                  VARCHAR,
    author                  VARCHAR
);

-- Per-wave / per-chamber breakdown
CREATE OR REPLACE TABLE cdm_wave_chambers (
    wave_year       INTEGER NOT NULL REFERENCES cdm_redistricting_waves(year),
    chamber         VARCHAR NOT NULL,  -- congress | house | senate
    district_count  INTEGER NOT NULL,
    all_districts   BOOLEAN NOT NULL DEFAULT FALSE,
    districts_known BOOLEAN NOT NULL DEFAULT FALSE,  -- TRUE once IDs resolved from boundary comparison
    notes           VARCHAR,
    PRIMARY KEY (wave_year, chamber)
);

-- All boundary GeoJSON files in the repo
CREATE OR REPLACE TABLE cdm_boundary_catalog (
    file_id         VARCHAR PRIMARY KEY,  -- e.g. "house/enacted_house22"
    chamber         VARCHAR NOT NULL,     -- congress | house | senate | reference
    filename        VARCHAR NOT NULL,
    full_path       VARCHAR NOT NULL,
    file_size_kb    DOUBLE,
    label           VARCHAR,              -- human-readable name if in app config
    era             VARCHAR,              -- "2022_enacted", "2024_enacted", etc. (inferred)
    in_app_config   BOOLEAN NOT NULL DEFAULT FALSE
);

-- Plans registered in app configs
CREATE OR REPLACE TABLE cdm_plan_catalog (
    plan_id     VARCHAR PRIMARY KEY,
    app         VARCHAR NOT NULL,    -- map_compare | fdex | etc.
    chamber     VARCHAR NOT NULL,
    label       VARCHAR NOT NULL,
    filename    VARCHAR NOT NULL
);

-- Displacement analysis results (populated by fdp/analysis/displacement.py)
CREATE OR REPLACE TABLE cdm_displacement_metrics (
    id                          VARCHAR PRIMARY KEY,  -- plan_a_id || '__' || plan_b_id
    plan_a_id                   VARCHAR NOT NULL,
    plan_b_id                   VARCHAR NOT NULL,
    chamber                     VARCHAR,
    wave_year                   INTEGER REFERENCES cdm_redistricting_waves(year),
    total_pop                   BIGINT,
    displaced_pop               BIGINT,
    displaced_pct               DOUBLE,
    min_required_displaced_pop  BIGINT,
    min_required_displaced_pct  DOUBLE,
    excess_displaced_pop        BIGINT,
    excess_displaced_pct        DOUBLE,  -- the key advocacy metric
    district_count              INTEGER,
    method                      VARCHAR,  -- area_weighted | centroid
    computed_at                 TIMESTAMPTZ
);

-- Schema field contracts (from global.yml + config/schema/*.yml)
CREATE OR REPLACE TABLE cdm_schema_contracts (
    data_type   VARCHAR NOT NULL,   -- boundaries | precincts | redistricting_history | etc.
    field_name  VARCHAR NOT NULL,
    required    BOOLEAN NOT NULL DEFAULT FALSE,
    field_type  VARCHAR,
    description VARCHAR,
    PRIMARY KEY (data_type, field_name)
);
"""


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _load_waves(con: duckdb.DuckDBPyConnection, history_path: Path) -> None:
    history = RedistrictingHistory.from_yaml(history_path)
    wave_rows, chamber_rows = [], []

    for w in history.waves:
        wave_rows.append({
            "year": w.year,
            "end_year": w.end_year,
            "display_year": w.display_year,
            "label": w.label,
            "party": w.party,
            "reason": w.reason,
            "legal_context": w.legal_context or None,
            "election_result": w.election_result or None,
            "total_districts_changed": w.total_districts_changed,
            "source": history.source,
            "author": history.author,
        })
        for c in w.chambers:
            chamber_rows.append({
                "wave_year": w.year,
                "chamber": c.chamber,
                "district_count": c.district_count,
                "all_districts": c.all_districts,
                "districts_known": len(c.districts) > 0,
                "notes": c.notes or None,
            })

    con.executemany(
        "INSERT INTO cdm_redistricting_waves VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [list(r.values()) for r in wave_rows],
    )
    con.executemany(
        "INSERT INTO cdm_wave_chambers VALUES (?, ?, ?, ?, ?, ?)",
        [list(r.values()) for r in chamber_rows],
    )
    print(f"  ✓ {len(wave_rows)} redistricting waves, {len(chamber_rows)} chamber records")


def _load_boundary_catalog(
    con: duckdb.DuckDBPyConnection,
    repo_root: Path,
    app_config_path: Path | None,
) -> None:
    # Build a set of filenames registered in app config
    app_filenames: dict[str, str] = {}  # filename → label
    if app_config_path and app_config_path.exists():
        with open(app_config_path) as f:
            app_cfg = yaml.safe_load(f) or {}
        for chamber, plans in (app_cfg.get("plans") or {}).items():
            for p in plans or []:
                fname = Path(p.get("file", "")).name
                app_filenames[fname] = p.get("label", "")

    chambers = ["congress", "house", "senate", "reference"]
    rows = []
    for chamber in chambers:
        boundary_dir = repo_root / "boundaries" / chamber
        if not boundary_dir.exists():
            continue
        for geojson in sorted(boundary_dir.glob("*.geojson")):
            file_id = f"{chamber}/{geojson.stem}"
            size_kb = geojson.stat().st_size / 1024
            in_app = geojson.name in app_filenames
            label = app_filenames.get(geojson.name, "")
            # Infer era from filename heuristics
            name = geojson.stem
            if "24" in name or "2024" in name:
                era = "2024_enacted"
            elif "22" in name or "2022" in name:
                era = "2022_enacted"
            elif "2123" in name:
                era = "2021-23_transition"
            elif "remedy" in name:
                era = "remedy"
            elif "prop" in name or "proposed" in name:
                era = "proposed"
            elif "cooper" in name:
                era = "cooper_proposed"
            else:
                era = None
            rows.append((
                file_id, chamber, geojson.name, str(geojson),
                round(size_kb, 1), label or None, era, in_app,
            ))

    con.executemany(
        "INSERT INTO cdm_boundary_catalog VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    print(f"  ✓ {len(rows)} boundary files catalogued")


def _load_plan_catalog(
    con: duckdb.DuckDBPyConnection,
    config_dir: Path,
) -> None:
    rows = []
    for app_yml in sorted((config_dir / "apps").glob("*.yml")):
        with open(app_yml) as f:
            cfg = yaml.safe_load(f) or {}
        app_name = cfg.get("app", {}).get("name", app_yml.stem)
        for chamber, plans in (cfg.get("plans") or {}).items():
            for p in plans or []:
                rows.append((
                    f"{app_name}/{p['id']}",
                    app_name,
                    chamber,
                    p.get("label", p["id"]),
                    p.get("file", ""),
                ))
    con.executemany(
        "INSERT INTO cdm_plan_catalog VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    print(f"  ✓ {len(rows)} plan catalog entries")


def _load_schema_contracts(
    con: duckdb.DuckDBPyConnection,
    global_yml: Path,
    schema_dir: Path,
) -> None:
    rows = []
    with open(global_yml) as f:
        global_cfg = yaml.safe_load(f) or {}

    data_schema = global_cfg.get("data_schema", {})
    for data_type, contract in data_schema.items():
        for field in contract.get("required_columns", []) + contract.get("required_fields", []):
            rows.append((data_type, field, True, None, None))
        for field in contract.get("optional_columns", []):
            rows.append((data_type, field, False, None, None))

    # Also load schema YAMLs for richer descriptions
    for schema_yml in sorted(schema_dir.glob("*.yml")):
        with open(schema_yml) as f:
            s = yaml.safe_load(f) or {}
        schema_name = s.get("schema", {}).get("name", schema_yml.stem)
        for section_key, section in s.items():
            if section_key in ("schema", "enums", "computation_methods"):
                continue
            if isinstance(section, dict):
                for category in ("required_fields", "optional_fields"):
                    for field in section.get(category, []):
                        if isinstance(field, dict):
                            rows.append((
                                schema_name,
                                field.get("name", ""),
                                category == "required_fields",
                                field.get("type"),
                                field.get("description"),
                            ))
                        else:
                            rows.append((
                                schema_name, field,
                                category == "required_fields",
                                None, None,
                            ))

    # Deduplicate
    seen = set()
    deduped = []
    for r in rows:
        key = (r[0], r[1])
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    con.executemany(
        "INSERT INTO cdm_schema_contracts VALUES (?, ?, ?, ?, ?)",
        deduped,
    )
    print(f"  ✓ {len(deduped)} schema contract rows")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command()
@click.option("--db", default=None, help="Output DuckDB file path (default: fdp/data/cdm.duckdb)")
@click.option("--repo", default="main", help="Repo name to catalogue (default: main)")
def main(db: str | None, repo: str) -> None:
    """Export the FDP Common Data Model to a DuckDB database."""
    fdp_root = _FDP_ROOT
    data_root = fdp_root / "data" / "repos" / repo
    config_dir = fdp_root / "config"
    schema_dir = config_dir / "schema"
    history_path = data_root / "history" / "redistricting_waves.yml"

    db_path = Path(db) if db else fdp_root / "data" / "cdm.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Remove stale DB so we get a clean export
    if db_path.exists():
        db_path.unlink()

    print(f"\nExporting FDP CDM → {db_path}\n")
    con = duckdb.connect(str(db_path))

    try:
        con.execute(_DDL)
        print("Creating tables...")

        if history_path.exists():
            _load_waves(con, history_path)
        else:
            print(f"  ⚠ history file not found: {history_path}")

        _load_boundary_catalog(
            con, data_root,
            config_dir / "apps" / "map_compare.yml",
        )

        _load_plan_catalog(con, config_dir)
        _load_schema_contracts(con, config_dir / "global.yml", schema_dir)

        # Summary
        print("\nTable row counts:")
        for table in [
            "cdm_redistricting_waves", "cdm_wave_chambers",
            "cdm_boundary_catalog", "cdm_plan_catalog",
            "cdm_schema_contracts", "cdm_displacement_metrics",
        ]:
            n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table:<38} {n:>4} rows")

        print(f"\n✓ Done. Open in DBeaver:")
        print(f"    Driver : DuckDB")
        print(f"    File   : {db_path.resolve()}")
        print(f"\n  Or query directly:")
        print(f"    uv run python -c \"import duckdb; con=duckdb.connect('{db_path}'); con.sql('SHOW TABLES').show()\"")

    finally:
        con.close()


if __name__ == "__main__":
    main()
