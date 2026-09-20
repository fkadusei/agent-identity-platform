#!/bin/bash
# =============================================================================
# setup-aws-kms-role.sh — the one-time AWS side of the KMS KeyManager (S1).
#
# Creates the two principals docs/ha.md describes, so the long-lived credential
# that ends up in `.env` can do nothing but assume one role:
#
#   spire-kms-base   an IAM user whose ONLY permission is sts:AssumeRole
#   spire-kms        the role that holds the KMS permissions and signs the CA
#
# The plugin creates and rotates its own KMS keys, so no key is pre-created here;
# `setup.sh` writes the key policy naming the role.
#
# Properties worth knowing before you run it:
#   * idempotent — re-run it to repair a half-finished setup or change the region;
#   * it touches nothing outside those three names (policy, role, user + one key);
#   * it writes the settings into the gitignored `.env`, so nothing is copied by
#     hand — a secret pasted from a console is a secret in a scrollback buffer;
#   * it never creates or uses root *access keys*; SPIRE later uses only the
#     narrowly-scoped user's key;
#   * the first call SPIRE makes with that credential is sts:AssumeRole, and this
#     script makes the same call as a self-test before you deploy anything.
#
# Usage:
#   ./scripts/setup-aws-kms-role.sh --region eu-west-1 [--external-id] [--dry-run]
#
#   --region       where the CA keys will live (KMS is regional). Defaults to your
#                  CLI's configured region.
#   --external-id  generate an sts:ExternalId and require it in the trust policy.
#                  Extra defense; needs no other change (it is written to .env too).
#   --dry-run      print what would happen; change nothing, write nothing.
#
# Then:  ./scripts/setup.sh        # switches SPIRE to KMS, 2 replicas, same-CA gate
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

REGION=""
EXTERNAL_ID=""
DRY_RUN=""
ACCOUNT_ARG=""
# Set only when the identity check was skipped (--account with --dry-run). Declared
# here because `set -u` does not care that the flag is only read on one path — which
# is exactly how this landed in the authenticated path as an unbound variable.
UNAUTHENTICATED=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --region) REGION="${2:-}"; shift 2 ;;
    --external-id) EXTERNAL_ID="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --account) ACCOUNT_ARG="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,34p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1 (try --help)" >&2; exit 2 ;;
  esac
done

say()  { printf '\n\033[1;34m== %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m   ✓ %s\033[0m\n' "$*"; }
info() { printf '\033[2m   · %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m   ✗ %s\033[0m\n' "$*" >&2; exit 1; }

# In a dry run, mutating commands are printed instead of executed. Reads still run,
# so the plan is based on what is really there.
#
# The "would run" line goes to stderr on purpose: callers redirect these commands'
# stdout (`>/dev/null`) to keep normal runs quiet, and a plan that disappears into a
# redirect is worse than no plan at all.
run() {
  if [ -n "$DRY_RUN" ]; then
    printf '   would run: %s\n' "$*" >&2
    return 0
  fi
  "$@"
}

command -v aws >/dev/null 2>&1 || die "the aws CLI is not on PATH"
command -v python3 >/dev/null 2>&1 || die "python3 is not on PATH"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Who is running this. A browser console sign-in is not a CLI credential, and an
# expired one is the most common reason this fails — so show AWS's own words rather
# than replacing them with a guess.
IDENTITY=""
CALLER=""
if IDENTITY="$(aws sts get-caller-identity --output json 2>"$TMP/identity.err")"; then
  ACCOUNT="$(printf '%s' "$IDENTITY" | python3 -c 'import json,sys; print(json.load(sys.stdin)["Account"])')"
  CALLER="$(printf '%s' "$IDENTITY" | python3 -c 'import json,sys; print(json.load(sys.stdin)["Arn"])')"
elif [ -n "$ACCOUNT_ARG" ] && [ -n "$DRY_RUN" ]; then
  case "$ACCOUNT_ARG" in
    [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;;
    *) die "--account wants the 12-digit account id, got '$ACCOUNT_ARG'" ;;
  esac
  ACCOUNT="$ACCOUNT_ARG"
  CALLER="(not authenticated)"
  UNAUTHENTICATED=1
else
  printf '\033[1;31m   ✗ the aws CLI has no usable credentials.\033[0m\n' >&2
  printf '\033[2m     AWS says: %s\033[0m\n' "$(tr -d '\n' < "$TMP/identity.err")" >&2
  cat >&2 <<'HELP'

     A sign-in in the browser console is not a CLI credential. Pick one:

       aws login                 # if this CLI is set up for sign-in sessions
       aws configure             # paste an access key for an administrator
       export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... [AWS_SESSION_TOKEN=...]

     Root is not required: this script needs only IAM write (CreatePolicy,
     CreatePolicyVersion, CreateRole, AttachRolePolicy, PutUserPolicy, CreateUser,
     ListAccessKeys, CreateAccessKey).

     To see the whole plan without any credentials:
       ./scripts/setup-aws-kms-role.sh --account <12-digit-id> --dry-run
HELP
  exit 1
fi

