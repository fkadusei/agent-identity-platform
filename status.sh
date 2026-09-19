#!/usr/bin/env bash
# =============================================================================
# status.sh — is it running, and what URL do I open?
# =============================================================================
set -uo pipefail
# shellcheck source=scripts/lib.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/lib.sh"
cd "$(dirname "$0")"

NS=agent-platform
CLUSTER=agent-platform
# https, terminated at the ingress (S7b), with our CA — never -k.
URL=https://localhost:8443
EDGE_CA=.edge/ca.crt

if ! kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  echo "cluster: not created"
  echo "         run ./start.sh"
  exit 1
fi
echo "cluster: up"

# "2/2" and "Running" for every pod that is meant to be running. Pods that have
# finished (a Job, like the realm import; a one-shot like the attack suite's
# `rogue`) are not "not ready" — counting them made the total look wrong.
read -r ready total <<<"$(kubectl -n "$NS" get pods --no-headers 2>/dev/null \
  | awk -F'[ /]+' '$4 != "Completed" && $4 != "Succeeded" {t++; if ($2==$3 && $4=="Running") r++} END {print r+0, t+0}')"
echo "pods:    ${ready:-0}/${total:-0} ready"

if [ -f "$EDGE_CA" ] && curl -sf --cacert "$EDGE_CA" "$URL/healthz" >/dev/null 2>&1; then
  printf 'url:     \033[1;32m%s\033[0m  (open this)\n' "$URL"
elif [ ! -f "$EDGE_CA" ]; then
  echo "url:     the browser edge is not configured — run ./scripts/setup.sh"
else
  echo "url:     not reachable — run ./start.sh"
fi
