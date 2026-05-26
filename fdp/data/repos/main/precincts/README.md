# Precinct Data

Precinct shapefiles must be downloaded manually and placed here.

## Source: MGGG-States

Georgia precinct shapefile with 2020 Census + VEST election results:

```
https://github.com/mggg-states/GA-shapefiles
```

Expected files (place them in this directory):
```
ga_gen_20_congress_prec.shp   (and .dbf, .prj, .shx)
ga_gen_20_house_prec.shp
ga_gen_20_senate_prec.shp
```

## Alternative: Redistricting Data Hub

```
https://redistrictingdatahub.org/state/georgia/
→ Download: 2020 Georgia Precinct-Level Election Results
```

## Large Census block file (optional, ~3GB)

Only needed for GerryChain spatial joins:
```
https://www2.census.gov/geo/tiger/TIGER2020PL/STATE/13_GEORGIA/
→ Download: ga_pl2020_p3.shp (block-level race/VAP data)
```

Place as: `ga_pl2020_p3.shp` (and .dbf, .prj, .shx)

## Column normalisation

The `PrecinctLoader` automatically normalises column names across MGGG
release variants (e.g. `BVAP20` → `BVAP`, `G20PREDBID` → `DEM_VOTES`).
See `fdp/loaders/precincts.py` for the full alias map.
