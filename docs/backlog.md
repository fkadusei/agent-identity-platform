# Backlog

Every slice we have **not** built yet, with a stable ID so it can be referenced
("do S3"), what it is, why it matters, where it lands, and how we would know it
works. The phase history lives in [`roadmap.md`](roadmap.md).

Legend: **open** · *partly done* (say which half).

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
- **Lands in:** `policy/authz.rego` (key on tenant), the realm.
- **Verified by:** the same role in two tenants getting different tools.

## S9 — Durable sandbox / simulated-system state

- **What:** persist the synthetic data so it survives a restart, or make the
  sandbox stateless.
- **Why:** the sandbox holds its data in memory, so a restart resets every refund
  and draft — fine for a demo, confusing mid-demo.
- **Lands in:** `app/sandbox/`, `app/simulators/`.
- **Verified by:** issue a refund, restart the sandbox, list refunds.

## S10 — Privacy use case, end to end

- **Partly done.** The `privacy` role, the PII tool and its approval gate exist,
  and the console offers a role-appropriate PII task. The purpose-built view now
  exists too: `GET /privacy/access` (manager only) and the **Privacy** tab show
  the PII access trail — held / allowed / denied, with the policy reason and
  bundle revision — next to the approval trail. `GET /audit` gained
  `?event=&tool=&sub=` filters. See [`privacy.md`](privacy.md).
- **Open — and this is the gate for calling S10 done:** the view reads an
  in-memory, per-replica audit deque, so with two API replicas it is *partial*
  (measured: the two pods held 8 and 7 different events) and a restart clears it.
  An oversight view that silently misses events is worse than none. Fix: move
  audit events into the durable store the approvals already use
  (`app/approvals/store.py` has the pattern). The **Audit** tab has the same flaw.
- **Open (smaller):** an agent-side refusal leaves no trace. `alice` asking for
  PII is refused *before* the tool server (the agent is only offered permitted
  tools), so no `tool.denied` exists, the refusal is not audited, and the run
  reports `status: "error"` rather than a refusal.
- **Lands in:** `app/web/`, `app/api/`, and (for the durable store) `app/common/`.
- **Verified by:** reading PII as `priya`, approving as the manager, and seeing it
  in a PII-specific view. **Confirmed on kind**; the two limits above were found
  by verifying it rather than by reading the code.

---

## Not slices (documented limits)

- The trust domain (`acme.com`) and the demo passwords are documentation, not
  configuration to change.
- The mesh proxy is a native sidecar, so `kubectl exec` may need `-c <container>`.
