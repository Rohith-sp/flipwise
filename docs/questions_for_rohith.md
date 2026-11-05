# Open questions for Rohith

Validation is finished and thresholds are frozen (PRD v0.8.6). These decisions are yours now. The evidence is in `docs/decisions.md` (F9, F12–F14, D46, D47) and PRD §14.5. All figures are from 12 validation replicates at job sampling 0.1, and kgCO2 is relative until B3 is resolved.

Please settle question 1 before running the test set. Record each answer in `docs/decisions.md`, and in the PRD if the design changes.

## 1. Do we accept `INTERVAL_TOO_WIDE` above its 10 % flag? (before the test run)

At the frozen `w_max` = 2, θ is switched off on 28.4 % of `decision_flip`'s comparisons, and all 12 replicates are above the flag.

| `w_max` (θ = 0.1) | Fallback share | Replicates flagged | kgCO2 |
|---|---|---|---|
| 2 | 28.4 % | 12 of 12 | 14,008 |
| 3 | 17.3 % | 12 of 12 | 14,040 |
| 5 | 9.6 % | 4 of 12 | 14,079 |

Widening clears the flag on average but doesn't lower emissions. The gaps between these settings are within noise (2 vs 5: −71 kg, CI −206 to +71).

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
| `fixed_savings` | −24 kg | −101 to +58 |
| `periodic` | −49 kg | −100 to +9 |
| `pred_error` | −69 kg | −166 to +36 |

Its measured advantage is cost: 58 % fewer full re-scorings and 61 % fewer moves than `fixed_savings`.

Recommended: claim "about the same carbon at much lower re-planning cost", not "lowest emissions". Does this fit what the mentor expects (B1)?

## 4. What comes first for the Phase 2 review?

The local-split demo isn't ready: deployment steps 5–7 are missing (scripted driver, `local_cluster.sh`, `--mode remote`). Step 4 is done. The rest of build phase 8 (test set, sensitivity sweeps, ablations A0–A6) is also open.

Recommended: deployment steps 5–7 first, since the review expects the demo. What is the review date, and is that order right?

## 5. Which sweep curves go in the report?

§14.5 asks for the validation sweep curves (emissions vs `stage2_calls`, emissions vs moves). The dashboard takes one sweep per build, so only the `theta` curves have been drawn. They matter for `periodic` in particular: `T` = 7,200 s is only 10 kg behind 1,800 s with a quarter of the re-scorings, which a single frozen value hides.

Should all the sweeps be drawn (dashboard change or separate script), or is `theta` plus a table enough?

## Good to know

- **Saved runs aren't in git.** The 300 runs (2.5 GB in `results/`) are only on Stavan's laptop. Reproducing them takes about 6 hours with 5 jobs on 8 threads; the commands are in `docs/HANDOFF.md`. Ask Stavan for a copy if you'd rather not re-run. The numbers themselves are in F12–F14 and PRD §14.5.
- **`g_rel` differs by policy:** `fixed_savings` is 0.01 and `decision_flip` is 0.05. P1 and ablation A1 must set the same value on both.
- **Sweeps weren't a full grid:** θ and `w_max` were swept at `g_rel` = 0.05, and `g_rel` at θ = 0.1, `w_max` = 2.
- **Also still open:** B1 (mentor confirms scope) and B3 (power values).
