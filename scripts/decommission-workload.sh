#!/usr/bin/env bash
# =============================================================================
# decommission-workload.sh — remove a retired workload's registrations (S26).
#
#   ./scripts/decommission-workload.sh <spiffe-id> [--reason "why"]
#
# A workload that is gone should not leave identity behind. This removes the two
# registries a workload owns:
#   1. the SPIRE registration entry (namespace + service account -> SPIFFE ID);
#   2. the Keycloak client whose clientId is the SPIFFE ID (the delegation client).
#
# It also clears any admission-denylist entry for the id. It does NOT touch the
# static references — ALLOWED_WORKLOADS and the policy's is_trusted — which are
# code/config; they are printed at the end for a human to edit.
#
# For a *live* workload that must be cut off first, run revoke-workload.sh, then
# this. This is the deregistration half of the lifecycle gap (Q20).
# =============================================================================
set -euo pipefail
# shellcheck source=lib.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
cd "$(dirname "$0")/.."

NS=agent-platform
API="${API_URL:-https://localhost:8443}"
CA="${EDGE_CA:-.edge/ca.crt}"
SOCKET=/run/spire/server/private/api.sock

say()  { printf '\n\033[1;34m== %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m   ✓ %s\033[0m\n' "$*"; }
info() { printf '\033[2m   · %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m   ✗ %s\033[0m\n' "$*" >&2; exit 1; }

SPIFFE=""; REASON=""
while [ $# -gt 0 ]; do
  case "$1" in
    --reason) REASON="${2:-}"; shift 2 ;;
    --reason=*) REASON="${1#*=}"; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    -*) die "unknown option $1" ;;
    *) SPIFFE="$1"; shift ;;
  esac
done
[ -n "$SPIFFE" ] || die "usage: decommission-workload.sh <spiffe-id> [--reason ...]"
[ -f "$CA" ] || die "no edge CA at $CA — run ./start.sh first"

say "1. SPIRE registration entry — no identity can be issued"
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

say "2. Keycloak client — the delegation client is gone"
if kubectl -n $NS exec -i deploy/api -- python - delete "$SPIFFE" \
     < scripts/keycloak_client_admin.py 2>/dev/null | grep -q '^deleted'; then
  ok "deleted the Keycloak client named by the SPIFFE ID"
else
  info "no Keycloak client named $SPIFFE"
fi

say "3. admission denylist — clear any entry for the id"
TOKEN="$(curl -s --cacert "$CA" "$API/auth/login" -H 'content-type: application/json' \
  -d '{"username":"admin","password":"admin123"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')"
if [ -n "$TOKEN" ]; then
  curl -s --cacert "$CA" "$API/admin/workloads/restore" -H "authorization: Bearer $TOKEN" \
    -H 'content-type: application/json' -d "{\"spiffe_id\":\"$SPIFFE\"}" >/dev/null
  ok "denylist entry cleared (if there was one)"
else
  info "could not sign in as admin — skipped the denylist cleanup"
fi

say "still static — edit these by hand if they name the workload"
info "ALLOWED_WORKLOADS on each service (app/common/workload.py) — remove the SPIFFE ID"
info "policy is_trusted / the role matrix (policy/authz.rego) — remove the grant, rebuild the bundle"
info "reason recorded: ${REASON:-<none>}"
