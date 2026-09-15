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

## Refusals before the tool server

The agent is only offered the tools your role may call (`allowed_tools()` from the
same policy), so a request that needs a tool you cannot have is refused *before*
the tool server ever sees it — no `tool.denied` is emitted, because nothing was
attempted. Two things now cover that:

- the run reports `status: "refused"`, distinct from `error` (something broken);
- the agent records an `agent.refused` event with the user, the tenant, and the
  reason — **not** the task text, which is free-form and may itself contain the
  personal data this view exists to protect.

When the model names a tool it may not call — it is told which tools are *not*
permitted, precisely so it does not silently substitute another — the record names
it, and the refusal appears here as a row: *alice · refused · privacy.pii.read*.
`decide_tool` refuses that outright rather than letting the model pick something
else instead (`app/agent/llm.py`).

**The honest limit:** a small model often just *declines* instead of naming the
tool it wanted. When that happens the refusal is still recorded and still shows in
the generic **Audit** tab, but it cannot be attributed to `privacy.pii.read`, so it
does not appear in this view. Attribution depends on the model naming a tool, which
is why it is recorded as a separate event rather than guessed at from the task
text.

## Trying it

In the UI, as `priya` (privacy): *"Read the personal data (name, email, phone) of
customer c-100"* — it is held for approval. Sign in as `manager`, approve it in
**Approvals**, then re-run as `priya`. The **Privacy** tab shows the held attempt,
the approval, and the completed read.
