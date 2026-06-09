#!/usr/bin/env python3
"""
build_alarm_scorecard.py — Re-score the ALARM SMC ensemble with the 2018-2024 composite elections.

The original ALARM stats CSV uses a 2016-2020 election composite.  This script
replaces that with the same VTD-level composite used by the GerryChain benchmarks
(2018 Gov, 2020 Pres, 2021 Warnock runoff, 2022 Gov, 2022 Senate, 2024 Pres),
so that ALARM and GerryChain benchmarks share an identical electoral baseline.
The only remaining difference between the two benchmarks is the algorithm:
  ALARM  — SMC Sequential Monte Carlo, 2 independent chains × 5,000 plans
  GerryChain — ReCom Markov chain, 9,501 draws

Non-partisan metrics (Polsby-Popper, county/municipal splits, minority VAP)
are taken from the original ALARM stats CSV unchanged.

Usage (from fgdp/ root):
    uv run --project fdp python fdp/scripts/build_alarm_scorecard.py
    uv run --project fdp python fdp/scripts/build_alarm_scorecard.py --chamber congress
    uv run --project fdp python fdp/scripts/build_alarm_scorecard.py --out fdensemble/input_data/

Run `uv sync --project fdp` first to install dependencies (numpy, pandas, pyarrow).
Requires R (Rscript) to extract the GEOID row order from GA_cd_2020_map.rds.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

# ── Import grading helpers from build_scorecard.py ───────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
from build_scorecard import (  # noqa: E402
    _GRADE_ORDER,
    _METRIC_META,
    _adj,
    _build_composite_grades,
    _comp_grade,
    _directional_grade,
    _ensemble_pass,
    _generate_takeaway,
    _histogram_data,
    _metric_entry,
    _pct_rank,
    _seats_grade,
    _simple_grade,
    COMPETITIVE_THRESHOLD_DEFAULT,
    MAJORITY_THRESHOLD,
)

# Geographic metric metadata — not in build_scorecard.py (GerryChain doesn't compute these)
# Format mirrors _METRIC_META: (label, headline, category, description, higher_is_better)
_GEO_METRIC_META: dict = {
    "polsby_popper": (
        "Compactness (Polsby-Popper)", "Are district shapes compact and geographically coherent?",
        "geographic",
        "The Polsby-Popper score measures shape compactness (ratio of area to perimeter²). "
        "Scores near 1 indicate circular, compact districts. Oddly shaped districts can signal "
        "that lines were drawn to include or exclude specific communities.",
        True,
    ),
    "county_splits": (
        "County Integrity", "Are natural community boundaries being respected?",
        "geographic",
        "The number of counties divided across two or more districts. Fewer splits means more "
        "communities of interest are kept intact.",
        False,
    ),
    "muni_splits": (
        "Municipal Integrity", "Are cities and towns being kept whole?",
        "geographic",
        "The number of cities and municipalities divided across different districts. Fewer splits "
        "means residents share a single representative for local concerns.",
        False,
    ),
}

# ── Paths ─────────────────────────────────────────────────────────────────────
_REPO_ROOT    = _SCRIPT_DIR.parent.parent          # fgdp/
_FDP_DIR      = _SCRIPT_DIR.parent                 # fgdp/fdp/
_DATAVERSE    = _REPO_ROOT / "fdensemble" / "dataverse_files" / "GA_cd_2020"
_VTD_COMPOSITE = _FDP_DIR / "data" / "repos" / "main" / "vtd" / "vtd_composite.parquet"
_VTD_CVAP      = _FDP_DIR / "data" / "repos" / "main" / "vtd" / "cvap_vtd.parquet"
_DEFAULT_OUT  = _REPO_ROOT / "fdensemble" / "input_data"

ALARM_RDS     = _DATAVERSE / "GA_cd_2020_map.rds"
PLANS_MATRIX  = _DATAVERSE / "GA_cd_2020_plans_matrix.csv"
STATS_CSV     = _DATAVERSE / "GA_cd_2020_stats.csv"


# ── Step 1: export GEOID row order from R ─────────────────────────────────────

def export_geoids_from_rds(rds_path: Path) -> list[str]:
    """
    Use Rscript to extract the GEOID column from the redist_map RDS file.
    Returns a list of 2,698 GEOID strings in row order.
    """
    r_code = f"""
map <- readRDS("{rds_path}")
geoids <- map$GEOID
if (is.null(geoids)) geoids <- map[["GEOID"]]
cat(paste(as.character(geoids), collapse="\\n"), "\\n")
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".R", delete=False) as f:
        f.write(r_code)
        r_script = f.name

    try:
        result = subprocess.run(
            ["Rscript", "--vanilla", r_script],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"R script failed:\n{result.stderr}")
        geoids = [g.strip() for g in result.stdout.strip().split("\n") if g.strip()]
        print(f"  Exported {len(geoids)} GEOIDs from {rds_path.name}")
        return geoids
    finally:
        Path(r_script).unlink(missing_ok=True)


