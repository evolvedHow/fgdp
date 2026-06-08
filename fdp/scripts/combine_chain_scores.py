#!/usr/bin/env python3
"""
combine_chain_scores.py — Merge per-chain scores parquets into a single file
with globally unique draw numbers that match the combined plans parquet.

Draw renumbering (matches orchestrator merge logic):
  chain0: offset = 0             (draws 1 → 1..90001)
  chain1: offset = max(chain0)   (draws 1 → 90002..180002)
  chain2: offset = max(chain1)+1 (etc.)
  ...

Usage (from fgdp/ root):
    uv run --project fdp python fdp/scripts/combine_chain_scores.py \\
        --run-name senate_450K_2601 \\
        --n-chains 5
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

_SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = _SCRIPT_DIR.parent / "data/repos/main"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-name", required=True,
                    help="Base run name (e.g. senate_450K_2601)")
    ap.add_argument("--n-chains", type=int, default=5,
                    help="Number of chains (default: 5)")
    ap.add_argument("--data-dir", default=None,
                    help=f"Root data directory (default: {DEFAULT_DATA_DIR})")
    ap.add_argument("--out-file", default=None,
                    help="Output path (default: {data_dir}/ensemble/{run_name}_scores.parquet)")
    args = ap.parse_args()

    data_dir = Path(args.data_dir) if args.data_dir else DEFAULT_DATA_DIR
    ensemble_dir = data_dir / "ensemble"

    out_file = (Path(args.out_file).resolve() if args.out_file
                else ensemble_dir / f"{args.run_name}_scores.parquet")

    draw_offset  = 0
    total_rows   = 0
    writer       = None
    draw_min_out = None
    draw_max_out = None

    out_file.parent.mkdir(parents=True, exist_ok=True)

    for i in range(args.n_chains):
        chain_file = ensemble_dir / f"{args.run_name}_chain{i}_scores.parquet"
        if not chain_file.exists():
            print(f"ERROR: missing {chain_file.name}")
            import sys; sys.exit(1)

        print(f"Loading chain{i} scores from {chain_file.name}…")
        df = pd.read_parquet(chain_file)

        max_draw = int(df["draw"].max())
        print(f"  {len(df):,} rows, draws {df['draw'].min()}-{max_draw}, "
              f"applying offset +{draw_offset}")

        if draw_offset > 0:
            df["draw"] = df["draw"] + draw_offset
        df["plan_id"] = args.run_name

        tbl = pa.Table.from_pandas(df, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(out_file, tbl.schema)
        writer.write_table(tbl)

        new_min = int(df["draw"].min())
        new_max = int(df["draw"].max())
        if draw_min_out is None or new_min < draw_min_out:
            draw_min_out = new_min
        if draw_max_out is None or new_max > draw_max_out:
            draw_max_out = new_max

        total_rows  += len(df)
        draw_offset += max_draw

    if writer:
        writer.close()

    size_mb = out_file.stat().st_size / 1_000_000
    print(f"\n✓ {total_rows:,} rows → {out_file.name}  ({size_mb:.1f} MB)")
    print(f"  draw range: {draw_min_out}–{draw_max_out}")
    print(f"  unique chains: {args.n_chains}")


if __name__ == "__main__":
    main()
