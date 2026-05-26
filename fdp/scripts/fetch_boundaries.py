"""
Fetch and install district boundary GeoJSON files into the data platform.

This is a coordination script — it doesn't download from the web itself.
Boundary GeoJSONs come from the Georgia General Assembly redistricting portal
and MGGG; they must be placed here manually or via the redistricting portal.

What this script does:
  1. Validates that all expected boundary files are present in the repo
  2. Checks CRS and geometry validity for each file
  3. Reports what's missing

Usage:
    uv run python scripts/fetch_boundaries.py
    uv run python scripts/fetch_boundaries.py --repo my_workspace
    uv run python scripts/fetch_boundaries.py --fix-crs   # reproject if needed
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from scripts/ without install
sys.path.insert(0, str(Path(__file__).parent.parent))

from fdp.platform import DataPlatform
from fdp.quality.checks import check_crs, check_geometry_validity, QualityReport


EXPECTED_BOUNDARIES = {
    "congress": [
        "congress_enacted_24_2024update.geojson",
        "congress_remedy_a.geojson",
        "congress_remedy_b.geojson",
        "congress12_census20.geojson",
        "congress14_census20.geojson",
        "congress21_census20.geojson",
    ],
    "house": [
        "house_enacted_24_2024update.geojson",
        "house_remedy_a.geojson",
        "house_remedy_b.geojson",
        "house15_census20.geojson",
    ],
    "senate": [
        "senate_enacted_24_2024update.geojson",
        "senate_remedy.geojson",
        "senate14_census20.geojson",
    ],
    "reference": [
        "county.geojson",
        "places_2020data.geojson",
    ],
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=None, help="Repo or workspace name (default: platform default)")
    ap.add_argument("--fix-crs", action="store_true", help="Reproject files not in EPSG:4326 (rewrites in place)")
    ap.add_argument("--fdp-root", default=None, help="Override FDP_ROOT")
    args = ap.parse_args()

    p = DataPlatform(repo=args.repo, fdp_root=args.fdp_root)
    print(f"Using repo: {p.active_repo.name} ({p.active_repo.path})\n")

    missing: list[str] = []
    issues: list[str] = []

    for chamber, files in EXPECTED_BOUNDARIES.items():
        for fname in files:
            rel = f"boundaries/{chamber}/{fname}"
            if not p.exists(rel):
                missing.append(rel)
                print(f"  MISSING  {rel}")
                continue

            path = p.resolve(rel)
            print(f"  OK       {rel}  ({path.stat().st_size // 1024} KB)", end="")

            # CRS check
            try:
                import geopandas as gpd
                gdf = gpd.read_file(path)
                report = QualityReport()
                check_crs(gdf, report)
                check_geometry_validity(gdf, report)

                if report.has_errors:
                    if args.fix_crs and gdf.crs and gdf.crs.to_epsg() != 4326:
                        gdf = gdf.to_crs("EPSG:4326")
                        gdf.to_file(path, driver="GeoJSON")
                        print(f"  [reprojected to EPSG:4326]", end="")
                    else:
                        issues.append(f"{rel}: {report.summary}")
                        print(f"  !! {report.summary}", end="")
                elif report.has_warnings:
                    print(f"  ~ {report.summary}", end="")
            except Exception as exc:
                issues.append(f"{rel}: {exc}")
                print(f"  !! ERROR: {exc}", end="")

            print()

    print()
    if missing:
        print(f"MISSING FILES ({len(missing)}):")
        for m in missing:
            print(f"  {m}")
        print()
        print("Copy boundary GeoJSON files from:")
        print("  https://redistrictingdatahub.org/state/georgia/")
        print("  https://github.com/mggg-states/GA-shapefiles")
        print("  Or export from the Georgia General Assembly redistricting portal")

    if issues:
        print(f"\nDATA QUALITY ISSUES ({len(issues)}):")
        for i in issues:
            print(f"  {i}")
        print("  Run with --fix-crs to auto-reproject CRS issues.")

    if not missing and not issues:
        print("All boundary files present and valid.")

    sys.exit(1 if missing or issues else 0)


if __name__ == "__main__":
    main()
