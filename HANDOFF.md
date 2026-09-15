# HANDOFF

**The resume-here document.** Updated at the end of every work session.

> Machine-specific notes (absolute paths, local tool locations, the SSH signing
> setup) live in `NOTES.md`, which is **gitignored** — this file is the
> project-level record.

---

- **Project:** agent-identity-platform — an identity and authorization layer for
  AI agents (SPIFFE workload identity → OAuth delegation → OPA authorization →
  human approval → audit, with tenancy).
- **Status:** **Phases 1–3 complete**, both gates closed, and **every threat in
  the threat model addressed**. The platform runs end to end on a 3-node
  Kubernetes cluster (kind) and has grown a set of production-hardening slices
  beyond the original plan.
- **Repo:** `github.com/fkadusei/agent-identity-platform` — **public**, MIT.
- **Last updated:** 2026-09-14

## Resume in 60 seconds

```sh
./start.sh          # brings it up (builds on first run, resumes after) + prints the URL
./status.sh         # is it up? how many pods ready? what URL?
./stop.sh           # stop it (keeps data); ./stop.sh --delete removes the cluster
```

Then open **http://localhost:8080**. Demo users:

| user | password | role | can |
| --- | --- | --- | --- |
| `alice` | `alice123` | support_rep | everything but PII |
| `bella` | `bella123` | billing | orders + refunds only |
| `dana` | `dana1234` | read_only | reads only |
| `manager` | `manager123` | manager | reads + refund quotes; approves |
| `admin` | `admin123` | platform_admin | administers users; no tools, no approvals |
| `grace` | `grace123` | support_rep (tenant `globex`) | the second tenant |

## Test everything

```sh
.venv/bin/python -m pytest -q          # app: 118 passed (14 Postgres tests skip)
sdk/.venv/bin/python -m pytest sdk -q  # SDK: 34 passed
opa test policy/                       # policy: 31 passed
```

The Postgres-backed tests **skip** without a database. To run them:

```sh
docker run -d --rm --name ap-test-pg -e POSTGRES_DB=agent_platform \
  -e POSTGRES_USER=agent -e POSTGRES_PASSWORD=agent -p 55432:5432 postgres:17-alpine
PGHOST=localhost PGPORT=55432 PGUSER=agent PGPASSWORD=agent PGDATABASE=agent_platform \
  .venv/bin/python -m pytest -q
docker rm -f ap-test-pg
```

End-to-end, on the cluster:

```sh
./scripts/demo.sh           # read -> $200 refund -> approval -> issued
./scripts/attack-tests.sh   # all six attacks blocked
./scripts/tenancy-tests.sh  # tenant isolation: claim -> policy -> data
./scripts/role-tools.sh     # who may call which tool (no LLM)
./scripts/tls-check.sh      # every in-cluster edge is mTLS
./scripts/ha-check.sh       # replicas spread; an eviction is survivable
./logs.sh --last            # a trace of every interaction
```

## What is built

**Phase 1 — the platform.**
- `sdk/agentnhi/` — identity (SVIDs), RFC 8693 exchange, token verification
  (`aud` + `azp`), policy client (fail-closed), audit (redaction).
- `policy/authz.rego` — role → tool matrix; allow / deny / require-approval;
  deny-by-default.
- `app/simulators/` — synthetic CRM/orders/payments/ticketing.
- `app/tools/` — the policy enforcement point (HTTP + MCP transports).
- `app/approvals/` + `app/api/` — approvals, tasks, audit, login/enrollment,
  user administration.
- `app/agent/` — LangGraph with approval interrupts.
- `app/web/` — the React UI (console, approvals, **roles**, audit, admin).
- `deploy/kind/` + `scripts/` — the local cluster and the demo suites.

**Phase 2 — hardening.**
- **LLM gateway** (`app/gateway/`) — SPIFFE mTLS; the agent holds no model
  credential. Per-agent rate and cost limits, keyed on the caller's
  JWT-SVID-proven SPIFFE ID, durable in Postgres (`docs/llm-gateway.md`).
- **Secrets out of git/manifests** — generated into a gitignored `.env`, rendered
  into the realm, mounted as Secrets (`docs/secrets.md`).
