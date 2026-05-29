#!/usr/bin/env python3
"""
Build VTD-level input files for Georgia redistricting ensemble analysis.

Aggregates block-level RDH data to 2020 VTD geography via centroid spatial
join.  Produces clean, ALARM-compatible parquet files ready to join into
GA_cd_2020_map.rds.

Output (data/repos/main/vtd/):
  block_vtd_lookup.parquet    — block GEOID20 → VTD GEOID20 mapping (cached)
  vtd_elections_2022.parquet  — 2022 general election vote counts per VTD
  vtd_elections_2024.parquet  — 2024 general election vote counts per VTD
  vtd_cvap.parquet            — 2024 ACS CVAP counts per VTD
  vtd_combined.parquet        — all of the above joined, ALARM-ready

Usage (from the fdp/ directory in WSL):
    uv run python scripts/build_vtd_inputs.py
    uv run python scripts/build_vtd_inputs.py --input-dir /custom/path
    uv run python scripts/build_vtd_inputs.py --skip-lookup   # reuse cached lookup
    uv run python scripts/build_vtd_inputs.py --only cvap     # run one step only
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

# ── Paths ─────────────────────────────────────────────────────────────────────

# Google Drive input datasets (WSL mount path)
DEFAULT_INPUT_DIR = Path("/mnt/g/My Drive/$FDGA/$fgdp/input_datasets")

# Output goes into the FDP data repo
_SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = _SCRIPT_DIR.parent / "data/repos/main/vtd"

# ── Zip / shapefile names ──────────────────────────────────────────────────────

VTD_ZIP = "ga_pl2020_vtd.zip"
VTD_SHP = "ga_pl2020_vtd.shp"

BLOCKS_2022_ZIP = "Copy of ga_2022_gen_2020_blocks.zip"
BLOCKS_2022_SHP = "ga_2022_gen_2020_blocks/ga_2022_gen_2020_blocks.shp"

BLOCKS_2024_ZIP = "Copy of ga_2024_gen_2020_blocks.zip"
BLOCKS_2024_SHP = "ga_2024_gen_2020_blocks/ga_2024_gen_2020_blocks.shp"

CVAP_ZIP = "ga_cvap_2024_2020_b_csv.zip"
CVAP_CSV = "ga_cvap_2024_2020_b.csv"

# ── Column lists ───────────────────────────────────────────────────────────────

# 2022 general election columns (all major candidates)
COLS_2022 = [
    "GEOID20", "VAP_MOD",
    # Governor
    "G22GOVDABR", "G22GOVRKEM", "G22GOVLHAZ",
    # US Senate Nov 8 (Oliver forced runoff → include for two-party calc)
    "G22USSDWAR", "G22USSRWAL", "G22USSLOLI",
    # Attorney General
    "G22ATGDJOR", "G22ATGRCAR", "G22ATGLCOW",
    # Secretary of State
    "G22SOSDNGU", "G22SOSRRAF", "G22SOSLMET",
    # Lt. Governor
    "G22LTGDBAI", "G22LTGRJON", "G22LTGLGRA",
]

# 2024 general election columns
COLS_2024 = [
    "GEOID20", "VAP_MOD",
    # President (all candidates — minor ones helpful for total-vote check)
    "G24PREDHAR", "G24PRERTRU", "G24PRELOLI", "G24PREGSTE",
    "G24PREICRU", "G24PREIWES",
]

# CVAP columns (CVAP_ prefix = citizen voting-age population estimates)
CVAP_COLS = [
    "GEOID20",
    "CVAP_TOT24",   # Total CVAP
    "CVAP_BLK24",   # Black or African American alone or in combination
    "CVAP_BLA24",   # Black or African American alone
    "CVAP_HSP24",   # Hispanic or Latino
    "CVAP_WHT24",   # White alone (non-Hispanic)
    "CVAP_ASN24",   # Asian alone or in combination
    "CVAP_AMI24",   # American Indian / Alaska Native alone or in combination
    "CVAP_NHP24",   # Native Hawaiian / Other Pacific Islander alone or in combination
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    print(msg, flush=True)


def _extract_shp_to_tmpdir(zip_path: Path, internal_shp: str) -> tuple[Path, str]:
    """
    Extract all components of a shapefile (.shp/.shx/.dbf/.prj/.cpg) from
    a zip archive into a fresh temp directory.  Returns (shp_path, tmpdir).
    Caller is responsible for shutil.rmtree(tmpdir).
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


