import pandas as pd

cvap = pd.read_parquet('/home/vgana/codebox/fgdp/fdp/data/repos/main/vtd/ga-2024-cvap-vtd.parquet')
bvap = pd.read_parquet('/home/vgana/codebox/fgdp/fdp/data/repos/main/vtd/bvap_vtd.parquet')

print('=== BVAP (2020 Census PL 94-171 — what GerryChain used) ===')
print(f'  Total VAP:       {bvap["bvap_tot"].sum():>10,}')
print(f'  Black VAP:       {bvap["bvap_blk"].sum():>10,}  ({bvap["bvap_blk"].sum()/bvap["bvap_tot"].sum()*100:.1f}%)')
print(f'  White VAP:       {bvap["bvap_wht"].sum():>10,}  ({bvap["bvap_wht"].sum()/bvap["bvap_tot"].sum()*100:.1f}%)')
print(f'  Hispanic VAP:    {bvap["bvap_hsp"].sum():>10,}  ({bvap["bvap_hsp"].sum()/bvap["bvap_tot"].sum()*100:.1f}%)')
print()
print('=== CVAP (2020-2024 ACS 5yr — citizenship-adjusted, NOT used yet) ===')
print(f'  Total CVAP:      {cvap["CVAP_TOT24"].sum():>10,}')
print(f'  Black CVAP:      {cvap["CVAP_BLK24"].sum():>10,}  ({cvap["CVAP_BLK24"].sum()/cvap["CVAP_TOT24"].sum()*100:.1f}%)')
print(f'  White CVAP:      {cvap["CVAP_WHT24"].sum():>10,}  ({cvap["CVAP_WHT24"].sum()/cvap["CVAP_TOT24"].sum()*100:.1f}%)')
print(f'  Hispanic CVAP:   {cvap["CVAP_HSP24"].sum():>10,}  ({cvap["CVAP_HSP24"].sum()/cvap["CVAP_TOT24"].sum()*100:.1f}%)')
print()

# Now check the 5 near-majority Black districts using CVAP instead of BVAP
# Need the plans parquet to know which VTDs are in each enacted district
import duckdb
conn = duckdb.connect()

demo_file = '/home/vgana/codebox/fgdp/fdp/data/repos/main/ensemble/GA-2026-100K-2601_demographics.parquet'
plans_file = '/home/vgana/codebox/fgdp/fdp/data/repos/main/ensemble/GA-2026-100K-2601_plans.parquet'

# Check if plans file has the enacted district assignments (draw==1)
print('=== Plans parquet structure ===')
sample = conn.execute(f"SELECT * FROM read_parquet('{plans_file}') LIMIT 3").df()
print(sample.to_string())
print()
draws = conn.execute(f"SELECT MIN(draw), MAX(draw), COUNT(DISTINCT draw) FROM read_parquet('{plans_file}')").df()
print('Draw range:', draws.to_string())
