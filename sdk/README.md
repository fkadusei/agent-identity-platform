# agentnhi

Identity and policy plumbing for AI agents — extracted from the
[`enterprise-agent-nhi`](https://github.com/fkadusei/enterprise-agent-nhi)
concepts demo so it can be reused across agents and tools.

It provides the four things every governed agent needs, with the security
defaults baked in:

| Module | What it does | Security default |
|---|---|---|
| `agentnhi.identity` | Fetch a SPIFFE SVID (JWT or X.509) from the Workload API; build an mTLS context | No static credentials |
| `agentnhi.exchange` | OAuth 2.0 token exchange (RFC 8693) | Audience-bound, short-lived tokens |
| `agentnhi.tokens` | Verify a token: signature, issuer, `aud`, and the workload it was issued to (`azp`) | Refuses forwarded tokens |
| `agentnhi.policy` | Ask OPA: allow / deny / require-approval | **Deny by default; fails closed** |
| `agentnhi.audit` | One structured record per event | **Redacts secrets and PII before emitting** |

## Design principles

1. **No secret is ever required to prove identity.** Identity comes from SPIFFE.
2. **Fail closed.** If policy cannot be reached or understood, the answer is deny.
3. **Redact by default.** Tokens, credentials, and personal data never reach a
   log line unless a caller explicitly opts in.
4. **No token forwarding.** Every hop exchanges for its own audience-scoped token.

## Install (local)

```sh
cd sdk
pip install -e ".[dev]"          # or ".[dev,spiffe]" to include SPIFFE support
pytest
```

## Example

```python
from agentnhi import Settings, TokenVerifier, PolicyClient, Decision, audit
from agentnhi.identity import fetch_jwt_svid
from agentnhi.exchange import TokenExchanger

s = Settings.from_env()

# 1. prove who we are (no secret)
svid = fetch_jwt_svid(s.spiffe_socket, audience=s.keycloak_issuer)

# 2. trade the user's token for one scoped to us
token = TokenExchanger(s).exchange(subject_token=user_token, client_assertion=svid)

# 3. at the tool boundary: verify, then authorize
claims = TokenVerifier(s).verify(token, expected_audience=s.audience, expected_azp=s.trusted_workload)
result = PolicyClient(s).decide(agent=claims.workload, user=claims.user, tool="refunds.issue")
if result.decision is not Decision.ALLOW:
    raise PermissionError(result.reason)

audit("tool.allowed", spiffe_id=claims.workload, sub=claims.user, tool="refunds.issue")
```
