# Handoff: start here

Current state of the work, for a teammate or a new Claude Code session. Keep it short and overwrite it as things change; history belongs in `decisions.md` and `project_journey.md`.

**Last updated:** 5 Nov 2026 · **PRD version: 0.8.8**

**First-time setup (optional, for the graph):** `uv tool install graphifyy`, then `uv tool run --from graphifyy python scripts/build_graph.py`. Open `graphify-out/graph.html` in a browser to explore. The output is generated and not committed. The project's Claude Code hooks call `graphify`, so install it if you use Claude Code here.

## Read in this order

1. This file.
2. `CLAUDE.md`: rules that must not break, and commands.
3. `docs/decisions.md`: what was decided and why, by phase.
4. The PRD section you need; `CLAUDE.md` shows how to find it without reading the whole file.

To explore the code, use `graphify query "<question>"` if the graph is built.

## Where we are

- **Done:** build phases 1–7. All seven policies run on the toy (hand-checked in `expected.yaml`) and on the real dev week. P1 holds on real data (F8). `compare`, `sweep`, `report` and `dashboard` work, and their exit criterion is met on both.
- **First results:** PRD §10.11 has the seven-policy table and the θ sweep for one week, so no ranking follows from them.
- **Validation is done and thresholds are frozen (D47, PRD §14.5):** 12 replicates at sampling 0.1, 300 runs. Everything from those runs is in `docs/validation/` (start with its README), and findings are in F12–F15. The test set has not been run.
- **Nothing left depends on the run logs:** test, sensitivity and ablation runs start fresh from `configs/policies.yaml`, and the `g_abs` and `κ` sweep values are already set (D48).
- **Deployment:** `flipwise run --mode remote` works (step 7; the scripted driver, step 5, was dropped, D53). `scripts/local_cluster.sh` and `local_cluster.ps1` are built (step 6, D54) and work by hand, including the crash case (F16). **Open:** the PowerShell crash test timed out once (F16); overhead numbers (R-DEP-5); then Docker. Plotly dashboard charts are also not built: the optional extra would add hover, and the Matplotlib default is in place.

## Next steps

0. **Local split status (10 Nov, evening):** the PowerShell clean-up bug behind F16 is fixed (F17); all 6 script tests pass on Windows. Overhead is recorded in every `manifest.json` (D55); first numbers in F18 (about 5.5 ms per HTTP call). **Still to do:** re-run `decision_flip` through `local_cluster` on the dev week and check its hashes match the in-process run; then Docker (needs Docker Desktop installed). *(11 Nov, Fedora: the script tests now pass on Linux. They had failed only because a plain `bind()` is refused while the closed connections sit in TIME_WAIT; the port checks in the test and in `local_cluster.sh` now set `SO_REUSEADDR` off Windows, the same rule as `dcservice._Server`.)* The older note follows.
   **Earlier note (10 Nov, afternoon):** on a clean machine (no `dc-serve` running: check with `Get-CimInstance Win32_Process | ? CommandLine -match dc-serve`), run `uv run pytest -q "tests/test_local_cluster.py::test_a_crashed_service_aborts_the_run_cleanly_r_dep_3"` and find why it timed out once; never run two copies of `test_local_cluster.py` at once (they pick the same ports). Run the tests on Linux too. Then R-DEP-5 overhead numbers, then Docker (D52). Demo: `bash scripts/local_cluster.sh --scenario tests/fixtures/toy --policy decision_flip` or `.\scripts\local_cluster.ps1 --scenario tests/fixtures/toy --policy decision_flip`.

1. Rest of roadmap phase 8, with thresholds now frozen: run the test set **once** (`--split test`), then the sensitivity sweeps and ablations A0–A6. Settle F9 first, because changing `w_max` afterwards would mean re-tuning on validation and a test run that no longer counts as once.
2. Reproducing validation is optional: the commands are below and take about 6 hours with 5 jobs on 8 threads. Check the results against `docs/validation/runs.csv`.
   ```bash
   uv run flipwise compare --config configs/base.yaml --split validation --policies all --jobs 5
   uv run flipwise sweep --config configs/base.yaml --sweep configs/sweeps/theta.yaml --split validation --policies place_once,decision_flip --jobs 5
   uv run flipwise sweep --config configs/base.yaml --sweep configs/sweeps/w_max.yaml --split validation --policies place_once,decision_flip --jobs 5
   uv run flipwise sweep --config configs/base.yaml --sweep configs/sweeps/g_rel_decision_flip.yaml --split validation --policies place_once,decision_flip --jobs 5
   uv run flipwise sweep --config configs/base.yaml --sweep configs/sweeps/g_rel.yaml --split validation --policies place_once,fixed_savings --jobs 5
   uv run flipwise sweep --config configs/base.yaml --sweep configs/sweeps/periodic_t.yaml --split validation --policies place_once,periodic --jobs 5
   uv run flipwise sweep --config configs/base.yaml --sweep configs/sweeps/pred_error_eps.yaml --split validation --policies place_once,pred_error --jobs 5
   ```
3. Deployment step 5 (scripted driver), then `local_cluster.sh` and `flipwise run --mode remote`. Step 4 is done: `flipwise dc-serve` and `HttpDatacentre` pass R-DEP-4 and R-DEP-7, and every policy on the toy is already byte-identical over HTTP with services in threads.

To rebuild the review outputs: `uv run flipwise compare --config configs/base.yaml --jobs 7`, `uv run flipwise sweep --config configs/base.yaml --sweep configs/sweeps/theta.yaml --policies fcfs,place_once,fixed_savings,decision_flip --jobs 4`, then `uv run flipwise dashboard --runs results/compare_<hash> --sweep results/sweep_<hash>`. Finished runs are reused; a dev week takes about 8 minutes with 7 jobs.

## Waiting on a decision

Rohith has the open questions, with evidence and recommendations, in `docs/questions_for_rohith.md`.

| Item | Question | Who |
|---|---|---|
| B1 | Does the mentor confirm the scope, including the v0.8 method changes? | Mentor |
| B3 | Cited power values; until then kgCO2 is relative | Team |

## Things that will catch you out

- **Data:** only `data/processed/` exists here; `data/raw/` is gone. Checksums match the manifests, and `flipwise validate` passes.
- **`docs/design_phases_5_7.md` is design notes, not the spec.** It lists where PRD v0.8 differs from it. Where they disagree, follow the PRD.
- **Trace days count from 1970-01-01 UTC+8**, so day 25 is a Monday and the first job arrives on day 6.6.
- **Results in `results/` are reused by `run_id`, which does not cover code.** After changing simulator, planner or policy code, delete `results/` or the old runs come back as if current. Check `git.commit` in a run's `manifest.json`.
- **A real `fixed_savings` week takes about 8 minutes.** Most of it is rebuilding wait profiles, which is why the screen matters.
- **Single-week emissions totals are noisy** because of F4. Don't draw conclusions from one replicate.
- **`g_rel` differs by policy:** `fixed_savings` is 0.01 and `decision_flip` 0.05. P1 and ablation A1 need the same `g_*` on both; `scripts/check_p1.py` already does this.
- **Tuning:** never tune thresholds on test-period data (trace days 46–73, carbon from 1 Sep 2023).

## Ending a session

1. Update this file: where we are, next steps, anything newly confusing.
2. Add any new decision or finding to `decisions.md`, and change the PRD in the same commit if the design changed.
3. Run `graphify update .` if the graph is in use.
