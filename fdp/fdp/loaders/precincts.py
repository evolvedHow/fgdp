"""
Precinct shapefile loader — MGGG-States Georgia precinct data.

Files live in the repo under:
    precincts/ga_gen_20_<chamber>_prec.shp   (and accompanying .dbf, .prj, etc.)
    precincts/ga_pl2020_*.shp                (Census block-level, ~3GB)

Column standardisation
----------------------
Different MGGG releases use slightly different column names.  The loader
normalises them to a canonical schema on read so downstream code is stable.

Canonical names → common MGGG aliases:
    TOTPOP    ← TOTPOP, TOTPOP20
    BVAP      ← BVAP, BVAP20
    HVAP      ← HVAP, HVAP20
    AVAP      ← AVAP, AVAP20
    DEM_VOTES ← G20PREDBID, G16PREDCLI, PRES_DEM, DEM_VOTES
    REP_VOTES ← G20PRERTRU, G16PRERTRU, PRES_REP, REP_VOTES
    HDIST     ← HDIST, HD, HOUSE_DIST
    SDIST     ← SDIST, SD, SEN_DIST
    CDIST     ← CDIST, CD, CONG_DIST
"""

from __future__ import annotations

import re
from pathlib import Path

import geopandas as gpd
import pandas as pd

from fdp.loaders.base import BaseLoader
from fdp.quality.checks import QualityReport, check_crs, check_geometry_validity, check_no_null_required

CHAMBER_PRECINCT_FILES = {
    "congress": "precincts/ga_gen_20_congress_prec.shp",
    "house":    "precincts/ga_gen_20_house_prec.shp",
    "senate":   "precincts/ga_gen_20_senate_prec.shp",
}

# Canonical col → list of known aliases (first match wins)
_COL_ALIASES: dict[str, list[str]] = {
    "TOTPOP":    ["TOTPOP20", "TOTPOP"],
    "BVAP":      ["BVAP20", "BVAP"],
    "HVAP":      ["HVAP20", "HVAP"],
    "AVAP":      ["AVAP20", "AVAP"],
    "DEM_VOTES": ["G20PREDBID", "G22SENATOSS", "G16PREDCLI", "PRES_DEM", "DEM_VOTES"],
    "REP_VOTES": ["G20PRERTRU", "G22SENATWARN", "G16PRERTRU", "PRES_REP", "REP_VOTES"],
    "HDIST":     ["HD", "HOUSE_DIST", "HDIST"],
    "SDIST":     ["SD", "SEN_DIST",   "SDIST"],
    "CDIST":     ["CD", "CONG_DIST",  "CDIST"],
}

REQUIRED_COLS = ["TOTPOP", "BVAP", "DEM_VOTES", "REP_VOTES"]


class PrecinctLoader(BaseLoader):
    """
    Load and normalise precinct-level shapefiles.

    Examples::

        gdf = loader.load("congress")          # ga_gen_20_congress_prec.shp
        gdf = loader.load("precincts/custom.shp")  # literal path
    """

    def load(self, name: str, **kwargs) -> gpd.GeoDataFrame:
        rel_path = CHAMBER_PRECINCT_FILES.get(name, f"precincts/{name}" if "/" not in name else name)
        abs_path = self.path(rel_path)
        gdf = gpd.read_file(abs_path, **kwargs)

        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")
        elif gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs("EPSG:4326")

        gdf = self._normalise_columns(gdf)
        self._check_quality(gdf, name)
        return gdf

    def list_available(self) -> list[str]:
        prec_dir = self.repo.path / "precincts"
        if not prec_dir.exists():
            return []
        return sorted(
            str(p.relative_to(self.repo.path))
            for p in prec_dir.glob("*.shp")
        )

    def _normalise_columns(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Rename alias columns to canonical names in-place."""
        rename: dict[str, str] = {}
        existing = set(gdf.columns)
        for canonical, aliases in _COL_ALIASES.items():
            if canonical in existing:
                continue
            for alias in aliases:
                if alias in existing:
                    rename[alias] = canonical
                    break
        if rename:
            gdf = gdf.rename(columns=rename)
        return gdf

    def _validate(self, data: gpd.GeoDataFrame) -> QualityReport:
        report = QualityReport()
        check_crs(data, report)
        check_geometry_validity(data, report)
        check_no_null_required(data, REQUIRED_COLS, report)

        # Sanity: population numbers should be positive
        if "TOTPOP" in data.columns:
            negative = (data["TOTPOP"] < 0).sum()
            if negative:
                report.add_error(f"{negative} precincts have negative TOTPOP")

        return report
