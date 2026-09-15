# Personal-data access

Reading personal data is the one action here that is as sensitive as a change, so
it gets its own view rather than a row in the generic approval queue.

## The flow

Reading PII needs **two** things, and they are separate controls:

1. the `privacy` role — `policy/authz.rego` allows `privacy.pii.read` only for a
   caller whose token carries it;
2. **manager approval** — `require_approval` fires for every PII read, whatever
   the role, so `priya` cannot quietly read a customer's phone number.

So a single read produces two records about the same act: an approval, and a tool
decision. The **Privacy** tab (manager only) shows both.

## What the view shows

- **Access attempts** — every `privacy.pii.read` decision the tool server made,
  as `held for approval` / `allowed` / `denied`, with the user, the policy reason,
  the bundle revision that decided it, and the time.
- **Approvals** — each PII approval with the customer asked about, who asked, why,
  who decided, and any note.

It is scoped to your tenant, like everything else.

## Where the trail lives

`app/audit/store.py`, with the same two-backend shape as the approvals:
in-memory when no database is configured (so `./start.sh` needs no database), and
a Postgres `audit_events` table when one is. This replaced an in-memory deque in
the API process, which had made the view wrong rather than merely incomplete: with
two API replicas each pod held a *different* subset of the events (measured: 8 and
7), and a rollout cleared it. Now every replica gives the same answer and the
trail survives a restart — verified on kind by posting events, restarting the API,
and reading them back from both pods.

## One limit, stated plainly

**A refusal can happen before the tool server.** The agent is only offered the
tools your role may call (`allowed_tools()` from the same policy), so when `alice`
(a support rep) asks for PII, the model is never given `privacy.pii.read` at all
and the tool server never emits `tool.denied`. The agent refuses it instead, and
today that refusal is neither audited nor labelled as a refusal — the run comes
back as `status: "error"` with *"no tool your role may call fits this task"*. So
"who tried to look at PII and was turned away" is missing from the trail, which is
the most interesting row a privacy view could have. Fixing it means auditing the
agent-side refusal (with the user and tenant, and without storing the raw task
text, which may itself contain personal data) and giving the run a `refused`
status instead of `error`.

## Trying it

In the UI, as `priya` (privacy): *"Read the personal data (name, email, phone) of
customer c-100"* — it is held for approval. Sign in as `manager`, approve it in
**Approvals**, then re-run as `priya`. The **Privacy** tab shows the held attempt,
the approval, and the completed read.
