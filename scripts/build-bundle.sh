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
# data.json carries the revision AND the tool catalogue, so the policy can assert
# every tool is grantable and deny unknown tools — without a hardcoded list.
python3 - "$REVISION" <<'PY' > dist/bundle/data.json
import json, pathlib, re, sys

revision = sys.argv[1]
source = pathlib.Path("app/tools/catalog.py").read_text()
tools = sorted(set(re.findall(r'name="([^"]+)"', source)))
print(json.dumps({"agentnhi": {"policy_version": revision}, "tools": tools}))
PY
printf '{"revision": "%s", "roots": ["agentnhi", "tools"]}\n' "$REVISION" > dist/bundle/.manifest
tar -C dist/bundle -czf dist/bundle.tar.gz .

echo "$REVISION"
