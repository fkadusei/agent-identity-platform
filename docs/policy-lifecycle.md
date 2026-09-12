# Policy lifecycle

Policy is code, and code has a lifecycle: build a versioned artifact, roll it
out, and be able to answer *which revision made this decision*. This document
covers the bundle, how a decision carries its revision, and how to roll out a
change.

## The bundle

`policy/authz.rego` is the single source of truth (the file CI tests). The
deployable artifact is a **bundle** built from it:

```bash
./scripts/build-bundle.sh            # revision = git short SHA
POLICY_REVISION=v42 ./scripts/build-bundle.sh   # or an explicit revision
```

It produces:

```
dist/bundle/
  authz.rego        the policy
  data.json         {"agentnhi": {"policy_version": "<revision>"}}
  .manifest         {"revision": "<revision>", "roots": ["agentnhi"]}
dist/bundle.tar.gz  the distributable artifact (what you sign and publish)
```

`setup.sh` builds the bundle, mounts it into OPA from the `opa-bundle`
ConfigMap, and OPA loads it with `--bundle`. (The files are mounted
individually — a whole-ConfigMap mount adds Kubernetes' `..data` timestamp
directory, which OPA's bundle loader would try to read as bundle data.)

## Which revision decided this?

The revision is stamped into the policy as `data.agentnhi.policy_version` and
returned with every decision. It appears in four places:

| Where | Example |
| --- | --- |
| The decision itself | `{"decision": "require_approval", "policy_version": "876731b", …}` |
| The audit event | `tool.allowed … policy_version=876731b` |
| The trace span | `policy.decision … policy_version=876731b` |
| OPA decision logs | structured JSON on the OPA pod's stdout |

So any decision — in the audit timeline, in a trace, or in OPA's logs — names the
policy revision that produced it. `data.agentnhi.policy_version` falls back to
`"dev"` when the raw file is run directly (`opa test policy/`).

## Rolling out a change

The bundle is what makes rollout a deployment problem rather than a code edit:

1. **Change and test.** Edit `policy/authz.rego`; `opa test policy/` must pass
   (CI runs this).
2. **Build a revision.** `POLICY_REVISION=<new> ./scripts/build-bundle.sh`.
3. **Stage it.** Point a canary OPA at the new bundle (or run it in shadow mode
   and compare decisions against the live one) before promoting.
4. **Promote.** `./scripts/setup.sh` re-creates the `opa-bundle` ConfigMap and
   restarts OPA. Every decision from then on reports the new revision.
5. **Roll back** by re-applying the previous revision's ConfigMap — the revision
   in the audit trail tells you exactly what you rolled back from.

A real deployment serves the bundle from a registry (OCI artifact) with OPA's
bundle API and signing. Signing the bundle is the supply-chain step (ADR-0010).

## Decision logs

OPA is started with `--set=decision_logs.console=true`, so every decision is
emitted as a structured JSON line to the OPA pod's stdout:

```bash
kubectl -n agent-platform logs deploy/opa | python3 -c '
import sys, json
for line in sys.stdin:
    if line.startswith("{"):
        d = json.loads(line)
        if "decision_id" in d:
            print(d["result"].get("decision"), d["result"].get("policy_version"), d["input"].get("tool"))
'
```

In production these ship to the same pipeline as the audit stream (see
[`observability.md`](observability.md)) so policy decisions and application
events land together, both tagged with the revision.
