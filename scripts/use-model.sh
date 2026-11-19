#!/usr/bin/env bash
# =============================================================================
# use-model.sh — choose the model the gateway uses. Nothing is rebuilt: the
# gateway is the only component that talks to a model, so the choice is written
# to .env and handed to it as a ConfigMap.
#
#   ./scripts/use-model.sh                 # interactive: local / hosted / no model
#   ./scripts/use-model.sh --list          # list the local Ollama models
#   ./scripts/use-model.sh --local [model] [url]
#   ./scripts/use-model.sh --hosted <base-url> <model>   # key from LLM_API_KEY or prompt
#   ./scripts/use-model.sh --stub          # the in-cluster test double, no model/key
#   ./scripts/use-model.sh <model> [url]   # legacy spelling of --local
#   ... add --eval to run the live evals afterwards
#
# Local is Ollama (the default, and the one that keeps data on the machine).
# Hosted is any OpenAI-compatible endpoint (OpenAI, Groq, Together, vLLM, …), the
# standard this project already speaks. The key lives only in .env and the
# llm-api-key Secret the gateway mounts — never in the agent.
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

usage() { sed -n '2,20p' "$0"; exit 0; }

MODE=""; MODEL=""; URL=""; EVAL=""; ARGS=()
for arg in "$@"; do
  case "$arg" in
    --eval) EVAL=1 ;;
    -h|--help) usage ;;
    --list|--local|--hosted|--stub) MODE="${arg#--}"; ARGS=() ;;
    -*) die "unknown option $arg (see --help)" ;;
    *) ARGS+=("$arg") ;;
  esac
done

# Load the existing choice so a bare `use-model.sh` starts from it.
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi
# OLLAMA_URL is what the *gateway container* uses (host.docker.internal);
# HOST_OLLAMA_URL is what this script uses to discover models from the host.
: "${OLLAMA_URL:=http://host.docker.internal:11434}"
: "${HOST_OLLAMA_URL:=http://localhost:11434}"

if [ -z "$MODE" ]; then
  if [ "${#ARGS[@]}" -ge 1 ]; then
    MODE=local
  elif [ -t 0 ]; then
    MODE=interactive
  else
    usage
  fi
fi
if [ -z "$MODEL" ] && [ "${#ARGS[@]}" -ge 1 ]; then MODEL="${ARGS[0]}"; fi
if [ -z "$URL" ] && [ "${#ARGS[@]}" -ge 2 ]; then URL="${ARGS[1]}"; fi

kubectl get ns "$NS" >/dev/null 2>&1 || die "no $NS namespace — run ./start.sh first"

ollama_models() {
  curl -sf --max-time 4 "$HOST_OLLAMA_URL/api/tags" 2>/dev/null \
    | python3 -c 'import sys,json; print("\n".join(m["name"] for m in json.load(sys.stdin).get("models",[])))' 2>/dev/null || true
}

ask_local() {
  local models chosen
  models="$(ollama_models)"
  [ -n "$models" ] || die "no models at $HOST_OLLAMA_URL — start Ollama (ollama serve) and pull one, e.g. ollama pull llama3.2:3b"
  if [ -z "$MODEL" ]; then
    say "local models on $HOST_OLLAMA_URL"
    printf '%s\n' "$models" | nl -ba -w2 -s') '
    printf 'pick a number, or type a model name: '
    read -r chosen
    case "$chosen" in
      ''|*[!0-9]*) MODEL="$chosen" ;;
      *) MODEL="$(printf '%s\n' "$models" | sed -n "${chosen}p")" ;;
    esac
    [ -n "$MODEL" ] || die "nothing selected"
  fi
  [ -n "$URL" ] || URL="$OLLAMA_URL"
}

ask_hosted() {
  if [ -z "$URL" ]; then
    printf 'base URL [https://api.openai.com/v1]: '; read -r URL
    : "${URL:=https://api.openai.com/v1}"
  fi
  if [ -z "$MODEL" ]; then
    printf 'model [gpt-4o-mini]: '; read -r MODEL
    : "${MODEL:=gpt-4o-mini}"
  fi
  if [ -z "${LLM_API_KEY:-}" ]; then
    printf 'API key (hidden; stored only in .env): '
    read -rs LLM_API_KEY; printf '\n'
  fi
  [ -n "${LLM_API_KEY:-}" ] || die "a hosted provider needs an API key"
}

