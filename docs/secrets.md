# Secrets

**The rule: no secret is committed, and no secret lives in a manifest.** The
repository contains templates and references; the values come from a store at
deploy time.

## What counts as a secret here

| Item | Secret? | Where it lives |
|---|---|---|
| SPIFFE workload identities (SVIDs) | no — fetched, never stored | issued on demand by SPIRE |
| Human demo logins (`alice`/`manager`/`admin`) | documented demo values | realm template + guides |
| Keycloak **client secrets** (`demo-cli`, `manager-cli`, `mcp-tools`, `portal`) | **yes** | generated into a gitignored `.env` |
| Keycloak **admin** service-account secret (`platform-admin`) | **yes** | gitignored `.env` → Secret, read only by the API |
| The demo **database** password (`postgres`) | **yes** | gitignored `.env` → the `postgres` Secret, read by the API/agent/gateway |
| SPIRE's **datastore** password (the `spire` role) | **yes** | gitignored `.env` → rendered into `server.conf` → the `spire-server-config` Secret |
| LLM provider key | **yes** (optional) | gitignored `.env` → Kubernetes Secret, read **only** by the gateway |

## How it works locally (kind)

1. `scripts/setup.sh` creates `.env` on first run (mode 0600) with **random**
   client secrets, or reuses the existing file:
   ```sh
   DEMO_CLI_SECRET=<random>
   MANAGER_CLI_SECRET=<random>
   MCP_TOOLS_SECRET=<random>
    PORTAL_SECRET=<random>          # the web app's login client
    ADMIN_CLIENT_SECRET=<random>    # the API's least-privilege admin client
    POSTGRES_PASSWORD=<random>      # the demo database
    SPIRE_DB_PASSWORD=<random>      # SPIRE's own role in that database (S1)
    # LLM_API_KEY=...               # optional, for a hosted model
    ```
2. The Keycloak realm is **rendered** from `realm.json.tmpl` (`${VAR}`
   placeholders) with those values, then applied as a ConfigMap. The template is
   committed; the values are not. SPIRE's `server.conf` is rendered the same way —
   from `server.conf.tmpl` into a **Secret**, because the datastore connection
   string carries its password.
3. The API gets `DEMO_CLI_SECRET` / `MANAGER_CLI_SECRET` (scripted demo),
   `PORTAL_SECRET` (login), and `ADMIN_CLIENT_SECRET` (enrollment + role
   management) from the `platform-secrets` Secret, mounted as environment
   variables. The admin secret is **least privilege**: the service account holds
   only `manage-users` plus read-roles on the realm — never the bootstrap admin.
4. If `LLM_API_KEY` is set, it is placed in the `llm-api-key` Secret, consumed
   **only** by the gateway.

`.env` is in [`.gitignore`](../.gitignore); CI runs gitleaks plus an explicit
check that `.env` is never tracked.

## Production: a real secret manager

The local `.env` is a stand-in. In production, an **External Secrets Operator
(ESO)** syncs from a manager (HashiCorp Vault, AWS Secrets Manager, GCP Secret
Manager) into the *same* Kubernetes Secrets, so nothing in the manifests or the
application code changes.

```yaml
# Example (requires the External Secrets Operator + a SecretStore/ClusterSecretStore)
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: platform-secrets
  namespace: agent-platform
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault
    kind: ClusterSecretStore
  target:
    name: platform-secrets        # the same name the API already mounts
  data:
    - secretKey: DEMO_CLI_SECRET
      remoteRef: { key: agent-platform/demo-cli, property: secret }
    - secretKey: MANAGER_CLI_SECRET
      remoteRef: { key: agent-platform/manager-cli, property: secret }
```

An `ExternalSecret` for `llm-api-key` works the same way; the gateway is its only
consumer, so its blast radius is one component.

## Rotation

- **SPIFFE SVIDs** rotate automatically (minutes); there is nothing to rotate.
- **Client secrets**: change the value in the manager; ESO re-syncs the Secret
  and the Keycloak client is updated on the next realm apply. Because the agent
  authenticates with its SVID (no client secret), only the *human* login clients
  and the audience client are affected.
- **LLM key**: rotate in the manager; the gateway picks it up on restart.

## Why not just put them in a manifest?

A manifest is copied into the repo, into CI logs, into `kubectl get -o yaml`
output, and into backups. A Secret that exists only at deploy time, from a
manager, has far fewer places to leak — and can be rotated and audited centrally.
