#!/bin/bash
# =============================================================================
# demo-roles.sh — enrollment, role assignment, and server-side enforcement.
# Usage: ./scripts/demo-roles.sh
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

NS=agent-platform
beat() { printf "\n\033[1;36m━━ %s ━━\033[0m\n" "$*"; }

beat "ENROLL → ADMIN GRANTS A ROLE → ROLE IS ENFORCED"
kubectl -n $NS exec -i deploy/agent -- python - < scripts/roles_client.py

printf "\n\033[1;32mDone. Roles are enforced by the API, not the UI.\033[0m\n"
