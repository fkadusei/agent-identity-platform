# Revoking a workload identity

An SVID is a **bearer credential with no CRL or OCSP** — you cannot un-issue one.
So "revoke a workload" means two things: **stop issuing** new credentials, and
**refuse the ones already issued** at every hop we own — immediately, without
waiting for the credential to expire (S23).

## The levers, and what each buys

| Lever | Stops | Latency |
| --- | --- | --- |
| **Admission denylist** (the api) | a revoked SPIFFE ID at every hop we own | seconds (a short cache) |
| **SPIRE registration entry** (`spire-server entry delete`) | issuing *new* SVIDs | immediate for new SVIDs |
| **Keycloak client** (the client whose `clientId` is the SPIFFE ID) | token exchange | immediate |
| **The workload's pods** | presenting the held SVID | immediate |
| The held credential itself | nothing — it lives until it expires | JWT 5 m, X.509 1 h |

The denylist is what makes the refusal *immediate* at our hops. The TTL bounds
what is left: a copied SVID key still works somewhere we do not control until it
expires, which is why "stop issuing" alone is not the claim.

## The admission denylist

The api is the authority. It stores the revoked SPIFFE IDs (in Postgres when a
database is configured, so it survives a restart and every replica agrees) and
serves them to the services that enforce admission:

- `GET /workloads/revoked` — the set, read by our services over a hop we own.
- `POST /admin/workloads/revoke` and `/admin/workloads/restore` — platform_admin,
  audited as `workload.revoked` / `workload.restored`.

Every hop we own checks it **at admission** (`app/common/workload.py`, the
gateway's `caller_id`): a revoked identity is refused before its SVID would have
expired. Services fetch the set from the api and cache it for a few seconds
(`app/common/revocation.py`), so staleness is seconds, not minutes-to-an-hour.

```bash
# revoke, one command
./scripts/revoke-workload.sh spiffe://acme.com/ns/agent-platform/sa/agent --reason "gone rogue"

# prove it (non-destructive: denylist only, then restore)
./scripts/revocation-tests.sh

# undo the denylist entry
./scripts/revoke-workload.sh spiffe://acme.com/ns/agent-platform/sa/agent --restore
```

## The runbook

`scripts/revoke-workload.sh` does all four, in order of immediacy:

1. **api denylist** — refused at admission, now.
2. **SPIRE entry** — deleted, so no new SVIDs.
3. **Keycloak client** — disabled, so no new token exchanges.
4. **pods** — deleted, so the held SVID stops being presented.

```bash
# what it does under the hood, if you prefer to run it by hand:
SPIRE="kubectl -n agent-platform exec spire-server-0 -- /opt/spire/bin/spire-server"
SOCKET=/run/spire/server/private/api.sock
$SPIRE entry show  -socketPath $SOCKET -spiffeID <spiffe-id>
$SPIRE entry delete -socketPath $SOCKET -entryID <entry-id>
kubectl -n agent-platform delete pod -l app=<workload>
```

**Restore** removes the denylist entry only. Re-run `./scripts/setup.sh` to
re-register the SPIRE entry and re-enable the Keycloak client — deregistration is
still not automated, which is the remaining gap (see below).

## Decommissioning a retired workload (S26)

Revoking cuts a workload off; **decommissioning** removes the registrations it leaves
behind. `scripts/decommission-workload.sh` deletes the SPIRE entry and the Keycloak
client, and clears any denylist entry:

```bash
./scripts/decommission-workload.sh spiffe://acme.com/ns/agent-platform/sa/agent
./scripts/reaping-tests.sh      # prove both registries are reaped
```

It does **not** touch the static references — `ALLOWED_WORKLOADS` and the policy's
`is_trusted` — because those are code/config; it prints them for a human to edit.
Making the whole registration declarative and reviewed (Q11's four registries) is the
larger piece still open.

The Keycloak step uses the `platform-admin` service account, which holds
`manage-clients` (added in S26) as well as `manage-users`. Because the realm is
imported with `--override=false`, a *fresh* cluster gets the permission; an existing
one does not until the realm (or the `keycloak` database) is reset and re-imported —
the same durability rule that governs rotating a client secret.

## The honest limits

- **No un-issue.** A copied SVID key works until it expires. Revocation is
  *stop issuing + refuse at admission*, not "instantly dead everywhere".
- **The gateway name-checks now**, but a denylist fetch that fails keeps the last
  known set (and, with no set ever fetched, refuses nothing) — the denylist is
  defence in depth, not the only control.
- **Reaping is manual.** Deleting a workload does not remove its SPIRE entry or
  its Keycloak client; `setup.sh` re-creates them. Automating that is the
  deregistration half of the lifecycle gap (Q20).
