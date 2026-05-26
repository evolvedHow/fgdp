"""
Data quality checks for FDP loaders.

Each check function receives a dataset and a QualityReport, appends findings,
and returns nothing.  Loaders call the relevant checks then emit warnings or
raise based on halt_on_error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# QualityReport — accumulates errors and warnings from multiple checks
# ---------------------------------------------------------------------------

@dataclass
class QualityIssue:
    level: str  # "error" | "warning"
    message: str
    check: str = ""


@dataclass
class QualityReport:
    issues: list[QualityIssue] = field(default_factory=list)

    def add_error(self, message: str, check: str = "") -> None:
        self.issues.append(QualityIssue("error", message, check))

    def add_warning(self, message: str, check: str = "") -> None:
        self.issues.append(QualityIssue("warning", message, check))

    @property
    def has_errors(self) -> bool:
        return any(i.level == "error" for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.level == "warning" for i in self.issues)

    @property
    def summary(self) -> str:
        errors   = [i for i in self.issues if i.level == "error"]
        warnings = [i for i in self.issues if i.level == "warning"]
        parts = []
        if errors:
            parts.append(f"{len(errors)} error(s): " + "; ".join(e.message for e in errors))
        if warnings:
            parts.append(f"{len(warnings)} warning(s): " + "; ".join(w.message for w in warnings))
        return " | ".join(parts) if parts else "OK"

    def __repr__(self) -> str:
        return f"QualityReport({self.summary})"


# Alias so loaders can import the ABC-style name if they want
QualityCheck = QualityReport


# ---------------------------------------------------------------------------
# Individual check functions — composable, stateless
# ---------------------------------------------------------------------------

def check_crs(gdf: Any, report: QualityReport) -> None:
    """Verify CRS is WGS-84 (EPSG:4326)."""
    try:
        epsg = gdf.crs.to_epsg() if gdf.crs else None
    except Exception:
        epsg = None
    if epsg != 4326:
        report.add_error(
            f"CRS is {gdf.crs!r}, expected EPSG:4326",
            check="crs_is_wgs84",
        )


def check_geometry_validity(gdf: Any, report: QualityReport) -> None:
    """Warn about invalid or null geometries."""
    null_count = gdf.geometry.isna().sum()
    if null_count:
        report.add_error(f"{null_count} null geometries", check="no_invalid_geometries")
    invalid_count = (~gdf.geometry.is_valid).sum()
    if invalid_count:
        report.add_warning(
            f"{invalid_count} invalid geometries (consider buffer(0) fix)",
            check="no_invalid_geometries",
        )


def check_no_null_required(df: Any, required_cols: list[str], report: QualityReport) -> None:
    """Error if any required column has null values."""
    import pandas as pd
    for col in required_cols:
        if col not in df.columns:
            report.add_error(f"Required column '{col}' is missing", check="no_null_required_columns")
        elif df[col].isna().any():
            n = df[col].isna().sum()
            report.add_error(f"Column '{col}' has {n} null values", check="no_null_required_columns")


def check_population_reasonable(gdf: Any, pop_col: str, report: QualityReport) -> None:
    """Warn if total population looks unreasonably low or individual rows are zero."""
    if pop_col not in gdf.columns:
        return
    total = gdf[pop_col].sum()
    if total < 1_000:
        report.add_warning(
            f"Total population ({total:,}) seems very low",
            check="population_totals_reasonable",
        )
    zero_rows = (gdf[pop_col] == 0).sum()
    if zero_rows:
        report.add_warning(
            f"{zero_rows} rows have zero population",
            check="population_totals_reasonable",
        )


def check_no_overlapping_districts(gdf: Any, report: QualityReport, tolerance: float = 0.001) -> None:
    """Warn if any two district polygons overlap significantly."""
    try:
        from shapely.ops import unary_union
        union = unary_union(gdf.geometry.buffer(0))
        total_area = union.area
        sum_area   = gdf.geometry.buffer(0).area.sum()
        overlap_pct = (sum_area - total_area) / total_area * 100
        if overlap_pct > tolerance:
            report.add_warning(
                f"Districts overlap by ~{overlap_pct:.2f}% of total area",
                check="no_overlapping_districts",
            )
    except Exception as exc:
        report.add_warning(f"Could not check district overlaps: {exc}", check="no_overlapping_districts")


def check_districts_cover_state(
    gdf: Any,
    state_bounds: Any | None,
    report: QualityReport,
    coverage_threshold: float = 0.99,
) -> None:
    """Warn if districts don't cover at least coverage_threshold of the state area."""
    if state_bounds is None:
        return
    try:
        from shapely.ops import unary_union
        district_union = unary_union(gdf.geometry.buffer(0))
        coverage = district_union.intersection(state_bounds).area / state_bounds.area
        if coverage < coverage_threshold:
            report.add_warning(
                f"Districts cover only {coverage:.1%} of state area (threshold {coverage_threshold:.0%})",
                check="districts_fully_cover_state",
            )
    except Exception as exc:
        report.add_warning(f"Could not check state coverage: {exc}", check="districts_fully_cover_state")