def _read_vtd_shapefile(zip_path: Path) -> gpd.GeoDataFrame:
    """Load the VTD reference shapefile (2,698 rows, ~6 MB)."""
    _log("  Loading VTD reference shapefile…")
    shp_path, tmpdir = _extract_shp_to_tmpdir(zip_path, VTD_SHP)
    try:
        vtds = gpd.read_file(shp_path, engine="pyogrio")
        _log(f"  Loaded {len(vtds):,} VTDs  (CRS: {vtds.crs})")
        return vtds
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── Step 1: Build block→VTD lookup ────────────────────────────────────────────

def build_lookup(input_dir: Path, output_dir: Path) -> pd.DataFrame:
    """
    Spatial join: 2022 block centroids → VTD polygons.
    Returns and saves a DataFrame with columns [block_GEOID20, vtd_GEOID20].

    Uses the 2022 block shapefile because it has all 232,717 blocks with
    geometry.  Result applies equally to 2024 elections and CVAP since all
    three use identical 2020 block geography.
    """
    lookup_path = output_dir / "block_vtd_lookup.parquet"
    _log("\n[1/4] Building block→VTD spatial lookup")

    vtds = _read_vtd_shapefile(input_dir / VTD_ZIP)
    vtds = vtds[["GEOID20", "geometry"]].rename(columns={"GEOID20": "vtd_GEOID20"})
    # Ensure consistent CRS
    if vtds.crs.to_epsg() != 4269:
        vtds = vtds.to_crs(epsg=4269)

    _log("  Loading 2022 block geometries (geometry + GEOID20 only) — this takes a few minutes…")
    shp_path, tmpdir = _extract_shp_to_tmpdir(input_dir / BLOCKS_2022_ZIP, BLOCKS_2022_SHP)
    try:
        blocks = gpd.read_file(shp_path, columns=["GEOID20"], engine="pyogrio")
        _log(f"  Loaded {len(blocks):,} blocks")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    if blocks.crs.to_epsg() != 4269:
        blocks = blocks.to_crs(epsg=4269)

    _log("  Computing block centroids…")
    blocks = blocks[["GEOID20", "geometry"]].copy()
    blocks.geometry = blocks.geometry.centroid
    blocks = blocks.rename(columns={"GEOID20": "block_GEOID20"})

    _log("  Running spatial join (centroid within VTD)…")
    joined = gpd.sjoin(blocks, vtds, how="left", predicate="within")

    # Report join quality
    assigned = joined["vtd_GEOID20"].notna().sum()
    unassigned = len(joined) - assigned
    _log(f"  Assigned {assigned:,}/{len(joined):,} blocks  ({unassigned} unmatched)")

    if unassigned > 0:
        _log(f"  WARNING: {unassigned} blocks did not fall within any VTD polygon.")
        _log("  These are typically water or boundary slivers with VAP_MOD=0.")

    lookup = joined[["block_GEOID20", "vtd_GEOID20"]].copy()
    lookup.to_parquet(lookup_path, index=False)
    _log(f"  Saved → {lookup_path}")
    return lookup


def load_or_build_lookup(input_dir: Path, output_dir: Path, skip_rebuild: bool) -> pd.DataFrame:
    lookup_path = output_dir / "block_vtd_lookup.parquet"
    if lookup_path.exists() and skip_rebuild:
        _log(f"\n[1/4] Reusing cached lookup from {lookup_path}")
        return pd.read_parquet(lookup_path)
    elif lookup_path.exists() and not skip_rebuild:
        _log(f"\n[1/4] Lookup exists but --skip-lookup not set. Rebuilding.")
    return build_lookup(input_dir, output_dir)


# ── Step 2: Aggregate 2022 elections ──────────────────────────────────────────

