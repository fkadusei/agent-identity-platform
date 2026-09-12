"""Exception types for the SDK.

Every exception carries a message that is safe to show a caller (no secrets).
"""
from __future__ import annotations


class AgentNhiError(Exception):
    """Base class for all SDK errors."""


class IdentityError(AgentNhiError):
    """Could not obtain or use a workload identity."""


class TokenRejected(AgentNhiError):
    """A token failed verification (signature, issuer, audience, azp, expiry)."""


class ExchangeError(AgentNhiError):
    """A token exchange failed."""


class PolicyError(AgentNhiError):
    """Policy could not be evaluated. Callers should treat this as DENY."""
