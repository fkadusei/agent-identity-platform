# Roles and tools

Who may call what. The matrix lives in **one place** — `policy/authz.rego` — and
everything else reads it from there.

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

## See it

```bash
./scripts/role-tools.sh
```

```
  user     role           customer.read    orders.list      refunds.issue    pii.read
  alice    support_rep    allowed          allowed          allowed          DENIED
  bella    billing        DENIED           allowed          allowed          DENIED
  dana     read_only      allowed          allowed          DENIED           DENIED
  manager  manager        allowed          allowed          DENIED           DENIED
```

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
  policy, and refuses what the roles do not grant. Nothing else can bypass it.
- **The agent's filtering is convenience, not a control.** It asks policy which
  tools the caller's roles permit (`data.agentnhi.authz.tools_for_roles`) and
  offers the model only those, so it does not propose a tool that will be denied.
  If policy is unreachable the agent offers **no** tools (fails closed), and if the
  model finds no tool that fits the task it reports that instead of quietly doing
  something else.
- **The UI is convenience too.** `/auth/login` returns the caller's tools (from
  policy), so the console can show what they may call and needs no copy of the
  matrix.

## Adding a role or a tool

1. **A tool** — add it to `app/tools/catalog.py`, then grant it in `role_tools`.
   The bundle injects the catalogue, so the coverage test fails if you forget.
2. **A role** — add it to the realm (`realm.json.tmpl`) and to `role_tools`.
   A role absent from the matrix can call nothing.
3. Re-run `./scripts/setup.sh` (the realm is re-imported and the bundle rebuilt)
   and `./scripts/role-tools.sh` to see the new row.

## Notes

- **Changes lag by up to one token lifetime** (5 minutes). A grant or revoke takes
  effect the next time the user signs in, like disabling an account.
- **The matrix is global**, not per-tenant. Per-tenant role mappings would be a
  further step.
- **The reason is always one string.** The deny reasons are an `else` chain, so
  overlapping conditions (e.g. "your role may not call X" *and* "bad amount")
  still produce a single, readable reason rather than a set — which the audit
  trail, the trace and the UI all expect.
