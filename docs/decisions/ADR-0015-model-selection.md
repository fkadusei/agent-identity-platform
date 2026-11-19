# ADR-0015: Choosing a model — local-first, OpenAI-compatible, and a no-model stub

- **Status:** Accepted — **implemented** in `scripts/use-model.sh` and the model
  fallback in `scripts/setup.sh`.
- **Date:** 2026-11-19
- **Related:** ADR-0009 (provider-agnostic LLM), ADR-0013 (provider-agnostic
  models and cloud PII)

## Context

ADR-0009 made the model a swappable dependency behind the **OpenAI-compatible
Chat Completions API**, with a local model by default and the gateway holding the
only provider key. But "swappable" still meant editing `.env` by hand, and a first
run assumed a multi-gigabyte local model. For a repository someone downloads and
runs, that is the difference between "try it" and "configure it for an hour".

## Decision

Model selection is a **gateway concern**, exposed as one guided script
(`scripts/use-model.sh`) with three standards-based modes:

1. **Local** (default) — Ollama, discovered from `/api/tags` and chosen from a
   list. Data stays on the machine.
2. **Hosted** — any **OpenAI-compatible** endpoint (OpenAI, Groq, Together, vLLM,
   …), configured by base URL, model and key. The gateway already speaks that
   standard; there is no bespoke adapter per vendor.
3. **None** — the in-cluster `app/provider_stub`, a deterministic
   OpenAI-compatible test double, so the whole demo runs with no model download and
   no key.

The choice is written to the gitignored `.env`, rendered into the `llm-config`
ConfigMap, and the gateway restarts (it reads the config at startup). The provider
key, when used, lives only in `.env` and the `llm-api-key` Secret the gateway
mounts; the agent holds no model credential. `setup.sh` falls back to the stub
when the default local model is unreachable, so a first run never depends on a
download — and `.env` is left untouched.

## Consequences

- A stranger can clone and run with no model; a privacy-conscious user gets local
  by default; a team can point at its own provider without a code change.
- One place names the model, and no image rebuild is involved.
- The stub is a **test double**, not a model: it parses the task and returns a
  plausible tool decision. It proves the wiring, not model quality.
- The standards boundary is the OpenAI-compatible API; the local path translates
  to Ollama behind the gateway.

## Alternatives considered

- **Require a local model** — rejected: a multi-GB download as the price of a
  first look.
- **Bespoke per-provider adapters** — rejected: a standard already exists and
  every provider implements it.
- **Let the agent choose or hold the provider** — rejected: it reintroduces the
  credential the platform removes (ADR-0009).
- **Hard-code a model in the manifest** — rejected: a swap would need an edit and
  a rebuild, and the choice would not be visible in one place.
