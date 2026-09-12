# ADR-0007: Security baseline and repository governance

- **Status:** Accepted
- **Date:** 2026-09-12

## Context

Security controls added late are usually incomplete and always more expensive.
The repository must be safe from its first commit, and the controls must not
depend on anyone remembering to run them.

## Decision

Establish the security baseline **before any application code**:

- **Secret hygiene:** `.gitignore`, `.gitleaks.toml`, a **pre-commit hook**
  (blocks sensitive filenames and scans staged changes), `scan-secrets.sh`, and
  the `.env` / `.env.example` convention.
- **CI enforcement:** gitleaks + an explicit "`.env` is not tracked" guard, plus
  Semgrep (SAST), Trivy, dependency audits, and an SBOM that activate as code
  lands.
- **Governance:** private repo, branch protection with PR-only merges and no
  force-push, and **signed commits**.
- **Invariant:** no secret in git, logs, traces, or prompts; synthetic data only.

## Consequences

- A fresh clone cannot commit a secret; CI fails on any secret.
- Contributors must install hooks (`./scripts/install-hooks.sh`) and sign
  commits — a small one-time setup cost.
- Defence in depth: a bypassed layer is covered by the next.

## Alternatives considered

- **Rely on GitHub secret scanning** — not available on free private repos;
  treated as an optional extra, not the primary control.
- **Add security later** — rejected: the whole point is to never commit a secret.
