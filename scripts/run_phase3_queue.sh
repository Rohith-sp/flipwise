#!/usr/bin/env bash
# Phase 3 goal 1 queue (PRD 18.2, D66): ablations and the rho/slack sensitivity sweeps on the
# validation split only. Never uses --split test. Finished runs are reused by run_id, so rerun
# this after an interruption to resume. Progress: results/phase3_progress.txt.
#   bash scripts/run_phase3_queue.sh
cd "$(dirname "$0")/.." || exit 1
LOG=results/sweeps_logs
mkdir -p "$LOG"
run() {  # run <sweep name> <policies>
  echo "START $1 $(date '+%F %T')" >> results/phase3_progress.txt
  uv run flipwise sweep --config configs/base.yaml --sweep "configs/sweeps/$1.yaml" \
    --split validation --policies "$2" --jobs 5 > "$LOG/$1.log" 2>&1
  echo "END $1 rc=$? $(date '+%F %T') $(grep '^wrote' "$LOG/$1.log" | tail -1)" >> results/phase3_progress.txt
}
run ablation_screen place_once,decision_flip
run ablation_width place_once,decision_flip
run sens_slack_base place_once,fixed_savings,decision_flip
run sens_k_slack place_once,fixed_savings,decision_flip
run sens_rho all
echo "ALL DONE $(date '+%F %T')" >> results/phase3_progress.txt
