#!/usr/bin/env bash
# Validation-split ablations (PRD §14.6) and the sensitivity sweeps that need no new code (§14.4),
# one after another. Never uses --split test. Finished runs are reused by run_id, so after an
# interruption just run this again: it resumes. Progress goes to results/sweeps_progress.txt.
#   bash scripts/run_ablations.sh
cd "$(dirname "$0")/.." || exit 1
LOG=results/sweeps_logs
mkdir -p "$LOG"
run() {  # run <sweep name> <policies>
  echo "START $1 $(date +%T)" >> results/sweeps_progress.txt
  uv run flipwise sweep --config configs/base.yaml --sweep "configs/sweeps/$1.yaml" \
    --split validation --policies "$2" --jobs 5 > "$LOG/$1.log" 2>&1
  echo "END $1 rc=$? $(date +%T) $(grep '^wrote' "$LOG/$1.log" | tail -1)" >> results/sweeps_progress.txt
}
run ablation_width place_once,decision_flip
run ablation_screen place_once,decision_flip
run kappa place_once,decision_flip
run ablation_feasibility all
run sens_rho all
run sens_slack_base place_once,fixed_savings,decision_flip
run sens_k_slack place_once,fixed_savings,decision_flip
run sens_missing_gpu place_once,fixed_savings,decision_flip
run sens_phase_shift place_once,fixed_savings,decision_flip
run sens_lambda_ovh place_once,decision_flip
echo "ALL DONE $(date +%T)" >> results/sweeps_progress.txt
