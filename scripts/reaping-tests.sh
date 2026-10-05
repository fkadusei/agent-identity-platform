#!/usr/bin/env bash
# =============================================================================
# reaping-tests.sh — a retired workload leaves no identity behind (S26).
#
# Registers a throwaway identity in both registries (a SPIRE entry and a Keycloak
# client), then runs the decommission runbook and shows both are gone. It never
# touches the real agent.
# Usage: ./scripts/reaping-tests.sh
# =============================================================================
set -euo pipefail
# shellcheck source=lib.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
cd "$(dirname "$0")/.."

NS=agent-platform
SOCKET=/run/spire/server/private/api.sock
TEST_ID="spiffe://acme.com/ns/agent-platform/sa/retired-test"

say()  { printf '\n\033[1;36m━━ %s ━━\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m   ✓ %s\033[0m\n' "$*"; }
info() { printf '\033[2m   · %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m   ✗ %s\033[0m\n' "$*" >&2; exit 1; }

spire() { kubectl -n $NS exec spire-server-0 -- /opt/spire/bin/spire-server "$@"; }
spire_entries() { spire entry show -socketPath "$SOCKET" -spiffeID "$TEST_ID" 2>/dev/null | grep -c 'Entry ID' || true; }
client() { kubectl -n $NS exec -i deploy/api -- python - "$1" "$TEST_ID" < scripts/keycloak_client_admin.py 2>/dev/null; }

say "1. register a throwaway identity"
# Start clean: an interrupted earlier run may have left the throwaway behind.
for e in $(spire entry show -socketPath "$SOCKET" -spiffeID "$TEST_ID" 2>/dev/null | awk '/Entry ID/{print $NF}'); do
  spire entry delete -socketPath "$SOCKET" -entryID "$e" >/dev/null
done
client delete >/dev/null 2>&1 || true
parent="$(spire agent list -socketPath "$SOCKET" | awk '/SPIFFE ID/{print $NF}' | head -1)"
[ -n "$parent" ] || die "no attested SPIRE agent to parent an entry to — run ./scripts/setup.sh"
spire entry create -socketPath "$SOCKET" -spiffeID "$TEST_ID" -parentID "$parent" \
  -selector "k8s:ns:$NS" -selector "k8s:sa:retired-test" >/dev/null
client create >/dev/null
[ "$(spire_entries)" -ge 1 ] || die "the SPIRE entry was not created"
[ "$(client show)" = "found" ] || die "the Keycloak client was not created"
ok "registered: 1 SPIRE entry, 1 Keycloak client"

say "2. decommission it"
./scripts/decommission-workload.sh "$TEST_ID" --reason "reaping-test" >/dev/null
ok "decommission ran"

say "3. nothing is left"
[ "$(spire_entries)" -eq 0 ] || die "the SPIRE entry still exists"
[ "$(client show)" = "missing" ] || die "the Keycloak client still exists"
ok "both registries reaped"

printf '\n\033[1;32mA retired workload leaves no identity behind.\033[0m\n'
