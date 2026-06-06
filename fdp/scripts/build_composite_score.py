#!/usr/bin/env python3
"""
build_composite_score.py — Build a single composite partisan score per VTD.

For each census block, compute the average Dem/Rep/Other vote share across 6 elections:
  1. 2018 Governor          (VTD-level from election_results_vtd.parquet)
  2. 2020 President         (block-level from ga_2020gen_2021runoff_2020blocks_csv.zip)
  3. 2021 Warnock Runoff    (block-level from ga_2020gen_2021runoff_2020blocks_csv.zip)
  4. 2022 Governor          (block-level from ga-2022-general-election-block.parquet)
  5. 2022 US Senate         (block-level from ga-2022-general-election-block.parquet)
  6. 2024 President         (block-level from ga-2024-general-election-block.parquet)

2022 Governor and 2022 US Senate are treated as separate elections (not averaged together),
giving each equal 1/6 weight in the composite alongside the other four.

The per-block composite is then aggregated to VTD using total-votes weighting.

Outputs:
  fdp/data/repos/main/vtd/vtd_composite.parquet
    GEOID20, composite_dem_pct, composite_rep_pct, composite_other_pct,
    composite_dem_2pv, dem_pct_2018_gov, dem_pct_2020_pres,
    dem_pct_2021_war_runoff, dem_pct_2022_gov, dem_pct_2022_uss,
    dem_pct_2024_pres, VAP_MOD

  Synthetic rows appended to election_results_vtd.parquet (year=0, office='composite')

Usage (from fgdp/ root):
    uv run --project fdp python fdp/scripts/build_composite_score.py
    uv run --project fdp python fdp/scripts/build_composite_score.py --dry-run
"""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

_SCRIPT_DIR   = Path(__file__).resolve().parent
_DATA_DIR     = _SCRIPT_DIR.parent / "data/repos/main"
_VTD_DIR      = _DATA_DIR / "vtd"
_BLOCK_DIR    = _DATA_DIR / "block"
_INPUT_DIR    = Path(__file__).resolve().parents[2] / "fdensemble/input_data"

# Source files
_VTD_SHP          = _INPUT_DIR / "ga_pl2020_vtd.zip"
_CSV_ZIP_2020     = _INPUT_DIR / "ga_2020gen_2021runoff_2020blocks_csv.zip"
_PARQUET_2022     = _BLOCK_DIR / "ga-2022-general-election-block.parquet"
_PARQUET_2024     = _BLOCK_DIR / "ga-2024-general-election-block.parquet"
_ELECTION_VTD     = _DATA_DIR / "election_results_vtd.parquet"
_BLOCK_VTD_LOOKUP = _VTD_DIR / "block_vtd_lookup.parquet"

# Outputs
_COMPOSITE_OUT    = _VTD_DIR / "vtd_composite.parquet"


# ── Election loaders ──────────────────────────────────────────────────────────

def _load_2020_pres_and_2021_war(csv_zip: Path) -> pd.DataFrame:
    """
    Load 2020 President and 2021 Warnock runoff vote shares from the
    ga_2020_gen_2020_blocks_csv.zip file.

    Returns DataFrame with columns:
      GEOID20, dem_pct_2020_pres, rep_pct_2020_pres, total_2020,
      dem_pct_2021_war_runoff, rep_pct_2021_war_runoff, total_2021
    """
    print(f"  Loading 2020 Pres + 2021 Warnock runoff from {csv_zip.name} …")
    needed = ["GEOID20", "G20PREDBID", "G20PRERTRU", "G20PRELJOR",
              "R21USSDWAR", "R21USSRLOE"]

    with zipfile.ZipFile(csv_zip) as z:
        csv_name = next(n for n in z.namelist() if n.endswith(".csv"))
        df = pd.read_csv(z.open(csv_name), usecols=needed, dtype={"GEOID20": str})

    df["GEOID20"] = df["GEOID20"].str.zfill(15)

    # 2020 President — 2-party only (ignore Jorgensen L); standard redistricting practice
    df["total_2020"] = df["G20PREDBID"] + df["G20PRERTRU"]
    with np.errstate(invalid="ignore", divide="ignore"):
        df["dem_pct_2020_pres"] = np.where(df["total_2020"] > 0,
                                            df["G20PREDBID"] / df["total_2020"], np.nan)
        df["rep_pct_2020_pres"] = np.where(df["total_2020"] > 0,
                                            df["G20PRERTRU"] / df["total_2020"], np.nan)

    # 2021 Warnock runoff (2-party: Warnock D vs Loeffler R)
    df["total_2021"] = df["R21USSDWAR"] + df["R21USSRLOE"]
    with np.errstate(invalid="ignore", divide="ignore"):
        df["dem_pct_2021_war_runoff"] = np.where(df["total_2021"] > 0,
                                                   df["R21USSDWAR"] / df["total_2021"], np.nan)
        df["rep_pct_2021_war_runoff"] = np.where(df["total_2021"] > 0,
                                                   df["R21USSRLOE"] / df["total_2021"], np.nan)

    keep = ["GEOID20",
            "dem_pct_2020_pres", "rep_pct_2020_pres", "total_2020",
            "dem_pct_2021_war_runoff", "rep_pct_2021_war_runoff", "total_2021"]
    print(f"    {len(df):,} blocks, 2020 turnout sum: {df['total_2020'].sum():,.0f}")
    return df[keep].copy()


