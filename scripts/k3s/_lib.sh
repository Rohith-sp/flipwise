# Shared helpers for scripts/k3s/*.sh (PRD §13.5 DT3-K, D72). Sourced, not run.
# k3s itself is Linux-only; the coordinator and live dashboard run anywhere with `uv run`.
SITES=(delhi mumbai chennai kolkata hyderabad)   # dc0..dc4, the order of configs/regions5.yaml
NODEPORT_BASE=30101                               # dc<i> is on NodePort 30101 + i
NS=flipwise
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MANIFEST="$REPO/deploy/k3s/datacentres.yaml"

die() { echo "$(basename "$0"): $*" >&2; exit 2; }

# kubectl from PATH, else the one bundled with k3s. KUBECTL="..." overrides both.
if [[ -z "${KUBECTL:-}" ]]; then
  if command -v kubectl >/dev/null 2>&1; then KUBECTL=kubectl
  elif command -v k3s >/dev/null 2>&1; then KUBECTL="k3s kubectl"
  fi
fi
kc() { [[ -n "${KUBECTL:-}" ]] || die "no kubectl (install kubectl, or k3s which bundles it)"; $KUBECTL "$@"; }

dc_urls() {  # dc_urls <host> <n>: the --dc-urls list for the first n sites
  local host="$1" n="$2" i out=()
  for ((i = 0; i < n; i++)); do out+=("http://$host:$((NODEPORT_BASE + i))"); done
  (IFS=,; echo "${out[*]}")
}

wait_ready() {  # every datacentre Deployment rolled out, or fail with where each pod is stuck
  if ! kc -n "$NS" rollout status deploy --timeout="${1:-180s}"; then
    kc -n "$NS" get pods -o wide
    echo "Pending pods usually mean a site label is missing (label_sites.sh);" \
         "ErrImageNeverPull means the image was not imported on that node (load_image.sh)." >&2
    return 1
  fi
}
