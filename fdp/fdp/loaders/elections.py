"""
Election data loader — county-level results and swing analysis.

Files live in the repo under:
    elections/dim_elections.parquet
    elections/dim_swings.parquet
    elections/*.parquet | *.csv
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from fdp.loaders.base import BaseLoader
from fdp.quality.checks import QualityReport, check_no_null_required

KNOWN_DATASETS = {
    "elections": "elections/dim_elections.parquet",
    "swings":    "elections/dim_swings.parquet",
}

ELECTION_REQUIRED_COLS = ["county", "year", "race", "dem_votes", "rep_votes"]
SWING_REQUIRED_COLS    = ["county", "race_a", "race_b", "dem_swing"]


class ElectionLoader(BaseLoader):
    """
    Load county-level election results and swing analysis.

    Examples::

        elections_df = loader.load("elections")
        swings_df    = loader.load("swings")
        custom_df    = loader.load("my_results.parquet")
    """

    def load(self, name: str, **kwargs) -> pd.DataFrame:
        rel_path = KNOWN_DATASETS.get(name, f"elections/{name}")
        abs_path = self.path(rel_path)

        if abs_path.suffix == ".parquet":
            df = pd.read_parquet(abs_path, **kwargs)
        elif abs_path.suffix == ".csv":
            df = pd.read_csv(abs_path, **kwargs)
        else:
            raise ValueError(f"Unsupported election data format: {abs_path.suffix}")

        self._check_quality(df, name)
        return df

    def list_available(self) -> list[str]:
        elec_dir = self.repo.path / "elections"
        if not elec_dir.exists():
            return []
        return sorted(
            str(p.relative_to(self.repo.path))
            for p in elec_dir.iterdir()
            if p.is_file() and p.name != ".gitkeep"
        )

    def _validate(self, data: pd.DataFrame) -> QualityReport:
        report = QualityReport()
        # Use looser check: only validate if expected columns are present at all
        if "county" in data.columns:
            check_no_null_required(data, ELECTION_REQUIRED_COLS, report)
        return report
