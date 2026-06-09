#!/usr/bin/env bash
# Full data rebuild pipeline — runs after audit bug fixes.
# Phases:
#   1. Rebuild vtd_composite.parquet (6-election composite, no Dec-22 runoff)
#   2. Rescore demographics (CVAP) for all 4 runs in parallel
#   3. Rescore plans with new composite for GerryChain + senate-ALARM runs
#   4. Rebuild draw stats
#   5. Rebuild all 4 scorecards

set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd /home/vgana/codebox/fgdp

LOGS=/tmp/fdga_rebuild
ENS=fdp/data/repos/main/ensemble
mkdir -p "$LOGS"

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOGS/pipeline.log"; }

log "=== Phase 1: Rebuild vtd_composite.parquet (6-election, no Dec-22 runoff) ==="
uv run --project fdp python fdp/scripts/build_composite_score.py 2>&1 | tee "$LOGS/composite.log"
log "Composite rebuild done."

log "=== Phase 2: Rescore demographics (CVAP) — all 4 runs in parallel ==="
for run in congress senate congress_alarm senate_alarm; do
  uv run --project fdp python fdp/scripts/score_ensemble_demographics.py \
    --run-name "fdga_baseline_benchmarks_2601_${run}" \
    --plans-file "$ENS/fdga_baseline_benchmarks_2601_${run}_plans.parquet" \
    > "$LOGS/demo_${run}.log" 2>&1 &
done
wait
log "Demographics rescoring done."

log "=== Phase 3: Rescore plans (new composite) — congress, senate, senate_alarm in parallel ==="
# congress_alarm uses build_alarm_scorecard.py which recomputes from scratch; skip here
for run in congress senate senate_alarm; do
  uv run --project fdp python fdp/scripts/score_ensemble_plans.py \
    --run-name "fdga_baseline_benchmarks_2601_${run}" \
    --plans-file "$ENS/fdga_baseline_benchmarks_2601_${run}_plans.parquet" \
    > "$LOGS/score_${run}.log" 2>&1 &
done
wait
log "Plan rescoring done."

log "=== Phase 4: Rebuild draw stats — congress, senate, senate_alarm in parallel ==="
for run in congress senate senate_alarm; do
  uv run --project fdp python fdp/scripts/build_draw_stats.py \
    --run-name "fdga_baseline_benchmarks_2601_${run}" \
    --thresholds 0.035 0.05 \
    > "$LOGS/drawstats_${run}.log" 2>&1 &
done
wait
log "Draw stats done."

log "=== Phase 5: Rebuild scorecards — all 4 in parallel ==="
uv run --project fdp python fdp/scripts/build_scorecard.py \
  --run-name fdga_baseline_benchmarks_2601_congress \
  --out fdensemble/input_data/fdga_baseline_benchmarks_2601_congress_scorecard.json \
  > "$LOGS/sc_congress.log" 2>&1 &

uv run --project fdp python fdp/scripts/build_scorecard.py \
  --run-name fdga_baseline_benchmarks_2601_senate \
  --out fdensemble/input_data/fdga_baseline_benchmarks_2601_senate_scorecard.json \
  > "$LOGS/sc_senate.log" 2>&1 &

uv run --project fdp python fdp/scripts/build_alarm_scorecard.py \
  --chamber congress \
  --out fdensemble/input_data/ \
  > "$LOGS/sc_congress_alarm.log" 2>&1 &

uv run --project fdp python fdp/scripts/build_scorecard.py \
  --run-name fdga_baseline_benchmarks_2601_senate_alarm \
  --out fdensemble/input_data/fdga_baseline_benchmarks_2601_senate_alarm_scorecard.json \
  > "$LOGS/sc_senate_alarm.log" 2>&1 &

wait
log "=== ALL PHASES COMPLETE ==="
echo ""
echo "Scorecard outputs:"
ls -lh /home/vgana/codebox/fgdp/fdensemble/input_data/*.json
