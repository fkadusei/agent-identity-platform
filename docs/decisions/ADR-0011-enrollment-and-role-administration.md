# ADR-0011: Self-service enrollment and role administration

- **Status:** Accepted
- **Date:** 2026-09-12
- **Related:** ADR-0002 (Keycloak token exchange), ADR-0003 (OPA policy), ADR-0007 (security baseline), ADR-0010 (supply chain)

## Context

Roles only mean something if there is a way to grant them. Until now the demo
users were hardcoded in the realm template, the UI gated features on a
**username** (`user === "manager"`), and there was no way to onboard anyone. The
`manager` role was carried in tokens but never actually required anywhere — so
"manager" was a persona, not an authorization decision.

We need people to be able to get accounts and admins to grant access, without
(a) letting a user self-escalate, (b) putting a bootstrap admin password in the
app, or (c) trusting the UI to enforce anything.

## Decision

**Add self-service enrollment (toggleable) and admin role management, backed by
Keycloak's Admin API through a least-privilege service account, with all
authorization enforced server-side.**

- **Enrollment.** `POST /enroll` creates an account with **no roles**. Roles are
  never read from the request, so a signup cannot self-escalate. A
  `SIGNUP_ENABLED` toggle lets an operator make enrollment admin-only.
- **Real login.** `POST /auth/login` does a username/password grant against a
  `portal` client; its tokens carry `aud=agent` and `aud=mcp-tools` so one
  session can both run tasks and approve. (The browser uses authorization-code +
  PKCE in a real deployment; the server-side grant keeps the demo self-contained.)
- **Administration.** A new `platform_admin` role gates `GET/POST/DELETE
  /admin/users…`. The API calls Keycloak's Admin API with a dedicated
  `platform-admin` **service account** holding only `manage-users` + read-roles —
  never the bootstrap admin credential. Its secret comes from a Secret.
- **Server-side role checks.** A `require_roles(...)` dependency is the control;
  the UI hiding a button is convenience only. This closes the earlier gap: the
  approval decision now requires the `manager` (or `platform_admin`) role, in
  addition to the existing no-self-approval rule.
- **Audit.** `user.enrolled`, `auth.login`, `user.role_granted`, `user.deleted`,
  … are all written to the audit stream.

## Consequences

- Roles are now enforced where they matter (server), and the role set is closed:
  only `support_rep`, `manager`, `privacy`, `platform_admin` may be granted.
- The platform holds one new privileged credential — the admin service account
  secret — but it is scoped to user administration and stored as a Secret, not
  in code. A real deployment rotates it (see docs/secrets.md).
- Enrollment is a public endpoint when enabled; production should add email
  verification, rate limiting, and CAPTCHA.
- The UI now needs the caller's roles; it reads them from the login response.

## Alternatives considered

- **Keep users in the realm file.** Rejected: no onboarding path, and it made
  roles a documentation exercise rather than an enforced control.
- **Use the bootstrap admin credential in the app.** Rejected: a full-power,
  long-lived secret in the request path.
- **Enforce roles in the UI only.** Rejected: the UI is not a trust boundary.
- **A separate identity provider (SCIM/IdP federation).** The right answer at
  scale; out of scope for the reference platform, and the API surface here
  (enroll + role mapping) maps onto it cleanly.
