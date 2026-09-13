#!/usr/bin/env bash
# =============================================================================
# stop.sh — stop the platform.
#
#   ./stop.sh            stops the port-forward and the cluster. Your data is
#                        kept, so ./start.sh brings it back quickly.
#   ./stop.sh --delete   removes the cluster entirely (a clean slate).
# =============================================================================
set -uo pipefail
cd "$(dirname "$0")"

NS=agent-platform
CLUSTER=agent-platform

if [ -f .port-forward.pid ]; then
  kill "$(cat .port-forward.pid)" 2>/dev/null || true
  rm -f .port-forward.pid
fi
pkill -f "port-forward svc/api" 2>/dev/null || true

if [ "${1:-}" = "--delete" ]; then
  ./scripts/teardown.sh
else
  docker stop "$CLUSTER-control-plane" "$CLUSTER-worker" "$CLUSTER-worker2" >/dev/null 2>&1 || true
  echo "Stopped. Your data is kept — ./start.sh brings it back quickly."
  echo "Use ./stop.sh --delete to remove the cluster entirely."
fi
