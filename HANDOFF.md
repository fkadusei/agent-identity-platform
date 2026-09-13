# HANDOFF

**The resume-here document.** Updated at the end of every work session.

---

- **Project:** agent-identity-platform
- **Status:** Phases 1–3 **complete** — both gates closed (Phase 2 hardening on
  2026-09-12; Phase 3 deploy/adoption once the platform ran end to end).
  **Phase 1:** SPIFFE identity, OAuth exchange, OPA policy, approvals, the
  LangGraph agent, the MCP tool boundary, the React UI, and the kind deployment.
  **Phase 2:** the **LLM gateway** (SPIFFE mTLS; the agent holds no model
  credential), **secrets out of git/manifests**, **observability** (OTel traces
  with identity → collector → Jaeger, plus platform metrics → Prometheus → a
  provisioned Grafana dashboard), the **policy lifecycle** (versioned bundle;
  every decision names its revision), **supply chain** (keyless cosign signing +
  Kyverno admission policy), **enrollment + role administration** (ADR-0011),
  **UI polish**, and the **operator guide** (the runbook). **Phase 3:** a
  cloud-agnostic **Helm chart** (`deploy/helm/agent-platform`) with ingress/TLS,
  **CI/CD with an approval gate** (`release.yml` + `deploy.yml`,
  `docs/ci-cd.md`), **managed data stores** (durable approvals + run checkpoints
  in Postgres, `docs/data-stores.md`), **real sandbox integrations** (a backend
  seam + sandbox service, `docs/integrations.md`), and the finalized
  **adoption guide** (`docs/real-world-adoption.md`). Since then: **multi-tenant
  isolation (threat T9)** — the tenant is an identity attribute, policy denies an
  unscoped caller, and every data accessor scopes by tenant (`docs/tenancy.md`,
  `scripts/tenancy-tests.sh`). Then **TLS/mTLS everywhere**: SPIFFE mTLS on
  agent↔gateway plus a service mesh (Linkerd) for every other in-cluster hop,
  Keycloak, OPA and the observability stack included (`docs/tls.md`,
  `scripts/tls-check.sh`). Then **per-agent rate and cost limits** at the LLM
  gateway, keyed on the caller's JWT-SVID-proven SPIFFE ID (`docs/llm-gateway.md`).
  The threat model is fully addressed.
- **Last updated:** 2026-09-13
- **Last updated:** 2026-09-12
- **Repo:** `github.com/fkadusei/agent-identity-platform` (private)
- **Local path:** `/Users/felixadusei/Development/AI_Engineering/OpenCode/agent-identity-platform`

## Resume in 60 seconds

```sh
cd /Users/felixadusei/Development/AI_Engineering/OpenCode/agent-identity-platform
./scripts/install-hooks.sh          # enable the secret guard (once per clone)
./scripts/scan-secrets.sh           # verify: no secrets in tree or history
git log --oneline -8                # where we are
cat docs/roadmap.md                 # what's done / next
```

Test everything that exists so far:

```sh
# SDK (identity, exchange, tokens, policy, audit) — 32 tests
cd sdk && .venv/bin/pytest && cd ..        # (or: python -m venv .venv && pip install -e sdk[dev])

# policy — 14 tests
/tmp/opa test policy/ -v                   # (or: brew install opa)

# app (simulators + tool enforcement + MCP) — 21 tests
.venv/bin/pip install -e sdk -r requirements-dev.txt
.venv/bin/python -m pytest
```

## Where we are

- **Phase 0 — complete.** Security baseline, ADRs 0001–0010, docs, governance.
- **Phase 1 — backend complete.** Merged so far (84 tests):
  - `sdk/agentnhi/` — identity, exchange, tokens (`aud`+`azp`), policy
    (fail-closed), audit (redaction) — 32 tests
  - `policy/authz.rego` — allow / deny / require-approval matrix — 14 tests
  - `app/simulators/` — synthetic CRM/orders/payments/ticketing — 10 tests
  - `app/tools/` — enforcement core + FastAPI and MCP transports — 11 tests
  - `app/approvals/` + `app/api/` — approvals store + endpoints — 13 tests
  - `app/agent/` — LangGraph with approval interrupts — 4 tests
  - `deploy/kind/` + `scripts/` — SPIRE/Keycloak/OPA + api/tools/agent on kind;
    `demo.sh` (approval flow) and `attack-tests.sh` (5 attacks blocked)
- **Next: Phase 2** — production hardening. Done so far: the **LLM gateway**
  (`app/gateway/`, SPIFFE mTLS), **secrets out of git** (`.env` +
  `docs/secrets.md`), **observability** (`app/common/telemetry.py` + the
  collector/Jaeger manifests), the **policy lifecycle**
  (`scripts/build-bundle.sh` + `docs/policy-lifecycle.md`), and **supply chain**
  (`scripts/sign-bundle.sh` + the Kyverno policy + `docs/supply-chain.md`).
  Remaining: the operator guide.

## Immediate next task

