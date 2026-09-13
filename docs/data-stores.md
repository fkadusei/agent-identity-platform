# Data stores

Some state must survive a restart; some must not. The rule here is simple: state
that a *decision* depends on is durable, state that is a *fixture* is not.

| State | Backend | Why |
| --- | --- | --- |
| **Approvals** | Postgres (durable) | an approval outlives the request that created it; two replicas must agree |
| **Agent run checkpoints** | Postgres (durable) | a paused run must be resumable after a restart, by any replica |
| **Tool simulators** | in-memory | synthetic fixtures; a reset is harmless (and documented) |
| **Audit timeline** | in-memory ring (500) | the durable audit record is the stdout stream, not this buffer |

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

## Agent run checkpoints

The agent graph takes an injectable checkpointer (`build_agent(deps,
checkpointer=...)`). With `DATABASE_URL` set it uses LangGraph's
`PostgresSaver`, so a run that pauses for approval is stored in Postgres and can
be resumed after the agent pod restarts.

The **token is deliberately not durable.** A resume that lands on a process which
never saw the run carries the caller's token again
(`/tasks/resume` → `/resume` forwards it), and the agent rebuilds itself from the
durable checkpoint. A stored token would be a static credential — exactly what
this platform removes.

## Local (kind)

`scripts/setup.sh` deploys Postgres (`deploy/kind/manifests/data/postgres.yaml`)
with a generated password and wires `DATABASE_URL` into the api and agent. To
watch durability:

```bash
# create an approval, then restart the API and look again
kubectl -n agent-platform rollout restart deploy/api
kubectl -n agent-platform rollout status deploy/api
curl -s localhost:8080/approvals          # the pending approval is still there
```

To run **without** Postgres (in-memory), remove the `PG*` env from the
api/agent manifests and re-apply.

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

- The kind Postgres uses `emptyDir` — data is lost with the cluster. That is
  deliberate (disposable demo); production uses managed storage.
- The agent holds a single Postgres connection for the process lifetime. That is
  fine at demo scale; a busy deployment would use a connection pool.
