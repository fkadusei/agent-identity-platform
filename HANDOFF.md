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
  beyond the original plan. The 2026-09-16 gateway outage is fixed — see S13 and
  S15 in [`docs/backlog.md`](docs/backlog.md). **S18** taught the agent to ask for a
  missing argument instead of refusing, **S19** lets it take more than one bounded
  step, **S20** stops it inventing an identifier, and **S21** stops "allowed" reading
  as "it happened"; the agent-upgrade work is complete, and **S22** writes down what
  that loop now keeps and re-exposes. **S17** (cloud providers) is the one open
  slice.
- **Repo:** `github.com/fkadusei/agent-identity-platform` — **public**, MIT.
- **Last updated:** 2026-09-25

## Resuming work in a fresh session

A new session needs **none** of the previous conversation. In order:

1. **Read this file and [`docs/backlog.md`](docs/backlog.md).** The slice entries
   carry what each change was, why, and how it was verified — that is the memory.
2. **Check the tree is what you think it is:** `git log --oneline -1`, `git status`,
   and `./scripts/check-images.sh` (the cluster must be stamped at HEAD; see the
   gotcha below).
3. **Run the suites before changing anything** (next section), so a failure is
   theirs and not yours.
4. **Take the next item from "Immediate next task"** and follow the house rhythm:
   branch → PR → the ten required checks → squash merge → rebuild the six images
   from a clean HEAD → verify on the cluster.
5. **If a change alters behaviour a page describes, change the page in the same
   PR** — `scripts/check-docs-pages.py` enforces it, including that quoted code
   still matches its source.

What a fresh session does *not* have is the reasoning from the conversation that
produced the code. That is exactly why decisions are written where they belong —
ADRs, backlog entries, the pages, commit messages — rather than only in chat. When
a session ends with something only in the transcript, write it down first; the next
one will not have this one's memory.

## Resume in 60 seconds

```sh
./start.sh          # brings it up (builds on first run, resumes after) + prints the URL
./status.sh         # is it up? how many pods ready? what URL?
./stop.sh           # stop it (keeps data); ./stop.sh --delete removes the cluster
```

Then open **https://localhost:8443**. Demo users:

> The certificate is one `setup.sh` generates, not a public CA's — the browser
> will ask you to trust it once (import `.edge/ca.crt`, gitignored). The command
> line equivalents below all use `--cacert .edge/ca.crt`; nothing uses `-k`.
> TLS terminates at the ingress, not on the api's own listener (S7b).

| user | password | role | can |
| --- | --- | --- | --- |
| `alice` | `alice123` | support_rep | everything but PII |
| `bella` | `bella123` | billing | orders + refunds only |
| `dana` | `dana1234` | read_only | reads only |
| `priya` | `priya123` | privacy | reads PII (with approval) + the basic reads |
| `manager` | `manager123` | manager | reads + refund quotes; approves |
| `admin` | `admin123` | platform_admin | administers users; no tools, no approvals |
| `grace` | `grace123` | support_rep (tenant `globex`) | the second tenant |

## Test everything

