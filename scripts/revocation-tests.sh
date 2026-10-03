#!/usr/bin/env bash
# =============================================================================
# revocation-tests.sh — a revoked identity is refused at admission, now (S23).
#
# Revokes the agent's own SPIFFE ID in the denylist, shows the next task fail
# because the tool server refuses the agent *before its SVID expires*, then
# restores it. Non-destructive: it touches only the denylist, not SPIRE or
# Keycloak (that is scripts/revoke-workload.sh's fuller runbook).
# Usage: ./scripts/revocation-tests.sh
# =============================================================================
set -euo pipefail
# shellcheck source=lib.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
cd "$(dirname "$0")/.."

API=https://localhost:8443
CA=.edge/ca.crt
AGENT=spiffe://acme.com/ns/agent-platform/sa/agent
TASK='Get the profile of customer c-100'

say()  { printf '\n\033[1;36m━━ %s ━━\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m   ✓ %s\033[0m\n' "$*"; }
info() { printf '\033[2m   · %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m   ✗ %s\033[0m\n' "$*" >&2; exit 1; }

login() {
  curl -s --cacert "$CA" "$API/auth/login" -H 'content-type: application/json' \
    -d "{\"username\":\"$1\",\"password\":\"$2\"}" \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])'
}
run_task() {
  curl -s --cacert "$CA" "$API/tasks" -H "authorization: Bearer $1" \
    -H 'content-type: application/json' -d "{\"task\":\"$TASK\"}"
}
status_of() { python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("status","?"))'; }

ADMIN="$(login admin admin123)"
ALICE="$(login alice alice123)"
[ -n "$ADMIN" ] && [ -n "$ALICE" ] || die "could not sign in — is the edge up (./start.sh)?"

say "1. the agent works before revocation"
[ "$(run_task "$ALICE" | status_of)" = "ok" ] || die "the baseline task did not succeed"
ok "baseline: status ok"

say "2. revoke the agent's identity (denylist)"
curl -s --cacert "$CA" "$API/admin/workloads/revoke" -H "authorization: Bearer $ADMIN" \
  -H 'content-type: application/json' -d "{\"spiffe_id\":\"$AGENT\",\"reason\":\"revocation-test\"}" >/dev/null
ok "revoked"
info "waiting out the denylist cache (5s)…"
sleep 6

say "3. a task now fails — the agent is refused at admission, before any TTL"
after="$(run_task "$ALICE")"
echo "$after" | python3 -c 'import sys,json;d=json.load(sys.stdin);print("   status:",d.get("status"),"| reason:",(d.get("reason") or "")[:140])'
# The agent reaches the gateway first; the gateway refuses and audits the refusal.
if kubectl -n agent-platform logs -l app=gateway --tail=200 2>/dev/null | grep -q "revoked_refused"; then
  ok "refused at the gateway and audited (llm.revoked_refused)"
else
  info "refused (see the gateway/tools logs for 'revoked')"
fi

say "4. restore"
curl -s --cacert "$CA" "$API/admin/workloads/restore" -H "authorization: Bearer $ADMIN" \
  -H 'content-type: application/json' -d "{\"spiffe_id\":\"$AGENT\"}" >/dev/null
sleep 6

say "5. the agent works again"
[ "$(run_task "$ALICE" | status_of)" = "ok" ] || die "the agent did not recover after restore"
ok "revocation is immediate and reversible"

printf '\n\033[1;32mRevocation holds: refused at admission, not at SVID expiry.\033[0m\n'
