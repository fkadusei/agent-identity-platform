#!/bin/bash
# =============================================================================
# scan-secrets.sh — scan the working tree AND the full git history for secrets.
# Uses gitleaks with .gitleaks.toml. Install it with: brew install gitleaks
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

if command -v gitleaks >/dev/null 2>&1; then
  GL=$(command -v gitleaks)
elif [ -x /tmp/gitleaks ]; then
  GL=/tmp/gitleaks
else
  echo "gitleaks not found. Install it:  brew install gitleaks" >&2
  exit 1
fi

echo "== working tree =="
"$GL" dir . -c .gitleaks.toml --no-banner --redact
echo
echo "== full git history =="
"$GL" git -c .gitleaks.toml --no-banner --redact
echo
echo "== staged changes =="
"$GL" git --staged -c .gitleaks.toml --no-banner --redact || true
echo
echo "scan complete"
