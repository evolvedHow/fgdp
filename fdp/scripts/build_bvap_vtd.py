#!/usr/bin/env python3
"""
Build a BVAP-style parquet from fdensemble/data/vtd_demographics.parquet.

Output schema (matches score_ensemble_demographics.py expectations):
  GEOID20, bvap_tot, bvap_blk, bvap_wht, bvap_hsp, bvap_asn
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
OUT_PATH = SCRIPT_DIR.parent / "data" / "repos" / "main" / "vtd" / "bvap_vtd.parquet"
DEMO_PATH = SCRIPT_DIR.parent.parent / "fdensemble" / "data" / "vtd_demographics.parquet"


def main() -> None:
    print(f"Reading {DEMO_PATH.name} ...")
    df = pd.read_parquet(DEMO_PATH)
    out = pd.DataFrame({
        "GEOID20": df["geoid"].astype(str),
        "bvap_tot": df["vap"].fillna(0).astype(int),
        "bvap_blk": df["vap_black"].fillna(0).astype(int),
        "bvap_wht": df["vap_white"].fillna(0).astype(int),
        "bvap_hsp": df["vap_hisp"].fillna(0).astype(int),
        "bvap_asn": df["vap_asian"].fillna(0).astype(int),
    })
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT_PATH, index=False)
    print(f"Wrote {OUT_PATH}  ({len(out):,} rows)")


if __name__ == "__main__":
    main()
