#!/usr/bin/env python3
"""
enrich_plan_geojson.py — Add 2024 election data to district plan GeoJSONs.

For every district plan GeoJSON in data/repos/main/boundaries/, computes
district-level election shares from raw VTD vote counts and writes or refreshes:

  p24_pct_dem  — 2024 President D two-party share  (NEW)
  partisan     — updated 6-election simple mean (previously 5-election)

Also refreshes the existing election fields to stay in sync:
  g18_pct_dem, p20_pct_dem, r21_pct_dem, g22_pct_dem, s22_pct_dem

Method: for each plan, spatially join VTD centroids to district polygons to get
VTD→district assignment, then compute district shares as:
  dem_pct = sum(D_votes across VTDs) / sum(D_votes + R_votes across VTDs)
This is the same as the existing values in the GeoJSONs.

partisan = simple unweighted mean of the 6 election shares per district.

Usage:
    uv run --project fdp python fdp/scripts/enrich_plan_geojson.py
    uv run --project fdp python fdp/scripts/enrich_plan_geojson.py --dry-run
    uv run --project fdp python fdp/scripts/enrich_plan_geojson.py --chamber congress

After running, sync to fdex:
    bash fdex/scripts/sync_data.sh
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import shape

_SCRIPT_DIR = Path(__file__).resolve().parent
_DATA_ROOT  = _SCRIPT_DIR.parent / "data/repos/main"
_VTD_DIR    = _DATA_ROOT / "vtd"
_BOUNDARIES = _DATA_ROOT / "boundaries"

CHAMBERS = ["congress", "senate", "house"]

# election id → (GeoJSON property, D vote col, R vote col, parquet filename)
ELECTIONS: list[tuple[str, str, str, str]] = [
    ("g18", "g18_pct_dem", "G18GOVDABR", "G18GOVRKEM", "vtd_elections_2018_governor.parquet"),
    ("p20", "p20_pct_dem", "G20PREDBID", "G20PRERTRU", "vtd_elections_2020_president.parquet"),
    ("r21", "r21_pct_dem", "R21USSDWAR", "R21USSRLOE", "vtd_elections_2021_runoff.parquet"),
    ("g22", "g22_pct_dem", "G22GOVDABR", "G22GOVRKEM", "ga-2022-general-election-vtd.parquet"),
    ("s22", "s22_pct_dem", "G22USSDWAR", "G22USSRWAL", "ga-2022-general-election-vtd.parquet"),
    ("p24", "p24_pct_dem", "G24PREDHAR", "G24PRERTRU", "ga-2024-president-election-vtd.parquet"),
]


def load_vtd_votes() -> pd.DataFrame:
    """
    Build one VTD-level DataFrame with raw D and R vote columns for all 6 elections.
    Uses VTD centroid coords from vtd_composite.parquet.
    """
    # Centroids for spatial join
    composite = pd.read_parquet(_VTD_DIR / "vtd_composite.parquet",
                                columns=["GEOID20", "centroid_lat", "centroid_lon"])

    # Load each election parquet, keep only GEOID20 + relevant vote cols
    seen_parquets: dict[str, pd.DataFrame] = {}
    election_frames: list[pd.DataFrame] = []

    for (eid, geo_prop, d_col, r_col, parquet_name) in ELECTIONS:
        path = _VTD_DIR / parquet_name
        if not path.exists():
            sys.exit(f"ERROR: {path} not found")
        if parquet_name not in seen_parquets:
            seen_parquets[parquet_name] = pd.read_parquet(path)
        df = seen_parquets[parquet_name]
        needed = ["GEOID20", d_col, r_col]
        missing = [c for c in needed if c not in df.columns]
        if missing:
            sys.exit(f"ERROR: {parquet_name} missing columns: {missing}")
        sub = df[needed].copy().rename(columns={d_col: f"d_{eid}", r_col: f"r_{eid}"})
        election_frames.append(sub)

    # Merge all elections onto composite (left join — composite has all 2698 VTDs)
    vtd = composite.copy()
    for sub in election_frames:
        vtd = vtd.merge(sub, on="GEOID20", how="left")

    print(f"  Loaded vote data: {len(vtd):,} VTDs × {len(vtd.columns)} columns")
    return vtd


def load_vtd_centroids(vtd: pd.DataFrame) -> gpd.GeoDataFrame:
    geometry = gpd.points_from_xy(vtd["centroid_lon"], vtd["centroid_lat"])
    gdf = gpd.GeoDataFrame(vtd, geometry=geometry, crs="EPSG:4326")
    missing = gdf["centroid_lat"].isna().sum()
    if missing:
        print(f"  WARNING: {missing} VTDs have no centroid — they'll be unmatched")
    return gdf


def enrich_geojson(path: Path, vtd_gdf: gpd.GeoDataFrame, dry_run: bool) -> int:
    """
    Enrich one district plan GeoJSON.  Returns number of districts updated.
    """
    with open(path) as f:
        gj = json.load(f)

    features = gj.get("features", [])
    if not features:
        return 0

    # Build district GeoDataFrame
    district_rows = []
    for feat in features:
        props = feat.get("properties") or {}
        raw = props.get("district") or props.get("DISTRICT")
        if raw is None:
            continue
        district_rows.append({"district": int(float(raw)), "geometry": shape(feat["geometry"])})

    if not district_rows:
        return 0

    districts_gdf = gpd.GeoDataFrame(district_rows, crs="EPSG:4326")

    # Spatial join: VTD centroid → district polygon
    joined = gpd.sjoin(vtd_gdf, districts_gdf[["district", "geometry"]],
                       how="left", predicate="within")

    # Nearest-neighbour fallback for any edge-case unmatched VTDs
    unmatched_mask = joined["district"].isna()
    if unmatched_mask.any():
        unmatched = joined[unmatched_mask].drop(columns=["index_right", "district"])
        nearest = gpd.sjoin_nearest(unmatched, districts_gdf[["district", "geometry"]],
                                    how="left")
        joined.loc[unmatched_mask, "district"] = nearest["district"].values

    joined = joined[joined["district"].notna()].copy()
    joined["district"] = joined["district"].astype(int)

    # Aggregate raw vote sums to district level
    vote_cols = [f"d_{eid}" for eid, *_ in ELECTIONS] + [f"r_{eid}" for eid, *_ in ELECTIONS]
    agg = joined.groupby("district")[vote_cols].sum()

    # Compute per-election dem_pct = sum(D) / (sum(D) + sum(R))
    district_stats: dict[int, dict[str, float]] = {}
    for dist_id, row in agg.iterrows():
        stats: dict[str, float] = {}
        for (eid, geo_prop, *_) in ELECTIONS:
            d = float(row[f"d_{eid}"])
            r = float(row[f"r_{eid}"])
            total = d + r
            stats[geo_prop] = round(d / total, 4) if total > 0 else float("nan")

        el_vals = [v for v in stats.values() if not np.isnan(v)]
        stats["partisan"] = round(float(np.mean(el_vals)), 4) if el_vals else float("nan")
        district_stats[int(dist_id)] = stats

    # Patch features
    updated = 0
    for feat in features:
        props = feat.get("properties") or {}
        raw = props.get("district") or props.get("DISTRICT")
        if raw is None:
            continue
        dist_id = int(float(raw))
        stat = district_stats.get(dist_id)
        if stat is None:
            continue
        for prop, val in stat.items():
            if not (isinstance(val, float) and np.isnan(val)):
                feat["properties"][prop] = val
        updated += 1

    if not dry_run:
        with open(path, "w") as f:
            json.dump(gj, f, separators=(",", ":"))

    return updated


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="Compute but do not write any files")
    ap.add_argument("--chamber", choices=CHAMBERS,
                    help="Restrict to one chamber (default: all)")
    args = ap.parse_args()

    missing = [f for _, _, _, _, f in ELECTIONS
               if not (_VTD_DIR / f).exists()]
    if missing:
        seen = set()
        for f in missing:
            if f not in seen:
                print(f"ERROR: {_VTD_DIR / f} not found")
                seen.add(f)
        sys.exit(1)

    print("=== Enriching district plan GeoJSONs with 2024 election data ===")
    if args.dry_run:
        print("  [DRY RUN — no files will be written]\n")

    vtd = load_vtd_votes()
    vtd_gdf = load_vtd_centroids(vtd)

    chambers = [args.chamber] if args.chamber else CHAMBERS
    total_files = total_districts = 0

    for chamber in chambers:
        chamber_dir = _BOUNDARIES / chamber
        if not chamber_dir.exists():
            print(f"\nWARNING: {chamber_dir} not found — skipping")
            continue
        geojson_files = sorted(chamber_dir.glob("*.geojson"))
        print(f"\n── {chamber.upper()} ({len(geojson_files)} files) ─────────────────────")
        for path in geojson_files:
            n = enrich_geojson(path, vtd_gdf, args.dry_run)
            verb = "would update" if args.dry_run else "updated"
            prefix = "[DRY]" if args.dry_run else "✓"
            print(f"  {prefix}  {path.name}  ({verb} {n} districts)")
            total_files += 1
            total_districts += n

    verb = "would have been" if args.dry_run else "were"
    print(f"\n{'DRY RUN complete' if args.dry_run else 'Done'}: "
          f"{total_files} files, {total_districts} district features {verb} enriched.")

    if not args.dry_run:
        print("\nNext: sync updated GeoJSONs to fdex/")
        print("  bash fdex/scripts/sync_data.sh")


if __name__ == "__main__":
    main()
