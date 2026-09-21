# LLM gateway

The gateway (`app/gateway/`) is the **only** component that talks to a model
provider. It holds the provider key, so the agent needs no model credential at
all — and because it is the single egress, it is also the right place to cap what
an agent can spend.

## Two identities, two jobs

| Proof | Proves | Used for |
| --- | --- | --- |
| **SPIFFE mTLS** (X.509-SVID) | *a* workload in our trust domain is calling | the connection is refused otherwise |
| **JWT-SVID** (`Authorization: Bearer …`) | *which* workload is calling | keying the per-agent limits |

mTLS alone only says "some workload"; the JWT-SVID names the caller, and the
gateway verifies it against SPIRE's JWKS. The limits are keyed on the resulting
SPIFFE ID — never on a header the caller could set freely, or the limit would be
trivial to bypass.

## Limits

| Env | Meaning | Default |
| --- | --- | --- |
| `LLM_RATE_LIMIT_PER_MINUTE` | requests per minute, per caller (burst guard) | 0 (unlimited) |
| `LLM_TOKEN_BUDGET_PER_DAY` | estimated tokens per day, per caller (cost guard) | 0 (unlimited) |

Both are **per caller** and independent: one agent hitting its limit does not
affect another.

On exceed the gateway returns **429** with a `Retry-After` header and writes an
`llm.limited` audit event naming the caller and the reason:

```json
{"event": "llm.limited", "caller": "spiffe://acme.com/ns/agent-platform/sa/agent",
 "reason": "rate limit reached (60 requests/minute)"}
```

Tokens are counted from the provider's `usage` when it reports it, and otherwise
estimated (~4 characters per token). The estimate is deliberately cheap and
provider-agnostic; it is a spend guard, not billing.

## Try it

With a low limit, the second call is refused:

```bash
# in the gateway's env: LLM_RATE_LIMIT_PER_MINUTE=1
./scripts/demo.sh        # the first agent run succeeds, later ones get 429
kubectl -n agent-platform logs deploy/gateway | grep llm.limited
```

Unit tests cover the limiter directly (`app/gateway/tests/test_limits.py`) and the
429 path (`app/gateway/tests/test_gateway.py`).

## Durable counters

The counters live in Postgres when a database is configured (the same
`DATABASE_URL`/`PG*` as the rest of the platform), and in memory otherwise:

| Backend | When | Survives a restart | Shared across replicas |
| --- | --- | --- | --- |
| `PostgresLimiter` | a database is configured | yes | yes |
| `Limiter` (in-memory) | no database | no | no |

The rate window is one row per `(caller, minute)` and the budget one row per
`(caller, day)`, both upserted atomically — so concurrent calls cannot both see a
stale count. Old rows are cleaned up opportunistically.

## Limitations

- **Estimate, not metering.** The token count is approximate; a provider that
  reports `usage` is exact for hosted models, Ollama is estimated.
- **One budget per caller.** Per-tenant or per-tool budgets would key on more
  than the SPIFFE ID.
- **A small over-shoot is possible.** The budget check reads, then the call
  charges; two calls in flight together can slightly exceed the budget. It is a
  spend guard, not an accounting ledger.

## Swapping models

The model is named in exactly one place, and swapping it does not touch a manifest or
rebuild an image:

```bash
./scripts/use-model.sh qwen3:30b-a3b            # swap
./scripts/use-model.sh llama3.2:3b              # and back
./scripts/use-model.sh --eval qwen3:30b-a3b     # swap, then run the live evals
```

The script records the choice in `.env` (so re-running `setup.sh` keeps it), re-renders
the `llm-config` ConfigMap from those values, and restarts the gateway — the config is
read at startup, so a ConfigMap change on its own would leave the old model running.

**Which model?** The demo's portable default is `qwen3:30b-a3b`; `llama3.2:3b` is a
quarter of the size and much quicker if you want a snappier demo. The difference is not
cosmetic — measured with the eval suite on one machine:

| Model | Eval score | Notes |
| --- | --- | --- |
| `qwen3:30b-a3b` (and its local derivatives) | **6/8** | the misses are the two hardest cases |
| `llama3.2:3b` | 4–5/8 | fails *"PII is refused for a support rep"* — a security guardrail, not a nicety |

Small local models vary run to run, so treat those as indicative rather than exact.
What matters is the class of failure: the 3B picks a plausible tool when it should
refuse, and the guardrail suite is how you see it before your users do.

### Two things a swap taught us

- **A thinking model puts its answer somewhere else.** With `format: json`, a Qwen3-style
  model returns `response` *empty* and the JSON in `thinking` — so the agent reported an
  unparseable reply while the model had answered correctly (1/8 on the evals). The
  gateway now asks for `think: false` and falls back to `thinking`, which took the same
  model from 1/8 to 6/8.
- **The audit had been naming the wrong thing.** `llm.call` recorded the model the
  *caller* asked for, and the agent asks for none — so the field meant "which model
  did someone request", with an empty answer, instead of *"which model decided this"*.
  It now records the model resolved for the call, which is what makes a swap visible in
  the trail:

```
"event": "llm.call", "provider": "ollama", "model": "qwen3-warden-ctx16k:latest",
"caller": "spiffe://acme.com/ns/agent-platform/sa/agent"
```

Checking a swap is therefore three commands: the audit line above after any run,
`./scripts/demo.sh` for the end-to-end path, and `use-model.sh --eval <model>` for a score.
The suites that do not involve a model (`role-tools.sh`, `attack-tests.sh`,
`tenancy-tests.sh`) are unaffected and should stay green.

Cloud and native providers are deliberately not wired yet — see **S17** in
[`backlog.md`](backlog.md) for the two defects that stand between here and there.
