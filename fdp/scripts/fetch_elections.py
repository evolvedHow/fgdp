"""
Fetch and process Georgia election results into the data platform.

Consolidates logic from fdga/scripts/fetch_election_data.py.

Sources:
  - Georgia Secretary of State precinct results (CSV)
  - VEST (Voting and Election Science Team) processed data
  - RDH (Redistricting Data Hub) elections files

Output written to:
  data/repos/main/elections/dim_elections.parquet
  data/repos/main/elections/dim_swings.parquet

Usage:
    uv run python scripts/fetch_elections.py
    uv run python scripts/fetch_elections.py --state GA --year 2022
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))


ELECTION_RACES = [
    ("2020", "president"),
    ("2020", "senate_special"),
    ("2021", "senate_runoff"),
    ("2022", "governor"),
    ("2022", "senate"),
    ("2024", "president"),
]


def process_election_file(csv_path: Path, year: str, race: str) -> pd.DataFrame:
    """
    Read a raw election CSV and return a normalised DataFrame with columns:
      county, year, race, dem_votes, rep_votes, total_votes, dem_pct, rep_pct
    """
    df = pd.read_csv(csv_path)

    # Column discovery — different SOS export formats
    county_col = next((c for c in df.columns if c.lower() in ("county", "county_name", "cnty_name")), None)
    dem_col    = next((c for c in df.columns if "dem" in c.lower() or "biden" in c.lower() or "warnock" in c.lower()), None)
    rep_col    = next((c for c in df.columns if "rep" in c.lower() or "trump" in c.lower() or "loeffler" in c.lower()), None)

    if not all([county_col, dem_col, rep_col]):
        raise ValueError(f"Cannot identify required columns in {csv_path}. Found: {list(df.columns)}")

    result = pd.DataFrame({
        "county":     df[county_col].str.upper().str.strip(),
        "year":       year,
        "race":       race,
        "dem_votes":  pd.to_numeric(df[dem_col], errors="coerce").fillna(0).astype(int),
        "rep_votes":  pd.to_numeric(df[rep_col], errors="coerce").fillna(0).astype(int),
    })
    result["total_votes"] = result["dem_votes"] + result["rep_votes"]
    result["dem_pct"] = (result["dem_votes"] / result["total_votes"].replace(0, pd.NA) * 100).round(1)
    result["rep_pct"] = (result["rep_votes"] / result["total_votes"].replace(0, pd.NA) * 100).round(1)
    return result


def build_swings(elections_df: pd.DataFrame) -> pd.DataFrame:
    """Compute Democratic vote swing between consecutive elections per county."""
    records = []
    pairs = [
        ("2020_president", "2022_governor"),
        ("2020_president", "2024_president"),
        ("2020_senate_special", "2022_senate"),
    ]
    for race_a, race_b in pairs:
        year_a, name_a = race_a.split("_", 1)
        year_b, name_b = race_b.split("_", 1)
        a = elections_df[(elections_df.year == year_a) & (elections_df.race == name_a)][["county", "dem_pct"]].rename(columns={"dem_pct": "dem_pct_a"})
        b = elections_df[(elections_df.year == year_b) & (elections_df.race == name_b)][["county", "dem_pct"]].rename(columns={"dem_pct": "dem_pct_b"})
        merged = a.merge(b, on="county", how="inner")
        merged["race_a"]   = f"{year_a}_{name_a}"
        merged["race_b"]   = f"{year_b}_{name_b}"
        merged["dem_swing"] = (merged["dem_pct_b"] - merged["dem_pct_a"]).round(1)
        records.append(merged[["county", "race_a", "race_b", "dem_swing"]])
    return pd.concat(records, ignore_index=True) if records else pd.DataFrame()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw-dir", default=None, help="Directory containing raw election CSVs (default: data/repos/main/elections/raw/)")
    ap.add_argument("--fdp-root", default=None)
    args = ap.parse_args()

    from fdp.platform import DataPlatform
    p = DataPlatform(fdp_root=args.fdp_root)

    elections_dir = p.active_repo.path / "elections"
    raw_dir = Path(args.raw_dir) if args.raw_dir else elections_dir / "raw"

    if not raw_dir.exists():
        print(f"Raw elections directory not found: {raw_dir}")
        print("Place Georgia SOS election CSVs there and re-run.")
        sys.exit(1)

    frames: list[pd.DataFrame] = []
    for year, race in ELECTION_RACES:
        pattern = f"{year}_{race}*.csv"
        files = list(raw_dir.glob(pattern))
        if not files:
            print(f"  SKIP     {year} {race} (no file matching {pattern})")
            continue
        try:
            df = process_election_file(files[0], year, race)
            frames.append(df)
            print(f"  OK       {year} {race}: {len(df)} counties from {files[0].name}")
        except Exception as exc:
            print(f"  ERROR    {year} {race}: {exc}")

    if not frames:
        print("No election data processed.")
        sys.exit(1)

    elections_df = pd.concat(frames, ignore_index=True)
    elections_path = elections_dir / "dim_elections.parquet"
    elections_df.to_parquet(elections_path, index=False)
    print(f"\nWrote {len(elections_df)} rows → {elections_path}")

    swings_df = build_swings(elections_df)
    swings_path = elections_dir / "dim_swings.parquet"
    swings_df.to_parquet(swings_path, index=False)
    print(f"Wrote {len(swings_df)} rows → {swings_path}")


if __name__ == "__main__":
    main()
