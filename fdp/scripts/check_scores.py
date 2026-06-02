"""Quick check of ensemble_scores distribution for congress_2026_v1."""
import os
import psycopg

DB_URL = os.environ.get("DATABASE_URL")
if not DB_URL:
    raise RuntimeError("DATABASE_URL not set")

with psycopg.connect(DB_URL, connect_timeout=30) as conn:
    rows = conn.execute("""
        SELECT year, office,
               COUNT(DISTINCT draw)                                        AS n_draws,
               MIN(dem_seats)                                              AS min_dem,
               MAX(dem_seats)                                              AS max_dem,
               ROUND(AVG(dem_seats::numeric), 2)                          AS avg_dem,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY dem_seats)     AS median_dem
        FROM (
            SELECT draw, year, office,
                   SUM(CASE WHEN winner = 'dem' THEN 1 ELSE 0 END) AS dem_seats
            FROM fdp.ensemble_scores
            WHERE plan_id = 'congress_2026_v1'
              AND draw > 1
            GROUP BY draw, year, office
        ) t
        GROUP BY year, office
        ORDER BY year, office
    """).fetchall()

print(f"{'Year':<6} {'Office':<12} {'Draws':>7} {'Min':>5} {'Max':>5} {'Avg':>6} {'Median':>7}")
print("-" * 55)
for r in rows:
    print(f"{r[0]:<6} {r[1]:<12} {r[2]:>7,} {r[3]:>5} {r[4]:>5} {r[5]:>6} {r[6]:>7}")

# Enacted plan (draw=1) — fresh connection
print("\nEnacted plan (draw=1):")
with psycopg.connect(DB_URL, connect_timeout=30) as conn:
 enacted = conn.execute("""
    SELECT year, office,
           SUM(CASE WHEN winner = 'dem' THEN 1 ELSE 0 END) AS dem_seats,
           SUM(CASE WHEN winner = 'rep' THEN 1 ELSE 0 END) AS rep_seats
    FROM fdp.ensemble_scores
    WHERE plan_id = 'congress_2026_v1' AND draw = 1
    GROUP BY year, office ORDER BY year, office
 """).fetchall()
for r in enacted:
    print(f"  {r[0]} {r[1]}: D{r[2]} / R{r[3]}")