set_env() { # set_env <KEY> <VALUE> — replace in place, or append; never echoed
  local key="$1" value="$2" tmp
  umask 077
  if [ -f "$ENV_FILE" ] && grep -q "^${key}=" "$ENV_FILE"; then
    tmp="$(mktemp)"
    grep -v "^${key}=" "$ENV_FILE" > "$tmp"
    printf "%s='%s'\n" "$key" "$value" >> "$tmp"
    mv "$tmp" "$ENV_FILE"
  else
    printf "%s='%s'\n" "$key" "$value" >> "$ENV_FILE"
  fi
}

case "$MODE" in
  list)
    models="$(ollama_models)"
    [ -n "$models" ] && printf '%s\n' "$models" || die "no models at $HOST_OLLAMA_URL (is Ollama running?)"
    exit 0
    ;;
  interactive)
    say "which model should the gateway use?"
    printf '  1) Local model (Ollama — stays on this machine)\n'
    printf '  2) Hosted / any OpenAI-compatible provider\n'
    printf '  3) No model (in-cluster test double — the demo runs, no downloads)\n'
    printf 'choose [1]: '; read -r choice
    case "${choice:-1}" in
      1) MODE=local ;;
      2) MODE=hosted ;;
      3) MODE=stub ;;
      *) die "unknown choice $choice" ;;
    esac
    ;;
esac

CFG_PROVIDER=""; CFG_OLLAMA_URL=""; CFG_OLLAMA_MODEL=""
CFG_BASE_URL=""; CFG_MODEL=""; CFG_STRIP=""; NEED_KEY=""

case "$MODE" in
  local)
    ask_local
    CFG_PROVIDER=ollama; CFG_OLLAMA_URL="$URL"; CFG_OLLAMA_MODEL="$MODEL"
    set_env LLM_PROVIDER ollama
    set_env OLLAMA_URL "$URL"
    set_env OLLAMA_MODEL "$MODEL"
    ok "$ENV_FILE: local model $MODEL at $URL"
    ;;
  hosted)
    ask_hosted
    CFG_PROVIDER=openai-compatible; CFG_BASE_URL="$URL"; CFG_MODEL="$MODEL"; CFG_STRIP=1; NEED_KEY=1
    set_env LLM_PROVIDER openai-compatible
    set_env LLM_BASE_URL "$URL"
    set_env LLM_MODEL "$MODEL"
    set_env LLM_STRIP_RESPONSE_FORMAT 1
    set_env LLM_API_KEY "$LLM_API_KEY"
    ok "$ENV_FILE: hosted model $MODEL at $URL (key stored, never printed)"
    ;;
  stub)
    CFG_PROVIDER=openai-compatible; CFG_BASE_URL="http://provider-stub:8080/v1"; CFG_MODEL=stub; CFG_STRIP=1
    set_env LLM_PROVIDER openai-compatible
    set_env LLM_BASE_URL "$CFG_BASE_URL"
    set_env LLM_MODEL stub
    set_env LLM_STRIP_RESPONSE_FORMAT 1
    ok "$ENV_FILE: the in-cluster test double (no model, no key)"
    ;;
  *) die "unknown mode $MODE" ;;
esac

say "hand it to the gateway"
kubectl -n "$NS" create configmap llm-config \
  --from-literal=LLM_PROVIDER="$CFG_PROVIDER" \
  --from-literal=OLLAMA_URL="$CFG_OLLAMA_URL" \
  --from-literal=OLLAMA_MODEL="$CFG_OLLAMA_MODEL" \
  --from-literal=LLM_BASE_URL="$CFG_BASE_URL" \
  --from-literal=LLM_MODEL="$CFG_MODEL" \
  --from-literal=LLM_STRIP_RESPONSE_FORMAT="$CFG_STRIP" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

if [ "$NEED_KEY" = "1" ]; then
  kubectl -n "$NS" create secret generic llm-api-key \
    --from-literal=LLM_API_KEY="$LLM_API_KEY" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  ok "llm-api-key Secret updated (only the gateway mounts it)"
else
  kubectl -n "$NS" delete secret llm-api-key --ignore-not-found >/dev/null 2>&1 || true
fi

# The config is read at startup; a ConfigMap change alone leaves the old model.
kubectl -n "$NS" rollout restart deploy/gateway >/dev/null
kubectl -n "$NS" rollout status deploy/gateway --timeout=300s >/dev/null
ok "gateway restarted with the new choice"

if [ -n "$EVAL" ]; then
  say "the live evals (real model calls — this takes a while)"
  kubectl -n "$NS" exec deploy/agent -c agent -- python -m app.agent.evals --live || true
else
  say "next"
  info "./scripts/demo.sh                                  # a run through the model"
  info "kubectl -n $NS logs deploy/gateway | grep llm.call   # which model ran, per call"
  info "$0 --eval                                        # score it against the evals"
fi
