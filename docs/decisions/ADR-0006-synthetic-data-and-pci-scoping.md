# ADR-0006: Synthetic data only, and PCI-aware scoping

- **Status:** Accepted
- **Date:** 2026-09-12
- **Related:** ADR-0007

## Context

The application models customer support and refunds — a domain that normally
touches personal data and payment instruments. A reference platform must not
become a place where real customer data leaks, and it must not pull card data
into scope.

## Decision

1. **Synthetic data only.** Every fixture, simulator, seed, test, log line, and
   prompt uses clearly-labelled synthetic data. No real customer, card, or
   personal data — anywhere, ever.
2. **No card data, ever.** The payments path handles only opaque, non-PAN
   tokens. The project is deliberately **out of PCI card-data scope**.

## Consequences

- The repository is safe to share; there is nothing real to leak.
- Simulators must be realistic in *shape* without being real in *content*.
- Real sandbox integrations (later) must be configured to return synthetic or
  test-mode data only.

## Alternatives considered

- **Anonymized real data** — rejected: anonymization is easy to get wrong, and
  the value of a reference platform does not justify the risk.
