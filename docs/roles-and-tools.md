# Roles and tools

Who may call what. The matrix lives in **one place** — `policy/authz.rego` — and
everything else reads it from there: the tool server that enforces it, the agent
that offers only what it permits, and the page that displays it.

It has **two layers**: a default per role, and an optional per-tenant override.

## The matrix

| role | may call |
| --- | --- |
| `support_rep` | crm.customer.read, crm.orders.list, tickets.read, tickets.reply.draft, refunds.quote, refunds.issue |
| `billing` | crm.orders.list, refunds.quote, refunds.issue |
| `read_only` | crm.customer.read, crm.orders.list, tickets.read |
| `privacy` | privacy.pii.read, crm.customer.read, crm.orders.list, tickets.read |
| `manager` | crm.customer.read, crm.orders.list, tickets.read, refunds.quote |
| `platform_admin` | *(none — administers users, not tools)* |

A user with several roles gets the **union**. Every tool in the catalogue must be
granted to some role — a test asserts it against the catalogue injected into the
policy bundle, so a new tool cannot be silently uncallable.

`platform_admin` is deliberately outside all of this: it administers **users**, and
can neither call tools nor approve/deny held actions. Approving a refund is a
business decision (`manager`), and keeping it out of the administrator's hands is
separation of duties — the person who can grant themselves any role should not
also be able to push business actions through.

On top of the matrix, the same rules as before: refunds are tiered (≤50 allow /
≤500 manager approval / >500 deny), PII needs the `privacy` role **and**
approval, everything is tenant-scoped, and bulk actions are never allowed.

## Per tenant

The table above is the **default**, what every tenant gets. A tenant can override
a role, and an override **replaces** the default for that role entirely — nothing
is merged, so there is one place to read and the failure mode is visible. A role
the tenant does not mention keeps the default.

`globex` is the demonstration: the same role name, less power.

| tenant | role | may call |
| --- | --- | --- |
| `acme` | `support_rep` | crm.customer.read, crm.orders.list, tickets.read, tickets.reply.draft, refunds.quote, **refunds.issue** |
| `globex` | `support_rep` | crm.customer.read, crm.orders.list, tickets.read, tickets.reply.draft, refunds.quote |

So `alice` (acme) may issue a refund and `grace` (globex) may only quote one —
same role name, decided by which customer they belong to. The tenant comes from
the caller's verified token, never from the request, so it cannot be chosen.

The maps live **in the policy file** rather than a data document loaded into OPA,
so changing a customer's powers is a reviewed, signed policy release rather than a
config edit that lands with less scrutiny.

## See it

```bash
./scripts/role-tools.sh
```

```
  user     tenant   role           customer.read    orders.list      refunds.issue    pii.read
  alice    acme     support_rep    allowed          allowed          allowed          DENIED
  grace    globex   support_rep    unknown customer allowed          DENIED           DENIED
  bella    acme     billing        DENIED           allowed          allowed          DENIED
  dana     acme     read_only      allowed          allowed          DENIED           DENIED
  manager  acme     manager        allowed          allowed          DENIED           DENIED
```

(`grace` reading acme's `c-100` says "unknown customer": a record outside your
tenant is deliberately indistinguishable from one that does not exist.)

It is deterministic — it logs in as each user, exchanges the token through the
agent's own identity, and calls every tool at the tool server, which is where the
decision is made.

## Where it is enforced

```
login → token (roles) ─▶ agent ─▶ tool server ─▶ policy ─▶ allow / approval / deny
                            │
                            └── offers the model only the tools the roles permit
```

- **The tool server (PEP) is the control.** It verifies the caller's token, asks
  policy, and refuses what the roles do not grant. The tenant travels with the ask,
  from the identity, so the answer is the caller's own tenant's matrix.
- **The agent's filtering is convenience, not a control.** It asks policy which
  tools the caller's roles permit, *in their tenant*
  (`data.agentnhi.authz.tools_for_roles`) and offers the model only those. It also
  *names* the tools the role may not use and **refuses deterministically** if the
  model asks for one — because hiding them makes a small model substitute a
  different, allowed tool and the run then *looks* like it succeeded (a refund
  request quietly becoming "list orders"). When nothing fits, the run reports that,
  with the model's reason, and executes nothing. If policy is unreachable, or the
  caller has no tenant, the agent offers **no** tools (fails closed).
- **The UI is convenience too.** `/auth/login` returns the caller's tools (from
  policy), so the console can show what they may call and needs no copy of the
  matrix.

## Adding a role or a tool

1. **A tool** — add it to `app/tools/catalog.py`, then grant it in
   `default_role_tools` (and in any tenant override that should have it).
   The bundle injects the catalogue, so the coverage test fails if you forget.
2. **A role** — add it to the realm (`realm.json.tmpl`) and to
   `default_role_tools`. A role absent from both layers can call nothing.
3. **A tenant's difference** — add it to `tenant_role_tools` in the same file.
   Two tests guard the data: an override may only name roles that exist, and only
   tools that are in the catalogue, so a typo cannot quietly remove access.
4. Re-run `./scripts/setup.sh` (it rebuilds the policy bundle and re-renders the
   realm template) and `./scripts/role-tools.sh` to see the new row. Note that the
   realm import is non-destructive (S2): a change to `realm.json.tmpl` — a new
   role, say — needs the realm deleted first, or the import skips it. See the
   operator guide. A **policy** change is picked up by `setup.sh` alone.

## Notes

- **Changes lag by up to one token lifetime** (5 minutes). A grant or revoke takes
  effect the next time the user signs in, like disabling an account.
- **The matrix is per tenant** (see above): a default, plus overrides that replace
  it per role. A role a tenant does not mention falls back to the default, so a new
  default role reaches every tenant without editing their overrides.
- **The reason is always one string.** The deny reasons are an `else` chain, so
  overlapping conditions (e.g. "your role may not call X" *and* "bad amount")
  still produce a single, readable reason rather than a set — which the audit
  trail, the trace and the UI all expect.
