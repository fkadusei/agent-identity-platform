# ADR-0004: LangGraph for the stateful agent and human-in-the-loop

- **Status:** Accepted
- **Date:** 2026-09-12
- **Related:** ADR-0003

## Context

A `require_approval` decision means the agent's run must **pause**, wait for a
human, and then **resume** — potentially minutes or hours later, across process
restarts. A stateless request/response agent cannot do this.

## Decision

Build the agent as a **LangGraph** state machine with native **interrupts** and
**checkpointing** (persisted state). On `require_approval`, the graph interrupts,
an approval request is created, and the run resumes when a decision is recorded.

## Consequences

- Human-in-the-loop becomes a first-class control rather than a hack.
- Run state must be persisted (a datastore), and the approval API must be
  idempotent and auditable.
- One significant framework dependency; the workflow is explicit and testable.

## Alternatives considered

- **Hand-rolled state machine** — viable and framework-free, but we would
  re-implement checkpointing and interrupts; more code to own for a reference
  platform.
- **Blocking tool call that polls for approval** — rejected: holds a worker,
  fragile across restarts, poor UX.
