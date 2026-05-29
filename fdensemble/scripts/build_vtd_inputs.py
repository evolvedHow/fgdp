#!/usr/bin/env python3
"""
Build VTD-level input files for Georgia redistricting ensemble analysis.

Aggregates block-level RDH data to 2020 VTD geography via centroid spatial
join.  Produces clean, ALARM-compatible parquet files ready to join into
GA_cd_2020_map.rds in R.

Input (fdensemble/input_data/):
  ga_pl2020_vtd.zip                    — VTD reference shapefile (2,698 VTDs)
  ga_2020_gen_2020_blocks.zip          — 2020 general + 2021 Jan 5 runoffs at 2020 blocks
  Copy of ga_2022_gen_2020_blocks.zip  — 2022 general election at 2020 blocks
  Copy of ga_2024_gen_2020_blocks.zip  — 2024 general election at 2020 blocks
  ga_cvap_2024_2020_b_csv.zip          — 2024 ACS CVAP at 2020 blocks (CSV)

Output (fdensemble/output/vtd/):
  block_vtd_lookup.parquet      — block GEOID20 → VTD GEOID20 mapping (cached)
  vtd_elections_2020.parquet    — 2020 special + 2021 Jan 5 runoff vote counts per VTD
  vtd_elections_2022.parquet    — 2022 general election vote counts per VTD
  vtd_elections_2024.parquet    — 2024 general election vote counts per VTD
  vtd_cvap.parquet              — 2024 ACS CVAP counts per VTD
  vtd_combined.parquet          — all joined, ALARM-ready (join key: GEOID20)

Usage (from fdensemble/ directory in WSL):
    uv run python scripts/build_vtd_inputs.py
    uv run python scripts/build_vtd_inputs.py --skip-lookup    # reuse cached lookup
    uv run python scripts/build_vtd_inputs.py --only elections2021  # one step only

R join example:
    library(arrow)
    vtd <- read_parquet("output/vtd/vtd_combined.parquet")
    map_data <- left_join(GA_cd_2020_map, vtd, by = c("GEOID" = "GEOID20"))
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd

# ── Paths ──────────────────────────────────────────────────────────────────────

_SCRIPT_DIR   = Path(__file__).resolve().parent
_PROJECT_DIR  = _SCRIPT_DIR.parent

DEFAULT_INPUT_DIR  = _PROJECT_DIR / "input_data"
DEFAULT_OUTPUT_DIR = _PROJECT_DIR / "output" / "vtd"

# ── Zip / internal file names ─────────────────────────────────────────────────

VTD_ZIP      = "ga_pl2020_vtd.zip"
VTD_SHP      = "ga_pl2020_vtd.shp"

# Note: 2020 file has shapefiles at zip root (no subdirectory)
BLOCKS_2020_ZIP = "ga_2020_gen_2020_blocks.zip"
BLOCKS_2020_SHP = "ga_2020_gen_2020_blocks.shp"

BLOCKS_2022_ZIP = "Copy of ga_2022_gen_2020_blocks.zip"
BLOCKS_2022_SHP = "ga_2022_gen_2020_blocks/ga_2022_gen_2020_blocks.shp"

BLOCKS_2024_ZIP = "Copy of ga_2024_gen_2020_blocks.zip"
BLOCKS_2024_SHP = "ga_2024_gen_2020_blocks/ga_2024_gen_2020_blocks.shp"

CVAP_ZIP = "ga_cvap_2024_2020_b_csv.zip"
CVAP_CSV = "ga_cvap_2024_2020_b.csv"

# ── Column selections ──────────────────────────────────────────────────────────

# 2020 file: Nov 3 special election + January 5, 2021 runoffs
# (2020 President and Perdue/Ossoff Nov 3 are already in the ALARM map)
COLS_2020 = [
    "GEOID20", "VAP_MOD",
    # Nov 3, 2020 Special Election — Loeffler seat (jungle primary, key candidates)
    "S20USSDWAR",   # Warnock (D)
    "S20USSRLOE",   # Loeffler (R) — incumbent
    "S20USSRCOL",   # Collins (R) — major challenger
    # Jan 5, 2021 Runoff — Ossoff vs Perdue
    "R21USSDOSS",   # Ossoff (D)
    "R21USSRPER",   # Perdue (R)
    # Jan 5, 2021 Runoff — Warnock vs Loeffler
    "R21USSDWAR",   # Warnock (D)
    "R21USSRLOE",   # Loeffler (R)
]

# 2022 general election columns (block → aggregate to VTD)
COLS_2022 = [
    "GEOID20", "VAP_MOD",
    "G22GOVDABR", "G22GOVRKEM", "G22GOVLHAZ",    # Governor
    "G22USSDWAR", "G22USSRWAL", "G22USSLOLI",     # US Senate Nov 8
    "G22ATGDJOR", "G22ATGRCAR", "G22ATGLCOW",     # Attorney General
    "G22SOSDNGU", "G22SOSRRAF", "G22SOSLMET",     # Secretary of State
    "G22LTGDBAI", "G22LTGRJON", "G22LTGLGRA",     # Lt. Governor
]

# 2024 general election columns
COLS_2024 = [
    "GEOID20", "VAP_MOD",
    "G24PREDHAR", "G24PRERTRU", "G24PRELOLI",     # President (D/R/L)
    "G24PREGSTE", "G24PREICRU", "G24PREIWES",     # President (G/I/I)
]

# CVAP columns  (CVAP_ = citizen VAP estimates from 2020–2024 ACS 5-yr)
CVAP_COLS = [
    "GEOID20",
    "CVAP_TOT24",    # Total CVAP
    "CVAP_BLK24",    # Black or AA alone or in combination
    "CVAP_BLA24",    # Black or AA alone
    "CVAP_HSP24",    # Hispanic or Latino
    "CVAP_WHT24",    # White alone (non-Hispanic)
    "CVAP_ASN24",    # Asian alone or in combination
    "CVAP_AMI24",    # American Indian/AK Native alone or in combination
    "CVAP_NHP24",    # Native Hawaiian/Pacific Islander alone or in combination
]

# ── Statewide certified totals (GA SOS) for sanity checks ─────────────────────

_SOS_2021 = {
    # Jan 5, 2021 runoffs — GA SOS certified
    "R21USSDOSS": 2269923,   # Ossoff (50.38%)
    "R21USSRPER": 2237921,   # Perdue (49.62%)
    "R21USSDWAR": 2288923,   # Warnock (50.81%)
    "R21USSRLOE": 2215599,   # Loeffler (49.19%)
}

_SOS_2022 = {
    "G22GOVDABR": 1813503,   # Abrams (2022 — not 2018)
    "G22GOVRKEM": 2112319,   # Kemp
    "G22USSDWAR": 1945370,   # Warnock (Nov 8 general)
    "G22USSRWAL": 1908442,   # Walker (Nov 8 general)
}
_SOS_2024 = {
    "G24PREDHAR": 2547753,   # Harris (GA SOS official canvass)
    "G24PRERTRU": 2663916,   # Trump  (GA SOS official canvass)
    # Note: Oliver Lib shows ~21K in block file vs ~142K certified — known
    # RDH limitation: third-party votes in low-VAP_MOD precincts get lost
    # during block disaggregation. R/D totals are unaffected.
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    print(msg, flush=True)


def _extract_shp_to_tmpdir(zip_path: Path, internal_shp: str) -> tuple[Path, str]:
    """
    Extract all sidecar files (.shp/.shx/.dbf/.prj/.cpg) for one shapefile
    from a zip archive into a fresh temp directory.
    Returns (shp_path, tmpdir_str).  Caller must shutil.rmtree(tmpdir_str).
    """
    stem = Path(internal_shp).stem
    tmpdir = tempfile.mkdtemp(prefix="vtd_build_")
    with zipfile.ZipFile(zip_path) as zf:
        for entry in zf.namelist():
            if Path(entry).stem == stem:
                zf.extract(entry, tmpdir)
    matches = list(Path(tmpdir).rglob(f"{stem}.shp"))
    if not matches:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise FileNotFoundError(f"Could not find {stem}.shp inside {zip_path}")
    return matches[0], tmpdir


def _add_2pv(df: pd.DataFrame, race: str, dem_col: str, rep_col: str) -> pd.DataFrame:
    """Append two-party vote share columns: dem_2pv_<race>, rep_2pv_<race>."""
    total_2p = (df[dem_col] + df[rep_col]).replace(0, float("nan"))
    df[f"dem_2pv_{race}"] = (df[dem_col] / total_2p * 100).round(4)
    df[f"rep_2pv_{race}"] = (df[rep_col] / total_2p * 100).round(4)
    return df


def _check_totals(df: pd.DataFrame, expected: dict[str, int], label: str) -> None:
    log(f"  Vote-total check vs GA SOS ({label}):")
    for col, exp in expected.items():
        got = int(df[col].sum())
        pct = abs(got - exp) / exp * 100
        flag = "OK" if pct < 0.5 else "WARN"
        log(f"    [{flag}] {col}: got {got:,}  expected {exp:,}  ({pct:.2f}% diff)")


# ── Step 1: block → VTD lookup ─────────────────────────────────────────────────

def build_lookup(input_dir: Path, output_dir: Path) -> pd.DataFrame:
    """
    Spatial join: 2022 block centroids within VTD polygons.
    The result is valid for 2022, 2024, and CVAP — all use identical 2020 blocks.
    Saved to block_vtd_lookup.parquet and returned.
    """
    log("\n[1/4] Building block → VTD spatial lookup")
    lookup_path = output_dir / "block_vtd_lookup.parquet"

    # Load VTD reference (small: 2,698 rows)
    log("  Loading VTD shapefile…")
    shp_path, tmpdir = _extract_shp_to_tmpdir(input_dir / VTD_ZIP, VTD_SHP)
    try:
        vtds = gpd.read_file(shp_path, engine="pyogrio")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    vtds = vtds[["GEOID20", "geometry"]].rename(columns={"GEOID20": "vtd_GEOID20"})
    if vtds.crs.to_epsg() != 4269:
        vtds = vtds.to_crs(epsg=4269)
    log(f"  Loaded {len(vtds):,} VTDs  (CRS: {vtds.crs.to_epsg()})")

    # Load 2022 block geometries + GEOID20 only (skip all 400+ vote columns)
    log("  Loading block geometries from 2022 zip — takes 1–2 min…")
    shp_path, tmpdir = _extract_shp_to_tmpdir(input_dir / BLOCKS_2022_ZIP, BLOCKS_2022_SHP)
    try:
        blocks = gpd.read_file(shp_path, columns=["GEOID20"], engine="pyogrio")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    log(f"  Loaded {len(blocks):,} blocks")

    # Reproject to projected CRS (UTM 16N) for accurate centroids, then back to NAD83
    _UTM = 32616
    blocks_proj = blocks.to_crs(epsg=_UTM)
    vtds_proj   = vtds.to_crs(epsg=_UTM)

    log("  Computing centroids and running spatial join…")
    centroids = blocks_proj[["GEOID20", "geometry"]].copy()
    centroids.geometry = centroids.geometry.centroid
    centroids = centroids.rename(columns={"GEOID20": "block_GEOID20"})

    joined = gpd.sjoin(centroids, vtds_proj, how="left", predicate="within")

    n_assigned   = joined["vtd_GEOID20"].notna().sum()
    n_unassigned = len(joined) - n_assigned
    log(f"  Assigned {n_assigned:,} / {len(joined):,} blocks  "
        f"({n_unassigned} unmatched — typically zero-VAP water blocks)")

    lookup = joined[["block_GEOID20", "vtd_GEOID20"]].copy()
    lookup.to_parquet(lookup_path, index=False)
    log(f"  Saved → {lookup_path}")
    return lookup


def load_or_build_lookup(input_dir: Path, output_dir: Path, skip_rebuild: bool) -> pd.DataFrame:
    lookup_path = output_dir / "block_vtd_lookup.parquet"
    if lookup_path.exists() and skip_rebuild:
        log(f"\n[1/4] Reusing cached lookup: {lookup_path}")
        lk = pd.read_parquet(lookup_path)
        log(f"  {len(lk):,} block → VTD mappings loaded")
        return lk
    return build_lookup(input_dir, output_dir)


# ── Step 2: 2020 special + 2021 runoffs ───────────────────────────────────────

def build_elections_2020(input_dir: Path, output_dir: Path,
                         lookup: pd.DataFrame) -> pd.DataFrame | None:
    """
    Aggregate Nov 3, 2020 special election (Loeffler seat) and
    January 5, 2021 Senate runoffs (Ossoff/Perdue + Warnock/Loeffler) to VTD.
    Note: 2020 President and Ossoff/Perdue Nov 3 are already in the ALARM map.

    Returns None if the zip file is missing the R21* runoff columns —
    this happens when the file is the 2020-General-only download from RDH.
    The full file (including specials + runoffs) must be requested separately.
    """
    log("\n[2/5] Aggregating 2020 special + 2021 runoffs → VTD")
    out_path = output_dir / "vtd_elections_2020.parquet"

    log("  Reading 2020 block attribute table (no geometry)…")
    # Read without column filter first to check what's available
    shp_path, tmpdir = _extract_shp_to_tmpdir(input_dir / BLOCKS_2020_ZIP, BLOCKS_2020_SHP)
    try:
        df_probe = gpd.read_file(shp_path, engine="pyogrio", ignore_geometry=True, rows=1)
        available_cols = set(df_probe.columns)
        needed_runoff = {"R21USSDOSS", "R21USSRPER", "R21USSDWAR", "R21USSRLOE"}
        if not needed_runoff.issubset(available_cols):
            missing_cols = needed_runoff - available_cols
            log(f"  SKIP: R21 runoff columns not found in file: {sorted(missing_cols)}")
            log("  The downloaded file is the 2020-General-only version.")
            log("  Request ga_2020_gen_runoff_2020_blocks.zip from RDH for 2021 runoff data.")
            return None
        cols_to_read = [c for c in COLS_2020 if c in available_cols]
        df = gpd.read_file(shp_path, columns=cols_to_read, engine="pyogrio", ignore_geometry=True)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    log(f"  Loaded {len(df):,} blocks × {len(df.columns)} columns")

    vote_cols = [c for c in cols_to_read if c != "GEOID20"]
    df[vote_cols] = df[vote_cols].apply(pd.to_numeric, errors="coerce").fillna(0)

    df = df.merge(lookup, left_on="GEOID20", right_on="block_GEOID20", how="left")
    n_drop = df["vtd_GEOID20"].isna().sum()
    if n_drop:
        log(f"  Dropping {n_drop} blocks with no VTD assignment")
    df = df.dropna(subset=["vtd_GEOID20"])

    agg_cols = [c for c in cols_to_read if c != "GEOID20"]
    vtd = df.groupby("vtd_GEOID20")[agg_cols].sum().reset_index()
    vtd = vtd.rename(columns={"vtd_GEOID20": "GEOID20"})

    # 2021 runoff two-party vote shares
    vtd = _add_2pv(vtd, "ussR21a", "R21USSDOSS", "R21USSRPER")   # Ossoff/Perdue
    vtd = _add_2pv(vtd, "ussR21b", "R21USSDWAR", "R21USSRLOE")   # Warnock/Loeffler

    vtd.to_parquet(out_path, index=False)
    log(f"  {len(vtd):,} VTDs × {len(vtd.columns)} columns → {out_path}")
    _check_totals(vtd, _SOS_2021, "2021 runoffs")
    return vtd


# ── Step 3: 2022 elections ─────────────────────────────────────────────────────

def build_elections_2022(input_dir: Path, output_dir: Path, lookup: pd.DataFrame) -> pd.DataFrame:
    log("\n[3/5] Aggregating 2022 general election → VTD")
    out_path = output_dir / "vtd_elections_2022.parquet"

    log("  Reading 2022 block attribute table (no geometry)…")
    shp_path, tmpdir = _extract_shp_to_tmpdir(input_dir / BLOCKS_2022_ZIP, BLOCKS_2022_SHP)
    try:
        df = gpd.read_file(shp_path, columns=COLS_2022, engine="pyogrio", ignore_geometry=True)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    log(f"  Loaded {len(df):,} blocks × {len(df.columns)} columns")

    vote_cols = [c for c in COLS_2022 if c != "GEOID20"]
    df[vote_cols] = df[vote_cols].apply(pd.to_numeric, errors="coerce").fillna(0)

    df = df.merge(lookup, left_on="GEOID20", right_on="block_GEOID20", how="left")
    n_drop = df["vtd_GEOID20"].isna().sum()
    if n_drop:
        log(f"  Dropping {n_drop} blocks with no VTD assignment")
    df = df.dropna(subset=["vtd_GEOID20"])

    agg_cols = [c for c in COLS_2022 if c != "GEOID20"]
    vtd = df.groupby("vtd_GEOID20")[agg_cols].sum().reset_index()
    vtd = vtd.rename(columns={"vtd_GEOID20": "GEOID20"})

    vtd = _add_2pv(vtd, "gov22", "G22GOVDABR", "G22GOVRKEM")
    vtd = _add_2pv(vtd, "uss22", "G22USSDWAR", "G22USSRWAL")
    vtd = _add_2pv(vtd, "atg22", "G22ATGDJOR", "G22ATGRCAR")
    vtd = _add_2pv(vtd, "sos22", "G22SOSDNGU", "G22SOSRRAF")
    vtd = _add_2pv(vtd, "ltg22", "G22LTGDBAI", "G22LTGRJON")

    vtd.to_parquet(out_path, index=False)
    log(f"  {len(vtd):,} VTDs × {len(vtd.columns)} columns → {out_path}")
    _check_totals(vtd, _SOS_2022, "2022 general")
    return vtd


# ── Step 3: 2024 elections ─────────────────────────────────────────────────────

def build_elections_2024(input_dir: Path, output_dir: Path, lookup: pd.DataFrame) -> pd.DataFrame:
    log("\n[4/5] Aggregating 2024 general election → VTD")
    out_path = output_dir / "vtd_elections_2024.parquet"

    log("  Reading 2024 block attribute table (no geometry)…")
    shp_path, tmpdir = _extract_shp_to_tmpdir(input_dir / BLOCKS_2024_ZIP, BLOCKS_2024_SHP)
    try:
        df = gpd.read_file(shp_path, columns=COLS_2024, engine="pyogrio", ignore_geometry=True)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    log(f"  Loaded {len(df):,} blocks × {len(df.columns)} columns")

    vote_cols = [c for c in COLS_2024 if c != "GEOID20"]
    df[vote_cols] = df[vote_cols].apply(pd.to_numeric, errors="coerce").fillna(0)

    df = df.merge(lookup, left_on="GEOID20", right_on="block_GEOID20", how="left")
    df = df.dropna(subset=["vtd_GEOID20"])

    agg_cols = [c for c in COLS_2024 if c != "GEOID20"]
    vtd = df.groupby("vtd_GEOID20")[agg_cols].sum().reset_index()
    vtd = vtd.rename(columns={"vtd_GEOID20": "GEOID20"})

    vtd = _add_2pv(vtd, "pre24", "G24PREDHAR", "G24PRERTRU")

    vtd.to_parquet(out_path, index=False)
    log(f"  {len(vtd):,} VTDs × {len(vtd.columns)} columns → {out_path}")
    _check_totals(vtd, _SOS_2024, "2024 general")
    return vtd


# ── Step 4: CVAP ───────────────────────────────────────────────────────────────

def build_cvap(input_dir: Path, output_dir: Path, lookup: pd.DataFrame) -> pd.DataFrame:
    log("\n[5/5] Aggregating CVAP → VTD")
    out_path = output_dir / "vtd_cvap.parquet"

    log("  Reading CVAP CSV from zip…")
    with zipfile.ZipFile(input_dir / CVAP_ZIP) as zf:
        with zf.open(CVAP_CSV) as f:
            df = pd.read_csv(f, usecols=CVAP_COLS, dtype={"GEOID20": str})
    log(f"  Loaded {len(df):,} blocks")

    # Pad to 15 chars in case leading zeros were dropped
    df["GEOID20"] = df["GEOID20"].str.zfill(15)

    cvap_val_cols = [c for c in CVAP_COLS if c != "GEOID20"]
    df[cvap_val_cols] = df[cvap_val_cols].apply(pd.to_numeric, errors="coerce").fillna(0)

    df = df.merge(lookup, left_on="GEOID20", right_on="block_GEOID20", how="left")
    n_drop = df["vtd_GEOID20"].isna().sum()
    if n_drop:
        log(f"  Dropping {n_drop} blocks with no VTD assignment")
    df = df.dropna(subset=["vtd_GEOID20"])

    vtd = df.groupby("vtd_GEOID20")[cvap_val_cols].sum().reset_index()
    vtd = vtd.rename(columns={"vtd_GEOID20": "GEOID20"})

    # Derived CVAP percentages useful for VRA analysis
    tot = vtd["CVAP_TOT24"].replace(0, float("nan"))
    vtd["bvap_pct24"] = (vtd["CVAP_BLK24"] / tot * 100).round(2)
    vtd["hvap_pct24"] = (vtd["CVAP_HSP24"] / tot * 100).round(2)
    vtd["wvap_pct24"] = (vtd["CVAP_WHT24"] / tot * 100).round(2)
    vtd["avap_pct24"] = (vtd["CVAP_ASN24"] / tot * 100).round(2)

    vtd.to_parquet(out_path, index=False)
    log(f"  {len(vtd):,} VTDs × {len(vtd.columns)} columns → {out_path}")
    total_cvap = int(vtd["CVAP_TOT24"].sum())
    log(f"  Statewide CVAP total: {total_cvap:,}")
    return vtd


# ── Combine all three ──────────────────────────────────────────────────────────

def build_combined(output_dir: Path,
                   df22: pd.DataFrame,
                   df24: pd.DataFrame,
                   cvap: pd.DataFrame,
                   df20: pd.DataFrame | None = None) -> pd.DataFrame:
    log("\n[Combine] Joining all VTD tables → vtd_combined.parquet")
    out_path = output_dir / "vtd_combined.parquet"

    # Use 2022 as base (has VAP_MOD and most elections)
    combined = df22.copy()
    # 2020/2021 (optional — only present when runoff file is available):
    if df20 is not None:
        combined = combined.merge(
            df20.drop(columns=["VAP_MOD"], errors="ignore"),
            on="GEOID20", how="outer",
        )
    # 2024: drop VAP_MOD duplicate
    combined = combined.merge(
        df24.drop(columns=["VAP_MOD"], errors="ignore"),
        on="GEOID20", how="outer",
    )
    combined = combined.merge(cvap, on="GEOID20", how="outer")

    combined.to_parquet(out_path, index=False)
    log(f"  {len(combined):,} VTDs × {len(combined.columns)} total columns → {out_path}")
    log("\n  All columns in vtd_combined.parquet:")
    for col in combined.columns:
        log(f"    {col}")
    return combined


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--input-dir",  default=str(DEFAULT_INPUT_DIR),
                    help=f"Directory with input zip files (default: {DEFAULT_INPUT_DIR})")
    ap.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR),
                    help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})")
    ap.add_argument("--skip-lookup", action="store_true",
                    help="Reuse block_vtd_lookup.parquet if it already exists")
    ap.add_argument("--only",
                    choices=["lookup", "elections2020", "elections2022", "elections2024", "cvap"],
                    help="Run only one step (lookup must exist for non-lookup steps)")
    args = ap.parse_args()

    input_dir  = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    if not input_dir.exists():
        log(f"ERROR: Input directory not found: {input_dir}")
        sys.exit(1)

    required_zips = [VTD_ZIP, BLOCKS_2022_ZIP, BLOCKS_2024_ZIP, CVAP_ZIP]
    missing = [f for f in required_zips if not (input_dir / f).exists()]
    if missing:
        log("ERROR: Missing input files:")
        for f in missing:
            log(f"  {input_dir / f}")
        sys.exit(1)

    # 2020 file is optional — only useful if it contains R21* runoff columns
    have_2020 = (input_dir / BLOCKS_2020_ZIP).exists()

    output_dir.mkdir(parents=True, exist_ok=True)
    log(f"Input:  {input_dir}")
    log(f"Output: {output_dir}")

    if args.only == "lookup":
        build_lookup(input_dir, output_dir)
        return

    lookup = load_or_build_lookup(input_dir, output_dir, skip_rebuild=args.skip_lookup)

    if args.only == "elections2020":
        if not have_2020:
            log(f"ERROR: {BLOCKS_2020_ZIP} not found in {input_dir}")
            sys.exit(1)
        build_elections_2020(input_dir, output_dir, lookup)
        return
    if args.only == "elections2022":
        build_elections_2022(input_dir, output_dir, lookup)
        return
    if args.only == "elections2024":
        build_elections_2024(input_dir, output_dir, lookup)
        return
    if args.only == "cvap":
        build_cvap(input_dir, output_dir, lookup)
        return

    # Full run
    df20 = build_elections_2020(input_dir, output_dir, lookup) if have_2020 else None
    if df20 is None:
        log("\n[2/5] Skipping 2020 special/runoff step — file not present or columns unavailable")
    df22 = build_elections_2022(input_dir, output_dir, lookup)
    df24 = build_elections_2024(input_dir, output_dir, lookup)
    cvap = build_cvap(input_dir, output_dir, lookup)
    build_combined(output_dir, df22, df24, cvap, df20=df20)

    log("\nDone.")
    log("Join into R with:")
    log("  library(arrow)")
    log("  vtd <- read_parquet('output/vtd/vtd_combined.parquet')")
    log("  map_data <- left_join(GA_cd_2020_map, vtd, by = c('GEOID' = 'GEOID20'))")


if __name__ == "__main__":
    main()
