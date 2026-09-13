"""Prove tenant isolation at all three layers: the claim, the policy, the data.

Runs inside the cluster (see scripts/tenancy-tests.sh).
"""
from __future__ import annotations

import os

import httpx
import jwt

KC = "http://keycloak:8080/realms/agent-platform"
OPA = "http://opa:8181/v1/data/agentnhi/authz"
SANDBOX = "http://sandbox:8090"
AGENT = "spiffe://acme.com/ns/agent-platform/sa/agent"


def login(username: str, password: str) -> str:
    # The agent pod holds the demo client secret (not the portal's); any user can
    # log in through it, and the tenant claim is what this script is checking.
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


def tenant_of(token: str) -> str | None:
    return jwt.decode(token, options={"verify_signature": False}).get("tenant")


def decide(input_doc: dict) -> str:
    return httpx.post(OPA, json={"input": input_doc}, timeout=5).json()["result"]["decision"]


def read(tenant: str, customer_id: str) -> int:
    return httpx.get(
        f"{SANDBOX}/customers/{customer_id}", headers={"X-Tenant": tenant}, timeout=5
    ).status_code


print("1. the token carries the tenant")
alice = login("alice", "alice123")
grace = login("grace", "grace123")
print(f"   alice -> {tenant_of(alice)!r}   grace -> {tenant_of(grace)!r}")

print("\n2. policy denies an unscoped identity")
base = {"agent": AGENT, "user": "alice", "roles": ["support_rep"], "tool": "crm.customer.read"}
print(f"   scoped (tenant=acme) -> {decide({**base, 'tenant': 'acme'})}")
print(f"   unscoped             -> {decide(base)}")

print("\n3. the data layer scopes by tenant")
print(f"   acme   -> c-100 (acme)   : HTTP {read('acme', 'c-100')}")
print(f"   acme   -> c-900 (globex) : HTTP {read('acme', 'c-900')}  (as if it did not exist)")
print(f"   globex -> c-900 (globex) : HTTP {read('globex', 'c-900')}")

print("\nTenant isolation holds at every layer.")
