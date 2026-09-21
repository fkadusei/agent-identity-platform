#!/bin/bash
# =============================================================================
# use-model.sh — swap the model the gateway uses, without editing a manifest.
#
#   ./scripts/use-model.sh qwen3:30b-a3b              # swap
#   ./scripts/use-model.sh llama3.2:3b                # and back
#   ./scripts/use-model.sh --eval qwen3:30b-a3b       # swap, then run the live evals
#
# The gateway is the only component that talks to a model, so the model is named in
# exactly one place: the llm-config ConfigMap, rendered here from .env. Nothing is
# rebuilt, no image changes, and no provider key is read or printed on this path.
# Usage: ./scripts/use-model.sh <model> [url] [--eval]
# =============================================================================
set -euo pipefail
# shellcheck source=lib.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
cd "$(dirname "$0")/.."

NS=agent-platform
ENV_FILE=.env
say()  { printf '\n\033[1;34m== %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m   ✓ %s\033[0m\n' "$*"; }
info() { printf '\033[2m   · %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m   ✗ %s\033[0m\n' "$*" >&2; exit 1; }

MODEL=""
URL=""
EVAL=""
for arg in "$@"; do
  case "$arg" in
    --eval) EVAL=1 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    -*) die "unknown option $arg" ;;
    *) if [ -z "$MODEL" ]; then MODEL="$arg"; else URL="$arg"; fi ;;
  esac
done
[ -n "$MODEL" ] || die "usage: use-model.sh <model> [url] [--eval]"
: "${URL:=${OLLAMA_URL:-http://host.docker.internal:11434}}"

kubectl get ns "$NS" >/dev/null 2>&1 || die "no $NS namespace — run ./start.sh first"

say "1. record it in .env (so a re-run of setup.sh keeps the choice)"
umask 077
set_env() { # set_env <KEY> <VALUE> — replace in place, or append
  local key="$1" value="$2" tmp
  if [ -f "$ENV_FILE" ] && grep -q "^${key}=" "$ENV_FILE"; then
    tmp="$(mktemp)"
    grep -v "^${key}=" "$ENV_FILE" > "$tmp"
    printf "%s='%s'\n" "$key" "$value" >> "$tmp"
    mv "$tmp" "$ENV_FILE"
  else
    printf "%s='%s'\n" "$key" "$value" >> "$ENV_FILE"
  fi
}
set_env OLLAMA_MODEL "$MODEL"
set_env OLLAMA_URL "$URL"
: "${LLM_PROVIDER:=ollama}"
set_env LLM_PROVIDER "$LLM_PROVIDER"
ok "$ENV_FILE: OLLAMA_MODEL=$MODEL"

say "2. hand it to the gateway"
kubectl -n "$NS" create configmap llm-config \
  --from-literal=LLM_PROVIDER="$LLM_PROVIDER" \
  --from-literal=OLLAMA_URL="$URL" \
  --from-literal=OLLAMA_MODEL="$MODEL" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
# The config is read at startup and is mounted as environment, so the pod has to
# restart: a ConfigMap change on its own would leave the old model running.
kubectl -n "$NS" rollout restart deploy/gateway >/dev/null
kubectl -n "$NS" rollout status deploy/gateway --timeout=300s >/dev/null
kubectl -n "$NS" exec deploy/gateway -c gateway -- sh -c 'printf "   gateway now: %s\n" "$OLLAMA_MODEL"'

if [ -n "$EVAL" ]; then
  say "3. the live evals (real model calls — this takes a while)"
  kubectl -n "$NS" exec deploy/agent -c agent -- python -m app.agent.evals --live || true
else
  say "3. next"
  info "./scripts/demo.sh                                     # a run through the new model"
  info "kubectl -n $NS logs deploy/gateway | grep llm.call      # which model ran, per call"
  info "$0 --eval $MODEL                                     # score it against the eval suite"
fi
