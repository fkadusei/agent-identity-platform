#!/bin/bash
# =============================================================================
# setup.sh — kind cluster -> SPIRE -> Keycloak -> OPA -> API/tools/agent,
# with a verification gate after each identity-critical step.
# Usage: ./scripts/setup.sh        (teardown: ./scripts/teardown.sh)
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

say()  { printf "\n\033[1;34m== %s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m   ✓ %s\033[0m\n" "$*"; }
info() { printf "\033[2m   · %s\033[0m\n" "$*"; }
die()  { printf "\033[1;31m   ✗ %s\033[0m\n" "$*" >&2; exit 1; }

NS=agent-platform
SPIFFE_ID="spiffe://acme.com/ns/agent-platform/sa/agent"
MANIFESTS=deploy/kind/manifests

say "0. prerequisites"
for bin in kind kubectl docker; do
  command -v "$bin" >/dev/null || die "$bin not found (kind: brew install kind)"
done
docker info >/dev/null 2>&1 || die "docker daemon not running"
ok "kind, kubectl, docker present"

say "1. kind cluster"
kind get clusters 2>/dev/null | grep -qx agent-platform || \
  kind create cluster --config deploy/kind/cluster.yaml
kubectl cluster-info --context kind-agent-platform >/dev/null
ok "cluster agent-platform"

say "2. build + load images"
# SPIRE server + agent are custom builds (jti plugin; no JWT-SVID cache) —
# see docker/spire-*.Dockerfile and spire-plugin/.
docker build -q -f docker/spire-server.Dockerfile -t agent-platform/spire-server-jti:demo . >/dev/null
docker build -q -f docker/spire-agent.Dockerfile  -t agent-platform/spire-agent-nocache:demo . >/dev/null
ok "spire-server-jti, spire-agent-nocache"
for svc in api tools agent gateway; do
  docker build -q -f "docker/$svc.Dockerfile" -t "agent-platform/$svc:demo" . >/dev/null
  kind load docker-image "agent-platform/$svc:demo" --name agent-platform >/dev/null
  ok "agent-platform/$svc:demo"
done
kind load docker-image agent-platform/spire-server-jti:demo --name agent-platform >/dev/null
kind load docker-image agent-platform/spire-agent-nocache:demo --name agent-platform >/dev/null

say "3. namespace + SPIRE"
kubectl apply -f "$MANIFESTS/namespace.yaml" >/dev/null
kubectl apply -f "$MANIFESTS/spire/" >/dev/null
kubectl -n $NS rollout status statefulset/spire-server --timeout=240s >/dev/null
kubectl -n $NS rollout restart daemonset/spire-agent >/dev/null
kubectl -n $NS rollout status daemonset/spire-agent --timeout=180s >/dev/null
ok "spire-server + spire-agent ready"

SOCKET=/run/spire/server/private/api.sock
SPIRE="kubectl -n $NS exec spire-server-0 -- /opt/spire/bin/spire-server"
PARENT_ID=""
for _ in $(seq 1 12); do
  PARENT_ID=$($SPIRE agent list -socketPath "$SOCKET" 2>/dev/null | awk '/SPIFFE ID/{print $NF; exit}')
  [ -n "$PARENT_ID" ] && break
  sleep 5
done
[ -n "$PARENT_ID" ] || die "no attested SPIRE agent found"

# One registration entry per workload identity. The gateway has its own SPIFFE
# ID so the agent can verify it over mTLS (and vice versa).
ensure_entry() { # ensure_entry <service-account> <spiffe-id>
  local sa="$1" id="$2" existing entry
  existing=$($SPIRE entry show -socketPath "$SOCKET" -spiffeID "$id" 2>/dev/null \
    | awk '/Parent ID/{print $NF; exit}')
  if [ "$existing" != "$PARENT_ID" ]; then
    if [ -n "$existing" ]; then
      entry=$($SPIRE entry show -socketPath "$SOCKET" -spiffeID "$id" 2>/dev/null \
        | awk '/Entry ID/{print $NF; exit}')
      $SPIRE entry delete -socketPath "$SOCKET" -entryID "$entry" >/dev/null
    fi
    $SPIRE entry create -socketPath "$SOCKET" \
      -spiffeID "$id" -parentID "$PARENT_ID" \
      -selector "k8s:ns:$NS" -selector "k8s:sa:$sa" >/dev/null
  fi
  ok "registration entry: $id (k8s:sa=$sa)"
}

ensure_entry agent "$SPIFFE_ID"
ensure_entry gateway "spiffe://acme.com/ns/agent-platform/sa/gateway"

say "4. Keycloak"
kubectl -n $NS create configmap keycloak-realm \
  --from-file=realm.json="$MANIFESTS/keycloak/realm.json" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl apply -f "$MANIFESTS/keycloak/keycloak.yaml" >/dev/null
kubectl -n $NS rollout status deploy/keycloak --timeout=300s >/dev/null
ok "keycloak ready (realm agent-platform imported)"

say "5. OPA"
kubectl -n $NS create configmap opa-policy \
  --from-file=policy.rego=policy/authz.rego \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl apply -f "$MANIFESTS/opa/" >/dev/null
kubectl -n $NS rollout status deploy/opa --timeout=120s >/dev/null
ok "opa serving the allow/deny/require-approval policy"

say "6. platform services"
kubectl apply -f "$MANIFESTS/apps/" >/dev/null
kubectl -n $NS rollout restart deploy/api deploy/tools deploy/agent >/dev/null
kubectl -n $NS rollout status deploy/api deploy/tools deploy/agent --timeout=240s >/dev/null
ok "api, tools, agent ready"

say "7. GATE: the agent pod can fetch its SVID (no secrets involved)"
OUT=""
for _ in $(seq 1 12); do
  OUT=$(kubectl -n $NS exec deploy/agent -- python -c "
from agentnhi.identity import fetch_jwt_svid
print(fetch_jwt_svid('unix:///run/spire/sockets/agent.sock', 'smoke-test'))" 2>/dev/null) || OUT=""
  [ -n "$OUT" ] && break
  sleep 5
done
[ -n "$OUT" ] || die "agent could not fetch its SVID"
ok "agent holds a JWT-SVID issued to $SPIFFE_ID"

say "SETUP COMPLETE"
echo "Next: ./scripts/demo.sh        # the happy path + approval flow"
echo "      ./scripts/attack-tests.sh # watch the attacks fail"
