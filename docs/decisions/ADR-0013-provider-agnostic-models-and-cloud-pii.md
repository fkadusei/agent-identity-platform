# ADR-0013: Provider-agnostic models — and what a cloud model may see

- **Status:** Accepted
- **Date:** 2026-10-03
- **Related:** ADR-0006 (synthetic data), ADR-0009 (provider-agnostic LLM + identity-authenticated gateway), ADR-0012 (transport identity), S17

## Context

The gateway (ADR-0009) was built to speak to any OpenAI-compatible provider, but
only the local Ollama path had ever run. Two defects sat in the hosted branch,
both found by reading it: the gateway forwarded the caller's request verbatim and
the agent sends no `model`, so a provider received none and failed; and the
formal `response_format` hint was forwarded to providers that might reject it.
Neither was exercised, so neither was noticed.

Fixing them raised the real question. The default is a **local** model on purpose:
when the agent reads personal data under an approval, nothing leaves the machine.
Point the gateway at a cloud provider and that changes — and **S19/S22** made it
concrete: a multi-step run feeds the previous tool result back into the prompt, so
a run that read PII as step 1 would send it to whichever model the gateway points
at.

## Decision

**Finish the provider-agnostic path, and make a cloud provider opt-in — with the
fine control left to policy.**

- The gateway forwards the **resolved model** (already computed for the audit) and
  fails clearly when a hosted provider has no `LLM_MODEL`. `LLM_STRIP_RESPONSE_FORMAT=1`
  drops `response_format` for a strict provider. Both are covered by tests.
- An in-cluster **stub** OpenAI-compatible provider (`provider-stub`) is deployed by
  `setup.sh`, so the hosted branch is exercised end to end without anyone's cloud key.
- A cloud provider is **opt-in** (you set `LLM_PROVIDER`/`LLM_BASE_URL`/`LLM_API_KEY`);
  local remains the default.
- The control that decides *what* a cloud model may see — "this tenant, or this tool,
  may only use a local model" — belongs in **policy**, not the gateway: the gateway
  sees a prompt, not the tool that produced it, so it cannot make that judgement. The
  rule is documented here and in `docs/llm-gateway.md` as **future work**, and not
  pretended to exist.

## Consequences

- The platform is honestly provider-agnostic: local and hosted models are both real,
  tested paths, and "swap models" no longer means "swap local models".
- Local-by-default keeps PII on-premises unless an operator deliberately opts into a
  cloud provider. That is a posture, not a proof: opting in is the moment the S22/T11
  leak becomes reachable, and it is the operator's decision, recorded here.
- The gateway carries one more configuration surface (`LLM_*`), rendered from `.env`
  into `llm-config` by `setup.sh`.
- A real cloud run still needs a key we do not keep in the repository; the stub makes
  the code path verifiable without one.

## Alternatives considered

- **Local-only forever.** Rejected: the plumbing existed and the defects were real; a
  platform that claims provider-agnosticism should be able to prove it.
- **Gate by tool in the gateway.** Rejected: the gateway never sees the tool — only the
  assembled prompt. A control there would be fiction. Policy is where the platform
  already decides per tool and tenant.
- **Block cloud entirely by default with an allow-list.** Deferred, not rejected: the
  policy rule is the natural home for it (a per-tenant/per-tool "local only"), and is
  the named next step rather than a half-built switch here.
