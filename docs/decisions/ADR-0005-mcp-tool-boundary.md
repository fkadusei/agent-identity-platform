# ADR-0005: MCP as the tool boundary

- **Status:** Accepted
- **Date:** 2026-09-12
- **Related:** ADR-0001, ADR-0003

## Context

The agent needs a standard way to discover and call tools. The concepts demo
used a plain HTTP tool server to keep the identity story front and center; the
real platform should use the industry standard for agent tools.

## Decision

Expose every tool as a **Model Context Protocol (MCP)** server. The tool server
remains the **policy enforcement point**: it verifies the token (signature,
audience, and the workload it was issued to), queries OPA, and — if allowed —
performs its **own** token exchange for downstream calls. It never forwards the
inbound token.

## Consequences

- Tool integration follows a standard, interoperable protocol; the LLM's native
  tool-calling maps directly onto MCP.
- The security invariants (no token forwarding, per-tool policy) must be
  enforced in every MCP server — provided by the shared SDK, not re-implemented.
- MCP's OAuth 2.1 resource-indicator model lines up with our audience-bound
  tokens.

## Alternatives considered

- **Plain HTTP tool API** — fine for the demo, but non-standard for the wider
  agent ecosystem.
- **Framework-specific tool plugins** — rejected: locks tooling to one agent
  framework.
