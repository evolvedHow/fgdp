"""
modal_app.py — GerryChain ensemble compute on Modal.

This module defines the Modal app for running GerryChain ReCom MCMC ensemble
chains on serverless Modal CPUs. It is the ONLY compute layer — there is no
API server. Results (plan parquets) are written to the Modal volume and then
downloaded locally for scoring via the fdp pipeline.

─── Volume layout ─────────────────────────────────────────────────────────────

  Persistent volume "fdga-chain-data" mounted at /data:

    /data/graphs/    — pre-built VTD dual graphs (ga_{chamber}.json)
    /data/ensemble/  — plan assignment parquets written by ensemble runs

─── Day-to-day workflow ───────────────────────────────────────────────────────

  # Run an ensemble on Modal (blocking):
  cd ~/codebox/fgdp/ensemble
  modal deploy modal_app.py
  uv run python scripts/run_ensemble.py \\
      --run-name congress_2026_v3 \\
      --config ../fdp/configs/benchmarks/ga_congress_2026_v2.yml \\
      --modal

  # Check what's in the volume:
  modal run modal_app.py::list_volume

  # Download a completed plans file:
  modal volume get fdga-chain-data /ensemble/{run_name}_plans.parquet .

  # After downloading, run the scoring pipeline (from fgdp/ root):
  uv run --project fdp python fdp/scripts/score_ensemble_plans.py --run-name {run_name}
  uv run --project fdp python fdp/scripts/score_ensemble_demographics.py --run-name {run_name} ...
  uv run --project fdp python fdp/scripts/build_draw_stats.py --run-name {run_name}
  uv run --project fdp python fdp/scripts/build_scorecard.py --run-name {run_name}
  cp fdp/data/repos/main/ensemble/{run_name}_scorecard.json fdensemble/input_data/

─── One-time setup ────────────────────────────────────────────────────────────

  pip install modal && modal setup
  cd ~/codebox/fgdp/ensemble
  modal deploy modal_app.py
  uv run python scripts/upload_to_modal.py   # uploads graphs to volume

─── Re-deploy after code changes ──────────────────────────────────────────────

  cd ~/codebox/fgdp/ensemble
  modal deploy modal_app.py
"""

import modal

# ---------------------------------------------------------------------------
# Volume
# ---------------------------------------------------------------------------

data_volume = modal.Volume.from_name("fdga-chain-data", create_if_missing=True)

# ---------------------------------------------------------------------------
# Compute image — GerryChain + geospatial stack
# ---------------------------------------------------------------------------

_PYPI_DEPS = [
    "fiona>=1.10.1",
    "geopandas>=1.1.3",
    "gerrychain>=0.3.2",
    "numpy>=1.26",
    "pandas>=2.0",
    "pyarrow>=14.0",
    "pyproj>=3.6",
    "python-dotenv>=1.0",
    "shapely>=2.0",
]

ensemble_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("libgdal-dev", "gdal-bin", "libspatialindex-dev")
    .pip_install(_PYPI_DEPS)
    .add_local_dir("scripts", remote_path="/root/scripts")
    .add_local_file("pyproject.toml", remote_path="/root/pyproject.toml")
)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = modal.App("fdga-chain")

# ---------------------------------------------------------------------------
# Single chain — runs one MCMC chain, writes to volume
# ---------------------------------------------------------------------------

