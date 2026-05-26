"""
Ensemble and graph loader — GerryChain output data.

Files live in the repo under:
    ensembles/<chamber>_ensemble.parquet
    ensembles/<chamber>_meta.json
    ensembles/<chamber>_stability.json
    graphs/ga_<chamber>.json
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from fdp.loaders.base import BaseLoader
from fdp.quality.checks import QualityReport, check_no_null_required

REQUIRED_ENSEMBLE_COLS = ["district", "dem_seats", "efficiency_gap", "mean_median"]


class EnsembleLoader(BaseLoader):
    """
    Load GerryChain ensemble outputs (parquets, meta JSON, stability JSON)
    and dual-graph JSON files.

    Examples::

        df       = loader.load_ensemble("house")
        meta     = loader.load_meta("house")
        stability = loader.load_stability("house")
        graph    = loader.load_graph("house")
    """

    def load(self, name: str, **kwargs) -> pd.DataFrame:
        """Alias for load_ensemble for BaseLoader compatibility."""
        return self.load_ensemble(name, **kwargs)

    def load_ensemble(self, chamber: str, **kwargs) -> pd.DataFrame:
        rel_path = f"ensembles/{chamber}_ensemble.parquet"
        abs_path = self.path(rel_path)
        df = pd.read_parquet(abs_path, **kwargs)
        self._check_quality(df, f"{chamber} ensemble")
        return df

    def load_meta(self, chamber: str) -> dict:
        rel_path = f"ensembles/{chamber}_meta.json"
        abs_path = self.path(rel_path)
        with abs_path.open() as f:
            return json.load(f)

    def load_stability(self, chamber: str) -> dict:
        rel_path = f"ensembles/{chamber}_stability.json"
        abs_path = self.path(rel_path)
        with abs_path.open() as f:
            return json.load(f)

    def load_graph(self, chamber: str) -> dict:
        """Load a GerryChain dual-graph JSON (adjacency list format)."""
        rel_path = f"graphs/ga_{chamber}.json"
        abs_path = self.path(rel_path)
        with abs_path.open() as f:
            return json.load(f)

    def list_available(self) -> dict[str, list[str]]:
        ensembles_dir = self.repo.path / "ensembles"
        graphs_dir    = self.repo.path / "graphs"
        return {
            "ensembles": sorted(
                p.stem.replace("_ensemble", "")
                for p in ensembles_dir.glob("*_ensemble.parquet")
            ) if ensembles_dir.exists() else [],
            "graphs": sorted(
                p.stem.replace("ga_", "")
                for p in graphs_dir.glob("ga_*.json")
            ) if graphs_dir.exists() else [],
        }

    def _validate(self, data: pd.DataFrame) -> QualityReport:
        report = QualityReport()
        check_no_null_required(data, REQUIRED_ENSEMBLE_COLS, report)
        return report
