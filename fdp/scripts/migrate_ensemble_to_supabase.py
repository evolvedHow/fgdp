#!/usr/bin/env python3
"""
Copy ensemble tables from the local fdga Postgres to Supabase.

Run after cdm_to_postgres.py has built the schema in Supabase.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import psycopg
from psycopg.types.json import Json

LOCAL_DSN = "host=localhost port=5432 dbname=fdga user=homelab password=homelab"


def _adapt_row(row: tuple) -> tuple:
    """Adapt Python dicts/lists to Postgres JSON/JSONB."""
    return tuple(Json(v) if isinstance(v, (dict, list)) else v for v in row)

TABLES = [
    "fdp.ensemble_runs",
    "fdp.ensemble_scores",
    "analytics.ensemble_demographic_scores",
]


def copy_table(src_cur: psycopg.Cursor, dst_cur: psycopg.Cursor, table: str) -> int:
    src_cur.execute(f'SELECT * FROM {table}')
    columns = [desc.name for desc in src_cur.description]
    rows = src_cur.fetchall()

    if not rows:
        print(f"  {table}: 0 rows")
        return 0

    # Truncate target so the load is idempotent
    dst_cur.execute(f"TRUNCATE TABLE {table} CASCADE")

    col_list = ", ".join(f'"{c}"' for c in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    insert_sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"
    dst_cur.executemany(insert_sql, [_adapt_row(r) for r in rows])
    print(f"  {table}: {len(rows):,} rows copied")
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--local-dsn", default=os.getenv("LOCAL_POSTGRES_DSN", LOCAL_DSN))
    ap.add_argument("--remote-dsn", required=True)
    args = ap.parse_args()

    print("Copying ensemble data to Supabase...")
    with psycopg.connect(args.local_dsn) as src_conn:
        src_conn.autocommit = True
        src_cur = src_conn.cursor()

        with psycopg.connect(args.remote_dsn) as dst_conn:
            dst_conn.autocommit = False
            dst_cur = dst_conn.cursor()

            total = 0
            for table in TABLES:
                total += copy_table(src_cur, dst_cur, table)

            print("\nRefreshing materialized views...")
            for mv in (
                "analytics.agg_sim_partisan_outcomes",
                "analytics.agg_sim_competitiveness",
                "analytics.agg_sim_minority_representation",
                "dashboard.mv_county_summary",
                "dashboard.mv_county_election_trends",
                "dashboard.mv_vtd_partisan_demographics",
            ):
                try:
                    dst_cur.execute(f"REFRESH MATERIALIZED VIEW {mv}")
                    print(f"  refreshed {mv}")
                except Exception as exc:
                    print(f"  warning: could not refresh {mv}: {exc}")

            dst_conn.commit()

    print(f"\nDone. Copied {total:,} rows.")


if __name__ == "__main__":
    main()
