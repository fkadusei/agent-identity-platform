"""Call every tool as every demo user, and print the outcome.

Deterministic — no LLM. It logs in as each user, exchanges the token through the
agent's own identity (the same path the agent uses), and calls each tool at the
tool server, which enforces the policy.
"""
from __future__ import annotations

import os

import httpx

from agentnhi import Settings, TokenExchanger
from agentnhi.identity import fetch_jwt_svid

KC = "http://keycloak:8080/realms/agent-platform"
TOOLS = "http://tools:8000"
AGENT_ID = "spiffe://acme.com/ns/agent-platform/sa/agent"
S = Settings.from_env()

USERS = [
    ("alice", "alice123", "support_rep"),
    ("bella", "bella123", "billing"),
    ("dana", "dana1234", "read_only"),
    ("manager", "manager123", "manager"),
]
CALLS = [
    ("crm.customer.read", {"customer_id": "c-100"}),
    ("crm.orders.list", {"customer_id": "c-100"}),
    ("tickets.read", {"ticket_id": "t-5001"}),
    ("tickets.reply.draft", {"ticket_id": "t-5001", "body": "hello"}),
    ("refunds.quote", {"order_id": "o-1001"}),
    ("refunds.issue", {"order_id": "o-1001", "amount": 25}),
    ("privacy.pii.read", {"customer_id": "c-100"}),
]


def login(username: str, password: str) -> str:
    resp = httpx.post(
        f"{KC}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "demo-cli",
            "client_secret": os.environ["DEMO_CLI_SECRET"],
            "username": username,
            "password": password,
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def exchange(user_token: str) -> str:
    svid = fetch_jwt_svid(S.spiffe_socket, S.keycloak_issuer)
    return TokenExchanger(S).exchange(
        subject_token=user_token, client_id=AGENT_ID, client_assertion=svid
    )


def outcome(user_token: str, name: str, args: dict) -> str:
    resp = httpx.post(
        f"{TOOLS}/tools/{name}",
        json=args,
        headers={"Authorization": f"Bearer {user_token}"},
        timeout=20,
    )
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    status = body.get("status")
    if resp.status_code == 200 and not status:
        return "allowed"
    if status == "approval_required":
        return "needs approval"
    if status == "denied":
        return "DENIED"
    return str(body.get("reason") or body.get("detail") or resp.status_code)[:22]


header = "  " + f"{'user':<9}{'role':<15}" + "".join(f"{n.split('.')[-1]:<17}" for n, _ in CALLS)
print(header)
print("  " + "-" * (len(header) - 2))
for user, password, role in USERS:
    token = exchange(login(user, password))
    cells = [outcome(token, name, args) for name, args in CALLS]
    print("  " + f"{user:<9}{role:<15}" + "".join(f"{c:<17}" for c in cells))

print("\nThe tool server decides; the role -> tool matrix is policy/authz.rego.")
