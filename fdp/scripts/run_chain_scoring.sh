#!/usr/bin/env bash
# Score partisan plans + demographics for chains 1-4 of senate_450K_2601
set -e
cd ~/codebox/fgdp

RUN=senate_450K_2601

for chain in 1 2 3 4; do
    echo "=== Scoring chain${chain} plans ==="
    uv run --project fdp python -u fdp/scripts/score_ensemble_plans.py \
        --run-name "${RUN}_chain${chain}" \
        --plans-file "fdp/data/repos/main/ensemble/${RUN}_chain${chain}_plans.parquet"

    echo "=== Scoring chain${chain} demographics ==="
    uv run --project fdp python -u fdp/scripts/score_ensemble_demographics.py \
        --run-name "${RUN}_chain${chain}" \
        --plans-file "fdp/data/repos/main/ensemble/${RUN}_chain${chain}_plans.parquet"

    echo "=== chain${chain} complete ==="
done

echo "=== All chains scored ==="
