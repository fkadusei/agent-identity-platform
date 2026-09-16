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
| `spire-server` | Its state survives the pod now (S1: the registry is in Postgres and the keys are on a PVC), so a restart keeps the same CA and entries. HA still needs a **shared KeyManager** as well as a shared datastore, and that means a cloud KMS; the demo keeps the disk KeyManager, which is single-replica by nature. | Shared datastore + AWS/GCP/Azure KMS, 2+ replicas |
| `keycloak` | HA needs an external database **and** clustering (cache discovery). The demo uses `start-dev` with in-memory H2. | External DB + `start` + 2+ replicas behind the Service |
| `postgres` | Its data is on a `PersistentVolumeClaim` now (S3), so it survives a pod restart and is not lost with the process — but it is still one replica, and running HA Postgres well (failover, backups) is its own discipline. | A managed HA database with backups; the chart takes the DSN (`database.url`) |
| `sandbox` | It holds the synthetic data **in memory**, so replicas would disagree. | A real backend (the tools' HTTP backend already targets one) |
| observability | Jaeger/Prometheus/Grafana are demo-scale. | Managed backends |

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
