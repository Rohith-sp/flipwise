#!/usr/bin/env bash
# Build the slim datacentre image (deploy/k3s/Dockerfile.dc, about 180 MB, almost all of it the
# python:3.12-slim base). With --save, also write a gzipped tarball to carry to other laptops.
#   bash scripts/k3s/build_image.sh [--save flipwise-dc.tar.gz]
set -euo pipefail
source "$(dirname "$0")/_lib.sh"
cd "$REPO"
commit=$(git rev-parse HEAD 2>/dev/null || echo unknown)
docker build -f deploy/k3s/Dockerfile.dc --build-arg GIT_COMMIT="$commit" -t flipwise-dc:dev .
if [[ "${1:-}" == --save ]]; then
  out="${2:?--save needs a file name}"
  docker save flipwise-dc:dev | gzip > "$out"
  echo "wrote $out ($(du -h "$out" | cut -f1)); copy it to each laptop and run load_image.sh there"
fi