@app.function(
    image   = ensemble_image,
    volumes = {"/data": data_volume},
    cpu     = 4,
    memory  = 8192,
    timeout = 14400,      # 4 hours — sufficient for House (180 districts)
)
def run_single_chain_modal(
    run_name:  str,
    chain_idx: int,
    params:    dict,
) -> str:
    """
    Run one MCMC chain on Modal.
    Writes chain assignments to /data/ensemble/{run_name}_chain{i}_plans.parquet.
    Returns the volume path of the written file.
    """
    import os
    import sys
    sys.path.insert(0, "/root")
    os.chdir("/")

    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq

    from scripts.run_ensemble import run_chain
    from gerrychain import Graph

    DISTRICT_COLS = {"house": "HDIST", "senate": "SDIST", "congress": "CDIST"}

    mcmc    = params["mcmc"]
    chamber = params["chamber"]
    geo     = params["geography"]

    graph_path = f"/data/graphs/ga_{chamber['name']}.json"
    if not os.path.exists(graph_path):
        raise FileNotFoundError(
            f"Graph not found at {graph_path}. "
            "Upload it first: uv run python scripts/upload_to_modal.py"
        )

    print(f"[chain {chain_idx}] Loading graph from {graph_path}")
    graph = Graph.from_json(graph_path)

    seed = mcmc.get("random_seed")
    if seed is not None:
        seed = seed + chain_idx

    dist_col = DISTRICT_COLS.get(chamber["name"], "CDIST")
    sample_attrs = graph.nodes[next(iter(graph.nodes()))]
    if dist_col not in sample_attrs:
        fallbacks = [
            k for k in sample_attrs
            if chamber["name"][:3].upper() in k.upper() and "DIST" in k.upper()
        ]
        if fallbacks:
            dist_col = fallbacks[0]
        else:
            raise ValueError(
                f"District column '{dist_col}' not found in graph. "
                f"Available: {list(sample_attrs.keys())}"
            )

    plan_matrix, node_order = run_chain(
        graph        = graph,
        pop_column   = chamber["pop_column"],
        district_col = dist_col,
        n_steps      = mcmc["n_steps"],
        burn_in      = mcmc["burn_in"],
        epsilon      = mcmc["pop_epsilon"],
        algo         = mcmc["algorithm"],
        seed         = seed,
    )

    geoid_attr = next(
        (a for a in ["GEOID20", "GEOID", "geoid", "GEOID10"] if a in sample_attrs),
        None,
    )
    geoid_map = (
        {n: str(graph.nodes[n][geoid_attr]) for n in graph.nodes()}
        if geoid_attr
        else {n: str(n) for n in graph.nodes()}
    )

    n_draws, n_nodes = plan_matrix.shape
    geoids     = np.array([geoid_map.get(n, str(n)) for n in node_order])
    total_rows = n_draws * n_nodes

    table = pa.table({
        "plan_id":   pa.array([run_name]          * total_rows, type=pa.string()),
        "draw":      pa.array(np.repeat(np.arange(1, n_draws + 1, dtype=np.int32), n_nodes), type=pa.int32()),
        "geoid":     pa.array(np.tile(geoids, n_draws),         type=pa.string()),
        "district":  pa.array(plan_matrix.flatten().astype(np.int32), type=pa.int32()),
        "geo_level": pa.array([geo["geo_level"]]  * total_rows, type=pa.string()),
        "state":     pa.array([geo["state"]]       * total_rows, type=pa.string()),
        "chamber":   pa.array([chamber["name"]]    * total_rows, type=pa.string()),
    })

    out_dir  = "/data/ensemble"
    os.makedirs(out_dir, exist_ok=True)
    out_path = f"{out_dir}/{run_name}_chain{chain_idx}_plans.parquet"

    pq.write_table(table, out_path, compression="zstd")
    size_mb = os.path.getsize(out_path) / 1_048_576
    print(f"[chain {chain_idx}] Written {n_draws:,} draws → {out_path}  ({size_mb:.1f} MB)")

    data_volume.commit()
    return out_path


# ---------------------------------------------------------------------------
# Orchestrator — runs all chains, concatenates, writes final parquet
# ---------------------------------------------------------------------------

