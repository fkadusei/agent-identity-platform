#!/usr/bin/env bash
# =============================================================================
# start.sh — bring the platform up and print the URL. One command.
#
#   ./start.sh      first run builds everything (~10-15 min); after that it
#                   resumes the existing cluster in well under a minute.
#
#   BIND_ADDR=0.0.0.0 ./start.sh   publish the edge on every interface so another
#                                  machine can reach it (see docs/operator-guide.md,
#                                  "Reach it from another machine"). Default is
#                                  127.0.0.1, host-only.
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
# The browser reaches the platform over https, terminated at the ingress (S7b) —
# not by exposing the API itself. The port is the forward to the *controller*.
URL=https://localhost:8443
EDGE_CA=.edge/ca.crt
PIDFILE=.port-forward.pid
ADDRFILE=.port-forward.addr
# Which interface the port-forward binds: host-only by default, or 0.0.0.0 to
# publish it to the LAN for a second machine.
BIND_ADDR="${BIND_ADDR:-127.0.0.1}"
edge_up() { curl -sf --cacert "$EDGE_CA" "$URL/healthz" >/dev/null 2>&1; }

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

# The port-forward goes to the ingress controller, not the API: TLS is
# terminated there with the certificate we generated, so the browser speaks
# https the whole way from the host.
#
# Reuse a running forward only if it is bound to the address we want now.
# Otherwise replace it — and clear any other forward for this service (one
# started by hand has no pidfile), so exactly one is bound.
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null \
   && [ "$(cat "$ADDRFILE" 2>/dev/null || echo 127.0.0.1)" = "$BIND_ADDR" ]; then
  : # already running on the requested address
else
  if [ -f "$PIDFILE" ]; then
    kill "$(cat "$PIDFILE")" 2>/dev/null || true
    rm -f "$PIDFILE"
  fi
  pkill -f "port-forward.*svc/ingress-nginx-controller" 2>/dev/null || true
  sleep 1
  kubectl -n ingress-nginx port-forward --address "$BIND_ADDR" \
    svc/ingress-nginx-controller 8443:443 >/tmp/agent-platform-port-forward.log 2>&1 &
  echo $! > "$PIDFILE"
  echo "$BIND_ADDR" > "$ADDRFILE"
fi

# Wait until it actually answers. `edge_up` verifies the certificate against our
# CA — no -k, so a wrong or untrusted certificate fails here rather than in the
# browser.
for _ in $(seq 1 30); do
  edge_up && break
  sleep 1
done

echo
if edge_up; then
  printf '\033[1;32mReady → %s\033[0m\n' "$URL"
  printf '\033[2m    certificate signed by %s (trust it once to use a browser)\033[0m\n' \
    "$(pwd)/$EDGE_CA"
  if [ "$BIND_ADDR" != "127.0.0.1" ] && [ "$BIND_ADDR" != "localhost" ]; then
    printf '\033[2m    LAN: https://agent-platform.local:8443 — point agent-platform.local at this\n'
    printf '         host on the client, and trust %s there too\033[0m\n' "$(pwd)/$EDGE_CA"
  fi
else
  printf '\033[1;33mThe edge is not answering yet. Give it a moment, then run ./status.sh\033[0m\n'
fi
echo
echo "Sign in with:  alice / alice123  (support rep)"
echo "               manager / manager123  (approver)"
echo "               admin / admin123  (platform admin)"
echo "               grace / grace123  (second tenant)"
