#!/usr/bin/env python3
"""
build_cvap_vtd.py — Build a CVAP-based VTD parquet compatible with
score_ensemble_demographics.py (same column layout as bvap_vtd.parquet).

Source: ga-2024-cvap-vtd.parquet (2020-2024 ACS 5yr CVAP Special Tabulation,
        aggregated from 2020 Census blocks by build_vtd_inputs.py).

Why CVAP instead of BVAP for VRA analysis:
  - BVAP (2020 Census PL 94-171) counts all residents 18+ including non-citizens.
  - CVAP (ACS CVAP Special Tabulation) counts only citizen VAP — the population
    that can legally vote. This is the standard used in VRA §2 majority-minority
    district analysis (Gingles test, DOJ, courts).
  - For Georgia's Black congressional districts, BVAP shows 47-49% Black;
    CVAP shows 51-57% Black — the non-citizen denominator was masking true
    Black citizen majority status.

Column mapping (ACS CVAP → bvap_vtd column names):
  CVAP_TOT24  → bvap_tot      (total citizen VAP)
  CVAP_BLK24  → bvap_blk      (Black alone or in combination — VRA "any-part" standard)
  CVAP_WHT24  → bvap_wht      (White alone NH)
  CVAP_HSP24  → bvap_hsp      (Hispanic/Latino)
  CVAP_ASN24  → bvap_asn      (Asian alone or in combination)
  derived     → bvap_coalition (total CVAP minus White CVAP)

Output: fdp/data/repos/main/vtd/cvap_vtd.parquet
  Same schema as bvap_vtd.parquet — pass via --bvap-file to
  score_ensemble_demographics.py.

Usage (from fgdp/ root):
    uv run --project fdp python fdp/scripts/build_cvap_vtd.py
    uv run --project fdp python fdp/scripts/build_cvap_vtd.py --dry-run
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
_DATA_DIR   = _SCRIPT_DIR.parent / "data" / "repos" / "main"
_SRC_FILE   = _DATA_DIR / "vtd" / "ga-2024-cvap-vtd.parquet"
_OUT_FILE   = _DATA_DIR / "vtd" / "cvap_vtd.parquet"


def build(dry_run: bool = False) -> pd.DataFrame:
    if not _SRC_FILE.exists():
        raise FileNotFoundError(
            f"CVAP source not found: {_SRC_FILE}\n"
            "  Run build_vtd_inputs.py first:\n"
            "    uv run --project fdp python fdp/scripts/build_vtd_inputs.py --only cvap"
        )

    print(f"Reading {_SRC_FILE.name}…")
    src = pd.read_parquet(_SRC_FILE)
    print(f"  {len(src):,} VTDs")

    # ── Map CVAP columns → bvap_vtd schema ────────────────────────────────────
    df = pd.DataFrame({
        "GEOID20":        src["GEOID20"].astype(str),
        "bvap_tot":       src["CVAP_TOT24"].astype(int),   # total citizen VAP
        "bvap_blk":       src["CVAP_BLK24"].astype(int),   # Black alone or in combination
        "bvap_wht":       src["CVAP_WHT24"].astype(int),   # White alone NH
        "bvap_hsp":       src["CVAP_HSP24"].astype(int),   # Hispanic/Latino
        "bvap_asn":       src["CVAP_ASN24"].astype(int),   # Asian alone or in combination
    })
    df["bvap_coalition"] = (df["bvap_tot"] - df["bvap_wht"]).astype(int)

    tot = df["bvap_tot"].sum()
    print(f"  Total citizen VAP : {tot:>10,}")
    print(f"  Black CVAP        : {df['bvap_blk'].sum():>10,}  ({df['bvap_blk'].sum()/tot*100:.1f}%)")
    print(f"  White CVAP        : {df['bvap_wht'].sum():>10,}  ({df['bvap_wht'].sum()/tot*100:.1f}%)")
    print(f"  Hispanic CVAP     : {df['bvap_hsp'].sum():>10,}  ({df['bvap_hsp'].sum()/tot*100:.1f}%)")
    print(f"  Asian CVAP        : {df['bvap_asn'].sum():>10,}  ({df['bvap_asn'].sum()/tot*100:.1f}%)")
    print(f"  Coalition CVAP    : {df['bvap_coalition'].sum():>10,}  ({df['bvap_coalition'].sum()/tot*100:.1f}%)")

    if dry_run:
        print(f"\n[dry-run] Would write {len(df):,} rows → {_OUT_FILE.name}")
        return df

    _OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(_OUT_FILE, index=False)
    size_kb = _OUT_FILE.stat().st_size / 1024
    print(f"\n✓ {_OUT_FILE}  ({size_kb:.0f} KB)")
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="Show stats but do not write")
    args = ap.parse_args()
    build(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
