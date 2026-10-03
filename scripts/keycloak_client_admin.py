"""Enable/disable a Keycloak client by its `clientId` (S23).

Runs inside the API pod (see `scripts/revoke-workload.sh`), using the same
least-privilege `platform-admin` service account the API uses. The client whose
`clientId` is a workload's SPIFFE ID is the agent's delegation client; disabling
it stops that workload exchanging tokens — the half of revocation that lives in
Keycloak.

Usage (via kubectl exec):
    python - disable <clientId>
    python - enable  <clientId>
"""
from __future__ import annotations

import sys

from app.api.identity import admin_from_env


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in ("disable", "enable"):
        print("usage: keycloak_client_admin.py disable|enable <clientId>", file=sys.stderr)
        return 2
    action, client_id = argv[0], argv[1]
    admin = admin_from_env()
    ok = admin.set_client_enabled(client_id, action == "enable")
    print(f"{action}d client {client_id!r}" if ok else f"no client named {client_id!r}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
