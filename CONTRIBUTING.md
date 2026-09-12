# Contributing

Thanks for helping. This project has a few non-negotiable rules, then a normal
development flow.

## Non-negotiables

1. **Never commit a secret.** The real `.env` stays local; the committed template
   is `.env.example`. Run `./scripts/install-hooks.sh` once per clone.
2. **Synthetic data only.** Never real customer, card, or personal data — in
   code, tests, logs, prompts, or fixtures.
3. **No secret or token in logs/traces.** Redact before emitting.
4. **Policy is code.** Changes to `policy/` need tests.
5. **Signed commits.** See below.

## One-time setup

```sh
# 1. Enable the secret-guard hooks
./scripts/install-hooks.sh

# 2. Sign your commits (SSH signing is the simplest path)
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519.pub
git config --global commit.gpgsign true
# Then add the SAME public key to GitHub as a SIGNING key:
#   Settings -> SSH and GPG keys -> New SSH key -> Key type: Signing Key
```

Verify with `git log --show-signature -1`.

Optionally install `gitleaks` for a thorough local scan:
`brew install gitleaks`.

## Workflow

1. Branch from `main` (`git switch -c feat/short-description`).
2. Make focused commits with clear messages (see style below).
3. Run the checks locally (below).
4. Open a PR. `main` is protected: PR-only, no force-push, reviews required.
5. Update `HANDOFF.md` and `docs/roadmap.md` if the change affects state.

## Local checks

```sh
./scripts/scan-secrets.sh          # secrets: tree + full history
bash -n scripts/*.sh               # shell syntax
# Phase 1+:
#   pytest            # python tests
#   opa test policy/  # policy tests
#   npm test          # web tests
```

CI runs the same (`.github/workflows/ci.yml`, `security.yml`) and must be green.

## Commit messages

Conventional-ish, imperative, explaining *why*:

```
feat(sdk): add audience-bound token verification

Keycloak V2 issues the exchanged token to the requesting workload (azp);
verify both aud and azp so a forwarded token is refused.
```

## Code style

- **Python:** formatted with `ruff` (or `black`), typed where practical, small
  functions, no secrets in logs.
- **TypeScript/React:** `eslint` + `prettier`.
- **Rego:** tested; deny by default.
- **Docs:** plain language; define jargon; a worked example per user guide.

## Documentation

- **Developer docs** live in `docs/` as Markdown.
- **User guides** live in `docs/guides/` as self-contained HTML, one per role.
- New significant decisions get an ADR in `docs/decisions/` (use the existing
  files as a template).

## Reporting a security issue

Do **not** open a public issue — see [`SECURITY.md`](SECURITY.md).
