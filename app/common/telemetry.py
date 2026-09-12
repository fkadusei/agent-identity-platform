"""OpenTelemetry setup: traces that carry the identity, exported over OTLP/HTTP.

The point of tracing here is not just latency — it is **attribution**. Every
span that matters records *which agent*, *which user*, and *which decision*, so a
trace answers the same question the audit log does, but visually and end to end
(agent → gateway → tools → policy).

Tracing is optional: if `OTEL_EXPORTER_OTLP_ENDPOINT` is unset, everything here
is a no-op and the services behave exactly as before.
"""
from __future__ import annotations

import os
from contextlib import contextmanager

from opentelemetry import trace

_provider = None
_instrumented = False


def enabled() -> bool:
    return bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))


def setup_telemetry(service_name: str):
    """Configure the tracer provider and auto-instrumentation (idempotent)."""
    global _provider, _instrumented
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint or _provider is not None:
        return _provider

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
        )
    )
    trace.set_tracer_provider(provider)
    _provider = provider

    if not _instrumented:
        _instrumented = True
        try:  # outbound calls propagate the trace across services
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

            HTTPXClientInstrumentor().instrument()
        except Exception:  # noqa: BLE001 - instrumentation is best effort
            pass
    return provider


def instrument_fastapi(app) -> None:
    """Auto-instrument a FastAPI app (one server span per request)."""
    if not enabled():
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except Exception:  # noqa: BLE001
        pass


@contextmanager
def span(name: str, **attributes):
    """A span carrying identity attributes (None values are dropped)."""
    tracer = trace.get_tracer("agentnhi")
    clean = {k: v for k, v in attributes.items() if v is not None}
    with tracer.start_as_current_span(name, attributes=clean) as current:
        yield current
