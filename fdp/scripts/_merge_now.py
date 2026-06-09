"""Run the chain merge for senate_450K_2601 — no CLI args needed."""
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq

RUN_NAME  = "senate_450K_2601"
N_CHAINS  = 5
DATA_DIR  = Path(__file__).resolve().parents[2] / "fdp/data/repos/main"
ENS_DIR   = DATA_DIR / "ensemble"
OUT_PATH  = ENS_DIR / f"{RUN_NAME}_plans.parquet"

chain_paths = [ENS_DIR / f"{RUN_NAME}_chain{i}_plans.parquet" for i in range(N_CHAINS)]

print(f"Merging {N_CHAINS} chains for '{RUN_NAME}'...")
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
    print(f"  {path.name}: {tbl.num_rows:,} rows, offset now {draw_offset}")

combined = pa.concat_tables(tables)
pq.write_table(combined, OUT_PATH, compression="zstd")
size_mb = OUT_PATH.stat().st_size / 1_048_576
print(f"Done: {OUT_PATH.name}  ({size_mb:.0f} MB), {combined.num_rows:,} rows, {draw_offset:,} draws")
