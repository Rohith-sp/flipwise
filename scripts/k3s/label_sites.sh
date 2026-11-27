#!/usr/bin/env bash
# Decide which laptop (k3s node) hosts which datacentre. Clears every old site label first, then
# restarts the datacentre pods so they move (nodeSelector does not evict running pods).
#   bash scripts/k3s/label_sites.sh --all <node>                       # one laptop hosts all five
#   bash scripts/k3s/label_sites.sh laptop-a=delhi,mumbai laptop-b=chennai laptop-c=kolkata,hyderabad
# Node names: `kubectl get nodes`. Every site must be placed exactly once.
set -euo pipefail
source "$(dirname "$0")/_lib.sh"
[[ $# -ge 1 ]] || die "usage: label_sites.sh --all NODE | NODE=site[,site] ..."
declare -A where=()
if [[ "$1" == --all ]]; then
  node="${2:?--all needs a node name}"
  for s in "${SITES[@]}"; do where[$s]="$node"; done
else
  for arg in "$@"; do
    node="${arg%%=*}"; list="${arg#*=}"
    [[ "$arg" == *=* && -n "$node" && -n "$list" ]] || die "bad argument: $arg"
    IFS=, read -ra picked <<< "$list"
    for s in "${picked[@]}"; do
      [[ " ${SITES[*]} " == *" $s "* ]] || die "unknown site $s (known: ${SITES[*]})"
      [[ -z "${where[$s]:-}" ]] || die "site $s placed twice"
      where[$s]="$node"
    done
  done
fi
for s in "${SITES[@]}"; do [[ -n "${where[$s]:-}" ]] || die "site $s is not placed on any node"; done
for s in "${SITES[@]}"; do kc label nodes --all "flipwise.io/site-$s-" >/dev/null 2>&1 || true; done
for s in "${SITES[@]}"; do
  kc label node "${where[$s]}" "flipwise.io/site-$s=true" --overwrite >/dev/null
  echo "dc-$s -> ${where[$s]}"
done
if kc get namespace "$NS" >/dev/null 2>&1; then
  kc -n "$NS" rollout restart deploy >/dev/null && wait_ready
fi
