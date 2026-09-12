# Security Policy

## Our security invariants

These hold for the whole repository, in code, config, tests, logs, traces, and
prompts. A change that violates one of them is a bug.

1. **No secret is ever committed.** The real `.env` stays local and is
   gitignored; the committed template is `.env.example`.
2. **No secret or token in logs, traces, or error messages.** Redaction is
   applied before anything is emitted.
3. **Synthetic data only.** Never real customer, card, or personal data — in
   git, tests, logs, prompts, or fixtures.
4. **No card data, ever.** The payments path handles only opaque tokens; the
   project is deliberately out of PCI card-data scope.
5. **Identity over secrets.** Workloads prove who they are cryptographically
   (SPIFFE); they do not carry shared static credentials.
6. **Least privilege and no token forwarding.** Every hop exchanges for a
   token scoped to exactly one audience.
7. **Human approval for high-risk actions**, with an authenticated approver
   identity and no self-approval.

## Reporting a vulnerability

Please do **not** open a public issue for security problems.

- Report privately via GitHub's **Security → Report a vulnerability** (private
  advisory) on this repository, or
- email the maintainer directly.

Include: a description, reproduction steps, impact, and any suggested fix.
We aim to acknowledge within a few business days.

## What we scan, and when

| Control | Where | What it catches |
|---|---|---|
| Pre-commit hook | local, every commit | sensitive filenames, staged secrets |
| gitleaks (`.gitleaks.toml`) | pre-commit + CI | secrets in the tree and full history |
| `.env`-tracked guard | CI | an accidentally committed `.env` |
| Semgrep (SAST) | CI | insecure code patterns |
| Trivy | CI | vulnerable dependencies and images |
| dependency audit (`pip-audit`, `npm audit`) | CI | known-vulnerable packages |
| SBOM (Syft) | CI | software bill of materials |
| cosign (keyless Sigstore) | CI + deploy (Phase 2) | image signing, verification, provenance |
| GitHub Advanced Security | GitHub (when enabled) | secret scanning, push protection, CodeQL |

## Supply chain & signing

Container images are **signed keyless with cosign** (Sigstore) using the CI
workflow's OIDC identity — so there is no long-lived signing key to manage or
leak. Deployments verify the signature before rollout, and (Phase 2+) an
admission policy admits only images signed by our workflow identity. See
[`docs/decisions/ADR-0010-supply-chain-signing-cosign.md`](docs/decisions/ADR-0010-supply-chain-signing-cosign.md).

## Supported versions

This is a reference platform under active development; security fixes are
applied to the default branch.
