#!/bin/bash
# =============================================================================
# tls-check.sh — prove every in-cluster hop is mTLS.
#
# The app layer does SPIFFE mTLS on agent<->gateway; the service mesh (Linkerd)
# covers every other hop. This reports the mesh edges and fails if any is not
# SECURED.
# Usage: ./scripts/tls-check.sh
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

NS=agent-platform
beat() { printf "\n\033[1;36m━━ %s ━━\033[0m\n" "$*"; }

if ! command -v linkerd >/dev/null 2>&1; then
  echo "linkerd CLI not found — install it (brew install linkerd) to check the mesh." >&2
  exit 1
fi

beat "MESH CONTROL PLANE"
linkerd check 2>&1 | tail -1

beat "IN-CLUSTER EDGES (SECURED = mTLS)"
edges=$(linkerd viz edges deploy -n "$NS" 2>/dev/null)
printf '%s\n' "$edges" | awk 'NR==1 || $NF=="√"'

unsecured=$(printf '%s\n' "$edges" | awk 'NR>1 && $NF!="√"' | wc -l | tr -d ' ')
if [ "$unsecured" != "0" ]; then
  printf '\n\033[1;31m%d edge(s) are NOT mTLS:\033[0m\n' "$unsecured"
  printf '%s\n' "$edges" | awk 'NR>1 && $NF!="√"'
  exit 1
fi

printf '\n\033[1;32mAll in-cluster edges are mTLS.\033[0m\n'
