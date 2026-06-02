"""Apply a SQL migration file to Supabase via psycopg."""
import os, sys
import psycopg

DB_URL = os.environ.get("DATABASE_URL")
if not DB_URL:
    raise RuntimeError("DATABASE_URL not set")

sql_file = sys.argv[1] if len(sys.argv) > 1 else None
if not sql_file:
    print("Usage: python scripts/apply_migration.py fdp/sql/006_draw_stats.sql")
    sys.exit(1)

sql = open(sql_file).read()
print(f"Applying: {sql_file}")

with psycopg.connect(DB_URL) as conn:
    conn.execute("SET SESSION default_transaction_read_only = off")
    conn.execute("BEGIN READ WRITE")
    conn.execute(sql)
    conn.execute("COMMIT")

print("✓ Done")
