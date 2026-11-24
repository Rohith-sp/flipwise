#!/usr/bin/env bash
# max_moves and cooldown_s sweeps, validation split only. Finished runs are reused.
set -u
J=${JOBS:-15}
for s in max_moves cooldown; do
  for p in decision_flip fixed_savings; do
    uv run flipwise sweep --config configs/base.yaml --sweep "configs/sweeps/${s}_${p}.yaml" \
      --split validation --policies "place_once,$p" --jobs "$J" 2>&1 | tail -3
    echo "DONE ${s}_${p}"
  done
done
