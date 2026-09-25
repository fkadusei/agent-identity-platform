# Backlog

Every slice, with a stable ID so it can be referenced ("do S3"), what it is, why
it matters, where it lands, and how we would know it works. Done slices are kept
and marked **done** for the record (S5, S10, S13, S15). The phase history lives in
[`roadmap.md`](roadmap.md).

Legend: **open** · *partly done* (say which half).

---

## Resolved (2026-09-16): the gateway was serving an expired SVID

The live evals scored **1/8 for every model** — `llama3.2:3b` and
`qwen3-warden-ctx16k` alike — so the model was never the variable. The `1/8` was
the tell: of the eight live cases, the single pass ("an injection attempt is
refused before the model") is refused locally by the task guardrail **before any
model call**. Everything that reached the gateway failed, identically.

The `llm.fallback` audit reason named the real cause, exactly as this section
predicted:

```
[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: certificate has expired
```

The gateway was serving an expired certificate: its SVID had `notAfter 12:38:23`
while the evals ran at `12:42:39`, and the process itself was healthy — an
unverified handshake to it succeeded. The cause and the fix are **S15**; the
message that hid it for hours is **S13**.

**For context.** A 45GB model (a 30B with a 262k context) was loaded beside an
8GB Docker VM, which starved the host. The SPIRE server could not reach the
Kubernetes API server, crashed, and crash-looped; SVID rotation stopped and
certificates expired. That is fixed, and it is **S11**'s ground — a transient
resource spike must not become hours of outage. The model was swapped to
`qwen3-warden-ctx16k` during the investigation and has been **reverted** to
`llama3.2:3b`; Docker Desktop now has 33GB instead of 8GB.

**Still worth knowing when diagnosing.** There are two agent replicas, so
`exec deploy/agent` runs the evals in one pod while `logs deploy/agent` reads the
other — pick a named pod:

```
kubectl --context kind-agent-platform -n agent-platform get pods -l app=agent
kubectl --context kind-agent-platform -n agent-platform exec <that-pod> -c agent -- python -m app.agent.evals --live
kubectl --context kind-agent-platform -n agent-platform logs <that-pod> -c agent \
  | grep -o 'llm\.[a-z_]*\|reason[^,}]\{0,150\}'
```

The live evals now score **5/8**, and the agent's audit trail carries no
`llm.fallback` events at all. The three remaining failures are `llama3.2:3b`'s
own behaviour — a substituted tool, a bare decline, an unusable argument set —
not infrastructure. The live eval stays deliberately out of CI (S5).

---

## S1 — HA: SPIRE server — **done**

- **What:** run SPIRE with a shared datastore and a shared key manager, 2+ replicas.
- **Why:** identity is the critical path — without it nothing gets an SVID. It was
  a single StatefulSet on `sqlite` + the disk key manager, so a restart forgot its
  agents and entries, and two replicas would sign with different CAs.
- **Built:** the **shared datastore** half.
  - The registration registry now lives in Postgres — a dedicated, least-privilege
    `spire` role and database in the S3 database — through the `sql` datastore
    plugin. `deploy/kind/manifests/spire/server.conf.tmpl` holds the configuration;
    `setup.sh` renders it into the `spire-server-config` **Secret** (the connection
    string carries the password) and the StatefulSet mounts that read-only.
  - The disk KeyManager's keys moved from the demo's `emptyDir` to a
    `PersistentVolumeClaim` (`spire-server-data`), so a restarted server signs with
    the **same CA** instead of regenerating one.
  - `setup.sh` applies Postgres *before* SPIRE now, because identity depends on the
    database. It creates the role and database idempotently, and re-sets the
    password so it always matches `.env` (`SPIRE_DB_PASSWORD`).
- **Verified by:** deleting the SPIRE server pod. `spire-server entry show` was
  unchanged (4 entries before and after); the trust bundle's SHA-256 fingerprint was
  **identical**, so no workload needed restarting to pick up a fresh SVID; a
  workload still fetched a new SVID; and every app pod's restart count stayed **0**.
- **Built (the shared KeyManager half):** the KeyManager is now **switchable**.
  `SPIRE_KEY_MANAGER` in `.env` selects the block in `server.conf.tmpl` — `disk`
  (default: no credentials, single replica, CA on a PVC) or `aws_kms` (the CA is
  created, rotated and *used* inside KMS; every replica signs with the same one).
  `scripts/render.py` gained `{{#if}}/{{#unless}}` blocks so one template describes
  both, rather than two files drifting apart, and `spire-server.yaml` mounts the
  KMS config/credentials/key policy with `optional: true` so a single manifest
  serves both modes. `setup.sh` stages those (and **deletes** them when switching
  back to disk), scales to `SPIRE_SERVER_REPLICAS`, and **gates** on every replica
  presenting the same trust-bundle fingerprint.
- **The setting HA turns on:** `SPIRE_KMS_SERVER_ID` must be identical on every
  replica. The plugin's default identifier is a per-server *file*, which each
  replica would create for itself — one identifier each, therefore one key each,
  therefore a different CA each, which is worse than a single server.
- **Verified by:** `disk` mode unchanged end to end (`setup.sh`, the suite, the new
  CA gate); both modes rendering correctly from the one template; renderer
  conditionals unit-tested; and the `aws_kms` plugin **loading in our own image** —
  a probe with no credentials fails at `KMS:ListAliases` with `no EC2 IMDS role
  found`, which proves the plugin is compiled in and that the wiring reaches AWS.
- **Exercised against a live key** (AWS KMS, `us-east-1`, role-based access through
  `scripts/setup-aws-kms-role.sh`): the plugin created its own `ECC_NIST_P256`
  `SIGN_VERIFY` keys (`x509-CA-A`, `JWT-Signer-A`) under
  `alias/SPIRE_SERVER/acme_com/acme-com/`, both replicas served a **byte-identical
  trust bundle**, and deleting a replica left the survivor issuing SVIDs with an
  unchanged bundle — a workload fetched a fresh JWT-SVID **during** the failover and
  **no workload restarted**. The full suite passed on the KMS-backed CA afterwards.
  The base credential behaved as designed, too: a `kms:ListAliases` with it was
  denied, because it may only assume the role.
- **Two things the live run established that are worth keeping:** switching the
  KeyManager **changes the CA** (a maintenance-window operation, not a flip), and the
  demo rotates CAs every ~12h — so the gate compares the whole bundle, not one
  certificate. Latency and cost are in `docs/ha.md`.
- **Unchanged:** a second replica would use the `sql` datastore's `read_only`
  connection string for reads, and SPIRE needs Postgres reachable — which is why
  production points `database.url` at a managed, HA database.

## S2 — HA: Keycloak — **done**

- **What:** Keycloak in production mode against an external database, 2+ replicas
  behind the Service.
- **Why:** no Keycloak, no tokens. It was `start-dev` with ephemeral H2, and
  `setup.sh` recreated it every run — which is also why runtime-enrolled accounts
  were lost.
- **Built:** two replicas behind the Service, against Postgres — a dedicated
  least-privilege `keycloak` role and database, created by `setup.sh` alongside
  SPIRE's. Sessions are shared through the embedded `ispn` cache, which discovers
  peers through the database (`jdbc-ping` is the default), so no headless service
  or JGroups DNS setup is needed. Added a PodDisruptionBudget and the same soft
  anti-affinity the other replicated services use. The realm is imported by a
  **Job** (`keycloak-import.yaml`) with `--override=false`: the first run creates
  it, every later run is a no-op that leaves the database alone — which is what
  keeps enrolled accounts. `setup.sh` no longer deletes Keycloak.
- **Verified by:** 2/2 replicas spread across both workers; a direct grant against
  *each pod individually* (port-forwarded) returned a valid token with
  `iss=http://keycloak:8080/realms/agent-platform`; and a user created at runtime
  was still present after a full `setup.sh` re-run, alongside the seeded users.
- **Trade-off, named:** because the import never overwrites, rotating a *client
  secret* in `.env` does not reach an existing realm — delete the realm (or the
  `keycloak` database) and re-run. That is in the operator guide.

## S3 — Persistent, managed Postgres — **done**

- **What:** a durable database with backups (a managed service in production),
  instead of the demo's `emptyDir`.
- **Why:** approvals, run checkpoints, gateway counters and the audit trail are all
  in Postgres; they survived a pod restart but not the *volume*.
- **Built:** `deploy/kind/manifests/data/postgres.yaml` now backs `/var/lib/postgresql/data`
  with a `PersistentVolumeClaim` (2Gi, the cluster default `local-path`
  StorageClass) instead of an `emptyDir`, and the Deployment uses strategy
  `Recreate` — one ReadWriteOnce volume, so a rolling update must not try to start
  the replacement before the old pod has released the claim. The rest is
  unchanged: still one replica, still a node-local volume, so the pod cannot be
  rescheduled to another node. Production remains a managed database with backups
  (the chart's `database.url`); this slice is what makes the demo honest about
  durability.
- **Found while doing it:** the manifest had never actually been committed. A bare
  `data/` line in `.gitignore` matched `deploy/kind/manifests/data/`, so the file
  was untracked and absent from every clone — while `setup.sh` applies it, which
  meant a fresh clone could not come up at all. The rule is root-anchored now
  (`/data/`) and the manifest is tracked.
- **Verified by:** ran a full run → approval → resume, then deleted the Postgres
  pod. It came back on the *same* claim and the counts were unchanged —
  `1 approvals, 11 checkpoints, 10 audit events` before and after — with the
  approval (`ap-15030b86dc51`) still `approved (refunds.issue, acme)`.
- **Note:** a `setup.sh` re-run no longer wipes this data; it now survives one. The
  volume is still deleted with the cluster (`./stop.sh --delete`).

## S4 — Hardened Keycloak — **done**

- **What:** the production-mode half of S2 that stands alone: TLS, no `start-dev`,
  an explicit hostname, and a realm imported by a job rather than by the server.
- **Why:** `start-dev` is documented as a demo setting; the read-only root
  filesystem was a scoped exception in `.trivyignore.yaml`.
- **Built:** `args: ["start", "--optimized"]`; an explicit `KC_HOSTNAME`
  (`http://keycloak:8080`, which pins the `iss` the services already expect);
  `KC_HOSTNAME_STRICT=true`; and a shared `keycloak-env` ConfigMap so the Job and
  the server cannot drift. A read-only root filesystem needed a custom image:
  `start` re-augments Quarkus into `/opt/keycloak/lib/quarkus` at runtime, so
  `docker/keycloak.Dockerfile` bakes `kc.sh build` in and the server runs with
  `--optimized`, never writing to `/opt/keycloak` at all.
- **Verified by:** the Trivy exception is **deleted** — `.trivyignore.yaml` now
  carries no exceptions, and every container in the repository sets
  `readOnlyRootFilesystem`.
- **Interpretation, stated:** the listener is HTTP and TLS is terminated in front.
  Every in-cluster hop is already mTLS (Linkerd, asserted by `tls-check.sh`) and
  the browser edge is S7's ingress; Keycloak documents `--http-enabled` for exactly
  this case ("fronted by a TLS termination"), so a Keycloak HTTPS listener would be
  redundant *inside* the mesh rather than more secure.

## S5 — Agent guardrails + evals — **done**

- **What:** input/output guardrails on the agent, and an evaluation suite (a set
  of tasks with expected tool/decision) run in CI.
- **Why:** the last unbuilt Phase 2 feature. Policy constrains what the agent may
  *do*; nothing yet constrains what it may be *asked*, or measures whether it
  picks the right tool.
- **Built:** `app/agent/guardrails.py` (the task before the model, the decision
  before the tool) and `app/agent/evals.py` (10 cases; stubbed in CI, `--live`
  against the real model). See [`guardrails-and-evals.md`](guardrails-and-evals.md).
- **Still open:** output-*content* checks, and a live eval in CI (deliberately
  absent — it would be flaky).

## S6 — Custom-metric autoscaling — **done**

- **What:** scale on the signal that matters instead of CPU: the approval backlog
  for the api, and request rate per pod — via a Prometheus adapter.
- **Why:** CPU is a proxy. The platform already exports the real signals, so
  nothing new needed instrumenting; the HPA just could not see them.
- **Built:**
  - `prometheus-adapter` (`deploy/kind/manifests/autoscaling/`) exposing
    `approvals_pending` on `external.metrics.k8s.io` (the queue depth — a property
    of the platform, not of one pod) and `http_requests_per_second` on
    `custom.metrics.k8s.io` (`Pods` — the api's counter turned into a rate). It
    gets its own serving cert, pinned into both APIServices (never
    `insecureSkipTLSVerify`), and skips the mesh on 6443 — the API server is not a
    mesh client (S7's rule).
  - The api's HPA carries all three metrics; the other services stay on CPU. An
    HPA takes the largest, so CPU remains the fallback.
  - The chart takes `autoscaling.extraMetrics` per service; the adapter is a
    cluster add-on, like metrics-server.
- **Two bugs found by watching it fail — both would have looked plausible while
  being wrong:**
  - Prometheus scraped the api's **Service**, so per-process counters jumped
    backwards between replicas and `rate()` was noise (and there was no `pod`
    label for a `Pods` metric). It now scrapes per pod.
  - The backlog gauge was written **per replica and per tenant** when an approval
    changed, so only the replica that handled the change moved: after draining the
    queue the api **stayed at 5 replicas** forever, because `max()` across the
    replicas followed a stale value. The count is now read from the store at
    scrape time (`store.pending_count()`), across every tenant.
- **Verified by:** a full cycle on kind — seven held approvals took the api
  `2 → 3 → 5`, and deciding them brought it back to `2` after the 120s
  stabilization window — with `kubectl describe hpa api` reporting all three
  metrics (`0 / 5`, `171m / 20`, `5% / 70%`). Unit-tested at the property that
  broke: `app/api/tests/test_metrics.py`.
- **Corrected, not silently substituted:** the slice asked for "request rate for
  the **gateway**", but the gateway serves **only** mTLS with an SVID, so
  Prometheus (which holds no SVID) cannot scrape it — there is nothing to scale it
  on beyond CPU. The rate metric was built for the api, which does export one. To
  do the gateway later, either give it a listener to be scraped on, give
  Prometheus an SVID, or derive the signal from the audit stream the gateway
  already sends to the api (which is the shape `app/common/metrics.py` already
  prefers).

## S7 — SPIFFE-native transport everywhere — **done**

- **What:** replace the mesh's own identity with SPIFFE mTLS on the hops between
  workloads we own, and terminate TLS for the browser edge at an ingress.
- **Why:** the app layer did SPIFFE for agent↔gateway, but the rest of the mesh
  authenticated with Linkerd's identity — two identity systems where one would do,
  and no hop told the application *who* its peer was.
- **Built:** see [ADR-0012](decisions/ADR-0012-transport-identity.md) for the
  boundary and why it is drawn there.
  - `api`, `tools` and `agent` hold SVIDs beside `gateway` (ServiceAccounts, SPIRE
    registration entries in `setup.sh`, the Workload API socket mounted, and
    `agentnhi[spiffe]` installed — which `api` and `tools` were missing entirely, so
    they could not have fetched one).
  - `app/common/server.py` serves every one of their TLS listeners with
    `CERT_REQUIRED` against the SPIRE bundle and rests 120s before the SVID expires
    (S15's rule, now shared); `app/common/hop.py` is the client half.
  - `app/common/workload.py` names the caller: a JWT-SVID audienced to the callee,
    verified against SPIRE's JWKS, allow-listed. Enforced in the tools'
    **enforcement core** — one choke point covering both the HTTP and MCP transports
    — and on the api's machine routes. **`/audit/events` had taken no credential at
    all**; only the agent and the tool server may ingest now.
  - Each service serves **two listeners**: SPIFFE for workloads, its original port
    for the browser and the verification scripts, which cannot hold an SVID.
  - The mesh is **kept** for Keycloak, OPA, Postgres, the sandbox and `/metrics`,
    and our SPIFFE port skips the proxy in both directions so it is never
    mesh-terminated.
- **Verified by:** `./scripts/tls-check.sh`, which now asserts per-hop identity as
  well as mesh encryption — a client with no SVID cannot complete a handshake on any
  hop we own, and the machine routes refuse an unnamed caller while admitting the
  agent (`scripts/spiffe_hops_client.py`). Plus, on kind: the demo end to end over
  the new hops, a tool call with a real exchanged token but no workload identity
  refused, audit ingest refused, and all four suites green.
- **Closed since:** the **browser edge** (S7b below). Also named in the ADR: the
  naming rides a bearer token rather than the certificate's SAN, because our ASGI
  server does not expose the peer certificate.

## S7b — TLS for the browser edge — **done**

- **What:** actually run the chart's `ingress` on kind: an ingress, with a
  certificate, in front of the api's user listener, instead of `port-forward`.
- **Why:** it was the one hop carrying user tokens that was still unencrypted, and
  the chart had supported it since Phase 3 with nobody exercising it. The demo's
  own comment — "no host port mappings on purpose" — meant the browser path had
  never been a real one.
- **Delivered:**
  - `ingress-nginx` (controller-v1.15.1, every image by digest) and a TLS Ingress
    for the api that mirrors the chart's object —
    `deploy/kind/manifests/edge/ingress.yaml`.
  - A certificate **we generate**: a CA and a leaf named for the host, into the
    gitignored `.edge/`, carrying the extensions strict clients require. A browser
    imports `ca.crt`; the CLI uses `--cacert`. Nothing is skipped, and the API's own
    listener is no longer exposed to the host.
  - `start.sh`/`status.sh` reach the platform over `https://localhost:8443` through
    the controller; `setup.sh` step 10 installs, generates and **gates** on a
    verified `https` fetch from outside the cluster.
  - `tls-check.sh` grew a third section: the chain, the name, the CA's extensions,
    and a real fetch — all with the CA, none with `-k`.
- **Residual, named:** the controller carries no sidecar, so ingress→api:8080 is
  plaintext in-cluster (the mesh can only encrypt what it originates). Before this,
  the *whole* host→api path was plaintext. Close it with
  `linkerd.io/inject: ingress` on the controller, or terminate inside the mesh.
- **Verified by:** `tls-check.sh` (all three sections green); and the user journey
  over `https` — sign in, a $200 refund that policy holds for approval, the approver
  queue, the decision, the refund `issued` — driven through the edge with a strict
  TLS client (Python/OpenSSL 3, which is what rejected our first certificate).
- **Found and fixed along the way:**
  - The first CA was too loose for strict clients — no `basicConstraints`/`keyUsage`
    — so curl accepted the chain and Python/OpenSSL 3 refused it outright. The
    extensions are generated now, and `tls-check.sh` asserts them.
  - **`setup.sh` could not finish for ~31 hours.** Jaeger's process hung (still
    `Running`, not logging, UI dead) and, having a readiness probe but no liveness
    probe, nothing ever restarted it — so the rollout gate parked the whole bring-up
    and only a human could clear it. Jaeger has a liveness probe now; the rest of
    the stack has the same gap — see S16.

## S8 — Per-tenant role → tool maps — **done**

- **What:** let the role → tool matrix differ per tenant, instead of one global
  table.
- **Why:** two customers may want different definitions of "billing". The matrix
  was global and the tenant only scoped data.
- **Part 1 — done (PR #69):** `/audit` is authenticated and scoped to the caller's
  tenant. It had taken no token at all, so anything that could reach the API could
  read every tenant's events — which was why the Audit tab passed no token. The
  hole was load-bearing.
- **Decisions, settled:**
  - the demonstration is `globex`'s `support_rep` **losing** refunds while `acme`'s
    keeps them: the same role name with different power, decided by which customer
    you belong to;
  - a tenant's entry for a role **replaces** the default for that role entirely; a
    role the tenant does not mention falls back to the default. One place to read,
    nothing to reconcile, and the failure mode is visible.
- **Decision taken:** the tenant maps live **in the policy file**, adopting the
  proposed option above. Changing a customer's powers is therefore a reviewed,
  signed policy release. A data document could change without a policy release, at
  the cost of a second artefact to version, sign and deploy — and a place where a
  mistake gets less review.
- **Built** (it landed atomically, as it had to):
  1. `policy/authz.rego` — `role_tools` split into `default_role_tools` and
     `tenant_role_tools`, plus `role_tools_for(tenant, role)` and a `role_matrix`
     rule for the page. `may_call`, `tools_for_roles` and `role_matrix` all read
     `input.tenant`, so a role defined in neither resolves nothing and denies.
  2. `policy/tests/authz_test.rego` — 45 tests (was 31), including the globex
     demonstration, replacement-not-merge, fallback for an unmentioned role, an
     unscoped caller, and two data-hygiene guards (overrides may only name real
     roles and real tools).
  3. `app/common/policy.py` — `tools_for_roles(url, roles, tenant)`; the tenant is
     a required argument, so a caller cannot forget it. `role_matrix(url, tenant)`
     is queried with input.
  4. `app/agent/{live,service}.py` — `LiveDeps` takes `tenant` and passes it, so
     the tools the model is *offered* match the tools policy will *allow*, per
     tenant.
  5. `app/api/{roles,auth}.py` — the Roles page and the login response both resolve
     the caller's own tenant.
  6. The realm needed nothing: the maps live in policy, and `globex` already had a
     seeded `support_rep` (`grace`).
- **Verified by:** `./scripts/role-tools.sh` — alice (acme) may issue a refund,
  grace (globex) is refused the same call with the same role name; `refunds.quote`
  and the rest of the role still work, so it is a replacement and not a blanket
  removal. A direct policy query confirms the *offered* set differs per tenant and
  is empty without one; the login response and the Roles page show the same
  difference.
- **Found on the way** (fixed rather than routed around, because the demonstration
  exposed it): asking for a record outside your tenant returned a **500** from the
  sandbox for the two *write* tools. The simulators signal a missing record with
  `NotFound` (a `ValueError` subclass), the sandbox's write endpoints did not
  translate it, and the two write handlers did not turn a `None` into a readable
  result the way every read handler does. All three layers are fixed, so a record
  that is not there is a clear "unknown ticket/order" — never a 500, never a silent
  success. See `docs/integrations.md`.

## S9 — Durable sandbox / simulated-system state — **done**

- **What:** persist the synthetic data so it survives a restart, or make the
  sandbox stateless.
- **Why:** the sandbox held its data in memory, so a restart reset every refund and
  draft — fine for a demo, confusing mid-demo.
- **Built:** the sandbox keeps its own snapshot. The simulated systems gained
  `snapshot()` / `restore()` (`app/simulators/`), and the sandbox writes them to
  `SANDBOX_STATE_PATH` after each write and reloads them at startup — so a pod
  restart continues the demo (`app/sandbox/persistence.py`). Three deliberate
  properties: **off unless configured** (tests and a local run keep the in-memory
  behaviour), **never fatal** (a snapshot that cannot be read is treated as empty
  and a failed write is reported as `sandbox.state_error`, because a volume that is
  not mounted should not fail the write it is recording), and **atomic** (written
  to a temporary file and renamed, so a crash cannot leave a half-written snapshot
  to be read at startup). The ids resume after the restored records, so a new
  refund cannot collide with an old one and idempotency still holds across a
  restart.
- **Why the sandbox's own volume, not Postgres:** the sandbox stands in for a
  vendor's systems, so it owns this storage — the platform's database is not the
  vendor's. The tools do not know either way; the REST contract is unchanged.
- **Verified by:** issued a refund and a draft, deleted the sandbox pod, and the
  quote still reported it (`already_refunded 25.0`); the next refund came back as
  `r-0002`, so the counter had resumed. Removing the snapshot and restarting
  returns the demo to its clean baseline, which is also how the volume behaves in
  `./stop.sh --delete`. Tests: a round-trip at the simulator level (ids, idempotency)
  and an end-to-end restart through the app's lifespan — both fail if the restore
  is removed.

## S10 — Privacy use case, end to end

- **Done.** The `privacy` role, the PII tool and its approval gate exist,
  and the console offers a role-appropriate PII task. The purpose-built view now
  exists too: `GET /privacy/access` (manager only) and the **Privacy** tab show
  the PII access trail — held / allowed / denied, with the policy reason and
  bundle revision — next to the approval trail. `GET /audit` gained
  `?event=&tool=&sub=` filters. See [`privacy.md`](privacy.md).
- **Audit is durable** (`app/audit/store.py`): in-memory without a database,
  Postgres `audit_events` with one. This fixed the flaw the view was built on —
  an in-memory deque per API replica meant two pods held 8 and 7 *different*
  events and a restart cleared it. Both replicas now return the same trail, and
  it survives a restart (verified on kind).
- **Refusals are now recorded.** A refusal before the tool server reports
  `status: "refused"` (distinct from `error`), and the agent audits an
  `agent.refused` event with the user, tenant and reason — not the task text, which
  may itself contain personal data. When the model names a tool it may not call,
  the event names it and the refusal appears on the privacy trail. **Limit:** a
  small model often just declines rather than naming the tool, in which case the
  refusal is recorded but cannot be attributed to `privacy.pii.read` — verified on
  kind with `llama3.2:3b`, which declines. Attributing that case would need a
  heuristic over the task text, which is deliberately not done.
- **Lands in:** `app/web/`, `app/api/`, and (for the durable store) `app/common/`.
- **Verified by:** reading PII as `priya`, approving as the manager, and seeing it
  in a PII-specific view. **Confirmed on kind**; the limits above were found by
  verifying it rather than by reading the code.

---

## S11 — SPIRE should survive an API-server blip — **done**

- **What:** the SPIRE server exits when it cannot reach the Kubernetes API server
  to update its bundle ConfigMap — `Fatal run error ... notifier(k8sbundle):
  unable to get list ... TLS handshake timeout` — and because its datastore is
  in-memory, every restart regenerates the CA, so *every* workload must be
  restarted to pick up fresh SVIDs.
- **Why:** this turned a transient resource spike into hours of outage whose only
  symptoms were expired certificates and a message blaming the model. It is the
  same ground as **S1**.
- **Built:** SPIRE 1.11.2 → **1.12.4** (both `docker/spire-*.Dockerfile`, and the
  OIDC discovery provider image), because the fix is the `k8s_configmap`
  **BundlePublisher** that replaced the deprecated `k8sbundle` **Notifier**. The
  notifier was called on bundle events and its error was fatal; the publisher runs
  on a 30-second tick, and a failed publish is only logged
  (`Failed to publish bundle`) and retried. `spire-server.yaml` now configures
  `BundlePublisher "k8s_configmap"` — ConfigMap `spire-bundle`, key `bundle.crt`
  (what the agent reads), format `pem` — and the `jti` plugin's
  `spire-plugin-sdk` pin moves with the server version. `setup.sh` also restarts
  the SPIRE **server**, not just the agents: its config comes from a ConfigMap and
  its image from a reused `:demo` tag, so a re-run previously kept the old SPIRE
  (and the old config) running — the same trap `check-images.sh` warns about.
- **Migration gotcha:** the publisher uses Server-Side Apply, which refuses to
  take over a field another manager owns. A cluster upgrading from the notifier
  has `.data.bundle.crt` owned by a manager named `spire-server`, so publishing
  fails every tick with `Apply failed with 1 conflict`. `setup.sh` recreates the
  (empty) `spire-bundle` ConfigMap before applying the manifests, clearing the
  stale owner; a no-op on a fresh cluster.
- **Verified by:** revoking the publisher's RBAC so its API call genuinely fails,
  then restarting the server. It logged **4 consecutive** `Failed to publish
  bundle` errors over ~2 minutes and stayed `Running`/`Ready`, restart count **0**,
  with `spire-server healthcheck` healthy — where the notifier took the server
  down. Restoring the permission republished within one tick, and the ConfigMap
  then matched the server CA's SHA-256 fingerprint exactly. The platform runs end
  to end on 1.12.4: `demo.sh`, all six attacks blocked, and the tenancy,
  role→tool, TLS and HA suites — plus the SVID gate, which exercises the rebuilt
  `jti` plugin.
- **Was still open at the time:** the demo's SPIRE datastore was an `emptyDir`, so
  recreating the server *pod* regenerated the CA and forgot the registration
  entries, and the app tier then needed a restart. **S1** has since fixed that — the
  registry is in Postgres and the keys are on a PVC — while S11 removed the
  crash-loop that kept triggering it.

## S12 — The agent must survive a Postgres restart — **done**

- **What:** the agent's run checkpointer held a single Postgres connection. When
  Postgres restarted, that connection died and every run failed in 0.1s with
  `psycopg.OperationalError: server closed the connection unexpectedly` — forever,
  until the agent process was restarted.
- **Why:** a database restart must not require restarting the application, and the
  failure looks identical to a dozen other errors from the outside.
- **Built:** `app/agent/service.py` — `get_checkpointer()` builds a
  `psycopg_pool.ConnectionPool` (`check=ConnectionPool.check_connection`, so a dead
  connection is caught at checkout and replaced rather than handed out to fail
  once) and gives it to `PostgresSaver`, which checks a connection out per
  operation. It also re-runs the idempotent `saver.setup()` on each request — the
  same defence the approvals and audit stores apply per operation — because a
  database can come back without the schema under a running agent (the demo's
  `emptyDir` Postgres did exactly that; S3 has since given it a volume). The
  pool's backends carry `application_name=agent-checkpointer`, so they are visible
  in `pg_stat_activity` and addressable by the test.
- **Verified by:** two tests in `app/agent/tests/test_checkpointer_postgres.py`,
  both of which fail against the old single-connection code (with
  `AdminShutdown` and `UndefinedTable` respectively). On kind, with the agent's
  restart count unchanged at 0 throughout: (1) terminating its four pooled
  connections, then a full run → approval → resume → issued; and (2) dropping the
  checkpoint tables — a database that came back empty — then the same full run,
  which recreated all eight tables on demand.
- **Note:** `psycopg[pool]` is now declared in `requirements.txt`; it previously
  arrived only transitively.

## S13 — Stop blaming the model for infrastructure faults — **done**

- **What:** "the model did not choose a usable tool — nothing was executed" was
  emitted for at least four unrelated causes: the model answered unusably, the
  model call raised (expired certificate, unreachable gateway), the response did
  not parse, and the model was unreachable at all. The `llm.fallback` audit event
  carried the real reason; the user-facing message did not.
- **Why:** during the 2026-09-16 incident this message pointed at the model for
  hours while the actual faults were an expired SVID and a dead database
  connection. It cost most of a debugging session.
- **Built:** `decide_tool` now splits the three ways a run ends without a tool —
  `unreachable` ("the model could not be reached"), `unparseable`, and `unusable`
  (the model's own bad answer, the old message) — and returns a machine-readable
  `cause` next to the reason. `llm.fallback` is kept as the event name, so the
  diagnostic grep above still works, and now carries that `cause`. `graph.py`
  needed no change: it already maps a decision without `refused` to
  `status: "error"`, so an unreachable model was already *classified* correctly —
  only the words were wrong. `live.py` needed none either; the timeout surfaces as
  an exception from `_chat`, which is the path that now names it.
- **Verified by:** `test_a_model_call_failure_blames_the_infrastructure` in
  `app/agent/tests/test_decide_tool.py`, with two companions pinning the
  `unparseable` path and the `cause` on the audit event.

## S14 — setup.sh must not run against the wrong cluster — **done**

- **What:** `setup.sh` verifies the kind cluster on line 78
  (`kubectl cluster-info --context kind-agent-platform`) and then runs every
  subsequent `kubectl` against whatever context happens to be *active*. When
  Docker Desktop restarted (making `docker-desktop` the active context), a full run
  applied everything to the wrong cluster and died with
  `error: no objects passed to apply` — naming neither the file nor the cluster it
  was aiming at.
- **Why:** three failures in one. It targets the wrong cluster; it fails with a
  message that cannot be diagnosed (most applies send stdout to `/dev/null`, so the
  failing command is not even visible); and it *partially* succeeds, leaving
  resources on a cluster it was never meant to touch. Found on 2026-09-16 while
  recovering from the SPIRE outage.
- **Built:** `scripts/lib.sh` pins the cluster for every script that touches it:
  it sets `KUBE_CONTEXT` (default `kind-agent-platform`, overridable) and defines a
  `kubectl` wrapper that always passes `--context`, so a call site *cannot* forget.
  The eleven scripts that use kubectl source it — `setup.sh` first among them — and
  `tls-check.sh` passes `linkerd --context`, because Linkerd reads the active
  context itself and cannot be wrapped. `start.sh` and `status.sh` no longer call
  `kubectl config use-context`, so nothing mutates your active context any more.
  `setup.sh`'s cluster check now names the context it wanted instead of surfacing a
  bare kubectl error. `stop.sh` and `teardown.sh` were already safe — they name the
  cluster and the docker containers explicitly and never read the active context.
- **Verified by:** with the active context deliberately set to `docker-desktop`,
  the unpinned `kubectl -n agent-platform get pods -l app=api` silently returned
  *"No resources found"* — the failure mode itself — while `./status.sh` reported
  `20/20` from the right cluster and `./scripts/role-tools.sh` ran end to end.
  `KUBE_CONTEXT=kind-does-not-exist ./scripts/setup.sh` exits 1 at step 1 with
  *"cannot reach context kind-does-not-exist"*, before building anything.

## S15 — The gateway must not serve an expired SVID — **done**

- **What:** the gateway restarted on a fixed 3300s timer that assumed a fresh 1h
  SVID at startup. But the Workload API returns SPIRE's **cached** SVID, and SPIRE
  rotates at roughly half the lifetime — so the gateway could fetch a certificate
  with only 36 minutes left, sleep 55 minutes, and serve an **expired** one for
  the difference. Every agent→gateway handshake then failed with
  `CERTIFICATE_VERIFY_FAILED`, which is what "the model did not choose a usable
  tool" was really reporting (2026-09-16).
- **Why:** a TLS server holding an expired certificate looks exactly like an
  application outage, and the symptom named the wrong component. Both replicas
  restart on their own hourly, so the gap recurred — about 19 minutes per cycle —
  and was found only by accident.
- **Lands in:** `app/gateway/run.py` — the restart deadline is now derived from
  the certificate's own `notAfter` (exit 120s early, re-checking at most each
  minute), `GATEWAY_SVID_RESTART_MARGIN_SECONDS` sets the margin, and a
  `gateway.svid_loaded` audit event reports `expires_in_seconds` at startup so the
  condition is visible before it bites.
- **Verified by:** `app/gateway/tests/test_run.py`, and on kind — both replicas
  logged `expires_in_seconds` of ~2470 (reproducing the half-spent SVID), and the
  live evals went from `1/8` with seven `llm.fallback` events to `5/8` with none.

## S16 — Liveness probes (a hung process must heal itself) — **done**

- **What:** every component in the demo had a readiness probe and **no** liveness
  probe, so a process that hangs was never restarted: the kubelet had nothing to act
  on, the container stayed `Running`, and readiness only reported the failure forever.
- **Why:** observed, not theorised. Jaeger hung for **31 hours** — no logs, no HTTP,
  UI dead — and because a readiness probe is a signal rather than a restart, nothing
  recovered it. The cost was a first-run path (`./start.sh` → `scripts/setup.sh`)
  that could not complete without a human, plus a trace UI nobody could reach.
- **Built:**
  - Liveness probes on **every** container that has a readiness probe: the app tier
    (`api`/`tools`/`agent`/`sandbox` on `/healthz`), the gateway, `postgres`
    (`pg_isready`), `opa`, `prometheus` (`/-/healthy`), `grafana`,
    `otel-collector`, `metrics-server`, `jaeger`, and SPIRE's
    `oidc-discovery-provider` (`/keys` — the endpoint the gateway verifies
    JWT-SVIDs against, so its hangs stop naming machine callers). Thresholds are
    per component and deliberately unhurried: ~60s of silence for a stateless
    service, ~2 minutes for Postgres, where a restart is the most expensive thing
    Kubernetes can do.
  - The **gateway needed code, not just a probe.** Its only listener is mTLS, so the
    kubelet cannot check it — it has no SVID to present — and the existing probe
    only asked whether the socket was open, which a hung process still answers
    because the kernel completes the handshake. A TCP liveness probe would have
    added nothing on top of the restart policy, which already restarts a process
    that *exits*. So `app/common/server.py` gained `health_port`: `/healthz` and
    nothing else, plaintext, started **after** the SVID is loaded. It is
    deliberately not the service's own app on a second port — that would expose the
    model endpoint to anything that can reach the pod.
  - The chart carries the same probes, and `services.<name>.healthPort` for the
    gateway. (Found while editing: a duplicated `resources:` block in
    `templates/apps.yaml` from an old merge, rendered twice and silently
    last-wins — removed.)
- **Verified by:** hanging each container's main process and watching the kubelet
  restart it — **fifteen containers**, all recovered: `api` 96s, `tools` 92s,
  `agent` 92s, `sandbox` 92s, `gateway` 87s, `otel-collector` 92s, `opa` 97s,
  `grafana` 122s, `prometheus` 122s, `postgres` 147s, `jaeger` 86s, `keycloak` 76s,
  `metrics-server` 86s, `spire-server` 96s, `oidc-discovery-provider` 147s.
  The suite and the metrics API were re-checked afterwards: 22/22 pods ready,
  demo, attacks, tenancy, TLS and HA all green.
- **Two things learned worth keeping:**
  - `kubectl exec <pod> -- kill -STOP 1` is a **no-op**: signals sent to a
    PID-namespace init process from inside the namespace are discarded (the same
    protection that stops a container killing itself), and PID 1 stays in state `S`.
    The test has to signal from outside — from the node, matching the process by
    cgroup. The first run of this verification "passed" nothing at all.
  - Mesh probes still fail correctly through Linkerd's proxy, which is what makes
    these probes meaningful for the injected app tier.

## S17 — Provider-agnostic models (native and cloud)

- **What:** make the gateway work with any OpenAI-compatible provider, not only Ollama.
  The plumbing for this is already in place — the model is named in one place (the
  `llm-config` ConfigMap, rendered from `.env` by `setup.sh` and swappable with
  `scripts/use-model.sh`), and a hosted key is already staged into the `llm-api-key`
  Secret that only the gateway mounts — but the hosted branch has two defects.
- **Why:** "swap models in and out" should not mean "swap *local* models in and out". We
  chose local-only deliberately, and the moment someone points this at a cloud provider
  the first defect below is what they will hit.
- **Two known defects, both found by reading the branch rather than by using it:**
  - **No model reaches the provider.** The branch forwards the caller's request with
    `req.model_dump(exclude_none=True)`, and the agent deliberately sends no model, so a
    hosted provider receives a request with no `model` and fails. Needs a fallback to
    `LLM_MODEL` in the gateway (the resolution added for the audit in the local slice is
    the place for it).
  - **`response_format` is forwarded blindly.** A strict provider may reject an unknown
    field. Needs a way to strip it; note the agent also asks for JSON in words, so
    stripping is survivable.
- **Also worth deciding when it lands:** whether a cloud model may see the personal data
  the agent can read under approval. Local-by-default keeps that data on-premises today;
  making it a *policy* question ("this tool or tenant may only use a local model") would
  suit this platform's approach, and is a larger piece than the two fixes. **S19 made
  this concrete**: a second step feeds the previous result back into the prompt, so a
  run that read PII as step 1 would send it to whichever model the gateway points at —
  see **S22**, which is the documentation side of the same fact.
- **Lands in:** `app/gateway/app.py`, `scripts/use-model.sh`, `docs/llm-gateway.md`.
- **Verified by:** a stub OpenAI-compatible provider in-cluster (so the path can be
  exercised without anyone's cloud key), unit tests for both defects, and the live evals
  against a real provider.

## S18 — The agent asks instead of refusing (clarification) — **done**

- **What:** when the model named a tool it may use but could not supply a required
  argument, the run ended as a refusal. The value usually exists — it is in the
  head of the person who asked — so the run now pauses and asks for it.
- **Why:** "refusing rather than guessing" is the right rule and the wrong end.
  Nothing was executed either way, so the only thing this changes is whether the
  person gets a question or a dead end. It is the first half of the agent-upgrade
  work; the second half (a bounded observation loop, **S19**) builds on it.
- **Built:**
  - `check_decision` **returns** the missing required names instead of raising. A
    missing argument is not a fault to refuse, and not a guess to make: the run
    pauses. Every other guardrail still ends the run, because a bad task or a
    forbidden tool has no answer to wait for.
  - `decide_tool` returns the decision as a *clarification* — tool kept, `missing`
    named, `clarify: True` — and the prompt now tells the model to leave an
    argument out rather than invent one. A tool the role may not call is still
    refused outright, missing argument or not.
  - The graph gains `ask_clarification`, an `interrupt` following the same rule as
    `await_decision` (pure, because the interrupt re-executes on resume), a
    self-loop bounded at **two** asks, and — when the budget is spent — a
    **refusal**, not an error: nothing is broken, the agent simply will not invent
    an identifier. `MAX_ASKS` is the bound.
  - `_shape` reads the status from the interrupt payload's own `type`, so
    `approval_required` and `clarification_required` pause identically and mean
    different things. `resume_task` takes a decision (`{"approved": …}` or
    `{"values": …}`) instead of a boolean; the service maps the two request shapes
    and audits `agent.clarification_requested`.
  - The UI grows a question card: one field per missing argument, and the words
    "answering is not approving" next to it.
- **The property that makes it safe:** the answer is untrusted input. It is merged
  into the arguments and judged by the same policy as one the model produced — a
  clarified $200 refund is still held for a manager, a clarified `bulk.` argument
  is still denied. Answering supplies a fact; it never grants anything. There is a
  test for exactly this (`test_an_answer_is_not_an_approval`).
- **Lands in:** `app/agent/{guardrails,llm,graph,service,evals}.py`, the web app,
  `docs/guardrails-and-evals.md`, `docs/site/agent-flow.html`.
- **Verified by:** graph tests against `ScriptedDeps` (asked vs refused vs
  proceeded, the answer reaching the same enforcement path, a partial answer asked
  for again, the budget ending in a refusal, and an answer still going on to need
  approval), the stubbed evals in CI (11 cases; the old "a required argument is
  missing → refused" case rewritten deliberately), and the live paths
  (demo, attacks, tenancy) unchanged.

## S19 — The agent takes more than one step (bounded loop) — **done**

- **What:** a task that needs two calls — "refund the order from the last ticket"
  — could not be done at all, because the graph made exactly one tool call and
  ended.
- **Why:** the second half of the agent-upgrade work. S18 landed first so a
  multi-step run could be multi-*turn* before it was multi-*step*.
- **Built:**
  - One new edge, `call_tool → plan`, and `observations` in the state: what each
    call returned, in order, shown to the model on the next pass (truncated for
    the prompt; the run keeps the whole thing).
  - **The loop is opt-in from the model, and that is a change from the agreed
    design.** The plan was for every successful run to go round again so the model
    could declare itself finished — which would have made a single-step task take
    two model calls and end as `answered` rather than `ok`, changing the outcome
    contract the demo, the UI and the tests all read. Instead the reply may carry
    `"more": true`, and a run that does not ask stops after one call. Completion is
    therefore expressed by *not* asking for more, which needed no new terminal
    status and no unvalidated model prose in the result.
  - **`MAX_STEPS = 3`**, counted in calls that *happened* — a denial or a hold
    teaches the model nothing, so a run cannot loop on those.
  - **The same call is never made twice.** A repeat is a second real action (a
    second refund) for no new information, and the check sits in `call_tool`,
    before the call, where no routing can bypass it. It compares against
    *observations*, so the held attempt of an approved refund — not a step, and not
    an observation — is correctly allowed through.
  - `AgentDeps.decide` grew an optional `observations` argument; `ScriptedDeps`
    grew a queue of decisions, which is what makes a multi-step run testable.
- **Lands in:** `app/agent/{deps,llm,graph,live,evals}.py`, the web app (the path
  a multi-step run took), `docs/site/agent-flow.html`, `docs/guardrails-and-evals.md`.
- **One thing learned worth keeping:** a prose instruction did not work. The prompt
  first said *"if you will need another call after seeing this one's result, add
  `more: true`"*, and `qwen3-warden-ctx16k` ignored it on every run — while stating in
  its own `reason` that it needed the ticket before it could refund. Moving the same
  field into the reply template —
  `{"tool": …, "args": {…}, "reason": …, "more": true if you will need another call after this one}`
  — made it emit `"more": true` for two-step tasks and `false` for single-step ones.
  Show a small model the shape of the answer; do not describe it in a sentence.
- **Verified by:** graph tests (a single-step run is unchanged — one model call,
  one tool call, `ok`; a second step sees the first result; the budget stops a
  model that would never stop; a recorded repeat is refused; an approval in the
  middle is a pause and the loop continues after it), the stubbed evals in CI (12
  cases now), and live: a three-step run against the cluster — read ticket t-5001,
  list that customer's orders, quote the damaged one — with the budget stopping it
  at three, and the repeat guard firing when the model tried a call it had already
  made.

## S20 — The model may pass along an identifier, never invent one — **done**

- **What:** asked to refund $200 with no order named, the model answered
  `{"order_id": "order_id", "amount": 200}` — the field's own name as the value.
  `check_decision` saw a present, non-empty string, so nothing was missing and no
  question was asked: a refund against an order called `order_id` went to a manager
  for approval.
- **Why:** reported by using the platform, not by reading it. It is the hole under
  S18 — the ask only fires when the model *omits* an argument, and a guessed value
  is not an omission. Worse, `_fill_gaps` only filled empty arguments, so a model
  that guessed a different id than the person typed would have had its guess used.
- **Built:**
  - `resolve_identifiers`: an identifier is kept only if the model has **seen** it —
    in the task, or in what an earlier call returned. A value outside that is a
    guess, and a guess is not a proposal: it is replaced by the one the task named
    (the person's words outrank the model's) and otherwise removed, which routes the
    call into the question S18 already knows how to ask.
  - What counts as an identifier is the `_id` suffix on a required argument —
    `customer_id`, `order_id`, `ticket_id` — so `amount` and `body` are untouched.
    Seen means a whole token: `o-1` is not found inside `o-1001`.
  - `llm.identifier_invented` is audited with the argument *name* — the guessed
    value is deliberately not recorded.
  - The multi-step case still works: an id read from a ticket (an observation) was
    seen, so it is kept.
- **Lands in:** `app/agent/{guardrails,llm,evals}.py`, `docs/site/agent-flow.html`,
  `docs/guardrails-and-evals.md`.
- **Verified by:** guardrail tests (an identifier the model never saw is dropped and
  becomes a question; a task-named id replaces the model's guess; an id from a
  previous call is kept; a truncated id is not treated as seen), the reported case as
  a test and as an eval case, and the live run that started this — see the annotation
  in `docs/site/agent-flow.html`.

## S21 — "Allowed" must not read as "it happened" — **done**

- **What:** a $20 refund against an order that does not exist was allowed by policy,
  the tool answered `unknown order`, and the screen said **allowed** with an error in
  the result. Reported by using the platform.
- **Why it matters:** `allow` is policy's answer, not the tool's. The outcome was
  *deliberate* — a record that is not there is an answer the caller can read, not a
  failure (S13, and there is a test that says so) — but the presentation made a
  nothing-happened look like a success, and the audit held only `tool.allowed`, so
  "did the refund actually happen?" could not be answered from the trail at all.
- **Built, without reversing that decision:**
  - the tool's own negative answer is **audited**: `tool.reported_error`, with the
    tool and the message (`unknown order`), right after `tool.allowed`. The outcome
    stays `OK`, so the earlier decision and its test are untouched.
  - the UI stops letting "allowed" stand alone: the chip reads **allowed — but
    nothing happened** (amber), the step says the call was allowed and the tool
    answered, and the result block is headed "The tool's answer".
- **Lands in:** `app/tools/enforcement.py`, the web app, `docs/site/{index,agent-flow}.html`.
- **Verified by:** an enforcement test that both events are recorded in order and
  that a normal answer raises none; the reported task replayed live.

## S22 — Document what the loop stores and re-exposes — **done**

- **What:** two consequences of S19's multi-step loop that are behaviour rather
  than defects, and are not yet written where they belong.
- **Why they matter, and why they are one slice:** they are the same fact seen from
  two sides — a run that makes several calls keeps more than it used to.
  - A run's **checkpoint now holds what each tool returned**, in order. Before the
    loop, a run's state held the last result; now a `privacy.pii.read` inside a
    multi-step run leaves the personal data in the run's state, in Postgres, for as
    long as the run exists. Same data, wider footprint, and it is *not* the audit —
    the audit deliberately records that a read happened, not what it returned.
  - A **result is fed back into the next prompt** on a second step, so whatever a
    PII tool returned is shown to the model. With a local model nothing leaves the
    building; the moment the gateway points at a cloud provider, this is the hop
    that would carry it off-site.
- **Decision taken: accept both, documented and bounded — not prevented.** The data
  is synthetic (ADR-0006), the model is local by default, the audit records *that* a
  read happened and not what it returned, and a run's state lives only as long as
  the run. Constraining them — dropping observation contents for PII tools, or
  making "a run that read PII may continue only on a local model" a policy decision
  — is **S17**'s policy question, and is deliberately left there rather than
  pre-empted here.
- **Built:** `docs/threat-model.md` gains **T11** (the threat, the accepted-risk
  mitigation, and the test that demonstrates it), `docs/privacy.md` gains "What a
  run keeps, and for how long" (the storage and retention answer, with the four
  bounds), and `docs/site/agent-flow.html` §9 gains a callout next to the loop. The
  live pages' threat count moves ten → eleven, with the T11 row, so the summary
  cannot drift from the model.
- **Verified by:** the docs naming the concrete case — a `privacy.pii.read` as step
  1 of a two-step run — and stating plainly that both consequences are accepted
  rather than prevented, with the cloud-model control deferred to S17. The
  demonstration test is
  `test_a_second_step_sees_what_the_first_one_returned`
  (`app/agent/tests/test_graph.py`); `scripts/check-docs-pages.py` keeps the pages
  and their quoted lines consistent.

## Not slices (documented limits)

- **There is exactly one agent, by construction.** One workload, one SPIFFE ID
  (`spiffe://acme.com/ns/agent-platform/sa/agent`), held by two interchangeable
  replicas — runs are checkpointed in Postgres, so either can resume, and many run
  at once as the same agent. `policy/authz.rego` trusts that ID and no other
  (`is_trusted if input.agent == trusted_agent`), so a second agent is refused as an
  untrusted workload until it is registered *and* the policy names it. The seams are
  already per-agent — policy reads `input.agent`, the gateway keys its limits on the
  proven caller, the audit records `spiffe_id` — so a second agent would be a policy
  and manifest change (a set of trusted agents, and probably per-agent role → tool
  matrices), not a redesign. Noted here because it was nowhere until it was asked.
- The trust domain (`acme.com`) and the demo passwords are documentation, not
  configuration to change.
- The mesh proxy is a native sidecar, so `kubectl exec` may need `-c <container>`.
