#!/usr/bin/env bash
# =============================================================================
# stop.sh — stop the platform.
#
#   ./stop.sh            stops the cluster. Your data is kept, so ./start.sh
#                        brings it back quickly.
#   ./stop.sh --delete   removes the cluster entirely (a clean slate).
# =============================================================================
set -uo pipefail
cd "$(dirname "$0")"

NS=agent-platform
CLUSTER=agent-platform

if [ "${1:-}" = "--delete" ]; then
  ./scripts/teardown.sh
else
  docker stop "$CLUSTER-control-plane" "$CLUSTER-worker" "$CLUSTER-worker2" >/dev/null 2>&1 || true
  echo "Stopped. Your data is kept — ./start.sh brings it back quickly."
  echo "Use ./stop.sh --delete to remove the cluster entirely."
fi
