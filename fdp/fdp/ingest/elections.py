"""
Election data ingestor — converts RDH block-level election zip → parquet.

RDH column naming convention
-----------------------------
  {prefix}{YY}{RACE}{PARTY}{NAME3}

  prefix: G = general, R = runoff, S = special election
  YY:     2-digit year  (22, 24, 20, 21 …)
  RACE:   GOV, USS, ATG, SOS, LTG, PRE, PSC …
  PARTY:  D = Dem, R = Rep, L = Lib, G = Green, I = Ind
  NAME3:  3-char candidate surname

Examples
  G22GOVDABR  → 2022 general, Governor, Democrat, Abrams
  G24PRERTRU  → 2024 general, President, Republican, Trump
  R21USSDWAR  → 2021 runoff, US Senate, Democrat, Warnock

Always-present columns in RDH files
  GEOID20   → 15-char 2020 block GEOID
  VAP_MOD   → P0040001 − P0050003  (VAP minus incarcerated pop)
"""

from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Callable

import geopandas as gpd
import pandas as pd


# Regex matching any RDH election column (G/R/S prefix + 2-digit year + rest)
_RDH_COL_RE = re.compile(r"^[GRS]\d{2}[A-Z]")

# Always-needed metadata columns
_META_COLS = ["GEOID20", "VAP_MOD"]


def _log(msg: str, log_fn: Callable[[str], None] | None) -> None:
    if log_fn:
        log_fn(msg)


def _detect_shp_inner(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        shp_members = [m for m in zf.namelist() if m.endswith(".shp")]
    if not shp_members:
        raise ValueError(f"No .shp file found in {zip_path.name}")
    shp_members.sort(key=lambda p: (p.count("/"), p))
    return shp_members[0]


def probe_columns(zip_path: Path, shp_inner: str | None = None) -> list[str]:
    """Return the column names in an RDH election zip without loading all data."""
    inner = shp_inner or _detect_shp_inner(zip_path)
    tmpdir = Path(tempfile.mkdtemp(prefix="fdp_probe_"))
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmpdir)
        shp_path = tmpdir / inner
        df = gpd.read_file(shp_path, engine="pyogrio", ignore_geometry=True, rows=0)
        return list(df.columns)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def select_election_cols(
    available: list[str],
    year: int | None = None,
    election_type: str | None = None,
) -> list[str]:
    """
    From the full column list, return the election columns to extract.

    Filters by year prefix (e.g. year=2022 → G22*, R22*) when given.
    Always includes GEOID20 and VAP_MOD.
    """
    # Build year prefix filter
    year_prefixes: set[str] | None = None
    if year is not None:
        yy = str(year)[-2:]
        # adjacent year for runoffs: 2020 general → could have R21 runoffs
        yy_next = str(year + 1)[-2:]
        if election_type == "runoff":
            year_prefixes = {yy}
        else:
            # General year may have runoffs in Jan of the following year (e.g. 2021 from 2020)
            year_prefixes = {yy, yy_next}

    kept = list(_META_COLS)
    for col in available:
        if col in kept:
            continue
        if not _RDH_COL_RE.match(col):
            continue
        if year_prefixes is not None:
            col_yy = col[1:3]
            if col_yy not in year_prefixes:
                continue
        kept.append(col)

    return kept


def ingest_election_zip(
    zip_path: Path,
    year: int | None = None,
    election_type: str | None = "general",
    shp_inner: str | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Read an RDH block-level election zip and return a clean DataFrame.

    Parameters
    ----------
    zip_path:      Path to the RDH zip file.
    year:          Election year (used to filter columns; None = keep all).
    election_type: 'general' | 'runoff' | 'special' | None.
    shp_inner:     Path of .shp inside zip (auto-detected if None).
    log_fn:        Optional callable for progress messages.

    Returns
    -------
    (DataFrame, election_columns)
    DataFrame has GEOID20, VAP_MOD, and all detected election columns.
    election_columns is the list of columns beyond the metadata pair.
    """
    zip_path = Path(zip_path)
    inner = shp_inner or _detect_shp_inner(zip_path)

    _log(f"  Probing columns in {zip_path.name}…", log_fn)
    all_cols = probe_columns(zip_path, inner)

    cols_to_read = select_election_cols(all_cols, year=year, election_type=election_type)
    election_cols = [c for c in cols_to_read if c not in _META_COLS]

    if not election_cols:
        raise ValueError(
            f"No election columns found in {zip_path.name} "
            f"(year={year}, type={election_type}).  "
            f"Available: {[c for c in all_cols if _RDH_COL_RE.match(c)][:10]}"
        )

    _log(f"  Found {len(election_cols)} election columns (e.g. {election_cols[:3]}…)", log_fn)
    _log(f"  Reading {len(cols_to_read)} columns (no geometry)…", log_fn)

    tmpdir = Path(tempfile.mkdtemp(prefix="fdp_ingest_"))
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmpdir)
        shp_path = tmpdir / inner
        df = gpd.read_file(
            shp_path,
            columns=cols_to_read,
            engine="pyogrio",
            ignore_geometry=True,
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    _log(f"  Loaded {len(df):,} blocks × {len(df.columns)} columns", log_fn)

    # Coerce election columns to numeric
    df[election_cols] = df[election_cols].apply(pd.to_numeric, errors="coerce").fillna(0)
    df["VAP_MOD"] = pd.to_numeric(df["VAP_MOD"], errors="coerce").fillna(0)

    return df, election_cols
