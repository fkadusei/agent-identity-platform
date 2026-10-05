"""Create, enable/disable, or delete a Keycloak client by its `clientId` (S23/S26).

Runs inside the API pod (see `scripts/revoke-workload.sh` and
`scripts/decommission-workload.sh`), using the same least-privilege
`platform-admin` service account the API uses. The client whose `clientId` is a
workload's SPIFFE ID is the agent's delegation client: disabling it stops token
exchange, deleting it reaps the registration when the workload is retired.

Usage (via kubectl exec):
    python - create  <clientId>
    python - disable <clientId>
    python - enable  <clientId>
    python - delete  <clientId>
    python - show    <clientId>     # prints found|missing (tests)
"""
from __future__ import annotations

import sys

from app.api.identity import admin_from_env

_ACTIONS = ("create", "disable", "enable", "delete", "show")


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in _ACTIONS:
        print(f"usage: keycloak_client_admin.py {'|'.join(_ACTIONS)} <clientId>", file=sys.stderr)
        return 2
    action, client_id = argv[0], argv[1]
    admin = admin_from_env()

    try:
        if action == "show":
            print("found" if admin.find_client(client_id) else "missing")
            return 0
        if action == "create":
            admin.create_client(client_id)
            print(f"created client {client_id!r}")
            return 0
        if action == "delete":
            ok = admin.delete_client(client_id)
            print(f"deleted client {client_id!r}" if ok else f"no client named {client_id!r}")
            return 0 if ok else 1
        ok = admin.set_client_enabled(client_id, action == "enable")
        print(f"{action}d client {client_id!r}" if ok else f"no client named {client_id!r}")
        return 0 if ok else 1
    except Exception as exc:  # noqa: BLE001 - report, do not traceback
        print(f"keycloak admin call failed: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
