# Handoff: start here

Current state of the work, for a teammate or a new Claude Code session. Keep it short and overwrite it as things change; history belongs in `decisions.md`.

**Last updated:** 27 Nov 2026 · **PRD version: 0.9.6**

## Phase 3 plan (27 Nov 2026, D66): review on 16 Dec

Scope, goals and dates are in PRD §18.2 "Scope and schedule". Everything runs locally (no AWS). Validation data only until any frozen final run.

| Stage | Dates | Work | Status |
|---|---|---|---|
| A | 27–29 Nov | Docs (done); overnight validation queue (`sens_rho`, `sens_slack_base`, `sens_k_slack`, `ablation_screen`, `ablation_width`); Holm statistics and effect sizes in `reporting.py`; load-scaling setup; ER-grid data go/no-go for region scaling | next |
| B | 30 Nov – 5 Dec | X10 (scikit-learn) built and compared on validation; load-scaling runs; P1 proof and Big‑O; region-scaling code if go; win/lose table | — |
| C | 6–13 Dec | Region-scaling runs; freeze in `decisions.md`; one figure script; demo polish ("why this job moved", guided flow); X13 if X10 done by 6 Dec; WP6 only with guide approval; rehearse demo twice plus backup recording; final cleanup and push | — |
| D | 14–15 Dec | Paperwork only: 14 Dec paper (IEEEtran) and EL report; 15 Dec slides and number check | — |

**For Stavan: long runs (A2, then B3).** These take hours, so run them on a machine that can stay on overnight. Validation only; never `--split test`.

1. `git pull`, then `uv sync`.
2. Goal 1 queue (A2, about 12–15 h; resumes if interrupted, since finished runs are reused):
   - Linux or Git Bash: `bash scripts/run_phase3_queue.sh`
   - Progress: `results/phase3_progress.txt`; logs in `results/sweeps_logs/`.
3. When it ends with `ALL DONE`, tell the team; the outputs are exported to `docs/` in Stage B.
4. Load-scaling timing runs (B3) come after A4 is merged: run nothing else on the machine at the same time, because they measure CPU time.

Rules for the runs: timing (scaling) runs use `--jobs 1` and never overlap other runs; about 6 GB RAM is free, so sampling 1.0 may not fit. Open: LaTeX tool (Overleaf or local `pdflatex`), WP6 approval from the guide.

## Done 24 Nov 2026: code cleanup merged into `main` and committed

Three cleanup agents (bugs, latency, redundancy) finished and their work is merged; worktrees removed. Outputs are byte-identical (33 `events.log`/`jobs.csv`/`decisions.csv` hashes checked), P1 holds, ruff clean, 282 tests pass.

- Simulation core: queue-wait profiles rebuilt with one sweep and checkpoints; `flipwise run` 1.6–2.2× faster (decision_flip dev week 82 s to 50 s).
- Live dashboard and services: `/status` 2,170 ms to 13 ms; skips no longer block the API; static files cached and gzipped (`webstatic.send_static`); Datacentres page now follows the policy picker; several POST and JSON-body bugs fixed; unused `tabler.min.js` dropped.
- CLI and scripts: `ingest india` default truth kind fixed (rebuilds the committed truth file); UTF-8 YAML reads for Windows; empty policy list fails early; shared `bootstrap_ci`; `scripts/rerun_power.sh` removed.

The three known issues listed then (KPI delta colour, Docker port subtitle, ignored sweep keys) were fixed and pushed.

