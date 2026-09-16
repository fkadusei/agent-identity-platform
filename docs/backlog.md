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

## S1 — HA: SPIRE server

- **What:** run SPIRE with a shared datastore and a shared key manager, 2+ replicas.
- **Why:** identity is the critical path — without it nothing gets an SVID. Today
  it is a single StatefulSet on `sqlite` + the disk key manager, so a restart
  forgets its agents and entries, and two replicas would sign with different CAs.
- **Lands in:** `deploy/kind/manifests/spire/spire-server.yaml` (datastore → SQL,
  KeyManager → a cloud KMS), `deploy/helm/agent-platform/`.
- **Verified by:** kill the SPIRE server pod; a workload still fetches an SVID,
  and `spire-server entry show` is unchanged after the restart.

## S2 — HA: Keycloak

- **What:** Keycloak in production mode against an external database, 2+ replicas
  behind the Service.
- **Why:** no Keycloak, no tokens. Today it is `start-dev` with ephemeral H2, and
  `setup.sh` recreates it every run — which is also why runtime-enrolled accounts
  are lost.
- **Lands in:** `deploy/kind/manifests/keycloak/`, the realm template, the chart.
- **Verified by:** scale to 2, log in against either pod, and keep enrolled users
  across a `setup.sh` re-run.

## S3 — Persistent, managed Postgres

- **What:** a durable database with backups (a managed service in production),
  instead of the demo's `emptyDir`.
- **Why:** approvals, run checkpoints and gateway counters are all in Postgres;
  today they survive a pod restart but not the volume.
- **Lands in:** `deploy/kind/manifests/data/postgres.yaml`, the chart's
  `database.url`.
- **Verified by:** write an approval, delete the Postgres pod, read it back.

## S4 — Hardened Keycloak

- **What:** the production-mode half of S2 that stands alone: TLS, no `start-dev`,
  an explicit hostname, and a realm imported by a job rather than by the server.
- **Why:** `start-dev` is documented as a demo setting; the read-only root
  filesystem is a scoped exception in `.trivyignore.yaml`.
- **Lands in:** `deploy/kind/manifests/keycloak/keycloak.yaml`.
- **Verified by:** the Trivy exception can be deleted because the control holds.

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

## S6 — Custom-metric autoscaling

- **What:** scale on the signal that matters — the approval backlog for the api,
  request rate for the gateway — via a Prometheus Adapter.
- **Why:** CPU is a proxy; the platform already exports the real signals
  (`agent_platform_approvals_pending`, `agent_platform_http_requests_total`).
- **Lands in:** `deploy/kind/manifests/autoscaling/`, the chart.
- **Verified by:** pushing the backlog up and watching the HPA scale the api.

## S7 — SPIFFE-native transport everywhere

- **What:** replace the mesh's own identity with SPIFFE mTLS on every hop, and
  terminate TLS for the browser edge at an ingress.
- **Why:** the app layer does SPIFFE for agent↔gateway, but the rest of the mesh
  authenticates with Linkerd's identity — two identity systems where one would do.
- **Lands in:** the service runners (`app/common/server.py`), the mesh config,
  `deploy/helm/agent-platform/` ingress.
- **Verified by:** `tls-check.sh` plus a peer-identity assertion per hop.

## S8 — Per-tenant role → tool maps

- **What:** let the role → tool matrix differ per tenant, instead of one global
  table.
- **Why:** two customers may want different definitions of "billing". Today the
  matrix is global and the tenant only scopes data.
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
- **Decision, proposed (not confirmed):** the tenant maps live **in the policy
  file** rather than a separate data document, so changing a customer's powers is a
  reviewed, signed policy release. The alternative — a data document loaded into
  OPA — lets tenant configuration change without a policy release, at the cost of a
  second artefact to version, sign and deploy, and a place where a mistake gets
  less review.
- **Must land atomically.** The agent asks the policy which tools a role may call
  (`tools_for_roles`) so the model is only offered tools it could actually use, and
  it does not currently pass a tenant. Keying the policy first would have the agent
  offer tools the tool server then denies — exactly the substitution the agent
  exists to prevent. So:
  1. `policy/authz.rego` — split `role_tools` into `default_role_tools` +
     `tenant_role_tools`, add `role_tools_for(tenant, role)`; `may_call` and
     `tools_for_roles` read `input.tenant`.
  2. `policy/tests/authz_test.rego` — `expected_role_tools` is a second copy of the
     matrix and needs updating, plus per-tenant cases (31 tests today).
  3. `app/common/policy.py` — `tools_for_roles(url, roles, tenant)`.
  4. `app/agent/{live,service}.py` — `LiveDeps` needs `delegation.tenant`.
  5. `app/api/roles.py` — the Roles page shows the caller's own tenant's matrix.
  6. Nothing to change in the realm: the maps live in policy, and `globex` already
     has a seeded `support_rep` (`grace`) to demonstrate it with.
- **Verified by:** `./scripts/role-tools.sh` showing the same role getting
  different tools in `acme` and `globex`, with the policy tests covering both.

## S9 — Durable sandbox / simulated-system state

- **What:** persist the synthetic data so it survives a restart, or make the
  sandbox stateless.
- **Why:** the sandbox holds its data in memory, so a restart resets every refund
  and draft — fine for a demo, confusing mid-demo.
- **Lands in:** `app/sandbox/`, `app/simulators/`.
- **Verified by:** issue a refund, restart the sandbox, list refunds.

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

## S11 — SPIRE should survive an API-server blip

- **What:** the SPIRE server exits when it cannot reach the Kubernetes API server
  to update its bundle ConfigMap — `Fatal run error ... notifier(k8sbundle):
  unable to get list ... TLS handshake timeout` — and because its datastore is
  in-memory, every restart regenerates the CA, so *every* workload must be
  restarted to pick up fresh SVIDs.
- **Why:** this turned a transient resource spike into hours of outage whose only
  symptoms were expired certificates and a message blaming the model. It is the
  same ground as **S1**.
- **Lands in:** `deploy/kind/manifests/spire/`, plus the operator guide; S1 covers
  the HA half (shared datastore, no CA regeneration).
- **Verified by:** making the API server briefly unreachable and watching SPIRE
  recover on its own, with no manual restart of the workloads.

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
  same defence the approvals and audit stores apply per operation — because the
  demo's `emptyDir` Postgres comes back with no schema after a pod restart. The
  pool's backends carry `application_name=agent-checkpointer`, so they are visible
  in `pg_stat_activity` and addressable by the test.
- **Verified by:** two tests in `app/agent/tests/test_checkpointer_postgres.py`,
  both of which fail against the old single-connection code (with
  `AdminShutdown` and `UndefinedTable` respectively). On kind, with the agent's
  restart count unchanged at 0 throughout: (1) terminating its four pooled
  connections, then a full run → approval → resume → issued; and (2) deleting the
  Postgres pod — new `emptyDir`, `\dt` showing *no* relations — then the same full
  run, which recreated all eight tables on demand.
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

## Not slices (documented limits)

- The trust domain (`acme.com`) and the demo passwords are documentation, not
  configuration to change.
- The mesh proxy is a native sidecar, so `kubectl exec` may need `-c <container>`.
