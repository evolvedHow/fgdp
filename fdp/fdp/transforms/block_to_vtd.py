"""
Block → VTD spatial aggregation.

2020 Census blocks nest perfectly within 2020 VTDs by design, so the join
is done via centroid-in-polygon (block centroid falls inside exactly one VTD).

The lookup is cached as a parquet file — build it once (~3-5 min), reuse it.

Typical usage
-------------
    from fdp.transforms.block_to_vtd import build_lookup, aggregate_to_vtd

    # Build once (slow — spatial join of 232K blocks):
    lookup = build_lookup(vtd_zip, blocks_zip, blocks_shp_inner, output_path)

    # Aggregate fast thereafter:
    vtd_df = aggregate_to_vtd(blocks_df, lookup, value_cols=["G22GOVDABR", ...])
"""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Callable

import geopandas as gpd
import pandas as pd


# Default projected CRS for Georgia — UTM Zone 16N.
# Always project before computing centroids to avoid "geographic CRS" warning.
_PROJECTED_CRS = "EPSG:32616"


def _log(msg: str, log_fn: Callable[[str], None] | None) -> None:
    if log_fn:
        log_fn(msg)


def _extract_zip_to_tmpdir(zip_path: Path, inner_path: str) -> tuple[Path, Path]:
    """
    Extract a zip archive to a fresh temp directory.

    Parameters
    ----------
    zip_path:   Path to the zip file.
    inner_path: Path of the target file inside the zip (e.g. "subdir/file.shp").

    Returns
    -------
    (file_path, tmpdir_path) — caller is responsible for shutil.rmtree(tmpdir_path).
    """
    tmpdir = Path(tempfile.mkdtemp(prefix="fdp_vtd_"))
    with zipfile.ZipFile(zip_path) as zf:
        # Extract all members so .dbf/.shx/.prj siblings are present too
        zf.extractall(tmpdir)
    return tmpdir / inner_path, tmpdir


def _detect_shp_inner_path(zip_path: Path) -> str:
    """
    Auto-detect the .shp file inside a zip.

    Prefers files at the root; if multiple .shp files exist, returns the first
    alphabetically.  Raises ValueError if none found.
    """
    with zipfile.ZipFile(zip_path) as zf:
        shp_members = [m for m in zf.namelist() if m.endswith(".shp")]
    if not shp_members:
        raise ValueError(f"No .shp file found inside {zip_path.name}")
    # Prefer shallowest path (fewest slashes)
    shp_members.sort(key=lambda p: (p.count("/"), p))
    return shp_members[0]


def build_lookup(
    vtd_zip: Path,
    blocks_zip: Path,
    blocks_shp_inner: str | None = None,
    vtd_shp_inner: str | None = None,
    output_path: Path | None = None,
    projected_crs: str = _PROJECTED_CRS,
    log_fn: Callable[[str], None] | None = None,
) -> pd.DataFrame:
    """
    Build a block→VTD lookup table via centroid-in-polygon spatial join.

    Parameters
    ----------
    vtd_zip:           Path to the VTD reference zip (e.g. ga_pl2020_vtd.zip).
    blocks_zip:        Path to a block-level shapefile zip that has geometry
                       (e.g. ga_2022_gen_2020_blocks.zip).  Only GEOID20
                       and geometry are read — no vote columns loaded.
    blocks_shp_inner:  Path of the .shp inside blocks_zip (auto-detected if None).
    vtd_shp_inner:     Path of the .shp inside vtd_zip (auto-detected if None).
    output_path:       If given, write the lookup to this parquet file.
    projected_crs:     CRS string used for centroid calculation.
    log_fn:            Optional callable(str) for progress messages.

    Returns
    -------
    DataFrame with columns: block_GEOID20, vtd_GEOID20
    """
    vtd_zip = Path(vtd_zip)
    blocks_zip = Path(blocks_zip)

    vtd_inner = vtd_shp_inner or _detect_shp_inner_path(vtd_zip)
    blk_inner = blocks_shp_inner or _detect_shp_inner_path(blocks_zip)

    _log(f"  Loading VTD shapefile from {vtd_zip.name}…", log_fn)
    vtd_shp_path, vtd_tmpdir = _extract_zip_to_tmpdir(vtd_zip, vtd_inner)
    try:
        gdf_vtd = gpd.read_file(vtd_shp_path, engine="pyogrio")
        gdf_vtd = gdf_vtd[["GEOID20", "geometry"]].to_crs(projected_crs)
    finally:
        shutil.rmtree(vtd_tmpdir, ignore_errors=True)

    _log(f"  Loading block geometries from {blocks_zip.name}…", log_fn)
    blk_shp_path, blk_tmpdir = _extract_zip_to_tmpdir(blocks_zip, blk_inner)
    try:
        gdf_blocks = gpd.read_file(
            blk_shp_path,
            columns=["GEOID20"],
            engine="pyogrio",
        ).to_crs(projected_crs)
    finally:
        shutil.rmtree(blk_tmpdir, ignore_errors=True)

    _log(f"  Computing centroids ({len(gdf_blocks):,} blocks)…", log_fn)
    gdf_ctr = gdf_blocks.copy()
    gdf_ctr.geometry = gdf_blocks.geometry.centroid

    _log("  Spatial join: block centroids → VTDs…", log_fn)
    joined = gpd.sjoin(
        gdf_ctr,
        gdf_vtd[["GEOID20", "geometry"]],
        how="left",
        predicate="within",
    )

    lookup = (
        joined[["GEOID20_left", "GEOID20_right"]]
        .rename(columns={"GEOID20_left": "block_GEOID20", "GEOID20_right": "vtd_GEOID20"})
        .reset_index(drop=True)
    )

    n_unmatched = lookup["vtd_GEOID20"].isna().sum()
    if n_unmatched:
        _log(f"  Warning: {n_unmatched:,} blocks had no matching VTD (water/boundary edge cases)", log_fn)

    _log(f"  Lookup: {len(lookup):,} block→VTD pairs", log_fn)

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        lookup.to_parquet(output_path, index=False)
        _log(f"  Lookup saved → {output_path}", log_fn)

    return lookup


def aggregate_to_vtd(
    blocks_df: pd.DataFrame,
    lookup: pd.DataFrame,
    value_cols: list[str],
    block_geoid_col: str = "GEOID20",
) -> pd.DataFrame:
    """
    Aggregate block-level numeric columns to VTD level by summing.

    Parameters
    ----------
    blocks_df:       Block-level DataFrame with a GEOID20 column.
    lookup:          DataFrame with block_GEOID20 → vtd_GEOID20 mapping
                     (produced by build_lookup).
    value_cols:      Columns to aggregate (must all be numeric).
    block_geoid_col: Name of the GEOID column in blocks_df (default "GEOID20").

    Returns
    -------
    DataFrame with GEOID20 (=vtd_GEOID20) + aggregated value_cols.
    """
    merged = blocks_df.merge(
        lookup,
        left_on=block_geoid_col,
        right_on="block_GEOID20",
        how="left",
    )

    n_drop = merged["vtd_GEOID20"].isna().sum()
    if n_drop:
        merged = merged.dropna(subset=["vtd_GEOID20"])

    vtd = (
        merged.groupby("vtd_GEOID20")[value_cols]
        .sum()
        .reset_index()
        .rename(columns={"vtd_GEOID20": "GEOID20"})
    )

    return vtd
