"""Attack checks that run inside the agent pod.

Each attack is expected to be BLOCKED. The script prints a clear PASS/FAIL so a
regression is obvious.
"""
import os

import httpx

from agentnhi import Settings, TokenExchanger
from agentnhi.identity import fetch_jwt_svid

from app.common import hop, workload

KC = "http://keycloak:8080/realms/agent-platform"
TOOLS = "https://tools:8443"
AGENT_ID = "spiffe://acme.com/ns/agent-platform/sa/agent"
DEMO_CLI_SECRET = os.environ["DEMO_CLI_SECRET"]
S = Settings.from_env()

failures = 0


def login(username, password, client_id, secret):
    # A cold Keycloak (right after a restart) can exceed a short timeout on the
    # first token. One retry settles it, and issuing a token is a read.
    for attempt in (1, 2):
        try:
            resp = httpx.post(
                f"{KC}/protocol/openid-connect/token",
                data={
                    "grant_type": "password", "client_id": client_id, "client_secret": secret,
                    "username": username, "password": password,
                },
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()["access_token"]
        except httpx.TimeoutException:
            if attempt == 2:
                raise


def tool_token(user_token):
    svid = fetch_jwt_svid(S.spiffe_socket, S.keycloak_issuer)
    return TokenExchanger(S).exchange(
        subject_token=user_token, client_id=AGENT_ID, client_assertion=svid
    )


def call(tool, args, token):
    # An honest client of the tool server names itself (S7). Attack 2's *raw* user
    # token must still be refused, and it is — on its audience, not on identity.
    client, workload_headers = hop.open_hop(TOOLS, workload.TOOLS, timeout=15)
    try:
        resp = client.post(
            f"{TOOLS}/tools/{tool}", json=args,
            headers={"Authorization": f"Bearer {token}", **workload_headers},
        )
    finally:
        client.close()
    return resp.status_code, resp.text[:160]


def check(label, blocked, detail):
    global failures
    if blocked:
        print(f"   BLOCKED ✓  {label} — {detail}")
    else:
        failures += 1
        print(f"   SUCCEEDED ✗  {label} — {detail}")


alice = login("alice", "alice123", "demo-cli", DEMO_CLI_SECRET)

print("\nATTACK 2 — TOKEN FORWARDING (wrong audience)")
status, detail = call("crm.customer.read", {"customer_id": "c-100"}, alice)
check("alice's raw user token at the tools service", status == 403, f"HTTP {status}: {detail}")

agent_token = tool_token(alice)

print("\nATTACK 3 — OUT-OF-POLICY TOOL (refund above the ceiling)")
status, detail = call("refunds.issue", {"order_id": "o-1001", "amount": 1000}, agent_token)
check("refund of $1000", status == 403, f"HTTP {status}: {detail}")

print("\nATTACK 4 — APPROVAL BYPASS (high-risk without approval)")
status, detail = call("refunds.issue", {"order_id": "o-1001", "amount": 200}, agent_token)
check("refund of $200 with no approval", status == 428, f"HTTP {status}: {detail}")

print("\nATTACK 5 — PII ACCESS WITHOUT THE PRIVACY ROLE")
status, detail = call("privacy.pii.read", {"customer_id": "c-100"}, agent_token)
check("PII read as a support rep", status == 403, f"HTTP {status}: {detail}")

print()
raise SystemExit(1 if failures else 0)
