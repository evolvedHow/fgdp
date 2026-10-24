# Agent notes: FDP semantic layer + WrenAI NLQ

## Goal
Let WrenAI answer natural-language questions about Georgia redistricting and election data using a read-only semantic DuckDB (`fdp/data/semantic.duckdb`) built on top of `cdm.duckdb` and `manifest.duckdb`.

## Current state
- `sql/semantic/001_redistricting_views.sql` defines the full semantic views (7 models).
- `sql/semantic/002_compact_views.sql` defines compact views for small local LLMs.
- `sql/semantic/build.py` rebuilds `data/semantic.duckdb` from SQL + fdensemble Parquets.
- WrenAI project 8 is configured as DUCKDB with init SQL attaching `cdm`, `manifest`, and `semantic`.
- Election/CVAP views are deferred until source Parquet files exist.

## Known limitations
- The full 7-model schema produces prompts >20K tokens, which exceeds what a 1B-parameter local model can handle.
- For `gemma-3-1B-it` use the **compact views** and a small context window (see WrenAI setup below).
- For larger models (4B–7B+ with 32K context) the full views work.

## How to rebuild the semantic DB
```bash
cd /path/to/fgdp/fdp
uv run --with duckdb python sql/semantic/build.py
```
This regenerates `data/semantic.duckdb` from the SQL files and fdensemble Parquets.

## Local LLM / embedder server commands
Run from the host (not inside Docker) so WrenAI containers can reach them at `172.17.0.1`.

**LLM (gemma-3-1B-it)**
```bash
# For compact schema / small prompts
/root/llama.cpp/build/bin/llama-server \
  -m /root/models/gemma-3-1B-it-QAT-Q4_0.gguf \
  --host 0.0.0.0 --port 8080 -ngl 0 -c 4096 -np 1 -cb

# For full schema / large prompts (needs a faster machine)
/root/llama.cpp/build/bin/llama-server \
  -m /root/models/gemma-3-1B-it-QAT-Q4_0.gguf \
  --host 0.0.0.0 --port 8080 -ngl 0 -c 32768 -np 1 -cb
```

**Embedder (nomic-embed-text-v1.5)**
```bash
/root/llama.cpp/build/bin/llama-server \
  -m /root/models/nomic-embed-text-v1.5.Q4_K_M.gguf \
  --host 0.0.0.0 --port 8081 -ngl 0 --embedding --pooling mean \
  -c 2048 -np 1 -ub 2048
```

## WrenAI config summary
Config lives in `~/.wrenai/config.yaml` (not in this repo). Key settings:
- LLM: `openai/gemma` at `http://172.17.0.1:8080/v1`
- Embedder: `openai/nomic-embed-text-v1.5` at `http://172.17.0.1:8081/v1`
- Document store: Qdrant with `embedding_model_dim: 768` and `recreate_index: true`
- Qdrant image pinned to `v1.11.0` in `~/.wrenai/docker-compose.yaml`

See `wrenai/config.yaml.example` in this repo for the full file.

## Switching WrenAI to compact views
1. Rebuild `semantic.duckdb` (it already contains both view sets).
2. In the Wren UI for project 8, remove the full `v_*` models and add the `v_*_compact` models.
3. Recreate the same 3 relationships using the compact view names.
4. Keep descriptions short and focused.
5. Deploy.

## TODO
- [ ] Add county/muni reference views (`v_counties`, `v_municipalities`).
- [ ] Seed WrenAI `sql_pair` table with example SQL pairs.
- [ ] Build election/CVAP views once source Parquet files are available.
