#!/usr/bin/env python3
"""
build_bvap_vtd.py — Extract BVAP (Black Voting Age Population) from 2020 Census PL 94-171.

Uses the VTD-level PL 94-171 shapefile (already present in fdensemble/input_data/).
Produces Census headcounts, NOT ACS estimates.

Census PL 94-171 Table P4 columns used:
  P0040001 — Total Voting Age Population (18+)
  P0040002 — Hispanic or Latino VAP
  P0040005 — Not Hispanic or Latino: White alone
  P0040006 — Not Hispanic or Latino: Black or African American alone  (= BVAP)
  P0040008 — Not Hispanic or Latino: Asian alone

Derived columns:
  bvap_coalition = P0040001 - P0040005  (all non-white VAP)

Output: fdp/data/repos/main/vtd/bvap_vtd.parquet
  GEOID20, bvap_tot, bvap_blk, bvap_wht, bvap_hsp, bvap_asn, bvap_coalition

Usage (from fgdp/ root):
    uv run --project fdp python fdp/scripts/build_bvap_vtd.py
    uv run --project fdp python fdp/scripts/build_bvap_vtd.py --dry-run
"""
from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT  = _SCRIPT_DIR.parent.parent

_VTD_SHP    = _REPO_ROOT / "fdensemble" / "input_data" / "ga_pl2020_vtd.zip"
_OUT_DIR    = _SCRIPT_DIR.parent / "data" / "repos" / "main" / "vtd"
_OUT_FILE   = _OUT_DIR / "bvap_vtd.parquet"


def build_bvap(dry_run: bool = False) -> pd.DataFrame:
    print(f"Reading {_VTD_SHP.name}…")
    gdf = gpd.read_file(f"/vsizip/{_VTD_SHP}/ga_pl2020_vtd.shp",
                        columns=["GEOID20", "P0040001", "P0040002",
                                 "P0040005", "P0040006", "P0040008"])

    df = pd.DataFrame({
        "GEOID20":        gdf["GEOID20"].astype(str),
        "bvap_tot":       gdf["P0040001"].astype(int),   # Total VAP
        "bvap_blk":       gdf["P0040006"].astype(int),   # NH Black alone
        "bvap_wht":       gdf["P0040005"].astype(int),   # NH White alone
        "bvap_hsp":       gdf["P0040002"].astype(int),   # Hispanic or Latino
        "bvap_asn":       gdf["P0040008"].astype(int),   # NH Asian alone
    })
    df["bvap_coalition"] = (df["bvap_tot"] - df["bvap_wht"]).astype(int)

    print(f"  {len(df):,} VTDs")
    print(f"  Total VAP       : {df['bvap_tot'].sum():>10,}")
    print(f"  Black VAP (BVAP): {df['bvap_blk'].sum():>10,}  ({df['bvap_blk'].sum()/df['bvap_tot'].sum()*100:.1f}%)")
    print(f"  White VAP (NH)  : {df['bvap_wht'].sum():>10,}  ({df['bvap_wht'].sum()/df['bvap_tot'].sum()*100:.1f}%)")
    print(f"  Hispanic VAP    : {df['bvap_hsp'].sum():>10,}  ({df['bvap_hsp'].sum()/df['bvap_tot'].sum()*100:.1f}%)")
    print(f"  Asian VAP (NH)  : {df['bvap_asn'].sum():>10,}  ({df['bvap_asn'].sum()/df['bvap_tot'].sum()*100:.1f}%)")
    print(f"  Coalition VAP   : {df['bvap_coalition'].sum():>10,}  ({df['bvap_coalition'].sum()/df['bvap_tot'].sum()*100:.1f}%)")

    if dry_run:
        print(f"\n[dry-run] Would write {len(df):,} rows to {_OUT_FILE.name}")
        print(df.head(5).to_string())
        return df

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(_OUT_FILE, index=False)
    size_kb = _OUT_FILE.stat().st_size / 1024
    print(f"\n✓ {_OUT_FILE}  ({size_kb:.0f} KB)")
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="Show stats but do not write")
    args = ap.parse_args()
    build_bvap(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
