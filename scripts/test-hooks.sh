#!/usr/bin/env bash
# Prove the pre-commit hook actually blocks secrets.
#
# Runs in a throwaway repository so it can never touch the real index, and works
# whether or not gitleaks is installed (the hook falls back to pattern matching).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
HOOK="$ROOT/.githooks/pre-commit"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

git -C "$TMP" init -q
git -C "$TMP" config user.email test@example.com
git -C "$TMP" config user.name test
cp "$ROOT/.gitleaks.toml" "$TMP/.gitleaks.toml"

fail=0
runs_hook() { (cd "$TMP" && "$HOOK") >/dev/null 2>&1; }

# 1. A sensitive filename is refused outright.
printf 'DEMO=1\n' > "$TMP/.env"
git -C "$TMP" add -f .env
if runs_hook; then
  echo "FAIL: hook allowed a staged .env"; fail=1
else
  echo "ok: hook refused .env"
fi
git -C "$TMP" rm --cached -q .env && rm -f "$TMP/.env"

# 2. Secret content is caught. The header is assembled at runtime so that this
#    script does not itself contain a private-key block (gitleaks would flag it).
{ printf -- '-----BEGIN %s PRIVATE KEY-----\n' RSA; printf 'MIIEfake\n'; } > "$TMP/notes.txt"
git -C "$TMP" add notes.txt
if runs_hook; then
  echo "FAIL: hook allowed a staged secret"; fail=1
else
  echo "ok: hook blocked a staged secret"
fi
git -C "$TMP" rm --cached -q notes.txt && rm -f "$TMP/notes.txt"

# 3. A clean change passes (no false positives).
printf 'hello\n' > "$TMP/readme.txt"
git -C "$TMP" add readme.txt
if runs_hook; then
  echo "ok: hook allowed a clean change"
else
  echo "FAIL: hook blocked a clean change"; fail=1
fi

exit $fail
