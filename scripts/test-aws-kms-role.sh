#!/bin/bash
# =============================================================================
# test-aws-kms-role.sh — self-test for scripts/setup-aws-kms-role.sh.
#
# Exists because three bugs in that script reached a real AWS account: a flag read
# without being declared (set -u), the role created before the user it trusts, and a
# missing --policy-arn. Each was invisible to the testing I had done, because the
# stub I tested against accepted anything.
#
# So this stub is **strict**: it fails the way the real CLI fails when a required
# argument is absent (`ParamValidation`), and it returns not-found the way IAM does.
# A rubber-stamp stub proves only that the script runs.
#
# Run: ./scripts/test-aws-kms-role.sh        (no AWS access needed, nothing touched)
# =============================================================================
set -uo pipefail
cd "$(dirname "$0")/.."

STUB_DIR="$(mktemp -d)"
WORK="$(mktemp -d)"
trap 'rm -rf "$STUB_DIR" "$WORK"' EXIT

cat > "$STUB_DIR/aws" <<'STUB'
#!/bin/bash
# A strict stand-in for the AWS CLI: only the calls this script makes, each with its
# required arguments enforced.
log="${STUB_LOG:-/dev/null}"
printf '%s\n' "$*" >> "$log"
sub="$1 $2"
shift 2 2>/dev/null || true
need() {
  local flag="$1"; shift
  for arg in "$@"; do [ "$arg" = "$flag" ] && return 0; done
  printf 'aws: [ERROR]: An error occurred (ParamValidation): the following arguments are required: %s\n' "$flag" >&2
  exit 255
}
case "$sub" in
  "sts get-caller-identity")
    echo '{"UserId":"AIDAEXAMPLE","Account":"111122223333","Arn":"arn:aws:iam::111122223333:user/admin-example"}' ;;
  "sts assume-role")
    need --role-arn "$@"; need --role-session-name "$@"
    if [ "${STUB_ASSUME_RACE:-}" = "1" ] && [ ! -f "${STUB_DIR:-/tmp}/assume-attempted" ]; then
      : > "${STUB_DIR:-/tmp}/assume-attempted"
      printf 'aws: [ERROR]: An error occurred (AccessDenied) when calling the AssumeRole operation: User: arn:aws:iam::111122223333:user/spire-kms-base is not authorized to perform: sts:AssumeRole on resource: arn:aws:iam::111122223333:role/spire-kms\n' >&2
      exit 254
    fi
    echo "arn:aws:sts::111122223333:assumed-role/spire-kms/spire-setup-check" ;;
  "iam get-policy")
    need --policy-arn "$@"
    [ "${STUB_POLICY_EXISTS:-}" = "1" ] || exit 254
    case " $* " in
      *" --query "*) echo "v3" ;;
      *) echo '{"Policy":{"DefaultVersionId":"v3"}}' ;;
    esac ;;
  "iam get-policy-version")
    need --policy-arn "$@"; need --version-id "$@"
    [ -n "${STUB_POLICY_DOC:-}" ] && cat "$STUB_POLICY_DOC" ;;
  "iam create-policy") need --policy-name "$@"; need --policy-document "$@" ;;
  "iam create-policy-version") need --policy-arn "$@"; need --policy-document "$@" ;;
  "iam get-role") need --role-name "$@"; [ "${STUB_ROLE_EXISTS:-}" = "1" ] || exit 254 ;;
  "iam create-role")
    need --role-name "$@"; need --assume-role-policy-document "$@"
    if [ "${STUB_ROLE_RACE:-}" = "1" ] && [ ! -f "${STUB_DIR:-/tmp}/role-attempted" ]; then
      : > "${STUB_DIR:-/tmp}/role-attempted"
      printf 'aws: [ERROR]: An error occurred (MalformedPolicyDocument) when calling the CreateRole operation: Invalid principal in policy: "AWS":"arn:aws:iam::111122223333:user/spire-kms-base"\n' >&2
      exit 254
    fi ;;
  "iam update-assume-role-policy") need --role-name "$@"; need --policy-document "$@" ;;
  "iam attach-role-policy") need --role-name "$@"; need --policy-arn "$@" ;;
  "iam get-user") need --user-name "$@"; [ "${STUB_USER_EXISTS:-}" = "1" ] || exit 254 ;;
  "iam create-user") need --user-name "$@" ;;
  "iam put-user-policy") need --user-name "$@"; need --policy-name "$@"; need --policy-document "$@" ;;
  "iam list-access-keys") need --user-name "$@"; printf '%s' "${STUB_KEYS:-}" ;;
  "iam create-access-key")
    need --user-name "$@"
    echo '{"AccessKey":{"AccessKeyId":"AKIASTUBKEYEXAMPLE","SecretAccessKey":"s/x+y="}}' ;;
  *) exit 0 ;;
esac
STUB
chmod +x "$STUB_DIR/aws"

LOG="$WORK/calls.log"
FAILURES=0

