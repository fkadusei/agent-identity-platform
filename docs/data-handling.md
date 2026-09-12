# Data Handling

**The rule, stated once: this project uses synthetic data only. Never real
customer, card, or personal data — in git, tests, logs, traces, prompts, or
fixtures.** A reference platform has nothing real to protect, and that is a
feature.

---

## Data classification

| Class | Examples | Where it may appear |
|---|---|---|
| **Synthetic** | generated customers, orders, refunds | everywhere (git, tests, logs, prompts) |
| **Sensitive (PII)** | names, emails, addresses | never; only synthetic stand-ins |
| **Card data (PAN)** | card numbers | **never, ever** — out of PCI scope |
| **Secrets** | API keys, tokens, passwords | only in a secret manager / local `.env`; never in git or logs |

## Personal data (PII)

- The platform simulates PII but never stores or transmits real PII.
- Tools that would touch PII are **tagged** (`pii: true`) and gated by policy —
  in the demo model, `privacy.pii.read` requires approval.
- Audit records store **references** (identifiers, decisions), not raw personal
  data.
- Redaction runs **before** anything is logged, traced, or sent to a model.

## Card data and PCI

- The payments/refunds path handles only **opaque, non-PAN tokens**.
- The project is deliberately **out of PCI card-data scope**; nothing in the
  codebase should ever receive, store, log, or forward a card number.
- Real sandbox integrations (later) must return test-mode data only.

## The LLM boundary

- **Default:** a local model (Ollama) — no data leaves the machine.
- **Hosted:** only via the **LLM gateway** (Phase 2), which authenticates the
  agent by its SPIFFE identity, applies redaction before egress, and is where
  provider retention settings are enforced.
- Prompts must contain only synthetic or already-redacted data.

## Redaction rules

Before a record is emitted (log, trace, audit, or prompt), remove or mask:

- `Authorization` headers and anything matching a bearer/JWT shape
- `access_token`, `refresh_token`, `assertion`, `client_assertion`, `jti`
- API keys and database connection strings with passwords
- Direct identifiers when a reference suffices

## Retention

- Local development data is disposable; the cluster is torn down with
  `teardown.sh`.
- Audit records are retained for a defined window in production and contain
  references, not raw personal data.

## Verification

- **Redaction tests** assert that emitted records contain no tokens or PII
  fields.
- **Secret scans** (`scripts/scan-secrets.sh`, CI) assert no secrets in the tree
  or history.
- **Policy tests** assert PII-tagged tools require approval.
