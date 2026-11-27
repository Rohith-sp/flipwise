#!/usr/bin/env bash
# Load-scaling timing runs (PRD 18.2 WP3, D66). Validation split only. --jobs 1 and one run at a
# time, because CPU time is the measurement: do not run anything else meanwhile. Finished runs
# are reused, so re-running resumes. Progress: results/scaling_progress.txt.
# Env: LIMIT=6h time limit for each 1.0 sweep cell; REPS=2 replicates.
set -u
LIMIT=${LIMIT:-6h}
REPS=${REPS:-2}
LOG=results/scaling_progress.txt
mkdir -p results
note() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }

note "START 0.05-0.5, 4 policies, ${REPS} replicates"
uv run flipwise sweep --config configs/base.yaml --sweep configs/sweeps/scaling_sampling.yaml \
  --split validation --policies place_once,fixed_savings,periodic,decision_flip \
  --replicates "$REPS" --jobs 1 2>&1 | tail -3 | tee -a "$LOG"
note "DONE 0.05-0.5"

for p in place_once decision_flip; do
  note "START sampling 1.0 $p (limit $LIMIT)"
  timeout "$LIMIT" uv run flipwise sweep --config configs/base.yaml \
    --sweep configs/sweeps/scaling_sampling_full.yaml --split validation \
    --policies "$p" --replicates "$REPS" --jobs 1 2>&1 | tail -3 | tee -a "$LOG"
  rc=${PIPESTATUS[0]}
  if [ "$rc" -eq 124 ]; then note "TIMEOUT sampling 1.0 $p after $LIMIT (a result)"
  else note "DONE sampling 1.0 $p exit=$rc"; fi
done
