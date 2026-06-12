"""
Build city integrity lookup files for fdensemble.

Outputs:
  fdensemble/data/city_integrity_lookup.parquet  — city metadata (muni_id, name, total_pop)
  fdensemble/input_data/{run_id}_city_integrity.json  — per-run enacted split counts

Run from fgdp/ root:
  uv run --project fdp python fdp/scripts/build_city_integrity_lookup.py
"""
import json
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow.parquet as pq
import pyarrow.compute as pc

_REPO_ROOT = Path(__file__).resolve().parents[2]   # fgdp/
_VTD_MUNI   = _REPO_ROOT / "fdensemble/data/vtd_muni.parquet"
_VTD_DEMO   = _REPO_ROOT / "fdensemble/data/vtd_demographics.parquet"
_PLACES_GEO = _REPO_ROOT / "fdp/data/repos/main/boundaries/reference/places_2020data.geojson"
_LOOKUP_OUT = _REPO_ROOT / "fdensemble/data/city_integrity_lookup.parquet"
_INPUT_DATA = _REPO_ROOT / "fdensemble/input_data"
_ENSEMBLE   = _REPO_ROOT / "fdp/data/repos/main/ensemble"


# ── Step 1: Build city metadata lookup ───────────────────────────────────────

def build_city_lookup() -> pd.DataFrame:
    """Return DataFrame (muni_id, name, total_pop) for named GA municipalities."""
    # Municipality populations: sum VTD pops by muni_id
    conn = duckdb.connect()
    city_pops = conn.execute("""
        SELECT m.muni_id, SUM(d.pop) AS total_pop
        FROM read_parquet(?) m
        JOIN read_parquet(?) d ON m.geoid = d.geoid
        GROUP BY m.muni_id
    """, [str(_VTD_MUNI), str(_VTD_DEMO)]).df()

    # City names from places GeoJSON: GEOCODE = "13" + 5-digit muni_id
    features = json.loads(_PLACES_GEO.read_text())["features"]
    names = {}
    for f in features:
        p = f["properties"]
        geocode = str(p.get("GEOCODE", ""))
        name    = p.get("PLACE", "")
        if geocode.startswith("13") and len(geocode) == 7:
            muni_id = int(geocode[2:])
            names[muni_id] = name

    name_df = pd.DataFrame(
        [(mid, nm) for mid, nm in names.items()],
        columns=["muni_id", "name"],
    )

    # Inner join: only keep cities with both a name and VTD population data
    lookup = name_df.merge(city_pops, on="muni_id", how="inner")
    lookup = lookup.sort_values("total_pop", ascending=False).reset_index(drop=True)
    print(f"  City lookup: {len(lookup)} named municipalities")
    return lookup


# ── Step 2: Compute enacted plan city splits for one run ─────────────────────

def _enacted_draw(source: str) -> int:
    return 0 if source == "alarm" else 1


def compute_run_integrity(run_id: str, source: str, lookup: pd.DataFrame) -> dict | None:
    """
    Read enacted draw from plans parquet, compute per-city district counts.
    Returns list of city records with split info, or None if parquet not found.
    """
    plans_path = _ENSEMBLE / f"{run_id}_plans.parquet"
    if not plans_path.exists():
        print(f"  SKIP {run_id}: plans parquet not found at {plans_path}")
        return None

    draw = _enacted_draw(source)
    print(f"  Loading enacted draw={draw} from {plans_path.name}…")

    # Read only the enacted draw (pyarrow predicate pushdown)
    tbl = pq.read_table(plans_path, columns=["draw", "geoid", "district"],
                        filters=[("draw", "==", draw)])
    print(f"    {len(tbl):,} VTD rows for enacted draw")

    # Join vtd_muni, count distinct districts per municipality
    conn = duckdb.connect()
    conn.register("enacted", tbl.to_pandas())
    conn.register("vtd_muni", pd.read_parquet(_VTD_MUNI))

    city_splits = conn.execute("""
        SELECT m.muni_id,
               COUNT(DISTINCT e.district) AS n_districts,
               LIST(DISTINCT CAST(e.district AS VARCHAR)) AS district_list
        FROM vtd_muni m
        JOIN enacted e ON m.geoid = e.geoid
        GROUP BY m.muni_id
    """).df()

    # Join with lookup (name + pop)
    merged = lookup.merge(city_splits, on="muni_id", how="inner")
    merged = merged.sort_values("total_pop", ascending=False)

    cities = []
    for _, row in merged.iterrows():
        cities.append({
            "muni_id":    int(row["muni_id"]),
            "name":       row["name"],
            "pop":        int(row["total_pop"]),
            "n_districts": int(row["n_districts"]),
            "is_split":   bool(row["n_districts"] > 1),
            "districts":  sorted([int(d) for d in row["district_list"]]),
        })

    split_count = sum(1 for c in cities if c["is_split"])
    print(f"    {split_count} of {len(cities)} named cities split in enacted plan")
    return {"source": source, "enacted_draw": draw, "cities": cities}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Building city integrity lookup…")
    lookup = build_city_lookup()

    # Write shared lookup parquet
    import pyarrow as pa
    table = pa.Table.from_pandas(lookup)
    pq.write_table(table, _LOOKUP_OUT, compression="snappy")
    print(f"  Written: {_LOOKUP_OUT}")

    # Process each scorecard in input_data/
    scorecard_paths = sorted(_INPUT_DATA.glob("*_scorecard.json"))
    if not scorecard_paths:
        print("No scorecard files found in fdensemble/input_data/")
        return

    for sc_path in scorecard_paths:
        run_id = sc_path.stem.replace("_scorecard", "")
        sc     = json.loads(sc_path.read_text())
        run    = sc.get("run", {})
        source = run.get("source", "gerrychain")

        print(f"\nProcessing {run_id} (source={source})…")
        result = compute_run_integrity(run_id, source, lookup)
        if result is None:
            continue

        out_path = _INPUT_DATA / f"{run_id}_city_integrity.json"
        out_path.write_text(json.dumps(result, separators=(",", ":")))
        print(f"  Written: {out_path.name}")

    print("\nDone.")


if __name__ == "__main__":
    main()
