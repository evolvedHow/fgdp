"""
ALARM-ready combined VTD export.

Joins all VTD-level election and CVAP datasets for a state into a single
parquet file suitable for joining to an ALARM redist_map object in R.

R usage
-------
    library(arrow)
    vtd <- read_parquet("output/vtd/ga_alarm_combined.parquet")
    map_data <- left_join(GA_cd_2020_map, vtd, by = c("GEOID" = "GEOID20"))

The join key is GEOID20 (11-char: SS+CCC+VVVVVV), which matches the ALARM
map's GEOID column directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pandas as pd


def _log(msg: str, log_fn: Callable[[str], None] | None) -> None:
    if log_fn:
        log_fn(msg)


def add_two_party_vote_share(
    df: pd.DataFrame,
    race: str,
    dem_col: str,
    rep_col: str,
) -> pd.DataFrame:
    """
    Add dem_2pv_{race} and rep_2pv_{race} columns (percentage, 4 decimal places).

    Uses only D + R votes in the denominator (excludes 3rd-party candidates).
    VTDs with zero total two-party votes get NaN (not 0).
    """
    total = (df[dem_col] + df[rep_col]).replace(0, float("nan"))
    df[f"dem_2pv_{race}"] = (df[dem_col] / total * 100).round(4)
    df[f"rep_2pv_{race}"] = (df[rep_col] / total * 100).round(4)
    return df


# Map of well-known election column pairs to add 2PV for.
# key = race label, value = (dem_col, rep_col)
_KNOWN_2PV: dict[str, tuple[str, str]] = {
    "gov22":   ("G22GOVDABR", "G22GOVRKEM"),
    "uss22":   ("G22USSDWAR", "G22USSRWAL"),
    "atg22":   ("G22ATGDJOR", "G22ATGRCAR"),
    "sos22":   ("G22SOSDNGU", "G22SOSRRAF"),
    "ltg22":   ("G22LTGDBAI", "G22LTGRJON"),
    "pre24":   ("G24PREDHAR", "G24PRERTRU"),
    "ussR21a": ("R21USSDOSS", "R21USSRPER"),
    "ussR21b": ("R21USSDWAR", "R21USSRLOE"),
}


def build_combined(
    vtd_parquets: list[Path],
    output_path: Path,
    add_2pv: bool = True,
    log_fn: Callable[[str], None] | None = None,
) -> pd.DataFrame:
    """
    Join multiple VTD-level parquet files on GEOID20 into one combined file.

    Parameters
    ----------
    vtd_parquets:  List of paths to VTD-level parquet files.
                   First file becomes the left table; all others are outer-joined.
    output_path:   Where to write the combined parquet.
    add_2pv:       If True, add two-party vote share columns for known races.
    log_fn:        Optional callable for progress messages.

    Returns
    -------
    Combined DataFrame (also written to output_path).
    """
    if not vtd_parquets:
        raise ValueError("No VTD parquet files provided to combine.")

    _log(f"  Joining {len(vtd_parquets)} VTD datasets…", log_fn)

    combined: pd.DataFrame | None = None
    for pq in vtd_parquets:
        pq = Path(pq)
        _log(f"    + {pq.name}", log_fn)
        df = pd.read_parquet(pq)

        if combined is None:
            combined = df
        else:
            # Drop duplicate VAP_MOD if present in right table
            right = df.drop(columns=["VAP_MOD"], errors="ignore")
            combined = combined.merge(right, on="GEOID20", how="outer")

    assert combined is not None

    if add_2pv:
        for race, (dem_col, rep_col) in _KNOWN_2PV.items():
            if dem_col in combined.columns and rep_col in combined.columns:
                combined = add_two_party_vote_share(combined, race, dem_col, rep_col)
                _log(f"    added 2PV for {race}", log_fn)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(output_path, index=False)

    _log(f"  Combined: {len(combined):,} VTDs × {len(combined.columns)} cols → {output_path}", log_fn)
    _log("\n  Columns:", log_fn)
    for col in combined.columns:
        _log(f"    {col}", log_fn)

    return combined
