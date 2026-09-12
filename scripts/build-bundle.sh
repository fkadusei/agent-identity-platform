#!/usr/bin/env bash
# Build the OPA policy bundle — the versioned, signable artifact OPA loads.
#
#   dist/bundle/
#     authz.rego        the policy (copied from policy/authz.rego)
#     data.json         {"agentnhi": {"policy_version": "<revision>"}}
#     .manifest         {"revision": "<revision>", "roots": ["agentnhi"]}
#   dist/bundle.tar.gz  the distributable artifact (what you sign/publish)
#
# The revision defaults to the git short SHA; override with POLICY_REVISION=...
# It is stamped into the bundle and returned with every decision, so a decision
# always names the policy revision that produced it.
set -euo pipefail
cd "$(dirname "$0")/.."

REVISION="${POLICY_REVISION:-$(git rev-parse --short HEAD 2>/dev/null || echo dev)}"

rm -rf dist/bundle
mkdir -p dist/bundle
cp policy/authz.rego dist/bundle/authz.rego
printf '{"agentnhi": {"policy_version": "%s"}}\n' "$REVISION" > dist/bundle/data.json
printf '{"revision": "%s", "roots": ["agentnhi"]}\n' "$REVISION" > dist/bundle/.manifest
tar -C dist/bundle -czf dist/bundle.tar.gz .

echo "$REVISION"
