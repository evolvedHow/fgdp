"""
build_graph.py — Build GerryChain dual graphs from a Census VTD shapefile.

Produces one graph per chamber. Every node is a Census VTD with GEOID20 as
its identifier, matching Supabase, ALARM, and all FDP data.

Node attributes on every graph
-------------------------------
  GEOID20     11-char Census VTD identifier (e.g. '13001000001')
  TOTPOP      Total population (P0010001 or TOTPOP)
  VAP_MOD     VAP minus correctional pop (P0040001 - P0050003)
  COUNTYFP20  5-char county FIPS (for county-aware proposals)
  {dist_col}  Enacted district assignment — column name from --district-col

Usage
-----
# Georgia — build all three chambers (auto-detects GA shapefiles)
    uv run python scripts/build_graph.py --state ga

# Single chamber
    uv run python scripts/build_graph.py --state ga --chamber congress

# Other state — specify VTD shapefile + enacted shapefiles explicitly
    uv run python scripts/build_graph.py \\
        --state nc \\
        --vtd-file data/raw/nc_pl2020_vtd.zip \\
        --enacted congress=data/raw/NC-Congress-2023.shp:CDIST \\
        --enacted senate=data/raw/NC-Senate-2023.shp:SDIST \\
        --enacted house=data/raw/NC-House-2023.shp:HDIST

# Custom district column name
    uv run python scripts/build_graph.py \\
        --state pa --chamber congress \\
        --enacted congress=data/raw/PA-Congress.shp:CONG_DIST

After building, upload graphs to Modal:
    python scripts/upload_to_modal.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import networkx as nx
import pandas as pd
from gerrychain import Graph


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
CHAIN_ROOT = SCRIPT_DIR.parent
DATA_RAW   = CHAIN_ROOT / "data" / "raw"
DATA_GRAPH = CHAIN_ROOT / "data" / "graphs"


# ---------------------------------------------------------------------------
# State defaults — auto-detected when --state is known
# ---------------------------------------------------------------------------

# VTD shapefile search paths per state (first found wins)
VTD_SEARCH_PATHS: dict[str, list[Path]] = {
    "ga": [
        DATA_RAW / "ga_pl2020_vtd.zip",
        CHAIN_ROOT.parent / "fdensemble" / "input_data" / "ga_pl2020_vtd.zip",
        CHAIN_ROOT.parent / "input_datasets" / "ga_pl2020_vtd.zip",
        DATA_RAW / "ga_pl2020_vtd.shp",
    ],
}

# Default enacted shapefiles per state: {chamber: (path, district_col)}
ENACTED_DEFAULTS: dict[str, dict[str, tuple[Path, str]]] = {
    "ga": {
        "congress": (DATA_RAW / "Congress-2023 shape.shp",       "CDIST"),
        "senate":   (DATA_RAW / "Senate-2023 shape file.shp",    "SDIST"),
        "house":    (DATA_RAW / "House-2023 shape.shp",          "HDIST"),
    },
}

# UTM zones for automatic area-accurate projection.
# Used when --proj-crs is not specified. Keys are state abbreviations.
# Auto-detection from centroid longitude is used when state is unknown.
UTM_DEFAULTS: dict[str, str] = {
    "ga": "EPSG:32617",   # UTM zone 17N
    "nc": "EPSG:32617",   # UTM zone 17N
    "pa": "EPSG:32618",   # UTM zone 18N
    "tx": "EPSG:32614",   # UTM zone 14N
    "fl": "EPSG:32617",   # UTM zone 17N
    "va": "EPSG:32618",   # UTM zone 18N
    "ca": "EPSG:32610",   # UTM zone 10N
    "ny": "EPSG:32618",   # UTM zone 18N
    "mi": "EPSG:32616",   # UTM zone 16N
    "wi": "EPSG:32616",   # UTM zone 16N
    "oh": "EPSG:32617",   # UTM zone 17N
    "il": "EPSG:32616",   # UTM zone 16N
}

# Columns kept from VTD shapefile — everything else dropped before graph build
VTD_KEEP = ["GEOID20", "COUNTYFP20", "TOTPOP", "VAP_MOD", "geometry"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utm_from_centroid(gdf: gpd.GeoDataFrame) -> str:
    """Estimate UTM zone CRS from dataset centroid longitude."""
    centroid = gdf.to_crs("EPSG:4326").unary_union.centroid
    zone = int((centroid.x + 180) / 6) + 1
    hemisphere = "N" if centroid.y >= 0 else "S"
    epsg = 32600 + zone if hemisphere == "N" else 32700 + zone
    return f"EPSG:{epsg}"


def _parse_enacted_arg(val: str) -> tuple[str, Path, str]:
    """
    Parse a --enacted argument of the form  chamber=path:dist_col
    or  chamber=path  (dist_col inferred from chamber name).

    Returns (chamber_name, shapefile_path, district_col).
    """
    if "=" not in val:
        raise argparse.ArgumentTypeError(
            f"--enacted must be  chamber=path[:dist_col], got: {val!r}"
        )
    chamber, rest = val.split("=", 1)
    if ":" in rest:
        path_str, dist_col = rest.rsplit(":", 1)
    else:
        path_str = rest
        # Infer dist_col from chamber name: congress→CDIST, senate→SDIST, house→HDIST
        dist_col = chamber[:1].upper() + "DIST"
    return chamber.strip(), Path(path_str.strip()), dist_col.strip()


# ---------------------------------------------------------------------------
# Step 1 — Load and slim the VTD shapefile
# ---------------------------------------------------------------------------

def load_vtd(vtd_path: Path) -> gpd.GeoDataFrame:
    print(f"Loading VTD shapefile: {vtd_path.name}")
    path_str = f"zip://{vtd_path}" if vtd_path.suffix == ".zip" else str(vtd_path)
    gdf = gpd.read_file(path_str)
    print(f"  {len(gdf):,} VTDs  |  CRS: {gdf.crs}")

    if "GEOID20" not in gdf.columns:
        raise ValueError("VTD shapefile missing GEOID20 column")

    gdf["GEOID20"] = gdf["GEOID20"].astype(str)

    # County FIPS — pad to 3 chars if present
    if "COUNTYFP20" in gdf.columns:
        gdf["COUNTYFP20"] = gdf["COUNTYFP20"].astype(str).str.zfill(3)
    else:
        gdf["COUNTYFP20"] = "000"

    # Population — accept P0010001 (PL 94-171 raw) or TOTPOP (pre-named)
    if "P0010001" in gdf.columns:
        gdf["TOTPOP"] = gdf["P0010001"].astype(int)
    elif "TOTPOP" in gdf.columns:
        gdf["TOTPOP"] = gdf["TOTPOP"].astype(int)
    else:
        raise ValueError("No population column found (expected P0010001 or TOTPOP)")

    # VAP_MOD = total VAP minus correctional facility population
    # This adjusts for prison gerrymandering in rural counties.
    if "P0040001" in gdf.columns and "P0050003" in gdf.columns:
        gdf["VAP_MOD"] = (gdf["P0040001"] - gdf["P0050003"]).clip(lower=0).astype(int)
    else:
        print("  NOTE: P0040001/P0050003 not found — VAP_MOD = 0 (no prison adjustment)")
        gdf["VAP_MOD"] = 0

    # Normalise to WGS84 for consistent spatial joins
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    print(f"  Total pop: {gdf['TOTPOP'].sum():,}")
    print(f"  GEOID20 sample: {gdf['GEOID20'].iloc[0]}")
    return gdf[VTD_KEEP].copy()


# ---------------------------------------------------------------------------
# Step 2 — Spatial join enacted districts onto VTDs
# ---------------------------------------------------------------------------

def join_districts(
    vtd_gdf: gpd.GeoDataFrame,
    enacted: dict[str, tuple[Path, str]],
    proj_crs: str,
) -> gpd.GeoDataFrame:
    """
    Add district assignment columns to the VTD GeoDataFrame.

    Uses largest-overlap (intersection area): each VTD is assigned to
    whichever enacted district covers the greatest share of its area.
    This is correct for all chamber sizes, including State House maps
    where districts can be smaller than individual VTDs.

    Parameters
    ----------
    vtd_gdf : GeoDataFrame
        The loaded VTD shapefile (WGS84).
    enacted : dict
        {chamber_name: (shapefile_path, output_col_name)}
    proj_crs : str
        A projected CRS (e.g. UTM zone) for area computations.
    """
    import warnings

    gdf      = vtd_gdf.copy()
    gdf_proj = gdf.to_crs(proj_crs)

    for chamber, (shp_path, out_col) in enacted.items():
        print(f"\n  Joining {chamber} districts ({shp_path.name}) → {out_col}…")

        if not shp_path.exists():
            print(f"    WARNING: {shp_path} not found — {out_col} = 0 for all VTDs")
            gdf[out_col] = 0
            continue

        enacted_gdf = gpd.read_file(shp_path).to_crs(proj_crs)

        # Locate the district ID column in the shapefile
        dist_src = "DISTRICT"
        if dist_src not in enacted_gdf.columns:
            # Fall back: any column with 'dist' in the name
            alt = next(
                (c for c in enacted_gdf.columns
                 if "dist" in c.lower() or "district" in c.lower()),
                None,
            )
            if alt:
                dist_src = alt
                print(f"    Using column: {dist_src}")
            else:
                print(f"    WARNING: no district column in {shp_path.name} — {out_col} = 0")
                print(f"    Columns available: {list(enacted_gdf.columns)}")
                gdf[out_col] = 0
                continue

        # Largest-overlap join:
        #   1. Intersect every VTD polygon with every district polygon
        #   2. Measure intersection area
        #   3. Assign each VTD to the district it overlaps most
        print(f"    Computing intersections (largest-overlap)…")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            overlay = gpd.overlay(
                gdf_proj[["GEOID20", "geometry"]],
                enacted_gdf[["geometry", dist_src]],
                how="intersection",
                keep_geom_type=False,
            )

        overlay["_area"] = overlay.geometry.area
        best_idx = overlay.groupby("GEOID20")["_area"].idxmax()
        best     = overlay.loc[best_idx].set_index("GEOID20")
        dist_map = best[dist_src].to_dict()

        gdf[out_col] = gdf["GEOID20"].map(dist_map)
        gdf[out_col] = (
            pd.to_numeric(gdf[out_col], errors="coerce")
            .fillna(0)
            .astype(int)
        )

        n_assigned = (gdf[out_col] > 0).sum()
        n_missing  = (gdf[out_col] == 0).sum()
        print(f"    {n_assigned:,} VTDs assigned  |  {n_missing} unassigned (set to 0)")
        if n_missing > 0:
            print(f"    Unassigned: {gdf.loc[gdf[out_col]==0, 'GEOID20'].tolist()[:5]}")

    return gdf


# ---------------------------------------------------------------------------
# Step 3 — Build and save GerryChain graph
# ---------------------------------------------------------------------------

def build_and_save(
    gdf:          gpd.GeoDataFrame,
    district_col: str,
    out_path:     Path,
) -> None:
    print(f"\n  Building dual graph (rook adjacency)…")
    graph = Graph.from_geodataframe(gdf, adjacency="rook")
    n_nodes = graph.number_of_nodes()
    n_edges = graph.number_of_edges()
    print(f"  {n_nodes:,} nodes  |  {n_edges:,} edges")

    # Connectivity check — disconnected graphs cause GerryChain errors
    components = list(nx.connected_components(graph))
    if len(components) > 1:
        sizes = sorted([len(c) for c in components], reverse=True)
        print(f"  WARNING: {len(components)} components — sizes: {sizes[:5]}")
        print(f"  Small island VTDs may cause GerryChain errors.")
    else:
        print(f"  ✓ Fully connected")

    # Spot-check key attributes
    sample = graph.nodes[next(iter(graph.nodes()))]
    for attr in ["GEOID20", "TOTPOP", district_col]:
        val = sample.get(attr, "MISSING")
        print(f"  [{attr}] sample: {val}")

    n_districts = max(graph.nodes[n].get(district_col, 0) for n in graph.nodes())
    total_pop   = sum(graph.nodes[n].get("TOTPOP", 0) for n in graph.nodes())
    print(f"  Districts: {n_districts}  |  Total pop: {total_pop:,}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    graph.to_json(str(out_path))
    size_mb = out_path.stat().st_size / 1_048_576
    print(f"  ✓ Saved: {out_path}  ({size_mb:.1f} MB)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--state",
        default="ga",
        help="Two-letter state abbreviation (default: ga). Used for output "
             "filename prefix and shapefile auto-discovery.",
    )
    parser.add_argument(
        "--chamber",
        default="all",
        help="Chamber to build: congress | senate | house | all (default: all). "
             "Can be any name that matches an --enacted entry.",
    )
    parser.add_argument(
        "--vtd-file",
        type=Path,
        default=None,
        help="Path to Census VTD shapefile or zip. Auto-detected from known "
             "paths if omitted.",
    )
    parser.add_argument(
        "--enacted",
        action="append",
        default=None,
        metavar="CHAMBER=PATH[:DIST_COL]",
        help="Enacted district shapefile for one chamber. Repeatable. "
             "Format: chamber=path/to/file.shp[:DISTRICT_COL_NAME]. "
             "DIST_COL defaults to first-letter-of-chamber + DIST (e.g. CDIST). "
             "Example: --enacted congress=data/raw/Congress.shp:CDIST. "
             "If omitted, uses built-in defaults for --state.",
    )
    parser.add_argument(
        "--proj-crs",
        default=None,
        help="Projected CRS for area calculations (e.g. EPSG:32617). "
             "Auto-detected from data centroid if omitted.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DATA_GRAPH,
        help="Output directory for graph JSON files (default: data/graphs/).",
    )
    args = parser.parse_args()

    state = args.state.lower()

    # ── Resolve enacted shapefiles ───────────────────────────────────────────
    enacted: dict[str, tuple[Path, str]] = {}

    if args.enacted:
        # User-supplied via CLI
        for raw in args.enacted:
            chamber, shp_path, dist_col = _parse_enacted_arg(raw)
            enacted[chamber] = (shp_path, dist_col)
    elif state in ENACTED_DEFAULTS:
        # Use built-in defaults for this state
        enacted = ENACTED_DEFAULTS[state]
        print(f"Using default enacted shapefiles for state={state}")
    else:
        print(f"ERROR: No --enacted shapefiles specified and no defaults for state={state!r}.")
        print(f"  Use --enacted CHAMBER=PATH[:DIST_COL] to specify each chamber.")
        sys.exit(1)

    # Filter to requested chamber(s)
    if args.chamber != "all":
        if args.chamber not in enacted:
            print(f"ERROR: Chamber {args.chamber!r} not in enacted dict.")
            print(f"  Available: {list(enacted.keys())}")
            sys.exit(1)
        enacted = {args.chamber: enacted[args.chamber]}

    # ── Find VTD shapefile ───────────────────────────────────────────────────
    vtd_path = args.vtd_file
    if vtd_path is None:
        candidates = VTD_SEARCH_PATHS.get(state, [])
        vtd_path   = next((p for p in candidates if p.exists()), None)
    if vtd_path is None or not vtd_path.exists():
        print(f"ERROR: VTD shapefile not found for state={state!r}.")
        print(f"  Tried: {VTD_SEARCH_PATHS.get(state, ['(no defaults)'])}")
        print(f"  Use --vtd-file to specify the path explicitly.")
        sys.exit(1)

    # ── Step 1: load VTD base ────────────────────────────────────────────────
    vtd_gdf = load_vtd(vtd_path)

    # ── Resolve projection CRS ───────────────────────────────────────────────
    proj_crs = args.proj_crs
    if proj_crs is None:
        proj_crs = UTM_DEFAULTS.get(state) or _utm_from_centroid(vtd_gdf)
        print(f"  Projection CRS: {proj_crs}")

    # ── Step 2: join all district assignments ────────────────────────────────
    print("\nJoining enacted district assignments…")
    vtd_gdf = join_districts(vtd_gdf, enacted, proj_crs)

    # ── Step 3: build graphs ─────────────────────────────────────────────────
    for chamber, (_, dist_col) in enacted.items():
        out_path = args.out_dir / f"{state}_{chamber}.json"
        print(f"\n{'='*60}")
        print(f"Building {out_path.name}  (district col: {dist_col})")
        print(f"{'='*60}")
        build_and_save(vtd_gdf, dist_col, out_path)

    print(f"\n{'='*60}")
    print("Done. Next steps:")
    print("  1. Upload:  python scripts/upload_to_modal.py")
    print("  2. Deploy:  modal deploy modal_app.py")
    print("  3. Test run (100 steps):")
    print(f"       uv run python scripts/run_ensemble.py \\")
    print(f"           --run-name test_100 --chamber congress --n-steps 100 --no-db --modal")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
