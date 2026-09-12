"""Verify tokens and extract the delegation binding.

A resource server must check three things about an inbound token:

1. **Signature and issuer** — it really came from our authorization server.
2. **Audience (`aud`)** — it was minted for *this* service. This is what makes a
   forwarded token fail.
3. **Issued-to (`azp`)** — it was issued to the workload we expect. Defense in
   depth: even with a matching audience, a token issued to someone else is
   refused.

The result is a :class:`Delegation`: who the human is, and which workload is
acting on their behalf.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import jwt
from jwt import PyJWKClient

from .config import Settings
from .errors import TokenRejected

SigningKeyResolver = Callable[[str], Any]


@dataclass(frozen=True)
class Delegation:
    """Who is acting, and for whom."""

    user: str
    workload: str
    audience: str
    roles: tuple[str, ...] = ()
    claims: dict = field(default_factory=dict)

    @classmethod
    def from_claims(cls, claims: dict, audience: str) -> "Delegation":
        # `sub` is the human; `preferred_username` is their readable name.
        user = claims.get("preferred_username") or claims.get("sub") or "?"
        # `azp` is the workload the token was issued to (the actor). RFC 8693
        # calls this the `act` claim; Keycloak's Standard Token Exchange V2
        # surfaces it as `azp`.
        act = claims.get("act") or {}
        workload = act.get("sub") or claims.get("azp") or "?"
        # Keycloak puts realm roles under realm_access.roles; accept a flat
        # `roles` claim too, so the SDK is not Keycloak-specific.
        roles = (
            (claims.get("realm_access") or {}).get("roles")
            or claims.get("roles")
            or ()
        )
        return cls(
            user=user,
            workload=workload,
            audience=audience,
            roles=tuple(roles),
            claims=claims,
        )


class TokenVerifier:
    """Verifies inbound tokens against a Keycloak realm.

    The signing-key resolver is injectable so the verifier can be unit-tested
    without a live authorization server.
    """

    def __init__(self, settings: Settings, signing_key_resolver: SigningKeyResolver | None = None):
        self._settings = settings
        self._resolver = signing_key_resolver
        self._jwks_client: PyJWKClient | None = None

    def _resolve(self, token: str) -> Any:
        if self._resolver is not None:
            return self._resolver(token)
        if self._jwks_client is None:
            self._jwks_client = PyJWKClient(self._settings.jwks_url)
        return self._jwks_client.get_signing_key_from_jwt(token).key

    def verify(
        self,
        token: str,
        *,
        expected_audience: str | None = None,
        expected_azp: str | None = None,
    ) -> Delegation:
        """Return the :class:`Delegation` or raise :class:`TokenRejected`."""
        audience = expected_audience if expected_audience is not None else self._settings.audience
        if not audience:
            raise TokenRejected("no expected audience configured")
        azp = expected_azp if expected_azp is not None else self._settings.trusted_workload

        try:
            key = self._resolve(token)
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256", "ES256"],
                audience=audience,
                issuer=self._settings.keycloak_issuer,
            )
        except jwt.InvalidAudienceError as exc:
            raise TokenRejected(
                f"token audience is not {audience!r} (refusing a forwarded token)"
            ) from exc
        except jwt.PyJWTError as exc:
            raise TokenRejected(f"invalid token: {exc}") from exc

        if azp is not None and claims.get("azp") != azp:
            raise TokenRejected(
                f"token was issued to {claims.get('azp')!r}, not {azp!r} "
                "(refusing a forwarded token)"
            )

        return Delegation.from_claims(claims, audience)
