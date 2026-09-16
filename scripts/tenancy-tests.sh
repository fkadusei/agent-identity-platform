#!/bin/bash
# =============================================================================
# tenancy-tests.sh — prove tenant isolation (threat T9) at every layer.
# Usage: ./scripts/tenancy-tests.sh
# =============================================================================
set -euo pipefail
# shellcheck source=lib.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
cd "$(dirname "$0")/.."

NS=agent-platform
beat() { printf "\n\033[1;36m━━ %s ━━\033[0m\n" "$*"; }

beat "TENANT ISOLATION — claim → policy → data"
kubectl -n $NS exec -i deploy/agent -- python - < scripts/tenancy_client.py

printf "\n\033[1;32mA second tenant's data is unreachable from the first.\033[0m\n"
