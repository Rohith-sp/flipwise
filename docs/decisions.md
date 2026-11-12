# Decision log

Every design decision, grouped by the phase it was made in. For how the project got here as a story, see `project_journey.md`; for where work stands today, see `HANDOFF.md`.

**PRD version: 0.9.1**

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
| D21 | 24 Oct | Results viewer is a static `dashboard.html`, separate from `run` | Long runs never block on a UI, and the demo cannot fail on a server | active | §4.1 | dashboard |
| D22 | 25 Oct | Project named Flipwise (was FlipSim) | "It re-evaluates decision flips wisely" | active | header | — |

## Deployment track: PRD v0.4 and v0.6 (28–29 Oct 2026)

| ID | Date | Decision | Why | Status | PRD | Code |
|---|---|---|---|---|---|---|
| D23 | 28 Oct | Datacentres can run as separate services (local, Docker, AWS), but the coordinator owns a simulated clock and every mode must be byte-identical to in-process | Real-time services would make runs slow and unrepeatable | active | §13.5 | datacentre, dcservice |
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
| D26 | 2 Nov | Stage-1 screen uses a feasible-window, empty-queue bound; replaces the `m_p` multi-scale bound | F1 | active | §10.4 | planner, carbon |
| D27 | 2 Nov | Noise width is paired: runtime counts only through the difference between options. θ grid becomes 0, 0.05, 0.1, 0.25, 0.5 | F2 | active | §10.5 | planner, policies |
| D28 | 2 Nov | Rescue limits: missing carbon keeps the incumbent, no repeat rescue on a fallback placement, a queued job needs a feasible alternative, one rescue per release | Prevents queue-loss spirals and a release loop; resolves a §10.2 and §10.7 contradiction | active | §10.2 | simulator, policies |
| D29 | 2 Nov | A queued job's incumbent is exempt from the Range check | Its release is already in the past, so it would always look infeasible | active | §9.5 | planner |
| D30 | 2 Nov | Moves in one update apply one at a time | Otherwise every job picks the same cheap slot | active | §10.6 | simulator, policies |
| D31 | 2 Nov | FCFS ties rotate over datacentres | A carbon-blind reference should not favour one site. Its expected effect was wrong: see F3 | active | §11 | planner, policies |
| D32 | 2 Nov | Trace slices start on trace Mondays (days 25, 32, …, 67); trace day 0 is 1970-01-01 00:00 UTC+8 | §6.3 needs Mondays; the origin was stated in v0.8.2 | active | §14.2 | scenario, validate |
| D33 | 2 Nov | Cluster totals stored in config: 156,576 cores, 948,224 GB, 6,742 GPUs | The raw machine file is not needed at run time | active | §8.1 | scenario |
| D34 | 2 Nov | Placeholder powers for the Phase 2 review: 0.3 kW/GPU, 0.01 kW/core, results labelled relative | B3 is open; rankings do not depend on the scale | active | §7.2 | scenario |
| D35 | 4 Nov | All data lives in `data/processed/`; `.gitignore` covers `data/` except its README and manifests | A nested unzip could otherwise commit about 250 MB | active | §17.1 | — |
| D36 | 4 Nov | Residual fit expands full vintages and uses only slots inside the calibration period | The forecast file is a change-log, and late captures reach into validation | active | §6.8 | carbon |
| D37 | 2 Nov | A queued job's incumbent is scored at its own queue position, and profiles used to score a job never contain that job | Last place overstates its wait, biases towards moving and makes Stage 1 rebuild profiles. Approved in review, added to the PRD in v0.8.1. Extended by D44 | active | §9.3 | planner, simulator |
| D38 | 2 Nov | Acceptance also requires a strictly positive gain, in every policy with an acceptance rule, so the θ = 0 equivalence holds | One real job has zero power, so a gain of 0 would pass the gate repeatedly. Approved in review, added to the PRD in v0.8.1 | active | §10.5 | policies |
| D41 | 4 Nov | Emissions and intensity are always reported for all jobs and for jobs with `runtime_actual_s ≤ r_q90`. The rule is fixed and not tuned, and no conclusion rests on one week | F4. The rule uses actual runtime only in reporting, so it cannot affect decisions | active | §14.1 | — |

## Build phase 5: baselines, PRD v0.8.3 (4 Nov 2026)

