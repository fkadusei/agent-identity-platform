# AGENTS.md

Instructions for AI agents (opencode and others) working in this repository.
`HANDOFF.md` is the resume-here document — read it and
[`docs/backlog.md`](docs/backlog.md) **first**, before touching anything.

## The rule this repo is built around: write it down as you go

Sessions here stop mid-conversation, and the next session has **none** of this
one's memory — so the repository *is* the memory. Update it incrementally, after
each meaningful step rather than only at the end, and before you stop for any
reason make sure the next session can resume from files alone.

At the end of every session (and after each slice-sized change):

1. **Update `HANDOFF.md`.** Bump "Last updated" and edit the sections a change
   touches: "What is built", "Immediate next task", "Known issues / gotchas", and
   the record of done work. Say what changed, why, and how it was verified.
2. **Update the associated file the change belongs to:**
   - `docs/backlog.md` — a new or changed slice, with a stable ID.
   - `docs/roadmap.md` — phase/state changes.
   - `docs/site/questions.html` — a `QA:` question, appended (next `qnum`, a nav
     entry, the answer checked against the code or the running cluster).
   - `docs/decisions/` — a significant decision, as a new ADR.
   - `NOTES.md` — machine-specific facts only (gitignored; never committed).
3. **Change the page if you changed the behaviour it describes** — same change,
   not a follow-up: `scripts/check-docs-pages.py` enforces it (nav, links, and
   every quoted line against its source).
4. **Run the checks** from `HANDOFF.md` → "Test everything"; at minimum
   `python3 scripts/check-docs-pages.py` for a docs change.

A change is not finished until the tree reflects it. Leaving it only in the chat
is losing it.

## Non-negotiables (see `CONTRIBUTING.md`)

- Never commit a secret; `.env` is gitignored. Synthetic data only.
- No secret or token in logs, traces, or errors.
- Policy is code: a change to `policy/` needs tests.
- Commits are signed; `main` is PR-only with linear history.
- Verify TLS with `--cacert .edge/ca.crt`, never `-k`.
