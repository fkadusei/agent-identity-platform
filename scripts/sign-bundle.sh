#!/usr/bin/env bash
# Sign the OPA policy bundle (dist/bundle.tar.gz).
#
# Two modes, matching ADR-0010:
#   * keyless (COSIGN_KEYLESS=1) — Sigstore. Fulcio issues a short-lived
#     certificate from the CI workflow's OIDC identity; the signature is recorded
#     in Rekor. No key exists to leak. This is the production path.
#   * local key — for a self-contained demo without OIDC. A key pair is
#     generated under .cosign/ (gitignored) on first use.
#
# Keyless only makes sense in CI (it needs an OIDC token), which is why the
# default here is the local key.
set -euo pipefail
cd "$(dirname "$0")/.."

BUNDLE=dist/bundle.tar.gz
if [ ! -f "$BUNDLE" ]; then
  echo "no bundle at $BUNDLE — run scripts/build-bundle.sh first" >&2
  exit 1
fi

if [ "${COSIGN_KEYLESS:-0}" = "1" ]; then
  cosign sign-blob --yes --bundle "$BUNDLE.sig" "$BUNDLE"
  echo "signed $BUNDLE (keyless / Sigstore)"
else
  mkdir -p .cosign
  if [ ! -f .cosign/cosign.key ]; then
    COSIGN_PASSWORD="" cosign generate-key-pair --output-key-prefix .cosign/cosign >/dev/null
    echo "generated a local signing key at .cosign/ (gitignored)"
  fi
  COSIGN_PASSWORD="" cosign sign-blob --yes --key .cosign/cosign.key \
    --bundle "$BUNDLE.sig" "$BUNDLE"
  echo "signed $BUNDLE (local key)"
fi
