# Decision log

Every design decision, grouped by the phase it was made in. For how the project got here as a story, see `project_journey.md`; for where work stands today, see `HANDOFF.md`.

**PRD version: 0.8.2**

## Rules

- **The PRD holds the rule, this log holds the history.** If they disagree, the PRD wins until someone fixes the log. A design change edits both in the same commit.
- **Never edit a past decision to change its meaning.** Add a new row and mark the old one `superseded by Dn`.
- **Numbers are permanent.** New decisions take the next free `D` number. A rejected proposal keeps its number.
- **Status** is one of `active`, `proposed`, `rejected`, or `superseded by Dn`.
- **Record a decision when** it changes behaviour, a formula, a data rule or a result, or when it rejects an option someone may suggest again. Routine implementation choices stay in the code.
- **Findings** (`F` numbers) are measurements that drove decisions. They stay here even after the fix, because a method that failed is a result too.

`Code` names modules in `src/flipwise/` that implement the decision so far; `—` means none yet or not code. `tests/test_decisions.py` checks the numbering, statuses, links, modules and PRD version. `scripts/build_graph.py` reads this file, so keep the table format.

## Spec phase: PRD v0.1 to v0.3 (23–25 Oct 2026)

| ID | Date | Decision | Why | Status | PRD | Code |
|---|---|---|---|---|---|---|
| D1 | 24 Oct | One job state machine; a deadline miss is an outcome flag, not a state | One vocabulary; misses are measured | active | §8.2 | models |
| D2 | 24 Oct | No future capacity reservations: a placement sets a release slot, and resources are allocated only at start | Overbooking becomes impossible by construction | active | §8.2 | simulator, datacentre |
| D3 | 24 Oct | Custom `heapq` engine, not SimPy | Needs cancellable events and fixed same-time priorities | active | §5 | simulator |
| D4 | 24 Oct | pandas, YAML and CSV; not Polars, TOML or Parquet | Smallest set that handles about 0.73 M rows | active | §5 | — |
| D5 | 24 Oct | Alibaba trace v2020, not v2026 | Downloaded, checksum-verified and audited | active | §6.1 | ingest, trace |
| D6 | 24 Oct | Queue wait is model-based, not historical | In v2020 every job's `start_time` equals its earliest task start, so historical wait is not derivable | active | §9.3 | estimates |
| D7 | 24 Oct | NESO forecast-vintage archive provides vintages and regional truth | The official API overwrites old forecasts | superseded by D19 | §5 | — |
| D8 | 24 Oct | Baseline named "fixed-savings gate"; no CATS equivalence claimed | A savings gate was not found in the CATS material checked | active | §5 | — |
| D9 | 24 Oct | q90 deadline feasibility is shared by every policy; point estimate becomes an ablation | Avoids a baseline that differs only in a shared component | active | §9.5 | planner |
| D10 | 24 Oct | Oracle renamed perfect-information greedy (`pig`); not called a bound | It is greedy in arrival order, so better schedules may exist | active | §11 | — |
| D11 | 24 Oct | DRO is extension X1, not the core | Mixing it with the trigger confounds attribution, and DRO for carbon scheduling is already published | active | §4.2 | — |
| D12 | 24 Oct | Queued jobs may be moved, and they lose their queue position | Matches "pending = not started"; queue loss is a real switching cost | active | §8.2 | simulator |
| D13 | 24 Oct | Optimiser overhead is not converted to carbon | No measured scheduler energy model | active | §5 | — |
| D14 | 24 Oct | One small package layout | Fewer modules for an MVP | active | §13.1 | — |
| D15 | 24 Oct | Synthetic deadlines derived only from the frozen runtime estimate | Using actual runtime would leak it to the scheduler | active | §6.6 | scenario |
| D16 | 24 Oct | Per-user runtime quantiles from early trace days, frozen | Leak-free and identical across policies | active | §6.5 | estimates, scenario |
| D21 | 24 Oct | Results viewer is a static `dashboard.html`, separate from `run` | Long runs never block on a UI, and the demo cannot fail on a server | active | §4.1 | — |
| D22 | 25 Oct | Project named Flipwise (was FlipSim) | "It re-evaluates decision flips wisely" | active | header | — |

## Deployment track: PRD v0.4 and v0.6 (28–29 Oct 2026)

| ID | Date | Decision | Why | Status | PRD | Code |
|---|---|---|---|---|---|---|
| D23 | 28 Oct | Datacentres can run as separate services (local, Docker, AWS), but the coordinator owns a simulated clock and every mode must be byte-identical to in-process | Real-time services would make runs slow and unrepeatable | active | §13.5 | datacentre |
| D24 | 29 Oct | Docker moves into EL Phase 2 as a stretch; local split is built first, in an order where no step is throwaway | The team wanted to attempt Docker without risking the core results | active | §18 | — |

## India-only world: PRD v0.5 (29 Oct 2026)

| ID | Date | Decision | Why | Status | PRD | Code |
|---|---|---|---|---|---|---|
| D17 | 29 Oct | India only: Delhi NCR, Mumbai and Chennai on the NR, WR and SR grids | The team wants Indian conditions; the datasets stay as available | active | §6.2.1 | scenario |
| D18 | 29 Oct | Truth is production-based regional intensity: generation by fuel × CEA factors | India's official factor source; flows ignored and stated | active | §6.2.2 | ingest |
| D19 | 29 Oct | Forecasts are Indian truth + scaled real NESO error paths | No Indian forecast archive exists; random noise would favour noise-margin policies | active | §6.2.4 | ingest |
| D20 | 29 Oct | Trace clock aligned to IST | Submissions should meet the Indian solar day | active | §6.3 | scenario |

