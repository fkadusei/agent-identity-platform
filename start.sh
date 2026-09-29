#!/usr/bin/env bash
# =============================================================================
# start.sh — bring the platform up and print the URL. One command.
#
#   ./start.sh      first run builds everything (~10-15 min); after that it
#                   resumes the existing cluster in well under a minute.
#
# The browser edge is a fixed host port, not a port-forward: cluster.yaml maps
# host 8443 to the ingress controller's NodePort (setup.sh pins it). So the URL
# keeps working with nothing to keep alive — a laptop sleep, a closed terminal or
# a dropped connection no longer takes the edge down. Nothing to restart.
#
# A cluster created before that mapping existed has to be recreated once:
#   ./stop.sh --delete && ./scripts/setup.sh
#
# Then open the URL it prints.
# =============================================================================
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/lib.sh"
cd "$(dirname "$0")"

NS=agent-platform
CLUSTER=agent-platform
# The browser reaches the platform over https, terminated at the ingress (S7b),
# on the host port kind maps to the controller (deploy/kind/cluster.yaml).
URL=https://localhost:8443
EDGE_CA=.edge/ca.crt
edge_up() { curl -sf --max-time 5 --cacert "$EDGE_CA" "$URL/healthz" >/dev/null 2>&1; }

# Clear a forward an older version of this script left running: it is no longer
# how the edge is reached, and it would sit on port 8443.
rm -f .port-forward.pid .port-forward.addr
pkill -f "port-forward.*svc/ingress-nginx-controller" 2>/dev/null || true

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
  kubectl -n ingress-nginx wait --for=condition=available deploy/ingress-nginx-controller \
    --timeout=120s >/dev/null 2>&1 || true
fi

if [ ! -f "$EDGE_CA" ]; then
  echo "The browser edge is not configured (no $EDGE_CA)."
  echo "Run ./scripts/setup.sh — it installs the ingress and generates the certificate."
  exit 1
fi

# Wait until the edge answers. `edge_up` verifies the certificate against our CA
# — no -k, so a wrong or untrusted certificate fails here rather than in the
# browser.
for _ in $(seq 1 60); do
  edge_up && break
  sleep 1
done

echo
if edge_up; then
  printf '\033[1;32mReady → %s\033[0m\n' "$URL"
  printf '\033[2m    certificate signed by %s (trust it once to use a browser)\033[0m\n' \
    "$(pwd)/$EDGE_CA"
else
  printf '\033[1;33mThe edge is not answering.\033[0m\n'
  printf '    If this cluster predates the host-port mapping, recreate it once:\n'
  printf '      ./stop.sh --delete && ./scripts/setup.sh\n'
fi
echo
echo "Sign in with:  alice / alice123  (support rep)"
echo "               manager / manager123  (approver)"
echo "               admin / admin123  (platform admin)"
echo "               grace / grace123  (second tenant)"
