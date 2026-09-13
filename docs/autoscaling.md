# Autoscaling

The app tier scales horizontally without a redeploy. This builds directly on
[`ha.md`](ha.md): a component can be replicated only if its state lives
elsewhere — the same property that makes it safe to run two replicas makes it
safe to run five.

## What scales

| Service | Min | Max | Signal |
| --- | --- | --- | --- |
| `api`, `tools`, `agent`, `gateway`, `opa` | 2 | 5 | CPU utilization, target 70% |

The floor is **2** — matching the HA replicas, so autoscaling never takes you
below the redundancy you asked for. Scale-down has a 120s stabilization window so
a short burst does not immediately drop capacity.

```bash
kubectl -n agent-platform get hpa
```

```
NAME      REFERENCE            TARGETS        MINPODS   MAXPODS   REPLICAS
api       Deployment/api       cpu: 23%/70%   2         5         2
gateway   Deployment/gateway   cpu: 20%/70%   2         5         2
```

## Two things that have to be true

Both were bugs before they were documentation:

1. **Pods need CPU requests.** A utilization target is a percentage *of the
   request*; without one the HPA reports `<unknown>` and never scales. Every
   service declares requests and limits.
2. **The mesh sidecar needs requests too.** Linkerd's proxy runs *in* the pod, so
   the HPA counts it — without a request on `linkerd-proxy` it fails with
   `missing request for cpu in container linkerd-proxy`. The manifests set
   `config.linkerd.io/proxy-cpu-request` / `-memory-request`.

## Next: scale on the signal that matters

CPU is a proxy. The platform already exports the metrics that describe the real
load — `agent_platform_approvals_pending` (a queue depth) and
`agent_platform_http_requests_total` (request rate). Scaling the **api** on the
approval backlog, or the **gateway** on request rate, needs a Prometheus Adapter
exposing those via `custom.metrics.k8s.io`, then an HPA of type `Pods`/`Object`.
That is the natural next step; the metrics are already there.

## Setup

`scripts/setup.sh` installs metrics-server and applies the HPAs. In Helm, set
`autoscaling.enabled=true` and `services.<name>.autoscale` (the kind manifests
are the reference). metrics-server is not installed by the chart — it is a
cluster add-on.
