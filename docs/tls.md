# Transport security (TLS/mTLS)

Two layers, and the boundary between them is deliberate (ADR-0012):

| Layer | Covers | Identity |
| --- | --- | --- |
| **App-level SPIFFE mTLS** | every hop between workloads **we own**: `agent ⇄ gateway`, `agent ⇄ tools`, `agent ⇄ api` | the workloads' X.509-SVIDs, and a named caller (a JWT-SVID) on the machine routes |
| **Service mesh (Linkerd)** | everything else: `keycloak`, `opa`, `postgres`, `sandbox`, the observability stack — and `/metrics` | the mesh's own workload identity |

Both are required. Our SPIFFE port **skips the mesh proxy** in both directions
(`config.linkerd.io/skip-inbound-ports` / `skip-outbound-ports: "8443"`), because a
proxy that terminated the connection would prove *its* identity and hide the peer's
SVID from our server. Everything else stays on the mesh, so no hop went plaintext
when SPIFFE was introduced — a measurement, not an assumption: uninjecting our pods
was tried and rejected, because a client without a proxy loses encryption on **all**
its outbound hops, not just the ones being retired.

## Why SPIFFE here, and not everywhere

The **hops we own** are the ones where "who is calling" has to be answerable at the
application layer. SVIDs give both ends a workload identity, and the machine routes
require the caller to be *named* — the agent creates approvals, the tool server
verifies them, and both may ingest audit. Before this, a hop "being encrypted" said
nothing about who the peer was, and `/audit/events` took no credential at all, so
any meshed pod could forge an audit event.

The **mesh** covers the components that cannot present a workload identity:
**Keycloak, OPA and Postgres** are third-party products, and the **sandbox** stands
in for a vendor's system — a real vendor has no SVID, so requiring one would model
the wrong thing. A mesh is the right tool for them for three reasons:

- those products need no TLS code, and no certificate distribution of our own;
- it covers the hops you would forget, including telemetry and `/metrics`;
- it leaves the **browser edge** to the ingress (S7b): a browser holds no SVID and
  cannot be meshed, so the UI reaches the API over ordinary TLS at an ingress and
  authenticates with bearer tokens — which is what a browser can actually do.

Because the mesh terminates TLS for it, **Keycloak's own listener is HTTP even in
production mode** (S4). That is its documented deployment shape — `--http-enabled`
is for a server "fronted by a TLS termination" — and a second, in-mesh HTTPS
listener would be redundant rather than more secure. What changed in S4 is that
Keycloak no longer needs a *development* mode to be reachable: `start-dev`, its
ephemeral database, and the read-only-rootfs exception are all gone.

## What is covered

```
browser ──TLS──▶ ingress ──▶ api:8080        (edge: TLS at the ingress, bearer tokens)
                                │
        ┌───────────────────────┴──────── mesh mTLS ─────────────────────────┐
        │  keycloak ⇄ opa ⇄ postgres ⇄ sandbox   +   otel ⇄ jaeger ⇄ prom    │
        └────────────────────────────────────────────────────────────────────┘

   agent:8443 ⇄ tools:8443      SPIFFE: both sides' SVIDs, caller named
   agent:8443 ⇄ api:8443        SPIFFE
   api:8443   ⇄ agent:8443      SPIFFE
   agent:8443 ─▶ gateway:8443 ─▶ model provider   SPIFFE
```

`api`, `tools` and `agent` each serve **two listeners**: the SPIFFE one for
workloads, and their original port for callers that cannot hold an SVID — the
browser, and the verification scripts standing in for a user. That second listener
is a different trust domain, and it is fronted by the ingress that terminates the
browser's TLS: the first line of the diagram is real on kind, not a plan (S7b).

`gateway` is the exception, and it is the strictest case: its **only** listener is
mTLS, so nothing outside a workload can reach it at all. That has a consequence for
operations, not for callers — a kubelet probe has no SVID to present, so it cannot
check the serving listener, and asking whether the socket is open is answered by a
hung process too. The gateway therefore serves **`/healthz` and nothing else** on a
separate plaintext port (`health_port`), started only once its SVID is loaded. It is
not the gateway's app on a second port: the model endpoint stays behind mTLS (S16).

The **edge** is `ingress-nginx` with a certificate `setup.sh` generates (a CA in
the gitignored `.edge/`, the leaf named `localhost` with the extensions strict
clients require). It fronts `api:8080` and nothing else: the gateway is
deliberately not exposed — it is mTLS-only and only the agent should reach it.

