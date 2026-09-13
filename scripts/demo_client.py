"""The happy path, run inside the agent pod: login -> run -> approval -> resume.

Piped to the agent pod by scripts/demo.sh (it needs the pod's SPIFFE socket and
network access to the services).
"""
import json
import os

import httpx

KC = "http://keycloak:8080/realms/agent-platform"
AGENT = "http://agent:8081"
API = "http://api:8080"

# Client secrets come from the environment (a Secret), never from source.
DEMO_CLI_SECRET = os.environ["DEMO_CLI_SECRET"]
MANAGER_CLI_SECRET = os.environ["MANAGER_CLI_SECRET"]


def login(username, password, client_id, secret):
    resp = httpx.post(
        f"{KC}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": client_id,
            "client_secret": secret,
            "username": username,
            "password": password,
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def run(task, token):
    resp = httpx.post(
        f"{AGENT}/run", json={"task": task}, headers={"Authorization": f"Bearer {token}"}, timeout=180
    )
    resp.raise_for_status()
    return resp.json()


def show(label, payload):
    print(f"\n--- {label} ---")
    print(json.dumps(payload, indent=2, sort_keys=True))


print("1. alice (support rep) logs in")
alice = login("alice", "alice123", "demo-cli", DEMO_CLI_SECRET)
print("   got alice's token")

show("2. agent run — a read (allowed)", run("Get the profile of customer c-100", alice))

print("\n3. agent run — a $200 refund (policy requires approval)")
outcome = run("Issue a refund of 200 dollars for order o-1001", alice)
show("agent paused", outcome)

if outcome.get("status") == "approval_required":
    approval_id = outcome["approval_id"]
    print(f"\n4. manager reviews approval {approval_id}")
    manager = login("manager", "manager123", "manager-cli", MANAGER_CLI_SECRET)
    # The queue is tenant-scoped, so it needs the caller's token.
    pending = httpx.get(
        f"{API}/approvals?status=pending",
        headers={"Authorization": f"Bearer {manager}"},
        timeout=10,
    ).json()
    print(f"   approval queue: {len(pending)} pending — {pending[0]['reason'] if pending else ''}")

    decided = httpx.post(
        f"{API}/approvals/{approval_id}/decision",
        json={"approved": True, "note": "within policy"},
        headers={"Authorization": f"Bearer {manager}"},
        timeout=10,
    ).json()
    print(f"   manager decided: {decided.get('status')}")

    show("5. agent resumes after approval", httpx.post(
        f"{AGENT}/resume",
        json={"thread_id": outcome["thread_id"], "approved": True},
        headers={"Authorization": f"Bearer {alice}"},
        timeout=60,
    ).json())
else:
    print("   (the model chose a different tool; no approval was required)")

print("\nDone.")
