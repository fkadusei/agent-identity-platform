# spire-plugin — the `jti` CredentialComposer

A tiny SPIRE **CredentialComposer** plugin (external process, gRPC) that adds a
unique `jti` claim to every workload **JWT-SVID**.

## Why

The demo's agent authenticates to Keycloak as its SPIFFE identity by presenting
its JWT-SVID as a `private_key_jwt` client assertion. Keycloak requires a `jti`
claim on such assertions (RFC 7523) and hardcodes that requirement
(`JWTClientValidator.isReusePermitted()` returns `false`). SPIRE's JWT-SVIDs
carry only `iss/sub/aud/exp/iat`, so the assertion is rejected with
`"Token jti claim is required"`.

This plugin closes that gap at issuance, leaving the rest of the architecture
untouched. It does **not** modify the SPIFFE ID, audience, expiry, or any other
claim.

## Alternatives considered (and why not)

- **Static client secret for the agent** — reintroduces exactly the credential
  the demo exists to eliminate.
- **Keycloak X.509 client auth (`client-x509`)** — matches only on the
  certificate subject DN. SPIRE X.509-SVIDs all share `O=SPIRE,C=US` (the
  SPIFFE ID lives in the SAN URI), so Keycloak cannot distinguish workloads.
  This is the gap `draft-ietf-oauth-spiffe-client-auth` is being written to fill.
- **mTLS to the tool server instead** — correct and SPIFFE-native, but moves
  the token exchange out of the agent and changes the demo's story.

## Build

Built into the SPIRE server image by `docker/spire-server.Dockerfile`; the
resulting image is wired up in `k8s/spire/spire-server.yaml`:

```hcl
CredentialComposer "jti" {
  plugin_cmd = "/opt/spire/plugins/jti-plugin"
  plugin_data {}
}
```
