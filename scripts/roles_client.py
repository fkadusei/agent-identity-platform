"""Walk enrollment -> admin role grant -> server-side role enforcement.

Runs inside the cluster (see scripts/demo-roles.sh), talking to the API by
service name. Fast and deterministic: no LLM involved.
"""
from __future__ import annotations

import json
import secrets

import httpx

API = "http://api:8080"


def login(username: str, password: str) -> dict:
    # A cold API/Keycloak (right after a restart) can exceed a short timeout on
    # the first call. One retry settles it, and a login is a read, so it is safe.
    for attempt in (1, 2):
        try:
            resp = httpx.post(
                f"{API}/auth/login",
                json={"username": username, "password": password},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            if attempt == 2:
                raise


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


username = f"carol-{secrets.token_hex(2)}"
password = "password1"

print(f"1. enroll {username} (self-service)")
created = httpx.post(
    f"{API}/enroll",
    json={
        "username": username,
        "email": f"{username}@example.com",
        "firstName": "Carol",
        "lastName": "Candidate",
        "password": password,
    },
    timeout=30,
)
created.raise_for_status()
print("   ->", json.dumps(created.json()))

print("2. sign in: a token, but no roles")
carol = login(username, password)
print("   -> roles:", carol["roles"], "| tools:", carol["tools"])
if carol["tools"]:
    # The point of enrollment: an account starts with nothing it may do.
    raise SystemExit(f"a user with no roles was offered tools: {carol['tools']}")

print("3. carol tries to administer users (must be refused)")
resp = httpx.get(f"{API}/admin/users", headers=bearer(carol["access_token"]), timeout=30)
print(f"   -> HTTP {resp.status_code}: {resp.json().get('detail')}")
if resp.status_code != 403:
    # It said "must be refused" and then printed whatever came back; a 200 would have
    # passed. An assertion is the difference between a claim and a check.
    raise SystemExit(f"carol administered users as a role-less account: HTTP {resp.status_code}")

print("3b. carol asks the agent to act (nothing may run)")
outcome = httpx.post(
    f"{API}/tasks",
    json={"task": "Issue a refund of 200 dollars for order o-1001"},
    headers=bearer(carol["access_token"]),
    timeout=60,
).json()
print(f"   -> {outcome.get('status')}: {outcome.get('reason')}")
if outcome.get("status") != "refused":
    raise SystemExit("a user with no roles was able to have the agent act")

print("4. admin grants support_rep")
admin = login("admin", "admin123")
print("   -> admin roles:", admin["roles"])
users = httpx.get(f"{API}/admin/users", headers=bearer(admin["access_token"]), timeout=30).json()
carol_id = next(u["id"] for u in users if u["username"] == username)
granted = httpx.post(
    f"{API}/admin/users/{carol_id}/roles",
    json={"role": "support_rep"},
    headers=bearer(admin["access_token"]),
    timeout=30,
)
granted.raise_for_status()
print("   -> carol roles now:", granted.json()["roles"])

print("5. carol signs in again and now carries the role")
carol = login(username, password)
print("   -> roles:", carol["roles"])

print("\nEnrollment grants nothing; only an admin can authorize.")
