# Threat Model

The platform's job is to let an AI agent do useful work **without** trusting the
model, and **without** letting a single leaked value cause broad damage.

Each threat below lists the mitigation **and the test that proves it**. A
mitigation we cannot demonstrate is treated as unverified.

---

## T1 — Stolen credential impersonates a workload

**Threat.** An API key or token is exfiltrated and replayed from elsewhere.
**Mitigation.** No static workload credentials: identities are short-lived
SPIFFE SVIDs issued only after Kubernetes attests the workload (namespace +
service account). Tokens are audience-bound and expire in minutes.
**Test.** Attack suite #1: a rogue pod in the same namespace requests an identity
and receives nothing.

## T2 — Token forwarding / lateral movement

**Threat.** A captured token is passed along a chain of services.
**Mitigation.** Every hop performs its own RFC 8693 exchange for a token scoped
to exactly one audience; each resource server enforces `aud` **and** the
workload the token was issued to (`azp`). Every in-cluster hop is additionally
mTLS — app-level SPIFFE for agent↔gateway, a service mesh for the rest
(`tls.md`) — so a token cannot be passively captured on the wire.
**Test.** Attack suite #2: a valid `aud=tool-server` token replayed at the
customer API returns `403`.

## T3 — Prompt injection / model misjudgment

**Threat.** Crafted input talks the model into a harmful tool call.
**Mitigation.** The LLM only *proposes*; authorization is decided by OPA,
deny-by-default, keyed on the agent's identity and the human's identity — not on
anything the model says. High-risk actions additionally require human approval.
**Test.** Attack suite #3: the agent calls a tool it is not permitted to use and
policy refuses it.

## T4 — Approval bypass

**Threat.** A high-risk action executes without the required human approval, or
an approver approves their own request.
**Mitigation.** The graph interrupts before execution; the tool server refuses
any `require_approval` action that lacks a recorded, authenticated approval.
**Test.** Approval-bypass test: attempt to execute an approval-gated tool with no
approval, and attempt self-approval — both refused.

## T5 — Privilege escalation

**Threat.** A low-privilege user (or the agent on their behalf) performs an
action above their role.
**Mitigation.** Policy is evaluated on the *human's* role and the *agent's*
identity together; roles are least-privilege; bulk actions are denied.
**Test.** Escalation test: a support rep attempts a manager-only action — denied.

## T6 — Secret leakage into git

**Threat.** A key, token, or password is committed.
**Mitigation.** `.gitignore`, gitleaks config, a pre-commit hook, and a CI guard
that fails if `.env` is ever tracked.
**Test.** `scripts/scan-secrets.sh` (tree + full history) and
`scripts/test-hooks.sh` — run in CI — which stages a `.env` and a fake private
key in a throwaway repo and asserts the pre-commit hook blocks both (and does not
false-positive on a clean change).

## T7 — Secret/PII leakage into logs and traces

**Threat.** Tokens or personal data end up in logs, traces, or error messages.
**Mitigation.** Redaction middleware applied before emission; a denylist for
`Authorization`, `access_token`, `assertion`, `jti`; OTel attributes sanitized.
**Test.** Redaction tests assert that emitted audit/trace records contain no
tokens or PII fields.

## T8 — PII exposure via the LLM

**Threat.** Personal data is sent to an external model, or the agent reveals data
the user is not entitled to.
**Mitigation.** Synthetic data only; local model by default; a SPIFFE-
authenticated **LLM gateway** (implemented: `app/gateway/`) that is the only
egress point and holds the provider key, so the agent has no model credential;
redaction before egress and provider retention controls; PII-tagged tools gated
by policy.
**Test.** The gateway refuses connections without a client SVID (attack suite
#6); a policy test asserts PII tools require approval.

## T9 — Cross-tenant data leakage

**Threat.** A user (or the agent) accesses another tenant's data.
**Mitigation.** The tenant is an **identity** attribute, mapped into the token by
the realm and surfaced as `Delegation.tenant`. Policy denies any caller without a
tenant (fail closed); every data accessor takes the tenant and returns nothing
outside it, so another tenant's record is indistinguishable from one that does
not exist; and a signup cannot choose its own tenant. See
[`tenancy.md`](tenancy.md).
**Test.** `scripts/tenancy-tests.sh` walks claim → policy → data, and unit tests
cover each layer (`app/tests/test_simulators.py`,
`app/tools/tests/test_enforcement.py`, `app/sandbox/tests/test_sandbox.py`).

## T10 — Supply chain and CI/CD compromise

**Threat.** A malicious dependency, image, or workflow change.
**Mitigation.** Lockfiles committed; Dependabot; GitHub Actions pinned to full
commit SHAs (mutable tags can be repointed); SBOM (Syft); Trivy scans; SAST
(Semgrep); least-privilege `GITHUB_TOKEN`; no secrets in CI logs; images and the
policy bundle signed keyless (ADR-0010).
**Test.** CI jobs (`.github/workflows/security.yml`) fail on findings.

## T11 — A multi-step run retains and re-exposes what its tools returned

**Threat.** A run that makes more than one call keeps what each call returned in
its checkpointed state, and shows the previous result to the model on the next
step. A `privacy.pii.read` as the first step of a two-step run therefore leaves the
personal data in Postgres for as long as the run exists — and, once the gateway
points at a cloud provider, carries it to that provider on the second step.
**Mitigation.** **Accepted, bounded, and documented — not prevented.** The data is
synthetic (ADR-0006); the model is local by default, so nothing leaves the building
today; the audit records *that* a PII read happened, not what it returned; and a
run's state lives only as long as the run. The control that would close the cloud
case is **S17**'s policy question — whether a run that read PII may only continue on
a local model — which is deliberately not built yet. See [`privacy.md`](privacy.md)
for the storage and retention answer.
**Test.** `test_a_second_step_sees_what_the_first_one_returned`
(`app/agent/tests/test_graph.py`) is the demonstration: the second decision is made
with the first call's result in hand, which is exactly the exposure being accepted.
The mitigation is the documentation itself, checked by
`scripts/check-docs-pages.py`.

---

## Out of scope (documented, not hidden)

- Hardware-backed attestation (TPM/TEE) for nodes.
- Cross-organization identity federation.
- Insider with legitimate repository write access (mitigated by branch protection
  and review, not eliminated).
