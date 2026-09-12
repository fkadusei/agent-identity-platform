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

## Metrics

The collector exposes its own Prometheus metrics (including
`otelcol_exporter_sent_spans`) on `:8888`:

```bash
kubectl -n agent-platform port-forward svc/otel-collector 8888:8888
curl -s localhost:8888/metrics | grep otelcol_exporter_sent_spans
```

Point a Prometheus scrape config at `otel-collector.agent-platform:8888/metrics`
to collect them. Service-level metrics (counters on `policy.decision` outcomes)
are the natural next step; today the audit stream and traces carry the signal.

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
