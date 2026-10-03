#!/usr/bin/env bash
# =============================================================================
# revoke-workload.sh — cut off a workload identity at every hop we own (S23).
#
#   ./scripts/revoke-workload.sh <spiffe-id> [--reason "why"] [--no-pods]
#   ./scripts/revoke-workload.sh <spiffe-id> --restore
#
# Revoke does four things, in order of immediacy:
#   1. the api denylist — every hop we own refuses the id at admission, *now*,
#      before its SVID expires (the point of S23);
#   2. the SPIRE registration entry — no new SVIDs are issued;
#   3. the Keycloak client named by the SPIFFE ID — no new token exchanges;
#   4. the workload's pods — the held SVID stops being presented.
#
# --restore removes only the denylist entry. Re-run ./scripts/setup.sh to
# re-register the SPIRE entry and re-enable the Keycloak client.
# =============================================================================
set -euo pipefail
# shellcheck source=lib.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
cd "$(dirname "$0")/.."

NS=agent-platform
API="${API_URL:-https://localhost:8443}"
CA="${EDGE_CA:-.edge/ca.crt}"

say()  { printf '\n\033[1;34m== %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m   ✓ %s\033[0m\n' "$*"; }
info() { printf '\033[2m   · %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m   ✗ %s\033[0m\n' "$*" >&2; exit 1; }

SPIFFE=""; REASON=""; RESTORE=""; NO_PODS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --restore) RESTORE=1; shift ;;
    --no-pods) NO_PODS=1; shift ;;
    --reason) REASON="${2:-}"; shift 2 ;;
    --reason=*) REASON="${1#*=}"; shift ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    -*) die "unknown option $1" ;;
    *) SPIFFE="$1"; shift ;;
  esac
done
[ -n "$SPIFFE" ] || die "usage: revoke-workload.sh <spiffe-id> [--reason ...] [--no-pods] [--restore]"
[ -f "$CA" ] || die "no edge CA at $CA — run ./start.sh first"

admin_token() {
  curl -s --cacert "$CA" "$API/auth/login" -H 'content-type: application/json' \
    -d '{"username":"admin","password":"admin123"}' \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])'
}

TOKEN="$(admin_token)"
[ -n "$TOKEN" ] || die "could not sign in as admin — is the edge up (./start.sh)?"

if [ -n "$RESTORE" ]; then
  say "restore $SPIFFE"
  curl -s --cacert "$CA" "$API/admin/workloads/restore" -H "authorization: Bearer $TOKEN" \
    -H 'content-type: application/json' -d "{\"spiffe_id\":\"$SPIFFE\"}" >/dev/null
  ok "removed from the api denylist"
  info "re-run ./scripts/setup.sh to re-register the SPIRE entry and re-enable the Keycloak client"
  exit 0
fi

say "1. api denylist — refused at admission, before the SVID expires"
curl -s --cacert "$CA" "$API/admin/workloads/revoke" -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d "{\"spiffe_id\":\"$SPIFFE\",\"reason\":\"${REASON:-revoked}\"}" >/dev/null
ok "revoked in the api denylist"

say "2. SPIRE registration entry — no new SVIDs"
SOCKET=/run/spire/server/private/api.sock
entries="$(kubectl -n $NS exec spire-server-0 -- /opt/spire/bin/spire-server entry show \
  -socketPath "$SOCKET" -spiffeID "$SPIFFE" 2>/dev/null | awk '/Entry ID/{print $NF}')"
if [ -n "$entries" ]; then
  for entry in $entries; do
    kubectl -n $NS exec spire-server-0 -- /opt/spire/bin/spire-server entry delete \
      -socketPath "$SOCKET" -entryID "$entry" >/dev/null
  done
  ok "deleted $(printf '%s\n' "$entries" | wc -l | tr -d ' ') registration entr(y/ies)"
else
  info "no registration entry for $SPIFFE"
fi

say "3. Keycloak client — no new token exchanges"
if kubectl -n $NS exec -i deploy/api -- python - disable "$SPIFFE" \
     < scripts/keycloak_client_admin.py 2>/dev/null | grep -q '^disabled'; then
  ok "disabled the Keycloak client named by the SPIFFE ID"
else
  info "no Keycloak client named $SPIFFE (or the api could not disable it)"
fi

say "4. the workload's pods — stop presenting the held SVID"
app="${SPIFFE##*/sa/}"
if [ -n "$NO_PODS" ]; then
  info "skipped (--no-pods)"
else
  kubectl -n $NS delete pod -l "app=$app" --ignore-not-found >/dev/null 2>&1 || true
  ok "deleted pods with app=$app (they restart with no identity)"
fi

say "done — and the honest limit"
info "A credential already issued stays valid elsewhere until it expires (JWT 5 m, X.509 1 h)."
info "The denylist is what makes the refusal immediate at our hops; the TTL bounds the rest."