def _load_2022(parquet: Path) -> pd.DataFrame:
    """
    Load 2022 Governor and US Senate vote shares as two separate elections.
    Each is treated as an independent input (1/6 weight each) in the composite.

    Returns DataFrame with columns:
      GEOID20, VAP_MOD,
      dem_pct_2022_gov, rep_pct_2022_gov, total_gov22,
      dem_pct_2022_uss, rep_pct_2022_uss, total_uss22
    """
    print(f"  Loading 2022 Gov + USS from {parquet.name} …")
    needed = ["GEOID20", "VAP_MOD",
              "G22GOVDABR", "G22GOVRKEM", "G22GOVLHAZ",
              "G22USSDWAR", "G22USSRWAL", "G22USSLOLI"]
    df = pd.read_parquet(parquet, columns=needed)
    df["GEOID20"] = df["GEOID20"].astype(str).str.zfill(15)

    # Governor: 2-party only (ignore Hazel L ~1%)
    df["total_gov22"] = df["G22GOVDABR"] + df["G22GOVRKEM"]
    with np.errstate(invalid="ignore", divide="ignore"):
        df["dem_pct_2022_gov"] = np.where(df["total_gov22"] > 0,
                                           df["G22GOVDABR"] / df["total_gov22"], np.nan)
        df["rep_pct_2022_gov"] = np.where(df["total_gov22"] > 0,
                                           df["G22GOVRKEM"] / df["total_gov22"], np.nan)

    # US Senate: 2-party only (ignore Oliver L ~2.1% that forced the runoff)
    df["total_uss22"] = df["G22USSDWAR"] + df["G22USSRWAL"]
    with np.errstate(invalid="ignore", divide="ignore"):
        df["dem_pct_2022_uss"] = np.where(df["total_uss22"] > 0,
                                           df["G22USSDWAR"] / df["total_uss22"], np.nan)
        df["rep_pct_2022_uss"] = np.where(df["total_uss22"] > 0,
                                           df["G22USSRWAL"] / df["total_uss22"], np.nan)

    keep = ["GEOID20", "VAP_MOD",
            "dem_pct_2022_gov", "rep_pct_2022_gov", "total_gov22",
            "dem_pct_2022_uss", "rep_pct_2022_uss", "total_uss22"]
    print(f"    {len(df):,} blocks, 2022 Gov turnout: {df['total_gov22'].sum():,.0f}  "
          f"USS turnout: {df['total_uss22'].sum():,.0f}")
    return df[keep].copy()


