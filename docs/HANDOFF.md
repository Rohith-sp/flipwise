# Handoff: start here

Current state of the work, for a teammate or a new Claude Code session. Keep it short and overwrite it as things change; history belongs in `decisions.md` and `project_journey.md`.

**Last updated:** 4 Nov 2026 · **PRD version: 0.8.5**

**First-time setup (optional, for the graph):** `uv tool install graphifyy`, then `uv tool run --from graphifyy python scripts/build_graph.py`. Open `graphify-out/graph.html` in a browser to explore. The output is generated and not committed. The project's Claude Code hooks call `graphify`, so install it if you use Claude Code here.

## Read in this order

1. This file.
2. `CLAUDE.md`: rules that must not break, and commands.
3. `docs/decisions.md`: what was decided and why, by phase.
4. The PRD section you need; `CLAUDE.md` shows how to find it without reading the whole file.

To explore the code, use `graphify query "<question>"` if the graph is built.

## Where we are

- **Done:** build phases 1–7. All seven policies run on the toy (hand-checked in `expected.yaml`) and on the real dev week. P1 holds on real data (F8). `compare`, `sweep`, `report` and `dashboard` work, and their exit criterion is met on both.
- **First results:** PRD §10.11 has the seven-policy table and the θ sweep. They are one week, so no ranking follows from them.
- **Not built yet:** deployment steps 4 onward. Plotly dashboard charts are also not built: the optional extra would add hover, and the Matplotlib default is in place.

## Next steps

1. Roadmap phase 8: `uv run flipwise compare --config configs/base.yaml --split validation --jobs 5` (12 replicates at sampling 0.1, D46), then the sweeps in `configs/sweeps/`, then `scripts/select_thresholds.py` (PRD §14.5).
2. Look at F9 across those replicates before touching `w_max`.
3. Deployment step 4 (`dcservice.py`), then the scripted driver and `local_cluster.sh`.

To rebuild the review outputs: `uv run flipwise compare --config configs/base.yaml --jobs 7`, `uv run flipwise sweep --config configs/base.yaml --sweep configs/sweeps/theta.yaml --policies fcfs,place_once,fixed_savings,decision_flip --jobs 4`, then `uv run flipwise dashboard --runs results/compare_<hash> --sweep results/sweep_<hash>`. Finished runs are reused; a dev week takes about 8 minutes with 7 jobs.

## Waiting on a decision

| Item | Question | Who |
|---|---|---|
| F9 | `INTERVAL_TOO_WIDE` is above its 10 % flag. Is `w_max` worth revisiting on validation? | Team |
| B1 | Does the mentor confirm the scope, including the v0.8 method changes? | Mentor |
| B3 | Cited power values; until then kgCO2 is relative | Team |

## Things that will catch you out

- **Data:** only `data/processed/` exists here; `data/raw/` is gone. Checksums match the manifests, and `flipwise validate` passes.
- **`docs/design_phases_5_7.md` is design notes, not the spec.** It lists where PRD v0.8 differs from it. Where they disagree, follow the PRD.
- **Trace days count from 1970-01-01 UTC+8**, so day 25 is a Monday and the first job arrives on day 6.6.
- **Results in `results/` are reused by `run_id`, which does not cover code.** After changing simulator, planner or policy code, delete `results/` or the old runs come back as if current. Check `git.commit` in a run's `manifest.json`.
- **A real `fixed_savings` week takes about 8 minutes.** Most of it is rebuilding wait profiles, which is why the screen matters.
- **Single-week emissions totals are noisy** because of F4. Don't draw conclusions from one replicate.
- **Tuning:** never tune thresholds on test-period data (trace days 46–73, carbon from 1 Sep 2023).

## Ending a session

1. Update this file: where we are, next steps, anything newly confusing.
2. Add any new decision or finding to `decisions.md`, and change the PRD in the same commit if the design changed.
3. Run `graphify update .` if the graph is in use.
