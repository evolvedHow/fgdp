"""
DataPlatform — main entry point for all FDP consumers.

Usage (Python apps)::

    from fdp import DataPlatform

    # Standard: uses platform defaults + app config + main repo
    p = DataPlatform(app="fdga_chain")

    # Use a workspace (shadows specific files from main)
    p = DataPlatform(app="fdga_chain", repo="my_new_shapes")

    # Env var: FDP_WORKSPACE=my_new_shapes also activates a workspace
    # Env var: FDP_ROOT=/path/to/fdp overrides the platform root

    # Loaders
    gdf  = p.boundaries.load("congress_enacted_24", chamber="congress")
    demo = p.demographics.load("congress")
    df   = p.elections.load("elections")
    gdf  = p.precincts.load("congress")
    ens  = p.ensembles.load_ensemble("house")

    # Resolve a raw path (for code that needs the file path, not the data)
    path = p.resolve("boundaries/congress/congress_enacted_24_2024update.geojson")

    # Catalog
    p.catalog.print_summary()

    # Workspace management
    ws = p.registry.create_workspace("test_shapes", base="main")
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from fdp.config import ConfigLoader, ResolvedConfig
from fdp.repos import Repo, RepoRegistry
from fdp.loaders.boundaries import BoundaryLoader
from fdp.loaders.demographics import DemographicsLoader
from fdp.loaders.elections import ElectionLoader
from fdp.loaders.precincts import PrecinctLoader
from fdp.loaders.ensembles import EnsembleLoader
from fdp.catalog import DataCatalog
from fdp.manifest import DataManifest


class DataPlatform:
    """
    Unified access point for Fair Districts data.

    Parameters
    ----------
    app:
        App name matching a file in ``config/apps/<app>.yml``.
        If omitted, only global + defaults are loaded.
    repo:
        Named repo or workspace to use.  Defaults to ``app.repo`` from
        config, falling back to the platform default (``main``).
        Also read from the ``FDP_WORKSPACE`` env var if not supplied.
    fdp_root:
        Override the platform root directory.
        Defaults to the ``FDP_ROOT`` env var or the fdp package parent.
    halt_on_error:
        If True, data quality errors raise instead of warning.
    """

    def __init__(
        self,
        app: str | None = None,
        repo: str | None = None,
        fdp_root: str | Path | None = None,
        halt_on_error: bool = False,
    ) -> None:
        # Config
        loader = ConfigLoader(fdp_root)
        self._config: ResolvedConfig = loader.for_app(app)
        self._app = app

        # Repo resolution order:
        #   1. explicit `repo` arg
        #   2. FDP_WORKSPACE env var
        #   3. app config `app.repo`
        #   4. platform default (main)
        repo_name: str | None = (
            repo
            or os.environ.get("FDP_WORKSPACE")
            or self._config.get("app.repo")
        )

        # Registry
        self.registry = RepoRegistry(self._config)

        # Active repo
        self._repo: Repo = self.registry.get(repo_name)

        # Loaders (lazy init via properties below)
        _kw = dict(repo=self._repo, registry=self.registry, halt_on_error=halt_on_error)
        self._boundaries   = BoundaryLoader(**_kw)
        self._demographics = DemographicsLoader(**_kw)
        self._elections    = ElectionLoader(**_kw)
        self._precincts    = PrecinctLoader(**_kw)
        self._ensembles    = EnsembleLoader(**_kw)

        # Catalog (lazy)
        self._catalog: DataCatalog | None = None

        # Manifest (lazy)
        self._manifest: DataManifest | None = None

    # ------------------------------------------------------------------
    # Loader accessors
    # ------------------------------------------------------------------

    @property
    def boundaries(self) -> BoundaryLoader:
        return self._boundaries

    @property
    def demographics(self) -> DemographicsLoader:
        return self._demographics

    @property
    def elections(self) -> ElectionLoader:
        return self._elections

    @property
    def precincts(self) -> PrecinctLoader:
        return self._precincts

    @property
    def ensembles(self) -> EnsembleLoader:
        return self._ensembles

    @property
    def catalog(self) -> DataCatalog:
        if self._catalog is None:
            self._catalog = DataCatalog(self._repo, self.registry, self._config)
        return self._catalog

    @property
    def manifest(self) -> DataManifest:
        """
        Dataset registry — tracks every ingested/derived dataset by ID.

        Reads DATABASE_URL from the environment.  Raises RuntimeError if the
        env var is not set (set it before calling any manifest operations).
        """
        if self._manifest is None:
            self._manifest = DataManifest()
        return self._manifest

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def resolve(self, rel_path: str) -> Path:
        """Return the absolute Path for a repo-relative path."""
        return self._repo.resolve(rel_path, self.registry)

    def exists(self, rel_path: str) -> bool:
        try:
            self.resolve(rel_path)
            return True
        except FileNotFoundError:
            return False

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    @property
    def config(self) -> ResolvedConfig:
        return self._config

    @property
    def active_repo(self) -> Repo:
        return self._repo

    def __repr__(self) -> str:
        return f"DataPlatform(app={self._app!r}, repo={self._repo.name!r})"
