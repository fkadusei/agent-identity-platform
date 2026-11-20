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
if [ "$fail" = 1 ]; then
  case "$(uname -s)" in
    Darwin)
      echo "     install: brew install kind kubectl python curl openssl   ·   Docker Desktop" ;;
    Linux)
      if grep -qi microsoft /proc/version 2>/dev/null; then
        echo "     WSL detected — enable Docker Desktop → Settings → Resources → WSL integration"
      fi
      if command -v apt-get >/dev/null 2>&1; then
        echo "     install: sudo apt-get install -y python3 curl openssl docker.io"
      elif command -v dnf >/dev/null 2>&1; then
        echo "     install: sudo dnf install -y python3 curl openssl docker"
      elif command -v pacman >/dev/null 2>&1; then
        echo "     install: sudo pacman -S python curl openssl docker"
      fi
      echo "     kind + kubectl: https://kind.sigs.k8s.io/docs/user/quick-start/#installation"
      echo "                     https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/" ;;
    MINGW*|MSYS*|CYGWIN*)
      echo "     Windows: run this inside WSL2, with Docker Desktop's WSL integration enabled" ;;
    *)
      echo "     install docker, kind, kubectl, python3, curl, openssl (see the README)" ;;
  esac
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
elif command -v ss >/dev/null 2>&1; then
  if ss -ltn 2>/dev/null | awk 'NR>1{print $4}' | grep -q ':8443$'; then
    warn "8443 is in use — stop what holds it, or the edge cannot bind (cluster.yaml maps host 8443)"
  else
    ok "8443 is free"
  fi
else
  warn "cannot check port 8443 (no lsof or ss)"
fi

echo
if [ "$fail" = 1 ]; then
  echo "Fix the ✗ items above, then run ./start.sh again."
  exit 1
fi
echo "Prerequisites look good."
