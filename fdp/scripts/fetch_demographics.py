"""
Fetch ACS 5-year and Census PL 94-171 demographic data for all GA districts.

Consolidates logic from:
  - fdex/scripts/fetch_district_demographics.py  (ACS socioeconomic)
  - fdex/scripts/fetch_district_vap.py           (Census PL 94-171 race/VAP)

Output written to:
  data/repos/main/demographics/congress.json
  data/repos/main/demographics/house.json
  data/repos/main/demographics/senate.json

Requirements:
  pip install census us

Get a Census API key at: https://api.census.gov/data/key_signup.html
Set it in .env:  CENSUS_API_KEY=your_key_here

Usage:
    uv run python scripts/fetch_demographics.py
    uv run python scripts/fetch_demographics.py --chamber congress
    uv run python scripts/fetch_demographics.py --acs-year 2023
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

CENSUS_API_KEY = os.environ.get("CENSUS_API_KEY", "")
STATE_FIPS = "13"  # Georgia


# ---------------------------------------------------------------------------
# ACS variable definitions
# ---------------------------------------------------------------------------

ACS_VARIABLES = {
    "B19013_001E": "median_household_income",
    "B17001_002E": "below_poverty_count",
    "B17001_001E": "poverty_universe",
    "B15003_022E": "bachelors_count",
    "B15003_023E": "masters_count",
    "B15003_024E": "professional_count",
    "B15003_025E": "doctorate_count",
    "B15003_001E": "education_universe",
    "B11001_001E": "total_households",
    "B23025_002E": "in_labor_force",
    "B23025_001E": "labor_force_universe",
    "B27010_017E": "uninsured_under18",
    "B27010_033E": "uninsured_18_34",
    "B27010_050E": "uninsured_35_64",
    "B27010_066E": "uninsured_65plus",
    "B27010_001E": "health_insurance_universe",
}

# PL 94-171 VAP variables
PL_VAP_VARIABLES = {
    "P3_001N": "total_vap",
    "P3_003N": "white_alone_vap",
    "P3_004N": "black_alone_vap",
    "P3_005N": "aian_alone_vap",
    "P3_006N": "asian_alone_vap",
    "P3_007N": "nhpi_alone_vap",
    "P3_008N": "other_alone_vap",
    "P4_002N": "hispanic_vap",
}

CHAMBER_GEOGRAPHIES = {
    "congress": "congressional district",
    "house":    "state legislative district (lower chamber)",
    "senate":   "state legislative district (upper chamber)",
}


def fetch_acs(chamber: str, acs_year: int, api_key: str) -> dict:
    from census import Census
    c = Census(api_key, year=acs_year)

    geo = CHAMBER_GEOGRAPHIES[chamber]
    variables = list(ACS_VARIABLES.keys()) + ["NAME"]
    raw = c.acs5.state_legislative_district(  # type: ignore
        variables,
        STATE_FIPS,
        Census.ALL,
    )
    # Reshape into {district_id: {field: value, ...}}
    result = {}
    for row in raw:
        district_id = row.get("congressional district") or row.get("state legislative district (lower chamber)") or row.get("state legislative district (upper chamber)", "")
        entry: dict = {"name": row.get("NAME", "")}
        for api_col, friendly_name in ACS_VARIABLES.items():
            val = row.get(api_col)
            entry[friendly_name] = int(val) if val and val not in ("-666666666", "-999999999") else None
        # Derived rates
        if entry.get("poverty_universe") and entry.get("below_poverty_count") is not None:
            entry["poverty_rate"] = round(entry["below_poverty_count"] / entry["poverty_universe"] * 100, 1)
        edu_total = sum(entry.get(k) or 0 for k in ["bachelors_count", "masters_count", "professional_count", "doctorate_count"])
        if entry.get("education_universe"):
            entry["college_attainment_rate"] = round(edu_total / entry["education_universe"] * 100, 1)
        result[district_id] = entry
    return result


def fetch_vap(chamber: str, census_year: int, api_key: str) -> dict:
    """Fetch 2020 Census PL 94-171 VAP by race for all districts."""
    import requests
    base_url = f"https://api.census.gov/data/{census_year}/dec/pl"

    geo = CHAMBER_GEOGRAPHIES[chamber]
    variables = ",".join(["NAME"] + list(PL_VAP_VARIABLES.keys()))

    geo_query = {
        "congressional district": f"congressional+district:*&in=state:{STATE_FIPS}",
        "state legislative district (lower chamber)": f"state+legislative+district+(lower+chamber):*&in=state:{STATE_FIPS}",
        "state legislative district (upper chamber)": f"state+legislative+district+(upper+chamber):*&in=state:{STATE_FIPS}",
    }

    url = f"{base_url}?get={variables}&for={geo_query[geo]}&key={api_key}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    rows = resp.json()
    headers = rows[0]
    result = {}
    for row in rows[1:]:
        d = dict(zip(headers, row))
        district_id = d.get("congressional district") or d.get("state legislative district (lower chamber)") or d.get("state legislative district (upper chamber)", "")
        entry: dict = {}
        for api_col, name in PL_VAP_VARIABLES.items():
            val = d.get(api_col)
            entry[name] = int(val) if val else 0
        total_vap = entry.get("total_vap", 0)
        if total_vap:
            entry["bvap_pct"]     = round(entry["black_alone_vap"] / total_vap * 100, 1)
            entry["hvap_pct"]     = round(entry["hispanic_vap"] / total_vap * 100, 1)
            entry["asian_vap_pct"] = round(entry["asian_alone_vap"] / total_vap * 100, 1)
        result[district_id] = entry
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chamber", choices=["congress", "house", "senate", "all"], default="all")
    ap.add_argument("--acs-year", type=int, default=2022)
    ap.add_argument("--census-year", type=int, default=2020)
    ap.add_argument("--fdp-root", default=None)
    args = ap.parse_args()

    if not CENSUS_API_KEY:
        print("ERROR: CENSUS_API_KEY not set. Get one at https://api.census.gov/data/key_signup.html")
        sys.exit(1)

    from fdp.platform import DataPlatform
    p = DataPlatform(fdp_root=args.fdp_root)
    demo_dir = p.active_repo.path / "demographics"
    demo_dir.mkdir(parents=True, exist_ok=True)

    chambers = ["congress", "house", "senate"] if args.chamber == "all" else [args.chamber]

    for chamber in chambers:
        print(f"\nFetching demographics for {chamber}...")
        try:
            acs_data  = fetch_acs(chamber, args.acs_year, CENSUS_API_KEY)
            vap_data  = fetch_vap(chamber, args.census_year, CENSUS_API_KEY)

            # Merge ACS + VAP by district ID
            merged: dict = {}
            all_ids = set(acs_data) | set(vap_data)
            for district_id in sorted(all_ids):
                merged[district_id] = {
                    **(acs_data.get(district_id) or {}),
                    **(vap_data.get(district_id) or {}),
                }

            out_path = demo_dir / f"{chamber}.json"
            with out_path.open("w") as f:
                json.dump(merged, f, indent=2)
            print(f"  Wrote {len(merged)} districts → {out_path}")

        except Exception as exc:
            print(f"  ERROR: {exc}")
            sys.exit(1)

    print("\nDone.")


if __name__ == "__main__":
    main()
