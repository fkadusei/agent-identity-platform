#!/usr/bin/env bash
# =============================================================================
# doctor.sh — can this machine run the platform? Say what is missing, before a
# 10-minute build fails halfway. Required tools fail; the model is optional (the
# in-cluster test double covers a machine with no Ollama).
#
# Usage: ./scripts/doctor.sh
# =============================================================================
set -euo pipefail

fail=0
ok()   { printf '  \033[1;32m✓\033[0m %s\n' "$*"; }
bad()  { printf '  \033[1;31m✗\033[0m %s\n' "$*"; fail=1; }
warn() { printf '  \033[1;33m!\033[0m %s\n' "$*"; }

echo "== tools"
for bin in docker kind kubectl python3 curl openssl; do
  if command -v "$bin" >/dev/null 2>&1; then ok "$bin"; else bad "$bin not found"; fi
done
if [ "$fail" = 1 ] && [ "$(uname)" = "Darwin" ]; then
  echo "     install: brew install kind kubectl python curl openssl   ·   Docker Desktop"
fi

echo "== docker"
if docker info >/dev/null 2>&1; then
  ok "Docker daemon is running"
  mem="$(docker info --format '{{.MemTotal}}' 2>/dev/null || echo 0)"
  if [ "${mem:-0}" -gt 0 ]; then
    gb=$((mem / 1024 / 1024 / 1024))
    if [ "$gb" -lt 8 ]; then
      warn "Docker has ${gb}GB; the cluster wants ~8GB (Docker Desktop → Settings → Resources)"
    else
      ok "Docker memory ${gb}GB"
    fi
  fi
else
  bad "Docker daemon is not running — start Docker Desktop"
fi

echo "== model (optional)"
if curl -sf --max-time 3 http://localhost:11434/api/tags >/dev/null 2>&1; then
  ok "Ollama is reachable — ./scripts/use-model.sh --list to choose a model"
else
  warn "no Ollama on :11434; the in-cluster test double will be used (the demo needs no model)"
fi

echo "== port 8443"
if command -v lsof >/dev/null 2>&1; then
  owner="$(lsof -nP -iTCP:8443 -sTCP:LISTEN 2>/dev/null | awk 'NR==2{print $1}' || true)"
  case "$owner" in
    ""|com.docke|docker|kubectl) ok "8443 is free or held by Docker/kind" ;;
    *) warn "8443 is held by '$owner' — stop it, or the edge cannot bind (cluster.yaml maps host 8443)" ;;
  esac
fi

echo
if [ "$fail" = 1 ]; then
  echo "Fix the ✗ items above, then run ./start.sh again."
  exit 1
fi
echo "Prerequisites look good."