| ID | Date | Decision | Why | Status | PRD | Code |
|---|---|---|---|---|---|---|
| D42 | 4 Nov | A job with no feasible alternative moves to the fallback only if that finishes strictly earlier; otherwise `RESCUE_NOOP` | A rescue that finishes no earlier gains nothing. From the design notes (§3.4); the PRD's limits did not cover it | active | §10.2 | policies |
| D43 | 4 Nov | `pred_error` measures drift from the last time the plan was examined, even if the job was kept | Otherwise one past drift fires that job at every later update, turning the trigger into a timer | active | §11 | policies |
| D44 | 4 Nov | C3 covers every pending incumbent, not only queued ones: a placed job also keeps its place in the projected order | F6. Extends D37, as the original design note had it. Reads a shared profile, so it also removes three profile rebuilds per check. Approved by the team on 4 Nov | active | §9.3 | planner, simulator |

## Build phase 7: experiment runner, PRD v0.8.4 (4 Nov 2026)

| ID | Date | Decision | Why | Status | PRD | Code |
|---|---|---|---|---|---|---|
| D45 | 4 Nov | `run_id` hashes only the run's own policy parameters | A θ sweep would otherwise repeat every baseline in every cell, about 25 extra real runs on one replicate | active | §16.1 | experiment |

## Build phase 8: validation, PRD v0.8.5 (4 Nov 2026)

| ID | Date | Decision | Why | Status | PRD | Code |
|---|---|---|---|---|---|---|
| D46 | 4 Nov | Validation and test replicates use sampling 0.1, as dev does, until 1.0 is shown to be affordable | Full sampling is about 10× the jobs. One sampled week already takes up to 8 minutes per policy, and this laptop has about 3 GB of disk free | active | §14.4 | experiment |
| D47 | 5 Nov | Freeze by the §14.5 rule: `decision_flip` θ = 0.1, `w_max` = 2, `g_rel` = 0.05; `fixed_savings` `g_rel` = 0.01; `periodic` T = 1,800 s; `pred_error` ε = 0.05. `g_rel` was also swept for `decision_flip` (`configs/sweeps/g_rel_decision_flip.yaml`) | §14.5 applies per policy, and comparing `decision_flip` at 0.05 with `fixed_savings` at 0.01 needed `decision_flip`'s own sweep to show 0.05 is its pick. The rule decides even where cells can't be told apart (F14) | active | §14.5 | experiment |
| D48 | 5 Nov | Export validation evidence to `docs/validation/` (tables, curves, diagnostics, per-run hashes, dashboard; 1.3 MB) and set the `g_abs` and `κ` sweep values from median Ŝ = 0.04844 kg | `results/` is 2.5 GB and can't be shared, and the team needs these numbers without re-running 300 simulations. The rule against committing `results/` still stands: this is a curated summary, not the logs | active | §10.10, §14.5 | — |

## Team decisions after the freeze: PRD v0.8.8 (10 Nov 2026)

