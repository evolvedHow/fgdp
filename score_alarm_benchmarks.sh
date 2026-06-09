#!/usr/bin/env bash
# score_alarm_benchmarks.sh — Full scoring pipeline for ALARM congress + senate
#
# Run this from fgdp/ root AFTER downloading the plans parquets from Modal:
#
#   modal volume get fdga-chain-data \
#       /ensemble/fdga_baseline_benchmarks_2601_congress_alarm_plans.parquet \
#       fdp/data/repos/main/ensemble/
#
#   modal volume get fdga-chain-data \
#       /ensemble/fdga_baseline_benchmarks_2601_senate_alarm_plans.parquet \
#       fdp/data/repos/main/ensemble/
#
# Then:
#   bash score_alarm_benchmarks.sh
# or for a single chamber:
#   bash score_alarm_benchmarks.sh congress
#   bash score_alarm_benchmarks.sh senate
set -e
cd "$(dirname "$0")"

if [[ $# -eq 0 ]]; then
    CHAMBERS=(congress senate)
else
    CHAMBERS=("$@")
fi

DATA_DIR="fdp/data/repos/main"
ENSEMBLE_DIR="${DATA_DIR}/ensemble"

score_chamber() {
    local chamber="$1"
    local RUN

    case "$chamber" in
        congress) RUN="fdga_baseline_benchmarks_2601_congress_alarm" ;;
        senate)   RUN="fdga_baseline_benchmarks_2601_senate_alarm"   ;;
        *) echo "Unknown chamber: $chamber (use congress or senate)"; exit 1 ;;
    esac

    local PLANS="${ENSEMBLE_DIR}/${RUN}_plans.parquet"

    echo ""
    echo "======================================================="
    echo "  Scoring ${chamber} ALARM — ${RUN}"
    echo "======================================================="

    if [[ ! -f "$PLANS" ]]; then
        echo "ERROR: plans file not found: $PLANS"
        echo "  Download it first:"
        echo "    cd fdga-chain && modal volume get fdga-chain-data /ensemble/${RUN}_plans.parquet ../${PLANS}"
        exit 1
    fi

    echo ""
    echo "--- Step 1: Partisan scores ---"
    uv run --project fdp python -u fdp/scripts/score_ensemble_plans.py \
        --run-name "${RUN}" \
        --plans-file "${PLANS}" \
        --config "fdp/configs/benchmarks/ga_${chamber}_2026_alarm.yml"

    echo ""
    echo "--- Step 2: Draw stats ---"
    uv run --project fdp python -u fdp/scripts/build_draw_stats.py \
        --run-name "${RUN}" \
        --config "fdp/configs/benchmarks/ga_${chamber}_2026_alarm.yml"

    echo ""
    echo "--- Step 3: Demographics ---"
    uv run --project fdp python -u fdp/scripts/score_ensemble_demographics.py \
        --run-name "${RUN}" \
        --plans-file "${PLANS}"

    echo ""
    echo "--- Step 4: Scorecard ---"
    uv run --project fdp python -u fdp/scripts/build_scorecard.py \
        --run-name "${RUN}" \
        --chamber "${chamber}" \
        --source alarm

    local SCORECARD="${ENSEMBLE_DIR}/${RUN}_scorecard.json"
    if [[ -f "$SCORECARD" ]]; then
        echo ""
        echo "--- Step 5: Copy scorecard to fdensemble ---"
        cp -v "${SCORECARD}" "fdensemble/input_data/${RUN}_scorecard.json"
        echo ""
        echo "✓ ${chamber} ALARM scorecard ready: fdensemble/input_data/${RUN}_scorecard.json"
    else
        echo "ERROR: scorecard not found at ${SCORECARD}"
        exit 1
    fi
}

for chamber in "${CHAMBERS[@]}"; do
    score_chamber "$chamber"
done

echo ""
echo "======================================================="
echo "  All done! Scorecards deployed to fdensemble/input_data/"
echo "======================================================="
echo ""
echo "Next: build frontend and push to Railway"
echo "  cd fdensemble/frontend && npm run build"
echo "  cd ~/codebox/fgdp/fdensemble && git add -A && git commit -m '...'"
echo "  git push origin master"
