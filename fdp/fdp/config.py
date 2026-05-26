"""
Hierarchical configuration loader for the Fair Districts Data Platform.

Resolution order (later wins, except for locked global keys):
  global.yml  <  defaults.yml  <  apps/<app>.yml  <  env overrides

Locked keys (defined in global.yml under `platform`, `repos`, `data_layout`,
`data_schema`, `quality`) cannot be changed by app configs.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

# Top-level keys from global.yml that apps cannot override
_LOCKED_KEYS = {"platform", "repos", "data_layout", "data_schema", "quality"}


def _expand_env(value: Any, extra: dict[str, str] | None = None) -> Any:
    """Recursively expand ${VAR:-default} and ${VAR} in string values.

    ``extra`` overrides env var lookup, used to inject FDP_ROOT without
    requiring the caller to set it in the process environment.
    """
    if isinstance(value, str):
        def replacer(m: re.Match) -> str:
            var, _, default = m.group(1).partition(":-")
            if extra and var in extra:
                return extra[var]
            return os.environ.get(var, default)
        return re.sub(r"\$\{([^}]+)\}", replacer, value)
    if isinstance(value, dict):
        return {k: _expand_env(v, extra) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(i, extra) for i in value]
    return value


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base; override wins on conflicts."""
    result = base.copy()
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open() as f:
        return yaml.safe_load(f) or {}


class ResolvedConfig:
    """Merged, validated configuration for a specific app."""

    def __init__(self, data: dict) -> None:
        self._data = data

    def get(self, path: str, default: Any = None) -> Any:
        """Dot-separated key access, e.g. ``config.get('map.zoom')``."""
        parts = path.split(".")
        node = self._data
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def raw(self) -> dict:
        return self._data


class ConfigLoader:
    """Loads and merges the FDP YAML config hierarchy."""

    def __init__(self, fdp_root: Path | str | None = None) -> None:
        if fdp_root is None:
            fdp_root = os.environ.get("FDP_ROOT", str(Path(__file__).parent.parent))
        self._root = Path(fdp_root)
        self._config_dir = self._root / "config"

        self._global: dict = _load_yaml(self._config_dir / "global.yml")
        self._defaults: dict = _load_yaml(self._config_dir / "defaults.yml")

    def for_app(self, app: str | None = None) -> ResolvedConfig:
        """
        Merge global + defaults + app overrides into a single ResolvedConfig.

        Locked global keys (platform, repos, data_layout, data_schema, quality)
        are always restored after merging so apps cannot override them.
        """
        app_config: dict = {}
        if app:
            app_config = _load_yaml(self._config_dir / "apps" / f"{app}.yml")

        # Start with defaults, layer app overrides on top
        merged = _deep_merge(self._defaults, app_config)

        # Restore locked global sections — they always win
        for key in _LOCKED_KEYS:
            if key in self._global:
                merged[key] = self._global[key]

        # Add any remaining global keys not already present
        for key, val in self._global.items():
            if key not in merged:
                merged[key] = val

        # Expand ${FDP_ROOT} using the resolved root so callers don't need
        # the env var set when DataPlatform(fdp_root=...) is used directly.
        merged = _expand_env(merged, extra={"FDP_ROOT": str(self._root)})

        # Inject the resolved FDP root so consumers can build absolute paths
        merged.setdefault("platform", {})["root"] = str(self._root)

        return ResolvedConfig(merged)
