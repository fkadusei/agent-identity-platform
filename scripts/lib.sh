#!/bin/bash
# =============================================================================
# lib.sh — the cluster every script talks to, pinned.
#
# Sourced, never run. `kubectl` is wrapped so it always targets
# `kind-agent-platform`, whatever the *active* context happens to be.
#
# Why this exists (S14): setup.sh verified the cluster by name on one line
# (`kubectl cluster-info --context kind-agent-platform`) and then ran every
# later kubectl against whatever context was active. Docker Desktop restarting
# makes `docker-desktop` active, so a full run applied everything to the wrong
# cluster and died with `error: no objects passed to apply` — a message naming
# neither the file nor the cluster it was aiming at. Pinning here means a call
# site cannot forget.
#
#   . scripts/lib.sh          # kubectl is now pinned
#   KUBE_CONTEXT=kind-other . scripts/lib.sh   # ...to a different cluster
# =============================================================================

if [ -z "${KUBE_CONTEXT:-}" ]; then
  KUBE_CONTEXT="kind-agent-platform"
fi
# Exported so a nested script (setup.sh -> check-images.sh) inherits the choice.
export KUBE_CONTEXT

kubectl() { command kubectl --context "$KUBE_CONTEXT" "$@"; }

# Linkerd reads the kubeconfig's active context itself and cannot be wrapped the
# same way, so callers pass `linkerd --context "$KUBE_CONTEXT"`.
