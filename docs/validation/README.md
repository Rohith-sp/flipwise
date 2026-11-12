# Validation results (PRD v0.8.7)

Everything from the 300 validation runs that other work depends on, small enough for git. The full logs (2.5 GB in `results/`) are not committed and **you don't need them**: test, sensitivity and ablation runs all start fresh from the frozen `configs/policies.yaml`.

All runs: 12 replicates (3 trace weeks × 4 carbon Mondays), job sampling 0.1, commit `b669c70`. kgCO2 is relative until B3 is resolved. Validation only, so none of this is the final claim. Findings are in `docs/decisions.md` (F12–F15, D47, D48).

## Files

| File | What it holds | Use it for |
|---|---|---|
| `dashboard.html` | Timeline, Pareto, results table, θ sweep | Phase 2 review; opens with no server |
| `summary.csv` | Every metric, per replicate and policy, at the frozen settings | Report tables |
| `paired.csv` | Each policy against `place_once`, with 95 % CI | Main comparison |
| `pairwise.csv` | `decision_flip` against every other policy, with 95 % CI | The claim (D51 in `docs/decisions.md`) |
| `sweep_means.csv` | Each swept setting: means, miss limit, gap to frozen with 95 % CI | Threshold choices |
| `sweep_replicates.csv` | The same settings, per replicate | Any other test on sweeps |
| `figures/sweep_*.png` | Emissions against re-scorings and moves, per sweep (PRD §14.5) | Report |
| `figures/*.png` (others) | Policy-level charts and carbon coverage | Report |
| `diagnostics.csv` | From the logs: energy concentration, who misses and why, `w_ab / Ŝ_a`, moves with θ off | Risks and limitations |
| `decision_counts.csv` | Every decision and reason count | Any other count |
| `carbon_coverage.csv` | Carbon interval coverage per lead bucket | Interval coverage report (phase 8 exit) |
| `p1.csv` | P1 on each replicate | Core claim (R-TRIG-2) |
| `score_scale.json` | Median Ŝ and the `g_abs` and `κ` values derived from it (PRD §10.10) | `configs/sweeps/g_abs.yaml`, `kappa.yaml` |
| `runs.csv` | Every run: settings, wall-clock time, SHA-256 of its outputs | Checking a re-run |

## Headline numbers

| Policy (frozen) | kgCO2 | g/kWh | g/kWh, jobs within `r_q90` | Miss rate | Full re-scorings | Moves |
|---|---|---|---|---|---|---|
| `pig` (oracle) | 13,896 | 616.3 | 534.1 | 2.64 % | 0 | 0 |
| `decision_flip` | 14,008 | 622.7 | 610.2 | 4.17 % | 16,933 | 2,289 |
| `fixed_savings` | 14,032 | 623.8 | 609.0 | 4.26 % | 39,969 | 5,938 |
| `periodic` | 14,057 | 625.1 | 613.0 | 4.16 % | 37,966 | 6,343 |
| `pred_error` | 14,077 | 625.6 | 615.1 | 4.15 % | 15,684 | 4,569 |
| `place_once` | 14,155 | 629.6 | 617.2 | 4.09 % | 0 | 0 |
| `fcfs` | 14,169 | 631.1 | 630.0 | 2.07 % | 0 | 0 |

CIs differ by a kg or two between `paired.csv` and `pairwise.csv`, because each bootstrap draws its own resamples. Quote the difference from `place_once` from `paired.csv`, and the others from `pairwise.csv`.

## Checking a re-run

A run's `run_id` and SHA-256 are in `runs.csv`. The same config, seed and data should reproduce them (R-SIM-1), so compare `manifest.json` → `output_sha256` in a new run against that row. They were produced on one Linux machine and haven't been compared across machines or operating systems, so a mismatch on another machine is a finding to look into, not automatically a bug.

## Regenerating

With the runs in `results/`, from the repo root:

```bash
uv run python scripts/export_validation.py --compare results/compare_e02ae64d6283 --sweep results/sweep_213b86182fd7 --sweep results/sweep_482125981f21 --sweep results/sweep_0eabcb0219a1 --sweep results/sweep_13bb4721a592 --sweep results/sweep_b775c64a4d24 --sweep results/sweep_1375e534b388 --out docs/validation
```

Those hashes depend on the config; after a fresh run, use the folders it prints.