## Build phase 2: canonical data, PRD v0.7 (29 Oct 2026)

| ID | Date | Decision | Why | Status | PRD | Code |
|---|---|---|---|---|---|---|
| D25 | 29 Oct | Indian generation built from Grid-India daily regional mix × national SCADA within-day shape (resolves B4) | Electricity Maps' free data ended and Energymap is paid; this is free and official. Timing within a day is national, not regional | active | §6.2.2 | ingest |

## Design review of phases 5–7: PRD v0.8 to v0.8.2 (2–4 Nov 2026)

| ID | Date | Decision | Why | Status | PRD | Code |
|---|---|---|---|---|---|---|
| D26 | 2 Nov | Stage-1 screen uses a feasible-window, empty-queue bound; replaces the `m_p` multi-scale bound | F1 | active | §10.4 | — |
| D27 | 2 Nov | Noise width is paired: runtime counts only through the difference between options. θ grid becomes 0, 0.05, 0.1, 0.25, 0.5 | F2 | active | §10.5 | — |
| D28 | 2 Nov | Rescue limits: missing carbon keeps the incumbent, no repeat rescue on a fallback placement, a queued job needs a feasible alternative, one rescue per release | Prevents queue-loss spirals and a release loop; resolves a §10.2 and §10.7 contradiction | active | §10.2 | simulator |
| D29 | 2 Nov | A queued job's incumbent is exempt from the Range check | Its release is already in the past, so it would always look infeasible | active | §9.5 | — |
| D30 | 2 Nov | Moves in one update apply one at a time | Otherwise every job picks the same cheap slot | active | §10.6 | simulator, policies |
| D31 | 2 Nov | FCFS ties rotate over datacentres | A carbon-blind reference should not favour one site. Its expected effect was wrong: see F3 | active | §11 | planner, policies |
| D32 | 2 Nov | Trace slices start on trace Mondays (days 25, 32, …, 67); trace day 0 is 1970-01-01 00:00 UTC+8 | §6.3 needs Mondays; the origin was stated in v0.8.2 | active | §14.2 | scenario, validate |
| D33 | 2 Nov | Cluster totals stored in config: 156,576 cores, 948,224 GB, 6,742 GPUs | The raw machine file is not needed at run time | active | §8.1 | scenario |
| D34 | 2 Nov | Placeholder powers for the Phase 2 review: 0.3 kW/GPU, 0.01 kW/core, results labelled relative | B3 is open; rankings do not depend on the scale | active | §7.2 | scenario |
| D35 | 4 Nov | All data lives in `data/processed/`; `.gitignore` covers `data/` except its README and manifests | A nested unzip could otherwise commit about 250 MB | active | §17.1 | — |
| D36 | 4 Nov | Residual fit expands full vintages and uses only slots inside the calibration period | The forecast file is a change-log, and late captures reach into validation | active | §6.8 | carbon |
| D37 | 2 Nov | A queued job's incumbent is scored at its own queue position, and profiles used to score a job never contain that job | Last place overstates its wait, biases towards moving and makes Stage 1 rebuild profiles. Approved in review, added to the PRD in v0.8.1 | active | §9.3 | — |
| D38 | 2 Nov | Acceptance also requires a strictly positive gain, in every policy with an acceptance rule, so the θ = 0 equivalence holds | One real job has zero power, so a gain of 0 would pass the gate repeatedly. Approved in review, added to the PRD in v0.8.1 | active | §10.5 | — |
| D41 | 4 Nov | Emissions and intensity are always reported for all jobs and for jobs with `runtime_actual_s ≤ r_q90`. The rule is fixed and not tuned, and no conclusion rests on one week | F4. The rule uses actual runtime only in reporting, so it cannot affect decisions | active | §14.1 | — |

## Project tooling: PRD v0.8.2 (4 Nov 2026)

| ID | Date | Decision | Why | Status | PRD | Code |
|---|---|---|---|---|---|---|
| D39 | 4 Nov | This log and `HANDOFF.md` are the written record of decisions and current state | Git and the changelog show what changed, not always why, and a code graph shows neither | active | §12.1 | — |
| D40 | 4 Nov | Graphify is an optional navigation tool, outside the project's dependencies; it indexes this log and never replaces it | It maps the project as it is now, so it cannot hold history. Simulation code never imports it | active | §12.1 | — |

## Findings

| ID | Date | Finding | Led to | Evidence |
|---|---|---|---|---|
| F1 | 2 Nov | The naive Stage-1 bound failed: 100 % of checks passed, so the screen saved nothing. The new bound passes 18.3 %, against a floor of 9.7 % | D26 | PRD §10.11; simplified run of 1,800 jobs, no queues |
| F2 | 2 Nov | The original noise width was "too wide" on 98.7 % of comparisons, which switched θ off | D27 | PRD §10.11; same run |
| F3 | 4 Nov | Rotating FCFS's tie-break lowered its intensity (665.6 → 639.0 g/kWh), the opposite of what v0.8 expected | Correction to D31 | PRD §10.11 |
| F4 | 4 Nov | 35 of 6,975 jobs use half the energy, running for days against estimates under an hour. One week's total mostly records where they land: `fcfs` 639.0 and `place_once` 638.9 g/kWh, or 654.8 and 635.1 on jobs within `r_q90` | Compare across replicates; report with and without those jobs (PRD §17.1) | PRD §10.11; one validation week, relative emissions |
| F5 | 4 Nov | `place_once` misses 7.34 % of deadlines against 2.44 % for `fcfs`; 81 % of its misses are jobs that outran `r_q90` | Check before build phase 6 (PRD §17.1) | PRD §10.11, §17.1 |
