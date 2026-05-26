"""
Population displacement analysis between two redistricting plans.

Computes how many people ended up in a different district when moving from
Plan A to Plan B, and how much of that displacement was in excess of the
minimum required for population equalization.

This is the server-side (accurate) implementation using geopandas.
The browser-side approximation lives in map-compare/src/lib/utils/displacementMetrics.ts.

Usage
-----
    from fdp.analysis.displacement import compute_displacement
    import geopandas as gpd

    plan_a = gpd.read_file("before.geojson")
    plan_b = gpd.read_file("after.geojson")
    summary, districts = compute_displacement(plan_a, plan_b, "2021_enacted", "2023_enacted")

CLI
---
    fdp displacement compute --plan-a before.geojson --plan-b after.geojson
"""

from __future__ import annotations

import warnings
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np

from fdp.schema.models import DisplacementMetrics, DistrictDisplacement

# Georgia (and surrounding) UTM Zone 17N — used for area calculations
_PROJ_CRS = "EPSG:32617"
_WGS84 = "EPSG:4326"

# Property name candidates for district ID and population, in priority order
_DISTRICT_PROPS = ["DISTRICT", "district", "DISTRICTID", "District", "NAME", "name", "ID"]
_POP_PROPS = ["TOTPOP", "pop", "POP", "POPULATION", "total_pop"]


def _district_id(row: "pd.Series", idx: int) -> str:  # type: ignore[name-defined]
    for prop in _DISTRICT_PROPS:
        val = row.get(prop)
        if val is not None:
            return str(val)
    return str(idx)


def _population(row: "pd.Series", pop_col: str | None) -> float:  # type: ignore[name-defined]
    if pop_col:
        return float(row.get(pop_col, 0) or 0)
    for prop in _POP_PROPS:
        val = row.get(prop)
        if val is not None:
            return float(val or 0)
    return 0.0


def _detect_pop_col(gdf: gpd.GeoDataFrame) -> str | None:
    for prop in _POP_PROPS:
        if prop in gdf.columns:
            return prop
    return None


def compute_displacement(
    plan_a: gpd.GeoDataFrame,
    plan_b: gpd.GeoDataFrame,
    plan_a_id: str = "plan_a",
    plan_b_id: str = "plan_b",
    pop_col: str | None = None,
) -> tuple[DisplacementMetrics, list[DistrictDisplacement]]:
    """
    Compute population displacement between two redistricting plans.

    Method: area-weighted intersection.
    For each Plan A district, intersect with all Plan B districts and assign
    population proportionally by area. People assigned to a Plan B district
    other than the dominant one (largest overlap) are counted as displaced.

    Minimum required displacement is the theoretical minimum to equalize
    Plan A's district populations:
        min_required = Σ max(0, pop_a_i − ideal_a) / total_pop

    Returns
    -------
    (DisplacementMetrics, list[DistrictDisplacement])
    """
    # Normalise CRS
    if plan_a.crs is None:
        plan_a = plan_a.set_crs(_WGS84)
    if plan_b.crs is None:
        plan_b = plan_b.set_crs(_WGS84)
    if plan_a.crs != plan_b.crs:
        plan_b = plan_b.to_crs(plan_a.crs)

    # Auto-detect population column
    if pop_col is None:
        pop_col = _detect_pop_col(plan_a)

    # Project to UTM for accurate area calculations
    a_proj = plan_a.to_crs(_PROJ_CRS)
    b_proj = plan_b.to_crs(_PROJ_CRS)

    # Pre-compute B areas and build spatial index
    b_proj = b_proj.copy()
    b_proj["_area"] = b_proj.geometry.area
    b_sindex = b_proj.sindex

    total_pop = sum(_population(plan_a.iloc[i], pop_col) for i in range(len(plan_a)))
    ideal_pop_a = total_pop / len(plan_a) if len(plan_a) > 0 else 0.0
    ideal_pop_b = total_pop / len(plan_b) if len(plan_b) > 0 else 0.0

    district_results: list[DistrictDisplacement] = []
    total_displaced = 0.0

    for i in range(len(a_proj)):
        row_a = a_proj.iloc[i]
        orig_row_a = plan_a.iloc[i]
        geom_a = row_a.geometry
        if geom_a is None or geom_a.is_empty:
            continue

        area_a = geom_a.area
        if area_a == 0:
            continue

        pop_a = _population(orig_row_a, pop_col)
        id_a = _district_id(orig_row_a, i)

        # Use spatial index to find candidate B districts
        candidate_idxs = list(b_sindex.intersection(geom_a.bounds))
        if not candidate_idxs:
            continue

        overlaps: list[tuple[str, float]] = []
        for j in candidate_idxs:
            row_b = b_proj.iloc[j]
            geom_b = row_b.geometry
            if geom_b is None or geom_b.is_empty:
                continue
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    inter = geom_a.intersection(geom_b)
                area = inter.area
            except Exception:
                area = 0.0
            if area > 0:
                id_b = _district_id(plan_b.iloc[j], j)
                overlaps.append((id_b, area))

        if not overlaps:
            continue

        # Dominant B district (largest overlap)
        overlaps.sort(key=lambda x: x[1], reverse=True)
        dominant_b_id, dominant_area = overlaps[0]

        # Area that moved to non-dominant B districts
        displaced_area = max(0.0, area_a - dominant_area)
        displaced_pop = pop_a * displaced_area / area_a if area_a > 0 else 0.0
        total_displaced += displaced_pop

        district_results.append(DistrictDisplacement(
            district_id_a=id_a,
            district_id_b=dominant_b_id,
            pop_a=int(round(pop_a)),
            displaced_from_a=int(round(displaced_pop)),
            displaced_pct=displaced_pop / pop_a if pop_a > 0 else 0.0,
        ))

    # Minimum required displacement: over-ideal population in Plan A must move
    # to achieve equalization. Σ max(0, pop_a_i − ideal_a) / total_pop
    min_required = sum(
        max(0.0, _population(plan_a.iloc[i], pop_col) - ideal_pop_a)
        for i in range(len(plan_a))
    )

    displaced_pop_int = int(round(total_displaced))
    min_required_int = int(round(min_required))
    excess = max(0, displaced_pop_int - min_required_int)

    summary = DisplacementMetrics(
        plan_a_id=plan_a_id,
        plan_b_id=plan_b_id,
        total_pop=int(round(total_pop)),
        displaced_pop=displaced_pop_int,
        displaced_pct=total_displaced / total_pop if total_pop > 0 else 0.0,
        min_required_displaced_pop=min_required_int,
        min_required_displaced_pct=min_required / total_pop if total_pop > 0 else 0.0,
        excess_displaced_pop=excess,
        excess_displaced_pct=excess / total_pop if total_pop > 0 else 0.0,
        district_count=len(plan_a),
        method="area_weighted",
        computed_at=datetime.now(timezone.utc).isoformat(),
    )

    return summary, district_results


def compute_displacement_from_files(
    path_a: Path | str,
    path_b: Path | str,
    plan_a_id: str | None = None,
    plan_b_id: str | None = None,
    pop_col: str | None = None,
) -> tuple[DisplacementMetrics, list[DistrictDisplacement]]:
    """Convenience wrapper that reads GeoJSON files directly."""
    path_a = Path(path_a)
    path_b = Path(path_b)
    plan_a = gpd.read_file(path_a)
    plan_b = gpd.read_file(path_b)
    return compute_displacement(
        plan_a,
        plan_b,
        plan_a_id=plan_a_id or path_a.stem,
        plan_b_id=plan_b_id or path_b.stem,
        pop_col=pop_col,
    )
