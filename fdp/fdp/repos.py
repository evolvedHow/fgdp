"""
Repo and workspace registry.

A Repo is a named, versioned data directory.  The ``main`` repo is the canonical
shared store.  A Workspace is a lightweight, user-private overlay: it inherits
every file from a base repo but can shadow individual files with local copies.

Lookup order for workspace ``ws`` with base ``main``:
    data/workspaces/<ws>/<rel_path>   →  first check here
    data/repos/main/<rel_path>        →  then fall back here
    FileNotFoundError                 →  if still missing

Workspace activation:
    • env var:    FDP_WORKSPACE=<name>
    • app config: app.repo: <workspace_name>     (in config/apps/<app>.yml)
    • API:        DataPlatform(repo="<workspace_name>")
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from fdp.config import ResolvedConfig


@dataclass
class Repo:
    name: str
    path: Path
    description: str = ""
    read_only: bool = False
    is_workspace: bool = False
    base_repo: str | None = None  # Only set for workspaces

    def resolve(self, rel_path: str, registry: "RepoRegistry") -> Path:
        """
        Return an absolute Path for rel_path, applying workspace fallback.

        For a workspace, falls back to the base repo when the file is absent.
        """
        candidate = self.path / rel_path
        if candidate.exists():
            return candidate

        if self.is_workspace and self.base_repo:
            base = registry.get(self.base_repo)
            return base.resolve(rel_path, registry)

        raise FileNotFoundError(
            f"'{rel_path}' not found in repo '{self.name}'"
            + (f" or its base '{self.base_repo}'" if self.base_repo else "")
        )

    def list_files(self, subdir: str = "") -> list[Path]:
        """List all files under an optional subdirectory."""
        root = self.path / subdir if subdir else self.path
        if not root.exists():
            return []
        return [p for p in root.rglob("*") if p.is_file() and p.name != ".gitkeep"]


class RepoRegistry:
    """Central registry of all repos and workspaces."""

    def __init__(self, config: ResolvedConfig) -> None:
        platform = config["platform"]
        fdp_root = Path(platform["root"])

        repos_cfg = config["repos"]
        self._default_repo: str = repos_cfg.get("default", "main")
        self._workspaces_dir: Path = Path(
            repos_cfg.get("workspaces_dir", str(fdp_root / "data" / "workspaces"))
        )

        self._repos: dict[str, Repo] = {}
        for name, spec in repos_cfg.get("registry", {}).items():
            if not isinstance(spec, dict):
                continue
            self._repos[name] = Repo(
                name=name,
                path=Path(spec["path"]),
                description=spec.get("description", ""),
                read_only=spec.get("read_only", False),
            )

        # Auto-discover workspaces on disk
        self._load_workspaces()

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, name: str | None = None) -> Repo:
        resolved = name or self._default_repo
        if resolved not in self._repos:
            raise KeyError(
                f"Repo/workspace '{resolved}' is not registered. "
                f"Known: {list(self._repos)}"
            )
        return self._repos[resolved]

    @property
    def default_repo(self) -> str:
        return self._default_repo

    def list_repos(self) -> list[Repo]:
        return [r for r in self._repos.values() if not r.is_workspace]

    def list_workspaces(self) -> list[Repo]:
        return [r for r in self._repos.values() if r.is_workspace]

    # ------------------------------------------------------------------
    # Workspace management
    # ------------------------------------------------------------------

    def create_workspace(
        self,
        name: str,
        base: str = "main",
        description: str = "",
    ) -> Repo:
        if name in self._repos:
            raise ValueError(f"Repo/workspace '{name}' already exists.")
        if base not in self._repos:
            raise ValueError(f"Base repo '{base}' does not exist.")

        ws_path = self._workspaces_dir / name
        ws_path.mkdir(parents=True, exist_ok=True)

        meta = {
            "name": name,
            "base_repo": base,
            "description": description,
            "created": datetime.date.today().isoformat(),
        }
        with (ws_path / "workspace.yml").open("w") as f:
            yaml.safe_dump(meta, f)

        repo = Repo(
            name=name,
            path=ws_path,
            description=description,
            is_workspace=True,
            base_repo=base,
        )
        self._repos[name] = repo
        return repo

    def delete_workspace(self, name: str) -> None:
        repo = self._repos.get(name)
        if repo is None:
            raise KeyError(f"Workspace '{name}' not found.")
        if not repo.is_workspace:
            raise ValueError(f"'{name}' is a regular repo, not a workspace.")

        import shutil
        shutil.rmtree(repo.path)
        del self._repos[name]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_workspaces(self) -> None:
        if not self._workspaces_dir.exists():
            return
        for ws_dir in self._workspaces_dir.iterdir():
            if not ws_dir.is_dir():
                continue
            meta_file = ws_dir / "workspace.yml"
            if not meta_file.exists():
                continue
            with meta_file.open() as f:
                meta = yaml.safe_load(f) or {}
            name = meta.get("name", ws_dir.name)
            self._repos[name] = Repo(
                name=name,
                path=ws_dir,
                description=meta.get("description", ""),
                is_workspace=True,
                base_repo=meta.get("base_repo", "main"),
            )
