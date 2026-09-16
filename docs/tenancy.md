# Tenancy

Tenant isolation is enforced in three places, and the rule is the same at each:
**the tenant comes from the identity, never from the request.**

```
token claim ──▶ policy (deny if unscoped) ──▶ tool/backend (scope every access)
```

## 1. The claim

The tenant is a Keycloak **user attribute**, mapped into the access token by the
realm's `tenant` protocol mapper. It survives the agent's token exchange (the
mapper is on the agent's client too), so the tools see the same tenant the user
logged in with.

The realm declares the attribute in its user profile (`unmanagedAttributePolicy:
ENABLED`), so the Admin API accepts it — without that, Keycloak 26 silently drops
undeclared attributes on created users.

## 2. Policy

`policy/authz.rego` denies any caller without a tenant:

```rego
deny if not input.tenant   # fail closed: an unscoped identity gets nothing
```

So even if a tool were called with a tenant it should not have, an identity with
no tenant cannot proceed at all.

The tenant also selects **which role → tool matrix applies** (S8): a tenant can
replace a role's tools, so the same role name grants different power in `acme` and
`globex`. That is resolved in policy, from `input.tenant`, and the agent asks for
the caller's tools *in their tenant* — so what the model is offered and what the
tool server allows cannot disagree. See [`roles-and-tools.md`](roles-and-tools.md).

## 3. The tools

Every data accessor takes the tenant — there is no way to read or write without
naming one:

```python
backend.get_customer(customer_id, tenant)   # returns None outside the tenant
```

The simulator backend filters the synthetic data; the HTTP backend sends it as
`X-Tenant`, the header a real multi-tenant API would scope on, and the sandbox
service enforces it. A record from another tenant is a **404**, indistinguishable
from a record that does not exist — so tenancy does not leak *existence* either.

## The platform's own state

Tenancy applies to the platform's own records, not just the data behind the tools:

| Record | Scoped by |
| --- | --- |
| approvals (`create`/`list`/`decide`/`verify`) | the caller's tenant |
| the approval queue (`GET /approvals`) | the caller's token, and filtered |

The tenant is never a request parameter — it comes from the verified token, so a
caller cannot ask for another tenant's queue. Another tenant's approval is
indistinguishable from one that does not exist: a decision returns 409.

## Enrollment

- **Self-service** (`POST /enroll`): the tenant is taken from `DEFAULT_TENANT`
  (API config), never from the request. A signup cannot choose its own tenant.
- **Admin-created** (`POST /admin/users`): the admin names the tenant (defaulting
  to `DEFAULT_TENANT`).

## See it

```bash
./scripts/tenancy-tests.sh
```

```
1. the token carries the tenant
   alice -> 'acme'   grace -> 'globex'
2. policy denies an unscoped identity
   scoped (tenant=acme) -> allow
   unscoped             -> deny
3. the data layer scopes by tenant
   acme   -> c-100 (acme)   : HTTP 200
   acme   -> c-900 (globex) : HTTP 404  (as if it did not exist)
   globex -> c-900 (globex) : HTTP 200
```

## What is not covered

- **A tenant per IdP/org** — the reference puts users in a tenant attribute;
  federating whole organizations is a further step.
- **Resource-level tenancy in every store** — approvals and run checkpoints are
  keyed by user/agent, not tenant; adding a tenant column there is the next step
  if those are ever shared across tenants.