@app.function(
    image   = ensemble_image,
    volumes = {"/data": data_volume},
    cpu     = 2,
    memory  = 4096,
    timeout = 86400,   # 24 hours — orchestration overhead
)
def run_ensemble_on_modal(run_name: str, params: dict) -> dict:
    """
    Orchestrate a full benchmark ensemble run on Modal.
    Called from scripts/run_ensemble.py with --modal or --modal-async.

    Flow:
    1. Run n_chains in parallel via run_single_chain_modal.starmap()
    2. Concatenate plan files, re-number draws sequentially (draw=1 = enacted)
    3. Write final {run_name}_plans.parquet to volume
    4. Clean up per-chain temp files
    5. Return summary dict
    """
    import os, sys, json, time, datetime
    sys.path.insert(0, "/root")
    os.chdir("/")

    import pyarrow as pa
    import pyarrow.parquet as pq

    # catalog_write_start/end gracefully skip when DATABASE_URL is not set
    from scripts.run_ensemble import catalog_write_start, catalog_write_end

    mcmc      = params["mcmc"]
    chamber   = params["chamber"]["name"]
    n_chains  = mcmc.get("n_chains", 1)
    out_dir   = "/data/ensemble"
    os.makedirs(out_dir, exist_ok=True)
    plans_path = f"{out_dir}/{run_name}_plans.parquet"
    meta_path  = f"{out_dir}/{run_name}_meta.json"

    print(f"\n{'='*60}")
    print(f"MODAL ENSEMBLE RUN: {run_name}")
    print(f"  chamber  : {chamber}")
    print(f"  algorithm: {mcmc['algorithm']}")
    print(f"  steps    : {mcmc['n_steps']:,}  burn_in={mcmc['burn_in']:,}")
    print(f"  chains   : {n_chains}")
    print(f"{'='*60}\n")

    catalog_write_start(run_name, params.get("benchmark_id", "unknown"), params)
    start = time.time()

    try:
        if n_chains > 1:
            print(f"Running {n_chains} chains in parallel on Modal…")
            chain_paths = []
            for result in run_single_chain_modal.starmap(
                [(run_name, i, params) for i in range(n_chains)],
                return_exceptions=True,
            ):
                if isinstance(result, Exception):
                    print(f"  WARNING: chain failed — {type(result).__name__}: {result}")
                else:
                    chain_paths.append(result)
            if not chain_paths:
                raise RuntimeError("All chains failed — no usable draws produced.")
            print(f"  {len(chain_paths)}/{n_chains} chains succeeded.")
        else:
            print("Running 1 chain on Modal…")
            chain_paths = [run_single_chain_modal.remote(run_name, 0, params)]

        data_volume.reload()

        print(f"\nConcatenating {len(chain_paths)} chain file(s)…")
        tables = []
        draw_offset = 0

        for path in chain_paths:
            if not os.path.exists(path):
                print(f"  WARNING: chain file not found: {path} — skipping")
                continue
            tbl    = pq.read_table(path)
            draws  = tbl.column("draw").to_pylist()
            max_d  = max(draws)
            new_draws = [d + draw_offset for d in draws]
            draw_offset += max_d
            tbl = tbl.set_column(
                tbl.schema.get_field_index("draw"), "draw",
                pa.array(new_draws, type=pa.int32()),
            )
            tables.append(tbl)

        combined   = pa.concat_tables(tables)
        total_rows = combined.num_rows
        n_draws    = draw_offset
        n_vtds     = total_rows // n_draws if n_draws > 0 else 0

        pq.write_table(combined, plans_path, compression="zstd")
        size_mb = os.path.getsize(plans_path) / 1_048_576

        for path in chain_paths:
            try: os.remove(path)
            except OSError: pass

        runtime = time.time() - start
        meta = {
            **params,
            "ran_at":          datetime.datetime.now().isoformat(timespec="seconds"),
            "runtime_seconds": round(runtime, 1),
            "n_draws":         n_draws,
            "n_vtds":          n_vtds,
            "n_chains_run":    n_chains,
            "plans_file":      plans_path,
        }
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2, default=str)

        data_volume.commit()

        summary = {
            "run_name":        run_name,
            "status":          "completed",
            "n_draws":         n_draws,
            "n_vtds":          n_vtds,
            "n_chains":        n_chains,
            "runtime_minutes": round(runtime / 60, 1),
            "plans_file":      plans_path,
            "size_mb":         round(size_mb, 1),
        }

        print(f"\n{'='*60}")
        print(f"COMPLETE: {run_name}")
        print(f"  {n_draws:,} draws | {n_vtds:,} VTDs | {runtime/60:.1f} min | {size_mb:.1f} MB")
        print(f"  Plans: {plans_path}")
        print(f"  Next: download and run fdp scoring pipeline")
        print(f"{'='*60}")

        catalog_write_end(run_name, status="completed", n_draws=n_draws,
                          n_vtds=n_vtds, n_chains_run=n_chains,
                          runtime_seconds=runtime, plans_file=plans_path)
        return summary

    except Exception as exc:
        runtime = time.time() - start
        print(f"\nERROR after {runtime/60:.1f} min: {exc}")
        catalog_write_end(run_name, status="failed", runtime_seconds=runtime,
                          error_message=str(exc))
        raise


# ---------------------------------------------------------------------------
# Utility: list volume contents
# Usage:  modal run modal_app.py::list_volume
# ---------------------------------------------------------------------------

@app.function(image=ensemble_image, volumes={"/data": data_volume}, timeout=60)
def list_volume():
    """Print everything in the data volume with sizes."""
    import os
    from pathlib import Path

    data_dir = Path("/data")
    if not data_dir.exists() or not any(data_dir.iterdir()):
        print("Volume /data is empty. Run: uv run python scripts/upload_to_modal.py")
        return

    total_bytes = 0
    for root, dirs, files in os.walk(data_dir):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for f in sorted(files):
            fpath = Path(root) / f
            size  = fpath.stat().st_size
            total_bytes += size
            print(f"  {str(fpath.relative_to(data_dir)):<70}  {size/1024:>8.1f} kB")

    print(f"\n  Total: {total_bytes/1024/1024:.1f} MB")


# ---------------------------------------------------------------------------
# Utility: list ensemble runs in volume
# Usage:  modal run modal_app.py::list_runs
# ---------------------------------------------------------------------------

@app.function(image=ensemble_image, volumes={"/data": data_volume}, timeout=60)
def list_runs():
    """Print ensemble plan files in the Modal volume."""
    import os

    ens_dir = "/data/ensemble"
    if not os.path.exists(ens_dir) or not os.listdir(ens_dir):
        print("No ensemble files yet in /data/ensemble")
        return

    print(f"\n{'File':<60}  {'Size':>8}")
    print("-" * 72)
    for f in sorted(os.listdir(ens_dir)):
        fpath = os.path.join(ens_dir, f)
        size_mb = os.path.getsize(fpath) / 1_048_576
        print(f"  {f:<58}  {size_mb:>6.1f} MB")