def _load_2024(parquet: Path) -> pd.DataFrame:
    """
    Load 2024 President vote shares.

    Returns DataFrame with columns:
      GEOID20, dem_pct_2024_pres, rep_pct_2024_pres, total_2024
    """
    print(f"  Loading 2024 Pres from {parquet.name} …")
    needed = ["GEOID20",
              "G24PREDHAR", "G24PRERTRU", "G24PRELOLI",
              "G24PREGSTE", "G24PREICRU", "G24PREIWES"]
    df = pd.read_parquet(parquet, columns=needed)
    df["GEOID20"] = df["GEOID20"].astype(str).str.zfill(15)

    # 2024 President — 2-party only (ignore Oliver L, Stein G, Cruz I, West I)
    df["total_2024"] = df["G24PREDHAR"] + df["G24PRERTRU"]
    with np.errstate(invalid="ignore", divide="ignore"):
        df["dem_pct_2024_pres"] = np.where(df["total_2024"] > 0,
                                            df["G24PREDHAR"] / df["total_2024"], np.nan)
        df["rep_pct_2024_pres"] = np.where(df["total_2024"] > 0,
                                            df["G24PRERTRU"] / df["total_2024"], np.nan)

    keep = ["GEOID20", "dem_pct_2024_pres", "rep_pct_2024_pres", "total_2024"]
    print(f"    {len(df):,} blocks, 2024 turnout sum: {df['total_2024'].sum():,.0f}")
    return df[keep].copy()


def _load_2018_vtd(election_vtd: Path) -> pd.DataFrame:
    """
    Load 2018 Governor vote shares at VTD level.

    Returns DataFrame with columns:
      vtd_GEOID20, dem_pct_2018_gov, rep_pct_2018_gov, total_2018
    """
    print(f"  Loading 2018 Gov (VTD level) from {election_vtd.name} …")
    df = pd.read_parquet(election_vtd)
    gov18 = df[(df["year"] == 2018) &
               (df["election_type"] == "general") &
               (df["office"] == "governor") &
               (df["party"].isin(["dem", "rep"]))]

    wide = gov18.pivot_table(index="geoid", columns="party",
                              values="votes", aggfunc="sum").reset_index()
    wide.columns.name = None
    wide = wide.rename(columns={"geoid": "vtd_GEOID20", "dem": "dem_2018", "rep": "rep_2018"})
    wide["total_2018"] = wide["dem_2018"].fillna(0) + wide["rep_2018"].fillna(0)
    with np.errstate(invalid="ignore", divide="ignore"):
        wide["dem_pct_2018_gov"] = np.where(wide["total_2018"] > 0,
                                             wide["dem_2018"] / wide["total_2018"], np.nan)
        wide["rep_pct_2018_gov"] = np.where(wide["total_2018"] > 0,
                                             wide["rep_2018"] / wide["total_2018"], np.nan)

    keep = ["vtd_GEOID20", "dem_pct_2018_gov", "rep_pct_2018_gov", "total_2018"]
    print(f"    {len(wide):,} VTDs, 2018 turnout sum: {wide['total_2018'].sum():,.0f}")
    return wide[keep].copy()


# ── Main composite builder ────────────────────────────────────────────────────