# AWSCLI: our stub, on PATH ahead of the real CLI.
AWSCLI="PATH=$STUB_DIR:$PATH STUB_LOG=$LOG ENV_FILE=$WORK/env"

check() { # check <description> <condition...>
  local what="$1"; shift
  if "$@"; then
    printf '\033[1;32m   ✓ %s\033[0m\n' "$what"
  else
    printf '\033[1;31m   ✗ %s\033[0m\n' "$what"
    FAILURES=$((FAILURES + 1))
  fi
}
heard() { grep -q "$1" "$LOG"; }
order_ok() { # user must be created before the role that trusts it
  local u r
  u="$(grep -n 'iam create-user' "$LOG" | head -1 | cut -d: -f1)"
  r="$(grep -n 'iam create-role' "$LOG" | head -1 | cut -d: -f1)"
  [ -n "$u" ] && [ -n "$r" ] && [ "$u" -lt "$r" ]
}
count() { grep -c "$1" "$LOG" 2>/dev/null || true; }
run_script() { # run_script <output-file> <VAR=VAL ...> -- <args ...>
  local out="$1"; shift
  local vars=()
  while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do vars+=("$1"); shift; done
  shift # the --
  : > "$LOG"
  env PATH="$STUB_DIR:$PATH" STUB_LOG="$LOG" ENV_FILE="$WORK/env" "${vars[@]}" \
    ./scripts/setup-aws-kms-role.sh "$@" >"$out" 2>&1
  local rc=$?
  if [ "$rc" -ne 0 ]; then printf '\033[2m     (%s, exit %s)\033[0m\n' "$out" "$rc"; tail -3 "$out" | sed 's/^/     /'; fi
  return $rc
}

printf '\n\033[1;34m== fresh setup\033[0m\n'
run_script "$WORK/run1.log" STUB_POLICY_EXISTS=0 STUB_ROLE_EXISTS=0 STUB_USER_EXISTS=0 STUB_KEYS= -- --region us-east-1
check "exits 0" test $? -eq 0
check "creates the policy" heard "iam create-policy"
check "creates the user" heard "iam create-user"
check "grants it AssumeRole" heard "iam put-user-policy"
check "creates the role" heard "iam create-role"
check "attaches the KMS policy" heard "iam attach-role-policy"
check "creates one access key" heard "iam create-access-key"
check "self-tests with sts:AssumeRole" heard "sts assume-role"
check "user is created before the role that trusts it" order_ok
check "wrote 6 settings to the env file" test "$(grep -c '=' "$WORK/env" 2>/dev/null || echo 0)" -eq 6

printf '\n\033[1;34m== the env file is shell-parseable\033[0m\n'
[ -f "$WORK/env" ] && ( set -a; . "$WORK/env"; set +a
  [ "$SPIRE_KEY_MANAGER" = "aws_kms" ] \
    && [ "$SPIRE_KMS_SERVER_ID" = "acme-com" ] \
    && [ "$SPIRE_KMS_ROLE_ARN" = "arn:aws:iam::111122223333:role/spire-kms" ] \
    && [ "$AWS_SECRET_ACCESS_KEY" = "s/x+y=" ] )
check "values survive sourcing (quoting holds for / + =)" test $? -eq 0

printf '\n\033[1;34m== re-run against existing resources\033[0m\n'
run_script "$WORK/run2.log" STUB_POLICY_EXISTS=1 STUB_ROLE_EXISTS=1 STUB_USER_EXISTS=1 STUB_KEYS= -- --region us-east-1
check "exits 0" test $? -eq 0
check "does not create a second access key" test "$(count 'iam create-access-key')" -eq 0
check "re-applies the user policy (idempotent by nature)" heard "iam put-user-policy"
check "re-attaches the role policy (idempotent by nature)" heard "iam attach-role-policy"

printf '\n\033[1;34m== policy versions\033[0m\n'
python3 - "$WORK/expanded.json" <<'PY'
# The document the script will apply, extracted from the script itself: the point is
# to compare what IAM already holds against what is about to be sent.
import json, pathlib, sys
sh = pathlib.Path("scripts/setup-aws-kms-role.sh").read_text()
doc = sh.split('cat > "$TMP/kms.json" <<\'JSON\'\n', 1)[1].split("\nJSON", 1)[0]
pathlib.Path(sys.argv[1]).write_text(doc)
PY
run_script "$WORK/run4.log" STUB_POLICY_EXISTS=1 STUB_POLICY_DOC="$WORK/expanded.json" \
  STUB_ROLE_EXISTS=1 STUB_USER_EXISTS=1 -- --region us-east-1
check "identical stored document adds no version" test "$(count 'iam create-policy-version')" -eq 0

printf '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["kms:Sign"],"Resource":"*"}]}\n' \
  > "$WORK/different.json"
run_script "$WORK/run5.log" STUB_POLICY_EXISTS=1 STUB_POLICY_DOC="$WORK/different.json" \
  STUB_ROLE_EXISTS=1 STUB_USER_EXISTS=1 -- --region us-east-1
