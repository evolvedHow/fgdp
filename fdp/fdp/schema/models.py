"""
CDM dataclass models — Python mirror of fdp/config/schema/*.yml

Keep these in sync with:
  - fdp/config/schema/redistricting_history.yml
  - fdp/config/schema/displacement.yml
  - map-compare/src/lib/types/cdm.ts  (TypeScript counterpart)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Redistricting history
# ---------------------------------------------------------------------------

@dataclass
class ChamberWave:
    chamber: Literal["congress", "house", "senate"]
    district_count: int
    all_districts: bool = False
    districts: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class RedistrictingWave:
    year: int
    label: str
    party: Literal["R", "D", "both"]
    reason: str
    chambers: list[ChamberWave]
    end_year: int | None = None
    legal_context: str = ""
    election_result: str = ""

    @property
    def total_districts_changed(self) -> int:
        return sum(c.district_count for c in self.chambers)

    @property
    def display_year(self) -> str:
        if self.end_year:
            return f"{self.year}–{self.end_year}"
        return str(self.year)


@dataclass
class RedistrictingHistory:
    source: str
    author: str
    created: str
    waves: list[RedistrictingWave]
    total_districts_changed: int = 0
    additional_bills_not_passed: int = 0

    @property
    def computed_total(self) -> int:
        return sum(w.total_districts_changed for w in self.waves)

    @classmethod
    def from_yaml(cls, path: Path | str) -> "RedistrictingHistory":
        with open(path) as f:
            data = yaml.safe_load(f)

        waves = []
        for w in data.get("waves", []):
            chambers = [
                ChamberWave(
                    chamber=c["chamber"],
                    district_count=c["district_count"],
                    all_districts=c.get("all_districts", False),
                    districts=c.get("districts", []),
                    notes=c.get("notes", ""),
                )
                for c in w.get("chambers", [])
            ]
            waves.append(RedistrictingWave(
                year=w["year"],
                end_year=w.get("end_year"),
                label=w["label"],
                party=w["party"],
                reason=w["reason"],
                legal_context=w.get("legal_context", ""),
                election_result=w.get("election_result", ""),
                chambers=chambers,
            ))

        return cls(
            source=data.get("source", ""),
            author=data.get("author", ""),
            created=data.get("created", ""),
            waves=waves,
            total_districts_changed=data.get("total_districts_changed", 0),
            additional_bills_not_passed=data.get("additional_bills_not_passed", 0),
        )


# ---------------------------------------------------------------------------
# Displacement metrics
# ---------------------------------------------------------------------------

@dataclass
class DisplacementMetrics:
    plan_a_id: str
    plan_b_id: str
    total_pop: int
    displaced_pop: int
    displaced_pct: float
    min_required_displaced_pop: int
    min_required_displaced_pct: float
    excess_displaced_pop: int
    excess_displaced_pct: float
    district_count: int = 0
    method: str = "area_weighted"
    computed_at: str = ""

    def to_dict(self) -> dict:
        return {
            "plan_a_id": self.plan_a_id,
            "plan_b_id": self.plan_b_id,
            "total_pop": self.total_pop,
            "displaced_pop": self.displaced_pop,
            "displaced_pct": round(self.displaced_pct, 6),
            "min_required_displaced_pop": self.min_required_displaced_pop,
            "min_required_displaced_pct": round(self.min_required_displaced_pct, 6),
            "excess_displaced_pop": self.excess_displaced_pop,
            "excess_displaced_pct": round(self.excess_displaced_pct, 6),
            "district_count": self.district_count,
            "method": self.method,
            "computed_at": self.computed_at,
        }


@dataclass
class DistrictDisplacement:
    district_id_a: str
    district_id_b: str
    pop_a: int
    displaced_from_a: int
    displaced_pct: float

    def to_dict(self) -> dict:
        return {
            "district_id_a": self.district_id_a,
            "district_id_b": self.district_id_b,
            "pop_a": self.pop_a,
            "displaced_from_a": self.displaced_from_a,
            "displaced_pct": round(self.displaced_pct, 6),
        }
