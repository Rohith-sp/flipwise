#!/usr/bin/env bash
# Single-laptop rehearsal of the multi-laptop k3s setup: k3s nodes as Docker containers (k3d).
# Same manifests, labels and checks as the real thing; only the node machines are simulated.
#   bash scripts/k3s/k3d_cluster.sh up [--agents N]   # N=0 (default): one node hosts all five
#   bash scripts/k3s/k3d_cluster.sh down
# Disk: about 250 MB for the k3s node image plus about 180 MB of flipwise-dc per node, because
# every k3d node keeps its own image store. With little free disk, keep --agents 0 or 1.
set -euo pipefail
source "$(dirname "$0")/_lib.sh"
command -v k3d >/dev/null || die "k3d not found: https://k3d.io (one static binary)"
CLUSTER=flipwise
case "${1:-}" in
  up)
    agents=0
    [[ "${2:-}" == --agents ]] && agents="${3:?--agents needs a number}"
    docker image inspect flipwise-dc:dev >/dev/null 2>&1 || bash "$REPO/scripts/k3s/build_image.sh"
    # NodePorts 30101-30105 are published on the laptop, as on a real node. Traefik and
    # metrics-server are not needed and cost memory on a hot laptop.
    k3d cluster create "$CLUSTER" --agents "$agents" --no-lb --wait \
      -p "30101-30105:30101-30105@server:0" \
      --k3s-arg "--disable=traefik@server:*" --k3s-arg "--disable=metrics-server@server:*"
    k3d image import flipwise-dc:dev -c "$CLUSTER"
    if [[ "$agents" -eq 0 ]]; then
      bash "$REPO/scripts/k3s/label_sites.sh" --all "k3d-$CLUSTER-server-0"
    else  # round-robin the five sites over the agent "laptops"
      declare -A per=()
      for i in "${!SITES[@]}"; do
        n="k3d-$CLUSTER-agent-$((i % agents))"
        per[$n]="${per[$n]:+${per[$n]},}${SITES[$i]}"
      done
      args=(); for n in "${!per[@]}"; do args+=("$n=${per[$n]}"); done
      bash "$REPO/scripts/k3s/label_sites.sh" "${args[@]}"
    fi
    bash "$REPO/scripts/k3s/deploy.sh" 127.0.0.1
    ;;
  down) k3d cluster delete "$CLUSTER" ;;
  *) die "usage: k3d_cluster.sh up [--agents N] | down" ;;
esac