if [ -z "$REGION" ]; then
  REGION="$(aws configure get region 2>/dev/null || true)"
fi
[ -n "$REGION" ] || die "no region given and none configured — use --region <e.g. eu-west-1>"
case "$REGION" in
  [a-z][a-z]-[a-z]*-[0-9]*) ;;
  *) die "'$REGION' does not look like an AWS region" ;;
esac

ROLE="spire-kms"
USER="spire-kms-base"
POLICY="SpireKmsKeyManager"
ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/${ROLE}"
POLICY_ARN="arn:aws:iam::${ACCOUNT}:policy/${POLICY}"

say "0. who this will be created for"
info "identity: $CALLER"
info "account:  $ACCOUNT"
info "region:   $REGION  (the CA keys are created here)"
case "$CALLER" in
  *:root) info "you are authenticated as root; that is fine for a one-time setup, and no root access key is created or used" ;;
esac
if [ -n "$UNAUTHENTICATED" ]; then
  info "no credentials: the reads below fail, so the plan assumes nothing exists yet"
fi

say "1. the KMS policy the role will hold ($POLICY)"
cat > "$TMP/kms.json" <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "SpireManagesItsOwnCaKeys",
      "Effect": "Allow",
      "Action": [
        "kms:CreateKey", "kms:CreateAlias", "kms:UpdateAlias", "kms:DeleteAlias",
        "kms:ListAliases", "kms:ListKeys", "kms:DescribeKey", "kms:GetPublicKey",
        "kms:Sign", "kms:ScheduleKeyDeletion", "kms:TagResource"
      ],
      "Resource": "*"
    },
    {
      "Sid": "TagBasedKeyDiscovery",
      "Effect": "Allow",
      "Action": ["tag:GetResources"],
      "Resource": "*"
    }
  ]
}
JSON
if aws iam get-policy --policy-arn "$POLICY_ARN" >/dev/null 2>&1; then
  run aws iam create-policy-version --policy-arn "$POLICY_ARN" \
    --policy-document "file://$TMP/kms.json" --set-as-default >/dev/null
  ok "exists — added a new default version"
else
  run aws iam create-policy --policy-name "$POLICY" \
    --policy-document "file://$TMP/kms.json" >/dev/null
  ok "created"
fi
info "CreateKey and ScheduleKeyDeletion cannot be scoped to a pre-existing key,"
info "because the plugin creates the keys it manages. That is why this is a role."

say "2. the role that signs ($ROLE)"
python3 - "$ACCOUNT" "$USER" "$EXTERNAL_ID" > "$TMP/trust.json" <<'PY'
import json, sys
account, user, external_id = sys.argv[1], sys.argv[2], sys.argv[3]
statement = {
    "Effect": "Allow",
    "Principal": {"AWS": f"arn:aws:iam::{account}:user/{user}"},
    "Action": "sts:AssumeRole",
}
if external_id:
    statement["Condition"] = {"StringEquals": {"sts:ExternalId": external_id}}
print(json.dumps({"Version": "2012-10-17", "Statement": [statement]}, indent=2))
PY
if aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  run aws iam update-assume-role-policy --role-name "$ROLE" \
    --policy-document "file://$TMP/trust.json"
  ok "exists — trust policy updated"
else
  run aws iam create-role --role-name "$ROLE" \
    --description "SPIRE server KMS KeyManager (S1)" \
    --assume-role-policy-document "file://$TMP/trust.json" >/dev/null
  ok "created"
fi
run aws iam attach-role-policy --role-name "$ROLE" --policy-arn "$POLICY_ARN"
ok "KMS policy attached"
if [ -n "$EXTERNAL_ID" ]; then
  info "trust policy requires sts:ExternalId (stored in .env below)"
fi

say "3. the base user, which may do exactly one thing ($USER)"
if aws iam get-user --user-name "$USER" >/dev/null 2>&1; then
  ok "exists"
else
  run aws iam create-user --user-name "$USER" >/dev/null
  ok "created"
fi
python3 - "$ACCOUNT" "$ROLE" > "$TMP/assume.json" <<'PY'
import json, sys
account, role = sys.argv[1], sys.argv[2]
print(json.dumps({
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Action": "sts:AssumeRole",
        "Resource": f"arn:aws:iam::{account}:role/{role}",
    }],
}, indent=2))
PY
run aws iam put-user-policy --user-name "$USER" --policy-name SpireAssumeKmsRole \
  --policy-document "file://$TMP/assume.json"
ok "its only permission: sts:AssumeRole on $ROLE_ARN"

say "4. the credential for .env"
umask 077
KEY_ID=""
SECRET=""
if grep -q '^AWS_ACCESS_KEY_ID=' .env 2>/dev/null; then
  ok ".env already holds an access key — leaving it alone"
  info "(delete the line and re-run if you want a fresh key)"
