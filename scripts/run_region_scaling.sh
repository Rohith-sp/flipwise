#!/usr/bin/env bash
# Region scaling (PRD 18.2 goal 2b, D66): the same validation compare at 3 and at 5 datacentres.
# Total cluster capacity is fixed and split over the sites (per-site capacity 3/5 at 5 sites).
# Validation only; --jobs 1 because scheduler CPU time is compared: run nothing else meanwhile.
# Resumable (finished runs are reused). Env: REPS=2. Progress: results/region_scaling_progress.txt.
set -u
cd "$(dirname "$0")/.." || exit 1
REPS=${REPS:-2}
LOG=results/region_scaling_progress.txt
mkdir -p results
note() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }
if [ ! -f data/processed/carbon_forecast_5dc.csv ]; then
  note "building 5-site forecast (about 1 min; carbon_forecast.csv is not changed)"
  uv run flipwise build-forecasts --config configs/regions5.yaml || exit 1
fi
for cfg in base regions5; do
  note "START $cfg"
  uv run flipwise compare --config "configs/$cfg.yaml" --split validation \
    --policies place_once,fixed_savings,periodic,decision_flip --replicates "$REPS" --jobs 1 \
    2>&1 | tail -3 | tee -a "$LOG"
  note "DONE $cfg exit=${PIPESTATUS[0]}"
done