check "a changed document adds exactly one" test "$(count 'iam create-policy-version')" -eq 1

printf '\n\033[1;34m== an unreadable existing key is refused\033[0m\n'
rm -f "$WORK/env"
run_script "$WORK/run3.log" STUB_POLICY_EXISTS=1 STUB_ROLE_EXISTS=1 STUB_USER_EXISTS=1 \
  STUB_KEYS=$'AKIAOLDKEYOLDKEY\t' -- --region us-east-1
check "exits non-zero" test $? -ne 0
check "says how to remove it" grep -q "delete-access-key" "$WORK/run3.log"
check "does not create another key" test "$(count 'iam create-access-key')" -eq 0

printf '\n\033[1;34m== IAM has not caught up with the new user yet\033[0m\n'
rm -f "$STUB_DIR/role-attempted"
STUB_DIR="$STUB_DIR" run_script "$WORK/run6.log" STUB_ROLE_RACE=1 STUB_POLICY_EXISTS=0 \
  STUB_ROLE_EXISTS=0 STUB_USER_EXISTS=0 -- --region us-east-1
check "retries the role instead of failing" test $? -eq 0
check "and says why it is waiting" grep -q "cannot see the new user yet" "$WORK/run6.log"
check "created the role in the end" heard "iam create-role"

printf '\n\033[1;34m== the role is not assumable the instant it exists\033[0m\n'
rm -f "$STUB_DIR/assume-attempted"
STUB_DIR="$STUB_DIR" run_script "$WORK/run7.log" STUB_ASSUME_RACE=1 STUB_POLICY_EXISTS=0 \
  STUB_ROLE_EXISTS=0 STUB_USER_EXISTS=0 -- --region us-east-1
check "retries the self-test instead of failing" test $? -eq 0
check "and says it may still be propagating" grep -q "may still be propagating" "$WORK/run7.log"

printf '\n\033[1;34m== a real deny is shown, not summarised\033[0m\n'
cat > "$STUB_DIR/aws-deny" <<'DENY'
#!/bin/bash
if [ "$1 $2" = "sts assume-role" ]; then
  echo "aws: [ERROR]: An error occurred (AccessDenied) when calling the AssumeRole operation: explicit deny in a service control policy" >&2
  exit 254
fi
exec "$STUB_REAL" "$@"
DENY
chmod +x "$STUB_DIR/aws-deny"
STUB_REAL="$STUB_DIR/aws" PATH="$STUB_DIR:$PATH" \
  bash -c 'mkdir -p /tmp/deny-bin && cp "$0" /tmp/deny-bin/aws && chmod +x /tmp/deny-bin/aws' "$STUB_DIR/aws-deny"
: > "$LOG"
PATH="/tmp/deny-bin:$STUB_DIR:$PATH" STUB_LOG="$LOG" ENV_FILE="$WORK/env" STUB_REAL="$STUB_DIR/aws" \
  ./scripts/setup-aws-kms-role.sh --region us-east-1 >"$WORK/run8.log" 2>&1
check "exits non-zero on a real deny" test $? -ne 0
check "prints AWS's own message" grep -q "explicit deny in a service control policy" "$WORK/run8.log"
check "and does not pretend it is propagation only" grep -q "an explicit deny" "$WORK/run8.log"
rm -rf /tmp/deny-bin

printf '\n\033[1;34m== no credentials: the plan still works, and says so\033[0m\n'
: > "$LOG"
cat > "$STUB_DIR/aws-noauth" <<'NOAUTH'
#!/bin/bash
echo "aws: [ERROR]: An error occurred (NoCredentials): Unable to locate credentials. You can configure credentials by running \"aws login\"." >&2
exit 255
NOAUTH
chmod +x "$STUB_DIR/aws-noauth"
PATH="$STUB_DIR:$PATH" ENV_FILE="$WORK/env2" PATH="$STUB_DIR:$PATH" \
  bash -c 'mkdir -p /tmp/noauth-bin && cp "$0" /tmp/noauth-bin/aws && chmod +x /tmp/noauth-bin/aws' "$STUB_DIR/aws-noauth"
out="$(PATH=/tmp/noauth-bin:$PATH ENV_FILE="$WORK/env2" ./scripts/setup-aws-kms-role.sh --account 111122223333 --region us-east-1 --dry-run 2>&1)"
check "credential-free dry run exits 0" test $? -eq 0
check "and does not write the env file" test ! -f "$WORK/env2"
case "$out" in *"would run"*) check "and prints the plan" true ;; *) check "and prints the plan" false ;; esac

printf '\n'
if [ "$FAILURES" -eq 0 ]; then
  printf '\033[1;32mAll checks passed.\033[0m\n'
  exit 0
fi
printf '\033[1;31m%d check(s) failed.\033[0m\n' "$FAILURES"
exit 1
