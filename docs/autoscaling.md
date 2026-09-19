# Autoscaling

The app tier scales horizontally without a redeploy. This builds directly on
[`ha.md`](ha.md): a component can be replicated only if its state lives
elsewhere — the same property that makes it safe to run two replicas makes it
safe to run five.

## What scales

| Service | Min | Max | Signal |
| --- | --- | --- | --- |
| `api` | 2 | 5 | the approval backlog (`External`, target 5) · requests/second per pod (`Pods`, target 20) · CPU 70% |
| `tools`, `agent`, `gateway`, `opa` | 2 | 5 | CPU utilization, target 70% |

The floor is **2** — matching the HA replicas, so autoscaling never takes you
below the redundancy you asked for. Scale-down has a 120s stabilization window so
a short burst does not immediately drop capacity. An HPA takes the **largest** of
its metrics, so CPU stays the fallback.

```bash
kubectl -n agent-platform get hpa
kubectl -n agent-platform describe hpa api
```

```
NAME   REFERENCE          TARGETS                                     MINPODS   MAXPODS   REPLICAS
api    Deployment/api     cpu: 5%/70%, 0/5 + 1 more...                2         5         2

Metrics:                                               ( current / target )
  resource cpu on pods  (as a percentage of request):  5% (4m) / 70%
  "approvals_pending" (target value):                  0 / 5
  "http_requests_per_second" on pods:                  171m / 20
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

## Scaling on the signal that matters

CPU is a proxy. The platform exports the real signals, so a **Prometheus
adapter** exposes them to the HPA as Kubernetes metrics — one component, two
aggregated APIs:

| Metric | API | Type | What it is |
| --- | --- | --- | --- |
| `approvals_pending` | `external.metrics.k8s.io` | `External` | the approval queue depth — a property of the platform, not of one pod |
| `http_requests_per_second` | `custom.metrics.k8s.io` | `Pods` | the api's request counter, turned into a per-pod rate |

Nothing new is instrumented to autoscale: both come from the counters the api
already serves at `/metrics`, and the adapter's rules do the translation
(`deploy/kind/manifests/autoscaling/prometheus-adapter.yaml`).

One arithmetic worth knowing, because it surprises people: an `External` metric
target is not "replicas = queue / target". It is
`desired = ceil(currentReplicas × value / target)` — the value is compared
against the capacity that already exists. A backlog of 7 against a target of 5
therefore goes 2 → 3 → 5 over successive syncs rather than jumping to a number
derived from the queue alone.

### Two things that had to be fixed first

Both were found by watching it fail on the cluster, and both would have made the
numbers look plausible while being wrong.

**Prometheus scraped the api's Service, not its pods.** The counters are
per-process: a Service that round-robins scrapes between replicas makes them jump
backwards, and `rate()` over a counter that resets is noise. It also yields no
`pod` label, which is exactly what a `Pods` metric needs. Prometheus now uses pod
service discovery and scrapes each replica (`deploy/kind/manifests/observability/`).

**The backlog gauge was per replica *and* per tenant.** It was written whenever an
approval changed — on the replica that handled the change, for that tenant's
count. With two replicas that means one gauge moves and the other keeps a stale
number, so `max()` across them reports the stale one: the queue was drained and
the api **stayed at five replicas**, indefinitely. The count is now read from the
store at scrape time (`store.pending_count()`), across every tenant, so every
replica reports the same number and `/metrics` cannot serve a value that no
longer exists.

### The trade-off, named

An HPA whose metric cannot be read records the failure and does **not** scale on
any of its metrics until it can. Adding a custom metric therefore adds a
dependency to scaling: if prometheus-adapter or Prometheus is down, the api stops
scaling on CPU too. That is the price of scaling on something more meaningful
than CPU, and it is why the metric is additive rather than a replacement.

The gateway is deliberately not in this table beyond CPU: it serves **only** mTLS
with an SVID, so Prometheus — which holds no SVID — cannot scrape it. Feeding a
gateway metric into an autoscaler would mean either a new listener for it to be
scraped on, or deriving the signal from the audit stream it already sends to the
api ([`backlog.md`](backlog.md)).

## Verify it

```bash
# the metric APIs answer (a value of 0 is still an answer)
kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1/namespaces/agent-platform/approvals_pending"
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/agent-platform/pods/%2A/http_requests_per_second"

# drive it: hold approvals, then decide them
kubectl -n agent-platform get hpa api -w
```

Observed on kind (a $200 refund needs approval; seven of them hold the queue):

```
seed the backlog      backlog=7   api replicas=2 → 3 → 5
drain it              backlog=0   api replicas=5 → 2   (~120s stabilization)
```

## Setup

`scripts/setup.sh` installs metrics-server **and** prometheus-adapter, giving each
a serving certificate it generates and pinning that CA into the APIService
(`insecureSkipTLSVerify: false` — never skip verification), then applies the HPAs
and gates on the external metric answering. In Helm, set `autoscaling.enabled=true`
plus `autoscaling.extraMetrics` (the kind manifests are the reference). Both
add-ons are cluster-level and are **not** installed by the chart.