| ID | Date | Decision | Why | Status | PRD | Code |
|---|---|---|---|---|---|---|
| D49 | 10 Nov | Keep `w_max` = 2 and accept `INTERVAL_TOO_WIDE` above its 10 % flag; report the fallback share and the share of moves made with θ off next to every `decision_flip` result | Widening to 5 cleared the flag on average but lowered no emissions (F13); changing it without evidence would be tuning, and after the test run it would break "run once" | active | §14.5 | — |
| D50 | 10 Nov | Run the test set once at sampling 0.1, as validation was, and say so in the report | Sampling 1.0 is about 10× the jobs and too slow for a laptop; the choice has to be made before the one run | active | §14.5 | — |
| D51 | 10 Nov | State the claim as "about the same carbon as the other re-planners at much lower re-planning cost", plus "clearly less carbon than place-once"; not "lowest emissions" | On validation `decision_flip` could not be told apart from `fixed_savings`, `periodic` or `pred_error` on carbon, but used 58 % fewer full re-scorings and 61 % fewer moves than `fixed_savings` (F14) | active | §14.5 | — |
| D58 | 12 Nov | Power model (B3): GPU power per type from NVIDIA datasheets (V100 and V100M32 300 W, P100 250 W, T4 70 W, MISC 150 W), CPU 10 W per core (assumed), and emissions reported as a bracket. `nameplate` charges requested GPUs at datasheet power (upper bound); `measured` scales GPU power by each job's measured use from `pai_sensor_table` and uses measured CPU cores (lower bound, idle draw excluded). The scheduler always uses nameplate power | Measured use is very low (F22), so datasheet power alone would overstate emissions several times, while utilisation alone ignores idle draw that no source quantifies; a bracket uses only cited numbers. Decisions do not depend on power (R-EN-3), so earlier placements stay valid and only kgCO2 is recomputed | active | §7.2, §13.4 | energy |
| D57 | 12 Nov | The test set was run once, as D50 decided, after deployment steps were done on Linux: `compare --split test --policies all`, 16 replicates, commit `6cf8b8a`, clean tree. Results are exported to `docs/test_results/` and the run is not to be repeated | The PRD allows one run, so the result is the claim whatever it shows; the Windows Docker run and B1 were still open, and neither can change the simulation | active | §14.5 | experiment |
| D56 | 11 Nov | DT2 Docker design: one image for all four containers (`python:3.12-slim`, uv 0.13.5 pinned, `--frozen --no-dev --no-editable`, uid 1000); `.dockerignore` is an allow-list; data is bind-mounted read-only and never copied in; the compose network is `internal` with no published ports; the coordinator waits for the three healthchecks; the commit comes from `FLIPWISE_GIT_COMMIT` because the image has no `.git`; `docker_check.sh` is the acceptance test | An allow-list cannot leak data or secrets by accident; a read-only data mount keeps the image small and the inputs the same as in-process; services only need to be reachable from the coordinator. Bind mounts carry `:z` so SELinux hosts (Fedora) can write results. Files: `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `scripts/docker_check.sh` | active | §13.4, §13.5, §18 | experiment |
| D55 | 10 Nov | Overhead (R-DEP-5) is measured in the coordinator: every datacentre client, in-process or HTTP, is wrapped in `experiment.TimedClient`, which counts calls and their `perf_counter` time. `manifest.json` gains `overhead` (`run_s`, and `calls` and `seconds` per datacentre) and `protocol_version` | The service may not read any clock (§13.5), and wrapping both modes alike makes them directly comparable; equal call counts are also a cheap check that both modes follow the same path | active | §13.5 | experiment |
| D54 | 10 Nov | Local-split scripts: `local_cluster.sh` and a PowerShell twin `local_cluster.ps1` with the same flags (`--base-port`, `--n-dc`, `--crash DC:N`). Busy ports are refused before anything starts; clean-up stops only the process trees the script started (`taskkill /T` on Windows), not by port. `dc-serve --crash-at-request N` exits on the N-th simulation request, so R-DEP-3 is tested at a fixed point, not by timing a kill. `dc-serve` no longer sets `SO_REUSEADDR` on Windows | Killing by port could stop someone else's program; the venv launcher on Windows starts a child interpreter that survives a plain kill of the launcher; a toy run takes under a second, too short to kill by hand; and on Windows `SO_REUSEADDR` lets a second socket take a busy port silently | active | §13.4, §18 | dcservice |
| D53 | 10 Nov | Drop the scripted driver (deployment step 5); `flipwise run --mode remote` on the toy is the local-split check. A remote run gets its own `run_id` (so a saved in-process run never stands in for it), and its URLs are checked against `dc_id` before the first event | The driver was meant to show the split before the simulator existed; the simulator now does the same job with every policy, and R-DEP-7 already covers the call-by-call behaviour | active | §18 | experiment |
| D52 | 10 Nov | Deployment before the test run: DT1 steps 5–7, then DT2 (Docker), which is now required for EL Phase 2 rather than a stretch goal; then the test set once, sensitivity sweeps and ablations | The Phase 2 review expects both the local split and Docker; the test run needs no further code | active | §14.5, §18.1 | — |

## Project tooling: PRD v0.8.2 (4 Nov 2026)

| ID | Date | Decision | Why | Status | PRD | Code |
|---|---|---|---|---|---|---|
| D39 | 4 Nov | This log and `HANDOFF.md` are the written record of decisions and current state | Git and the changelog show what changed, not always why, and a code graph shows neither | active | §12.1 | — |
| D40 | 4 Nov | Graphify is an optional navigation tool, outside the project's dependencies; it indexes this log and never replaces it | It maps the project as it is now, so it cannot hold history. Simulation code never imports it | active | §12.1 | — |

## Findings

| ID | Date | Finding | Led to | Evidence |
|---|---|---|---|---|
| F22 | 12 Nov | `pai_sensor_table` (3,033,232 instance rows, checksum matches Alibaba's README) covers 78.6 % of our 732,355 jobs. Measured GPU use per job, as a share of the GPUs requested: median 3.5 %, mean 17.1 % (capped at 1), 75th percentile 23.1 %; 2.4 % of jobs exceed their request. Measured CPU cores against requested: median 0.20. 62 % of jobs are on MISC GPUs | Most allocated GPU time is idle, so nameplate power overstates energy several times and idle draw dominates real consumption; the two bracket ends will be far apart. MISC's power value matters most | `data/raw/v2020/pai_sensor_table.csv` (not committed) |
| F21 | 12 Nov | Test-set result (16 replicates, sampling 0.1). `decision_flip` 16,055 kg against `place_once` 16,110 (−55, CI −128 to +12), `fixed_savings` 16,079 (−24, CI −83 to +31), `periodic` 16,045 (+10), `pred_error` 16,109 (−54), `fcfs` 16,482 (−427, CI −545 to −309), `pig` 15,858 (+196, CI +146 to +245). Cost: 54 % fewer full re-scorings and 60 % fewer moves than `fixed_savings` (20,035 against 43,540; 2,359 against 5,897), but 34 % more re-scorings than `pred_error` (14,944). Misses 4.13 % against 3.95 % for `place_once`. θ off on 23.4 % of comparisons | The validation result against `place_once` (−146 kg, clearly lower) did not repeat: it is within noise on the test set. Only the cost claim and the lead over `fcfs` held. The claim must say "about the same carbon as the other re-planners and `place_once`, at lower re-planning cost than `fixed_savings` and `periodic`", and must not say "lower emissions than `place_once`" | `docs/test_results/` (README, `pairwise.csv`, `paired.csv`) |
| F20 | 11 Nov | DT2 in Compose on Linux (Fedora, Docker 29.9, Compose 5.6): R-DEP-1 holds for all seven policies on the toy, R-DEP-2 holds for `decision_flip` on the dev week (`jobs.csv` hash `3f222d58…`, same as in-process and as the local split), and killing `dc-mumbai` mid-run makes the coordinator exit 1 with `DeploymentError` and no `metrics.json`. Dev-week wall time, same 58,454 calls each: in-process 69 s, local split 101 s, Docker 130 s (45 s of it in RPC, about 0.8 ms per call). Image 733 MB. The same three checks (R-DEP-1 on all seven policies, R-DEP-2, R-DEP-3) also passed from a fresh `git clone` of the DT2 commit with only `data/processed/` copied in | R-DEP-5 on Linux is far cheaper per call than F18's 5.5 ms on Windows, so the overhead figure depends on the host. Report it with its host, and do not compare it with F18 as if it were the same measure | `docker_check.sh` output; manifests (local) |
| F19 | 11 Nov | DT1 re-checked on Linux (Fedora): 247 tests pass, including the cluster tests. `decision_flip` on the dev week through `local_cluster.sh` gives `jobs.csv`, `decisions.csv` and `events.log` byte-identical to the in-process run (6,976, 55,268 and 28,523 lines; 58,454 datacentre calls), 103 s split against 69 s in-process. Toy crash injection (`--crash 1:5`) aborts with `DeploymentError`, exit 1, and leaves no listener on ports 8101–8103 | Closes the F18 follow-up. R-DEP-2 already holds without Docker, so DT2 only has to reproduce it inside Compose | Local runs, not committed |
| F18 | 10 Nov | R-DEP-5 on the dev week (sampling 0.1), Windows laptop: `fcfs` 10.0 s in-process (45,053 datacentre calls, 0.5 s in them) vs 261.9 s split (same 45,053 calls, 249.1 s in them), about 5.5 ms per HTTP call; `decision_flip` 179.5 s in-process (58,454 calls); its split run was stopped before it finished. The cost is per call: each call opens a new HTTP connection | Report it with the demo; a persistent connection per datacentre could cut it, but correctness does not need it. Re-run `decision_flip` split and check its hashes | Run manifests (local, `%TEMP%/fw_overhead`) |
| F17 | 10 Nov | F16 explained: in Windows PowerShell 5.1 with `ErrorActionPreference` Stop, `taskkill`'s "not found" for a service that had already crashed became a terminating error, which aborted the clean-up loop and left later services running; the test then hung on the orphan's open output pipe. Fixed in `local_cluster.ps1` (clean-up through `cmd`, never fatal) and in the test (output to a file, so an orphan fails the free-port check instead of hanging). All 6 script tests then passed in 21 s with no service left | Closes F16 on Windows; Linux still untested | `tests/test_local_cluster.py` |
| F16 | 10 Nov | Local split by hand on Windows: both scripts run the toy with `jobs.csv`, `decisions.csv` and `events.log` identical to `--mode inproc`, copy `dc-*.log` into the run folder and leave no service running; with `--crash 1:5` (PowerShell) or `--crash 2:3` (Git Bash) the run stops with `DeploymentError` in about 6 s, exits non-zero, writes no `metrics.json` and leaves no service. Automated (`tests/test_local_cluster.py`): 51 of 52 deployment tests passed; the PowerShell crash case timed out after 180 s in a run where a stray `dc-serve` from an earlier, overlapping test run was still alive. Not yet re-run on a clean machine, and Linux is untested | Re-run that test alone before relying on it (HANDOFF) | `tests/test_local_cluster.py`, PRD §18 |
| F1 | 2 Nov | The naive Stage-1 bound failed: 100 % of checks passed, so the screen saved nothing. The new bound passes 18.3 %, against a floor of 9.7 % | D26 | PRD §10.11; simplified run of 1,800 jobs, no queues |
| F2 | 2 Nov | The original noise width was "too wide" on 98.7 % of comparisons, which switched θ off | D27 | PRD §10.11; same run |
| F3 | 4 Nov | Rotating FCFS's tie-break lowered its intensity (665.6 → 639.0 g/kWh), the opposite of what v0.8 expected | Correction to D31 | PRD §10.11 |
| F4 | 4 Nov | 35 of 6,975 jobs use half the energy, running for days against estimates under an hour. One week's total mostly records where they land: `fcfs` 639.0 and `place_once` 638.9 g/kWh, or 654.8 and 635.1 on jobs within `r_q90` | Compare across replicates; report with and without those jobs (PRD §17.1) | PRD §10.11; one validation week, relative emissions |
| F5 | 4 Nov | `place_once` misses 7.34 % of deadlines against 2.44 % for `fcfs`; 81 % of its misses are jobs that outran `r_q90` | Check before build phase 6 (PRD §17.1); see F7 | PRD §10.11, §17.1 |
| F6 | 4 Nov | With C3 as worded in v0.8.1, placed jobs still competed with themselves: 3,532 `place_once` rescues across 6,975 jobs, undoing its carbon gain (668.6 g/kWh on jobs within `r_q90`). With every pending incumbent keeping its place: 939 rescues, 638.3 g/kWh | D44 | PRD §10.11; one validation week, relative emissions |
| F7 | 4 Nov | Place-once misses are explained: 87 % are jobs that outran `r_q90`. Deferral (mean 3.2 h) uses up slack they turn out to need: 39.8 % of them miss against 16.6 % under `fcfs`. Rescue lowers the rate from 7.34 % to 6.24 %; it cannot help a job already running | Closes phase 5's exit criterion; slack stays a sweep parameter | PRD §17.1; one validation week |
| F8 | 4 Nov | P1 holds on the first validation week: identical `jobs.csv` and `events.log`, and all 11,956 state-changing decisions match. The screen skips 66 % of full re-scorings (43,097 to 14,568), a pass rate of 33.8 % against 18.3 % in the queue-free estimate | The core claim of EL Phase 2 (R-TRIG-2, P2) | PRD §10.11; `scripts/check_p1.py` |
| F9 | 4 Nov | `INTERVAL_TOO_WIDE` turns θ off on 30.0 % of `decision_flip`'s comparisons on the first validation week, above the 10 % flag; median `w_ab / Ŝ_a` is 1.35. Far better than v0.7's 98.7 %, but not rare as v0.8 expected | Measure across validation replicates before changing `w_max` (PRD §14.5) | PRD §17.1 |
| F10 | 4 Nov | `pig` is cleanest on jobs within `r_q90` (540.2 g/kWh) but not on all jobs (654.0): for jobs that run for days it finds no feasible plan, and the fallback ignores carbon. Its 174 at-risk jobs hold 48.5 % of energy | Read `pig` on `J_e`; the fallback rule stays shared by every policy (PRD §9.5) | PRD §10.11 |
| F11 | 4 Nov | On one week `fcfs` has lower all-jobs emissions and fewer misses than `decision_flip` at every θ, and θ works as a dial on moves (3,834 down to 1,795) | Re-test across replicates before any conclusion (F4, D41) | PRD §10.11, `flipwise sweep` |
| F12 | 5 Nov | Across 12 validation replicates at sampling 0.1, `decision_flip` (θ = 0.1, `w_max` = 2) emits 146 kg less than `place_once` on all jobs (mean of about 14,155 kg; paired 95 % CI −234 to −60). On jobs within `r_q90` the gain is 53 kg, CI −113 to +5, so not resolved. Miss rate is level (4.17 % vs 4.09 %; CI of the difference −0.18 to +0.36 pp). It uses 59 % fewer full re-scorings than `fixed_savings` (16,933 vs 41,065) and 41 % fewer moves (2,289 vs 3,857). `fixed_savings`' all-jobs gain is not resolved (CI −215 to +38). `fcfs` no longer beats `decision_flip` on all-jobs emissions as it did in F11 (14,169 vs 14,008 kg) but still has half the misses (2.07 %) | Preliminary: kgCO2 is relative until B3, and no test data was used | `results/compare_29117a198ab8` (local only) |
| F13 | 5 Nov | F9 across replicates: at `w_max` = 2 the interval fallback is 28.4 % at θ = 0.1 and above the 10 % flag on all 12 replicates. `w_max` = 3 gives about 17 % (flagged on 12 of 12); `w_max` = 5 gives about 9–10 % (flagged on 2–4). Widening did not lower emissions: 14,008 kg at (θ 0.1, `w_max` 2), against 14,036–14,084 kg at `w_max` 3 and 5. The §14.5 rule therefore points to θ = 0.1, `w_max` = 2, the current defaults. Paired, `w_max` 2 against 3 is −32 kg (CI −81 to +14) and against 5 is −71 kg (CI −204 to +70), so this is not evidence that 2 is truly better | `w_max` = 2 frozen by D47; whether to accept the F9 flag is a team call | PRD §14.5, `scripts/select_thresholds.py` |
| F14 | 5 Nov | All validation sweeps done (300 runs at `b669c70`). The frozen `decision_flip` has the lowest all-jobs emissions of the online policies, but it can't be told apart from the other re-planners: difference from `fixed_savings` (`g_rel` 0.01) −24 kg, CI −103 to +59; `periodic` −49, CI −101 to +10; `pred_error` −69, CI −165 to +38. Its measured edge is cost: 58 % fewer full re-scorings and 61 % fewer moves than `fixed_savings`. Against `place_once`: −146 kg (CI −234 to −60). Against `fcfs`: −161 kg on all jobs (CI −260 to −57), −142 kg within `r_q90` (CI −184 to −102), but `fcfs` has half the misses. P1: at θ = 0 `jobs.csv` and `events.log` match `fixed_savings` (both `g_rel` 0.05) on 12 of 12 replicates, with 62 % fewer re-scorings. Within a sweep the gaps are mostly noise: `fixed_savings` `g_rel` 0.01 vs 0.05 −30 kg (CI −117 to +66); `periodic` T = 7,200 s is 10 kg behind 1,800 s (CI −85 to +103) with a quarter of the re-scorings | Validation only and sampling 0.1, not a final result; run the test set once for the claim. `periodic`'s cheaper T = 7,200 s should appear in the sweep curves (§14.5) | PRD §14.5, `docs/validation/` |
| F15 | 5 Nov | Earlier one-week findings across all 12 replicates (`decision_flip` unless named). F4: the top 1 % of jobs use 56.5 % of the energy. F7: 91.8 % of misses are jobs that outran `r_q90` (11.5 % of jobs); those jobs miss at 32.9 % against 16.7 % under `fcfs`, and jobs within `r_q90` miss at 0.4 %. F9: median `w_ab / Ŝ_a` 1.32, and 67.6 % of moves are made with θ off, so θ has no say in most moves. F10 did not hold: across replicates `pig` is cleanest on all jobs too (616.3 g/kWh), though its total is not clearly below `decision_flip`'s (+112 kg to `decision_flip`, CI −6 to +229). Coverage: carbon 91–93 % per lead bucket, runtime 86.8 %, wait 89.8 %, against a nominal 90 %. Screen pass rate 40.6 %. Completion flag: 0 of 84 | Use these numbers, not the one-week ones, in the report. Coverage is close to nominal, which the phase 8 exit asks to report | `docs/validation/diagnostics.csv`, `summary.csv` |
