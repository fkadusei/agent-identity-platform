"""agentnhi — identity and policy plumbing for governed AI agents.

Public API:
    Settings            configuration (from environment)
    TokenVerifier       verify tokens: signature, iss, aud, azp
    Delegation          the (user, workload) pair extracted from a token
    TokenExchanger      RFC 8693 token exchange
    PolicyClient        ask OPA; allow / deny / require-approval (fails closed)
    Decision            ALLOW | DENY | REQUIRE_APPROVAL
    PolicyResult        decision + reason
    audit               emit one redaction-safe structured record
    redact              redact secrets/PII from an arbitrary value
"""
from .audit import audit, configure, redact, set_sink
from .config import Settings
from .errors import (
    AgentNhiError,
    ExchangeError,
    IdentityError,
    PolicyError,
    TokenRejected,
)
from .exchange import TokenExchanger
from .policy import Decision, PolicyClient, PolicyResult
from .tokens import Delegation, TokenVerifier

__all__ = [
    "Settings",
    "TokenVerifier",
    "Delegation",
    "TokenExchanger",
    "PolicyClient",
    "Decision",
    "PolicyResult",
    "audit",
    "redact",
    "configure",
    "set_sink",
    "AgentNhiError",
    "ExchangeError",
    "IdentityError",
    "PolicyError",
    "TokenRejected",
]

__version__ = "0.1.0"