def build_elections_2022(input_dir: Path, output_dir: Path, lookup: pd.DataFrame) -> pd.DataFrame:
    """
    Load 2022 block election data (attribute table only, no geometry),
    merge with lookup, aggregate to VTD.
    """
    _log("\n[2/4] Aggregating 2022 general election to VTD")
    out_path = output_dir / "vtd_elections_2022.parquet"

    shp_path, tmpdir = _extract_shp_to_tmpdir(input_dir / BLOCKS_2022_ZIP, BLOCKS_2022_SHP)
    try:
        _log("  Reading 2022 block attribute table (no geometry)…")
        df = gpd.read_file(shp_path, columns=COLS_2022, engine="pyogrio", ignore_geometry=True)
        _log(f"  Loaded {len(df):,} rows × {len(df.columns)} columns")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # Convert vote columns to float (they come in as object sometimes)
    vote_cols = [c for c in COLS_2022 if c not in ("GEOID20",)]
    df[vote_cols] = df[vote_cols].apply(pd.to_numeric, errors="coerce").fillna(0)

    # Join to VTD lookup
    df = df.merge(lookup, left_on="GEOID20", right_on="block_GEOID20", how="left")
    unmatched = df["vtd_GEOID20"].isna().sum()
    if unmatched:
        _log(f"  WARNING: {unmatched} blocks have no VTD assignment — dropped from aggregation")
    df = df.dropna(subset=["vtd_GEOID20"])

    # Aggregate: sum all numeric columns by VTD
    agg_cols = [c for c in COLS_2022 if c != "GEOID20"]
    vtd_df = df.groupby("vtd_GEOID20")[agg_cols].sum().reset_index()
    vtd_df = vtd_df.rename(columns={"vtd_GEOID20": "GEOID20"})

    # Derived: two-party vote shares for key races
    vtd_df = _add_2pv(vtd_df, "gov22", "G22GOVDABR", "G22GOVRKEM")
    vtd_df = _add_2pv(vtd_df, "uss22", "G22USSDWAR", "G22USSRWAL")
    vtd_df = _add_2pv(vtd_df, "atg22", "G22ATGDJOR", "G22ATGRCAR")
    vtd_df = _add_2pv(vtd_df, "sos22", "G22SOSDNGU", "G22SOSRRAF")
    vtd_df = _add_2pv(vtd_df, "ltg22", "G22LTGDBAI", "G22LTGRJON")

    vtd_df.to_parquet(out_path, index=False)
    _log(f"  {len(vtd_df):,} VTDs  ×  {len(vtd_df.columns)} columns  →  {out_path}")
    _check_totals_2022(vtd_df)
    return vtd_df


# ── Step 3: Aggregate 2024 elections ──────────────────────────────────────────

def build_elections_2024(input_dir: Path, output_dir: Path, lookup: pd.DataFrame) -> pd.DataFrame:
    """Load 2024 block election data, aggregate to VTD."""
    _log("\n[3/4] Aggregating 2024 general election to VTD")
    out_path = output_dir / "vtd_elections_2024.parquet"

    shp_path, tmpdir = _extract_shp_to_tmpdir(input_dir / BLOCKS_2024_ZIP, BLOCKS_2024_SHP)
    try:
        _log("  Reading 2024 block attribute table (no geometry)…")
        df = gpd.read_file(shp_path, columns=COLS_2024, engine="pyogrio", ignore_geometry=True)
        _log(f"  Loaded {len(df):,} rows × {len(df.columns)} columns")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    vote_cols = [c for c in COLS_2024 if c not in ("GEOID20",)]
    df[vote_cols] = df[vote_cols].apply(pd.to_numeric, errors="coerce").fillna(0)

    df = df.merge(lookup, left_on="GEOID20", right_on="block_GEOID20", how="left")
    df = df.dropna(subset=["vtd_GEOID20"])

    agg_cols = [c for c in COLS_2024 if c != "GEOID20"]
    vtd_df = df.groupby("vtd_GEOID20")[agg_cols].sum().reset_index()
    vtd_df = vtd_df.rename(columns={"vtd_GEOID20": "GEOID20"})

    vtd_df = _add_2pv(vtd_df, "pre24", "G24PREDHAR", "G24PRERTRU")

    vtd_df.to_parquet(out_path, index=False)
    _log(f"  {len(vtd_df):,} VTDs  ×  {len(vtd_df.columns)} columns  →  {out_path}")
    _check_totals_2024(vtd_df)
    return vtd_df