One residual, stated rather than hidden: the ingress controller carries **no
sidecar**, so its hop to `api:8080` is plaintext *in-cluster* — the mesh can only
encrypt a connection it originates. Before S7b, the whole path from the host was
plaintext; now only that one in-cluster leg is. To close it, mesh the controller
(`linkerd.io/inject: ingress`) or terminate the edge inside the mesh.

## Verify

```bash
./scripts/tls-check.sh
```

Three checks, because no one of them can see the others:

- the **mesh** — every edge it carries must be `SECURED`;
- the **hops we own** — asked directly, from inside a pod that holds an SVID: a
  client with no SVID must not complete the handshake, and on the machine routes a
  caller with no *name* must be refused while the agent is admitted;
- the **browser edge** — fetched from outside the cluster the way a browser does,
  with our CA and never `-k`: the certificate must chain to it, must *name* the
  host, and the CA itself must carry `basicConstraints`/`keyUsage` (a CA without
  them passes curl and is refused by Python/OpenSSL 3 — that is the difference
  between a certificate that verifies and one that is merely present).

```
Every edge the mesh carries is mTLS.

  hop               transport           caller identity
  agent → tools     mTLS required ✓     ✓ refused unnamed; admitted named (403)
  agent → api       mTLS required ✓     ✓ refused unnamed; admitted named (200)
  agent → agent     mTLS required ✓     — (shared with the user path)
  agent → gateway   mTLS required ✓     — (shared with the user path)

BROWSER EDGE (TLS terminated at the ingress)
  certificate chains to    our CA ✓
  our CA                   CA:TRUE + keyCertSign ✓ (strict clients accept it)
  names                    localhost ✓ (SAN)
  https://localhost/healthz 200 ✓ (certificate verified)

Every hop is authenticated: SPIFFE where we own it, the mesh for the rest,
and the browser edge by a certificate we verify.
```

(The `403` on `agent → tools` is the tool call failing later for a missing *user*
token — the point is that it is no longer refused for a missing *identity*.)

## Setup

`scripts/setup.sh` installs Linkerd (if the CLI is present), annotates the namespace
for injection, and registers the SPIFFE entries for `api` and `tools` as well as
`agent` and `gateway`. The Helm chart takes `mesh.inject` to annotate the pods it
deploys, and `spiffe: true` adds the Workload API socket, the SVID expectations and
the port-skip rule. It then installs `ingress-nginx` (pinned, images by digest),
generates the edge certificate into the gitignored `.edge/`, and **gates** on a
verified `https` fetch through the edge — the chart's `ingress` block, which had
never been exercised on kind, is what runs.

On kind the browser reaches the controller through a `port-forward` (`start.sh`),
because `cluster.yaml` publishes no host ports on purpose. It is a port-forward to
the **ingress**, not to the API: the certificate and the TLS termination are real
either way, and the API's own listener is never exposed to the host.

Without the CLI, setup skips the mesh and the third-party hops run in plaintext; the
SPIFFE hops still apply, because they do not depend on it.

## What this does and does not give you

- **Encryption** — yes, on every hop: SPIFFE where we own it, the mesh for the rest.
- **Authenticated transport** — yes. SPIFFE hops require a chain-verified SVID; mesh
  hops are authenticated by the mesh's identity.
- **A named caller** — on the machine routes we own, yes (S7); the agent is the only
  workload that may create an approval, and the tool server the only one that may
  verify one. Elsewhere the name is not asserted, and authorization stays where it
  belongs: bearer tokens (audience + `azp`), OPA policy and tenant scoping.
- **The browser edge** — yes (S7b): TLS terminates at the ingress with a
  certificate from our own CA, and `tls-check.sh` verifies it rather than skipping
  it. The residual is the ingress→api leg in-cluster (above) and the *name*: a
  browser proves a user with a bearer token, not a workload identity, which is the
  right shape for a person. The chart's `ingress` block is the same object a real
  cluster runs; on kind the host is `localhost` and the CA is one you import.
- **Egress to the model provider** — the gateway reaches a hosted provider over the
  provider's own TLS; the local default (Ollama) stays in-cluster.

## Notes

- **Two identity systems remain**, deliberately, and ADR-0012 records why: Linkerd's
  identity is load-bearing for the components that cannot present an SVID. This is a
  boundary, not a claim that there is only one identity.
- **The peer certificate is not exposed by our ASGI server**, so the *name* on a hop
  rides a JWT-SVID in a header rather than the certificate's SAN — audience-bound to
  one callee, five minutes long, never logged. The strongest form would be an X.509
  SAN assertion, which would mean a different server.
- The mesh proxy is a native sidecar (an `initContainer` with `restartPolicy:
  Always`), so `kubectl exec` may need `-c <container>` to pick the app.
- Linkerd needs Kubernetes 1.29+ and the Gateway API CRDs (installed by setup).