**Phases 1–3 are complete**, both gates closed, and every threat in the model is
addressed (T9 tenancy included). Next, pick from the open backlog in
[`docs/roadmap.md`](docs/roadmap.md#backlog--known-gaps):

- **HA** — SPIRE, Keycloak, OPA, Postgres and the sandbox are single-replica demos.
- **Tenancy depth** — approvals/run checkpoints are keyed by user/agent, not
  tenant; add a tenant column if those are ever shared across tenants.
- **SPIFFE-native transport** — the mesh uses Linkerd's own identity; extending
  SPIFFE mTLS to every hop (and the browser edge via ingress TLS) is a further
  step.

Note: secrets live in a gitignored `.env` (generated by `setup.sh`); the realm is
rendered from `realm.json.tmpl`. `setup.sh` recreates Keycloak each run so the
fresh realm (and its client secrets) is imported. Traces go to the in-cluster
collector (`OTEL_EXPORTER_OTLP_ENDPOINT`); `./scripts/show-trace.sh` prints the
latest end-to-end trace. The OPA bundle is built by `scripts/build-bundle.sh`
(revision stamped into every decision) and signed by `scripts/sign-bundle.sh`.

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

## Open questions / blockers

- **Signed commits** — **DONE and verified end to end.** Local
  `git log --show-signature` reports a good signature, and GitHub marks pushed
  commits **Verified** (confirmed via the commits API: `"verified": true`).
  Setup steps for other machines are in "Signed commits (one-time setup)" below.
- **Branch protection is ENABLED** on `main`: PR-only (0 required approvals, so
  the owner can self-merge), no force-push, no deletions, linear history,
  conversation resolution, enforced for admins.
  **Consequence: `main` is no longer pushable directly — changes go via a branch
  + PR:**
  ```sh
  git switch -c feat/short-name
  git push -u origin HEAD
  gh pr create --fill
  gh pr merge --squash --delete-branch     # linear history => squash/rebase only
  ```
- **GHAS** (secret scanning / CodeQL) — enable on the repo if available; the OSS
  CI tooling covers the same ground meanwhile.

## Environment & manual steps

- Local tools used: Docker, `kind`, `kubectl`, `gh`, and (optional) `gitleaks`
  at `/tmp/gitleaks` for local scans.

### Signed commits (one-time setup)

Commits must be signed. This uses **SSH signing** (simpler than GPG). The same
SSH key can be registered on GitHub **twice** — once for authentication, once
for signing — so adding it a second time is normal and expected.

**Step 1 — register the key as a SIGNING key on GitHub.** The option people miss
is the **"Key type"** dropdown on the *New SSH key* form:

1. Open <https://github.com/settings/ssh/new>
2. **Title**: e.g. `MacBook signing`
3. **Key type**: choose **Signing Key**   ← this is the dropdown you were looking for
4. **Key**: paste the contents of `~/.ssh/id_ed25519.pub`
5. Click **Add SSH key**

If you already added the key as an *Authentication Key*, add it **again** and
select *Signing Key* — one key, two registrations. (If you truly see no "Key
type" dropdown, use the URL above; it exists on the current GitHub web UI. The
mobile app does not support signing keys.)

**Step 2 — configure git.** Already done on this machine, for reference:

```sh
git config --global gpg.format ssh
git config --global user.signingkey /Users/felixadusei/.ssh/id_ed25519.pub  # absolute path: ~ does NOT expand here
git config --global commit.gpgsign true
git config --global gpg.ssh.allowedSignersFile ~/.ssh/allowed_signers      # enables local verification
```

**Step 3 — verify.**

```sh
git log --show-signature -1     # local: expect 'Good "git" signature'
# after pushing, GitHub shows a green "Verified" badge on the commit
```

If a pushed commit shows **Unverified**, the signing key is not registered on
GitHub — redo Step 1. (Signing itself is working locally; that is a separate
failure mode from the key not being registered.)

## Known issues / gotchas

- The `gh` token lacks `admin:public_key`, so adding the SSH/signing key must be
  done in the GitHub web UI (or refresh the token scope).
- Local secret scans use `/tmp/gitleaks` if `gitleaks` is not on `PATH`.
- CI: `security.yml` secret scanning always runs; SAST/dependency/image jobs are
  conditional and activate as code lands.

## Key files map

| Path | What it is |
|---|---|
| `SECURITY.md` | security invariants + reporting |
| `docs/threat-model.md` | 10 threats, mitigations, tests |
| `docs/data-handling.md` | synthetic-only rule, PII, PCI, redaction |
| `docs/roadmap.md` | phase checklist |
| `docs/real-world-adoption.md` | adoption guide (draft) |
| `docs/decisions/` | ADRs |
| `.gitleaks.toml` | secret rules + narrow allowlist |
| `.githooks/pre-commit` | local secret guard |
| `scripts/scan-secrets.sh` | tree + history scan |
| `.github/workflows/security.yml` | CI security job |
| `docs/visualization/index.html` | interactive 3D architecture (open by double-click) |

## How to verify

```sh
./scripts/scan-secrets.sh      # expect: no leaks in tree or history
# hook self-test: construct a realistic fake key at runtime, confirm it blocks
# (the literal below deliberately does not contain a secret-shaped string)
printf 'LLM_API_KEY=sk-%s\n' "$(printf 'A%.0s' $(seq 1 24))" > t.txt
git add t.txt && .githooks/pre-commit; echo "exit=$? (expect 1)"; git reset -q t.txt; rm -f t.txt
```
