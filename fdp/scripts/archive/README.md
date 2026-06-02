# Archive — One-Time Fix Scripts

Scripts that were run exactly once to correct a specific data issue.
Not needed again, but kept for audit trail.

| Script | Why archived |
|---|---|
| `fix_2022_election_data.py` | One-time fix for a regex parsing bug (office code `>3 chars`) that caused 2022 SOS/INS/AGR races to be wrongly categorised in Supabase. The underlying bug is fixed in `race_registry.py` and `pg_loaders.py`. Data was corrected. Do not re-run. |
