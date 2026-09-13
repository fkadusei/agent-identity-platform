# CI/CD

Three workflows, in order: **CI** checks every change, **release** builds and
signs the artifacts, and **deploy** puts them on a cluster — but only after a
human approves. The last part is deliberate: the platform's whole point is that
high-risk actions need a human decision, and shipping to production is one.

```
push / PR ──▶ ci.yml        tests, SAST, secret scan, chart lint, web build
tag v*    ──▶ release.yml   build + push + keyless-sign images, bundle, chart
manual    ──▶ deploy.yml    ⏸ approval gate ▶ verify signatures ▶ helm upgrade ▶ smoke test
```

## 1. CI (`ci.yml`, `security.yml`)

Runs on every push and PR. Nothing here is deploy-specific; see the badges and
`security.yml` for the security jobs. The chart is linted and rendered too, so a
broken template cannot merge.

## 2. Release (`release.yml`)

On a `v*` tag, it builds the four images, pushes them to GHCR, and signs them
**keyless** (ADR-0010) — no signing key exists. It signs the policy bundle and
publishes the Helm chart as an OCI artifact:

```bash
helm push dist/agent-platform-<version>.tgz oci://ghcr.io/<owner>/charts
```

## 3. Deploy with an approval gate (`deploy.yml`)

Triggered manually (`workflow_dispatch`) with an environment and an image tag.

### The gate

The deploy job targets a **GitHub Environment**. When that environment has
*Required reviewers*, GitHub pauses the run and waits for a human to approve
before any cluster is touched. That is the entire gate — no extra action, no
custom approval service.

```
Settings → Environments → production
  ✔ Required reviewers        ← the approval gate
  Secret KUBECONFIG (base64)  ← access to that cluster
```

Mirroring the platform: an agent action that policy marks `require_approval`
stops until a manager decides. A deploy that the environment marks as gated stops
until a reviewer decides. Same shape, different layer.

### What the deploy does

1. **Verify signatures** — `cosign verify` each image against the release
   workflow's identity. An unsigned or wrongly-signed image is never deployed.
2. **Configure access** — decode the environment's `KUBECONFIG` secret.
3. **Build and apply the policy bundle** — the same `scripts/build-bundle.sh`
   artifact the CI tests, so the deployed policy is the reviewed one.
4. **`helm upgrade --install --atomic --wait`** — `--atomic` rolls the release
   back automatically if it fails or times out.
5. **Post-deploy smoke test** — `rollout status`, `/healthz`, and the **attack
   suite**: a deploy that reintroduces an attack is a failed deploy.
6. **Roll back** if the smoke test fails (`helm rollback`).

### Concurrency

Deploys to the same environment are serialized (`concurrency: deploy-<env>`), so
two approvals cannot race.

## One-time setup

1. Create the environment(s) with **Required reviewers** and a `KUBECONFIG`
   secret (base64 of the kubeconfig).
2. Ensure the target cluster has a SPIRE agent and Keycloak reachable (see
   [`../deploy/helm/agent-platform/README.md`](../deploy/helm/agent-platform/README.md)).
3. Tag a release (`git tag v0.1.0 && git push --tags`) to produce signed images.

## Rolling back

- A failed `helm upgrade` → automatic (`--atomic`).
- A failed smoke test → automatic (the rollback step).
- A bad release discovered later → `helm -n agent-platform rollback agent-platform`,
  or re-run the deploy with the previous `image_tag`. The policy bundle revision
  in every decision tells you which policy you rolled back from.
