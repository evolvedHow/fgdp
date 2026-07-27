#!/usr/bin/env python3
"""
enrich_plan_geojson.py — Score district plan GeoJSONs against six elections.

For every district plan GeoJSON in data/repos/main/boundaries/, computes
district-level two-party shares and writes:

  g18_pct_dem, p20_pct_dem, r21_pct_dem, g22_pct_dem, s22_pct_dem, p24_pct_dem
  partisan     — simple unweighted mean of the six shares

Method — block-weighted assignment
----------------------------------
Votes are aggregated from 2020 Census *blocks*, assigned to districts by the
Census-published internal point (a coordinate guaranteed to fall inside the
block).

This replaces the previous VTD-centroid method, which assigned each VTD whole
to whichever district contained its centroid. VTDs are far larger than a state
house district in rural Georgia, so that method could starve a district almost
entirely: HD-177 of the enacted house map captured 1 VTD and 1,710 votes
against a voting-age population of 46,014, putting its 2018 share at 0.880 D
where the source data says 0.593. Blocks are small enough that assignment error
is negligible, and split VTDs are apportioned rather than winner-take-all.

Vote sources differ by cycle:

  2022 (governor, US Senate) and 2024 (president)
      Real block-level counts from data/repos/main/block/. No estimation.

  2018 (governor), 2020 (president), 2021 (US Senate runoff)
      Only published at VTD level, so each VTD's votes are distributed across
      its blocks in proportion to VAP_MOD (voting-age population excluding
      correctional facilities). Blocks nest perfectly inside 2020 VTDs, so this
      is exact at the VTD level and only approximates *within* a split VTD.

Usage:
    uv run python scripts/enrich_plan_geojson.py
    uv run python scripts/enrich_plan_geojson.py --dry-run
    uv run python scripts/enrich_plan_geojson.py --chamber congress

Prerequisites:
    uv run python scripts/build_block_points.py   # writes block_points.parquet

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
_BLOCK_DIR  = _DATA_ROOT / "block"
_BOUNDARIES = _DATA_ROOT / "boundaries"

CHAMBERS = ["congress", "senate", "house"]

BLOCK_POINTS = _BLOCK_DIR / "block_points.parquet"
BLOCK_VTD    = _VTD_DIR / "block_vtd_lookup.parquet"

# Elections published at block level — used as-is.
# election id → (GeoJSON property, D column, R column, block parquet)
BLOCK_ELECTIONS: list[tuple[str, str, str, str, str]] = [
    ("g22", "g22_pct_dem", "G22GOVDABR", "G22GOVRKEM", "ga-2022-general-election-block.parquet"),
    ("s22", "s22_pct_dem", "G22USSDWAR", "G22USSRWAL", "ga-2022-general-election-block.parquet"),
    ("p24", "p24_pct_dem", "G24PREDHAR", "G24PRERTRU", "ga-2024-general-election-block.parquet"),
]

# Elections published only at VTD level — disaggregated to blocks by VAP_MOD.
VTD_ELECTIONS: list[tuple[str, str, str, str, str]] = [
    ("g18", "g18_pct_dem", "G18GOVDABR", "G18GOVRKEM", "vtd_elections_2018_governor.parquet"),
    ("p20", "p20_pct_dem", "G20PREDBID", "G20PRERTRU", "vtd_elections_2020_president.parquet"),
    ("r21", "r21_pct_dem", "R21USSDWAR", "R21USSRLOE", "vtd_elections_2021_runoff.parquet"),
]

# Canonical display order, oldest first.
ELECTIONS = [
    ("g18", "g18_pct_dem"),
    ("p20", "p20_pct_dem"),
    ("r21", "r21_pct_dem"),
    ("g22", "g22_pct_dem"),
    ("s22", "s22_pct_dem"),
    ("p24", "p24_pct_dem"),
]

# VAP_MOD is identical across the block election files (same RDH source); read
# it from whichever one we load first.
_VAP_SOURCE = "ga-2024-general-election-block.parquet"


def _require(path: Path) -> Path:
    if not path.exists():
        sys.exit(f"ERROR: {path} not found")
    return path


def load_block_votes() -> pd.DataFrame:
    """
    Build one block-level frame carrying D and R vote columns for all six
    elections, plus the Census internal point for each block.
    """
    points = pd.read_parquet(_require(BLOCK_POINTS))
    points["GEOID20"] = points["GEOID20"].astype(str)

    vap = pd.read_parquet(_require(_BLOCK_DIR / _VAP_SOURCE), columns=["GEOID20", "VAP_MOD"])
    vap["GEOID20"] = vap["GEOID20"].astype(str)

    blocks = points.merge(vap, on="GEOID20", how="left")
    missing_vap = int(blocks["VAP_MOD"].isna().sum())
    if missing_vap:
        print(f"  WARNING: {missing_vap} blocks have no VAP_MOD — treated as 0")
        blocks["VAP_MOD"] = blocks["VAP_MOD"].fillna(0)

    # ── Block-level elections: real counts, nothing to estimate ──────────
    cache: dict[str, pd.DataFrame] = {}
    for eid, _prop, d_col, r_col, parquet in BLOCK_ELECTIONS:
        if parquet not in cache:
            cache[parquet] = pd.read_parquet(_require(_BLOCK_DIR / parquet))
        df = cache[parquet]
        for col in (d_col, r_col):
            if col not in df.columns:
                sys.exit(f"ERROR: {parquet} missing column {col}")
        sub = df[["GEOID20", d_col, r_col]].copy()
        sub["GEOID20"] = sub["GEOID20"].astype(str)
        sub = sub.rename(columns={d_col: f"d_{eid}", r_col: f"r_{eid}"})
        blocks = blocks.merge(sub, on="GEOID20", how="left")

    # ── VTD-level elections: distribute across blocks by VAP_MOD ─────────
    lookup = pd.read_parquet(_require(BLOCK_VTD))
    lookup = lookup.rename(columns={"block_GEOID20": "GEOID20", "vtd_GEOID20": "vtd"})
    lookup["GEOID20"] = lookup["GEOID20"].astype(str)
    blocks = blocks.merge(lookup, on="GEOID20", how="left")

    orphans = int(blocks["vtd"].isna().sum())
    if orphans:
        orphan_vap = int(blocks.loc[blocks["vtd"].isna(), "VAP_MOD"].sum())
        print(f"  NOTE: {orphans} blocks have no VTD ({orphan_vap:,} VAP) — "
              "they receive no 2018/2020/2021 votes")

    # Each block's share of its VTD's voting-age population.
    vtd_vap = blocks.groupby("vtd")["VAP_MOD"].transform("sum")
    with np.errstate(invalid="ignore", divide="ignore"):
        blocks["vap_share"] = np.where(vtd_vap > 0, blocks["VAP_MOD"] / vtd_vap, 0.0)

    for eid, _prop, d_col, r_col, parquet in VTD_ELECTIONS:
        df = pd.read_parquet(_require(_VTD_DIR / parquet))
        for col in (d_col, r_col):
            if col not in df.columns:
                sys.exit(f"ERROR: {parquet} missing column {col}")
        sub = df[["GEOID20", d_col, r_col]].copy()
        sub["GEOID20"] = sub["GEOID20"].astype(str)
        sub = sub.rename(columns={"GEOID20": "vtd", d_col: f"vd_{eid}", r_col: f"vr_{eid}"})
        blocks = blocks.merge(sub, on="vtd", how="left")
        blocks[f"d_{eid}"] = blocks[f"vd_{eid}"].fillna(0) * blocks["vap_share"]
        blocks[f"r_{eid}"] = blocks[f"vr_{eid}"].fillna(0) * blocks["vap_share"]

        # Disaggregation must conserve votes: what we spread across blocks has
        # to equal what the VTD file reported, minus any VTD with zero VAP.
        for side, src in (("d", f"vd_{eid}"), ("r", f"vr_{eid}")):
            spread = blocks[f"{side}_{eid}"].sum()
            total = sub[src].sum()
            if total > 0 and abs(spread - total) / total > 0.001:
                print(f"  WARNING: {eid} {side} disaggregation lost "
                      f"{total - spread:,.0f} of {total:,.0f} votes")
        blocks = blocks.drop(columns=[f"vd_{eid}", f"vr_{eid}"])

    vote_cols = [f"{s}_{eid}" for eid, _ in ELECTIONS for s in ("d", "r")]
    blocks[vote_cols] = blocks[vote_cols].fillna(0)

    print(f"  Loaded {len(blocks):,} blocks; statewide two-party totals:")
    for eid, prop in ELECTIONS:
        d, r = blocks[f"d_{eid}"].sum(), blocks[f"r_{eid}"].sum()
        src = "block" if any(e[0] == eid for e in BLOCK_ELECTIONS) else "VTD→block"
        print(f"    {prop:14s} D {d:>10,.0f}  R {r:>10,.0f}   ({src})")

    return blocks[["GEOID20", "lat", "lon"] + vote_cols]


def to_geo(blocks: pd.DataFrame) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        blocks,
        geometry=gpd.points_from_xy(blocks["lon"], blocks["lat"]),
        crs="EPSG:4326",
    )


def enrich_geojson(path: Path, block_gdf: gpd.GeoDataFrame, dry_run: bool) -> int:
    """Enrich one district plan GeoJSON. Returns number of districts updated."""
    with open(path) as f:
        gj = json.load(f)

    features = gj.get("features", [])
    if not features:
        return 0

    rows = []
    for feat in features:
        props = feat.get("properties") or {}
        raw = props.get("district")
        if raw is None:
            raw = props.get("DISTRICT")
        if raw is None:
            continue
        rows.append({"district": int(float(raw)), "geometry": shape(feat["geometry"])})
    if not rows:
        return 0

    districts_gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")

    joined = gpd.sjoin(block_gdf, districts_gdf[["district", "geometry"]],
                       how="left", predicate="within")
    # A block whose internal point lands just outside the plan's outline (river
    # and coastline precision) falls back to the nearest district.
    unmatched = joined["district"].isna()
    if unmatched.any():
        # Project before the distance search — nearest-neighbour on lat/lon
        # degrees is not a metric distance.
        fix = joined[unmatched].drop(columns=["index_right", "district"]).to_crs(3857)
        nearest = gpd.sjoin_nearest(fix, districts_gdf[["district", "geometry"]].to_crs(3857),
                                    how="left")
        # sjoin_nearest can emit ties; keep the first match per block.
        nearest = nearest[~nearest.index.duplicated(keep="first")]
        joined.loc[unmatched, "district"] = nearest["district"]

    joined = joined[joined["district"].notna()].copy()
    joined["district"] = joined["district"].astype(int)

    vote_cols = [f"{s}_{eid}" for eid, _ in ELECTIONS for s in ("d", "r")]
    agg = joined.groupby("district")[vote_cols].sum()

    stats_by_district: dict[int, dict[str, float]] = {}
    for dist_id, row in agg.iterrows():
        stats: dict[str, float] = {}
        for eid, prop in ELECTIONS:
            d = float(row[f"d_{eid}"])
            r = float(row[f"r_{eid}"])
            total = d + r
            stats[prop] = round(d / total, 4) if total > 0 else float("nan")
        vals = [v for v in stats.values() if not np.isnan(v)]
        stats["partisan"] = round(float(np.mean(vals)), 4) if vals else float("nan")
        stats_by_district[int(dist_id)] = stats

    updated = 0
    for feat in features:
        props = feat.get("properties") or {}
        raw = props.get("district")
        if raw is None:
            raw = props.get("DISTRICT")
        if raw is None:
            continue
        stat = stats_by_district.get(int(float(raw)))
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

    print("=== Scoring district plans (block-weighted) ===")
    if args.dry_run:
        print("  [DRY RUN — no files will be written]\n")

    blocks = load_block_votes()
    block_gdf = to_geo(blocks)

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
            n = enrich_geojson(path, block_gdf, args.dry_run)
            verb = "would update" if args.dry_run else "updated"
            prefix = "[DRY]" if args.dry_run else "✓"
            print(f"  {prefix}  {path.name}  ({verb} {n} districts)")
            total_files += 1
            total_districts += n

    verb = "would have been" if args.dry_run else "were"
    print(f"\n{'DRY RUN complete' if args.dry_run else 'Done'}: "
          f"{total_files} files, {total_districts} district features {verb} scored.")

    if not args.dry_run:
        print("\nNext: sync updated GeoJSONs to fdex/")
        print("  bash fdex/scripts/sync_data.sh")


if __name__ == "__main__":
    main()
