#!/usr/bin/env bash
# Rescore demographics (MAJORITY_THRESHOLD 0.50 fix) and rebuild all scorecards.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd /home/vgana/codebox/fgdp

LOGS=/tmp/fdga_rescore
ENS=fdp/data/repos/main/ensemble
mkdir -p "$LOGS"

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOGS/pipeline.log"; }

log "=== Phase 1: Rescore demographics (config-driven threshold) — all 4 runs in parallel ==="
declare -A CONFIG_MAP=(
  [congress]="fdp/configs/benchmarks/ga_congress_2026_v3.yml"
  [senate]="fdp/configs/benchmarks/ga_senate_2026.yml"
  [congress_alarm]="fdp/configs/benchmarks/ga_congress_2026_alarm.yml"
  [senate_alarm]="fdp/configs/benchmarks/ga_senate_2026_alarm.yml"
)
for run in congress senate congress_alarm senate_alarm; do
  cfg="${CONFIG_MAP[$run]:-}"
  config_arg=""
  [[ -f "$cfg" ]] && config_arg="--config $cfg"
  uv run --project fdp python fdp/scripts/score_ensemble_demographics.py \
    --run-name "fdga_baseline_benchmarks_2601_${run}" \
    --plans-file "$ENS/fdga_baseline_benchmarks_2601_${run}_plans.parquet" \
    $config_arg \
    > "$LOGS/demo_${run}.log" 2>&1 &
done
wait
log "Demographics done."

log "=== Phase 2: Rebuild all 4 scorecards in parallel ==="
uv run --project fdp python fdp/scripts/build_scorecard.py \
  --run-name fdga_baseline_benchmarks_2601_congress \
  --out fdensemble/input_data/fdga_baseline_benchmarks_2601_congress_scorecard.json \
  > "$LOGS/sc_congress.log" 2>&1 &

uv run --project fdp python fdp/scripts/build_scorecard.py \
  --run-name fdga_baseline_benchmarks_2601_senate \
  --out fdensemble/input_data/fdga_baseline_benchmarks_2601_senate_scorecard.json \
  > "$LOGS/sc_senate.log" 2>&1 &

uv run --project fdp python fdp/scripts/build_scorecard.py \
  --run-name fdga_baseline_benchmarks_2601_congress_alarm \
  --out fdensemble/input_data/fdga_baseline_benchmarks_2601_congress_alarm_scorecard.json \
  > "$LOGS/sc_congress_alarm.log" 2>&1 &

uv run --project fdp python fdp/scripts/build_scorecard.py \
  --run-name fdga_baseline_benchmarks_2601_senate_alarm \
  --out fdensemble/input_data/fdga_baseline_benchmarks_2601_senate_alarm_scorecard.json \
  > "$LOGS/sc_senate_alarm.log" 2>&1 &

wait
log "=== ALL DONE ==="
echo ""
ls -lh /home/vgana/codebox/fgdp/fdensemble/input_data/*.json