- **Observability** — OpenTelemetry traces with identity attributes → collector →
  Jaeger; platform metrics → Prometheus → a provisioned Grafana dashboard
  (`docs/observability.md`).
- **Policy lifecycle** — a versioned bundle; every decision names its revision
  (`docs/policy-lifecycle.md`).
- **Supply chain** — keyless cosign signing + a Kyverno admission policy
  (`docs/supply-chain.md`, ADR-0010).
- **Enrollment + role administration** — self-service signup (toggleable), admin
  user management via a least-privilege Keycloak service account, real login,
  server-side role enforcement (ADR-0011, `docs/enrollment-and-roles.md`).
- **UI polish**, and the **operator guide** (`docs/operator-guide.md`).

**Phase 3 — deploy and adoption.**
- **Helm chart** (`deploy/helm/agent-platform`) — values-driven, ingress/TLS.
- **CI/CD with an approval gate** — `release.yml` builds/signs images, the bundle
  and the chart; `deploy.yml` verifies signatures and applies the chart behind a
  GitHub Environment approval gate (`docs/ci-cd.md`).
- **Managed data stores** — approvals and run checkpoints durable in Postgres
  (`docs/data-stores.md`).
- **Real sandbox integrations** — a backend seam (simulator | HTTP) plus a
  sandbox service (`docs/integrations.md`).
- **Adoption guide** (`docs/real-world-adoption.md`).

**Since then (beyond the original plan).**
- **Multi-tenant isolation (threat T9)** and **tenancy depth** — the tenant is an
  identity attribute; policy denies an unscoped caller; every data accessor scopes
  by tenant; approvals are tenant-scoped (`docs/tenancy.md`).
- **TLS/mTLS everywhere** — SPIFFE mTLS on agent↔gateway plus a service mesh
  (Linkerd) for every other in-cluster hop (`docs/tls.md`).
- **HA for the app tier** — api/tools/agent/gateway/opa at 2 replicas with
  anti-affinity and PodDisruptionBudgets (`docs/ha.md`).
- **Autoscaling** — those services scale 2→5 on CPU (`docs/autoscaling.md`).
- **Role → tool matrix** — an explicit table in the policy; the agent offers only
  the permitted tools and refuses deterministically otherwise; the tool server
  enforces (`docs/roles-and-tools.md`).
- **A Roles & tools page** in the UI, driven by the policy.

## Immediate next task

Phases 1–3 are complete and every threat is addressed. Next, pick from the open
backlog in [`docs/roadmap.md`](docs/roadmap.md#backlog--known-gaps):

Each remaining slice has a stable ID — see
[`docs/backlog.md`](docs/backlog.md) (S1–S10) for what it is, why, where it lands
and how we would verify it:

- **S1–S3** HA for the stateful components (SPIRE, Keycloak, Postgres) and
  persistent storage — the app tier is already replicated (`docs/ha.md`);
- **S4** hardened Keycloak (production mode, TLS, no `start-dev`);
- **S6** custom-metric autoscaling (CPU autoscaling is done);
- **S7** SPIFFE-native transport on every hop, and ingress TLS for the browser;
- **S8** per-tenant role → tool maps;
- **S9** durable sandbox/simulator state;
- **S10** a purpose-built privacy view (the privacy role and PII flow exist).

S5 (guardrails + evals) is done — see `docs/guardrails-and-evals.md`.

## The repository is public

- **No secrets, ever.** `.env` is gitignored and generated; the realm is rendered
  from `realm.json.tmpl`; CI fails if `.env` is tracked, and gitleaks scans the
  tree and the full history (`./scripts/scan-secrets.sh`). The demo passwords and
  the trust domain (`acme.com`) are documentation, not credentials.
- **Everything here is synthetic.** No real customer data, no card data — see
  [`docs/data-handling.md`](docs/data-handling.md).
- **Security reports** go through GitHub's *Report a vulnerability* (private
  advisory), never a public issue — see [`SECURITY.md`](SECURITY.md).
- **Contributions** follow [`CONTRIBUTING.md`](CONTRIBUTING.md); `main` is
  branch-protected.
