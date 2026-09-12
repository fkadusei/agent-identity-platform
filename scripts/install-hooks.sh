#!/bin/bash
# =============================================================================
# install-hooks.sh — enable this repository's git hooks (secret guard).
# Run once per clone:  ./scripts/install-hooks.sh
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

chmod +x .githooks/pre-commit
git config core.hooksPath .githooks
echo "git hooks enabled: core.hooksPath -> .githooks"
echo "the pre-commit hook now blocks .env / key files and scans staged changes"
