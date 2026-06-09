import json
with open('/home/vgana/codebox/fgdp/fdensemble/input_data/fdga_2026_benchmark_congress_scorecard.json') as f:
    d = json.load(f)
met = d.get('demographics',{}).get('metrics',{})
for key in ['maj_black','min_coal']:
    m = met.get(key,{})
    print(f'{key}: grade={m.get(\
