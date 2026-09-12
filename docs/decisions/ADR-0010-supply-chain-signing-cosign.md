# ADR-0010: Supply-chain signing with cosign (keyless Sigstore)

- **Status:** Accepted
- **Date:** 2026-09-12
- **Related:** ADR-0007 (security baseline), ADR-0001 (identity over secrets)

## Context

Once we ship container images, we need to be able to prove that a running image
is the one our pipeline built and not something tampered with. The usual answer —
a signing key — is itself a static secret, which cuts against the whole point of
this platform. We need provenance without adding a long-lived credential.

## Decision

**Yes, use cosign — keyless, via GitHub Actions OIDC (Sigstore).**

- **Sign in CI:** images pushed to the registry are signed with `cosign sign
  --yes`, using the workflow's short-lived OIDC identity (Fulcio issues a
  short-lived certificate; the signature is recorded in Rekor). **No signing key
  exists to manage or leak.**
- **Verify in the deploy pipeline:** `cosign verify` with the expected
  certificate identity and issuer before anything is deployed.
- **Enforce (Phase 2+):** an admission policy (Kyverno or OPA Gatekeeper) that
  admits only images carrying a valid signature from our workflow identity.

This pairs with the SBOM (Syft) and vulnerability scan (Trivy) already in CI.

## Consequences

- Provenance is tied to the *workflow identity*, which fits the "identity over
  secrets" theme; there is no signing key in the repo or a vault.
- Keyless mode uses the **public Sigstore** infrastructure (Fulcio/Rekor) by
  default, which records signature metadata in a public transparency log. For an
  air-gapped or strictly-private deployment, self-host Sigstore or fall back to
  key-based signing (which reintroduces a key to manage).
- Requires an OCI registry (GHCR supports cosign artifacts).
- Signing only makes sense once images are pushed to a registry, so the wiring
  lands when images exist (Phase 2), not during the local kind phase.

## Alternatives considered

- **Key-based cosign** — works, but reintroduces the long-lived secret we are
  eliminating.
- **No signing** — rejected: we would have no way to detect a tampered image.
- **SLSA provenance only** — complementary and worth adding, but not a
  substitute for a verifiable signature on the artifact itself.
