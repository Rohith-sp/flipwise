#!/usr/bin/env bash
# DT3-K acceptance (PRD §13.5, D72): datacentres on k3s, coordinator on this laptop.
#   toy      R-DEP-1: every policy on the toy, jobs.csv/decisions.csv/events.log byte-identical
#            to the in-process run (three sites: delhi, mumbai, chennai)
#   restart  a restarted datacentre pod refuses work until /reset (409 NOT_READY), so a lost
#            site can never be continued on silently
#   crash    R-DEP-3: with dc-mumbai scaled to 0 the run exits non-zero with DeploymentError and
#            writes no metrics.json; dc-mumbai is scaled back afterwards
#   bash scripts/k3s/k3s_check.sh [--host NODE_IP] [toy|restart|crash|all]   (default: all)
# Runs only the toy scenario (seconds of CPU), never real data, never --split test.
set -uo pipefail
source "$(dirname "$0")/_lib.sh"
cd "$REPO"
HOST=127.0.0.1
if [[ "${1:-}" == --host ]]; then HOST="${2:?--host needs an address}"; shift 2; fi
WHAT="${1:-all}"
POLICIES=(fcfs place_once periodic fixed_savings decision_flip pred_error pig)
URLS=$(dc_urls "$HOST" 3)
WORK=$(mktemp -d)
FAILED=0
trap 'rm -rf "$WORK"' EXIT

same() {
  local ok=0 f
  for f in jobs.csv decisions.csv events.log; do
    cmp -s "$1/$f" "$2/$f" || { echo "  DIFF $f"; ok=1; }
  done
  return $ok
}
run_dir() { find "$1" -name jobs.csv -printf '%h\n' | head -1; }

if [[ $WHAT == toy || $WHAT == all ]]; then
  echo "== R-DEP-1 on k3s: toy scenario, every policy ($URLS)"
  for p in "${POLICIES[@]}"; do
    ref="$WORK/ref_$p" res="$WORK/res_$p"
    uv run flipwise run --scenario tests/fixtures/toy --policy "$p" --out "$ref" >/dev/null 2>&1 \
      || { echo "FAIL $p: reference run"; FAILED=1; continue; }
    if uv run flipwise run --scenario tests/fixtures/toy --policy "$p" --mode remote \
         --dc-urls "$URLS" --out "$res" >"$WORK/$p.log" 2>&1 \
       && same "$(run_dir "$res")" "$(run_dir "$ref")"; then
      echo "PASS $p  ($(sha256sum "$(run_dir "$res")/jobs.csv" | cut -c1-12))"
    else
      echo "FAIL $p; log: $WORK/$p.log"; tail -n 5 "$WORK/$p.log"; FAILED=1
    fi
  done
fi

if [[ $WHAT == restart || $WHAT == all ]]; then
  echo "== restarted pod refuses work until /reset"
  kc -n "$NS" delete pod -l flipwise.io/site=chennai --wait=true >/dev/null
  wait_ready 120s >/dev/null
  code=$(uv run python -c "
import json, sys, urllib.error, urllib.request as u
req = u.Request('http://$HOST:30103/dispatch', data=json.dumps({'t': 0}).encode(),
                headers={'Content-Type': 'application/json'}, method='POST')
try:
    u.urlopen(req, timeout=5); print(200)
except urllib.error.HTTPError as e:
    print(e.code)")
  if [[ "$code" == 409 ]]; then echo "PASS restart  (fresh dc-chennai answered 409)"
  else echo "FAIL restart  (got $code, expected 409)"; FAILED=1; fi
fi

if [[ $WHAT == crash || $WHAT == all ]]; then
  echo "== R-DEP-3 on k3s: dc-mumbai unavailable"
  kc -n "$NS" scale deploy/dc-mumbai --replicas=0 >/dev/null
  kc -n "$NS" wait --for=delete pod -l flipwise.io/site=mumbai --timeout=60s >/dev/null 2>&1
  res="$WORK/res_crash"
  uv run flipwise run --scenario tests/fixtures/toy --policy decision_flip --mode remote \
    --dc-urls "$URLS" --out "$res" >"$WORK/crash.log" 2>&1
  rc=$?
  kc -n "$NS" scale deploy/dc-mumbai --replicas=1 >/dev/null
  wait_ready 120s >/dev/null || FAILED=1
  if [[ $rc -ne 0 ]] && grep -q DeploymentError "$WORK/crash.log" \
     && [[ -z "$(find "$res" -name metrics.json 2>/dev/null)" ]]; then
    echo "PASS crash  (exit $rc, DeploymentError, no metrics.json)"
  else
    echo "FAIL crash  (exit $rc)"; tail -n 5 "$WORK/crash.log"; FAILED=1
  fi
fi
exit $FAILED
