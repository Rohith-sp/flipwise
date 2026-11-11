# Test-set results (PRD v0.9)

The one test-set run the PRD allows (§14.5, D50), made on 11–12 Nov 2026 with commit `6cf8b8a` and a clean working tree: `flipwise compare --config configs/base.yaml --split test --policies all --jobs 5`. Frozen thresholds from `configs/policies.yaml`, job sampling 0.1, 4 trace weeks (days 46, 53, 60, 67) × 4 carbon Mondays = 16 replicates, 7 policies, 112 runs, all completed. The full logs (`results/compare_51565ad2804f`) are not committed.

**This run is spent.** Do not re-run the test split to try a different setting; that would be tuning on test data (PRD §14.3). kgCO2 is relative until B3 is resolved.

Files have the same meaning as in `docs/validation/README.md`: `summary.csv`, `paired.csv` (each policy against `place_once`, 95 % bootstrap CI), `pairwise.csv` (`decision_flip` against every other policy), `diagnostics.csv`, `decision_counts.csv`, `carbon_coverage.csv`, `runs.csv` (run ids and SHA-256 of outputs), `dashboard.html` and `figures/`. The θ-sweep tab of the dashboard is empty: no sweeps were run on the test set.

## Headline (means over 16 replicates)

| Policy | kgCO2 | Miss rate | Full re-scorings | Moves |
|---|---|---|---|---|
| `pig` (oracle) | 15,858 | 3.03 % | 0 | 0 |
| `periodic` | 16,045 | 4.00 % | 43,392 | 6,337 |
| `decision_flip` | 16,055 | 4.13 % | 20,035 | 2,359 |
| `fixed_savings` | 16,079 | 4.14 % | 43,540 | 5,897 |
| `pred_error` | 16,109 | 4.02 % | 14,944 | 4,122 |
| `place_once` | 16,110 | 3.95 % | 0 | 0 |
| `fcfs` | 16,482 | 2.13 % | 0 | 0 |

## What it supports (`decision_flip` minus other, kgCO2, 95 % CI)

| Against | Difference | CI | Reading |
|---|---|---|---|
| `fcfs` | −427 | −545 to −309 | Clearly lower |
| `place_once` | −55 | −128 to +12 | Not distinguishable (validation: −146, clearly lower) |
| `fixed_savings` | −24 | −83 to +31 | Not distinguishable |
| `periodic` | +10 | −59 to +78 | Not distinguishable |
| `pred_error` | −54 | −128 to +14 | Not distinguishable |
| `pig` | +196 | +146 to +245 | Oracle is clearly lower |

**Cost.** Against `fixed_savings`, `decision_flip` makes 54 % fewer full re-scorings (20,035 against 43,540) and 60 % fewer moves (2,359 against 5,897); against `periodic`, 54 % and 63 % fewer. Against `pred_error` it makes **more** full re-scorings (+5,091, CI +4,471 to +5,661) but fewer moves (−1,763).

**Not better than the simple baselines on carbon.** The validation advantage over `place_once` did not repeat on the test set: the difference shrank from −146 kg to −55 kg and its CI now includes zero.

**Deadlines.** `decision_flip` misses 4.13 % against 3.95 % for `place_once` (+0.2 points, CI +0.1 to +0.3) and 2.13 % for `fcfs`. 93 % of its misses are jobs that outran their 90th-percentile runtime estimate.

**Noise margin.** θ was switched off on 23.4 % of comparisons (`INTERVAL_TOO_WIDE`, above its 10 % flag) and on 59.6 % of moves.

**Interval coverage** for carbon by lead bucket was 88.8, 88.7, 88.5 and 86.7 % against a nominal 90 %.
