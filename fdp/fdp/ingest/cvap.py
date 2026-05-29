"""
CVAP data ingestor — converts RDH block-level CVAP CSV zip → parquet.

The RDH disaggregates ACS CVAP estimates to 2020 census blocks using
VAP_MOD weights.  Column names encode the ACS vintage year (e.g. CVAP_TOT24
for the 2020–2024 5-year ACS).

Key CVAP columns
-----------------
  GEOID20     → 15-char 2020 block GEOID
  CVAP_TOT{Y} → Total CVAP
  CVAP_BLK{Y} → Black or African American alone CVAP
  CVAP_BLA{Y} → Black alone or in combination CVAP  (broadest Black measure)
  CVAP_HSP{Y} → Hispanic or Latino CVAP
  CVAP_WHT{Y} → White alone (non-Hispanic) CVAP
  CVAP_ASN{Y} → Asian alone or in combination CVAP
  CVAP_AMI{Y} → American Indian / Alaska Native alone or in combo CVAP
  CVAP_NHP{Y} → Native Hawaiian / Pacific Islander alone or in combo CVAP

Where {Y} is the 2-digit ACS end year (e.g. 24 for 2020–2024 ACS).
"""

from __future__ import annotations

import zipfile
from io import TextIOWrapper
from pathlib import Path
from typing import Callable

import pandas as pd


# Columns we always want, in this preferred order
_KEY_PREFIXES = ["CVAP_TOT", "CVAP_BLK", "CVAP_BLA", "CVAP_HSP", "CVAP_WHT",
                 "CVAP_ASN", "CVAP_AMI", "CVAP_NHP"]


def _log(msg: str, log_fn: Callable[[str], None] | None) -> None:
    if log_fn:
        log_fn(msg)


def _detect_csv_inner(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        csv_members = [m for m in zf.namelist() if m.endswith(".csv")]
    if not csv_members:
        raise ValueError(f"No .csv file found in {zip_path.name}")
    csv_members.sort(key=lambda p: (p.count("/"), p))
    return csv_members[0]


def ingest_cvap_zip(
    zip_path: Path,
    year: int | None = None,
    csv_inner: str | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Read an RDH block-level CVAP CSV zip and return a clean DataFrame.

    Parameters
    ----------
    zip_path:  Path to the CVAP zip file.
    year:      ACS end year (e.g. 2024).  Used to filter columns; None = keep all.
    csv_inner: Path of the CSV inside the zip (auto-detected if None).
    log_fn:    Optional callable for progress messages.

    Returns
    -------
    (DataFrame, cvap_columns)
    DataFrame has GEOID20 + CVAP columns.
    cvap_columns is the list of CVAP columns beyond GEOID20.
    """
    zip_path = Path(zip_path)
    inner = csv_inner or _detect_csv_inner(zip_path)

    _log(f"  Reading CVAP CSV from {zip_path.name}/{inner}…", log_fn)

    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(inner) as raw:
            df = pd.read_csv(TextIOWrapper(raw, encoding="utf-8"), dtype=str)

    _log(f"  Loaded {len(df):,} rows × {len(df.columns)} columns", log_fn)

    # Determine year suffix
    yy: str | None = None
    if year is not None:
        yy = str(year)[-2:]
    else:
        # Auto-detect from column names
        for col in df.columns:
            for prefix in _KEY_PREFIXES:
                if col.startswith(prefix):
                    yy = col[len(prefix):]
                    break
            if yy:
                break

    # Select columns
    wanted_cvap = []
    for col in df.columns:
        for prefix in _KEY_PREFIXES:
            if col.startswith(prefix):
                if yy is None or col.endswith(yy):
                    wanted_cvap.append(col)
                break

    if not wanted_cvap:
        raise ValueError(
            f"No CVAP columns found in {zip_path.name} "
            f"(year={year}, detected suffix={yy!r}). "
            f"Available columns: {list(df.columns[:10])}"
        )

    # Keep GEOID20 + CVAP cols
    geoid_col = "GEOID20" if "GEOID20" in df.columns else df.columns[0]
    keep_cols = [geoid_col] + [c for c in wanted_cvap if c != geoid_col]
    df = df[keep_cols].copy()

    # Coerce CVAP columns to numeric
    cvap_cols = [c for c in keep_cols if c != geoid_col]
    df[cvap_cols] = df[cvap_cols].apply(pd.to_numeric, errors="coerce").fillna(0)

    _log(f"  Kept {len(cvap_cols)} CVAP columns: {cvap_cols}", log_fn)
    return df, cvap_cols
