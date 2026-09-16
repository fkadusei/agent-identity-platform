#!/bin/bash
# =============================================================================
# attack-tests.sh — the threat model made executable. Every attack must be
# BLOCKED. Usage: ./scripts/attack-tests.sh
# =============================================================================
set -uo pipefail   # no -e: we EXPECT failures
# shellcheck source=lib.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
cd "$(dirname "$0")/.."
NS=agent-platform
SPIFFE_ID="spiffe://acme.com/ns/agent-platform/sa/agent"

beat() { printf "\n\033[1;31m━━ ATTACK %s ━━\033[0m\n" "$*"; }
good() { printf "\033[1;32m   BLOCKED ✓  %s\033[0m\n" "$*"; }
bad()  { printf "\033[1;31m   SUCCEEDED — THAT IS A BUG ✗ %s\033[0m\n" "$*"; }

# ---------------------------------------------------------------------------
beat "1 — ROGUE WORKLOAD tries to fetch a workload identity"
kubectl -n $NS delete pod rogue --ignore-not-found >/dev/null 2>&1
kubectl -n $NS run rogue --image=agent-platform/agent:demo --restart=Never \
  --overrides='{"spec":{"serviceAccountName":"default","containers":[{"name":"rogue","image":"agent-platform/agent:demo","command":["sleep","infinity"],"volumeMounts":[{"name":"sock","mountPath":"/run/spire/sockets","readOnly":true}]}],"volumes":[{"name":"sock","hostPath":{"path":"/run/spire/sockets","type":"Directory"}}]}}' >/dev/null
kubectl -n $NS wait --for=condition=Ready pod/rogue --timeout=120s >/dev/null
OUT=$(kubectl -n $NS exec rogue -- python -c "
from agentnhi.identity import fetch_jwt_svid
try:
    print('GOT', fetch_jwt_svid('unix:///run/spire/sockets/agent.sock', 'x'))
except Exception:
    print('REFUSED')" 2>/dev/null)
if echo "$OUT" | grep -q REFUSED; then
  good "SPIRE issued nothing. No identity, no token, no access."
else
  bad "rogue workload got an SVID: $OUT"
fi

# ---------------------------------------------------------------------------
beat "6 — REACHING THE LLM GATEWAY WITHOUT A WORKLOAD IDENTITY"
# The gateway serves HTTPS and REQUIRES a client SVID (mTLS). A workload with no
# identity cannot complete the handshake, so it cannot reach the model at all.
OUT=$(kubectl -n $NS exec rogue -- python -c "
import httpx
try:
    r = httpx.get('https://gateway:8443/healthz', verify=False, timeout=5)
    print('REACHED', r.status_code)
except Exception as e:
    print('REFUSED', type(e).__name__)" 2>/dev/null)
if echo "$OUT" | grep -q REFUSED; then
  good "gateway refused the connection: $OUT"
else
  bad "an identity-less workload reached the gateway: $OUT"
fi
kubectl -n $NS delete pod rogue --wait=false >/dev/null 2>&1

# ---------------------------------------------------------------------------
beat "2-5 — TOKEN FORWARDING / OUT-OF-POLICY / APPROVAL BYPASS / PII"
kubectl -n $NS exec -i deploy/agent -- python - < scripts/attack_client.py
STATUS=$?

if [ "$STATUS" -eq 0 ]; then
  printf "\n\033[1;32mAll attacks blocked.\033[0m\n"
else
  printf "\n\033[1;31mAt least one attack succeeded — see above.\033[0m\n"
fi
exit $STATUS
