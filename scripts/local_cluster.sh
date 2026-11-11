#!/usr/bin/env bash
# DT1 local split (PRD §13.5): start one `flipwise dc-serve` per datacentre on 127.0.0.1, wait for
# /health, run `flipwise run --mode remote`, then stop every service, also on failure or Ctrl-C
# (R-DEP-3). Linux bash or Git Bash on Windows; local_cluster.ps1 is the PowerShell twin.
#
#   bash scripts/local_cluster.sh [--base-port 8101] [--n-dc 3] [--crash DC:N] <run args>
#   bash scripts/local_cluster.sh --scenario tests/fixtures/toy --policy decision_flip
#   bash scripts/local_cluster.sh --config configs/base.yaml --policy fcfs
#
# --crash DC:N is fault injection for R-DEP-3: service DC exits on its N-th simulation request.
# Service logs end up in results/<run_id>/dc-<id>.log (or the run's --out folder).
set -euo pipefail

BASE_PORT=8101
N_DC=3
CRASH=""
RUN_ARGS=()
while (($#)); do
  case "$1" in
    --base-port) BASE_PORT="$2"; shift 2 ;;
    --n-dc) N_DC="$2"; shift 2 ;;
    --crash) CRASH="$2"; shift 2 ;;
    *) RUN_ARGS+=("$1"); shift ;;
  esac
done

cd "$(dirname "$0")/.."
if [[ -x .venv/Scripts/python.exe ]]; then PY=.venv/Scripts/python.exe
elif [[ -x .venv/bin/python ]]; then PY=.venv/bin/python
else uv sync -q; PY=$([[ -x .venv/Scripts/python.exe ]] && echo .venv/Scripts/python.exe || echo .venv/bin/python)
fi

PORTS=()
URLS=()
for ((i = 0; i < N_DC; i++)); do
  PORTS+=($((BASE_PORT + i)))
  URLS+=("http://127.0.0.1:$((BASE_PORT + i))")
done
URL_LIST=$(IFS=,; echo "${URLS[*]}")

# Refuse busy ports before starting anything, so cleanup never touches a process we did not start.
"$PY" - "${PORTS[@]}" <<'EOF' || { echo "local_cluster: port in use; nothing started" >&2; exit 2; }
import socket, sys
for p in sys.argv[1:]:
    with socket.socket() as s:
        if sys.platform != "win32":  # ignore TIME_WAIT from a previous run, like the services do
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", int(p)))
        except OSError:
            print(f"port {p} is in use", file=sys.stderr)
            sys.exit(1)
EOF

LOG_DIR=$(mktemp -d)
PIDS=()
STARTED=0

stop_tree() {  # Windows: the venv launcher starts the real interpreter as a child, so stop the tree
  local pid=$1 winpid
  case "$(uname -s)" in
    MINGW* | MSYS* | CYGWIN*)
      winpid=$(cat "/proc/$pid/winpid" 2>/dev/null || true)
      if [[ -n "$winpid" ]]; then taskkill //F //T //PID "$winpid" >/dev/null 2>&1 || true; fi ;;
  esac
  kill "$pid" 2>/dev/null || true
}

stop_services() {
  # Only processes this script started are touched, never "whatever holds the port".
  ((STARTED)) || return 0
  STARTED=0
  for pid in "${PIDS[@]}"; do stop_tree "$pid"; done
  for pid in "${PIDS[@]}"; do wait "$pid" 2>/dev/null || true; done
}
trap stop_services EXIT
trap 'echo "local_cluster: interrupted" >&2; exit 130' INT TERM

STARTED=1
for ((i = 0; i < N_DC; i++)); do
  extra=()
  if [[ -n "$CRASH" && "${CRASH%%:*}" == "$i" ]]; then extra=(--crash-at-request "${CRASH#*:}"); fi
  "$PY" -m flipwise.cli dc-serve --dc-id "$i" --port "${PORTS[$i]}" "${extra[@]}" \
    >"$LOG_DIR/dc-$i.log" 2>&1 &
  PIDS+=($!)
done

"$PY" - "${URLS[@]}" <<'EOF' || { echo "local_cluster: services did not answer /health in 20 s" >&2; exit 3; }
import sys, time, urllib.request
deadline = time.monotonic() + 20
for url in sys.argv[1:]:
    while True:
        try:
            urllib.request.urlopen(url + "/health", timeout=1).read()
            break
        except OSError:
            if time.monotonic() > deadline:
                print(f"{url} did not answer", file=sys.stderr)
                sys.exit(1)
            time.sleep(0.1)
EOF
echo "local_cluster: ${N_DC} services up on ${URL_LIST}"

set +e
"$PY" -m flipwise.cli run --mode remote --dc-urls "$URL_LIST" "${RUN_ARGS[@]}" 2>&1 | tee "$LOG_DIR/run.log"
STATUS=${PIPESTATUS[0]}
set -e
stop_services

RUN_DIR=$(sed -n 's/^wrote //p' "$LOG_DIR/run.log" | tail -n 1 | tr -d '\r' | tr '\\' '/')
if [[ $STATUS -eq 0 && -n "$RUN_DIR" ]]; then
  cp "$LOG_DIR"/dc-*.log "$RUN_DIR"/
  echo "local_cluster: done; service logs in $RUN_DIR"
else
  echo "local_cluster: run failed (exit $STATUS); service logs in $LOG_DIR" >&2
fi
exit "$STATUS"
