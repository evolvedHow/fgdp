"""Rebuild data/semantic.duckdb from the semantic-layer SQL files.

Usage (from the fdp repo root):
    uv run --with duckdb python sql/semantic/build.py

The script imports useful analytical Parquet/JSON assets that live outside the
Wren engine mount (e.g. fdensemble/data) into self-contained tables inside
semantic.duckdb.  WrenAI only sees the `v_*` views defined in the SQL files.
"""

import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
SQL_DIR = Path(__file__).resolve().parent
TARGET = DATA / "semantic.duckdb"

FDENSEMBLE_DATA = ROOT.parent / "fdensemble" / "data"
DEMOGRAPHICS_DIR = DATA / "repos" / "main" / "demographics"


def _load_district_demographics(con: duckdb.DuckDBPyConnection) -> None:
    """Flatten the per-chamber district JSONs into a single table."""
    rows = []
    for chamber in ("congress", "house", "senate"):
        path = DEMOGRAPHICS_DIR / f"{chamber}.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        for district, metrics in data.items():
            row = {"chamber": chamber, "district": int(district)}
            row.update(metrics)
            rows.append(row)

    if not rows:
        return

    # Write rows to a temp JSONL/JSON file so DuckDB can infer the schema.
    tmp_path = TARGET.parent / ".tmp_district_demographics.json"
    tmp_path.write_text(json.dumps(rows))
    con.execute("DROP TABLE IF EXISTS raw_district_demographics")
    con.execute(
        f"CREATE TABLE raw_district_demographics AS SELECT * FROM read_json_auto('{tmp_path}')"
    )
    tmp_path.unlink()


def _load_fdensemble_parquet(con: duckdb.DuckDBPyConnection) -> None:
    """Copy fdensemble VTD Parquet files into self-contained raw tables."""
    imports = {
        "raw_vtd_demographics": FDENSEMBLE_DATA / "vtd_demographics.parquet",
        "raw_vtd_composite_lean": FDENSEMBLE_DATA / "vtd_composite.parquet",
    }
    for table_name, path in imports.items():
        con.execute(f"DROP TABLE IF EXISTS {table_name}")
        if path.exists():
            con.execute(
                f"CREATE TABLE {table_name} AS SELECT * FROM read_parquet(?)", [str(path)]
            )
            print(f"imported {table_name} ({path.name})")
        else:
            # Create an empty placeholder so the view definition does not fail.
            # The view will simply return no rows until the source file appears.
            con.execute(
                f"CREATE TABLE {table_name} (geoid VARCHAR, _placeholder BOOLEAN)"
            )
            print(f"warning: {path} not found; {table_name} is empty")


def main() -> None:
    con = duckdb.connect(str(TARGET))
    con.execute(f"ATTACH '{DATA / 'cdm.duckdb'}' AS cdm (READ_ONLY)")

    # Import external assets that the Wren engine mount cannot see directly.
    _load_fdensemble_parquet(con)
    _load_district_demographics(con)

    # Run versioned semantic SQL files.
    for sql_file in sorted(SQL_DIR.glob("*.sql")):
        con.execute(sql_file.read_text())
        print(f"applied {sql_file.name}")

    con.close()


if __name__ == "__main__":
    main()
