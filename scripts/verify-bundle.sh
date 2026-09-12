#!/usr/bin/env bash
# Verify the OPA policy bundle signature — the gate a deploy pipeline runs before
# shipping a policy revision.
#
#   local key mode  →  ./scripts/verify-bundle.sh
#   keyless mode    →  COSIGN_KEYLESS=1 COSIGN_IDENTITY_REGEXP='https://github.com/...' \
#                        ./scripts/verify-bundle.sh
set -euo pipefail
cd "$(dirname "$0")/.."

BUNDLE=dist/bundle.tar.gz
if [ ! -f "$BUNDLE.sig" ]; then
  echo "no signature at $BUNDLE.sig — run scripts/sign-bundle.sh first" >&2
  exit 1
fi

if [ "${COSIGN_KEYLESS:-0}" = "1" ]; then
  : "${COSIGN_IDENTITY_REGEXP:?set COSIGN_IDENTITY_REGEXP to the expected signing identity}"
  cosign verify-blob --bundle "$BUNDLE.sig" \
    --certificate-identity-regexp "$COSIGN_IDENTITY_REGEXP" \
    --certificate-oidc-issuer "${COSIGN_OIDC_ISSUER:-https://token.actions.githubusercontent.com}" \
    "$BUNDLE"
else
  cosign verify-blob --key .cosign/cosign.pub --bundle "$BUNDLE.sig" "$BUNDLE"
fi
echo "verified $BUNDLE"
