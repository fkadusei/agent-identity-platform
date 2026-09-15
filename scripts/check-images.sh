#!/usr/bin/env bash
# Are the running pods running the images built from this revision?
#
# "It works on kind" is only meaningful if the pods are actually running the code
# you just built. Reusing the :demo tag with imagePullPolicy: IfNotPresent makes
# that easy to get wrong — and easy to *misread*: a missing audit field was once
# blamed on a stale tools image when the image was in fact current, and the real
# cause (a call site that never passed the tenant) was missed because of it. Each
# app image carries the git revision it was built from; this compares the stamp
# inside the running container with HEAD.
#
#   ./scripts/check-images.sh        # exits non-zero if any pod is stale
set -euo pipefail

NS="${NAMESPACE:-agent-platform}"
SERVICES=(api tools agent gateway sandbox)

want="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
if ! git diff --quiet 2>/dev/null; then
  want="$want-dirty"
  echo "note: the working tree is dirty — an image built now would be stamped $want"
fi

fail=0
for svc in "${SERVICES[@]}"; do
  # A pod that is terminating is still in the list but is on its way out — it is
  # expected to hold the old image right after a rollout, so it is not a failure.
  pods="$(kubectl -n "$NS" get pods -l "app=$svc" \
    -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.metadata.deletionTimestamp}{"\n"}{end}' 2>/dev/null || true)"
  if [ -z "$pods" ]; then
    printf '  %-8s %s\n' "$svc" "no pods"
    fail=1
    continue
  fi
  while read -r name deleting; do
    [ -n "$name" ] || continue
    if [ -n "$deleting" ]; then
      printf '  %-8s %-32s %s\n' "$svc" "$name" "(terminating)"
      continue
    fi
    got="$(kubectl -n "$NS" exec "pod/$name" -c "$svc" -- printenv GIT_SHA 2>/dev/null || echo "(not stamped)")"
    if [ "$got" = "$want" ]; then
      printf '  %-8s %-32s %s\n' "$svc" "$name" "$got"
    else
      printf '  %-8s %-32s %s  != %s\n' "$svc" "$name" "$got" "$want"
      fail=1
    fi
  done <<< "$pods"
done

if [ "$fail" -ne 0 ]; then
  cat >&2 <<'MSG'

A pod is not running the revision you built. With a reused :demo tag and
imagePullPolicy: IfNotPresent, a rollout can look successful while the old image
stays. Rebuild, reload, and recreate — or just run ./scripts/setup.sh, which does
all of it:

  docker build --build-arg GIT_SHA="$(git rev-parse --short HEAD)" \
    -f docker/<svc>.Dockerfile -t agent-platform/<svc>:demo .
  kind load docker-image agent-platform/<svc>:demo --name agent-platform
  kubectl -n agent-platform rollout restart deploy/<svc>
MSG
  exit 1
fi
echo "all pods are running the revision you built"
