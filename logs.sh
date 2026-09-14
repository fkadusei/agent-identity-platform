#!/usr/bin/env bash
# =============================================================================
# logs.sh — a live trace of every interaction, across the services.
#
# Each service emits one JSON line per event (the audit stream), so this shows
# the whole chain in order: what the agent decided, what policy returned, what
# the tools did, and what the API recorded.
#
#   ./logs.sh          follow it live
#   ./logs.sh --last   the last 200 lines, then exit
# =============================================================================
set -uo pipefail
cd "$(dirname "$0")"

NS=agent-platform
# A plain string, not an array: `set -u` plus an empty array errors on bash 3.2
# (macOS), and word-splitting is exactly what we want here.
FOLLOW="-f"
[ "${1:-}" = "--last" ] && FOLLOW=""

echo "Tracing agent, tools, api, gateway (Ctrl-C to stop)…" >&2
kubectl -n "$NS" logs $FOLLOW --prefix=true --tail=200 --max-log-requests=8 \
  -l 'app in (agent,tools,api,gateway)' 2>&1 \
  | grep --line-buffered -vE 'GET /healthz|GET /metrics|"GET /|linkerd|Waiting for application|Application startup|Uvicorn running|Started server|Shutting down|Finished server'