def build_composite(dry_run: bool = False) -> pd.DataFrame:
    """
    Build VTD-level composite partisan score and return it as a DataFrame.
    Also injects synthetic rows into election_results_vtd.parquet unless dry_run.
    """
    print("\n=== Step 1: Load block-level election data ===")
    df_2020_21 = _load_2020_pres_and_2021_war(_CSV_ZIP_2020)
    df_2022    = _load_2022(_PARQUET_2022)
    df_2024    = _load_2024(_PARQUET_2024)

    print("\n=== Step 2: Load VTD-level 2018 Gov ===")
    df_2018_vtd = _load_2018_vtd(_ELECTION_VTD)

    print("\n=== Step 3: Load block → VTD lookup ===")
    lookup = pd.read_parquet(_BLOCK_VTD_LOOKUP)
    lookup["block_GEOID20"] = lookup["block_GEOID20"].astype(str).str.zfill(15)
    print(f"  {len(lookup):,} blocks → {lookup['vtd_GEOID20'].nunique():,} VTDs")

    print("\n=== Step 4: Join block-level elections ===")
    # Start from lookup (all 232,717 blocks) as the spine
    blocks = lookup.copy()

    # 2022 also carries VAP_MOD for all blocks — merge first to get it
    blocks = blocks.merge(
        df_2022[["GEOID20", "VAP_MOD",
                 "dem_pct_2022_gov", "rep_pct_2022_gov", "total_gov22",
                 "dem_pct_2022_uss", "rep_pct_2022_uss", "total_uss22"]],
        left_on="block_GEOID20", right_on="GEOID20", how="left"
    ).drop(columns="GEOID20")

    blocks = blocks.merge(
        df_2020_21[["GEOID20",
                    "dem_pct_2020_pres", "rep_pct_2020_pres", "total_2020",
                    "dem_pct_2021_war_runoff", "rep_pct_2021_war_runoff", "total_2021"]],
        left_on="block_GEOID20", right_on="GEOID20", how="left"
    ).drop(columns="GEOID20")

    blocks = blocks.merge(
        df_2024[["GEOID20",
                 "dem_pct_2024_pres", "rep_pct_2024_pres", "total_2024"]],
        left_on="block_GEOID20", right_on="GEOID20", how="left"
    ).drop(columns="GEOID20")

    # Attach VTD-level 2018 Gov to every block in that VTD
    blocks = blocks.merge(
        df_2018_vtd[["vtd_GEOID20", "dem_pct_2018_gov", "rep_pct_2018_gov"]],
        on="vtd_GEOID20", how="left"
    )

    print(f"  Combined block table: {len(blocks):,} rows")

    print("\n=== Step 5: Per-block composite (NaN-safe average of 6 elections) ===")
    dem_stack = np.stack([
        blocks["dem_pct_2018_gov"].values,
        blocks["dem_pct_2020_pres"].values,
        blocks["dem_pct_2021_war_runoff"].values,
        blocks["dem_pct_2022_gov"].values,
        blocks["dem_pct_2022_uss"].values,
        blocks["dem_pct_2024_pres"].values,
    ], axis=1)  # (n_blocks, 6)

    rep_stack = np.stack([
        blocks["rep_pct_2018_gov"].values,
        blocks["rep_pct_2020_pres"].values,
        blocks["rep_pct_2021_war_runoff"].values,
        blocks["rep_pct_2022_gov"].values,
        blocks["rep_pct_2022_uss"].values,
        blocks["rep_pct_2024_pres"].values,
    ], axis=1)

    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        blocks["avg_dem_pct"] = np.nanmean(dem_stack, axis=1)
        blocks["avg_rep_pct"] = np.nanmean(rep_stack, axis=1)

    # Weight for VTD aggregation: average total votes across the 5 block-level elections
    # (2018 Gov is VTD-level, contributes via dem_pct_2018_gov first-value; not in weight sum)
    blocks["weight"] = (
        blocks["total_2020"].fillna(0) +
        blocks["total_2021"].fillna(0) +
        blocks["total_gov22"].fillna(0) +
        blocks["total_uss22"].fillna(0) +
        blocks["total_2024"].fillna(0)
    ) / 5.0

    # Blocks with no participation across any election get zero weight → excluded
    blocks["weight"] = blocks["weight"].clip(lower=0)

    print(f"  Blocks with zero weight: {(blocks['weight'] == 0).sum():,}")
    print(f"  Blocks with valid composite: {(~blocks['avg_dem_pct'].isna()).sum():,}")

    print("\n=== Step 6: Aggregate blocks → VTDs (weighted average) ===")
    # Pre-compute all weighted products as columns (avoids groupby apply overhead)
    blocks["weighted_dem"] = blocks["avg_dem_pct"] * blocks["weight"]
    blocks["weighted_rep"] = blocks["avg_rep_pct"] * blocks["weight"]
    blocks["weighted_vap"] = blocks["VAP_MOD"].fillna(0)

    # Per-election transparency weighted products
    t20  = blocks["total_2020"].fillna(0)
    t21  = blocks["total_2021"].fillna(0)
    tg22 = blocks["total_gov22"].fillna(0)
    tu22 = blocks["total_uss22"].fillna(0)
    t24  = blocks["total_2024"].fillna(0)

    blocks["w_dem_2020"]     = blocks["dem_pct_2020_pres"].fillna(0) * t20
    blocks["w_dem_2021"]     = blocks["dem_pct_2021_war_runoff"].fillna(0) * t21
    blocks["w_dem_2022_gov"] = blocks["dem_pct_2022_gov"].fillna(0) * tg22
    blocks["w_dem_2022_uss"] = blocks["dem_pct_2022_uss"].fillna(0) * tu22
    blocks["w_dem_2024"]     = blocks["dem_pct_2024_pres"].fillna(0) * t24

    vtd = blocks.groupby("vtd_GEOID20").agg(
        sum_weighted_dem=("weighted_dem", "sum"),
        sum_weighted_rep=("weighted_rep", "sum"),
        sum_weight=("weight", "sum"),
        VAP_MOD=("weighted_vap", "sum"),
        dem_pct_2018_gov=("dem_pct_2018_gov", "first"),  # same value for every block in VTD
        # Transparency: per-election weighted numerators + denominators
        wn_2020=("w_dem_2020",     "sum"), wd_2020=("total_2020",   "sum"),
        wn_2021=("w_dem_2021",     "sum"), wd_2021=("total_2021",   "sum"),
        wn_g22 =("w_dem_2022_gov", "sum"), wd_g22 =("total_gov22",  "sum"),
        wn_u22 =("w_dem_2022_uss", "sum"), wd_u22 =("total_uss22",  "sum"),
        wn_2024=("w_dem_2024",     "sum"), wd_2024=("total_2024",   "sum"),
    ).reset_index().rename(columns={"vtd_GEOID20": "GEOID20"})

    # Derive per-election VTD shares
    def _safe_div(n, d): return np.where(d > 0, n / d, np.nan)

    vtd["dem_pct_2020_pres"]       = _safe_div(vtd["wn_2020"], vtd["wd_2020"])
    vtd["dem_pct_2021_war_runoff"] = _safe_div(vtd["wn_2021"], vtd["wd_2021"])
    vtd["dem_pct_2022_gov"]        = _safe_div(vtd["wn_g22"],  vtd["wd_g22"])
    vtd["dem_pct_2022_uss"]        = _safe_div(vtd["wn_u22"],  vtd["wd_u22"])
    vtd["dem_pct_2024_pres"]       = _safe_div(vtd["wn_2024"], vtd["wd_2024"])
    vtd = vtd.drop(columns=["wn_2020","wd_2020","wn_2021","wd_2021",
                              "wn_g22","wd_g22","wn_u22","wd_u22",
                              "wn_2024","wd_2024"])

    with np.errstate(invalid="ignore", divide="ignore"):
        vtd["composite_dem_pct"] = np.where(vtd["sum_weight"] > 0,
                                              vtd["sum_weighted_dem"] / vtd["sum_weight"],
                                              np.nan)
        vtd["composite_rep_pct"] = np.where(vtd["sum_weight"] > 0,
                                              vtd["sum_weighted_rep"] / vtd["sum_weight"],
                                              np.nan)

    vtd["composite_other_pct"] = (1.0 - vtd["composite_dem_pct"] - vtd["composite_rep_pct"]).clip(lower=0)

    # Zero-VAP VTDs (military bases, monuments, water areas) have no turnout
    # in any election → NaN composite.  Fill with 0.5/0.5 so scoring logic
    # doesn't propagate NaN; synthetic votes will be 0 anyway (VAP_MOD=0).
    zero_vap = vtd["VAP_MOD"] == 0
    vtd.loc[zero_vap, "composite_dem_pct"]   = 0.5
    vtd.loc[zero_vap, "composite_rep_pct"]   = 0.5
    vtd.loc[zero_vap, "composite_other_pct"] = 0.0
    if zero_vap.any():
        print(f"  Filled {zero_vap.sum()} zero-VAP VTDs with 0.5 composite")

    # Fill any remaining NaN VTDs (very low VAP with no block coverage) with
    # their county's average composite — these are micro-VTDs like Fort Benning
    # annex or Fulton County administrative polygons (VAP 2–11, no election data).
    nan_mask = vtd["composite_dem_pct"].isna()
    if nan_mask.any():
        vtd["_county"] = vtd["GEOID20"].str[:5]
        county_avg = (vtd[~nan_mask]
                      .groupby("_county")[["composite_dem_pct", "composite_rep_pct"]]
                      .mean())
        for idx in vtd[nan_mask].index:
            county = vtd.loc[idx, "_county"]
            vtd.loc[idx, "composite_dem_pct"] = county_avg.loc[county, "composite_dem_pct"]
            vtd.loc[idx, "composite_rep_pct"] = county_avg.loc[county, "composite_rep_pct"]
        vtd["composite_other_pct"] = (
            1.0 - vtd["composite_dem_pct"] - vtd["composite_rep_pct"]
        ).clip(lower=0)
        vtd = vtd.drop(columns=["_county"])
        print(f"  Filled {nan_mask.sum()} low-VAP NaN VTDs with county average")

    # Two-party vote share for scoring compatibility
    denom = vtd["composite_dem_pct"] + vtd["composite_rep_pct"]
    vtd["composite_dem_2pv"] = np.where(denom > 0,
                                          vtd["composite_dem_pct"] / denom, np.nan)

    # Add VTD centroids from Census interior point fields
    print("\n=== Step 6b: Add VTD centroids ===")
    shp_cols = gpd.read_file(_VTD_SHP, include_fields=["GEOID20", "INTPTLAT20", "INTPTLON20"])
    shp_cols = shp_cols[["GEOID20", "INTPTLAT20", "INTPTLON20"]].copy()
    shp_cols["centroid_lat"] = shp_cols["INTPTLAT20"].astype(str).str.lstrip("+").astype(float).round(6)
    shp_cols["centroid_lon"] = shp_cols["INTPTLON20"].astype(str).str.lstrip("+").astype(float).round(6)
    vtd = vtd.merge(shp_cols[["GEOID20", "centroid_lat", "centroid_lon"]], on="GEOID20", how="left")
    n_missing = vtd["centroid_lat"].isna().sum()
    print(f"  VTDs with centroid: {len(vtd) - n_missing:,}  missing: {n_missing}")

    # Round for readability
    for col in ["composite_dem_pct", "composite_rep_pct", "composite_other_pct",
                "composite_dem_2pv", "dem_pct_2020_pres", "dem_pct_2021_war_runoff",
                "dem_pct_2022_gov", "dem_pct_2022_uss", "dem_pct_2024_pres"]:
        if col in vtd.columns:
            vtd[col] = vtd[col].round(6)
    vtd["VAP_MOD"] = vtd["VAP_MOD"].round(0).astype(int)

    print(f"\n  VTDs in output: {len(vtd):,}  (expected 2,698)")
    print(f"  Statewide composite dem share: {vtd['composite_dem_pct'].mean():.3f}")
    print(f"  Statewide composite dem 2pv:   {vtd['composite_dem_2pv'].mean():.3f}")
    print(f"  NaN composite_dem_pct: {vtd['composite_dem_pct'].isna().sum()}")

    final_cols = [
        "GEOID20", "composite_dem_pct", "composite_rep_pct",
        "composite_other_pct", "composite_dem_2pv",
        "dem_pct_2018_gov", "dem_pct_2020_pres",
        "dem_pct_2021_war_runoff", "dem_pct_2022_gov", "dem_pct_2022_uss",
        "dem_pct_2024_pres", "VAP_MOD",
        "centroid_lat", "centroid_lon",
    ]
    vtd = vtd[[c for c in final_cols if c in vtd.columns]]

    if not dry_run:
        _VTD_DIR.mkdir(parents=True, exist_ok=True)
        vtd.to_parquet(_COMPOSITE_OUT, index=False)
        print(f"\n✓ Saved {_COMPOSITE_OUT}")

        _inject_composite_election(vtd)
    else:
        print("\n[dry-run] Skipping file writes.")
        print(vtd.head(5).to_string())

    return vtd



