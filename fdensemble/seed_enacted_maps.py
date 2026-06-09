#!/usr/bin/env python3
"""
seed_enacted_maps.py — Pre-populate the map library with the 2023 enacted plans.

Reads the district shapefiles from fdga-chain/data/raw/, reprojects to WGS84,
strips to geometry + DISTRICT only, and writes clean GeoJSON to uploaded_maps/.
Updates catalog.json idempotently.

Run once from fdensemble/:
    cd ~/codebox/fgdp/fdensemble
    uv run --project ../fdp python seed_enacted_maps.py
"""

import json
from datetime import date
from pathlib import Path

import geopandas as gpd

FDGA_CHAIN_RAW = Path(__file__).parent.parent / "fdga-chain" / "data" / "raw"
MAPS_DIR       = Path(__file__).parent / "uploaded_maps"
CATALOG_FILE   = MAPS_DIR / "catalog.json"

MAPS_TO_SEED = [
    {
        "id":       "congress_enacted_2023",
        "label":    "2023 Enacted Congressional Districts (14 districts)",
        "shp":      FDGA_CHAIN_RAW / "Congress-2023 shape.shp",
        "chamber":  "congress",
    },
    {
        "id":       "senate_enacted_2023",
        "label":    "2023 Enacted State Senate Districts (56 districts)",
        "shp":      FDGA_CHAIN_RAW / "Senate-2023 shape file.shp",
        "chamber":  "senate",
    },
    {
        "id":       "house_enacted_2023",
        "label":    "2023 Enacted State House Districts (180 districts)",
        "shp":      FDGA_CHAIN_RAW / "House-2023 shape.shp",
        "chamber":  "house",
    },
]

def main():
    MAPS_DIR.mkdir(exist_ok=True)
    catalog: list[dict] = []
    if CATALOG_FILE.exists():
        catalog = json.loads(CATALOG_FILE.read_text())

    existing_ids = {m["id"] for m in catalog}

    for m in MAPS_TO_SEED:
        mid = m["id"]
        out_path = MAPS_DIR / f"{mid}.geojson"

        if mid in existing_ids and out_path.exists():
            print(f"  skip  {mid}  (already in catalog)")
            continue

        if not m["shp"].exists():
            print(f"  WARN  {m['shp']} not found — skipping")
            continue

        print(f"  read  {m['shp'].name} …", end=" ", flush=True)
        gdf = gpd.read_file(m["shp"])

        # Reproject NAD83 → WGS84
        gdf = gdf.to_crs("EPSG:4326")

        # Keep only district number + geometry; rename for clarity
        gdf = gdf[["DISTRICT", "geometry"]].rename(columns={"DISTRICT": "district"})
        gdf["district"] = gdf["district"].astype(int)

        # Sort by district number for tidy output
        gdf = gdf.sort_values("district").reset_index(drop=True)

        geojson_str = gdf.to_json()
        out_path.write_text(geojson_str)

        size_kb = out_path.stat().st_size / 1024
        n_features = len(gdf)
        print(f"{n_features} features  {size_kb:.0f} KB → {out_path.name}")

        entry = {
            "id":         mid,
            "label":      m["label"],
            "chamber":    m["chamber"],
            "n_districts": n_features,
            "created":    date.today().isoformat(),
        }
        if mid in existing_ids:
            catalog = [e if e["id"] != mid else entry for e in catalog]
        else:
            catalog.append(entry)

    CATALOG_FILE.write_text(json.dumps(catalog, indent=2))
    print(f"\n✓ catalog.json updated ({len(catalog)} entries)")

if __name__ == "__main__":
    main()
