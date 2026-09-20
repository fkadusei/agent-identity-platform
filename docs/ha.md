# High availability

HA is a property of *state*: a component can be replicated only if the state it
depends on lives somewhere else. That is the rule this page applies.

## Replicated

| Service | Replicas | Why it can be |
| --- | --- | --- |
| `api` | 2 | approvals are in Postgres; the audit ring is per-pod but the durable record is the stream |
| `tools` | 2 | stateless — it verifies, asks OPA, and calls a backend |
| `agent` | 2 | run checkpoints are in Postgres; a resume on a fresh pod rebuilds from the checkpoint (see [`data-stores.md`](data-stores.md)) |
| `gateway` | 2 | the rate/cost counters are in Postgres ([`llm-gateway.md`](llm-gateway.md)) |
| `opa` | 2 | stateless — it loads the bundle |

Each has **soft pod anti-affinity** (replicas spread across nodes when there is
more than one) and a **PodDisruptionBudget** (`minAvailable: 1`), so a node drain
or an upgrade cannot take a whole service down.

## Not replicated (and why)

| Component | Why not | What production does |
| --- | --- | --- |
| `spire-server` | Its state survives the pod (S1: the registry is in Postgres and the keys are on a PVC), so a restart keeps the same CA and entries. HA also needs a **shared KeyManager**, and the default disk one is single-replica by nature — two replicas would each mint their own CA. | Shared datastore + a KMS KeyManager, 2+ replicas — supported here, see below |
| `keycloak` | 2 replicas behind the Service against Postgres (S2), sessions shared through the `ispn` cache discovering peers via the database. HA is otherwise taken care of; a genuine multi-site setup would add an external Infinispan. | 2+ replicas + a managed database (what the demo now does, minus the database being managed) |
| `postgres` | Its data is on a `PersistentVolumeClaim` now (S3), so it survives a pod restart and is not lost with the process — but it is still one replica, and running HA Postgres well (failover, backups) is its own discipline. | A managed HA database with backups; the chart takes the DSN (`database.url`) |
| `sandbox` | It holds the synthetic data, which now survives a restart on its own volume (S9) — but it is still a single writer, so replicas would disagree. | A real backend (the tools' HTTP backend already targets one) |
| observability | Jaeger/Prometheus/Grafana are demo-scale. | Managed backends |

## The identity tier: a shared KeyManager (S1's other half)

Identity is the critical path — nothing gets an SVID without it — so a single
SPIRE server is the sharpest single point of failure in the platform. Both halves
of HA are now supported:

| Half | State |
| --- | --- |
| **Shared datastore** | Done and default: the registry is in Postgres, so a replacement replica reads the same entries. |
| **Shared KeyManager** | Switchable: `SPIRE_KEY_MANAGER=aws_kms` in `.env` (default `disk`). |

```bash
# .env — the demo stays unattended without this; KMS mode is opt-in.
SPIRE_KEY_MANAGER=aws_kms
SPIRE_KMS_REGION=eu-west-1
SPIRE_KMS_SERVER_ID=acme-com          # shared by every replica — see below
SPIRE_KMS_PRINCIPAL_ARN=arn:aws:iam::123456789012:user/spire-kms
AWS_ACCESS_KEY_ID=...                 # or AWS_SESSION_TOKEN too, for temporary creds
AWS_SECRET_ACCESS_KEY=...
```

Then `./scripts/setup.sh` scales the server to 2 replicas and **gates on both
replicas presenting the same CA** — that is the whole point of the switch, and it
is asserted rather than assumed (a fleet silently alternating between two trust
bundles is worse than one server).

**The setting that decides whether HA works is `SPIRE_KMS_SERVER_ID`.** The plugin's
default identifier is a *file* per server, which each replica would create for
itself: one identifier each, therefore one key each, therefore a different CA each.
Every replica must share that value — and it cannot contain dots, so the trust
domain's own name has to be written as `acme-com`.

**What AWS needs.** The plugin *creates and rotates its own keys* (there is no
key to pre-create), so the principal named in `SPIRE_KMS_PRINCIPAL_ARN` needs:

| Permission | Why |
| --- | --- |
| `kms:CreateKey`, `kms:CreateAlias`, `kms:UpdateAlias`, `kms:DeleteAlias`, `kms:ListAliases` | the plugin manages a key per server instance and an alias to find it |
| `kms:DescribeKey`, `kms:GetPublicKey`, `kms:Sign` | signing SVIDs — the CA private key never leaves KMS |
| `kms:ScheduleKeyDeletion` | pruning keys whose liveness signal has gone stale (two weeks) |
| `tag:GetResources` | tag-based key discovery (`enable_tag_based_key_discovery`) |

Two consequences worth deciding before you turn it on: the policy can **create and
schedule deletion of KMS keys**, so scope it to a dedicated principal (never a
personal one); and the plugin's default key policy assumes SPIRE *assumes a role*,
which static credentials do not — `setup.sh` therefore writes an explicit key policy
naming `SPIRE_KMS_PRINCIPAL_ARN`. On kind, credentials arrive as a Kubernetes
Secret; in production, use workload identity (IRSA/EKS Pod Identity, GKE, Azure)
and no key material at all.

**Cost and latency:** every CA signature becomes a KMS API call, and each SVID
issuance needs one. Fine at demo scale; at production volume it is a real line item
and worth measuring before you commit to it.

## Multi-node: the SPIRE registration fix

With more than one node, each runs its own SPIRE agent, and a workload is
attested by the agent **on its own node**. A registration entry parented to a
single agent leaves pods on every other node with:

```
no identity issued (StatusCode.PERMISSION_DENIED)
```

So `scripts/setup.sh` registers **one entry per attested agent** (the same
identity, one parent each). That is what makes the replicated workloads actually
work across nodes.

## Verify

The kind cluster is one control-plane and **two workers** (`deploy/kind/cluster.yaml`),
so replicas genuinely spread:

```bash
./scripts/ha-check.sh
```

It prints the pods per node, the PodDisruptionBudgets, then evicts one replica
and confirms the service keeps answering:

```
tools            agent-platform-worker    Running
tools            agent-platform-worker2   Running
...
tools  1  N/A  1   # minAvailable 1, one disruption allowed
The tools service stayed up throughout.
```

## Next steps

- **Autoscaling** — the services are stateless; an HPA on CPU (and on the
  gateway's request rate) is the natural addition.
- **Multi-zone** — anti-affinity by `topology.kubernetes.io/zone` instead of
  hostname.
- **Managed Postgres with failover** — the one piece that most changes the
  durability story.
