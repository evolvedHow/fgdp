import duckdb

demo_file = '/home/vgana/codebox/fgdp/fdp/data/repos/main/ensemble/GA-2026-100K-2601_demographics.parquet'
conn = duckdb.connect()

# Check draw==1 (the "enacted" row)
print('=== Draw 1 (treated as enacted) ===')
df1 = conn.execute("""
    SELECT draw, district, pct_black, pct_white, pct_minority_coalition, cvap_total
    FROM read_parquet(?)
    WHERE draw = 1
    ORDER BY district
""", [demo_file]).df()
print(df1.to_string())

print()
print('=== Draw 0 (if exists) ===')
df0 = conn.execute("""
    SELECT draw, district, pct_black, pct_white, pct_minority_coalition, cvap_total
    FROM read_parquet(?)
    WHERE draw = 0
    ORDER BY district
""", [demo_file]).df()
print(df0.to_string())

print()
print('=== District-level: draws 1-3 pct_black ===')
df_sample = conn.execute("""
    SELECT draw, district, ROUND(pct_black, 3) as pct_black, ROUND(pct_white, 3) as pct_white
    FROM read_parquet(?)
    WHERE draw IN (1, 2, 3)
    ORDER BY draw, district
""", [demo_file]).df()
print(df_sample.to_string())

print()
print('=== For draw==1, which districts have the highest pct_black? ===')
df_top = conn.execute("""
    SELECT district, ROUND(pct_black,3) as pct_black, ROUND(pct_white,3) as pct_white,
           ROUND(pct_minority_coalition,3) as pct_min, cvap_total
    FROM read_parquet(?)
    WHERE draw = 1
    ORDER BY pct_black DESC
""", [demo_file]).df()
print(df_top.to_string())

print()
print('=== Distinct draw values range ===')
df_range = conn.execute("""
    SELECT MIN(draw) as min_draw, MAX(draw) as max_draw, COUNT(DISTINCT draw) as n_draws
    FROM read_parquet(?)
""", [demo_file]).df()
print(df_range.to_string())
