#!/usr/bin/env bash
# Put flipwise-dc:dev into this node's k3s image store (no registry needed).
#   bash scripts/k3s/load_image.sh                       # from local Docker (built here)
#   bash scripts/k3s/load_image.sh flipwise-dc.tar.gz    # from a tarball made by build_image.sh
#   bash scripts/k3s/load_image.sh --k3d                 # into the single-laptop k3d cluster
set -euo pipefail
source "$(dirname "$0")/_lib.sh"
case "${1:-}" in
  --k3d) k3d image import flipwise-dc:dev -c flipwise ;;
  "")    docker save flipwise-dc:dev | sudo k3s ctr images import - ;;
  *)     [[ -f "$1" ]] || die "no such file: $1"; gunzip -c "$1" | sudo k3s ctr images import - ;;
esac
