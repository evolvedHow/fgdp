"""
Demographics loader — ACS and Census PL 94-171 district-level data.

Files live in the repo under:
    demographics/congress.json
    demographics/house.json
    demographics/senate.json
    demographics/*.parquet
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from fdp.loaders.base import BaseLoader
from fdp.quality.checks import QualityReport, check_no_null_required

if TYPE_CHECKING:
    pass

CHAMBER_FILES = {
    "congress": "demographics/congress.json",
    "house":    "demographics/house.json",
    "senate":   "demographics/senate.json",
}


class DemographicsLoader(BaseLoader):
    """
    Load ACS/Census demographic summaries by district.

    Returns a dict (from JSON) or DataFrame (from parquet) keyed by district ID.

    Examples::

        data = loader.load("congress")      # → dict of district demographics
        df   = loader.load("elections.parquet")  # → DataFrame
    """

    REQUIRED_COLS: list[str] = []

    def load(self, name: str, **kwargs):
        rel_path = CHAMBER_FILES.get(name, f"demographics/{name}")
        abs_path = self.path(rel_path)

        if abs_path.suffix == ".json":
            with abs_path.open() as f:
                data = json.load(f)
            self._check_quality(data, name)
            return data

        if abs_path.suffix == ".parquet":
            df = pd.read_parquet(abs_path, **kwargs)
            self._check_quality(df, name)
            return df

        raise ValueError(f"Unsupported demographics format: {abs_path.suffix}")

    def list_available(self) -> list[str]:
        demo_dir = self.repo.path / "demographics"
        if not demo_dir.exists():
            return []
        return sorted(
            str(p.relative_to(self.repo.path))
            for p in demo_dir.iterdir()
            if p.is_file() and p.name != ".gitkeep"
        )

    def _validate(self, data) -> QualityReport:
        report = QualityReport()
        if isinstance(data, pd.DataFrame):
            check_no_null_required(data, self.REQUIRED_COLS, report)
        return report
