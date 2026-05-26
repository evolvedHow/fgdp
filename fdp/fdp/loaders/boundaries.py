"""
Boundary loader — GeoJSON district and reference layers.

Boundaries live in the repo under:
    boundaries/congress/<file>.geojson
    boundaries/house/<file>.geojson
    boundaries/senate/<file>.geojson
    boundaries/reference/<file>.geojson
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import geopandas as gpd

from fdp.loaders.base import BaseLoader
from fdp.quality.checks import QualityReport, check_crs, check_geometry_validity, check_no_null_required

if TYPE_CHECKING:
    pass

CHAMBER_DIRS = {
    "congress": "boundaries/congress",
    "house":    "boundaries/house",
    "senate":   "boundaries/senate",
    "reference": "boundaries/reference",
}


class BoundaryLoader(BaseLoader):
    """
    Load GeoJSON district boundary files.

    Examples::

        # By logical ID from the app config plan catalogue
        gdf = loader.load("congress_enacted_24", chamber="congress")

        # By literal filename
        gdf = loader.load("congress_enacted_24_2024update.geojson", chamber="congress")

        # Full relative path
        gdf = loader.load("boundaries/congress/congress_enacted_24_2024update.geojson")

        # Reference layer
        gdf = loader.load("county.geojson", chamber="reference")
    """

    REQUIRED_COLS: list[str] = []  # All columns optional; geometry always checked

    def load(
        self,
        name: str,
        chamber: str | None = None,
        **kwargs,
    ) -> gpd.GeoDataFrame:
        rel_path = self._resolve_rel_path(name, chamber)
        abs_path = self.path(rel_path)
        gdf = gpd.read_file(abs_path, **kwargs)
        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")
        elif gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs("EPSG:4326")
        self._check_quality(gdf, name)
        return gdf

    def list_available(self, chamber: str | None = None) -> list[str]:
        """Return rel paths to all GeoJSON files, optionally filtered by chamber."""
        chambers = [chamber] if chamber else list(CHAMBER_DIRS)
        result: list[str] = []
        for ch in chambers:
            if ch not in CHAMBER_DIRS:
                raise ValueError(f"Unknown chamber '{ch}'. Valid: {list(CHAMBER_DIRS)}")
            subdir = CHAMBER_DIRS[ch]
            result += [
                str(p.relative_to(self.repo.path))
                for p in (self.repo.path / subdir).glob("*.geojson")
                if p.is_file()
            ]
        return sorted(result)

    def _resolve_rel_path(self, name: str, chamber: str | None) -> str:
        if name.startswith("boundaries/") or name.endswith(".geojson") and "/" in name:
            return name
        if chamber is None:
            raise ValueError(
                f"Provide chamber= when loading by filename or logical ID. "
                f"Valid chambers: {list(CHAMBER_DIRS)}"
            )
        if chamber not in CHAMBER_DIRS:
            raise ValueError(f"Unknown chamber '{chamber}'. Valid: {list(CHAMBER_DIRS)}")
        filename = name if name.endswith(".geojson") else f"{name}.geojson"
        return f"{CHAMBER_DIRS[chamber]}/{filename}"

    def _validate(self, data: gpd.GeoDataFrame) -> QualityReport:
        report = QualityReport()
        check_crs(data, report)
        check_geometry_validity(data, report)
        check_no_null_required(data, self.REQUIRED_COLS, report)
        return report
