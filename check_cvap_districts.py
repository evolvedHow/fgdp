import pandas as pd
import duckdb

conn = duckdb.connect()

plans_file = '/home/vgana/codebox/fgdp/fdp/data/repos/main/ensemble/GA-2026-100K-2601_plans.parquet'
cvap_file  = '/home/vgana/codebox/fgdp/fdp/data/repos/main/vtd/ga-2024-cvap-vtd.parquet'
bvap_file  = '/home/vgana/codebox/fgdp/fdp/data/repos/main/vtd/bvap_vtd.parquet'

# Get enacted district assignments (draw == 1)
enacted = conn.execute(f"""
    SELECT geoid, district
    FROM read_parquet('{plans_file}')
    WHERE draw = 1
""").df()

# Load CVAP and BVAP
cvap = pd.read_parquet(cvap_file)
bvap = pd.read_parquet(bvap_file)

# Merge to get CVAP/BVAP per VTD per district
df = enacted.merge(cvap, left_on='geoid', right_on='GEOID20', how='left')
df = df.merge(bvap, left_on='geoid', right_on='GEOID20', how='left')

# Aggregate by district
agg = df.groupby('district').agg(
    cvap_tot=('CVAP_TOT24', 'sum'),
    cvap_blk=('CVAP_BLK24', 'sum'),
    cvap_wht=('CVAP_WHT24', 'sum'),
    bvap_tot=('bvap_tot', 'sum'),
    bvap_blk=('bvap_blk', 'sum'),
    bvap_wht=('bvap_wht', 'sum'),
).reset_index()

agg['pct_blk_bvap'] = agg['bvap_blk'] / agg['bvap_tot']
agg['pct_blk_cvap'] = agg['cvap_blk'] / agg['cvap_tot']
agg['pct_wht_bvap'] = agg['bvap_wht'] / agg['bvap_tot']
agg['pct_wht_cvap'] = agg['cvap_wht'] / agg['cvap_tot']

agg = agg.sort_values('pct_blk_cvap', ascending=False)

print('Enacted congressional districts — BVAP vs CVAP comparison:')
print(f'{"CD":>4}  {"BVAP Blk":>10}  {"CVAP Blk":>10}  {"Δ":>7}  {"BVAP Wht":>10}  {"CVAP Wht":>10}')
print('-' * 65)
for _, r in agg.iterrows():
    delta = r.pct_blk_cvap - r.pct_blk_bvap
    marker = ' ← MAJORITY' if r.pct_blk_cvap >= 0.50 else (' ← near-maj' if r.pct_blk_cvap >= 0.45 else '')
    print(f'  {int(r.district):>2}  {r.pct_blk_bvap:>10.1%}  {r.pct_blk_cvap:>10.1%}  {delta:>+7.1%}  {r.pct_wht_bvap:>10.1%}  {r.pct_wht_cvap:>10.1%}{marker}')

print()
print('Summary:')
print(f'  Districts ≥50% Black BVAP: {(agg.pct_blk_bvap >= 0.50).sum()}')
print(f'  Districts ≥50% Black CVAP: {(agg.pct_blk_cvap >= 0.50).sum()}')
print()
print('Key finding: CVAP includes only citizens, so Hispanic non-citizen')
print('population drops out, making Black % higher in mixed districts.')