Also pending from the Phase 2 review: see next step 5 below and `PROJECT_EXPLAINER.md` §17.

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
- **The test set has been run (12 Nov, D57, F21):** results in `docs/test_results/` (start with its README). **It is spent: never re-run `--split test`.** `decision_flip` is within noise of `place_once`, `fixed_savings`, `periodic` and `pred_error` on emissions (the validation lead over `place_once` did not repeat), is clearly below `fcfs`, and keeps its cost advantage over `fixed_savings` and `periodic` (54 % fewer re-scorings, 60 % fewer moves). State the claim with those limits.
- **Nothing left depends on the run logs:** test, sensitivity and ablation runs start fresh from `configs/policies.yaml`, and the `g_abs` and `κ` sweep values are already set (D48).
- **Deployment:** DT1 (local split) is complete: `dc-serve`, `--mode remote`, `local_cluster.sh` and `.ps1`, R-DEP-1/3/4/7 and overhead numbers (R-DEP-5, F18) all pass on Windows and Linux (Fedora, 11 Nov; 247 tests). The scripted driver (step 5) was dropped (D53). **DT2 Docker is built (11 Nov, D56, F20):** `Dockerfile`, `docker-compose.yml`, `.dockerignore`, and `scripts/docker_check.sh`, which passes R-DEP-1 (all seven policies on the toy), R-DEP-2 (dev week) and R-DEP-3 (a killed container) on Fedora. It also passed from a clean clone (11 Nov, F20). **Not done:** one run on a Windows laptop with Docker Desktop (the last DT2 exit item); DT3 AWS. Demo: `bash scripts/local_cluster.sh --scenario tests/fixtures/toy --policy decision_flip` (Linux/Git Bash) or `.\scripts\local_cluster.ps1 --scenario tests/fixtures/toy --policy decision_flip` (PowerShell); never run two copies of `tests/test_local_cluster.py` at once (same ports). Plotly dashboard charts are not built (optional; Matplotlib default is in place).

## Next steps

**Phase 3 plan: PRD §18.2 (D64), scope and dates fixed by D66 (see the top of this file).** Order: WP1 open sweeps and ablations (step 2 below) and WP2 rigor (P1 proof, complexity, Holm-corrected stats) together with WP3 scaling study; then WP4 X10 (step 4); WP5 X11 as stretch; WP6 the pre-registered final run (needs team and guide agreement first); WP7 paper. Every choice before WP6 uses validation data only.

1. **DT2 is done** (Linux, including a clean clone). The team waived the Windows/Docker Desktop run on 12 Nov; PowerShell commands stay documented but untested with Docker.
0a. **Live demo mode (D60): done and merged 12 Nov.** `uv run flipwise live --config configs/base.yaml`, dashboard at http://localhost:8100 (or `docker compose --profile live up --build dc-delhi dc-mumbai dc-chennai live`); demo script and page-by-page explanation in `docs/PROJECT_EXPLAINER.md` §10. Rehearse once on the presenting laptop. The algorithm alone is explained in §5 of the same file.
0b. **Docs consolidated (13 Nov):** `WALKTHROUGH.md`, `explanation.md`, `DECISION_FLIP.md`, `USAGE.md`, `DEMO.md`, `WEB_EXPLAINER.md`, `project_journey.md` and `helpfullinks.md` were replaced by one file, `docs/PROJECT_EXPLAINER.md`; a formatted copy (`Flipwise_Project_Explainer.docx` and `.pdf`, 38 pages) is kept outside the repo in the EL folder.
1a. **Re-measuring kgCO₂ (D59): done 12 Nov.** All 392 runs kept decisions byte-identical; the bracket tables are in `docs/power_bracket/` (F25). Quote kgCO₂ as measured–nameplate ranges from there.
2. **Ablations and sensitivity sweeps were started on 12 Nov and interrupted by a shutdown.** Resume with `bash scripts/run_ablations.sh` (validation split only; finished runs are reused; progress in `results/sweeps_progress.txt`; expect several hours). Sweep configs are in `configs/sweeps/` (`ablation_*.yaml`, `sens_*.yaml`, `kappa.yaml`). Not runnable without new code: σ spread scaling, region set {WR, SR, ER}, interval scaling, energy multipliers, α (needs forecasts rebuilt). When done: export with `scripts/export_validation.py --compare ... --sweep ... --out docs/ablations`, and record findings in `decisions.md`. Rest of roadmap phase 8: the sensitivity sweeps and ablations A0–A6 (PRD §14), on **validation** data, not the test split. Check which of A2–A6 already have config switches before starting (`screen` and `width` exist in `configs/policies.yaml`; A5 `feasibility = point` and A6 may not). Then roadmap phase 9: the report figures, limitations (including F21) and the reproducibility package.
3. Reproducing validation is optional: the commands are below and take about 6 hours with 5 jobs on 8 threads. Check the results against `docs/validation/runs.csv`.
   ```bash
   uv run flipwise compare --config configs/base.yaml --split validation --policies all --jobs 5
   uv run flipwise sweep --config configs/base.yaml --sweep configs/sweeps/theta.yaml --split validation --policies place_once,decision_flip --jobs 5
   uv run flipwise sweep --config configs/base.yaml --sweep configs/sweeps/w_max.yaml --split validation --policies place_once,decision_flip --jobs 5
   uv run flipwise sweep --config configs/base.yaml --sweep configs/sweeps/g_rel_decision_flip.yaml --split validation --policies place_once,decision_flip --jobs 5
   uv run flipwise sweep --config configs/base.yaml --sweep configs/sweeps/g_rel.yaml --split validation --policies place_once,fixed_savings --jobs 5
   uv run flipwise sweep --config configs/base.yaml --sweep configs/sweeps/periodic_t.yaml --split validation --policies place_once,periodic --jobs 5
   uv run flipwise sweep --config configs/base.yaml --sweep configs/sweeps/pred_error_eps.yaml --split validation --policies place_once,pred_error --jobs 5
   ```
