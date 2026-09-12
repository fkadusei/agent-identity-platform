"""Build the enforcement stack from configuration.

Kept separate so tests can construct an enforcer with fakes, and the HTTP/MCP
transports can share exactly the same wiring.
"""
from __future__ import annotations

import os

from agentnhi import PolicyClient, Settings, TokenVerifier

from app.tools.approvals import ApprovalsClient
from app.tools.enforcement import ToolEnforcer


def build_enforcer(settings: Settings | None = None) -> ToolEnforcer:
    settings = settings or Settings.from_env()
    approvals_url = os.environ.get("APPROVALS_URL", "http://api:8080")
    return ToolEnforcer(
        settings=settings,
        verifier=TokenVerifier(settings),
        policy=PolicyClient(settings),
        approvals=ApprovalsClient(approvals_url),
    )
