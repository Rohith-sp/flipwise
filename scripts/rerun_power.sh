#!/usr/bin/env bash
# D59: re-run validation and test in both power modes (PRD §7.2, D58) to recompute kgCO2. The
# decisions do not depend on power, so this re-measures the same decisions; it is not tuning.
# Finished runs are reused by run_id, so after an interruption just run this again.
#   bash scripts/rerun_power.sh
cd "$(dirname "$0")/.." || exit 1
mkdir -p results/rerun_logs
for split in validation test; do
  for mode in measured nameplate; do
    echo "START $split $mode $(date +%T)" >> results/rerun_progress.txt
    uv run flipwise compare --config configs/base.yaml --split "$split" --policies all --jobs 5 \
      --set power_mode="$mode" > "results/rerun_logs/${split}_${mode}.log" 2>&1
    echo "END $split $mode rc=$? $(date +%T) $(grep '^wrote' "results/rerun_logs/${split}_${mode}.log" | tail -1)" \
      >> results/rerun_progress.txt
  done
done
echo "ALL DONE $(date +%T)" >> results/rerun_progress.txt
