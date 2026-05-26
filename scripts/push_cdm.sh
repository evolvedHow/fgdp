#!/usr/bin/env bash
# Push updated CDM data from FDP into each app's local data cache.
#
# Usage:
#   ./scripts/push_cdm.sh              # sync all apps
#   ./scripts/push_cdm.sh fdex         # sync one app
#   ./scripts/push_cdm.sh --dry-run    # preview without copying
#
# Pass-through flags (--dry-run, FDP_WORKSPACE=...) are forwarded to each
# app's sync_data.sh.

set -e
cd "$(dirname "$0")/.."
FGDP_ROOT="$(pwd)"

# ---------------------------------------------------------------------------
# App registry: name -> path to sync_data.sh
# ---------------------------------------------------------------------------
declare -A APPS=(
  [fdex]="fdex/scripts/sync_data.sh"
  [lrdb]="lrdb/scripts/sync_data.sh"
  [map-compare]="map-compare/scripts/sync_data.sh"
  [fdga-chain]="fdga-chain/scripts/sync_data.sh"
  [fdworkbench]="fdworkbench/scripts/sync_data.sh"
)

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
TARGET=""
PASSTHROUGH=()

for arg in "$@"; do
  if [[ -v APPS[$arg] ]]; then
    TARGET="$arg"
  else
    PASSTHROUGH+=("$arg")
  fi
done

if [[ -n "$TARGET" ]] && [[ ! -v APPS[$TARGET] ]]; then
  echo "Unknown app: $TARGET"
  echo "Valid apps: ${!APPS[*]}"
  exit 1
fi

# ---------------------------------------------------------------------------
# Sync function
# ---------------------------------------------------------------------------
sync_app() {
  local name="$1"
  local script="$FGDP_ROOT/${APPS[$name]}"

  echo ""
  echo "━━━  $name  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  if [[ ! -f "$script" ]]; then
    echo "  [skip] sync script not found: $script"
    return
  fi

  bash "$script" "${PASSTHROUGH[@]}"
}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if [[ -n "$TARGET" ]]; then
  sync_app "$TARGET"
else
  for name in "${!APPS[@]}"; do
    sync_app "$name"
  done
fi

echo ""
echo "Done."
