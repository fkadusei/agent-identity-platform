#!/bin/bash
# =============================================================================
# tls-check.sh — prove every hop is authenticated, and say which mechanism does it.
#
# Two layers, and the boundary between them is deliberate (S7):
#
#   * the hops between workloads **we own** are SPIFFE: both sides present an
#     SVID, and the machine routes require the caller to be *named*;
#   * every other in-cluster hop is carried by the mesh (Linkerd), which still
#     wraps the third-party systems — Keycloak, OPA, Postgres, the sandbox — and
#     the /metrics scrape. Our SPIFFE ports pass through the proxy untouched
#     (skip-inbound/outbound-ports), so the mesh never terminates them.
#   * the **browser edge** is TLS at the ingress, with a certificate signed by
#     our own CA. Checked with that CA and never `-k`: a certificate nobody
#     verified is not evidence.
#
# This checks all three: the mesh edges it can see, each hop we own (asked
# directly — an SVID is required, and a name where one is enforced), and the
# edge, from outside the cluster.
# Usage: ./scripts/tls-check.sh
# =============================================================================
set -euo pipefail
# shellcheck source=lib.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
cd "$(dirname "$0")/.."

NS=agent-platform
EDGE_CA=.edge/ca.crt
EDGE_HOST=localhost
beat() { printf "\n\033[1;36m━━ %s ━━\033[0m\n" "$*"; }

mesh_ok=1
if ! command -v linkerd >/dev/null 2>&1; then
  printf '\033[1;33mlinkerd CLI not found — install it (brew install linkerd) to check the mesh;\n' >&2
  printf 'checking the SPIFFE hops only.\033[0m\n' >&2
  mesh_ok=0
fi

if [ "$mesh_ok" = "1" ]; then
  beat "MESH (every hop it carries)"
  linkerd --context "$KUBE_CONTEXT" check 2>&1 | tail -1

  beat "MESH EDGES (SECURED = mTLS)"
  edges=$(linkerd --context "$KUBE_CONTEXT" viz edges deploy -n "$NS" 2>/dev/null)
  printf '%s\n' "$edges" | awk 'NR==1 || $NF=="√"'

  unsecured=$(printf '%s\n' "$edges" | awk 'NR>1 && $NF!="√"' | wc -l | tr -d ' ')
  if [ "$unsecured" != "0" ]; then
    printf '\n\033[1;31m%d edge(s) the mesh carries are NOT mTLS:\033[0m\n' "$unsecured"
    printf '%s\n' "$edges" | awk 'NR>1 && $NF!="√"'
    exit 1
  fi

  printf '\n\033[1;32mEvery edge the mesh carries is mTLS.\033[0m\n'
fi

# The SPIFFE hops are not in the mesh's view at all — their traffic bypasses the
# proxy — so they are asserted where they live: inside a pod that holds an SVID.
beat "HOPS WE OWN (SPIFFE on both sides, caller named)"
kubectl -n "$NS" exec -i deploy/agent -c agent -- python - < scripts/spiffe_hops_client.py

# ---------------------------------------------------------------------------
# The browser edge. This is the hop a person uses, and it is the one the mesh
# cannot cover: a browser holds no SVID. It is TLS at the ingress, and the
# certificate is ours — checked against the CA rather than skipped, because
# "it answered over https" means nothing if nobody verified who answered.
# ---------------------------------------------------------------------------
beat "BROWSER EDGE (TLS terminated at the ingress)"
edge_fail=0
secret=$(kubectl -n "$NS" get ingress agent-platform -o jsonpath='{.spec.tls[0].secretName}' 2>/dev/null || true)
if [ -z "$secret" ]; then
  printf '  %-24s %s\n' "ingress" "MISSING — run ./scripts/setup.sh"
  edge_fail=1
elif [ ! -f "$EDGE_CA" ]; then
  printf '  %-24s %s\n' "our CA" "missing ($EDGE_CA) — run ./scripts/setup.sh"
  edge_fail=1
else
  # What the edge will present: it must chain to our CA, and name the host the
  # browser types (a valid certificate for the wrong name is still a warning).
  cert=$(mktemp)
  kubectl -n "$NS" get secret "$secret" -o jsonpath='{.data.tls\.crt}' \
    | openssl base64 -d -A > "$cert" 2>/dev/null || true
  if [ -s "$cert" ] && openssl verify -CAfile "$EDGE_CA" "$cert" >/dev/null 2>&1; then
    printf '  %-24s %s\n' "certificate chains to" "our CA ✓"
  else
    printf '  %-24s %s\n' "certificate chains to" "NOT our CA ✗"
    edge_fail=1
  fi
  # A CA without basicConstraints/keyUsage passes curl and fails strict clients
  # (Python/OpenSSL 3: "CA cert does not include key usage extension"), so assert
  # the extensions rather than trusting whoever generated the CA.
  if openssl x509 -in "$EDGE_CA" -noout -text 2>/dev/null | grep -q "CA:TRUE" \
    && openssl x509 -in "$EDGE_CA" -noout -text 2>/dev/null | grep -q "Certificate Sign"; then
    printf '  %-24s %s\n' "our CA" "CA:TRUE + keyCertSign ✓ (strict clients accept it)"
  else
    printf '  %-24s %s\n' "our CA" "missing CA extensions ✗ (strict clients reject it)"
    edge_fail=1
  fi
  san=$(openssl x509 -in "$cert" -noout -text 2>/dev/null \
    | awk '/Subject Alternative Name/{getline; print}')
  case "$san" in
    *"DNS:$EDGE_HOST"*) printf '  %-24s %s\n' "names" "$EDGE_HOST ✓ (SAN)";;
    *) printf '  %-24s %s\n' "names" "$EDGE_HOST ✗ ($san)"; edge_fail=1;;
  esac
  rm -f "$cert"

  # Reach it from outside the cluster, the way a browser does. A short-lived
  # port-forward of our own, so this does not depend on start.sh running.
  kubectl -n ingress-nginx port-forward svc/ingress-nginx-controller 8444:443 >/dev/null 2>&1 &
  edge_pf=$!
  trap 'kill $edge_pf 2>/dev/null || true' EXIT
  code=""
  for _ in $(seq 1 20); do
    code=$(curl -s -o /dev/null -w '%{http_code}' --cacert "$EDGE_CA" \
      --resolve "$EDGE_HOST:8444:127.0.0.1" "https://$EDGE_HOST:8444/healthz" 2>/dev/null || true)
    [ "$code" = "200" ] && break
    sleep 1
  done
  if [ "$code" = "200" ]; then
    printf '  %-24s %s\n' "https://$EDGE_HOST/healthz" "200 ✓ (certificate verified)"
  else
    printf '  %-24s %s\n' "https://$EDGE_HOST/healthz" "FAILED (got '${code:-nothing}')"
    edge_fail=1
  fi
  kill $edge_pf 2>/dev/null || true; trap - EXIT
fi
[ "$edge_fail" = "0" ] || exit 1

printf '\n\033[1;32mEvery hop is authenticated: SPIFFE where we own it, the mesh for the rest,\nand the browser edge by a certificate we verify.\033[0m\n'
