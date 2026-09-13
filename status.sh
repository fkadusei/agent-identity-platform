#!/usr/bin/env bash
# =============================================================================
# status.sh — is it running, and what URL do I open?
# =============================================================================
set -uo pipefail
cd "$(dirname "$0")"

NS=agent-platform
CLUSTER=agent-platform
URL=http://localhost:8080

if ! kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  echo "cluster: not created"
  echo "         run ./start.sh"
  exit 1
fi
echo "cluster: up"

kubectl config use-context "kind-$CLUSTER" >/dev/null 2>&1 || true

# "2/2" and "Running" for every pod.
read -r ready total <<<"$(kubectl -n "$NS" get pods --no-headers 2>/dev/null \
  | awk -F'[ /]+' '{t++; if ($2==$3 && $4=="Running") r++} END {print r+0, t+0}')"
echo "pods:    ${ready:-0}/${total:-0} ready"

if curl -sf "$URL/healthz" >/dev/null 2>&1; then
  printf 'url:     \033[1;32m%s\033[0m  (open this)\n' "$URL"
else
  echo "url:     not reachable — run ./start.sh"
fi
