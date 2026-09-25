"""List the users that really exist in Keycloak.

Runs inside the API pod (see scripts/show-keycloak-users.sh). It asks Keycloak's
Admin API, using the same least-privilege service account the API itself uses to
manage users — `platform-admin`, which holds `manage-users` plus read-roles on
the realm and nothing else. The master `admin` credential is deliberately not
used here.

The point is to answer one question in a way the app cannot fake: are these users
in the identity provider, or only in our own database? This asks Keycloak.
"""
from __future__ import annotations

import os

from app.api.identity import admin_from_env

# Every user carries this; it is not a role anybody was granted.
_DEFAULT_ROLE_PREFIX = "default-roles-"


def main() -> None:
    admin = admin_from_env()
    realm = os.environ.get("KC_ISSUER", "").rstrip("/").split("/realms/")[-1] or "?"

    users = sorted(admin.list_users(), key=lambda u: u["username"])
    width = max((len(u["username"]) for u in users), default=10)

    print(f"Keycloak realm {realm!r}: {len(users)} users, as Keycloak reports them")
    print("(read with the platform-admin service account: manage-users + read-roles)\n")

    for user in users:
        username = user["username"]
        tenant = (user.get("attributes") or {}).get("tenant", ["-"])[0]
        roles = [
            r for r in admin.user_role_names(user["id"]) if not r.startswith(_DEFAULT_ROLE_PREFIX)
        ]
        note = []
        if username.startswith("service-account-"):
            note.append("service account")
        if not user.get("enabled", True):
            note.append("disabled")
        print(
            f"  {username:<{width}}  tenant={tenant:<7} "
            f"roles={','.join(roles) or '-':<16} {' '.join(note)}"
        )

    print("\nThese users are rows in Keycloak's own database, not in the app.")


if __name__ == "__main__":
    main()
