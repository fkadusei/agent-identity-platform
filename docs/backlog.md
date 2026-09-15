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

## S5 — Agent guardrails + evals

- **What:** input/output guardrails on the agent, and an evaluation suite (a set
  of tasks with expected tool/decision) run in CI.
- **Why:** the last unbuilt Phase 2 feature. Policy constrains what the agent may
  *do*; nothing yet constrains what it may be *asked*, or measures whether it
  picks the right tool.
- **Lands in:** `app/agent/`, `app/tests/`, CI.
- **Verified by:** the eval suite failing when the model picks the wrong tool.

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

## S9 — Durable sandbox / simulator state

- **What:** persist the synthetic data so it survives a restart, or make the
  sandbox stateless.
- **Why:** the sandbox holds its data in memory, so a restart resets every refund
  and draft — fine for a demo, confusing mid-demo.
- **Lands in:** `app/sandbox/`, `app/simulators/`.
- **Verified by:** issue a refund, restart the sandbox, list refunds.

## S10 — Privacy use case, end to end

- **Partly done.** The `privacy` role, the PII tool and its approval gate exist,
  and the console now offers a role-appropriate PII task; the seeded `priya` user
  makes it reachable. **Open:** a purpose-built view (who has looked at PII, why,
  and the approval trail), rather than reusing the generic approval queue.
- **Lands in:** `app/web/`, `app/api/` (an audit filter by tool/decision).
- **Verified by:** reading PII as `priya`, approving as the manager, and seeing it
  in a PII-specific view.

---

## Not slices (documented limits)

- The trust domain (`acme.com`) and the demo passwords are documentation, not
  configuration to change.
- The mesh proxy is a native sidecar, so `kubectl exec` may need `-c <container>`.
