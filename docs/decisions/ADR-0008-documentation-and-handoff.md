# ADR-0008: Documentation and handoff strategy

- **Status:** Accepted
- **Date:** 2026-09-12

## Context

This project is built in sessions and must be resumable at any point by a human
or an AI collaborator. A design that lives only in chat is not resumable. It also
serves two very different audiences: engineers who build and operate it, and
non-engineers who use or sponsor it.

## Decision

1. **A living handoff.** `HANDOFF.md` (the resume-here narrative),
   `docs/roadmap.md` (the phase checklist), and `docs/decisions/ADR-*.md` are
   **updated at the end of every work session**, with a **git tag per completed
   phase**.
2. **Developer docs in Markdown** (GitHub-rendered, mermaid diagrams): README,
   CONTRIBUTING, architecture, development, api, policy-lifecycle, runbook,
   glossary, security docs.
3. **User guides as plain-language, self-contained HTML**, one per role
   (overview, support rep, approver, operator), plus `real-world-adoption.md` for
   leaders.

## Consequences

- Any session can end cleanly and resume from `HANDOFF.md`.
- Decisions are recorded once and not re-litigated.
- Documentation has a defined standard (plain language, a worked example per
  guide, "could a non-engineer follow this?").

## Alternatives considered

- **Docs at the end** — rejected: they drift and never get written.
- **A single combined user guide** — rejected: readers wade through roles that
  are not theirs.
