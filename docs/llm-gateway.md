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

## Limitations

- **In-memory, single-replica.** The counters live in the gateway process, so a
  restart resets them and replicas do not share state. For HA, move them to the
  same Postgres the rest of the platform uses (see
  [`data-stores.md`](data-stores.md)) — the `Limiter` interface is the seam.
- **Estimate, not metering.** The token count is approximate; a provider that
  reports `usage` is exact for hosted models, Ollama is estimated.
- **One gateway, one budget per caller.** Per-tenant or per-tool budgets would
  key on more than the SPIFFE ID.