- The docs are written to be read by strangers: they explain the *why*, name the
  trade-offs, and mark what is deliberately **not** implemented.

## Decisions made

Recorded as ADRs in [`docs/decisions/`](docs/decisions/):

- ADR-0001 SPIFFE/SPIRE for workload identity
- ADR-0002 Keycloak Standard Token Exchange V2 (+ `jti` plugin, no-cache agent)
- ADR-0003 OPA policy: allow / deny / require-approval
- ADR-0004 LangGraph for the stateful agent and human-in-the-loop
- ADR-0005 MCP as the tool boundary
- ADR-0006 Synthetic data only + PCI-aware scoping
- ADR-0007 Security baseline and repository governance
- ADR-0008 Documentation and handoff strategy
- ADR-0009 Provider-agnostic LLM + identity-authenticated gateway
- ADR-0010 Supply-chain signing with cosign (keyless Sigstore)
- ADR-0011 Self-service enrollment and role administration

## Governance (as configured)

- **`main` is branch-protected:** PR-only, 0 required approvals (the owner
  self-merges), no force-push, no deletions, linear history, conversation
  resolution, enforced for admins.
- **All 10 CI checks are required** on `main`, so a failing check blocks the merge:
  `app-tests, dependencies, helm, opa-tests, repo-checks, sast, sdk-tests,
  secrets, supply-chain, web-build`.
- **Commits are signed** (SSH) and GitHub-verified.

```sh
git switch -c feat/short-name
git push -u origin HEAD
gh pr create --fill
gh pr merge --squash --delete-branch     # linear history => squash/rebase only
```

## Known issues / gotchas

- **Keycloak re-import:** `setup.sh` recreates Keycloak each run (ephemeral H2,
  `IGNORE_EXISTING`), so accounts enrolled at runtime are lost. The realm file is
  the source of truth.
- **OPA bundle:** the files are mounted with `subPath`, which does not update in
  place — `setup.sh` restarts OPA after a new revision.
- **SPIRE datastore** is an `emptyDir`: a SPIRE-server restart forgets its agents
  and entries; a `setup.sh` re-run restores them. Registration entries are created
  **per attested agent**, or workloads on other nodes get no identity.
- **Role changes lag** by up to one token lifetime (5 minutes).
- **A failed run says so.** The agent never substitutes a tool the role may not
  call; it reports that nothing was executed.

## Key files map

| Path | What it is |
|---|---|
| `start.sh` / `status.sh` / `stop.sh` | one-command bring-up / check / stop |
| `SECURITY.md` | security invariants + private reporting |
| `CONTRIBUTING.md` | how to contribute |
| `docs/threat-model.md` | 10 threats, mitigations, and the test for each |
| `docs/roles-and-tools.md` | the role → tool matrix |
| `docs/tenancy.md` | tenant isolation, at every layer |
| `docs/tls.md` | transport security (SPIFFE + mesh) |
| `docs/ha.md`, `docs/autoscaling.md` | redundancy and scaling |
| `docs/llm-gateway.md` | the gateway, identity, rate/cost limits |
| `docs/data-stores.md` | durable state (Postgres) |
| `docs/operator-guide.md` | the runbook |
| `docs/real-world-adoption.md` | adoption guide + production checklist |
| `docs/roadmap.md` | phase checklist + backlog |
| `docs/decisions/` | ADRs 0001–0011 |
| `docs/guides/` | plain-language user guides |
| `docs/visualization/index.html` | interactive 3D architecture (open by double-click) |
| `scripts/` | setup, demo, and the verification suites |

## How to verify

```sh
./scripts/scan-secrets.sh      # expect: no leaks in tree or history
./status.sh                    # expect: cluster up, pods ready, the URL
# the pre-commit hook, self-tested (the literal below is not secret-shaped):
printf 'LLM_API_KEY=sk-%s\n' "$(printf 'A%.0s' $(seq 1 24))" > t.txt
git add t.txt && .githooks/pre-commit; echo "exit=$? (expect 1)"; git reset -q t.txt; rm -f t.txt
```
