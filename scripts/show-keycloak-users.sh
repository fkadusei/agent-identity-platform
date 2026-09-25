#!/bin/bash
# =============================================================================
# show-keycloak-users.sh — the users that really exist in Keycloak.
#
# Answers "where do the users live?" with Keycloak's own answer rather than the
# app's. It runs inside the API pod, which means no port-forward, no /etc/hosts
# entry and no browser: in there `keycloak` resolves by service name, which also
# sidesteps KC_HOSTNAME_STRICT pinning the console to that name.
#
# The console itself is still worth opening once by hand — see
# docs/enrollment-and-roles.md → "Seeing it in Keycloak".
#
# Usage: ./scripts/show-keycloak-users.sh
# =============================================================================
set -euo pipefail
# shellcheck source=lib.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
cd "$(dirname "$0")/.."

NS=agent-platform
beat() { printf "\n\033[1;36m━━ %s ━━\033[0m\n" "$*"; }

# The API pod is the one holding the admin client's secret, so this runs the
# product's own Keycloak client, not a second one with its own credentials.
beat "USERS AS KEYCLOAK REPORTS THEM"
kubectl -n $NS exec -i deploy/api -- python - < scripts/keycloak_users_client.py

printf "\n\033[1;32mThat is Keycloak's answer, not the app's — the app keeps no user table.\033[0m\n"
