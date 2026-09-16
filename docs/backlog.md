# Backlog

Every slice we have **not** built yet, with a stable ID so it can be referenced
("do S3"), what it is, why it matters, where it lands, and how we would know it
works. The phase history lives in [`roadmap.md`](roadmap.md).

Legend: **open** · *partly done* (say which half).

---

## Open right now (2026-09-16): the agent's model call is failing

The live evals score **1/8 for every model** — `llama3.2:3b` and
`qwen3-warden-ctx16k` alike — so the model is not the variable, whatever the error
message implies. The gateway can reach Ollama (`GET /api/tags -> 200`), so the
fault is on the agent-to-gateway hop or in the prompt/parse step.

**Next step:** the `llm.fallback` audit reason, which names the real cause.
**Beware:** there are two agent replicas, so `exec deploy/agent` runs the evals in
one pod while `logs deploy/agent` reads the other — pick a named pod:

```
kubectl --context kind-agent-platform -n agent-platform get pods -l app=agent
kubectl --context agent-platform ... exec <that-pod> -c agent -- python -m app.agent.evals --live
kubectl --context kind-agent-platform -n agent-platform logs <that-pod> -c agent \
  | grep -o 'llm\.[a-z_]*\|reason[^,}]\{0,150\}'
```

**What happened before this, for context.** A 45GB model (a 30B with a 262k
context) was loaded beside an 8GB Docker VM, which starved the host. The SPIRE
server could not reach the Kubernetes API server, crashed, and crash-looped for
hours; SVID rotation stopped and certificates expired, which surfaced as
`CERTIFICATE_VERIFY_FAILED` and then as "the model did not choose a usable tool".
SPIRE is fixed and the workloads have fresh SVIDs. The model was swapped to
`qwen3-warden-ctx16k` during the investigation and has been **reverted** to
`llama3.2:3b` in both the manifest and the running deployment. Docker Desktop now
has 33GB instead of 8GB.

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

## S12 — The agent must survive a Postgres restart

- **What:** the agent's run checkpointer holds a single Postgres connection. When
  Postgres restarted, that connection died and every run failed in 0.1s with
  `psycopg.OperationalError: server closed the connection unexpectedly` — forever,
  until the agent process was restarted.
- **Why:** a database restart must not require restarting the application, and the
  failure looks identical to a dozen other errors from the outside.
- **Lands in:** `app/agent/service.py` (`get_checkpointer`) — a checked pool
  (`psycopg_pool.ConnectionPool`) instead of a bare `connect(...)`.
- **Verified by:** restart Postgres, then run the evals *without* restarting the
  agent.

## S13 — Stop blaming the model for infrastructure faults

- **What:** "the model did not choose a usable tool — nothing was executed" is
  emitted for at least four unrelated causes: the model answered unusably, the
  model call raised (expired certificate, unreachable gateway), the response did
  not parse, and the model was unreachable at all. The `llm.fallback` audit event
  carries the real reason; the user-facing message does not.
- **Why:** during the 2026-09-16 incident this message pointed at the model for
  hours while the actual faults were an expired SVID and a dead database
  connection. It cost most of a debugging session.
- **Lands in:** `app/agent/llm.py` (separate the paths), `app/agent/graph.py`
  (already splits `refused` from `error` for the *decision* — carry the reason
  through too), and the timeout/connection handling in `app/agent/live.py`.
- **Verified by:** a test that makes the model call fail and asserts the message
  says the model could not be reached, rather than blaming its output.

## Not slices (documented limits)

- The trust domain (`acme.com`) and the demo passwords are documentation, not
  configuration to change.
- The mesh proxy is a native sidecar, so `kubectl exec` may need `-c <container>`.
