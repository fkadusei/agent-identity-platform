# Data stores

Some state must survive a restart; some must not. The rule here is simple: state
that a *decision* depends on is durable, state that is a *fixture* is not — and a
fixture that a restart makes confusing is kept by whoever owns it, which for the
simulated systems is the sandbox itself (S9).

| State | Backend | Why |
| --- | --- | --- |
| **Approvals** | Postgres (durable) | an approval outlives the request that created it; two replicas must agree |
| **Agent run checkpoints** | Postgres (durable) | a paused run must be resumable after a restart, by any replica |
| **Simulated systems** (the systems the tools act on) | the sandbox's own volume (durable) | synthetic fixtures — but a restart resetting every refund and draft mid-demo was confusing, so the sandbox snapshots them (S9). It owns this storage, as a stand-in for the vendor's database: the platform's Postgres is not the vendor's |
| **Audit timeline** | Postgres (durable) | "who looked at personal data, and who approved it" cannot be answered from a buffer that one replica holds and a restart clears |
| **SPIRE's registration registry** | Postgres (durable) | an attested agent, and every registration entry, must outlive the identity server's pod — losing them means no SVIDs for anything (S1) |
| **Keycloak's realm and users** | Postgres (durable) | accounts enrolled at runtime, and the realm the tokens are issued from, must outlive the pod — and two replicas must share them (S2) |

## Selecting the backend

Two standard ways to point at a database — when neither is set, the api and agent
use their in-memory stores, so tests and a single-process demo need no database:

- **`DATABASE_URL`** — one DSN string (what the Helm chart takes from an
  operator), in libpq's URI form naming the user, password, host and database.

- **the libpq `PG*` variables** — `PGHOST`, `PGUSER`, `PGPASSWORD`,
  `PGDATABASE`. The kind manifests use these so the password stays a Secret
  reference and **no credential ever appears in a URL**.

The choice lives in `app/common/db.py` (`database_configured()`) and each store's
`build_store()` / `get_checkpointer()`, so the service code does not branch on it.

**Two other services have their own datastore setting**, and in the kind manifests
both point at this same Postgres, each with a dedicated least-privilege role:
SPIRE (`spire`, S1) and Keycloak (`keycloak`, S2). So in the local setup identity
and tokens — not just the app — depend on the database being up.

## Approvals

`app/approvals/store.py` has two implementations behind identical semantics:

- `ApprovalStore` — in-memory (the default).
- `PostgresApprovalStore` — a single `approvals` table; selected when
  `DATABASE_URL` is set.

The security rules are enforced **in SQL**, not in application code, so they hold
under concurrency:

```sql
-- approve/deny: only a pending approval, and never by its own requester
UPDATE approvals SET status = %s, approver = %s, ...
 WHERE id = %s AND status = 'pending' AND "user" <> %s
 RETURNING ...
```

Two approvers racing on the same approval: exactly one `UPDATE` matches. A
requester approving their own: zero rows, refused — the same separation of duties
the in-memory store enforces, but atomic.

`verify()` re-checks the approval against the *exact* request (tool, arguments,
user, agent), so an approval cannot be replayed for a different action.

## Audit

`app/audit/store.py` follows the same shape as the approvals store: `AuditStore`
(in-memory, bounded at 500) when no database is configured, `PostgresAuditStore`
(the `audit_events` table) when one is, and `build_audit_store()` choosing.

Only `ts`, `event`, `sub`, `tenant`, `tool` and `decision` are columns; the record
itself is kept whole as `jsonb`, because the point of a trail is to be able to read
what happened. Records arrive already redacted — `agentnhi.audit` strips secrets
and personal data in the service that emits them, so nothing here decides what is
safe to store.

It used to be an in-memory deque in the API process, which made the privacy view
wrong rather than merely incomplete: with two API replicas each pod held a
different subset of the events, and a rollout cleared it.

## Agent run checkpoints

The agent graph takes an injectable checkpointer (`build_agent(deps,
checkpointer=...)`). With `DATABASE_URL` set it uses LangGraph's
`PostgresSaver`, so a run that pauses for approval is stored in Postgres and can
be resumed after the agent pod restarts.

The checkpointer holds a **connection pool** (`psycopg_pool`), not one connection,
and re-ensures its schema on each request — the same defence the approvals and
audit stores apply per operation. A Postgres restart drops the sockets, and a
restored or replaced database can come back without the schema; either way a run
after the restart succeeds without restarting the agent. Before S12 the single
connection stayed broken forever:

```
psycopg.OperationalError: server closed the connection unexpectedly
```

The pool's backends identify themselves as `application_name=agent-checkpointer`
in `pg_stat_activity`, which is also how the S12 test simulates a restart.

The **token is deliberately not durable.** A resume that lands on a process which
never saw the run carries the caller's token again
(`/tasks/resume` → `/resume` forwards it), and the agent rebuilds itself from the
durable checkpoint. A stored token would be a static credential — exactly what
this platform removes.

## Local (kind)

`scripts/setup.sh` deploys Postgres (`deploy/kind/manifests/data/postgres.yaml`)
with a generated password, wires `DATABASE_URL` into the api and agent, and creates
the `spire` and `keycloak` roles and databases for SPIRE's registry and Keycloak's
realm. To watch durability:

```bash
# create an approval, then restart the API and look again
kubectl -n agent-platform rollout restart deploy/api
kubectl -n agent-platform rollout status deploy/api
curl -s localhost:8080/approvals          # the pending approval is still there

# the state is on a PersistentVolumeClaim, so it also outlives the database:
kubectl -n agent-platform delete pod -l app=postgres
kubectl -n agent-platform rollout status deploy/postgres
curl -s localhost:8080/approvals          # still there
```

To run the app's stores **without** Postgres (in-memory), remove the `PG*` env
from the api/agent manifests and re-apply. SPIRE's registry and Keycloak's realm
still need the database — they live there (S1, S2) — so this takes only the *app*
stores back to memory.

## Production (Helm)

The chart takes an external DSN — use a managed database (RDS/Cloud SQL/Aurora):

```bash
# keep the DSN out of shell history / values files
helm upgrade agent-platform deploy/helm/agent-platform \
  --set-file database.url=dsn.txt
```

With `database.url` empty the chart deploys the in-memory stores; the chart does
not run a database for you, because that is an environment decision (managed
service, operator, or an external cluster).

## Notes and limits

- The kind Postgres keeps its data on a `PersistentVolumeClaim` (kind's
  `local-path` StorageClass), so approvals, checkpoints, gateway counters and the
  audit trail survive deleting the pod — and a `setup.sh` re-run. The volume is
  node-local, so the pod cannot be rescheduled to another node, and it is deleted
  with the cluster (`./stop.sh --delete`).
- Production points `database.url` at a managed database **with backups**. The PVC
  is a demo-scale substitute for durability, not a backup strategy (S3 in
  [`backlog.md`](backlog.md)).
- Every store recreates its tables on demand (`CREATE TABLE IF NOT EXISTS`), so a
  database that comes back empty still works — just without its history.
- The sandbox keeps its refunds and drafts across a restart (S9), so repeated demo
  runs accumulate on the same order. Remove `/data/sandbox-state.json` in the sandbox
  pod and restart it (`./stop.sh --delete` drops the volume) for a clean baseline.
- The agent's checkpointer pool is sized `min_size=1, max_size=5`. That is demo
  scale; size it against the database's connection budget in production (and put a
  pooler in front).
