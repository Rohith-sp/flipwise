#!/usr/bin/env bash
# DT2 acceptance (PRD §13.5, §18): the Compose cluster must reproduce the in-process outputs.
#   toy    R-DEP-1: every policy on the toy scenario, SHA-256 of jobs.csv, decisions.csv, events.log
#   dev    R-DEP-2: decision_flip on the dev replicate (about 3 minutes)
#   crash  R-DEP-3 in Compose: kill one datacentre mid-run; the coordinator must fail with
#          DeploymentError and write no metrics.json
#   bash scripts/docker_check.sh [toy|dev|crash|all]     (default: all)
set -uo pipefail
cd "$(dirname "$0")/.."
WHAT="${1:-all}"
POLICIES=(fcfs place_once periodic fixed_savings decision_flip pred_error pig)
export GIT_COMMIT="${GIT_COMMIT:-$(git rev-parse HEAD 2>/dev/null || echo unknown)}"
WORK=$(mktemp -d)
chmod 777 "$WORK"  # the container runs as uid 1000, which may not own this folder
FAILED=0
trap 'docker compose down -v >/dev/null 2>&1; rm -rf "$WORK"' EXIT

# Reuse the committed layers; building once up front keeps the timed runs clean.
docker compose build >/dev/null || { echo "docker_check: build failed"; exit 2; }

same() {  # same <dir_a> <dir_b>: the three byte-for-byte files of R-DEP-1
  local ok=0 f
  for f in jobs.csv decisions.csv events.log; do
    cmp -s "$1/$f" "$2/$f" || { echo "  DIFF $f"; ok=1; }
  done
  return $ok
}

run_pair() {  # run_pair <label> <run args...>: in-process reference, then the Compose cluster
  local label="$1"; shift
  local ref="$WORK/ref_$label" res="$WORK/res_$label"
  mkdir -p "$res"; chmod 777 "$res"
  uv run flipwise run "$@" --out "$ref" >/dev/null 2>&1 || { echo "FAIL $label: reference run"; FAILED=1; return; }
  FLIPWISE_RESULTS="$res" FLIPWISE_RUN_ARGS="$*" docker compose up --abort-on-container-exit \
    --exit-code-from coordinator >"$WORK/$label.log" 2>&1
  local rc=$?
  docker compose down -v >/dev/null 2>&1
  local got ref_dir
  got=$(find "$res" -name jobs.csv -printf '%h\n' | head -1)
  ref_dir=$(find "$ref" -name jobs.csv -printf '%h\n' | head -1)
  if [[ $rc -eq 0 && -n "$got" ]] && same "$got" "$ref_dir"; then
    echo "PASS $label  ($(sha256sum "$got/jobs.csv" | cut -c1-12))"
  else
    echo "FAIL $label  (exit $rc); log: $WORK/$label.log"; tail -n 5 "$WORK/$label.log"; FAILED=1
  fi
}

if [[ $WHAT == toy || $WHAT == all ]]; then
  echo "== R-DEP-1: toy scenario, every policy"
  for p in "${POLICIES[@]}"; do run_pair "toy_$p" --scenario tests/fixtures/toy --policy "$p"; done
fi
if [[ $WHAT == dev || $WHAT == all ]]; then
  echo "== R-DEP-2: dev replicate, decision_flip"
  run_pair dev_decision_flip --config configs/base.yaml --policy decision_flip
fi
if [[ $WHAT == crash || $WHAT == all ]]; then
  echo "== R-DEP-3: kill dc-mumbai mid-run"
  res="$WORK/res_crash"; mkdir -p "$res"; chmod 777 "$res"
  FLIPWISE_RESULTS="$res" FLIPWISE_RUN_ARGS="--config configs/base.yaml --policy decision_flip" \
    docker compose up -d >/dev/null 2>&1
  cid=$(docker compose ps -q coordinator)
  sleep 25  # the dev replicate takes minutes, so the run is under way
  docker compose kill dc-mumbai >/dev/null 2>&1
  rc=$(docker wait "$cid")
  err=$(docker logs "$cid" 2>&1 | grep -c DeploymentError)
  docker compose down -v >/dev/null 2>&1
  if [[ $rc -ne 0 && $err -ge 1 && -z "$(find "$res" -name metrics.json)" ]]; then
    echo "PASS crash  (coordinator exit $rc, DeploymentError, no metrics.json)"
  else
    echo "FAIL crash  (exit $rc, DeploymentError lines: $err)"; FAILED=1
  fi
fi
exit $FAILED
