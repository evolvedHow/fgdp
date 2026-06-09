#!/usr/bin/env python3
"""
downsample_plans.py — Downsample a plans parquet to a target number of draws.

Keeps draw=1 (the enacted plan) and randomly samples (target - 1) additional draws.
Renumbers draws 1..target so draw=1 remains the enacted plan.

Usage:
    uv run --project fdp python fdp/scripts/downsample_plans.py \
        --input  fdp/data/repos/main/ensemble/senate_450K_2601_plans.parquet \
        --output fdp/data/repos/main/ensemble/senate_100K_2601_plans.parquet \
        --target 100000 \
        --seed   42
"""

import argparse
import random
import duckdb
import pyarrow.parquet as pq
import pyarrow as pa
from pathlib import Path


def downsample(input_path: Path, output_path: Path, target: int, seed: int) -> None:
    print(f"Downsampling {input_path.name} → {output_path.name}")
    print(f"  Target draws: {target:,}  (including draw=1 enacted)")

    con = duckdb.connect()

    # Get total draw count and column names
    meta = con.execute(
        f"SELECT COUNT(DISTINCT draw) AS n_draws FROM read_parquet('{input_path}')"
    ).fetchone()
    n_draws = meta[0]
    print(f"  Source draws: {n_draws:,}")

    if target >= n_draws:
        raise ValueError(f"Target {target} >= source {n_draws} — nothing to downsample.")

    # Sample draw IDs: always keep draw=1, sample the rest
    all_draws = con.execute(
        f"SELECT DISTINCT draw FROM read_parquet('{input_path}') WHERE draw != 1 ORDER BY draw"
    ).fetchall()
    all_draw_ids = [r[0] for r in all_draws]

    random.seed(seed)
    sampled = random.sample(all_draw_ids, target - 1)
    sampled.sort()
    selected = [1] + sampled   # draw=1 first, then sorted sample

    print(f"  Sampled {len(sampled):,} draws + draw=1 = {len(selected):,} total")

    # Write selected draws with renumbered draw IDs (1..target)
    # Build a mapping table in DuckDB
    mapping_rows = [(orig, new) for new, orig in enumerate(selected, start=1)]
    con.execute("CREATE TABLE draw_map (orig_draw INTEGER, new_draw INTEGER)")
    con.executemany("INSERT INTO draw_map VALUES (?, ?)", mapping_rows)

    cols = con.execute(
        f"SELECT column_name FROM information_schema.columns "
        f"WHERE table_name='plans' ORDER BY ordinal_position"
    )
    # Get actual columns from parquet
    schema = pq.read_schema(input_path)
    col_names = schema.names
    non_draw_cols = [c for c in col_names if c != 'draw']

    select_cols = ", ".join(
        [f"dm.new_draw AS draw"] + [f"p.{c}" for c in non_draw_cols]
    )

    print(f"  Writing {output_path.name} …")
    con.execute(f"""
        COPY (
            SELECT {select_cols}
            FROM read_parquet('{input_path}') p
            JOIN draw_map dm ON p.draw = dm.orig_draw
            ORDER BY dm.new_draw, p.geoid
        )
        TO '{output_path}'
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)
    """)
    # Note: plans parquet schema is (geoid TEXT, draw INT, district INT16)

    # Verify
    result = con.execute(
        f"SELECT COUNT(DISTINCT draw) AS n_draws, COUNT(*) AS n_rows "
        f"FROM read_parquet('{output_path}')"
    ).fetchone()
    print(f"  ✓ {result[1]:,} rows  ·  {result[0]:,} draws  →  {output_path}")
    print(f"  File size: {output_path.stat().st_size / 1e6:.1f} MB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input',  required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--target', type=int, default=100_000)
    ap.add_argument('--seed',   type=int, default=42)
    args = ap.parse_args()

    inp = Path(args.input)
    out = Path(args.output)
    if not inp.exists():
        raise FileNotFoundError(inp)
    out.parent.mkdir(parents=True, exist_ok=True)

    downsample(inp, out, args.target, args.seed)


if __name__ == '__main__':
    main()
