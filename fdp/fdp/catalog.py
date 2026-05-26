"""
Data catalog — inventory of what's available in a repo or workspace.

The catalog reads the physical directory layout to discover files and
cross-references them against the app config plan entries.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fdp.repos import Repo, RepoRegistry
    from fdp.config import ResolvedConfig


@dataclass
class CatalogEntry:
    logical_id: str
    rel_path: str
    abs_path: Path
    category: str       # "boundaries", "demographics", "elections", "precincts", "ensembles", "lrdb"
    subcategory: str    # chamber or file type
    file_size_bytes: int
    exists: bool

    @property
    def file_size_mb(self) -> float:
        return round(self.file_size_bytes / 1_048_576, 2)


class DataCatalog:
    """
    Discover and report on available data files in a repo.

    Usage::

        catalog = DataCatalog(platform)
        catalog.print_summary()
        entries = catalog.list(category="boundaries", subcategory="congress")
    """

    def __init__(self, repo: "Repo", registry: "RepoRegistry", config: "ResolvedConfig") -> None:
        self.repo = repo
        self.registry = registry
        self.config = config
        self._entries: list[CatalogEntry] = []
        self._scan()

    def _scan(self) -> None:
        self._entries.clear()
        layout = self.config.get("data_layout", {})
        root = self.repo.path

        categories = {
            "boundaries/congress": ("boundaries", "congress"),
            "boundaries/house":    ("boundaries", "house"),
            "boundaries/senate":   ("boundaries", "senate"),
            "boundaries/reference": ("boundaries", "reference"),
            "demographics":        ("demographics", ""),
            "elections":           ("elections", ""),
            "precincts":           ("precincts", ""),
            "graphs":              ("ensembles", "graphs"),
            "ensembles":           ("ensembles", "ensembles"),
            "lrdb":                ("lrdb", ""),
        }

        for rel_dir, (category, subcategory) in categories.items():
            d = root / rel_dir
            if not d.exists():
                continue
            for f in sorted(d.iterdir()):
                if f.name == ".gitkeep" or not f.is_file():
                    continue
                size = f.stat().st_size
                rel_path = str(f.relative_to(root))
                self._entries.append(CatalogEntry(
                    logical_id=f.stem,
                    rel_path=rel_path,
                    abs_path=f,
                    category=category,
                    subcategory=subcategory,
                    file_size_bytes=size,
                    exists=True,
                ))

    def list(
        self,
        category: str | None = None,
        subcategory: str | None = None,
    ) -> list[CatalogEntry]:
        results = self._entries
        if category:
            results = [e for e in results if e.category == category]
        if subcategory:
            results = [e for e in results if e.subcategory == subcategory]
        return results

    def summary(self) -> dict:
        out: dict = {}
        for entry in self._entries:
            key = f"{entry.category}/{entry.subcategory}" if entry.subcategory else entry.category
            out.setdefault(key, {"count": 0, "total_mb": 0.0})
            out[key]["count"] += 1
            out[key]["total_mb"] = round(out[key]["total_mb"] + entry.file_size_mb, 2)
        return out

    def print_summary(self) -> None:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(title=f"Data Catalog — repo: {self.repo.name}", show_header=True)
        table.add_column("Category", style="cyan")
        table.add_column("Files", justify="right")
        table.add_column("Total MB", justify="right")

        for key, stats in sorted(self.summary().items()):
            table.add_row(key, str(stats["count"]), str(stats["total_mb"]))

        console.print(table)
