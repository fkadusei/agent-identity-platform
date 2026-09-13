# Operator guide

The runbook for running the platform: bring it up, keep it healthy, change
things safely, and respond when something goes wrong. It assumes you have read
[`real-world-adoption.md`](real-world-adoption.md) and
[`threat-model.md`](threat-model.md).

## 1. The shape of the system

Everything runs in the `agent-platform` namespace.

| Component | What it is | How it authenticates |
| --- | --- | --- |
| `api` | FastAPI: login/enroll/admin, tasks, approvals, audit; also serves the UI | verifies tokens (`aud=mcp-tools`) |
| `tools` | policy enforcement point (the MCP tool servers) | delegated token (`aud=mcp-tools`, `azp`=agent) |
| `agent` | LangGraph runtime (holds no credentials) | user token → RFC 8693 exchange |
| `gateway` | the only component that talks to a model provider | **SPIFFE mTLS** (client SVID required) |
| `opa` | policy decisions | in-cluster, fail-closed |
| `keycloak` | identity, token exchange, user administration | — |
| `spire-server` / `spire-agent` | workload identity (SVIDs) | — |
| `otel-collector` / `jaeger` | traces | — |

Two facts drive most operations: **workload identity is short-lived** (SVIDs are
fetched, never stored) and **policy fails closed** (if OPA is unreachable, the
answer is deny).

## 2. Bring-up

```bash
./scripts/install-hooks.sh     # once: enable the secret-guard pre-commit hook
./scripts/setup.sh             # build images, create the cluster, deploy everything
```

`setup.sh` is gated — it will not report success until:

1. the kind cluster exists and the images are loaded;
2. SPIRE is up and the agent is attested;
3. the realm is rendered from `.env` and imported;
4. OPA is serving the policy bundle (it prints the revision);
5. the collector and Jaeger are ready;
6. api/tools/agent/gateway are rolled out and ready;
7. **the agent pod can fetch its JWT-SVID** (a live identity smoke test).

If any gate fails, fix that and re-run — it is idempotent.

Verify by hand:

```bash
kubectl -n agent-platform get pods
kubectl -n agent-platform port-forward svc/api 8080:8080 &
curl -s localhost:8080/healthz          # {"ok":true}
curl -s localhost:8080/auth/config      # signup toggle + agent SPIFFE ID
./scripts/demo.sh                       # happy path + approval flow
./scripts/attack-tests.sh               # all six attacks blocked
```

## 3. Routine health checks

```bash
# everything ready?
kubectl -n agent-platform get pods
kubectl -n agent-platform get pods \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}'

# policy engine alive?  ({} == healthy)
kubectl -n agent-platform exec deploy/tools -- \
  python -c "import httpx; print(httpx.get('http://opa:8181/health').json())"

# which policy revision is live?
kubectl -n agent-platform exec deploy/tools -- \
  python -c "import httpx,json; print(httpx.get('http://opa:8181/v1/data/agentnhi/authz/policy_version').json())"

# recent decisions (structured)
kubectl -n agent-platform logs deploy/opa --tail=20 | grep decision_id

# durable state reachable?
kubectl -n agent-platform exec deploy/api -- python -c \
  "import os,psycopg; print(psycopg.connect(os.environ['DATABASE_URL']).execute('select 1').fetchone())"
```

What to watch over time:

| Signal | Where | Alert when |
| --- | --- | --- |
| OPA reachable | `/health` | any failure (traffic is being denied) |
| Failed span exports | collector `:8888` | `rate(otelcol_exporter_send_failed_spans[5m]) > 0` |
| Login failures | API logs `auth.login_failed` | a sustained spike |
| Policy denials | audit stream `tool.denied` | an unusual spike for one user/agent |
| Approval backlog | `/approvals?status=pending` | oldest pending age grows |
| Pod restarts | `kubectl get pods` | `RESTARTS` climbing |

## 4. Common operations

### Onboard a user, grant a role

See [`enrollment-and-roles.md`](enrollment-and-roles.md). Via the API:

```bash
TOKEN=$(curl -s localhost:8080/auth/login -H 'content-type: application/json' \
  -d '{"username":"admin","password":"admin123"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# self-service: a user enrolls themselves and starts with no roles
#   POST /enroll
# admin: find them, then grant a role
curl -s localhost:8080/admin/users -H "authorization: Bearer $TOKEN"
curl -s -X POST localhost:8080/admin/users/<id>/roles \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"role":"support_rep"}'
```

### Offboard / kill switch

