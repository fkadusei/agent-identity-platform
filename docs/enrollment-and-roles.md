# Enrollment and roles

How people get accounts, how roles are granted, and how roles turn into access.
See also [ADR-0011](decisions/ADR-0011-enrollment-and-role-administration.md).

## Roles

| Role | Can |
| --- | --- |
| `support_rep` | run agent tasks (which then pass policy) |
| `manager` | approve/deny held actions (refunds above the auto-approval limit) |
| `privacy` | access PII tools (via policy; approval still required) |
| `platform_admin` | administer users and roles |

A role is only real if the **server** enforces it. The UI hides what you cannot
do, but every check that matters lives in `app/api/authz.py`
(`require_roles(...)`) and in `policy/authz.rego`.

## Enrolling

Two ways to get an account:

1. **Self-service** — the sign-in page's "Create one" link posts to
   `POST /enroll`. The account is created with **no roles** and can do nothing
   until an admin grants one. Roles are never taken from the request, so a
   signup cannot self-escalate. The account is placed in the tenant from
   `DEFAULT_TENANT` — a signup cannot choose its own tenant either
   (see [`tenancy.md`](tenancy.md)).
2. **Admin-created** — an admin uses the Admin tab's "New user" form
   (`POST /admin/users`), which can set roles and the tenant immediately.

Self-service is toggled by `SIGNUP_ENABLED` (set in the API manifest). With
`SIGNUP_ENABLED=0`, `/enroll` returns 403 and only admins can create accounts.

## Granting roles (admin)

Sign in as a `platform_admin` and open the **Admin** tab:

- see every user and their roles;
- tick/untick `support_rep`, `manager`, `privacy`, `platform_admin`;
- enable/disable an account, reset a password, or delete a user;
- create a user with roles.

Each action calls the API (`/admin/users…`), which checks the caller holds
`platform_admin` and writes an audit record (`user.role_granted`, …).

### How the API talks to Keycloak

The API does not hold the bootstrap admin credential. It authenticates to
Keycloak's Admin API as the **`platform-admin` service account**, which holds
only `manage-users` plus read-roles on the realm (`realm.json.tmpl`). Its secret
is generated into the gitignored `.env` and mounted as a Secret
(`docs/secrets.md`).

## Signing in

`POST /auth/login` performs a username/password grant against the `portal`
client. The returned token carries `aud=agent` **and** `aud=mcp-tools`, so one
session can both run tasks and approve. The login response includes the user's
roles, which the UI uses to decide what to show.

Demo accounts: `alice`/`alice123` (support_rep), `manager`/`manager123`
(manager), `admin`/`admin123` (platform_admin).

## Try it end to end

```bash
# 1. enroll a new user (no roles)
curl -s localhost:8080/enroll -H 'content-type: application/json' \
  -d '{"username":"carol","email":"carol@example.com","password":"password1"}'

# 2. carol can sign in but can do nothing (no roles)
curl -s localhost:8080/auth/login -H 'content-type: application/json' \
  -d '{"username":"carol","password":"password1"}'   # -> roles: []

# 3. an admin grants her support_rep
TOKEN=$(curl -s localhost:8080/auth/login -H 'content-type: application/json' \
  -d '{"username":"admin","password":"admin123"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s localhost:8080/admin/users -H "authorization: Bearer $TOKEN"   # find carol's id
curl -s -X POST localhost:8080/admin/users/<id>/roles -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -d '{"role":"support_rep"}'

# 4. carol can now run tasks
```

`./scripts/demo-roles.sh` walks this automatically.

## What a production deployment adds

- authorization-code + PKCE in the browser instead of the server-side grant;
- email verification, rate limiting, and CAPTCHA on `/enroll`;
- rotation of the admin service-account secret;
- an IdP / SCIM for lifecycle (joiner-mover-leaver) rather than manual grants.
