#!/bin/bash
# teardown.sh — delete the demo cluster. Everything is disposable.
set -euo pipefail
kind delete cluster --name agent-platform
echo "cluster agent-platform deleted. Rebuild with ./scripts/setup.sh"