```bash
# disable (immediate: no new tokens; existing ones live <= 5 min)
curl -s -X POST localhost:8080/admin/users/<id>/enabled \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"enabled":false}'

# revoke a specific role
curl -s -X DELETE localhost:8080/admin/users/<id>/roles/manager \
  -H "authorization: Bearer $TOKEN"
```

### Rotate a secret

Client secrets and the admin service-account secret live in the gitignored
`.env` (see [`secrets.md`](secrets.md)).

```bash
# rotate everything, or edit a single value in .env
rm .env
./scripts/setup.sh
```

> **Caveat.** `setup.sh` recreates Keycloak, whose realm is ephemeral and
> re-imported from the template — so users/roles created at runtime (enrolled
> accounts) are **lost**. In production you rotate in the secret manager and
> restart consumers, without touching the realm.

### Roll out a policy change

See [`policy-lifecycle.md`](policy-lifecycle.md).

```bash
POLICY_REVISION=<new> ./scripts/build-bundle.sh    # version the bundle
./scripts/sign-bundle.sh                            # sign it (keyless in CI)
./scripts/setup.sh                                  # re-applies the bundle to OPA
```

Every decision from then on reports the new revision (in the decision, the audit
event, the trace span and OPA's decision logs). **Roll back** by re-applying the
previous revision's bundle and restarting OPA.

### Sign images / the bundle

See [`supply-chain.md`](supply-chain.md). Keyless in CI on a `v*` tag; the
Kyverno policy admits only images signed by the release workflow identity.

## 5. Incident response

**A. Compromised user account**

```bash
# 1. cut access now
curl -s -X POST localhost:8080/admin/users/<id>/enabled \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' -d '{"enabled":false}'
# 2. revoke roles (manager, privacy, platform_admin first)
# 3. reset the password (Admin tab, or POST /admin/users/<id>/password)
# 4. review what they did
curl -s localhost:8080/audit | python3 -c 'import sys,json;print([e for e in json.load(sys.stdin) if e.get("sub")=="<username>"])'
# 5. follow their calls in Jaeger (filter spans by sub=<username>)
```

**B. Compromised or rogue workload**

The workload's identity is its SVID. Remove the registration entry and the SVID
cannot be renewed:

```bash
SPIRE="kubectl -n agent-platform exec spire-server-0 -- /opt/spire/bin/spire-server"
SOCKET=/run/spire/server/private/api.sock
$SPIRE entry show  -socketPath $SOCKET -spiffeID <spiffe-id>
$SPIRE entry delete -socketPath $SOCKET -entryID <entry-id>
# cut the current SVID immediately:
kubectl -n agent-platform delete pod -l app=<workload>
```

**C. Leaked client secret or admin credential**

Rotate (§4) — the old value stops working as soon as Keycloak re-imports.

**D. Policy engine down**

`tools` **fails closed**: with OPA unreachable, every tool call is denied and
audited as `policy.unavailable`. This is intended, not an outage of policy — it
is policy working. Recover by restoring OPA (the bundle is a ConfigMap):

```bash
kubectl -n agent-platform get pods -l app=opa
kubectl -n agent-platform rollout restart deploy/opa
```

**E. Bad policy shipped**

Roll back to the previous bundle revision (§4). The revision stamped in every
decision tells you exactly what you rolled back from.

**F. Model provider / gateway down**

The `agent` reaches the model only through `gateway`, so tasks fail while the
gateway or provider is unavailable. Check `kubectl -n agent-platform logs
deploy/gateway`; a client without a valid SVID cannot even connect.

## 6. Observability and alerting

- **Traces** — Jaeger: `kubectl -n agent-platform port-forward svc/jaeger 16686:16686`, or `./scripts/show-trace.sh`. Every trace carries the identity on its `policy.decision` span (`spiffe_id`, `sub`, `tool`, `decision`).
- **Transport** — `./scripts/tls-check.sh` reports every in-cluster edge and fails if any is not mTLS (see [`tls.md`](tls.md)).
- **Redundancy** — `./scripts/ha-check.sh` shows the replicas' spread and the PodDisruptionBudgets, then evicts a replica to prove the service survives (see [`ha.md`](ha.md)).
- **Metrics** — Prometheus scrapes the API (`/metrics`), the collector and OPA. Platform counters: logins, policy decisions (from the audit stream), approval backlog, request rates.
- **Dashboard** — Grafana: `kubectl -n agent-platform port-forward svc/grafana 3000:3000` (the "Agent Identity Platform" dashboard is provisioned).
- **Audit** — `GET /audit` (also shown in the UI's Audit tab) is the record of who did what, on whose behalf, and why.

Example Prometheus rules (scrape targets are already configured in
`deploy/kind/manifests/observability/prometheus.yaml`):

```yaml
groups:
  - name: agent-platform
    rules:
      - alert: TraceExportFailing
        expr: rate(otelcol_exporter_send_failed_spans[5m]) > 0
        for: 10m
        labels: { severity: warning }
        annotations:
          summary: "Traces are failing to export — observability gap"
      - alert: NoTracesFlowing
        expr: rate(otelcol_exporter_sent_spans[10m]) == 0
        for: 15m
        labels: { severity: warning }
        annotations:
          summary: "No spans exported — is traffic reaching the services?"
      - alert: LoginFailureSpike
        expr: rate(agent_platform_logins_total{result="failed"}[5m]) > 0.2
        for: 10m
        labels: { severity: warning }
        annotations:
          summary: "Elevated login failures — possible credential stuffing"
      - alert: PolicyDenialSpike
        expr: rate(agent_platform_audit_events_total{event="tool.denied"}[5m]) > 0.5
        for: 10m
        labels: { severity: warning }
        annotations:
          summary: "Policy denials spiking — a misbehaving agent or a bad policy?"
      - alert: ApprovalBacklog
        expr: agent_platform_approvals_pending > 10
        for: 30m
        labels: { severity: warning }
        annotations:
          summary: "Approvals are piling up — is anyone on call?"
```

Load them into Prometheus with a `rule_files:` entry in the ConfigMap.

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Login returns `502 login failed` | realm not imported with the current secrets | `setup.sh` recreates Keycloak each run; re-run it |
| `invalid token: Not enough segments` | client sent a malformed/absent token | re-login; check the UI is current (rebuild the API image) |
| `Failed to fetch` in the browser | API unreachable — dropped `port-forward`, or dev-server proxy | restart `kubectl port-forward svc/api 8080:8080`; in dev, restart `npm run dev` |
| OPA pod `CrashLoopBackOff`, `manifest roots … do not permit` | the bundle ConfigMap's `..data` dir was scanned | bundle files are mounted individually — re-apply `deploy/kind/manifests/opa/` |
| `Account is not fully set up` on login | Keycloak user profile requires first/last name | the API defaults names on create; for old users, set them in Admin |
| Tools return `policy unavailable — denying` | OPA unreachable (fail-closed) | restore OPA (§5D) |
| `no attested SPIRE agent found` | agent not attested yet | re-run `setup.sh`; check `spire-agent` logs |
| Enrolled user vanished | Keycloak was recreated by `setup.sh` (ephemeral realm) | re-enroll, or use a persistent database in production |
| Approvals/runs vanish on restart | `DATABASE_URL` not set (in-memory stores) | set `DATABASE_URL` (see [`data-stores.md`](data-stores.md)) |
| An edge is not `SECURED` in `tls-check.sh` | the pod is not mesh-injected | annotate the namespace (`linkerd.io/inject=enabled`) and restart the deployment |
| An agent gets `429` from the gateway | it hit its rate or token budget | raise `LLM_RATE_LIMIT_PER_MINUTE` / `LLM_TOKEN_BUDGET_PER_DAY`, or check `llm.limited` in the audit ([`llm-gateway.md`](llm-gateway.md)) |

## 8. Teardown

```bash
./scripts/teardown.sh     # deletes the kind cluster; everything is disposable
```

## 9. Phase 2 gate checklist

Passed 2026-09-12:

- [x] **Threat model addressed** — every T1–T10 has a control or a documented, scoped exception. T9 (multi-tenant isolation) is honestly marked *not implemented* (single-tenant reference) and tracked in the backlog.
- [x] **Traces live** — Jaeger shows end-to-end traces across agent, api, gateway and tools, with identity attributes on the `policy.decision` span.
- [x] **Dashboards live** — Prometheus scrapes all targets (`api`, `opa`, `otel-collector` all `up`); the Grafana dashboard is provisioned.
- [x] **Secret audit clean** — `./scripts/scan-secrets.sh` reports no leaks (tree + history); `./scripts/test-hooks.sh` proves the hook blocks a staged secret.
- [x] **Attacks blocked** — `./scripts/attack-tests.sh` shows all six blocked.
- [x] **Supply chain** — images/bundle signed keyless in CI; Kyverno admission policy enforces signatures (not exercised by the local kind load).
