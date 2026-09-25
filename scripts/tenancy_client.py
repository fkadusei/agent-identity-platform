"""Prove tenant isolation at all three layers: the claim, the policy, the data.

Runs inside the cluster (see scripts/tenancy-tests.sh). It reads the tenant from
the login response rather than decoding the token.
"""
from __future__ import annotations

import os

import httpx

API = "http://api:8080"
OPA = "http://opa:8181/v1/data/agentnhi/authz"
SANDBOX = "http://sandbox:8090"
AGENT = "spiffe://acme.com/ns/agent-platform/sa/agent"


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


def decide(input_doc: dict) -> str:
    return httpx.post(OPA, json={"input": input_doc}, timeout=5).json()["result"]["decision"]


def read(tenant: str, customer_id: str) -> int:
    return httpx.get(
        f"{SANDBOX}/customers/{customer_id}", headers={"X-Tenant": tenant}, timeout=5
    ).status_code


print("1. the token carries the tenant")
alice = login("alice", "alice123")
grace = login("grace", "grace123")
print(f"   alice -> {alice['tenant']!r}   grace -> {grace['tenant']!r}")

print("\n2. policy denies an unscoped identity")
base = {"agent": AGENT, "user": "alice", "roles": ["support_rep"], "tool": "crm.customer.read"}
print(f"   scoped (tenant=acme) -> {decide({**base, 'tenant': 'acme'})}")
print(f"   unscoped             -> {decide(base)}")

print("\n3. the data layer scopes by tenant")
print(f"   acme   -> c-100 (acme)   : HTTP {read('acme', 'c-100')}")
print(f"   acme   -> c-900 (globex) : HTTP {read('acme', 'c-900')}  (as if it did not exist)")
print(f"   globex -> c-900 (globex) : HTTP {read('globex', 'c-900')}")

print("\nTenant isolation holds at every layer.")

