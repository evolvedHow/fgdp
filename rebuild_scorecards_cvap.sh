#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd /home/vgana/codebox/fgdp

LOGS=/tmp/fdga_rebuild2
mkdir -p "$LOGS"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

log "Rebuilding congress_alarm scorecard with CVAP fix..."
uv run --project fdp python fdp/scripts/build_alarm_scorecard.py \
  --chamber congress --out fdensemble/input_data/ \
  > "$LOGS/sc_alarm.log" 2>&1 &
PID_ALARM=$!

log "Rebuilding GerryChain scorecards (source/year cosmetic fix)..."
for run in congress senate senate_alarm; do
  uv run --project fdp python fdp/scripts/build_scorecard.py \
    --run-name "fdga_baseline_benchmarks_2601_${run}" \
    --out "fdensemble/input_data/fdga_baseline_benchmarks_2601_${run}_scorecard.json" \
    > "$LOGS/sc_${run}.log" 2>&1 &
done

wait
log "=== Done ==="
ls -lh /home/vgana/codebox/fgdp/fdensemble/input_data/*.json
