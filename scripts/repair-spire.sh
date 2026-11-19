#!/usr/bin/env bash
# =============================================================================
# repair-spire.sh — recover the identity tier when the app tier crash-loops.
#
# Symptom: api/tools/agent/gateway in CrashLoopBackOff, their logs showing
#   `could not obtain an X.509-SVID ... /run/spire/sockets/agent.sock does not exist`
# Cause: the SPIRE agent's data dir is an emptyDir, and after the server rotates
#   its CA an agent that lost its keys cannot re-attest. Deleting the agent pods
#   clears the stale state and forces a fresh attestation.
#
# Usage: ./scripts/repair-spire.sh
# =============================================================================
set -euo pipefail
# shellcheck source=lib.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
cd "$(dirname "$0")/.."

NS=agent-platform
APPS=(api tools agent gateway)

echo "1. recreating the SPIRE agent pods (clears stale identity state)"
kubectl -n "$NS" delete pod -l app=spire-agent --ignore-not-found
kubectl -n "$NS" rollout status ds/spire-agent --timeout=180s

echo "2. restarting the workloads that crash-looped on the missing SVID"
kubectl -n "$NS" rollout restart deploy/api deploy/tools deploy/agent deploy/gateway >/dev/null
for d in "${APPS[@]}"; do
  kubectl -n "$NS" rollout status "deploy/$d" --timeout=180s
done

echo
echo "Done. Verify:"
echo "  ./status.sh"
echo "  curl --cacert .edge/ca.crt https://localhost:8443/healthz"
