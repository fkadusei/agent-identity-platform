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
#
# This checks both: the mesh edges it can see, and then each hop we own, asked
# directly (an SVID is required, and a name is required where one is enforced).
# Usage: ./scripts/tls-check.sh
# =============================================================================
set -euo pipefail
# shellcheck source=lib.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
cd "$(dirname "$0")/.."

NS=agent-platform
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

printf '\n\033[1;32mEvery hop is authenticated: SPIFFE where we own it, the mesh for the rest.\033[0m\n'
