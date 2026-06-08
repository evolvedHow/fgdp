#!/usr/bin/env python3
"""
merge_chain_plans.py — Merge per-chain parquet files into a single plans parquet.

Replicates the merge logic from modal_app.py's run_ensemble_on_modal() function.
Draws are renumbered sequentially across chains so each draw ID is globally unique.

Usage:
    uv run --project fdp python fdp/scripts/merge_chain_plans.py \
        --run-name senate_450K_2601 \
        [--n-chains 5] \
        [--data-dir fdp/data/repos/main]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def merge_chains(run_name: str, data_dir: Path, n_chains: int = 5) -> Path:
    ensemble_dir = data_dir / "ensemble"
    out_path = ensemble_dir / f"{run_name}_plans.parquet"

    chain_paths = [
        ensemble_dir / f"{run_name}_chain{i}_plans.parquet"
        for i in range(n_chains)
    ]

    missing = [p for p in chain_paths if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Missing chain files: {[str(p) for p in missing]}")

    print(f"Merging {n_chains} chains for '{run_name}'...")
    tables = []
    draw_offset = 0

    for path in chain_paths:
        tbl = pq.read_table(path)
        draws = tbl.column("draw").to_pylist()
        max_d = max(draws)
        new_draws = [d + draw_offset for d in draws]
        draw_offset += max_d
        tbl = tbl.set_column(
            tbl.schema.get_field_index("draw"),
            "draw",
            pa.array(new_draws, type=pa.int32()),
        )
        tables.append(tbl)
        n_rows = tbl.num_rows
        n_draws_this = len(set(tbl.column("draw").to_pylist()))
        print(f"  {path.name}: {n_rows:,} rows, {n_draws_this:,} draws (offset +{draw_offset - max_d})")

    combined = pa.concat_tables(tables)
    total_rows = combined.num_rows
    n_draws_total = draw_offset
    n_vtds = total_rows // n_draws_total if n_draws_total > 0 else 0

    pq.write_table(combined, out_path, compression="zstd")
    size_mb = out_path.stat().st_size / 1_048_576

    print(f"\nDone: {out_path.name}  ({size_mb:.1f} MB)")
    print(f"  Total rows: {total_rows:,}")
    print(f"  Total draws: {n_draws_total:,}")
    print(f"  VTDs per draw: {n_vtds:,}")
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--n-chains", type=int, default=5)
    ap.add_argument("--data-dir", default=None,
                    help="Data directory (default: fdp/data/repos/main relative to repo root)")
    args = ap.parse_args()

    if args.data_dir:
        data_dir = Path(args.data_dir)
    else:
        data_dir = Path(__file__).resolve().parents[2] / "fdp/data/repos/main"

    merge_chains(args.run_name, data_dir, args.n_chains)


if __name__ == "__main__":
    main()