def _inject_composite_election(vtd: pd.DataFrame) -> None:
    """
    Add/replace composite election rows in election_results_vtd.parquet.

    Composite synthetic votes = composite_dem_pct * VAP_MOD (dem)
                                composite_rep_pct * VAP_MOD (rep)
    Using VAP_MOD as the scalar ensures VTDs with more eligible voters contribute
    proportionally when the scoring pipeline aggregates VTDs → districts.
    """
    print("\n=== Step 7: Inject composite into election_results_vtd.parquet ===")
    existing = pd.read_parquet(_ELECTION_VTD)

    # Remove any previous composite rows
    existing = existing[existing["office"] != "composite"]

    # Build synthetic rows: one dem, one rep per VTD
    # Any remaining NaN VTDs (e.g. all-NaN blocks that aren't zero-VAP) get 0 votes
    dem_votes = (vtd["composite_dem_pct"].fillna(0) * vtd["VAP_MOD"]).round(0).astype(int)
    rep_votes = (vtd["composite_rep_pct"].fillna(0) * vtd["VAP_MOD"]).round(0).astype(int)

    dem_rows = pd.DataFrame({
        "geoid":         vtd["GEOID20"],
        "year":          0,
        "election_type": "composite",
        "office":        "composite",
        "party":         "dem",
        "votes":         dem_votes,
    })
    rep_rows = pd.DataFrame({
        "geoid":         vtd["GEOID20"],
        "year":          0,
        "election_type": "composite",
        "office":        "composite",
        "party":         "rep",
        "votes":         rep_votes,
    })

    updated = pd.concat([existing, dem_rows, rep_rows], ignore_index=True)
    updated.to_parquet(_ELECTION_VTD, index=False)

    n_composite = len(dem_rows) + len(rep_rows)
    print(f"  Added {n_composite:,} composite rows ({len(dem_rows):,} dem + {len(rep_rows):,} rep)")
    print(f"  Total rows in election_results_vtd.parquet: {len(updated):,}")
    print(f"✓ Injected composite election into {_ELECTION_VTD.name}")


