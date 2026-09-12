# Glossary

Plain-language definitions. If a term is used anywhere in this project and is not
here, that is a documentation bug.

**Agent** — software that can *do things* (read data, issue a refund) on a
user's behalf, typically powered by a language model. In this project it is a
workload with its own cryptographic identity.

**NHI (Non-Human Identity)** — any identity that is not a person: a service, a
workload, a bot, or an agent. They vastly outnumber humans in most companies.

**Workload identity** — an identity bound to a running piece of software,
verified by the platform it runs on rather than by a secret it carries.

**SPIFFE** — the open standard for workload identity. Defines what an identity
looks like (a URI such as `spiffe://acme.com/ns/agent-nhi/sa/agent`) and how it
is proven. Think of it as the passport *standard*.

**SVID** — the signed identity document SPIRE issues. Think of it as the passport
itself; it expires in minutes.

**SPIRE** — the software that implements SPIFFE (the "passport office"). A server
issues identities; a per-node agent attests workloads and hands them out.

**Attestation** — proving what a workload is before giving it an identity.
Kubernetes testifies: "this is the agent, in the right namespace, with the right
service account."

**Token exchange (RFC 8693)** — trading one token for another with a narrower
scope and a specific audience, while preserving *who is acting through whom*.

**Audience (`aud`)** — which service a token is meant for. Enforcing it is what
makes forwarding a token fail.

**Actor (`azp` / `act`)** — the workload that performed an exchange. This is how
the system records "this agent is acting", not just "someone is acting".

**`jti`** — a unique ID on a token, used to prevent replay. Required by Keycloak
on client credentials.

**OPA / Rego** — the policy engine and the language its rules are written in.
Rules are code: versioned, reviewed, tested.

**Deny by default** — if no rule explicitly permits an action, it is refused.

**PEP / PDP** — Policy *Enforcement* Point (where a request is checked — the MCP
tool server) vs Policy *Decision* Point (where the answer comes from — OPA).

**MCP (Model Context Protocol)** — the standard way agents discover and call
tools.

**Token forwarding** — passing a received token along to another service. An
anti-pattern that turns one stolen token into a chain of compromises.

**Human-in-the-loop (approval)** — a high-risk action pauses until an
authenticated person approves it; the decision is recorded.

**Prompt injection** — tricking a model into attempting something harmful via
crafted input. This design assumes it will happen and makes the attempt
powerless.

**LLM gateway** — a component inside the trust domain that holds the model
provider's key and authenticates callers by identity, so agents hold no secrets.

**Synthetic data** — generated data that looks realistic in shape but describes
no real person, card, or account.
