# Transport security (TLS/mTLS)

Two layers, and between them every in-cluster hop is mutually authenticated.

| Layer | Covers | Identity |
| --- | --- | --- |
| **App-level SPIFFE mTLS** | `agent → gateway` (the model call) | the workloads' X.509-SVIDs |
| **Service mesh (Linkerd)** | every other in-cluster hop | the mesh's workload identity |

## Why both

The **app layer** uses SPIFFE because the agent→gateway hop is where a static
model credential would otherwise live — the gateway proves it is the gateway, and
the agent proves it is the agent, with SVIDs fetched from SPIRE. That is the
platform's identity story, applied to its most sensitive hop.

The **mesh** covers everything else — `api`, `tools`, `agent`, `sandbox`,
**Keycloak**, **OPA**, Postgres, and the observability stack — transparently. A
mesh is the right tool here for three reasons:

- the services (and third-party ones like Keycloak and OPA) need no TLS code;
- it covers the hops you would forget, including telemetry and the IdP;
- it leaves the **browser edge alone**: the UI reaches the API over ordinary TLS
  and authenticates with bearer tokens, which is what the browser can actually do.

## What is covered

```
browser ──TLS──▶ ingress/api         (edge: server TLS + bearer tokens)
                     │
   ┌─────────────────┴──────────── mesh mTLS ────────────────────────────┐
   │  api ⇄ agent ⇄ tools ⇄ sandbox ⇄ opa ⇄ keycloak ⇄ postgres           │
   │  + otel-collector ⇄ jaeger ⇄ prometheus ⇄ grafana                    │
   └──────────────────────────────────────────────────────────────────────┘
   agent ──SPIFFE mTLS──▶ gateway ──▶ model provider
```

## Verify

```bash
./scripts/tls-check.sh
```

It reports the mesh control plane's health and every edge, and fails if any edge
is not `SECURED`:

```
tools            sandbox          agent-platform   agent-platform   √
prometheus       keycloak         linkerd-viz      agent-platform   √
...
All in-cluster edges are mTLS.
```

## Setup

`scripts/setup.sh` installs Linkerd (if the CLI is present) and annotates the
namespace for injection — so every pod gets a proxy and every hop is mTLS. The
Helm chart takes `mesh.inject` to annotate the pods it deploys.

Without the CLI, setup skips the mesh and the platform runs in plaintext — the
app-level SPIFFE mTLS on agent→gateway still applies.

## What this does and does not give you

- **Encryption + authenticated transport** between pods — yes. Traffic on the
  wire is encrypted and each side is authenticated by the mesh.
- **Authorization** — no. The mesh proves *which workload* is talking; it does
  not decide whether the call is allowed. That stays in the app: bearer tokens
  (audience + `azp`), OPA policy, and tenant scoping.
- **The browser edge** — not covered here. Production terminates TLS at the
  ingress (see the chart's `ingress.*` values); the demo uses `port-forward`.
- **Egress to the model provider** — the gateway reaches a hosted provider over
  the provider's own TLS; the local default (Ollama) stays in-cluster.

## Notes

- Linkerd's identity is the mesh's own, not SPIFFE. The app layer keeps SPIFFE
  for the identity-sensitive hop; a SPIFFE-native mesh (or SPIFFE-aware mTLS
  everywhere) is a further step.
- The mesh proxy is a native sidecar (an `initContainer` with `restartPolicy:
  Always`), so `kubectl exec` may need `-c <container>` to pick the app.
- Linkerd needs Kubernetes 1.29+ and the Gateway API CRDs (installed by setup).
