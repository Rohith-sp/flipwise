# Handoff: start here

Current state of the work, for a teammate or a new Claude Code session. Keep it short and overwrite it as things change; history belongs in `decisions.md` and `project_journey.md`.

**Last updated:** 4 Nov 2026 · **PRD version: 0.8.3**

**First-time setup (optional, for the graph):** `uv tool install graphifyy`, then `uv tool run --from graphifyy python scripts/build_graph.py`. Open `graphify-out/graph.html` in a browser to explore. The output is generated and not committed. The project's Claude Code hooks call `graphify`, so install it if you use Claude Code here.

## Read in this order

1. This file.
2. `CLAUDE.md`: rules that must not break, and commands.
3. `docs/decisions.md`: what was decided and why, by phase.
4. The PRD section you need; `CLAUDE.md` shows how to find it without reading the whole file.

To explore the code, use `graphify query "<question>"` if the graph is built.

## Where we are

- **Done:** build phases 1–5. `fcfs`, `place_once`, `periodic`, `pred_error`, `fixed_savings` and `pig` run on the toy (hand-checked in `expected.yaml`). C3, C7, rescue and throttling are in.
- **Not built yet:** decision-flip, metrics, `compare`, `sweep`, `report`, dashboard, and deployment steps 4 onward.

## Next steps

1. Phase 6: lower bound, screen, paired width, fallbacks. Prove P1 on the toy and on the dev replicate.
2. Phase 7: metrics, run layout, `compare`, `sweep`, `report`, dashboard.

## Waiting on a decision

| Item | Question | Who |
|---|---|---|
| D44 | C3 was extended to placed jobs in v0.8.3, on evidence (F6). Does the team agree? | Team |
| B1 | Does the mentor confirm the scope, including the v0.8 method changes? | Mentor |
| B3 | Cited power values; until then kgCO2 is relative | Team |

## Things that will catch you out

- **Data:** only `data/processed/` exists here; `data/raw/` is gone. Checksums match the manifests, and `flipwise validate` passes.
- **`docs/design_phases_5_7.md` is design notes, not the spec.** It lists where PRD v0.8 differs from it. Where they disagree, follow the PRD.
- **Trace days count from 1970-01-01 UTC+8**, so day 25 is a Monday and the first job arrives on day 6.6.
- **A real `fixed_savings` week takes about 10 minutes.** Most of it is rebuilding wait profiles, which is why the screen matters.
- **Single-week emissions totals are noisy** because of F4. Don't draw conclusions from one replicate.
- **Tuning:** never tune thresholds on test-period data (trace days 46–73, carbon from 1 Sep 2023).

## Ending a session

1. Update this file: where we are, next steps, anything newly confusing.
2. Add any new decision or finding to `decisions.md`, and change the PRD in the same commit if the design changed.
3. Run `graphify update .` if the graph is in use.