# ── Step 2: compute district-level dem_2pv for all plans ─────────────────────

def compute_partisan_metrics(
    plans_matrix: pd.DataFrame,
    geoids: list[str],
    vtd_composite: pd.DataFrame,
    n_districts: int = 14,
    competitive_margin: float = COMPETITIVE_THRESHOLD_DEFAULT,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Vectorised computation of per-district dem_2pv for every ALARM plan.

    Returns:
        sampled_metrics: DataFrame indexed by draw (int), columns = metric names
        enacted_metrics: DataFrame (1 row), same columns
    """
    # Align plans matrix rows with VTD composite via GEOID
    vtd_lookup = vtd_composite.set_index("GEOID20")[["composite_dem_2pv", "VAP_MOD"]]
    geoid_series = pd.Series(geoids, name="GEOID20")

    # Some ALARM GEOIDs may differ slightly from vtd_composite GEOID20.
    # Inner-join and report any gaps.
    aligned = geoid_series.to_frame().join(vtd_lookup, on="GEOID20", how="left")
    n_missing = aligned["composite_dem_2pv"].isna().sum()
    if n_missing > 0:
        print(f"  WARNING: {n_missing} ALARM VTDs not found in vtd_composite "
              f"— they will be treated as zero contribution")
    aligned[["composite_dem_2pv", "VAP_MOD"]] = aligned[
        ["composite_dem_2pv", "VAP_MOD"]
    ].fillna(0.0)

    dem_votes_vtd = (aligned["composite_dem_2pv"] * aligned["VAP_MOD"]).values  # (2698,)
    rep_votes_vtd = ((1 - aligned["composite_dem_2pv"]) * aligned["VAP_MOD"]).values
    tot_votes_vtd = aligned["VAP_MOD"].values

    # Plans matrix: rows = VTDs (2698), cols = plans (5001)
    # Column 'cd_2020' = enacted; V2..V5001 = sampled draws 1..5000
    enacted_col = plans_matrix["cd_2020"].values.astype(np.int8)
    sampled_cols = plans_matrix.drop(columns=["cd_2020"]).values.astype(np.int8)
    n_sampled = sampled_cols.shape[1]

    def _plan_metrics(assignments_2d: np.ndarray) -> pd.DataFrame:
        """
        assignments_2d: (n_vtds, n_plans) district assignments.
        Returns DataFrame with one row per plan, columns = metric names.
        """
        n_plans_local = assignments_2d.shape[1]
        dem_by_dist = np.zeros((n_districts + 1, n_plans_local))
        rep_by_dist = np.zeros((n_districts + 1, n_plans_local))
        tot_by_dist = np.zeros((n_districts + 1, n_plans_local))

        for d in range(1, n_districts + 1):
            mask = (assignments_2d == d)                         # (n_vtds, n_plans)
            dem_by_dist[d] = (mask * dem_votes_vtd[:, np.newaxis]).sum(axis=0)
            rep_by_dist[d] = (mask * rep_votes_vtd[:, np.newaxis]).sum(axis=0)
            tot_by_dist[d] = (mask * tot_votes_vtd[:, np.newaxis]).sum(axis=0)

        # dem_2pv per district per plan: (14, n_plans)
        d2pv = dem_by_dist[1:] / np.where(
            tot_by_dist[1:] > 0, tot_by_dist[1:], np.nan
        )

        # Plan-level metrics
        dem_seats   = (d2pv >= 0.5).sum(axis=0).astype(float)
        mean_vals   = np.nanmean(d2pv, axis=0)
        median_vals = np.nanmedian(d2pv, axis=0)
        mean_median = mean_vals - median_vals

        # Efficiency gap
        waste_dem = np.where(
            d2pv >= 0.5,
            (d2pv - 0.5) * tot_by_dist[1:],
            d2pv * tot_by_dist[1:],
        ).sum(axis=0)
        waste_rep = np.where(
            d2pv < 0.5,
            (0.5 - d2pv) * tot_by_dist[1:],
            (1 - d2pv) * tot_by_dist[1:],
        ).sum(axis=0)
        total_v = tot_by_dist[1:].sum(axis=0)
        egap = np.where(total_v > 0, (waste_dem - waste_rep) / total_v, 0.0)

        # Competitive seats
        comp_seats = (np.abs(d2pv - 0.5) <= competitive_margin).sum(axis=0).astype(float)

        return pd.DataFrame({
            "dem_seats":      dem_seats,
            "efficiency_gap": np.round(egap, 6),
            "mean_median":    np.round(mean_median, 6),
            "comp_seats":     comp_seats,
        })

    print("  Computing partisan metrics for 5,000 sampled plans…")
    sampled_metrics = _plan_metrics(sampled_cols)
    sampled_metrics.index = range(1, n_sampled + 1)  # draw 1..5000
    sampled_metrics.index.name = "draw"

    print("  Computing partisan metrics for enacted plan…")
    enacted_metrics = _plan_metrics(enacted_col[:, np.newaxis])
    enacted_metrics.index = pd.Index(["cd_2020"], name="draw")

    return sampled_metrics, enacted_metrics


# ── Step 3: load non-partisan metrics from stats CSV ─────────────────────────

def load_nonpartisan_metrics(stats_csv: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Load Polsby-Popper, county splits, muni splits, and minority VAP metrics
    from the ALARM stats CSV.  These are independent of the election composite.

    Returns (sampled_df, enacted_df) with plan-level aggregates.
    """
    df = pd.read_csv(stats_csv, dtype={"draw": str})
    df["draw"] = df["draw"].str.strip()

    enacted_raw = df[df["draw"] == "cd_2020"].copy()
    sampled_raw = df[df["draw"] != "cd_2020"].copy()
    sampled_raw["draw"] = sampled_raw["draw"].astype(int)

    def _aggregate(raw: pd.DataFrame) -> pd.DataFrame:
        agg = raw.groupby("draw").agg(
            polsby_popper  = ("comp_polsby",  "mean"),
            county_splits  = ("county_splits", "first"),
            muni_splits    = ("muni_splits",   "first"),
            total_vap      = ("total_vap",     "sum"),
            vap_black      = ("vap_black",     "sum"),
            vap_white      = ("vap_white",     "sum"),
            # Per-district minority thresholds (aggregate as district count)
            _n_maj_black   = ("vap_black",     lambda x: (
                x / raw.loc[x.index, "total_vap"].clip(lower=1) >= MAJORITY_THRESHOLD
            ).sum()),
            _n_min_coal    = ("vap_white",     lambda x: (
                1 - x / raw.loc[x.index, "total_vap"].clip(lower=1) >= MAJORITY_THRESHOLD
            ).sum()),
        ).reset_index()
        return agg

    # Per-district VAP ratios for majority thresholds — compute more carefully
    def _minority_counts(raw: pd.DataFrame) -> pd.DataFrame:
        raw = raw.copy()
        raw["_frac_black"] = raw["vap_black"] / raw["total_vap"].clip(lower=1)
        raw["_frac_nonwhite"] = 1 - raw["vap_white"] / raw["total_vap"].clip(lower=1)
        raw["_maj_black"] = (raw["_frac_black"] >= MAJORITY_THRESHOLD).astype(int)
        raw["_min_coal"]  = (raw["_frac_nonwhite"] >= MAJORITY_THRESHOLD).astype(int)

        plan_agg = raw.groupby("draw").agg(
            polsby_popper = ("comp_polsby",  "mean"),
            county_splits = ("county_splits", "first"),
            muni_splits   = ("muni_splits",   "first"),
            maj_black     = ("_maj_black",    "sum"),
            min_coal      = ("_min_coal",     "sum"),
        )
        return plan_agg

    sampled_df = _minority_counts(sampled_raw)
    enacted_df = _minority_counts(enacted_raw)
    return sampled_df, enacted_df


# ── Step 3b: CVAP-based demographics (replaces BVAP from stats CSV) ───────────

def compute_cvap_demographics(
    plans_matrix: pd.DataFrame,
    geoids: list[str],
    cvap_vtd: pd.DataFrame,
    n_districts: int = 14,
    majority_threshold: float = MAJORITY_THRESHOLD,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Vectorised CVAP-based majority-Black / minority-coalition counts per plan.

    Uses 2024 ACS CVAP Special Tabulation (any-part Black CVAP / Total Citizen VAP)
    from cvap_vtd.parquet — the same source as the GerryChain pipeline.  Replaces
    the BVAP-from-stats-CSV calculation so both ensembles share a consistent VRA §2
    denominator.

    Returns (sampled_df, enacted_df) indexed the same as compute_partisan_metrics.
    """
    cvap_lookup = cvap_vtd.set_index("GEOID20")[["bvap_tot", "bvap_blk", "bvap_wht"]]
    aligned = (
        pd.Series(geoids, name="GEOID20")
        .to_frame()
        .join(cvap_lookup, on="GEOID20", how="left")
        .fillna(0.0)
    )
    cvap_tot_vtd = aligned["bvap_tot"].values   # (2698,)
    cvap_blk_vtd = aligned["bvap_blk"].values
    cvap_wht_vtd = aligned["bvap_wht"].values

    enacted_col  = plans_matrix["cd_2020"].values.astype(np.int8)
    sampled_cols = plans_matrix.drop(columns=["cd_2020"]).values.astype(np.int8)
    n_sampled    = sampled_cols.shape[1]

    def _demo_metrics(assignments_2d: np.ndarray) -> pd.DataFrame:
        n_plans_local = assignments_2d.shape[1]
        tot = np.zeros((n_districts + 1, n_plans_local))
        blk = np.zeros((n_districts + 1, n_plans_local))
        wht = np.zeros((n_districts + 1, n_plans_local))
        for d in range(1, n_districts + 1):
            mask = assignments_2d == d
            tot[d] = (mask * cvap_tot_vtd[:, np.newaxis]).sum(axis=0)
            blk[d] = (mask * cvap_blk_vtd[:, np.newaxis]).sum(axis=0)
            wht[d] = (mask * cvap_wht_vtd[:, np.newaxis]).sum(axis=0)
        safe_tot  = np.where(tot[1:] > 0, tot[1:], 1.0)
        frac_blk  = blk[1:] / safe_tot
        frac_nonw = 1.0 - wht[1:] / safe_tot
        return pd.DataFrame({
            "maj_black": (frac_blk  >= majority_threshold).sum(axis=0).astype(float),
            "min_coal":  (frac_nonw >= majority_threshold).sum(axis=0).astype(float),
        })

    sampled_df = _demo_metrics(sampled_cols)
    sampled_df.index = range(1, n_sampled + 1)
    sampled_df.index.name = "draw"

    enacted_df = _demo_metrics(enacted_col[:, np.newaxis])
    enacted_df.index = pd.Index(["cd_2020"], name="draw")

    return sampled_df, enacted_df


# ── Step 4: Princeton grading ─────────────────────────────────────────────────

def grade_all_metrics(
    sampled_partisan: pd.DataFrame,
    enacted_partisan: pd.DataFrame,
    sampled_geo: pd.DataFrame,
    enacted_geo: pd.DataFrame,
) -> dict:
    """
    Run Princeton grading on all metrics.  Returns a dict of grade entries
    matching the scorecard format: { metric_key: grade_entry_dict }.
    """
    s = sampled_partisan.copy()
    e = enacted_partisan.copy()

    # Merge geographic metrics
    s = s.join(sampled_geo[["polsby_popper", "county_splits", "muni_splits",
                             "maj_black", "min_coal"]])
    e = e.join(enacted_geo[["polsby_popper", "county_splits", "muni_splits",
                             "maj_black", "min_coal"]])

    grades: dict = {}

    # Partisan + minority metrics — use build_scorecard.py's _metric_entry + _METRIC_META
    for key in ["dem_seats", "efficiency_gap", "mean_median", "comp_seats",
                "maj_black", "min_coal"]:
        if key not in s.columns:
            continue
        s_vals = s[key].dropna().values
        e_val  = e[key].iloc[0] if key in e.columns else None
        if e_val is None or np.isnan(float(e_val)) or len(s_vals) < 10:
            continue
        entry = _metric_entry(key, s_vals, float(e_val))
        if entry is not None:
            grades[key] = entry

    # Geographic metrics — use local _GEO_METRIC_META (not in build_scorecard.py)
    for key in ["polsby_popper", "county_splits", "muni_splits"]:
        if key not in s.columns:
            continue
        s_vals = s[key].dropna().values
        e_val  = e[key].iloc[0] if key in e.columns else None
        if e_val is None or np.isnan(float(e_val)) or len(s_vals) < 10:
            continue
        label, headline, category, desc, hib = _GEO_METRIC_META[key]
        dist = np.array(s_vals, dtype=float)
        if np.std(dist) < 1e-9:
            continue
        pct  = _pct_rank(dist, float(e_val))
        hist = _histogram_data(dist, float(e_val))
        grade = _directional_grade(pct, hib)
        grades[key] = {
            "label":       label,
            "headline":    headline,
            "category":    category,
            "description": desc,
            "takeaway":    _generate_takeaway(key, float(e_val), pct, hist),
            "grade":       grade,
            "enacted":     round(float(e_val), 4),
            "pct_rank":    round(pct, 1),
            "histogram":   hist,
        }

    return grades


# ── Step 5: build correlations ───────────────────────────────────────────────

def build_alarm_correlations(
    sampled_partisan: pd.DataFrame,
    enacted_partisan: pd.DataFrame,
    sampled_geo: pd.DataFrame,
    enacted_geo: pd.DataFrame,
    n_scatter: int = 300,
) -> dict | None:
    """
    Compute cross-metric Pearson correlation matrix and downsampled scatter pairs
    for the urban-cracking / partisan-bias story.  Uses in-memory DataFrames
    (no DuckDB/parquet needed — ALARM data is already computed).

    Returns { "matrix": {...}, "scatter": {...} } matching the GerryChain format.
    """
    # Merge partisan + geo on draw index
    base = sampled_partisan[["dem_seats", "efficiency_gap", "mean_median", "comp_seats"]].copy()
    if "muni_splits" in sampled_geo.columns:
        base = base.join(sampled_geo[["muni_splits"]], how="inner")

    metrics = [c for c in ["dem_seats", "efficiency_gap", "mean_median", "comp_seats", "muni_splits"]
               if c in base.columns]
    if len(base) < 50 or len(metrics) < 2:
        return None

    # Pearson correlation matrix
    corr_df = base[metrics].corr(method="pearson")
    matrix = {
        row: {col: round(float(corr_df.loc[row, col]), 4) for col in metrics}
        for row in metrics
    }

    # Enacted values
    enacted_vals: dict = {}
    for key in ["dem_seats", "efficiency_gap", "mean_median", "comp_seats"]:
        if key in enacted_partisan.columns:
            enacted_vals[key] = float(enacted_partisan[key].iloc[0])
    if "muni_splits" in enacted_geo.columns:
        enacted_vals["muni_splits"] = float(enacted_geo["muni_splits"].iloc[0])

    # Downsampled scatter pairs
    rng = np.random.default_rng(42)
    n = len(base)
    idx = np.sort(rng.choice(n, min(n_scatter, n), replace=False))

    scatter_pairs = [
        ("muni_splits",   "dem_seats"),
        ("muni_splits",   "efficiency_gap"),
        ("muni_splits",   "comp_seats"),
        ("dem_seats",     "efficiency_gap"),
    ]

    scatter: dict = {}
    for x_key, y_key in scatter_pairs:
        if x_key not in base.columns or y_key not in base.columns:
            continue
        x_vals = base[x_key].values[idx]
        y_vals = base[y_key].values[idx]
        r = float(np.corrcoef(base[x_key].values, base[y_key].values)[0, 1])
        scatter[f"{x_key}_vs_{y_key}"] = {
            "x":        [round(float(v), 4) for v in x_vals],
            "y":        [round(float(v), 4) for v in y_vals],
            "enacted_x": round(enacted_vals.get(x_key, 0.0), 4),
            "enacted_y": round(enacted_vals.get(y_key, 0.0), 4),
            "r":         round(r, 4),
        }

    return {"matrix": matrix, "scatter": scatter}


# ── Step 6: build river data ──────────────────────────────────────────────────

def build_river(
    sampled_partisan: pd.DataFrame,
    enacted_partisan: pd.DataFrame,
    plans_matrix: pd.DataFrame,
    geoids: list[str],
    vtd_composite: pd.DataFrame,
    n_districts: int = 14,
    n_sample: int = 500,
) -> dict:
    """
    Build river chart data: for a random sample of plans, sort districts by
    partisan lean and compute p5/p50/p95 bands.  Include enacted overlay.
    """
    # Sample plans
    rng = np.random.default_rng(42)
    all_draws = sampled_partisan.index.tolist()
    sample_draws = rng.choice(all_draws, min(n_sample, len(all_draws)), replace=False)

    # Need per-district dem_2pv for sampled plans
    vtd_lookup = vtd_composite.set_index("GEOID20")[["composite_dem_2pv", "VAP_MOD"]]
    aligned = pd.Series(geoids, name="GEOID20").to_frame().join(vtd_lookup, on="GEOID20", how="left").fillna(0)
    dem_v = (aligned["composite_dem_2pv"] * aligned["VAP_MOD"]).values
    tot_v = aligned["VAP_MOD"].values

    # Get column indices for sampled draws
    sampled_cols_df = plans_matrix.drop(columns=["cd_2020"])
    # draw i → column index i-1 (V2=draw1, V3=draw2, ...)
    col_indices = [d - 1 for d in sample_draws]
    sample_assignments = sampled_cols_df.values[:, col_indices].astype(np.int8)  # (2698, n_sample)

    ribbons = []
    for pi in range(sample_assignments.shape[1]):
        asgn = sample_assignments[:, pi]
        d2pv_plan = []
        for d in range(1, n_districts + 1):
            mask = (asgn == d)
            dv = (dem_v * mask).sum()
            tv = (tot_v * mask).sum()
            d2pv_plan.append(dv / tv if tv > 0 else 0.5)
        ribbons.append(sorted(d2pv_plan))

    arr = np.array(ribbons)                              # (n_sample, 14)
    p5, p50, p95 = np.percentile(arr, [5, 50, 95], axis=0)

    # Enacted overlay
    enacted_col = plans_matrix["cd_2020"].values.astype(np.int8)
    enacted_d2pv = []
    for d in range(1, n_districts + 1):
        mask = (enacted_col == d)
        dv = (dem_v * mask).sum()
        tv = (tot_v * mask).sum()
        enacted_d2pv.append(round(dv / tv, 4) if tv > 0 else 0.5)
    enacted_sorted = sorted(enacted_d2pv)

    return {
        "n_draws":     len(sample_draws),
        "n_districts": n_districts,
        "p5":          [round(float(v), 4) for v in p5],
        "p50":         [round(float(v), 4) for v in p50],
        "p95":         [round(float(v), 4) for v in p95],
        "enacted":     [round(float(v), 4) for v in enacted_sorted],
        "enacted_district_ids": list(range(1, n_districts + 1)),
    }


# ── Step 6: enacted plan district breakdown ───────────────────────────────────

def build_enacted_districts(
    plans_matrix: pd.DataFrame,
    geoids: list[str],
    vtd_composite: pd.DataFrame,
    n_districts: int = 14,
) -> list[dict]:
    """Build per-district dem_2pv and VAP data for the enacted plan."""
    vtd_lookup = vtd_composite.set_index("GEOID20")[["composite_dem_2pv", "VAP_MOD",
                                                       "centroid_lat", "centroid_lon"]]
    aligned = pd.Series(geoids, name="GEOID20").to_frame().join(
        vtd_lookup, on="GEOID20", how="left"
    ).fillna(0)
    dem_v = (aligned["composite_dem_2pv"] * aligned["VAP_MOD"]).values
    tot_v = aligned["VAP_MOD"].values
    lat_v = aligned["centroid_lat"].values
    lon_v = aligned["centroid_lon"].values

    enacted_col = plans_matrix["cd_2020"].values.astype(int)
    districts = []
    for d in range(1, n_districts + 1):
        mask = (enacted_col == d)
        tv   = tot_v[mask].sum()
        dv   = dem_v[mask].sum()
        d2pv = round(dv / tv, 4) if tv > 0 else 0.5
        # VAP-weighted centroid
        if tv > 0:
            lat_c = round(float((lat_v[mask] * tot_v[mask]).sum() / tv), 5)
            lon_c = round(float((lon_v[mask] * tot_v[mask]).sum() / tv), 5)
        else:
            lat_c = lon_c = 0.0
        districts.append({
            "id":           f"GA-{d:02d}",
            "district_num": d,
            "dem_2pv":      d2pv,
            "total_vap":    int(tv),
            "centroid_lat": lat_c,
            "centroid_lon": lon_c,
        })

    return sorted(districts, key=lambda x: x["dem_2pv"])


# ── Main ──────────────────────────────────────────────────────────────────────

def build_alarm_scorecard(
    chamber: str = "congress",
    competitive_margin: float = COMPETITIVE_THRESHOLD_DEFAULT,
    out_dir: Path = _DEFAULT_OUT,
) -> dict:
    today = date.today().isoformat()
    run_id = f"fdga_2026_benchmark_{chamber}_alarm"

    print(f"\nBuilding ALARM scorecard: {run_id}")

    # ── Load source data ──
    print("\n[1/6] Loading source data…")
    if not ALARM_RDS.exists():
        raise FileNotFoundError(f"ALARM map not found: {ALARM_RDS}")
    if not PLANS_MATRIX.exists():
        raise FileNotFoundError(f"Plans matrix not found: {PLANS_MATRIX}")
    if not _VTD_COMPOSITE.exists():
        raise FileNotFoundError(f"VTD composite not found: {_VTD_COMPOSITE}")

    geoids = export_geoids_from_rds(ALARM_RDS)
    assert len(geoids) == 2698, f"Expected 2698 GEOIDs, got {len(geoids)}"

    print("  Loading plans matrix…")
    plans_matrix = pd.read_csv(PLANS_MATRIX)
    assert len(plans_matrix) == len(geoids), (
        f"Plans matrix rows ({len(plans_matrix)}) != GEOID count ({len(geoids)})"
    )
    print(f"  Plans matrix: {len(plans_matrix)} VTDs × {len(plans_matrix.columns)} plans")

    print("  Loading VTD composite…")
    vtd_composite = pd.read_parquet(_VTD_COMPOSITE)
    print(f"  VTD composite: {len(vtd_composite)} VTDs, "
          f"statewide dem 2PV: {vtd_composite['composite_dem_2pv'].mean():.4f}")

    if not _VTD_CVAP.exists():
        raise FileNotFoundError(
            f"CVAP parquet not found: {_VTD_CVAP}\n"
            "  Run build_cvap_vtd.py first."
        )
    cvap_vtd = pd.read_parquet(_VTD_CVAP)
    print(f"  CVAP: {len(cvap_vtd)} VTDs (2024 ACS, any-part Black)")

    # ── Partisan metrics ──
    print("\n[2/6] Computing partisan metrics (vectorised)…")
    sampled_partisan, enacted_partisan = compute_partisan_metrics(
        plans_matrix, geoids, vtd_composite,
        n_districts=14, competitive_margin=competitive_margin,
    )
    print(f"  Sampled: {len(sampled_partisan)} plans · "
          f"median Dem seats: {sampled_partisan['dem_seats'].median():.1f}")
    print(f"  Enacted: dem_seats={enacted_partisan['dem_seats'].iloc[0]:.0f}  "
          f"egap={enacted_partisan['efficiency_gap'].iloc[0]:.4f}  "
          f"mm={enacted_partisan['mean_median'].iloc[0]:.4f}")

    # ── Non-partisan metrics ──
    print("\n[3/6] Loading non-partisan metrics from stats CSV…")
    sampled_geo, enacted_geo = load_nonpartisan_metrics(STATS_CSV)
    print(f"  Polsby-Popper enacted: {enacted_geo['polsby_popper'].iloc[0]:.3f}  "
          f"county_splits: {enacted_geo['county_splits'].iloc[0]:.0f}")

    # Replace BVAP-based maj_black / min_coal with 2024 ACS CVAP equivalents so
    # both ALARM and GerryChain ensembles share the same VRA §2 denominator.
    sampled_cvap, enacted_cvap = compute_cvap_demographics(plans_matrix, geoids, cvap_vtd)
    sampled_geo["maj_black"] = sampled_cvap["maj_black"].reindex(sampled_geo.index).fillna(0)
    sampled_geo["min_coal"]  = sampled_cvap["min_coal"].reindex(sampled_geo.index).fillna(0)
    enacted_geo.loc[:, "maj_black"] = float(enacted_cvap["maj_black"].iloc[0])
    enacted_geo.loc[:, "min_coal"]  = float(enacted_cvap["min_coal"].iloc[0])
    print(f"  CVAP maj_black (enacted): {enacted_geo['maj_black'].iloc[0]:.0f}  "
          f"min_coal: {enacted_geo['min_coal'].iloc[0]:.0f}")

    # ── Grade all metrics ──
    print("\n[4/6] Computing Princeton grades…")
    metric_grades = grade_all_metrics(
        sampled_partisan, enacted_partisan, sampled_geo, enacted_geo
    )
    print("  Metric grades: " + " · ".join(
        f"{k}={v['grade']}" for k, v in metric_grades.items() if not k.startswith("_")
    ))

    # ── Build composite grades ──
    # Package election metrics into the format _build_composite_grades expects
    election_entry = {
        "label":   "2018–2024 Composite",
        "office":  "composite",
        "year":    0,
        "metrics": {
            k: metric_grades[k]
            for k in ["dem_seats", "efficiency_gap", "mean_median", "comp_seats"]
            if k in metric_grades
        },
    }
    demographics = {
        "source": "cvap",
        "year":   2024,  # 2024 ACS CVAP Special Tabulation (any-part Black)
        "metrics": {
            k: metric_grades[k]
            for k in ["maj_black", "min_coal"]
            if k in metric_grades
        },
    }
    composite_grades = _build_composite_grades([election_entry], demographics, 14)
    top_grades = {**composite_grades, **demographics["metrics"]}
    # Add geographic metrics (polsby_popper, county_splits, muni_splits)
    for key in ["polsby_popper", "county_splits", "muni_splits"]:
        if key in metric_grades:
            top_grades[key] = metric_grades[key]
    print(f"  Overall: {top_grades.get('_overall', {}).get('grade', '?')}  "
          f"Partisan: {top_grades.get('_partisan_fairness', {}).get('grade', '?')}")

    # ── Correlations ──
    print("\n[5/7] Computing correlation matrix + scatter pairs…")
    correlations = build_alarm_correlations(
        sampled_partisan, enacted_partisan, sampled_geo, enacted_geo
    )
    if correlations:
        muni_row = correlations["matrix"].get("muni_splits", {})
        print(f"  muni_splits ↔ dem_seats: r={muni_row.get('dem_seats', '?')}")
        print(f"  muni_splits ↔ efficiency_gap: r={muni_row.get('efficiency_gap', '?')}")
    else:
        print("  WARNING: correlations could not be computed (insufficient data)")

    # ── River data ──
    print("\n[6/7] Building river chart data (500-plan sample)…")
    river = build_river(
        sampled_partisan, enacted_partisan,
        plans_matrix, geoids, vtd_composite,
    )
    election_entry["river"] = river

    # ── Enacted districts ──
    print("\n[7/7] Building enacted district breakdown…")
    enacted_districts = build_enacted_districts(plans_matrix, geoids, vtd_composite)

    # Enacted plan grades + metrics for plans section
    enacted_plan_grades = {
        k: v for k, v in top_grades.items() if k.startswith("_")
    }
    enacted_plan_metrics = {
        k: {
            "value":    round(float(enacted_partisan[k].iloc[0]), 4),
            "pct_rank": round(float(metric_grades[k]["pct_rank"]), 1),
            "grade":    metric_grades[k]["grade"],
        }
        for k in ["dem_seats", "efficiency_gap", "mean_median", "comp_seats"]
        if k in metric_grades and k in enacted_partisan.columns
    }

    # ── Assemble scorecard ──
    scorecard = {
        "run": {
            "id":          run_id,
            "name":        f"FDGA 2026 ALARM Benchmark — {chamber.title()}",
            "source":      "alarm",
            "source_run":  "GA_cd_2020",
            "chamber":     chamber,
            "n_districts": 14,
            "n_draws":     len(sampled_partisan),
            "n_plans":     len(sampled_partisan) + 1,
            "algorithm":   "SMC (Sequential Monte Carlo)",
            "date":        today,
            "description": (
                f"ALARM Project SMC ensemble for Georgia {chamber} redistricting. "
                "Re-scored with the 2018–2024 six-election composite (2018 Governor, "
                "2020 President, 2021 Warnock Senate Runoff, 2022 Governor, 2022 Senate, "
                "2024 President) to match the GerryChain benchmark electoral baseline. "
                "Non-partisan metrics (compactness, splits, minority VAP) are from the "
                "original ALARM stats CSV (ALARM Project via Harvard Dataverse, "
                "doi:10.7910/DVN/SLCD3E)."
            ),
            "tags":        ["alarm", "smc", "congress"],
            "elections": [
                {
                    "year":           0,
                    "election_type":  "composite",
                    "office":         "composite",
                    "label":          "2018–2024 Composite",
                }
            ],
        },
        "elections":    [election_entry],
        "demographics": demographics,
        "compactness":  {
            k: metric_grades.get(k)
            for k in ["polsby_popper", "county_splits", "muni_splits"]
        },
        "correlations": correlations,
        "grades": top_grades,
        "plans": [
            {
                "id":           "enacted",
                "label":        "Enacted Congress Map",
                "source":       "catalog",
                "grades":       enacted_plan_grades,
                "metrics":      enacted_plan_metrics,
                "districts":    enacted_districts,
            }
        ],
    }

    return scorecard


def main():
    ap = argparse.ArgumentParser(description="Build ALARM scorecard with 2018-2024 composite")
    ap.add_argument("--chamber", default="congress",
                    choices=["congress", "senate", "house"],
                    help="Chamber to score (default: congress)")
    ap.add_argument("--competitive-threshold", type=float,
                    default=COMPETITIVE_THRESHOLD_DEFAULT,
                    help=f"Win-margin threshold for competitive seats "
                         f"(default: {COMPETITIVE_THRESHOLD_DEFAULT})")
    ap.add_argument("--out", default=None,
                    help="Output directory (default: fdensemble/input_data/)")
    args = ap.parse_args()

    out_dir = Path(args.out) if args.out else _DEFAULT_OUT
    out_dir.mkdir(parents=True, exist_ok=True)

    scorecard = build_alarm_scorecard(
        chamber=args.chamber,
        competitive_margin=args.competitive_threshold,
        out_dir=out_dir,
    )

    out_file = out_dir / f"fdga_2026_benchmark_{args.chamber}_alarm_scorecard.json"
    out_file.write_text(json.dumps(scorecard, indent=2, default=str))
    size_kb = out_file.stat().st_size / 1024

    ds = scorecard["elections"][0]["metrics"].get("dem_seats", {})
    print(f"\n✓  {out_file.name}  ({size_kb:.0f} KB)")
    print(f"   Overall grade  : {scorecard['grades'].get('_overall', {}).get('grade', '?')}")
    print(f"   Partisan grade : {scorecard['grades'].get('_partisan_fairness', {}).get('grade', '?')}")
    print(f"   dem_seats      : enacted={ds.get('enacted')}  pct_rank={ds.get('pct_rank')}  grade={ds.get('grade')}")
    print()
    print("Deploy: the scorecard is already in fdensemble/input_data/ — "
          "restart the server (or Railway will redeploy on git push) to load it.")


if __name__ == "__main__":
    main()
