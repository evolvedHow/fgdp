"""
FDP Benchmark Configuration — dataclass loader for YAML-driven ensemble runs.

Usage
-----
    from fdp.config import BenchmarkConfig

    cfg = BenchmarkConfig.from_yaml("configs/benchmarks/ga_congress_2026_v1.yml")
    print(cfg.benchmark_id)            # "ga_congress_2026_v1"
    print(cfg.chamber.n_districts)     # 14
    for e in cfg.elections:
        print(e.label, e.year, e.office)

All scripts that run, score, or visualise the benchmark accept --config and
delegate all parameter resolution to this module. Nothing is hardcoded anywhere
else in the pipeline.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Sub-configs
# ---------------------------------------------------------------------------

@dataclass
class GeographyConfig:
    state: str = "GA"
    geo_level: str = "vtd"          # vtd | precinct
    vintage_year: int = 2020
    graph_file: str | None = None   # path to GerryChain dual-graph JSON

    def graph_path(self, base_dir: Path) -> Path | None:
        if self.graph_file is None:
            return None
        p = Path(self.graph_file)
        return p if p.is_absolute() else base_dir / p


@dataclass
class ChamberConfig:
    name: str = "congress"          # congress | senate | house
    n_districts: int = 14
    pop_column: str = "TOTPOP"      # node attribute holding total population
    pop_epsilon: float = 0.01       # ±1% for Congress, ±5% for legislative


@dataclass
class ElectionConfig:
    label: str                      # short slug used in output columns
    year: int
    election_type: str              # general | runoff | special | primary
    office: str                     # president | governor | senate | us-house | state-rep
    candidates: list[str] | None = None   # filter to specific candidate codes
    partisan_score: bool = True     # include in partisan lean scoring
    competitive: bool = True        # include in competitiveness scoring

    @property
    def db_key(self) -> tuple[int, str, str]:
        """(year, election_type, office) — matches fdp.election_results PK fields."""
        return (self.year, self.election_type, self.office)


@dataclass
class DemographicGroup:
    name: str                       # black | white | hispanic | minority_coalition
    label: str                      # human-readable label for charts
    cvap_col: str | None = None     # CVAP column name (e.g. CVAP_BLK24)
    formula: str | None = None      # Python-eval formula using cvap columns
    majority_threshold: float = 0.50

    def __post_init__(self):
        if self.cvap_col is None and self.formula is None:
            raise ValueError(f"DemographicGroup '{self.name}' must have cvap_col OR formula")


@dataclass
class CompetitivenessConfig:
    thresholds: list[float] = field(default_factory=lambda: [0.07, 0.10])
    method: str = "all_independent"  # all_independent | composite_avg | specific
    elections: list[str] | str = "all"  # 'all' or list of election labels


@dataclass
class MCMCConfig:
    algorithm: str = "recom"        # recom | reversible_recom
    n_steps: int = 10_000
    burn_in: int = 0
    pop_epsilon: float | None = None  # if None: inherits from ChamberConfig
    n_chains: int = 1
    random_seed: int | None = None
    save_assignments: bool = True   # must be True to enable post-run re-scoring

    def effective_epsilon(self, chamber: ChamberConfig) -> float:
        return self.pop_epsilon if self.pop_epsilon is not None else chamber.pop_epsilon


@dataclass
class DemographicsConfig:
    cvap_year: int = 2024
    majority_threshold: float = 0.50   # global default; per-group can override
    groups: list[DemographicGroup] = field(default_factory=list)


@dataclass
class GradingConfig:
    pass_band: tuple[float, float] = (1.0, 99.0)   # 98% CI = PASS
    a_band:    tuple[float, float] = (25.0, 75.0)  # IQR
    b_band:    tuple[float, float] = (10.0, 90.0)
    c_band:    tuple[float, float] = (5.0, 95.0)
    composite: str = "min"          # min | average | weighted
    metric_weights: dict[str, float] | None = None

    def grade(self, pctile: float) -> str:
        """Return letter grade for a given percentile rank (0–100)."""
        lo_a, hi_a = self.a_band
        lo_b, hi_b = self.b_band
        lo_c, hi_c = self.c_band
        lo_p, hi_p = self.pass_band
        if lo_a <= pctile <= hi_a:
            return "A"
        if lo_b <= pctile <= hi_b:
            return "B"
        if lo_c <= pctile <= hi_c:
            return "C"
        if lo_p <= pctile <= hi_p:
            return "F"
        return "FAIL"

    def pass_fail(self, pctile: float) -> str:
        lo, hi = self.pass_band
        return "PASS" if lo <= pctile <= hi else "FAIL"


@dataclass
class OutputConfig:
    dir: str = "fdp/data/repos/main/ensemble"

    def resolve(self, base_dir: Path) -> Path:
        p = Path(self.dir)
        return p if p.is_absolute() else base_dir / p


# ---------------------------------------------------------------------------
# Root config
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkConfig:
    """
    Root configuration object for a benchmark ensemble run.

    Load with:
        cfg = BenchmarkConfig.from_yaml("configs/benchmarks/ga_congress_2026_v1.yml")

    The ``_source_path`` and ``_base_dir`` attributes are set automatically and
    let downstream code resolve relative file paths correctly.
    """
    benchmark_id: str
    description: str = ""
    version: str = "1.0"

    geography:       GeographyConfig      = field(default_factory=GeographyConfig)
    chamber:         ChamberConfig        = field(default_factory=ChamberConfig)
    elections:       list[ElectionConfig] = field(default_factory=list)
    competitiveness: CompetitivenessConfig = field(default_factory=CompetitivenessConfig)
    demographics:    DemographicsConfig   = field(default_factory=DemographicsConfig)
    mcmc:            MCMCConfig           = field(default_factory=MCMCConfig)
    grading:         GradingConfig        = field(default_factory=GradingConfig)
    output:          OutputConfig         = field(default_factory=OutputConfig)

    # Set by from_yaml — not in YAML file
    _source_path: Path | None = field(default=None, repr=False, compare=False)
    _base_dir:    Path | None = field(default=None, repr=False, compare=False)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_yaml(cls, path: str | Path) -> "BenchmarkConfig":
        """Load and validate a benchmark config from a YAML file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Benchmark config not found: {path}")

        with open(path) as f:
            raw: dict[str, Any] = yaml.safe_load(f)

        cfg = cls._from_dict(raw)
        cfg._source_path = path.resolve()
        cfg._base_dir    = path.resolve().parent.parent.parent  # configs/benchmarks/ → fdp root
        return cfg

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> "BenchmarkConfig":
        geo   = GeographyConfig(**{k: v for k, v in d.get("geography", {}).items()})
        ch    = ChamberConfig(**{k: v for k, v in d.get("chamber", {}).items()})

        elections = [
            ElectionConfig(**{k: v for k, v in e.items()})
            for e in d.get("elections", [])
        ]

        comp_raw  = d.get("competitiveness", {})
        comp = CompetitivenessConfig(
            thresholds=comp_raw.get("thresholds", [0.07, 0.10]),
            method=comp_raw.get("method", "all_independent"),
            elections=comp_raw.get("elections", "all"),
        )

        demo_raw = d.get("demographics", {})
        groups = [
            DemographicGroup(
                name=g["name"],
                label=g.get("label", g["name"]),
                cvap_col=g.get("cvap_col"),
                formula=g.get("formula"),
                majority_threshold=g.get("majority_threshold",
                                         demo_raw.get("majority_threshold", 0.50)),
            )
            for g in demo_raw.get("groups", [])
        ]
        demo = DemographicsConfig(
            cvap_year=demo_raw.get("cvap_year", 2024),
            majority_threshold=demo_raw.get("majority_threshold", 0.50),
            groups=groups,
        )

        mcmc_raw = d.get("mcmc", {})
        mcmc = MCMCConfig(
            algorithm=mcmc_raw.get("algorithm", "recom"),
            n_steps=mcmc_raw.get("n_steps", 10_000),
            burn_in=mcmc_raw.get("burn_in", 0),
            pop_epsilon=mcmc_raw.get("pop_epsilon"),
            n_chains=mcmc_raw.get("n_chains", 1),
            random_seed=mcmc_raw.get("random_seed"),
            save_assignments=mcmc_raw.get("save_assignments", True),
        )

        grading_raw = d.get("grading", {})
        grading = GradingConfig(
            pass_band=tuple(grading_raw.get("pass_band", [1, 99])),
            a_band=tuple(grading_raw.get("a_band", [25, 75])),
            b_band=tuple(grading_raw.get("b_band", [10, 90])),
            c_band=tuple(grading_raw.get("c_band", [5, 95])),
            composite=grading_raw.get("composite", "min"),
            metric_weights=grading_raw.get("metric_weights"),
        )

        output = OutputConfig(**{k: v for k, v in d.get("output", {}).items()})

        return cls(
            benchmark_id=d["benchmark_id"],
            description=d.get("description", ""),
            version=str(d.get("version", "1.0")),
            geography=geo,
            chamber=ch,
            elections=elections,
            competitiveness=comp,
            demographics=demo,
            mcmc=mcmc,
            grading=grading,
            output=output,
        )

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    def elections_for_partisan(self) -> list[ElectionConfig]:
        """Elections used for partisan lean scoring."""
        return [e for e in self.elections if e.partisan_score]

    def elections_for_competitiveness(self) -> list[ElectionConfig]:
        """Elections used for competitiveness scoring, based on method config."""
        if self.competitiveness.method == "all_independent":
            return [e for e in self.elections if e.competitive]
        if self.competitiveness.method == "specific":
            labels = set(self.competitiveness.elections)
            return [e for e in self.elections if e.label in labels]
        # composite_avg — also all competitive elections
        return [e for e in self.elections if e.competitive]

    def graph_path(self) -> Path | None:
        base = self._base_dir or Path.cwd()
        return self.geography.graph_path(base)

    def output_dir(self) -> Path:
        base = self._base_dir or Path.cwd()
        return self.output.resolve(base)

    def plans_parquet(self) -> Path:
        return self.output_dir() / f"{self.benchmark_id}_plans.parquet"

    def scores_parquet(self) -> Path:
        return self.output_dir() / f"{self.benchmark_id}_scores.parquet"

    def demographics_parquet(self) -> Path:
        return self.output_dir() / f"{self.benchmark_id}_demographics.parquet"

    def draw_stats_parquet(self) -> Path:
        return self.output_dir() / f"{self.benchmark_id}_draw_stats.parquet"

    def summary(self) -> str:
        """One-line human readable summary."""
        e_count = len(self.elections)
        return (
            f"{self.benchmark_id}  |  "
            f"{self.chamber.name} {self.chamber.n_districts}D  |  "
            f"{self.mcmc.algorithm} {self.mcmc.n_steps:,} steps  |  "
            f"{e_count} elections  |  "
            f"geo={self.geography.geo_level} {self.geography.vintage_year}"
        )
