# Archive — One-Time and Superseded Scripts

These scripts are kept for historical reference but are no longer part of the active pipeline.

| Script | Why archived |
|---|---|
| `migrate_data.py` | One-time migration of GeoJSON files from individual app directories into the fdp canonical repo. Already executed; not needed again. |
| `export_ensemble_plans.R` | One-time export of ALARM 2020 congressional ensemble (5,001 draws) from R RDS format to parquet. Data is now in Supabase. |
| `load_ensemble_plans.py` | One-time loader of ALARM plans parquet into `fdp.ensemble_plans` Supabase table. Data already loaded. |
| `fix_2022_election_data.py` | One-time fix for a regex parsing bug (office code `>3 chars`) that caused 2022 SOS/INS/AGR elections to be wrongly categorised. Bug is fixed in `race_registry.py` and `pg_loaders.py`. Data was corrected in Supabase. |
