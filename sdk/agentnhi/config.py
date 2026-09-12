"""Configuration, loaded from the environment.

Nothing here is a secret. Identity comes from SPIFFE; the only optional secret
in the whole platform is a hosted-LLM key, and it lives behind the LLM gateway,
not in this SDK.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_ISSUER = "http://keycloak:8080/realms/agent-nhi"


@dataclass(frozen=True)
class Settings:
    """Runtime configuration.

    Attributes:
        keycloak_issuer: realm issuer URL; must be byte-identical everywhere in
            the cluster (Keycloak derives `iss` from the request Host header).
        spiffe_socket: path to the SPIFFE Workload API socket.
        opa_url: base URL of the OPA server.
        audience: the audience this service expects on inbound tokens.
        trusted_workload: the workload (SPIFFE ID / `azp`) allowed to call this
            service, if any. `None` means "do not enforce azp".
        policy_path: OPA data path queried for decisions.
        policy_timeout: seconds to wait for OPA before failing closed.
        redact_extra_keys: additional field names to redact in audit records.
    """

    keycloak_issuer: str = DEFAULT_ISSUER
    spiffe_socket: str = "unix:///run/spire/sockets/agent.sock"
    opa_url: str = "http://opa:8181"
    audience: str = ""
    trusted_workload: str | None = None
    policy_path: str = "agentnhi/authz"
    policy_timeout: float = 3.0
    redact_extra_keys: tuple[str, ...] = field(default_factory=tuple)

    # -- derived ---------------------------------------------------------------
    @property
    def jwks_url(self) -> str:
        return f"{self.keycloak_issuer}/protocol/openid-connect/certs"

    @property
    def token_endpoint(self) -> str:
        return f"{self.keycloak_issuer}/protocol/openid-connect/token"

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        """Build settings from environment variables (with overrides)."""
        values = dict(
            keycloak_issuer=os.environ.get("KC_ISSUER", DEFAULT_ISSUER),
            spiffe_socket=os.environ.get(
                "SPIFFE_SOCKET", "unix:///run/spire/sockets/agent.sock"
            ),
            opa_url=os.environ.get("OPA_URL", "http://opa:8181"),
            audience=os.environ.get("TOKEN_AUDIENCE", ""),
            trusted_workload=os.environ.get("TRUSTED_WORKLOAD") or None,
            policy_path=os.environ.get("OPA_POLICY_PATH", "agentnhi/authz"),
        )
        extra = os.environ.get("REDACT_EXTRA_KEYS", "")
        values["redact_extra_keys"] = tuple(
            k.strip().lower() for k in extra.split(",") if k.strip()
        )
        values.update(overrides)
        return cls(**values)
