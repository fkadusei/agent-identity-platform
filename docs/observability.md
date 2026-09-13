# Observability

The platform answers the same question the audit log does — *which agent, acting
for which user, did what, and what did policy decide?* — but as a **distributed
trace**, end to end. Attribution is the point: a span is only useful here if it
carries the identity.

```
agent ──▶ gateway ──▶ (model)          every service exports OTLP/HTTP
   │                                        │
   └──▶ tools ──▶ OPA / approvals / audit   ▼
                                     otel-collector ──▶ Jaeger (traces)
                                            └──▶ :8888 (Prometheus metrics)
```

## What is traced

| Span | Emitted by | Identity attributes |
| --- | --- | --- |
| `POST /run`, `POST /tools/{tool_name}`, … | FastAPI auto-instrumentation | — |
| `policy.decision` | `app/tools/enforcement.py` | `spiffe_id`, `sub`, `tool`, `decision`, `reason` |
| `llm.provider_call` | `app/gateway/app.py` | `provider`, `model` |
| `… http send` / `… http receive` | httpx instrumentation | — (propagates the trace across services) |

The `policy.decision` span is the interesting one: it records the agent's SPIFFE
ID, the human it acts for, the tool, the decision, and the reason — for example:

```
policy.decision  spiffe_id=spiffe://acme.com/ns/agent-platform/sa/agent
                 sub=alice tool=refunds.issue
                 decision=require_approval
                 reason=requires manager approval: refund of 200 is above the
                        auto-approval limit of 50
```

Because httpx propagates the trace context, one user request produces a single
trace spanning **agent → gateway → tools → api** (25 spans in the refund flow).

## Seeing it

```bash
./scripts/demo.sh          # generate some traffic
./scripts/show-trace.sh    # print the richest recent trace + identity attributes
```

For the full UI:

```bash
kubectl -n agent-platform port-forward svc/jaeger 16686:16686
# open http://localhost:16686
```

## Metrics and dashboards

Traces answer "what happened in this one request"; metrics answer "is the
platform healthy right now". Both are live.

The API exposes platform counters at `/metrics` (`app/common/metrics.py`):

| Metric | Meaning |
| --- | --- |
| `agent_platform_logins_total{result}` | logins, ok vs failed |
| `agent_platform_audit_events_total{event}` | every audited event — policy decisions (`tool.allowed`/`tool.denied`/`tool.approval_required`), approvals, user administration |
| `agent_platform_approvals_pending` | the approval backlog |
| `agent_platform_http_requests_total{method,route,status}` | request rates by route template |

The audit-derived counters are the interesting ones: because every service
forwards its audit events to the API, one instrumentation point covers policy
decisions and admin actions across the whole platform — so the dashboard and the
audit log cannot drift apart.

**Prometheus** (`deploy/kind/manifests/observability/prometheus.yaml`) scrapes
the API, the OTel collector and OPA. **Grafana**
(`.../grafana.yaml`) is provisioned with the Prometheus datasource and a
dashboard, both from ConfigMaps:

```bash
kubectl -n agent-platform port-forward svc/grafana 3000:3000
# open http://localhost:3000 — the "Agent Identity Platform" dashboard is there
```

Panels: logins by result, policy decisions, approvals pending, requests by
route, spans exported, failed span exports. Anonymous viewer access is a demo
setting; a real deployment enables auth and puts it behind ingress.

To query without Grafana:

```bash
kubectl -n agent-platform port-forward svc/prometheus 9090:9090
curl -s 'localhost:9090/api/v1/query?query=agent_platform_audit_events_total'
```

## Design notes

- **Telemetry is optional.** With `OTEL_EXPORTER_OTLP_ENDPOINT` unset, every
  helper in `app/common/telemetry.py` is a no-op and the services behave exactly
  as before. The collector is the only stable export target, so the backend
  (Jaeger today, a managed backend later) can change without touching services.
- **Never trace the payload.** Spans carry identity and decision metadata only —
  never prompts, arguments, or tool output. This matches the audit rule in
  [`data-handling.md`](data-handling.md).
- **Demo-scale Jaeger.** `jaegertracing/all-in-one` stores traces in memory with
  no auth. A real deployment uses a persistent or managed backend behind the
  collector.