# ── Verification helper ───────────────────────────────────────────────────────

def verify(vtd: pd.DataFrame) -> None:
    """Print sanity checks."""
    print("\n=== Verification ===")
    assert len(vtd) == 2698, f"Expected 2,698 VTDs, got {len(vtd)}"

    statewide_dem = vtd["composite_dem_pct"].mean()
    statewide_2pv = vtd["composite_dem_2pv"].mean()
    print(f"  VTD count:          {len(vtd):,}  ✓")
    print(f"  Statewide dem%:     {statewide_dem:.3f}  (expect ~0.46–0.50)")
    print(f"  Statewide dem 2pv:  {statewide_2pv:.3f}  (expect ~0.48–0.52)")

    # Most Dem VTD (urban core)
    top = vtd.nlargest(3, "composite_dem_2pv")[["GEOID20", "composite_dem_2pv"]]
    print(f"  Most Dem VTDs:\n{top.to_string(index=False)}")

    # Most Rep VTD (rural)
    bot = vtd.nsmallest(3, "composite_dem_2pv")[["GEOID20", "composite_dem_2pv"]]
    print(f"  Most Rep VTDs:\n{bot.to_string(index=False)}")

    assert vtd["composite_dem_pct"].isna().sum() == 0, "NaN composite dem pct found"
    assert (vtd["composite_dem_pct"] > 0).all(), "Zero dem pct VTDs found"
    print("  All assertions passed ✓")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="Compute composite but do not write any files")
    ap.add_argument("--data-dir", default=None,
                    help="Override root data directory")
    args = ap.parse_args()

    for f in [_CSV_ZIP_2020, _PARQUET_2022, _PARQUET_2024,
              _ELECTION_VTD, _BLOCK_VTD_LOOKUP]:
        if not f.exists():
            raise FileNotFoundError(f"Required input not found: {f}")

    vtd = build_composite(dry_run=args.dry_run)
    if not args.dry_run:
        verify(vtd)
        print("\nNext steps:")
        print("  1. Re-score ensemble draws:")
        print("     uv run --project fdp python fdp/scripts/score_ensemble_plans.py \\")
        print("         --run-name congress_2026_v2 --races composite")
        print("  2. Build draw stats:")
        print("     uv run --project fdp python fdp/scripts/build_draw_stats.py \\")
        print("         --run-name congress_2026_v2 --thresholds 0.05 0.07")
        print("  3. Build composite scorecard:")
        print("     uv run --project fdp python fdp/scripts/build_scorecard.py \\")
        print("         --run-name congress_2026_v2 --composite")


if __name__ == "__main__":
    main()
