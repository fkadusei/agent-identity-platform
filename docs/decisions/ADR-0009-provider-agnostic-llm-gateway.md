# ADR-0009: Provider-agnostic LLM, with an identity-authenticated gateway

- **Status:** Accepted — **implemented** in `app/gateway/`: the gateway serves
  HTTPS with its own X.509-SVID and requires a client SVID (SPIFFE mTLS), so the
  agent holds no model credential and reaches the model only through it.
- **Date:** 2026-09-12
- **Related:** ADR-0001

## Context

A hosted LLM requires an API key — a static credential, the very thing this
platform removes. Teams also change models often, so the design must not be tied
to one vendor. The concepts demo resolved this by defaulting to a local model
and treating a hosted key as a documented exception.

## Decision

1. Treat the LLM as a swappable dependency behind the **OpenAI-compatible Chat
   Completions API** (implemented by virtually every provider). Default to a
   **local model** (Ollama), which needs no credential at all.
2. In Phase 2, introduce an **LLM gateway inside the trust domain** that
   authenticates the agent by its **SPIFFE identity** and holds the provider
   key. The agent returns to holding zero secrets; the key's blast radius shrinks
   to one auditable component.

## Consequences

- Changing providers is configuration, not code.
- The "zero credentials" claim stays literally true by default.
- The gateway becomes a component to operate and monitor (per-agent model/spend
  policy, logging).

## Alternatives considered

- **Hard-code a single provider** — rejected: dates the platform and adds a
  secret to every agent.
- **Give every agent the provider key** — rejected: multiplies the blast radius
  of the last remaining secret.
