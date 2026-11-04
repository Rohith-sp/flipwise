# Handoff: start here

Current state of the work, for a teammate or a new Claude Code session. Keep it short and overwrite it as things change; history belongs in `decisions.md` and `project_journey.md`.

**Last updated:** 4 Nov 2026 · **PRD version: 0.8.2**

**First-time setup (optional, for the graph):** `uv tool install graphifyy`, then `uv tool run --from graphifyy python scripts/build_graph.py`. Open `graphify-out/graph.html` in a browser to explore. The output is generated and not committed. The project's Claude Code hooks call `graphify`, so install it if you use Claude Code here.

## Read in this order

1. This file.
2. `CLAUDE.md`: rules that must not break, and commands.
3. `docs/decisions.md`: what was decided and why, by phase.
4. The PRD section you need; `CLAUDE.md` shows how to find it without reading the whole file.

To explore the code, use `graphify query "<question>"` if the graph is built.

## Where we are

- **Done:** build phases 1–4, and the groundwork for phase 5: scenario builder, `flipwise run --config`, runtime and residual fitting, scoring prefix sums, and simulator hooks.
- **Runs today:** `fcfs` and `place_once` on the toy and on the dev replicate (trace days 25–31, carbon Monday 3 Jul 2023, 10 % sampling).
- **Not built yet:** `rescore`, rescue, throttling, `periodic`, `fixed_savings`, decision-flip, metrics, dashboard, and deployment steps 4 onward.

## Next steps

1. Decide D37 and D38 below.
2. Finish phase 5: `planner.rescore`, `best_alternative`, rescue with the D28 limits, throttling, `FixedSavings`, `Periodic`, and `PolicyStats`. Build order and tests are in `design_phases_5_7.md` §3 and §6.
3. Check the deadline misses (F5). This is part of phase 5's exit criterion.
4. Phase 6: lower bound, screen, paired width. Prove P1 on the toy and on the dev replicate.

## Waiting on a decision

| Item | Question | Who |
|---|---|---|
| D37, D38 | Add both to the PRD? They were approved in review but left out of v0.8 | Team |
| B1 | Does the mentor confirm the scope, including the v0.8 method changes? | Mentor |
| B3 | Cited power values; until then kgCO2 is relative | Team |

## Things that will catch you out

- **Data:** only `data/processed/` exists here; `data/raw/` is gone. Checksums match the manifests, and `flipwise validate` passes.
- **`docs/design_phases_5_7.md` is design notes, not the spec.** It lists where PRD v0.8 differs from it. Where they disagree, follow the PRD.
- **`prd (1).md` in the repo root**, if you see it, is an old v0.3 copy. Ignore it.
- **Trace days count from 1970-01-01 UTC+8**, so day 25 is a Monday and the first job arrives on day 6.6.
- **Single-week emissions totals are noisy** because of F4. Don't draw conclusions from one replicate.
- **Tuning:** never tune thresholds on test-period data (trace days 46–73, carbon from 1 Sep 2023).

## Ending a session

1. Update this file: where we are, next steps, anything newly confusing.
2. Add any new decision or finding to `decisions.md`, and change the PRD in the same commit if the design changed.
3. Run `graphify update .` if the graph is in use.
