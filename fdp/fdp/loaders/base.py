"""Base loader class shared by all specialized loaders."""

from __future__ import annotations

import warnings
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from fdp.repos import Repo, RepoRegistry
    from fdp.quality.checks import QualityReport


class BaseLoader(ABC):
    """
    Abstract base for all FDP data loaders.

    Subclasses implement ``load()`` and ``_validate()``.  The base class
    orchestrates quality checks and emits ``QualityWarning`` when issues are
    found (or raises if ``halt_on_error`` is True).
    """

    def __init__(
        self,
        repo: "Repo",
        registry: "RepoRegistry",
        halt_on_error: bool = False,
    ) -> None:
        self.repo = repo
        self.registry = registry
        self.halt_on_error = halt_on_error

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def path(self, rel_path: str) -> Path:
        """Resolve a repo-relative path, applying workspace fallback."""
        return self.repo.resolve(rel_path, self.registry)

    def exists(self, rel_path: str) -> bool:
        try:
            self.path(rel_path)
            return True
        except FileNotFoundError:
            return False

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def load(self, name: str, **kwargs) -> Any:
        """Load a dataset by logical name or relative path."""

    @abstractmethod
    def _validate(self, data: Any) -> "QualityReport":
        """Run quality checks on freshly loaded data; return a QualityReport."""

    # ------------------------------------------------------------------
    # Post-load quality hook
    # ------------------------------------------------------------------

    def _check_quality(self, data: Any, label: str) -> "QualityReport":
        from fdp.quality.checks import QualityReport
        report = self._validate(data)
        if report.has_errors:
            msg = f"Quality issues in '{label}': {report.summary}"
            if self.halt_on_error:
                raise ValueError(msg)
            warnings.warn(msg, stacklevel=3)
        return report
