#!/usr/bin/env bash
# =============================================================================
# start.sh — bring the platform up and print the URL. One command.
#
#   ./start.sh      first run builds everything (~10-15 min); after that it
#                   resumes the existing cluster in well under a minute.
#
# Then open the URL it prints. Ctrl-C is safe; the port-forward keeps running in
# the background (./stop.sh stops it).
# =============================================================================
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/lib.sh"
cd "$(dirname "$0")"

NS=agent-platform
CLUSTER=agent-platform
URL=http://localhost:8080
PIDFILE=.port-forward.pid

if ! kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  echo "First run: building the cluster and the platform — about 10-15 minutes…"
  ./scripts/setup.sh
else
  # The cluster exists but may be stopped (e.g. after a Docker restart).
  if ! kubectl get nodes >/dev/null 2>&1; then
    echo "Starting the existing cluster…"
    docker start "$CLUSTER-control-plane" "$CLUSTER-worker" "$CLUSTER-worker2" >/dev/null 2>&1 || true
    for _ in $(seq 1 90); do
      kubectl get nodes >/dev/null 2>&1 && break
      sleep 2
    done
  fi

  echo "Waiting for the services to be ready…"
  kubectl -n "$NS" wait --for=condition=available deploy --all --timeout=300s >/dev/null 2>&1 || true
fi

# The UI/API port-forward (background, so the browser can reach it).
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  : # already running
else
  kubectl -n "$NS" port-forward svc/api 8080:8080 >/tmp/agent-platform-port-forward.log 2>&1 &
  echo $! > "$PIDFILE"
fi

# Wait until it actually answers.
for _ in $(seq 1 30); do
  curl -sf "$URL/healthz" >/dev/null 2>&1 && break
  sleep 1
done

echo
if curl -sf "$URL/healthz" >/dev/null 2>&1; then
  printf '\033[1;32mReady → %s\033[0m\n' "$URL"
else
  printf '\033[1;33mThe API is not answering yet. Give it a moment, then run ./status.sh\033[0m\n'
fi
echo
echo "Sign in with:  alice / alice123  (support rep)"
echo "               manager / manager123  (approver)"
echo "               admin / admin123  (platform admin)"
echo "               grace / grace123  (second tenant)"