# ── Step 4: Aggregate CVAP ─────────────────────────────────────────────────────

def build_cvap(input_dir: Path, output_dir: Path, lookup: pd.DataFrame) -> pd.DataFrame:
    """Load CVAP block CSV (no geometry), aggregate to VTD."""
    _log("\n[4/4] Aggregating CVAP to VTD")
    out_path = output_dir / "vtd_cvap.parquet"

    _log("  Reading CVAP CSV from zip…")
    with zipfile.ZipFile(input_dir / CVAP_ZIP) as zf:
        with zf.open(CVAP_CSV) as f:
            cvap_df = pd.read_csv(f, usecols=CVAP_COLS, dtype={"GEOID20": str})
    _log(f"  Loaded {len(cvap_df):,} blocks")

    # Pad GEOID20 to 15 chars (leading zeros sometimes dropped)
    cvap_df["GEOID20"] = cvap_df["GEOID20"].str.zfill(15)

    cvap_cols = [c for c in CVAP_COLS if c != "GEOID20"]
    cvap_df[cvap_cols] = cvap_df[cvap_cols].apply(pd.to_numeric, errors="coerce").fillna(0)

    df = cvap_df.merge(lookup, left_on="GEOID20", right_on="block_GEOID20", how="left")
    unmatched = df["vtd_GEOID20"].isna().sum()
    if unmatched:
        _log(f"  WARNING: {unmatched} CVAP blocks unmatched — dropped")
    df = df.dropna(subset=["vtd_GEOID20"])

    vtd_df = df.groupby("vtd_GEOID20")[cvap_cols].sum().reset_index()
    vtd_df = vtd_df.rename(columns={"vtd_GEOID20": "GEOID20"})

    # Derived BVAP % and HVAP % (useful for VRA analysis)
    tot = vtd_df["CVAP_TOT24"].replace(0, pd.NA)
    vtd_df["bvap_pct24"] = (vtd_df["CVAP_BLK24"] / tot * 100).round(2)
    vtd_df["hvap_pct24"] = (vtd_df["CVAP_HSP24"] / tot * 100).round(2)
    vtd_df["wvap_pct24"] = (vtd_df["CVAP_WHT24"] / tot * 100).round(2)

    vtd_df.to_parquet(out_path, index=False)
    _log(f"  {len(vtd_df):,} VTDs  ×  {len(vtd_df.columns)} columns  →  {out_path}")
    return vtd_df


# ── Combine ────────────────────────────────────────────────────────────────────

def build_combined(output_dir: Path,
                   df22: pd.DataFrame,
                   df24: pd.DataFrame,
                   cvap_df: pd.DataFrame) -> pd.DataFrame:
    """Outer-join all three VTD tables on GEOID20."""
    _log("\n[Combine] Building vtd_combined.parquet")
    out_path = output_dir / "vtd_combined.parquet"

    # Start from 2022 (most elections, most complete)
    combined = df22.copy()
    # Drop VAP_MOD duplicate — keep from 2022 (same denominator)
    combined = combined.merge(
        df24.drop(columns=["VAP_MOD"], errors="ignore"),
        on="GEOID20", how="outer",
    )
    combined = combined.merge(cvap_df, on="GEOID20", how="outer")

    combined.to_parquet(out_path, index=False)
    _log(f"  {len(combined):,} VTDs  ×  {len(combined.columns)} columns  →  {out_path}")
    _log("\n  Columns in vtd_combined.parquet:")
    for col in sorted(combined.columns):
        _log(f"    {col}")
    return combined


# ── Helpers ────────────────────────────────────────────────────────────────────

