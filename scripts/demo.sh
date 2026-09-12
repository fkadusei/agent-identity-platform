#!/bin/bash
# =============================================================================
# demo.sh — the happy path, paced for presenting.
# Talk track: docs/guides/ (added in Phase 1).
# Usage: ./scripts/demo.sh     (AUTO=1 skips pauses)
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

NS=agent-platform
beat()  { printf "\n\033[1;36m━━ %s ━━\033[0m\n" "$*"; }
pause() { [ "${AUTO:-0}" = "1" ] || { printf "\033[2m[enter]\033[0m"; read -r _; } ; }

beat "0. THE CAST"
kubectl -n $NS get pods
pause

beat "1-5. LOGIN → RUN → APPROVAL → RESUME"
kubectl -n $NS exec -i deploy/agent -- python - < scripts/demo_client.py
pause

beat "6. THE AUDIT TRAIL — who did what, on whose behalf, why"
kubectl -n $NS logs deploy/tools --tail=8 | grep '^{' || true
kubectl -n $NS logs deploy/api --tail=4 | grep '^{' || true

printf "\n\033[1;32mDemo complete. Now run ./scripts/attack-tests.sh\033[0m\n"
