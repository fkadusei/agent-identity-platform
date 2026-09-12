# Supply chain

We need to prove that a running image — and the policy it enforces — is the one
our pipeline built, not something tampered with. The trick is doing that without
introducing a signing key, which would be exactly the long-lived static secret
this platform exists to remove. See
[ADR-0010](decisions/ADR-0010-supply-chain-signing-cosign.md).

## Signing is keyless

In CI (`.github/workflows/release.yml`, on a `v*` tag) the workflow exchanges its
**OIDC identity** for a short-lived Fulcio certificate and signs:

```bash
cosign sign --yes ghcr.io/fkadusei/agent-identity-platform/api:v1.2.3
COSIGN_KEYLESS=1 ./scripts/sign-bundle.sh     # the OPA policy bundle
```

The signature is recorded in Rekor (the transparency log). **No signing key
exists** to store, rotate, or leak — provenance is tied to the workflow
identity, which is the same "identity over secrets" theme as the rest of the
platform.

## Verifying

```bash
# the policy bundle, keyless, pinned to our release workflow identity
COSIGN_KEYLESS=1 \
  COSIGN_IDENTITY_REGEXP='https://github.com/fkadusei/agent-identity-platform/.github/workflows/release.yml@refs/tags/*' \
  ./scripts/verify-bundle.sh
```

A tampered artifact fails verification:

```
Error: failed to verify signature: ... invalid signature
```

## Enforcing at admission

`deploy/kind/manifests/supply-chain/kyverno-verify-images.yaml` is a Kyverno
`ClusterPolicy` that **admits only images carrying a valid keyless signature from
our release workflow** — the point where verification stops being advisory and
becomes a gate:

```bash
kubectl apply -f https://github.com/kyverno/kyverno/releases/...   # install Kyverno
kubectl apply -f deploy/kind/manifests/supply-chain/
```

An unsigned or wrongly-signed image is refused admission.

## Running it locally

The local kind demo loads images straight into the cluster (`kind load
docker-image`), so there is no registry signature to verify — the admission
policy targets the registry images from CI. What you *can* run locally, with no
OIDC, is the bundle signing path with a local key:

```bash
./scripts/build-bundle.sh
./scripts/sign-bundle.sh      # generates .cosign/ (gitignored) on first use
./scripts/verify-bundle.sh
```

This is the same build → sign → verify shape; only the identity differs (a local
key instead of the CI OIDC identity). Set `COSIGN_KEYLESS=1` in CI to switch to
the real keyless path.

## Related controls

- **SBOM** — Syft generates a CycloneDX SBOM of the repo/deps in CI
  (`security.yml`).
- **Vulnerability scan** — Trivy scans images and dependencies, with a documented
  scoped exception (`.trivyignore.yaml`).
- **Dependencies** — Dependabot + `pip-audit`/`npm audit` in CI.