def _add_2pv(df: pd.DataFrame, race: str, dem_col: str, rep_col: str) -> pd.DataFrame:
    """Add two-party vote share columns (dem_2pv_<race>, rep_2pv_<race>)."""
    total_2p = df[dem_col] + df[rep_col]
    df[f"dem_2pv_{race}"] = (df[dem_col] / total_2p.replace(0, pd.NA) * 100).round(4)
    df[f"rep_2pv_{race}"] = (df[rep_col] / total_2p.replace(0, pd.NA) * 100).round(4)
    return df


# Statewide certified totals for sanity checks (from GA SOS)
_SOS_2022 = {
    "gov_abrams":  1326916,
    "gov_kemp":    2112319,
    "uss_warnock": 1945370,  # Nov 8 general
    "uss_walker":  1908442,
}
_SOS_2024 = {
    "pre_harris": 2197292,
    "pre_trump":  2209525,
}


def _check_totals_2022(df: pd.DataFrame) -> None:
    checks = [
        ("G22GOVDABR", "gov_abrams",  _SOS_2022["gov_abrams"]),
        ("G22GOVRKEM", "gov_kemp",    _SOS_2022["gov_kemp"]),
        ("G22USSDWAR", "uss_warnock", _SOS_2022["uss_warnock"]),
        ("G22USSRWAL", "uss_walker",  _SOS_2022["uss_walker"]),
    ]
    _log("  Vote-total check vs GA SOS certified results:")
    for col, label, expected in checks:
        got = int(df[col].sum())
        pct_diff = abs(got - expected) / expected * 100
        flag = "✓" if pct_diff < 0.5 else "⚠"
        _log(f"    {flag} {label}: {got:,} vs {expected:,} ({pct_diff:.2f}% diff)")


def _check_totals_2024(df: pd.DataFrame) -> None:
    checks = [
        ("G24PREDHAR", "pre_harris", _SOS_2024["pre_harris"]),
        ("G24PRERTRU", "pre_trump",  _SOS_2024["pre_trump"]),
    ]
    _log("  Vote-total check vs GA SOS certified results:")
    for col, label, expected in checks:
        got = int(df[col].sum())
        pct_diff = abs(got - expected) / expected * 100
        flag = "✓" if pct_diff < 0.5 else "⚠"
        _log(f"    {flag} {label}: {got:,} vs {expected:,} ({pct_diff:.2f}% diff)")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR),
                    help="Directory containing the raw zip files from Google Drive")
    ap.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR),
                    help="Directory to write VTD parquet output files")
    ap.add_argument("--skip-lookup", action="store_true",
                    help="Reuse existing block_vtd_lookup.parquet (fastest if it already exists)")
    ap.add_argument("--only", choices=["lookup", "elections2022", "elections2024", "cvap"],
                    help="Run only one step (still requires lookup to exist for non-lookup steps)")
    args = ap.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    # Validate input dir
    if not input_dir.exists():
        print(f"ERROR: Input directory not found: {input_dir}")
        print("Make sure the Google Drive is mounted at /mnt/g/ in WSL.")
        sys.exit(1)

    # Verify required zip files
    required = [VTD_ZIP, BLOCKS_2022_ZIP, BLOCKS_2024_ZIP, CVAP_ZIP]
    missing = [f for f in required if not (input_dir / f).exists()]
    if missing:
        print("ERROR: Missing input files:")
        for f in missing:
            print(f"  {input_dir / f}")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    _log(f"Input:  {input_dir}")
    _log(f"Output: {output_dir}")

    # ── Run pipeline ──
    if args.only == "lookup":
        build_lookup(input_dir, output_dir)
        return

    lookup = load_or_build_lookup(input_dir, output_dir, skip_rebuild=args.skip_lookup)

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
    df22  = build_elections_2022(input_dir, output_dir, lookup)
    df24  = build_elections_2024(input_dir, output_dir, lookup)
    cvap  = build_cvap(input_dir, output_dir, lookup)
    build_combined(output_dir, df22, df24, cvap)

    _log("\nDone. To join into R:")
    _log("  library(arrow); vtd <- read_parquet('data/repos/main/vtd/vtd_combined.parquet')")
    _log("  map_data <- left_join(GA_cd_2020_map, vtd, by = c('GEOID' = 'GEOID20'))")


if __name__ == "__main__":
    main()
