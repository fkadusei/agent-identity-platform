# Roadmap

Living checklist. Updated at the end of every work session (see
[`../HANDOFF.md`](../HANDOFF.md)). A phase is done only when its gate passes.

Legend: `[x]` done · `[~]` in progress · `[ ]` not started

---

## Phase 0 — Foundations, security, documentation

- [x] Repo scaffolded at `agent-identity-platform/`
- [x] Security baseline: `.gitignore`, `.gitleaks.toml`, pre-commit hook,
      `scripts/install-hooks.sh`, `scripts/scan-secrets.sh`, `.env.example`,
      `SECURITY.md`
- [x] CI security workflow (`security.yml`) + repo checks (`ci.yml`)
- [x] Verified the hook blocks a test secret and gitleaks finds no leaks
- [x] ADRs 0001–0010 recorded
- [x] `docs/threat-model.md`, `docs/data-handling.md`, `docs/glossary.md`,
      `CONTRIBUTING.md`
- [x] `docs/real-world-adoption.md` (draft)
- [x] `docs/visualization/index.html` — interactive 3D architecture (light/dark)
- [x] `README.md`, `HANDOFF.md`, `LICENSE`
- [x] Cross-links with `enterprise-agent-nhi`
- [x] Git repo created and pushed
- [ ] **Gate:** security DoD met, plan + adoption doc reviewed by owner

## Phase 1 — Reusable core + realistic local app

- [ ] Extract `sdk/agentnhi/` from the concepts demo (typed, unit-tested):
      SVID fetch, mTLS, token exchange, verification, OPA client, audit
- [ ] Synthetic simulators: CRM, orders, payments, ticketing
- [ ] MCP tool servers using the SDK for auth
- [ ] LangGraph agent: planner + tool loop + **approval interrupts**
- [ ] FastAPI: sessions, tasks, approvals, audit query
- [ ] React UI: task console, approval queue, audit timeline
- [ ] OPA policy matrix (allow / deny / require-approval) + tests
- [ ] Extended attack suite (approval bypass, injection, forwarding, escalation)
- [ ] User guides: overview, support rep, approver
- [ ] **Gate:** happy path works; all attacks blocked; approval flow demonstrated

## Phase 2 — Production hardening

- [ ] TLS/mTLS everywhere; HA SPIRE; persistent storage; hardened Keycloak
- [ ] Secret manager + External Secrets (remove every static secret)
- [ ] LLM gateway authenticated by SPIFFE identity (removes the last secret)
- [ ] OpenTelemetry end-to-end; Prometheus/Grafana; audit pipeline; alerts
- [ ] Policy lifecycle (bundle CI, versioning, staged rollout, decision logs)
- [ ] Agent guardrails + evals; rate and cost limits
- [ ] Supply chain: SBOM, image scan, **cosign (keyless Sigstore) signing +
      verification**, admission policy (ADR-0010)
- [ ] Operator user guide
- [ ] **Gate:** threat model addressed; dashboards live; secret audit clean

## Phase 3 — Deploy and adoption

- [ ] Cloud-agnostic Helm chart + values; ingress/TLS; managed data stores
- [ ] CI/CD with approval gates
- [ ] Real sandbox integrations behind the existing tool interfaces
- [ ] Finalize `docs/real-world-adoption.md` and the runbook
- [ ] **Gate:** deployed end-to-end; runbook + adoption guide complete
