#!/usr/bin/env python3
"""
build_block_points.py — Extract 2020 Census block internal points.

Reads the TIGER/Line 2020 PL tabblock20 shapefile for Georgia and writes a
compact lookup of each block's *internal point* — a coordinate the Census
guarantees falls inside the block polygon, unlike a computed centroid, which
can land outside a concave block.

This is the geometry side of the block-weighted scoring used by
enrich_plan_geojson.py; the vote and VAP_MOD side already lives in
data/repos/main/block/.

Output: data/repos/main/block/block_points.parquet
        GEOID20 (15-char block), lat, lon

Source: https://www2.census.gov/geo/tiger/TIGER2020PL/STATE/13_GEORGIA/13/
        tl_2020_13_tabblock20.zip

Usage:
    uv run python scripts/build_block_points.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "data/raw/boundaries/tl_2020_13_tabblock20.zip"
_OUT = _ROOT / "data/repos/main/block/block_points.parquet"


def main() -> None:
    if not _SRC.exists():
        sys.exit(
            f"ERROR: {_SRC} not found.\n"
            "Download it from https://www2.census.gov/geo/tiger/TIGER2020PL/"
            "STATE/13_GEORGIA/13/tl_2020_13_tabblock20.zip"
        )

    # Attributes only — the internal point ships as a DBF field, so the 260MB
    # geometry never needs to be read.
    df = gpd.read_file(f"zip://{_SRC}", ignore_geometry=True)
    cols = {c.upper(): c for c in df.columns}
    geoid = cols.get("GEOID20")
    lat = cols.get("INTPTLAT20")
    lon = cols.get("INTPTLON20")
    if not (geoid and lat and lon):
        sys.exit(f"ERROR: expected GEOID20/INTPTLAT20/INTPTLON20, got {list(df.columns)}")

    out = pd.DataFrame(
        {
            "GEOID20": df[geoid].astype(str),
            "lat": pd.to_numeric(df[lat], errors="coerce"),
            "lon": pd.to_numeric(df[lon], errors="coerce"),
        }
    )

    bad = out.lat.isna() | out.lon.isna()
    if bad.any():
        sys.exit(f"ERROR: {int(bad.sum())} blocks have unparseable internal points")

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(_OUT, index=False)
    print(f"Wrote {_OUT}  ({len(out):,} blocks)")
    print(f"  lat range {out.lat.min():.4f}..{out.lat.max():.4f}")
    print(f"  lon range {out.lon.min():.4f}..{out.lon.max():.4f}")


if __name__ == "__main__":
    main()