```sh
.venv/bin/python -m pytest -q          # app: 244 passed (23 Postgres tests skip)
sdk/.venv/bin/python -m pytest sdk -q  # SDK: 34 passed (quiet config: no summary line,
                                       #   so check the exit code or count the dots)
docker run --rm -v "$PWD":/w -w /w openpolicyagent/opa:1.9.0 test policy/   # policy: 45 passed
python3 scripts/check-docs-pages.py    # the pages: nav, links, and every quoted line
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
./scripts/tls-check.sh      # mesh edges mTLS, SPIFFE hops named, the browser edge verified
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
  sandbox service that keeps its own state on a volume, so a restart continues the
  demo (S9, `docs/integrations.md`).
- **Adoption guide** (`docs/real-world-adoption.md`).

**Since then (beyond the original plan).**
- **Multi-tenant isolation (threat T9)** and **tenancy depth** — the tenant is an
  identity attribute; policy denies an unscoped caller; every data accessor scopes
  by tenant; approvals are tenant-scoped (`docs/tenancy.md`).
- **TLS/mTLS everywhere** — SPIFFE (with a named caller) on every hop between
  workloads we own, a service mesh (Linkerd) for the third-party and simulated
  hops, **and the browser edge terminated at an ingress with a certificate we
  generate and verify** (S7b). The boundary is recorded in ADR-0012
  (`docs/tls.md`).
- **HA for the app tier** — api/tools/agent/gateway/opa at 2 replicas with
  anti-affinity and PodDisruptionBudgets (`docs/ha.md`).
- **Autoscaling** — those services scale 2→5, and the api also on the **approval
  backlog** and per-pod request rate through a Prometheus adapter (S6,
  `docs/autoscaling.md`).
- **Role → tool matrix, per tenant** (S8) — a default table in the policy plus
  per-tenant overrides that replace it per role; the agent offers only the
  permitted tools (asked for the caller's tenant) and refuses deterministically
  otherwise; the tool server enforces (`docs/roles-and-tools.md`).
- **A Roles & tools page** in the UI, driven by the policy, showing the caller's
  own tenant's matrix.
- **Honest failure reporting** — an unreachable model, an unparseable reply and a
  bad choice are now distinct messages (S13), and the gateway no longer serves an
  expired SVID (S15).
- **Durable identity and data** — SPIRE's registry lives in Postgres with its keys
  on a PVC (S1), and the demo database is on a PVC (S3), so restarting either pod
  no longer resets the platform ([`docs/data-stores.md`](docs/data-stores.md)).
- **The identity tier can be a failover pair (S1, completed)** — the KeyManager is
  switchable: `disk` by default, `aws_kms` when a shared CA is needed, with the
  credential passed as a profile that assumes a role whose only power is the KMS
  actions it needs. Exercised against a live AWS KMS: two replicas serving one trust
  bundle, and after deleting a replica a workload fetched a fresh SVID with no
  workload restarted (`docs/ha.md`).
- **Self-healing** — every container has a liveness probe (S16), so a *hung*
  process is restarted rather than reported forever. Verified by hanging fifteen of
  them and watching each recover; the gateway needed a health-only listener, because
  an mTLS-only service cannot be checked by a kubelet that has no SVID.

## Immediate next task

Phases 1–3 are complete, every threat is addressed, and **S1–S22 are done**. What
remains is one open slice and two loose ends — all three are small and each is
written up where it lands:

1. **S17 — provider-agnostic models** (the only open slice). Two defects in the
   hosted-provider branch, both found by reading it: the forwarder sends no model,
   and it forwards a JSON hint a strict provider may reject. The *interesting* half
   is the policy question: may a cloud model see the personal data the agent can
   read under approval? Local-only means it cannot, today. **S22** documented the
   concrete case that turns on — a multi-step run re-exposes a `privacy.pii.read`
   result to whichever model the gateway points at — and deliberately left the
   control here.
2. **`demo-roles.sh` is flaky** (roughly one run in five, right after a restart):
   the client scripts use `timeout=10` on the login/admin calls while the model call
   gets 60, so a cold first call can time out. A one-line hardening — raise them, or
   retry once — settles it. See Known issues.
3. **S1's KMS mode is off by default.** It is one line in `.env`, verified against a
   live key, and documented in [`docs/ha.md`](docs/ha.md) and question 12 of the
   pages. No action unless you want HA identity on by default.

Done, kept for the record:
 **S1** (SPIRE's registry is durable, and the KeyManager is
switchable with the KMS path verified against a live account), **S2** (Keycloak replicated against
Postgres), **S3** (a persistent Postgres volume), **S4** (Keycloak hardened —
no `start-dev`, no Trivy exception), **S5** (guardrails + evals,
`docs/guardrails-and-evals.md`), **S6** (custom-metric autoscaling), **S7** (SPIFFE
on every hop we own), **S7b** (TLS for the browser edge), **S8** (per-tenant role →
tool maps), **S9** (the sandbox keeps its own data), **S10** (the privacy view,
`docs/privacy.md`),
**S11** (SPIRE survives an API-server blip), **S12** (the agent survives a
Postgres restart), **S13** (stop blaming the model for infrastructure faults),
**S14** (the scripts pin their cluster context), **S15** (the gateway must not
serve an expired SVID), **S16** (a hung process restarts itself), **S18** (the
agent asks for a missing argument instead of refusing), **S19** (the agent
takes more than one bounded step), **S20** (the agent passes identifiers along
instead of inventing them), **S21** (a tool's own "no" is reported and
recorded, instead of a bare "allowed") and **S22** (what the loop keeps and
re-exposes is written down and accepted, not prevented).

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
- ADR-0012 Transport identity: SPIFFE for the workloads we own, the mesh for the rest

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

- **`demo-roles.sh` can time out once, right after a restart.** The client scripts
  use `timeout=10` on the login and admin calls (`scripts/roles_client.py` and its
  siblings) while the model call gets 60s, so a cold first call loses the race. It
  passed 5–6 runs in a row once warm, and re-running clears it. Fix (not done):
  raise those timeouts, or retry once. Seen intermittently; not a correctness bug.
- **Keycloak is durable now** (S2): its realm and users live in Postgres, the
  realm is imported by a Job with `--override=false`, and `setup.sh` no longer
  recreates it — so accounts enrolled at runtime survive a re-run. Consequence,
  named on purpose: rotating a client secret in `.env` does **not** reach an
  existing realm. Delete the realm (or the `keycloak` database) and re-run to pick
  a new secret up.
- **Keycloak runs in production mode** (S4) from `docker/keycloak.Dockerfile`,
  which bakes `kc.sh build` so the server starts with `--optimized` and a read-only
  root filesystem. Its listener is HTTP on purpose: the mesh carries the mTLS
  in-cluster and the ingress owns the browser edge (S7b).
- **OPA bundle:** the files are mounted with `subPath`, which does not update in
  place — `setup.sh` restarts OPA after a new revision.
- **SPIRE's state is durable now** (S1): the registration registry lives in
  Postgres (a dedicated `spire` database and role) and the disk KeyManager's keys
  are on a PVC, so killing the server pod keeps the **same CA and the same
  entries** — no workload restart. Registration entries are still created **per
  attested agent**, or workloads on other nodes get no identity. Two replicas
  remain impossible without a shared KeyManager (a cloud KMS).
- **Postgres is on SPIRE's critical path** now: identity needs the database, so a
  Postgres outage stops new SVIDs. That is why production points `database.url` at
  a managed, HA database.
- **The trust bundle is *published*, not notified** (S11). SPIRE 1.12.4 writes
  the `spire-bundle` ConfigMap on a 30-second tick; a failure is logged and
  retried, never fatal. A cluster upgraded from the old Notifier still has its
  field ownership, so publishing fails with `Apply failed with 1 conflict` until
  the ConfigMap is recreated — `setup.sh` does that.
- **Postgres is durable now** (S3): its data is on a `PersistentVolumeClaim`, so
  approvals, checkpoints, gateway counters and the audit trail survive deleting
  the pod and a `setup.sh` re-run. The volume is node-local (kind's `local-path`),
  so the pod cannot be rescheduled to another node, and `./stop.sh --delete`
  removes it. Production points `database.url` at a managed database.
- **A hop must be named.** A machine call that presents no JWT-SVID is refused with
  `workload identity rejected` — that is the control, not a fault. The manifests set
  `WORKLOAD_AUDIENCE`; the SPIFFE port must also skip the mesh proxy
  (`skip-inbound/outbound-ports: "8443"`), or Linkerd terminates the connection and
  the peer's SVID never reaches the server.
- **The browser edge is an ingress, with a certificate we generate** (S7b). The CA
  lives in the gitignored `.edge/` and carries `basicConstraints` + `keyUsage`:
  without them curl accepts the chain and strict clients (Python/OpenSSL 3) refuse
  it — a mistake worth not repeating, and `tls-check.sh` now asserts it.
  `start.sh` forwards the **controller** (`svc/ingress-nginx-controller`), never the
  api, so the API's own listener is not exposed to the host; `stop.sh` clears both.
  One residual remains: ingress→api:8080 is plaintext in-cluster, because the
  controller carries no sidecar.
- **A readiness probe is not a restart.** A hung process stays `Running` and never
  `Ready`: jaeger did exactly that for 31 hours, logging nothing, and `setup.sh`'s
  rollout gate could not finish until a human restarted it. Every container has a
  liveness probe now (S16), so this class of hang heals itself — but the thresholds
  are unhurried on purpose (a restart is not free), and a *too* eager one turns a
  slow start into a restart loop.
- **You cannot hang a container's PID 1 from inside it.** `kubectl exec <pod> --
  kill -STOP 1` is a no-op: signals to a PID-namespace init process from inside the
  namespace are discarded (the protection that stops a container killing itself),
  and the process stays in state `S`. To test a probe, signal from the node and pick
  the process by cgroup — the S16 verification script's approach. The first attempt
  at it "passed" by doing nothing at all.
- **Role changes lag** by up to one token lifetime (5 minutes).
- **The approval backlog is read from the store at scrape time**, not accumulated
  in the api process (S6). A gauge written per replica on change means only the
  replica that handled it moves, and `max()` across replicas then follows a stale
  queue — the api stayed at 5 replicas after the queue was drained until this was
  fixed. If you add a metric for an autoscaler, make it answer "what is true now",
  not "what did this process last see".
- **Prometheus scrapes the api per pod** (S6): the counters are per-process, so
  scraping through the Service round-robins between replicas and makes `rate()`
  meaningless — and a `Pods`-type HPA needs the `pod` label.
- **The gateway cannot be scraped.** It serves only mTLS with an SVID, and
  Prometheus holds no SVID — so it has no metrics endpoint to read and nothing to
  autoscale on beyond CPU. Giving it one is a design decision, not a config
  change: a listener for scraping, an SVID for Prometheus, or a signal derived
  from the audit stream it already sends to the api.
- **Every script pins its cluster.** `scripts/lib.sh` wraps `kubectl` with
  `--context kind-agent-platform` (override with `KUBE_CONTEXT`), and no script
  changes your active context any more. For bare `kubectl` against the demo
  cluster, set the context yourself.
- **Two replicas, two different pods.** `kubectl exec deploy/agent` and
  `kubectl logs deploy/agent` can land on different replicas, so an eval run and
  its logs appear to disagree. Name the pod
  (`get pods -l app=<name>`) when diagnosing.
- **The gateway restarts itself** to refresh its SVID, and the restart is derived
  from the certificate's own expiry — `gateway.svid_loaded` reports
  `expires_in_seconds` at startup. Invisible behind two replicas and a
  PodDisruptionBudget, but do not read a gateway restart as a crash.
- **A failed run says so.** The agent never substitutes a tool the role may not
  call; it reports that nothing was executed — and now says *why*: an unreachable
  model, an unparseable reply and a bad choice are different messages (S13).

## Key files map

| Path | What it is |
|---|---|
| `start.sh` / `status.sh` / `stop.sh` | one-command bring-up / check / stop |
| `SECURITY.md` | security invariants + private reporting |
| `CONTRIBUTING.md` | how to contribute |
| `docs/threat-model.md` | 11 threats, mitigations, and the test for each |
| `docs/roles-and-tools.md` | the role → tool matrix |
| `docs/guardrails-and-evals.md` | the agent's guardrails and the eval suite |
| `docs/privacy.md` | the PII tool, its approval gate, the access trail |
| `docs/tenancy.md` | tenant isolation, at every layer |
| `docs/tls.md` | transport security (SPIFFE + mesh + the browser edge) |
| `docs/ha.md`, `docs/autoscaling.md` | redundancy and scaling |
| `docs/llm-gateway.md` | the gateway, identity, rate/cost limits |
| `docs/data-stores.md` | durable state (Postgres) |
| `docs/operator-guide.md` | the runbook |
| `docs/real-world-adoption.md` | adoption guide + production checklist |
| `docs/roadmap.md` | phase checklist + backlog |
| `docs/decisions/` | ADRs 0001–0012 |
| `docs/guides/` | plain-language user guides |
| `docs/site/` | the living HTML pages — see "Living documentation" below |
| `docs/visualization/` | HTML diagrams — the 3D architecture (`index.html`) and the S7 transport plan |
| `scripts/` | setup, demo, and the verification suites |

## Living documentation

`docs/site/` holds navigable pages that explain the platform **with the code that
does it**. They are not a snapshot and not a separate effort: they are part of
each slice, and the rule is the same one the rest of the repo follows — *if the
behaviour changed, the page that describes it changes in the same PR*.

| Page | Covers |
|---|---|
| `index.html` | The whole platform, plain language, twenty sections |
| `agent-flow.html` | The agent end to end: the graph, the prompt, the guardrails, the tool boundary, the interrupt, the policy decision — including the upgrade (S18–S19), marked built where it is built |
| `questions.html` | The questions asked while learning the platform, answered from the code: the user store, one agent, how approvals work, disk vs KMS, and more |

There are no numbers in the list above and nothing to renumber: add a page, link
it from the one it extends, and it is part of the set.

To read them:
```sh
python3 -m http.server 8081 --directory docs/site    # → http://localhost:8081
# or just open docs/site/index.html — no build, no CDN, no network
```

House rules for a page, enforced by `scripts/check-docs-pages.py` (runs in CI):

- **Self-contained.** Inline CSS/JS, no build step, no CDN, no fonts to fetch.
  It must work from `file://`.
- **Quoted code is quoted.** A code block whose caption names a file must match
  that file line for line. A block that is a sketch must say *illustrative* or
  *commands* in its caption — so a reader can always tell code from a sketch, and
  a sketch cannot drift into looking like code.
- **Cross-linked.** A new page links back to the page it extends, and that page
  links forward to it.
- **Same visual language.** Dark by default, light one attribute away; sidebar +
  scroll-spy + filter + copy; print styles that drop the chrome.
- **The check can fail.** Before trusting it, break a nav link and a quoted line
  and watch it complain — the same discipline the other suites follow.

## How to verify

```sh
./scripts/scan-secrets.sh      # expect: no leaks in tree or history
./status.sh                    # expect: cluster up, pods ready, the URL
python3 scripts/check-docs-pages.py   # expect: pages consistent, quoted lines match
# the pre-commit hook, self-tested (the literal below is not secret-shaped):
printf 'LLM_API_KEY=sk-%s\n' "$(printf 'A%.0s' $(seq 1 24))" > t.txt
git add t.txt && .githooks/pre-commit; echo "exit=$? (expect 1)"; git reset -q t.txt; rm -f t.txt
```
