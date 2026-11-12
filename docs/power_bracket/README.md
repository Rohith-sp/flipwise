# kgCO₂ under the D58 power bracket (D59)

Validation (12 replicates) and test (16 replicates) re-run with the D58 power model in both evaluator modes, on 12 Nov 2026. The scheduler kept its fixed scoring scale, so every run's `decisions.csv` is byte-identical to the frozen runs: validation 84 of 84 in each mode, test 112 of 112 in each mode (compared with `docs/validation/runs.csv` and the 12 Nov test run). Only kgCO₂ changed.

- `measured`: datasheet GPU power × each job's measured GPU use (Alibaba `pai_sensor_table`) + measured cores × 10 W. A lower bound: idle GPU draw is left out.
- `nameplate`: requested GPUs at datasheet power + requested cores × 10 W. An upper bound.

`bracket.csv` has, per split, mode and policy: mean kgCO₂, energy and intensity per replicate, and the paired difference from `place_once` with its 95 % bootstrap CI. `<split>_<mode>_summary.csv` and `_paired.csv` are the per-replicate tables.

## Test set (16 replicates), kgCO₂ per replicate

| Policy | measured | nameplate | vs place_once, measured (95 % CI) | vs place_once, nameplate (95 % CI) |
|---|---|---|---|---|
| decision_flip | 3,853 | 11,862 | −20 (−73 to +26) | −40 (−111 to +25) |
| fixed_savings | 3,865 | 11,885 | −9 (−49 to +27) | −18 (−53 to +17) |
| periodic | 3,871 | 11,862 | −3 (−54 to +46) | −40 (−108 to +26) |
| pred_error | 3,856 | 11,904 | −18 (−74 to +39) | +1 (−80 to +77) |
| place_once | 3,873 | 11,902 | — | — |
| pig (oracle) | 3,863 | 11,767 | −11 (−68 to +43) | −135 (−228 to −46) |
| fcfs | 3,980 | 12,160 | +106 (+75 to +137) | +257 (+181 to +331) |

Reading: the claim of F21 holds at both ends of the bracket. decision_flip cannot be told apart on carbon from the other re-planners or from `place_once`, and is clearly below `fcfs`. Under `measured` the oracle `pig` is not the lowest, because it plans with the scheduler's uniform power scale while the evaluator weights jobs by how hard they used their GPUs.