To rebuild the review outputs: `uv run flipwise compare --config configs/base.yaml --jobs 7`, `uv run flipwise sweep --config configs/base.yaml --sweep configs/sweeps/theta.yaml --policies fcfs,place_once,fixed_savings,decision_flip --jobs 4`, then `uv run flipwise dashboard --runs results/compare_<hash> --sweep results/sweep_<hash>`. Finished runs are reused; a dev week takes about 8 minutes with 7 jobs.

4. **Phase 3, machine learning (D61; WP4 and WP5 of PRD 18.2):** after WP1, add learned runtime quantiles (X10) as an input to the same rules, then a learned Indian carbon forecaster (X11); an advisory learned trigger (X12) only as an ablation. Needs a PRD 12.1 edit to admit one ML library first.

5. **Phase 2 review follow-ups (24 Nov, D63).** The guide's feedback and our answers (formula and parameter justification, complexity and CPU-time comparison) are in `docs/PROJECT_EXPLAINER.md` §17. Still open, all on **validation** data only:
   - **Done 24 Nov (F26):** `max_moves` {1, 3, 10} and `cooldown_s` {1,800, 7,200} swept on validation (`configs/sweeps/max_moves_<policy>.yaml`, `cooldown_<policy>.yaml`, one file per policy because a grid key names one policy; `bash scripts/run_throttle_sweeps.sh`). All within noise of the defaults. P1 holds only at `cooldown_s` = 1,800 (PRD §10).
   - Run the ρ and slack sensitivity sweeps (`configs/sweeps/sens_rho.yaml`, `sens_slack_base.yaml`, `sens_k_slack.yaml`).
   - Add the complexity and CPU-time tables (§17.4, §17.5) and the parameter table (§17.3) to the Phase 2/3 slides.
   - Redraw the architecture diagram with labels (§17.6): numbered blocks, labelled arrows, a dashed information-boundary box, a legend.
   - When the sweeps finish, update §17.3 and remove the "open" marks.

## Waiting on a decision

The four post-freeze questions were answered on 10 Nov (D49–D52 in `decisions.md`). What remains:

| Item | Question | Who |
|---|---|---|
| B1 | Does the mentor confirm the scope, including the v0.8 method changes? | Mentor |
| B3 | Mostly resolved (12 Nov, D58): kgCO2 is a bracket, `measured` to `nameplate`. Still open: a CPU model for the PAI machines (10 W per core assumed). `docs/validation/` and `docs/test_results/` still hold the old relative kgCO2; their decisions are unchanged (verified on the dev week), so only the kgCO2 needs recomputing | Team |

## Things that will catch you out

- **Data:** only `data/processed/` exists here; `data/raw/` is gone. Checksums match the manifests, and `flipwise validate` passes.
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
