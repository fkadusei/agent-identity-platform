#!/bin/bash
# =============================================================================
# role-tools.sh — who may call which tool, end to end.
#
# Logs in as each demo user, exchanges the token through the agent's identity,
# and calls every tool at the tool server. Deterministic: no LLM involved.
# Usage: ./scripts/role-tools.sh
# =============================================================================
set -euo pipefail
# shellcheck source=lib.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
cd "$(dirname "$0")/.."

NS=agent-platform
beat() { printf "\n\033[1;36m━━ %s ━━\033[0m\n" "$*"; }

beat "WHO MAY CALL WHICH TOOL"
kubectl -n $NS exec -i deploy/agent -c agent -- python - < scripts/role_tools_client.py

printf "\n\033[1;32mRoles gate tools; policy is the control.\033[0m\n"
