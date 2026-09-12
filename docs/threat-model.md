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
workload the token was issued to (`azp`).
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
**Test.** `scripts/scan-secrets.sh` (tree + full history); a unit test in CI that
stages a fake secret and asserts the hook blocks it.

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
**Mitigation.** Tenant scoping enforced in policy *and* in the tools; the SDK
provides the scoped context, not the caller.
**Test.** A two-tenant test asserts tenant B's records are unreachable from
tenant A's session.

## T10 — Supply chain and CI/CD compromise

**Threat.** A malicious dependency, image, or workflow change.
**Mitigation.** Lockfiles committed; Dependabot; actions pinned to major
versions; SBOM (Syft); Trivy scans; SAST (Semgrep); least-privilege
`GITHUB_TOKEN`; no secrets in CI logs.
**Test.** CI jobs (`.github/workflows/security.yml`) fail on findings.

---

## Out of scope (documented, not hidden)

- Hardware-backed attestation (TPM/TEE) for nodes.
- Cross-organization identity federation.
- Insider with legitimate repository write access (mitigated by branch protection
  and review, not eliminated).