else
  EXISTING="$(aws iam list-access-keys --user-name "$USER" \
    --query 'AccessKeyMetadata[].AccessKeyId' --output text 2>/dev/null || true)"
  if [ -n "$EXISTING" ]; then
    printf '\033[1;31m   ✗ %s already has an access key (%s) and its secret cannot be read back.\033[0m\n' \
      "$USER" "$EXISTING" >&2
    echo "     Either put that key in .env yourself, or delete it and re-run:" >&2
    for k in $EXISTING; do
      echo "       aws iam delete-access-key --user-name $USER --access-key-id $k" >&2
    done
    exit 1
  fi
  if [ -n "$DRY_RUN" ]; then
    info "would create one access key for $USER"
    KEY_ID="<created by this script>"
  else
    KEY_JSON="$(aws iam create-access-key --user-name "$USER")"
    KEY_ID="$(printf '%s' "$KEY_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["AccessKey"]["AccessKeyId"])')"
    SECRET="$(printf '%s' "$KEY_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["AccessKey"]["SecretAccessKey"])')"
    ok "created access key ${KEY_ID} (its secret is written below, once)"
  fi
fi

say "5. .env (gitignored; single-quoted so the shell cannot mangle a value)"
set_env() { # set_env <KEY> <VALUE> — replace in place, or append
  local key="$1" value="$2" tmp
  if [ -f .env ] && grep -q "^${key}=" .env; then
    tmp="$(mktemp)"
    grep -v "^${key}=" .env > "$tmp"
    printf "%s='%s'\n" "$key" "$value" >> "$tmp"
    mv "$tmp" .env
  else
    printf "%s='%s'\n" "$key" "$value" >> .env
  fi
}
if [ -n "$DRY_RUN" ]; then
  info "would write to .env:"
  printf '       SPIRE_KEY_MANAGER=%s\n' "'aws_kms'"
  printf '       SPIRE_KMS_REGION=%s\n' "'$REGION'"
  printf '       SPIRE_KMS_SERVER_ID=%s\n' "'acme-com'"
  printf '       SPIRE_KMS_ROLE_ARN=%s\n' "'$ROLE_ARN'"
  printf '       AWS_ACCESS_KEY_ID=%s\n' "'${KEY_ID:-(unchanged)}'"
  printf '       AWS_SECRET_ACCESS_KEY=%s\n' "'<written but never printed>'" 
  [ -n "$EXTERNAL_ID" ] && printf '       SPIRE_KMS_EXTERNAL_ID=%s\n' "'<generated>'"
else
  set_env SPIRE_KEY_MANAGER aws_kms
  # No dots: the plugin accepts only alphanumerics, "/", "_" and "-" here, and this
  # value must be identical on every replica or each mints its own CA.
  set_env SPIRE_KMS_SERVER_ID acme-com
  set_env SPIRE_KMS_REGION "$REGION"
  set_env SPIRE_KMS_ROLE_ARN "$ROLE_ARN"
  if [ -n "$KEY_ID" ] && [ -n "$SECRET" ]; then
    set_env AWS_ACCESS_KEY_ID "$KEY_ID"
    set_env AWS_SECRET_ACCESS_KEY "$SECRET"
  fi
  [ -n "$EXTERNAL_ID" ] && set_env SPIRE_KMS_EXTERNAL_ID "$EXTERNAL_ID"
  chmod 600 .env 2>/dev/null || true
  ok "written (mode 0600). setup.sh will add its own demo secrets if .env is new."
fi

say "6. self-test: the credential can assume the role (what SPIRE does first)"
if [ -n "$DRY_RUN" ]; then
  info "dry run: skipped"
else
  if ( set -a; . ./.env; set +a
       aws sts assume-role --role-arn "$SPIRE_KMS_ROLE_ARN" \
         --role-session-name spire-setup-check \
         --query 'AssumedRoleUser.Arn' --output text >/dev/null 2>&1 ); then
    ok "sts:AssumeRole succeeded"
  else
    die "sts:AssumeRole failed — check the trust policy (and, if you used it, the external ID)"
  fi
fi

printf '\n\033[1;32mDone.\033[0m Next: \033[1m./scripts/setup.sh\033[0m\n'
cat <<'NOTE'

   That switches the KeyManager, mounts the credential as a profile in the pod,
   scales SPIRE to two replicas, and refuses to pass unless both report the same
   CA.

   To go back to the unattended default afterwards, edit .env (set
   SPIRE_KEY_MANAGER=disk) and re-run setup.sh — it deletes the KMS credentials
   from the cluster. To undo this script as well:

     aws iam list-access-keys  --user-name spire-kms-base
     aws iam delete-access-key --user-name spire-kms-base --access-key-id <ID>
     aws iam delete-user-policy --user-name spire-kms-base --policy-name SpireAssumeKmsRole
     aws iam delete-user --user-name spire-kms-base
     aws iam detach-role-policy --role-name spire-kms --policy-arn <POLICY_ARN>
     aws iam delete-role --role-name spire-kms
     aws iam delete-policy --policy-arn <POLICY_ARN>

   The KMS keys SPIRE created are yours to keep or remove. To find them:

     aws resourcegroupstaggingapi get-resources --resource-type-filters kms \
       --tag-filters Key=spire-server-td,Values=acme.com

   ...and schedule deletion with:
     aws kms schedule-key-deletion --key-id <KEY_ID> --pending-window-in-days 7
NOTE
