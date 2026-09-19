# agent-platform Helm chart

Deploys the platform's own workloads — `api`, `tools`, `agent`, `gateway`, OPA,
and (optionally) the observability stack — from values instead of the
kind-specific raw manifests in `deploy/kind/`.

## Prerequisites

Two things are environment-specific and **not** templated here. Provide them
wherever they live and point the values at them:

1. **SPIRE** — a SPIRE agent on each node exposing the Workload API socket and
   the trust bundle. Every service with `spiffe: true` (`api`, `tools`, `agent`,
   `gateway`) mounts:
   - the socket from `spire.agentSocketHostPath` (a `hostPath` on kind; use a
     CSI driver or a per-node agent in production);
   - the bundle from the `spire.bundleConfigMap` ConfigMap.

   SPIRE registration entries are keyed on **namespace + service account**, so the
   chart creates a ServiceAccount per SPIFFE service. Register **all four** —
   `api` and `tools` hold SVIDs since S7, and a missing entry means the pod cannot
   start (it fetches its identity at boot). `scripts/setup.sh` has the exact
   `spire-server entry create` calls.

   A service with a `spiffePort` serves two listeners: that port speaks SPIFFE (an
   SVID on both sides, and a named caller on its machine routes), while `port`
   stays for the browser and tooling, which cannot hold an SVID. The pods also
   carry `config.linkerd.io/skip-inbound/outbound-ports: "8443"` when `mesh.inject`
   is on — without it the mesh terminates the connection and the peer's SVID never
   reaches the server (ADR-0012).

2. **Keycloak** — the OIDC realm (issuer, clients, token exchange). Point
   `auth.issuer` at it. The realm template lives in
   `deploy/kind/manifests/keycloak/`.

Also required as existing Secrets (synced by External Secrets in production):

| Secret | Keys |
| --- | --- |
| `auth.existingSecret` (`platform-secrets`) | `PORTAL_SECRET`, `ADMIN_CLIENT_SECRET`, `DEMO_CLI_SECRET`, `MANAGER_CLI_SECRET` |
| `llm.existingSecret` (`llm-api-key`) | `LLM_API_KEY` (optional; only the gateway reads it) |

And the policy bundle ConfigMap (`opa.bundleConfigMap`, default `opa-bundle`),
built with `scripts/build-bundle.sh`.

## Install

```bash
# 1. build the policy bundle ConfigMap (versioned; sign it in production)
./scripts/build-bundle.sh
kubectl -n agent-platform create configmap opa-bundle \
  --from-file=authz.rego=dist/bundle/authz.rego \
  --from-file=data.json=dist/bundle/data.json \
  --from-file=.manifest=dist/bundle/.manifest \
  --dry-run=client -o yaml | kubectl apply -f -

# 2. install the chart
helm install agent-platform deploy/helm/agent-platform \
  --namespace agent-platform --create-namespace \
  --set image.registry=ghcr.io/fkadusei --set image.tag=v0.1.0
```

Render without installing:

```bash
helm template agent-platform deploy/helm/agent-platform
helm lint deploy/helm/agent-platform
```

## What the values control

| Value | Purpose |
| --- | --- |
| `image.registry` / `repository` / `tag` | image location (empty registry = locally loaded images) |
| `services.<name>.replicas` | per-service replica count |
| `services.<name>.env` | per-service environment (secrets referenced by `secretKeyRef`) |
| `services.<name>.spiffe` | mount the Workload API socket + trust bundle |
| `spire.*` | socket/bundle paths and the node socket `hostPath` |
| `auth.*` | issuer, audience, SPIFFE IDs, secret name, signup toggle |
| `llm.*` | gateway URL and provider settings |
| `opa.*` | OPA image and the bundle ConfigMap |
| `database.url` | Postgres DSN for durable approvals + run checkpoints (empty = in-memory) |
| `mesh.inject` | annotate pods for Linkerd injection (mTLS on every in-cluster hop) |
| `observability_stack.*` | enable/disable the collector, Jaeger, Prometheus, Grafana |
| `resources` | default requests/limits for every workload |
| `ingress.*` | host, class, TLS, annotations |

## Differences from the kind manifests

- **No namespace object** — the chart expects the namespace to exist (use
  `--create-namespace`).
- **No SPIRE, Keycloak, or realm** — prerequisites, as above.
- **No bundle generation** — the bundle is a signed build artifact.
- The ingress fronts only the **api**; the gateway stays mTLS-only.
