#!/usr/bin/env bash
# Apply the datacentre manifests, wait until every site is ready, and print the URLs to use.
#   bash scripts/k3s/deploy.sh [HOST]     # HOST: any node's IP (default 127.0.0.1)
#   bash scripts/k3s/deploy.sh --delete   # remove the namespace (and every datacentre)
set -euo pipefail
source "$(dirname "$0")/_lib.sh"
if [[ "${1:-}" == --delete ]]; then kc delete namespace "$NS" --ignore-not-found; exit 0; fi
host="${1:-127.0.0.1}"
kc apply -f "$MANIFEST"
wait_ready
kc -n "$NS" get pods -o wide
cat <<MSG

Datacentre dashboards: http://$host:30101 (Delhi NCR) ... http://$host:30105 (Hyderabad)
Live demo, from the repo on the presenting laptop (Linux or Windows):
  uv run flipwise live --mode remote --config configs/regions5.yaml --dc-urls $(dc_urls "$host" 5)
Research check (R-DEP-1 on the toy, three sites):
  bash scripts/k3s/k3s_check.sh --host $host
MSG
