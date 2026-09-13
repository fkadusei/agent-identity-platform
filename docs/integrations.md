# Integrations

The tools are a thin interface over a **backend**. Swapping the in-process
simulator for a real system is a configuration change, not a code change — and the
policy layer above never knows the difference.

```
agent ──▶ tools ──▶ Backend ──┬── SimulatorBackend   (in-process synthetic data)
                              └── HttpBackend        (a sandbox, or the real vendor)
```

## Choosing a backend

| Env | Effect |
| --- | --- |
| `TOOLS_BACKEND=simulator` (default) | use the in-process synthetic data |
| `TOOLS_BACKEND=http` | call a REST API |
| `SANDBOX_BASE_URL` | base URL for the HTTP backend (default `http://sandbox:8090`) |
| `SANDBOX_TOKEN` | optional bearer token sent to it |

The kind deployment sets `TOOLS_BACKEND=http` and points at the in-cluster
**sandbox** service, so the HTTP path is exercised end to end (the demo and the
attack suite run through it). Set `TOOLS_BACKEND=simulator` to go back to
in-process.

## The REST contract

The HTTP backend speaks exactly this, and nothing else. Every request carries
`X-Tenant` (from the caller's identity — see [`tenancy.md`](tenancy.md)):

| Tool | Request |
| --- | --- |
| `crm.customer.read` | `GET /customers/{id}` |
| `privacy.pii.read` | `GET /customers/{id}/pii` |
| `crm.orders.list` | `GET /customers/{id}/orders` → `{"orders": [...]}` |
| `tickets.read` | `GET /tickets/{id}` |
| `tickets.reply.draft` | `POST /tickets/{id}/drafts` `{"body": "..."}` |
| `refunds.quote` | `GET /orders/{id}/refund-quote` |
| `refunds.issue` | `POST /orders/{id}/refunds` `{"amount": 25}` |

A `404` maps to "not found" (the same result the simulator gives); any other
non-2xx raises, and the enforcement core turns that into a tool error — never a
silent success.

## The sandbox service

`app/sandbox/` is the simulators exposed over that contract. It stands in for a
real CRM/orders/payments/ticketing sandbox so the integration path is real
without vendor credentials:

```bash
kubectl -n agent-platform port-forward svc/sandbox 8090:8090
curl -s localhost:8090/customers/c-100
```

## Pointing at a real sandbox

Set `SANDBOX_BASE_URL` (and `SANDBOX_TOKEN`) to your provider's sandbox and the
tools use it — e.g. a payments sandbox for `refunds.issue`, a CRM sandbox for
`crm.*`. If the vendor's shape differs, write a backend rather than editing the
tools:

```python
class MyCrmBackend:            # implement the methods in app/tools/backends.py
    def get_customer(self, customer_id): ...
```

```python
tools = build_tools(MyCrmBackend())     # the catalogue takes any backend
```

Nothing above the backend changes: the tool names, the policy (`policy/authz.rego`
keys on the tool name and the caller's identity), the approvals and the audit
trail all stay exactly as they are. That is the point — **authorization is
independent of the integration**.

## Why a seam at all

- The policy decision is about *who* may call *which tool* — it must not depend on
  how the tool reaches its data.
- A vendor outage or shape change is contained to one class.
- Tests run against the simulator (fast, deterministic) while a staging
  environment runs against the sandbox and production against the vendor.

## Notes

- The sandbox is **synthetic data only** — no real personal data leaves the
  cluster (see [`data-handling.md`](data-handling.md)).
- `HttpBackend` uses a single `httpx.Client`; a busy deployment would configure
  connection limits and retries.
