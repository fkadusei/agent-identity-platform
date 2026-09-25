# Enrollment and roles

How people get accounts, how roles are granted, and how roles turn into access.
See also [ADR-0011](decisions/ADR-0011-enrollment-and-role-administration.md).

## Roles

| Role | Can |
| --- | --- |
| `support_rep` | run agent tasks (which then pass policy) |
| `manager` | approve/deny held actions (refunds above the auto-approval limit) |
| `privacy` | access PII tools (via policy; approval still required) |
| `platform_admin` | administer users and roles — **not** tools or approvals |

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

## Seeing it in Keycloak

These users are not in the app. The app keeps no user table: it verifies a token
Keycloak issued and reads `sub`, the realm roles and the `tenant` attribute from
it. To confirm that for yourself, ask Keycloak.

From the terminal, one command. It runs inside the API pod and reuses the API's
own least-privilege client (`platform-admin`: `manage-users` + read-roles), so
there is nothing to set up and no admin password involved:

```bash
./scripts/show-keycloak-users.sh
```

For the admin console itself, two one-time steps — a hosts entry and a
port-forward:

```bash
echo "127.0.0.1 keycloak" | sudo tee -a /etc/hosts      # once
kubectl --context kind-agent-platform -n agent-platform port-forward svc/keycloak 8080:8080
```

Then open <http://keycloak:8080/admin> and sign in as `admin` / `admin`. Switch
the realm selector to **agent-platform** → **Users**. Per user, **Role mapping**
is the realm role and **Attributes** is the tenant.

Two things that will puzzle you otherwise:

- Browsing `localhost:8080` does not work. `KC_HOSTNAME_STRICT=true` pins the
  console to `http://keycloak:8080`, so the browser has to resolve that name —
  hence the hosts entry, and why the redirect otherwise dead-ends.
- The realm holds more users than the demo. `carol-*`, `norole` and `survivor`
  are written by the suites (`demo-roles.sh`, the admin and tenancy tests). The
  realm is a live database and the tests use it, which is worth saying out loud
  when demonstrating rather than hiding.

The console is reachable **only** by port-forward: the ingress routes `/` to the
API (`deploy/kind/manifests/edge/ingress.yaml`), so no admin console is exposed
at the edge — `admin`/`admin` on a public hostname would be the worst day. That
credential is demo-only, used once to create the master realm on a fresh
database.

## Try it end to end

```bash
API=https://localhost:8443      # the https edge (./start.sh); see tls.md
CA=.edge/ca.crt                 # its CA — --cacert, never -k

# 1. enroll a new user (no roles)
curl -s --cacert $CA $API/enroll -H 'content-type: application/json' \
  -d '{"username":"carol","email":"carol@example.com","password":"password1"}'

# 2. carol can sign in but can do nothing (no roles)
curl -s --cacert $CA $API/auth/login -H 'content-type: application/json' \
  -d '{"username":"carol","password":"password1"}'   # -> roles: []

# 3. an admin grants her support_rep
TOKEN=$(curl -s --cacert $CA $API/auth/login -H 'content-type: application/json' \
  -d '{"username":"admin","password":"admin123"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s --cacert $CA $API/admin/users -H "authorization: Bearer $TOKEN"   # find carol's id
curl -s --cacert $CA -X POST $API/admin/users/<id>/roles -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -d '{"role":"support_rep"}'

# 4. carol can now run tasks
```

`./scripts/demo-roles.sh` walks this automatically.

## What a production deployment adds

- authorization-code + PKCE in the browser instead of the server-side grant;
- email verification, rate limiting, and CAPTCHA on `/enroll`;
- rotation of the admin service-account secret;
- an IdP / SCIM for lifecycle (joiner-mover-leaver) rather than manual grants.
