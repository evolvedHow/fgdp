#!/usr/bin/env python3
"""
Build election_results_vtd.parquet from fdensemble/data/vtd_composite.parquet.

The composite parquet only stores two-party vote percentages for individual
races and actual dem/total votes for the composite index. This script derives
dem/rep vote counts for each race and writes the long-format parquet expected
by score_ensemble_plans.py:

  geoid, year, election_type, office, party, votes
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = SCRIPT_DIR.parent / "data" / "repos" / "main"

RACES = [
    # (year, election_type, office, dem_pct_col)
    (2018, "general", "governor", "dem_pct_2018_gov"),
    (2020, "general", "president", "dem_pct_2020_pres"),
    (2021, "runoff", "senate", "dem_pct_2021_war_runoff"),
    (2022, "general", "governor", "dem_pct_2022_gov"),
    (2022, "general", "senate", "dem_pct_2022_uss"),
    (2024, "general", "president", "dem_pct_2024_pres"),
]


def main() -> None:
    data_dir = DEFAULT_DATA_DIR
    out_path = data_dir / "election_results_vtd.parquet"

    composite_path = Path(__file__).resolve().parent.parent.parent / "fdensemble" / "data" / "vtd_composite.parquet"
    print(f"Reading {composite_path.name} ...")
    df = pd.read_parquet(composite_path)

    rows = []
    # Composite index
    for _, r in df.iterrows():
        rows.append({
            "geoid": r["GEOID20"],
            "year": 0,
            "election_type": "composite",
            "office": "composite",
            "party": "dem",
            "votes": int(round(r["actual_dem_votes"])),
        })
        rows.append({
            "geoid": r["GEOID20"],
            "year": 0,
            "election_type": "composite",
            "office": "composite",
            "party": "rep",
            "votes": int(round(r["actual_total_votes"] - r["actual_dem_votes"])),
        })

    # Individual races (derive votes from actual total votes × dem pct)
    for year, etype, office, pct_col in RACES:
        print(f"  building {year} {etype} {office} ...")
        total = df["actual_total_votes"].fillna(0).to_numpy()
        dem_pct = df[pct_col].fillna(0).to_numpy()
        dem_votes = np.round(total * dem_pct).astype(int)
        rep_votes = np.maximum(total - dem_votes, 0)

        for i, geoid in enumerate(df["GEOID20"]):
            rows.append({
                "geoid": geoid,
                "year": year,
                "election_type": etype,
                "office": office,
                "party": "dem",
                "votes": int(dem_votes[i]),
            })
            rows.append({
                "geoid": geoid,
                "year": year,
                "election_type": etype,
                "office": office,
                "party": "rep",
                "votes": int(rep_votes[i]),
            })

    out = pd.DataFrame(rows)
    out["votes"] = out["votes"].astype(int)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_path, index=False)
    print(f"Wrote {out_path}  ({len(out):,} rows)")


if __name__ == "__main__":
    main()
