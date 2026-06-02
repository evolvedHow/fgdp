#!/usr/bin/env python3
"""
Re-melt 2022 election VTD parquet with the corrected regex (office code capped
at 3 chars) and upsert to Supabase, fixing the wrongly-parsed rows:

  G22SOSRRAF → was 'other_sosr' (rep, af) → now 'secretary-of-state' (rep, raf)
  G22INSDROB → was 'other_insd' (rep, ob) → now 'insurance-commissioner' (dem, rob)
  G22AGRLRAU → was 'other_agrl' (rep, au) → now 'agriculture-commissioner' (lib, rau)
  G22LTGLGRA → was 'other_ltgl' (grn, ra) → now 'lt-governor' (lib, gra)
"""
from __future__ import annotations
import io, os
import pandas as pd
import psycopg
from pathlib import Path
from fdp.transforms.pg_loaders import melt_election_vtd

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres.qcuveiiywbrmzguzducu:fdga-fdp-2016%21"
    "@aws-1-us-east-2.pooler.supabase.com:5432/postgres",
)
PARQUET = Path(__file__).parent.parent / "data/repos/main/vtd/ga-2022-general-election-vtd.parquet"

# ── Melt with fixed regex ────────────────────────────────────────────────────
print(f"Loading {PARQUET.name} …")
df22 = pd.read_parquet(PARQUET)
long22 = melt_election_vtd(
    df22, state="GA", source="RDH",
    geo_level="vtd", collection_geo_level="precinct",
    loaded_by="fix-regex-2022", log_fn=print,
)
print(f"\nFixed melt: {len(long22):,} rows")

# ── Upsert ───────────────────────────────────────────────────────────────────
PK = ["geoid", "year", "election_type", "office", "party", "candidate"]
update_cols = [c for c in long22.columns if c not in PK and
               c not in {"created_at", "updated_at", "update_count", "loaded_at"}]
col_names  = ", ".join(f'"{c}"' for c in long22.columns)
pk_str     = ", ".join(f'"{c}"' for c in PK)
update_str = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)

buf = io.StringIO()
long22.to_csv(buf, index=False, na_rep="\\N")
buf.seek(0)
buf.readline()   # discard header

with psycopg.connect(DB_URL, autocommit=True) as conn:
    with conn.cursor() as cur:
        cur.execute("SET SESSION default_transaction_read_only = off")
        cur.execute("BEGIN READ WRITE")
        cur.execute("CREATE TEMP TABLE _tmp_er (LIKE fdp.election_results INCLUDING DEFAULTS)")
        with cur.copy(f"COPY _tmp_er ({col_names}) FROM STDIN (FORMAT CSV, NULL '\\N')") as copy:
            copy.write(buf.read())
        cur.execute(
            f"INSERT INTO fdp.election_results ({col_names}) "
            f"SELECT {col_names} FROM _tmp_er "
            f"ON CONFLICT ({pk_str}) DO UPDATE SET {update_str}"
        )
        n = cur.rowcount
        cur.execute("COMMIT")
        print(f"Upserted {n:,} rows into fdp.election_results")

# ── Verify ───────────────────────────────────────────────────────────────────
print("\n2022 party coverage after fix:")
with psycopg.connect(DB_URL) as conn:
    rows = conn.execute("""
        SELECT office,
               STRING_AGG(DISTINCT party, ',' ORDER BY party) AS parties
        FROM fdp.election_results
        WHERE year = 2022 AND geo_level = 'vtd'
        GROUP BY office ORDER BY office
    """).fetchall()
    for office, parties in rows:
        has_dem = "dem" in parties
        has_rep = "rep" in parties
        flag = "✓" if (has_dem and has_rep) else "⚠ MISSING PARTY"
        print(f"  {office:<35} {parties:<20} {flag}")
