"""A thin, least-privilege client for Keycloak's Admin API.

The API uses a dedicated service account (`platform-admin`) that holds only
`manage-users` plus read-roles on the realm — **not** the bootstrap admin
credential. Its secret comes from a Secret, so no admin password lives in the
app or the repo.

Used for self-service enrollment and admin role management
(see docs/enrollment-and-roles.md).
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from agentnhi import Settings


class IdentityAdmin:
    """Create users and manage their realm roles via the Admin API."""

    def __init__(
        self,
        *,
        admin_url: str,
        issuer: str,
        client_id: str,
        client_secret: str,
        client: Any | None = None,
    ):
        self._admin_url = admin_url.rstrip("/")
        self._issuer = issuer.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._client = client or httpx.Client()

    # -- service-account token ------------------------------------------------
    def _headers(self) -> dict:
        resp = self._client.post(
            f"{self._issuer}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            timeout=10,
        )
        resp.raise_for_status()
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def _request(self, method: str, path: str, **kwargs) -> Any:
        return self._client.request(
            method, f"{self._admin_url}{path}", headers=self._headers(), timeout=15, **kwargs
        )

    # -- users ----------------------------------------------------------------
    def list_users(self) -> list[dict]:
        resp = self._request("GET", "/users", params={"max": 200})
        resp.raise_for_status()
        return resp.json()

    def find_user(self, username: str) -> dict | None:
        resp = self._request(
            "GET", "/users", params={"username": username, "exact": "true"}
        )
        resp.raise_for_status()
        users = resp.json()
        return users[0] if users else None

    def create_user(
        self,
        *,
        username: str,
        email: str,
        password: str,
        first_name: str = "",
        last_name: str = "",
        tenant: str = "",
    ) -> str:
        """Create a user and return its id. Raises ValueError on a duplicate."""
        payload: dict = {
            "username": username,
            "email": email,
            "enabled": True,
            "emailVerified": True,
            # Keycloak's default user profile requires firstName/lastName; a user
            # missing them is "not fully set up" and cannot log in. Default to the
            # username so a created account is always usable.
            "firstName": first_name or username,
            "lastName": last_name or username,
            "requiredActions": [],
            "credentials": [{"type": "password", "value": password, "temporary": False}],
        }
        if tenant:
            # The tenant is an identity attribute, mapped into the token by the
            # realm's `tenant` protocol mapper. Without it the account is
            # unscoped and policy denies everything.
            payload["attributes"] = {"tenant": [tenant]}
        resp = self._request("POST", "/users", json=payload)
        if resp.status_code == 409:
            raise ValueError("that username is already taken")
        resp.raise_for_status()
        location = resp.headers.get("Location", "")
        if location:
            return location.rsplit("/", 1)[-1]
        found = self.find_user(username)
        return (found or {}).get("id", "")

    def set_enabled(self, user_id: str, enabled: bool) -> None:
        resp = self._request("PUT", f"/users/{user_id}", json={"enabled": enabled})
        resp.raise_for_status()

    def reset_password(self, user_id: str, password: str) -> None:
        resp = self._request(
            "PUT",
            f"/users/{user_id}/reset-password",
            json={"type": "password", "value": password, "temporary": False},
        )
        resp.raise_for_status()

    def delete_user(self, user_id: str) -> None:
        resp = self._request("DELETE", f"/users/{user_id}")
        resp.raise_for_status()

    # -- roles ----------------------------------------------------------------
    def _role(self, name: str) -> dict | None:
        resp = self._request("GET", f"/roles/{name}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def user_role_names(self, user_id: str) -> list[str]:
        resp = self._request("GET", f"/users/{user_id}/role-mappings/realm")
        resp.raise_for_status()
        return sorted(r["name"] for r in resp.json())

    def assign_role(self, user_id: str, name: str) -> None:
        role = self._role(name)
        if role is None:
            raise ValueError(f"unknown role: {name}")
        resp = self._request(
            "POST", f"/users/{user_id}/role-mappings/realm", json=[role]
        )
        resp.raise_for_status()

    def remove_role(self, user_id: str, name: str) -> None:
        role = self._role(name)
        if role is None:
            raise ValueError(f"unknown role: {name}")
        resp = self._request(
            "DELETE", f"/users/{user_id}/role-mappings/realm", json=[role]
        )
        resp.raise_for_status()


def admin_from_env() -> IdentityAdmin:
    settings = Settings.from_env()
    realm = settings.keycloak_issuer.rstrip("/")
    return IdentityAdmin(
        admin_url=os.environ.get("KEYCLOAK_ADMIN_URL", realm.replace("/realms/", "/admin/realms/")),
        issuer=realm,
        client_id=os.environ.get("ADMIN_CLIENT_ID", "platform-admin"),
        client_secret=os.environ.get("ADMIN_CLIENT_SECRET", ""),
    )
