"""
run_ensemble.py — Config-driven GerryChain ReCom ensemble runner.

Every parameter comes from a YAML benchmark config (or its defaults).
Any scalar parameter can be overridden via CLI flag without editing the YAML.
Only --run-name is mandatory.

Usage
-----
# Minimal — use the default congress config, give the run a name:
    uv run python scripts/run_ensemble.py --run-name congress_baseline_v1

# With explicit config file:
    uv run python scripts/run_ensemble.py \\
        --run-name congress_test_rev \\
        --config ../fdp/configs/benchmarks/ga_congress_2026_v1.yml

# Override specific params on top of YAML defaults:
    uv run python scripts/run_ensemble.py \\
        --run-name congress_quick_test \\
        --config ../fdp/configs/benchmarks/ga_congress_2026_v1.yml \\
        --algorithm reversible_recom \\
        --n-steps 500 \\
        --burn-in 0 \\
        --n-chains 1

# Dry run — print resolved config and exit, no compute:
    uv run python scripts/run_ensemble.py \\
        --run-name debug \\
        --config ../fdp/configs/benchmarks/ga_congress_2026_v1.yml \\
        --dry-run

Output (written to config.output.dir)
--------------------------------------
  {run_name}_plans.parquet    — full VTD→district assignment matrix per draw
  {run_name}_meta.json        — resolved params + runtime summary

Schema of plans parquet
-----------------------
  plan_id   TEXT    — equals --run-name; used as plan_id in ensemble_scores
  draw      INT32   — 1-indexed draw number (burn-in excluded)
  geoid     TEXT    — VTD GEOID20 (11-char Census ID)
  district  INT32   — district number (1-indexed)
  geo_level TEXT    — vtd | precinct
  state     TEXT    — GA
  chamber   TEXT    — congress | senate | house

Supabase catalog
----------------
  fdp.ensemble_runs — one row per run; status updated running → completed/failed
  Requires DATABASE_URL env var.  Pass --no-db to skip catalog writes.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from functools import partial
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from gerrychain import GeographicPartition, Graph, MarkovChain
from gerrychain.accept import always_accept
from gerrychain.constraints import within_percent_of_ideal_population
from gerrychain.proposals import recom, reversible_recom
from gerrychain.tree import bipartition_tree
from gerrychain.updaters import Tally, cut_edges

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT  = SCRIPT_DIR.parent.parent           # fgdp/
FDP_ROOT   = REPO_ROOT / "fdp"

# Default config files per chamber
DEFAULT_CONFIGS: dict[str, Path] = {
    "congress": FDP_ROOT / "configs" / "benchmarks" / "ga_congress_2026_v1.yml",
    "senate":   FDP_ROOT / "configs" / "benchmarks" / "ga_senate_2026_v1.yml",
    "house":    FDP_ROOT / "configs" / "benchmarks" / "ga_house_2026_v1.yml",
}

# Canonical district column per chamber in the dual graph
# District column defaults kept for backward-compat when no config is loaded.
# Preferred: set chamber.district_col in the benchmark YAML, or use
# BenchmarkConfig.chamber.effective_district_col().
_DISTRICT_COL_DEFAULTS = {"house": "HDIST", "senate": "SDIST", "congress": "CDIST"}


# ---------------------------------------------------------------------------
# Lazy BenchmarkConfig import (fdp package in sibling directory)
# ---------------------------------------------------------------------------

def _load_benchmark_config():
    try:
        from fdp.benchmark_config import BenchmarkConfig
        return BenchmarkConfig
    except ImportError:
        if str(FDP_ROOT) not in sys.path:
            sys.path.insert(0, str(FDP_ROOT))
        from fdp.benchmark_config import BenchmarkConfig
        return BenchmarkConfig


# ---------------------------------------------------------------------------
# Catalog writes (Supabase)
# ---------------------------------------------------------------------------

def _db_url() -> str | None:
    return os.environ.get("DATABASE_URL")


def catalog_write_start(run_name: str, benchmark_id: str, params: dict) -> None:
    """Insert/upsert a 'running' row into fdp.ensemble_runs."""
    url = _db_url()
    if not url:
        print("  [catalog] DATABASE_URL not set — skipping catalog write")
        return
    try:
        import psycopg
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("SET SESSION default_transaction_read_only = off")
            conn.execute(
                """
                INSERT INTO fdp.ensemble_runs
                    (run_name, benchmark_id, status, started_at, params, loaded_by)
                VALUES (%s, %s, 'running', NOW(), %s, 'run_ensemble.py')
                ON CONFLICT (run_name) DO UPDATE SET
                    benchmark_id  = EXCLUDED.benchmark_id,
                    status        = 'running',
                    started_at    = NOW(),
                    params        = EXCLUDED.params,
                    error_message = NULL,
                    updated_at    = NOW()
                """,
                (run_name, benchmark_id, json.dumps(params)),
            )
        print(f"  [catalog] '{run_name}' registered (status=running)")
    except Exception as exc:  # noqa: BLE001
        print(f"  [catalog] WARNING: could not write start record — {exc}")


def catalog_write_end(
    run_name: str,
    *,
    status: str,
    n_draws: int | None = None,
    n_vtds: int | None = None,
    n_chains_run: int | None = None,
    runtime_seconds: float | None = None,
    plans_file: str | None = None,
    error_message: str | None = None,
) -> None:
    """Update the catalog row on completion or failure."""
    url = _db_url()
    if not url:
        return
    try:
        import psycopg
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("SET SESSION default_transaction_read_only = off")
            conn.execute(
                """
                UPDATE fdp.ensemble_runs SET
                    status           = %s,
                    completed_at     = NOW(),
                    n_draws          = %s,
                    n_vtds           = %s,
                    n_chains_run     = %s,
                    runtime_seconds  = %s,
                    plans_file       = %s,
                    error_message    = %s,
                    updated_at       = NOW()
                WHERE run_name = %s
                """,
                (
                    status,
                    n_draws,
                    n_vtds,
                    n_chains_run,
                    round(runtime_seconds, 1) if runtime_seconds is not None else None,
                    plans_file,
                    error_message,
                    run_name,
                ),
            )
        print(f"  [catalog] '{run_name}' → status={status}")
    except Exception as exc:  # noqa: BLE001
        print(f"  [catalog] WARNING: could not write end record — {exc}")


# ---------------------------------------------------------------------------
# Single MCMC chain
# ---------------------------------------------------------------------------

def run_chain(
    graph: Graph,
    pop_column: str,
    district_col: str,
    n_steps: int,
    burn_in: int,
    epsilon: float,
    algo: str,
    seed: int | None,
) -> tuple[np.ndarray, list]:
    """
    Run one MCMC chain.

    Returns
    -------
    plan_matrix : np.ndarray  (1 + n_usable_draws, n_nodes)  dtype int16
        Row 0   = enacted plan (from graph's district_col attribute)
        Rows 1+ = MCMC draws after burn-in

    node_order  : list of graph node IDs (column order for plan_matrix)

    Design:
    - Draw 1 (row 0) is ALWAYS the enacted plan read directly from the graph
      column, regardless of burn_in.
    - The chain starts from the enacted plan. GerryChain's validity constraint
      epsilon is auto-widened to the enacted map's actual VTD-level max deviation
      (plus 5% slack) so initialization never fails. The PROPOSAL still uses the
      target epsilon, so chain draws stay within the intended tolerance.
    - Burn-in steps are discarded before saving chain draws.
    """
    import random as _random
    from collections import defaultdict as _dd

    if seed is not None:
        _random.seed(seed)
        np.random.seed(seed)

    updaters = {
        "population": Tally(pop_column, alias="population"),
        "cut_edges":  cut_edges,
    }

    # ── Derive dimensions from the graph ────────────────────────────────────
    node_order  = list(graph.nodes())
    n_nodes     = len(node_order)
    node_index  = {n: i for i, n in enumerate(node_order)}

    total_pop   = sum(graph.nodes[n].get(pop_column, 0) for n in node_order)
    n_districts = len({graph.nodes[n][district_col] for n in node_order})
    ideal_pop   = total_pop / n_districts

    # ── Row 0: enacted plan — read directly from graph ───────────────────────
    # Always stored as draw=1 in the output, regardless of burn_in or epsilon.
    enacted_row = np.array(
        [graph.nodes[n][district_col] for n in node_order], dtype=np.int16
    )

    # ── Widen constraint epsilon to accommodate enacted VTD-level deviations ─
    # The enacted plan at VTD level may exceed the target epsilon (large VTDs
    # span multiple small legislative districts). We compute the actual max
    # deviation and widen the GerryChain validity constraint just enough to
    # accept it as the initial state. The PROPOSAL still targets the tight
    # epsilon, so chain draws stay within the intended population tolerance.
    dist_pop = _dd(int)
    for n in node_order:
        dist_pop[graph.nodes[n][district_col]] += graph.nodes[n].get(pop_column, 0)
    max_enacted_dev = max(abs(p - ideal_pop) / ideal_pop for p in dist_pop.values())
    constraint_eps  = max(epsilon, max_enacted_dev * 1.05)  # 5% slack above actual

    print(f"  {n_districts} districts | ideal pop {ideal_pop:,.0f}")
    print(f"  proposal ε={epsilon*100:.1f}%  |  "
          f"constraint ε={constraint_eps*100:.1f}%  "
          f"(enacted VTD max dev {max_enacted_dev*100:.1f}%)")

    initial = GeographicPartition(graph, district_col, updaters=updaters)

    # Cap bipartition attempts at 500 per pair attempt.
    # Default is 10000 — but BipartitionWarning fires at 1000, meaning the
    # chain can spin 1000–9999 times printing warnings without raising the
    # catchable RuntimeError. Capping at 500 makes failures come fast as
    # RuntimeErrors that _safe handles cleanly.
    # Only applies to recom; reversible_recom uses a different internals.
    fast_bipartition = partial(bipartition_tree, max_attempts=500)

    if algo == "reversible_recom":
        proposal = partial(
            reversible_recom,
            pop_col    = pop_column,
            pop_target = ideal_pop,
            epsilon    = epsilon,
        )
    else:
        proposal = partial(
            recom,
            pop_col      = pop_column,
            pop_target   = ideal_pop,
            epsilon      = epsilon,
            node_repeats = 2,
            method       = fast_bipartition,
        )

    chain = MarkovChain(
        proposal      = proposal,
        constraints   = [within_percent_of_ideal_population(initial, constraint_eps)],
        accept        = always_accept,
        initial_state = initial,
        total_steps   = n_steps,
    )

    n_usable    = max(n_steps - burn_in, 0)
    plan_matrix = np.zeros((n_usable, n_nodes), dtype=np.int16)
    draw_idx    = 0
    start       = time.time()

    _MAX_CONSECUTIVE_FAILURES = 5

    def _safe(c):
        """
        Iterate the chain, handling 'no possible cut' errors gracefully.

        A single failure means this proposal attempt failed — the GerryChain
        iterator is not broken; calling next() again will retry from the same
        state with a different random spanning tree. We skip and continue.

        If failures are consecutive (the chain is truly stuck in a topological
        dead-end), we stop after _MAX_CONSECUTIVE_FAILURES attempts.
        """
        it = iter(c)
        consecutive = 0
        while True:
            try:
                consecutive = 0
                yield next(it)
            except RuntimeError as e:
                if "Could not find a possible cut" in str(e):
                    consecutive += 1
                    if consecutive >= _MAX_CONSECUTIVE_FAILURES:
                        print(f"  WARNING: chain stuck for {consecutive} consecutive steps"
                              f" — stopping early with {draw_idx} draws")
                        return
                    # else: silently skip; retry from same partition state
                else:
                    raise
            except StopIteration:
                return

    print(f"  Running {n_steps:,} steps (burn_in={burn_in:,})…")
    for step, partition in enumerate(_safe(chain)):
        if step % 500 == 0:
            elapsed = time.time() - start
            rate    = (step + 1) / elapsed if elapsed > 0 else 0
            eta     = (n_steps - step) / rate if rate > 0 else 0
            print(f"    step {step:>6,}/{n_steps:,}  {rate:.1f} steps/s  ~{eta/60:.1f} min remaining")

        if step < burn_in:
            continue

        assignment = partition.assignment
        for node in node_order:
            plan_matrix[draw_idx, node_index[node]] = assignment[node]
        draw_idx += 1

    runtime = time.time() - start
    print(f"  Chain done: {draw_idx:,} draws in {runtime/60:.1f} min")

    # Prepend enacted plan as row 0; chain draws follow
    combined = np.vstack([enacted_row[np.newaxis, :], plan_matrix[:draw_idx]])
    return combined, node_order


# ---------------------------------------------------------------------------
# Save plan assignments parquet
# ---------------------------------------------------------------------------

def save_assignments(
    plan_matrix: np.ndarray,
    node_order: list,
    geoid_map: dict,
    run_name: str,
    chamber: str,
    state: str,
    geo_level: str,
    out_path: Path,
) -> None:
    """
    Write the assignment matrix in ALARM-compatible format.
    Schema: plan_id, draw, geoid, district, geo_level, state, chamber
    """
    n_draws, n_nodes = plan_matrix.shape
    print(f"  Saving {n_draws:,} draws × {n_nodes:,} VTDs → {out_path.name}")

    geoids = np.array([geoid_map.get(n, str(n)) for n in node_order])

    draws_col    = np.repeat(np.arange(1, n_draws + 1, dtype=np.int32), n_nodes)
    geoids_col   = np.tile(geoids, n_draws)
    district_col = plan_matrix.flatten().astype(np.int32)
    total_rows   = len(draws_col)

    table = pa.table({
        "plan_id":   pa.array([run_name]  * total_rows, type=pa.string()),
        "draw":      pa.array(draws_col,               type=pa.int32()),
        "geoid":     pa.array(geoids_col,              type=pa.string()),
        "district":  pa.array(district_col,            type=pa.int32()),
        "geo_level": pa.array([geo_level] * total_rows, type=pa.string()),
        "state":     pa.array([state]     * total_rows, type=pa.string()),
        "chamber":   pa.array([chamber]   * total_rows, type=pa.string()),
    })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, str(out_path), compression="zstd")
    size_mb = out_path.stat().st_size / 1_048_576
    print(f"  Written: {out_path.name}  ({size_mb:.1f} MB,  {total_rows:,} rows)")


# ---------------------------------------------------------------------------
# Modal dispatch helper
# ---------------------------------------------------------------------------

def _run_on_modal(
    run_name:   str,
    params:     dict,
    config_path: Path,
    async_mode: bool = False,
) -> None:
    """
    Dispatch a run to Modal.

    blocking   (async_mode=False): calls .remote() — waits until the run
               completes and prints the result summary.
    async mode (async_mode=True):  calls .spawn() — submits and returns
               immediately; status tracked via fdp.ensemble_runs in Supabase.

    Requires:
      - modal installed: pip install modal
      - authenticated:   modal setup
      - app deployed:    modal deploy modal_app.py
      - secrets created: see modal_app.py header for setup instructions
    """
    try:
        import modal
    except ImportError:
        print("ERROR: modal is not installed.")
        print("  Install it: pip install modal")
        print("  Then authenticate: modal setup")
        sys.exit(1)

    print(f"\nDispatching to Modal  ({'async' if async_mode else 'blocking'})…")
    print(f"  run_name   : {run_name}")
    print(f"  benchmark  : {params.get('benchmark_id')}")
    print(f"  chamber    : {params.get('chamber', {}).get('name')}")
    print(f"  steps      : {params.get('mcmc', {}).get('n_steps'):,}")
    print(f"  chains     : {params.get('mcmc', {}).get('n_chains')}")
    print()

    try:
        fn = modal.Function.from_name("fdga-chain", "run_ensemble_on_modal")
    except Exception as e:
        print("ERROR: Could not find Modal function 'run_ensemble_on_modal' in app 'fdga-chain'.")
        print("  Deploy it first: modal deploy modal_app.py")
        print(f"  Detail: {e}")
        sys.exit(1)

    if async_mode:
        call = fn.spawn(run_name, params)
        print(f"Run submitted to Modal (async).")
        print(f"  Call ID : {call.object_id}")
        print(f"\nTrack status:")
        print(f"  modal run modal_app.py::list_runs")
        print(f"  — or —")
        print(f"  SELECT status, n_draws, runtime_minutes")
        print(f"  FROM fdp.v_ensemble_runs WHERE run_name = '{run_name}';")
    else:
        print("Waiting for Modal run to complete…  (Ctrl-C to detach; run continues on Modal)\n")
        try:
            result = fn.remote(run_name, params)
            print(f"\nModal run complete:")
            print(f"  status          : {result.get('status')}")
            print(f"  draws           : {result.get('n_draws'):,}")
            print(f"  runtime         : {result.get('runtime_minutes')} min")
            print(f"  plans file      : {result.get('plans_file')}")
            print(f"  size            : {result.get('size_mb')} MB")
            print(f"\nNext step — score the plans:")
            print(f"  # Download plans from Modal volume first:")
            print(f"  modal volume get fdga-chain-data /ensemble/{run_name}_plans.parquet .")
            print(f"  # Then score:")
            print(f"  uv run python fdp/scripts/score_ensemble_plans.py \\")
            print(f"      --run-name {run_name} \\")
            print(f"      --config {config_path}")
        except KeyboardInterrupt:
            print("\nDetached from Modal run (it continues running in the background).")
            print(f"  Check status: modal run modal_app.py::list_runs")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a GerryChain ReCom ensemble benchmark.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Parameters not provided on the CLI default to the YAML config values.
Only --run-name is required.

Examples
--------
  # Quick 200-step test using the default congress config:
  uv run python scripts/run_ensemble.py \\
      --run-name congress_quick --n-steps 200

  # Full run, explicit config, reversible algorithm:
  uv run python scripts/run_ensemble.py \\
      --run-name congress_v1_rev \\
      --config ../fdp/configs/benchmarks/ga_congress_2026_v1.yml \\
      --algorithm reversible_recom

  # Dry run — print resolved config, no chain:
  uv run python scripts/run_ensemble.py --run-name debug --dry-run
""",
    )

    # Mandatory
    parser.add_argument(
        "--run-name", required=True,
        help="Unique run identifier.  Becomes plan_id in ensemble_scores and the catalog PK.",
    )

    # Config
    parser.add_argument("--config", default=None,
        help="Path to YAML benchmark config.  Defaults to the standard config for --chamber.")
    parser.add_argument("--chamber", choices=["congress", "senate", "house"], default=None,
        help="Chamber (used to find default config when --config is omitted).")

    # MCMC overrides
    parser.add_argument("--algorithm", choices=["recom", "reversible_recom"], default=None,
        help="recom (fast) or reversible_recom (statistically rigorous).")
    parser.add_argument("--n-steps",    type=int,   default=None, dest="n_steps",
        help="Total MCMC steps per chain (burn-in included).")
    parser.add_argument("--burn-in",    type=int,   default=None, dest="burn_in",
        help="Steps to discard at chain start.")
    parser.add_argument("--n-chains",   type=int,   default=None, dest="n_chains",
        help="Number of independent chains.")
    parser.add_argument("--pop-epsilon", type=float, default=None, dest="pop_epsilon",
        help="Population tolerance, e.g. 0.01 = ±1%%.")
    parser.add_argument("--random-seed", type=int,  default=None, dest="random_seed",
        help="Integer seed for reproducibility.  Omit for random.")

    # Geography / output overrides
    parser.add_argument("--graph-file",  default=None, dest="graph_file",
        help="Override geography.graph_file.")
    parser.add_argument("--output-dir",  default=None, dest="output_dir",
        help="Override output.dir.")

    # Behaviour flags
    parser.add_argument("--dry-run", action="store_true", default=False,
        help="Print resolved config and exit.  No chain, no catalog write.")
    parser.add_argument("--no-db", action="store_true", default=False,
        help="Skip Supabase catalog writes (local testing).")

    # Modal flags
    parser.add_argument("--modal", action="store_true", default=False,
        help=(
            "Run on Modal instead of locally.  Blocks until the run completes "
            "and prints a summary.  Requires 'modal' to be installed and authenticated."
        ))
    parser.add_argument("--modal-async", action="store_true", default=False,
        dest="modal_async",
        help=(
            "Fire-and-forget: submit to Modal and return immediately.  "
            "Check status via: modal run modal_app.py::list_runs  "
            "or query fdp.ensemble_runs in Supabase."
        ))

    args = parser.parse_args()

    # ── Load config ──────────────────────────────────────────────────────────
    BenchmarkConfig = _load_benchmark_config()

    if args.config:
        config_path = Path(args.config)
    elif args.chamber:
        config_path = DEFAULT_CONFIGS[args.chamber]
    else:
        config_path = DEFAULT_CONFIGS["congress"]
        print(f"INFO: no --config or --chamber given; using default: {config_path}")

    if not config_path.exists():
        print(f"ERROR: config not found: {config_path}")
        sys.exit(1)

    print(f"\nLoading config: {config_path}")
    cfg = BenchmarkConfig.from_yaml(config_path)

    # Apply non-None CLI overrides on top of YAML
    overrides = {k: v for k, v in {
        "algorithm":   args.algorithm,
        "n_steps":     args.n_steps,
        "burn_in":     args.burn_in,
        "n_chains":    args.n_chains,
        "pop_epsilon": args.pop_epsilon,
        "random_seed": args.random_seed,
        "graph_file":  args.graph_file,
        "output_dir":  args.output_dir,
    }.items() if v is not None}

    if overrides:
        print(f"  Overrides applied: {overrides}")
        cfg = cfg.apply_overrides(overrides)

    # ── Effective values ─────────────────────────────────────────────────────
    epsilon    = cfg.mcmc.effective_epsilon(cfg.chamber)
    graph_path = cfg.graph_path()
    out_dir    = cfg.output_dir()
    plans_path = out_dir / f"{args.run_name}_plans.parquet"
    meta_path  = out_dir / f"{args.run_name}_meta.json"
    params     = cfg.to_params_dict()
    params["run_name"] = args.run_name

    # ── Dry run ──────────────────────────────────────────────────────────────
    if args.dry_run:
        print("\n" + "=" * 68)
        print("DRY RUN — resolved config (nothing will execute)")
        print("=" * 68)
        print(cfg.summary())
        print(f"\n  run_name  : {args.run_name}")
        print(f"  config    : {config_path}")
        print(f"  graph     : {graph_path}")
        print(f"  algorithm : {cfg.mcmc.algorithm}")
        print(f"  steps     : {cfg.mcmc.n_steps:,}  burn_in={cfg.mcmc.burn_in:,}")
        print(f"  chains    : {cfg.mcmc.n_chains}")
        print(f"  epsilon   : ±{epsilon*100:.2f}%")
        print(f"  seed      : {cfg.mcmc.random_seed}")
        print(f"  elections : {[e.label for e in cfg.elections]}")
        print(f"  output    : {plans_path}")
        print("\nFull params:")
        print(json.dumps(params, indent=2, default=str))
        return

    # ── Modal path ────────────────────────────────────────────────────────────
    if args.modal or args.modal_async:
        _run_on_modal(args.run_name, params, config_path, async_mode=args.modal_async)
        return

    # ── Validate graph ────────────────────────────────────────────────────────
    if graph_path is None or not graph_path.exists():
        print(f"ERROR: graph not found: {graph_path}")
        print(f"  Build it: uv run python scripts/build_graph.py --chamber {cfg.chamber.name}")
        sys.exit(1)

    # ── Print header ──────────────────────────────────────────────────────────
    print("\n" + "=" * 68)
    print(f"ENSEMBLE RUN: {args.run_name}")
    print("=" * 68)
    print(f"  Chamber   : {cfg.chamber.name}  ({cfg.chamber.n_districts}D)")
    print(f"  Algorithm : {cfg.mcmc.algorithm}")
    print(f"  Steps     : {cfg.mcmc.n_steps:,}  burn_in={cfg.mcmc.burn_in:,}  chains={cfg.mcmc.n_chains}")
    print(f"  Epsilon   : ±{epsilon*100:.2f}%    seed: {cfg.mcmc.random_seed}")
    print(f"  Output    : {out_dir}")
    print()

    # ── Load graph ────────────────────────────────────────────────────────────
    print(f"Loading graph from {graph_path}…")
    graph   = Graph.from_json(str(graph_path))
    n_nodes = graph.number_of_nodes()
    print(f"  {n_nodes:,} nodes")

    # Build GEOID map
    sample_attrs = graph.nodes[next(iter(graph.nodes()))]
    geoid_attr   = next(
        (a for a in ["GEOID20", "GEOID", "geoid", "GEOID10"] if a in sample_attrs),
        None,
    )
    if geoid_attr:
        geoid_map = {n: str(graph.nodes[n][geoid_attr]) for n in graph.nodes()}
    else:
        print("  WARNING: no GEOID attribute in graph — using node IDs as geoids")
        geoid_map = {n: str(n) for n in graph.nodes()}

    # Resolve district column — priority order:
    #   1. YAML chamber.district_col (explicit, any state/chamber)
    #   2. Auto-detected from graph: any attribute matching *DIST* and chamber prefix
    #   3. Fallback defaults for backward-compat (GA-specific: CDIST/SDIST/HDIST)
    dist_col = cfg.chamber.effective_district_col()
    if dist_col not in sample_attrs:
        # Try to find any *DIST* attribute in the graph
        dist_candidates = [k for k in sample_attrs if "DIST" in k.upper()]
        chamber_prefix  = cfg.chamber.name[:1].upper()   # C, S, H, etc.
        # Prefer ones matching the chamber name prefix
        preferred = [k for k in dist_candidates if k.upper().startswith(chamber_prefix)]
        fallback  = preferred or dist_candidates
        if not fallback:
            print(f"ERROR: district column '{dist_col}' not found in graph.")
            print(f"  Graph attributes: {list(sample_attrs.keys())}")
            print(f"  Set chamber.district_col in your benchmark YAML to fix this.")
            sys.exit(1)
        dist_col = fallback[0]
        print(f"  Auto-detected district column: {dist_col}")

    # ── Catalog start ─────────────────────────────────────────────────────────
    if not args.no_db:
        catalog_write_start(args.run_name, cfg.benchmark_id, params)

    # ── Run chains ────────────────────────────────────────────────────────────
    all_matrices: list[np.ndarray] = []
    total_start = time.time()
    node_order_final: list = []

    try:
        for chain_idx in range(cfg.mcmc.n_chains):
            seed_i = (
                cfg.mcmc.random_seed + chain_idx
                if cfg.mcmc.random_seed is not None else None
            )
            if cfg.mcmc.n_chains > 1:
                print(f"\n── Chain {chain_idx + 1}/{cfg.mcmc.n_chains} ──")

            mat, node_order_final = run_chain(
                graph        = graph,
                pop_column   = cfg.chamber.pop_column,
                district_col = dist_col,
                n_steps      = cfg.mcmc.n_steps,
                burn_in      = cfg.mcmc.burn_in,
                epsilon      = epsilon,
                algo         = cfg.mcmc.algorithm,
                seed         = seed_i,
            )
            all_matrices.append(mat)

        combined    = np.concatenate(all_matrices, axis=0)
        total_draws = combined.shape[0]
        runtime     = time.time() - total_start
        print(f"\nAll chains complete: {total_draws:,} draws  in {runtime/60:.1f} min")

        # ── Save assignments ──────────────────────────────────────────────────
        save_assignments(
            plan_matrix = combined,
            node_order  = node_order_final,
            geoid_map   = geoid_map,
            run_name    = args.run_name,
            chamber     = cfg.chamber.name,
            state       = cfg.geography.state,
            geo_level   = cfg.geography.geo_level,
            out_path    = plans_path,
        )

        # ── Save meta JSON ────────────────────────────────────────────────────
        meta = {
            **params,
            "ran_at":          datetime.datetime.now().isoformat(timespec="seconds"),
            "runtime_seconds": round(runtime, 1),
            "n_draws":         total_draws,
            "n_vtds":          n_nodes,
            "n_chains_run":    cfg.mcmc.n_chains,
            "plans_file":      str(plans_path),
        }
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2, default=str)
        print(f"Metadata  : {meta_path}")

        # ── Summary ───────────────────────────────────────────────────────────
        print(f"\n{'='*68}")
        print(f"COMPLETE: {args.run_name}")
        print(f"  {total_draws:,} draws | {n_nodes:,} VTDs | {runtime/60:.1f} min")
        print(f"  Plans : {plans_path}")
        print(f"\nScore this run:")
        print(f"  uv run python fdp/scripts/score_ensemble_plans.py \\")
        print(f"      --run-name {args.run_name} \\")
        print(f"      --config {config_path}")
        print(f"{'='*68}")

        # ── Catalog end ───────────────────────────────────────────────────────
        if not args.no_db:
            catalog_write_end(
                args.run_name,
                status          = "completed",
                n_draws         = total_draws,
                n_vtds          = n_nodes,
                n_chains_run    = cfg.mcmc.n_chains,
                runtime_seconds = runtime,
                plans_file      = str(plans_path),
            )

    except Exception as exc:
        runtime = time.time() - total_start
        print(f"\nERROR after {runtime/60:.1f} min: {exc}")
        if not args.no_db:
            catalog_write_end(
                args.run_name,
                status          = "failed",
                runtime_seconds = runtime,
                error_message   = str(exc),
            )
        raise


if __name__ == "__main__":
    main()
