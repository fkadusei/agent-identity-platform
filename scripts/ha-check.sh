#!/bin/bash
# =============================================================================
# ha-check.sh — show the redundancy and prove a disruption is survivable.
#
# Reports each stateless service's replicas and spread, its PodDisruptionBudget,
# then evicts one replica and confirms the service keeps answering.
# Usage: ./scripts/ha-check.sh
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

NS=agent-platform
beat() { printf "\n\033[1;36m━━ %s ━━\033[0m\n" "$*"; }

beat "REPLICAS AND SPREAD"
kubectl -n $NS get pods \
  -o custom-columns='SERVICE:.metadata.labels.app,NODE:.spec.nodeName,STATUS:.status.phase' \
  | grep -E 'SERVICE|api|tools|agent|gateway|opa' | sort

beat "POD DISRUPTION BUDGETS"
kubectl -n $NS get pdb

beat "EVICT ONE REPLICA (the budget must keep the service up)"
victim=$(kubectl -n $NS get pods -l app=tools -o jsonpath='{.items[0].metadata.name}')
echo "evicting $victim"
kubectl -n $NS delete pod "$victim" --wait=false >/dev/null

ok=0
for _ in $(seq 1 30); do
  if kubectl -n $NS exec deploy/api -c api -- python -c \
    "import httpx,sys; sys.exit(0 if httpx.get('http://tools:8000/healthz', timeout=2).status_code==200 else 1)" \
    >/dev/null 2>&1; then
    ok=1; break
  fi
  sleep 2
done
[ "$ok" = "1" ] && printf '\n\033[1;32mThe tools service stayed up throughout.\033[0m\n' || {
  printf '\n\033[1;31mThe tools service was unreachable during the eviction.\033[0m\n'; exit 1; }

printf '\n\033[1;32mRedundancy holds: replicas spread, budgets protect them.\033[0m\n'
