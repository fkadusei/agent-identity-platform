# HANDOFF

**The resume-here document.** Updated at the end of every work session.

---

- **Project:** agent-identity-platform
- **Status:** Phase 0 complete · awaiting owner review before Phase 1
- **Last updated:** 2026-09-12
- **Repo:** `github.com/fkadusei/agent-identity-platform` (private)
- **Local path:** `/Users/felixadusei/Development/AI_Engineering/OpenCode/agent-identity-platform`

## Resume in 60 seconds

```sh
cd /Users/felixadusei/Development/AI_Engineering/OpenCode/agent-identity-platform
./scripts/install-hooks.sh          # enable the secret guard (once per clone)
./scripts/scan-secrets.sh           # verify: no secrets in tree or history
git log --oneline -5                # where we are
cat docs/roadmap.md                 # what's done / next
```

There is no application to run yet — Phase 0 deliberately lands security and
documentation first.

## Where we are

- **Phase 0 — complete.** Repo scaffolded, security baseline in place and
  verified, ADRs 0001–0009 recorded, core docs written, pushed to GitHub.
- **Next: Phase 1** — extract the SDK and build the local app (see roadmap).

## Immediate next task

**Phase 1, step 1: extract `sdk/agentnhi/` from the concepts demo.**

- Source of truth for the logic:
  `../agent_identity/src/{shared,agent,tool_server,customer_api}/`
  (repo: `enterprise-agent-nhi`).
- Package it as an installable, typed, unit-tested library exposing:
  `identity` (SVID fetch + mTLS), `exchange` (RFC 8693), `tokens`
  (verify `aud` + `azp`), `policy` (OPA client), `audit` (redaction + structured
  events).
- Acceptance: unit tests pass; a smoke test performs an exchange against the
  local Keycloak and verifies the resulting token.

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
