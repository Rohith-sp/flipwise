# Open questions for Rohith

Validation is finished and thresholds are frozen (PRD v0.8.6). These decisions are yours now. **You don't need the run logs:** everything from the 300 runs is in `docs/validation/` (start with its README), and findings are in `docs/decisions.md` (F9, F12–F15, D46–D48) and PRD §14.5. All figures are from 12 validation replicates at job sampling 0.1, and kgCO2 is relative until B3 is resolved.

Please settle question 1 before running the test set. Record each answer in `docs/decisions.md`, and in the PRD if the design changes.

## 1. Do we accept `INTERVAL_TOO_WIDE` above its 10 % flag? (before the test run)

At the frozen `w_max` = 2, θ is switched off on 28.4 % of `decision_flip`'s comparisons, and all 12 replicates are above the flag.

| `w_max` (θ = 0.1) | Fallback share | Replicates flagged | kgCO2 |
|---|---|---|---|
| 2 | 28.4 % | 12 of 12 | 14,008 |
| 3 | 17.3 % | 12 of 12 | 14,040 |
| 5 | 9.6 % | 4 of 12 | 14,079 |

Widening clears the flag on average but doesn't lower emissions. The gaps between these settings are within noise (2 vs 3: −32 kg, CI −81 to +14; 2 vs 5: −71 kg, CI −204 to +70). At `w_max` = 2, 68 % of moves are made with θ off, so θ has no say in most moves; the report should say so. Curves: `docs/validation/figures/sweep_decision_flip_theta_w_max.png`.

- **A (recommended):** keep 2, accept the flag, and report the fallback share with the results. Nothing needs re-running.
- **B:** raise `w_max` to 5, so θ is active more often. The §14.5 rule doesn't pick this, so we would have to record why we overrode it.

Changing `w_max` after the test run would mean tuning after seeing test results, so this has to be decided first.

## 2. When do we run the test set, and at what sampling?

The PRD allows one run only, after the freeze (§14.5), and it hasn't been run. `configs/base.yaml` has it at sampling 0.1 (D46). The final 1.0 is about 10× the jobs and was judged too slow for a laptop.

Recommended: stay at 0.1 and say so in the report. Use 1.0 only if we get a bigger machine. Choose before running, since the one run is the claim.

## 3. How should the report state the claim?

`decision_flip` is clearly better than `place_once` (−146 kg, CI −234 to −60), but it can't be told apart on emissions from the other re-planners:

| Compared with | Difference | 95 % CI |
|---|---|---|
| `fixed_savings` | −24 kg | −103 to +59 |
| `periodic` | −49 kg | −101 to +10 |
| `pred_error` | −69 kg | −165 to +38 |

Its measured advantage is cost: 58 % fewer full re-scorings and 61 % fewer moves than `fixed_savings`.

Recommended: claim "about the same carbon at much lower re-planning cost", not "lowest emissions". Does this fit what the mentor expects (B1)?

## 4. What comes first for the Phase 2 review?

The local-split demo isn't ready: deployment steps 5–7 are missing (scripted driver, `local_cluster.sh`, `--mode remote`). Step 4 is done. The rest of build phase 8 (test set, sensitivity sweeps, ablations A0–A6) is also open.

Recommended: deployment steps 5–7 first, since the review expects the demo. What is the review date, and is that order right?

## Good to know

- **You won't get the run logs, and don't need them.** They are 2.5 GB and stay on Stavan's laptop. Test, sensitivity and ablation runs start fresh, and `configs/sweeps/g_abs.yaml` and `kappa.yaml` already hold the values derived from validation. Re-running validation is optional (`docs/HANDOFF.md`).
- **You do need `data/processed/` (243 MB, not in git)** for any real run, including the test set. If you don't have it, tell Stavan or rebuild it with the steps in `data/README.md`.
- **Sweep curves are done:** all six are in `docs/validation/figures/sweep_*.png`, as §14.5 asks. They show cheaper settings the single frozen value hides: `periodic` at 7,200 s is 10 kg behind 1,800 s (CI −85 to +103) with a quarter of the re-scorings.
- **`g_rel` differs by policy:** `fixed_savings` is 0.01 and `decision_flip` is 0.05. P1 and ablation A1 must set the same value on both.
- **Sweeps weren't a full grid:** θ and `w_max` were swept at `g_rel` = 0.05, and `g_rel` at θ = 0.1, `w_max` = 2.
- **Figures are validation only.** Don't present them as the final result until the test set has run.
- **Also still open:** B1 (mentor confirms scope) and B3 (power values).
