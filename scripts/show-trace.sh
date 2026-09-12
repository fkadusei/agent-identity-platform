#!/usr/bin/env bash
# Show the most recent end-to-end trace and the identity attributes on its spans.
#
# Proves the point of tracing here: a trace answers "which agent, for which user,
# and what did policy decide?" — the same question the audit log answers, but
# visually and across services (agent → tools → policy).
set -euo pipefail

NS=agent-platform

kubectl -n "$NS" port-forward svc/jaeger 16686:16686 >/dev/null 2>&1 &
PF=$!
trap 'kill $PF 2>/dev/null || true' EXIT
sleep 2

python3 - <<'PY'
import json
import time
import urllib.request

BASE = "http://localhost:16686"
KEEP = ("service.name", "spiffe_id", "sub", "tool", "decision", "reason")


def get(path):
    return json.load(urllib.request.urlopen(f"{BASE}{path}"))


# Traces flush on a batch timer, so give the collector a moment. Prefer the
# richest trace (the one covering the most services), not simply the latest.
trace = None
for _ in range(10):
    data = get("/api/traces?service=tools&limit=20").get("data", [])
    if data:
        trace = max(data, key=lambda t: len(t["spans"]))
        break
    time.sleep(2)

if not trace:
    raise SystemExit("no traces yet — run ./scripts/demo.sh first")

procs = trace.get("processes", {})
services = sorted({procs[s["processID"]]["serviceName"] for s in trace["spans"] if s.get("processID") in procs})
print(f"trace {trace['traceID']}")
print(f"{len(trace['spans'])} spans across: {', '.join(services)}\n")
for span in sorted(trace["spans"], key=lambda s: s["startTime"]):
    tags = {t["key"]: t["value"] for t in span.get("tags", [])}
    shown = " ".join(f"{k}={tags[k]}" for k in KEEP if k in tags)
    print(f"  {span['operationName']:<34} {shown}")
PY
