# Project journey: from a PRD to a working pipeline

How Flipwise got from "a PRD and a plan" to a tested simulator core with real Indian grid data, and why each decision was made. Written 29 Oct 2026. For the exact rules, `prd.md` is authoritative; this file is the story.

---

## 1. Starting point (24–25 Oct)

The folder held three documents and no code:

- `docs/prd.md` (v0.3): the full specification. The research question was **when** a carbon-aware scheduler should re-plan a job that hasn't started yet. The proposed answer was the **decision-flip trigger**: a cheap screen plus a noise-adjusted gate. The simulated world was three datacentres in Great Britain fed by NESO carbon forecasts.
- `docs/explanation.md`: the same idea in plain language, partly out of date compared with the PRD.
- `docs/helpfullinks.txt`: dataset, paper and tool links.

There was no git repository and no README.

## 2. Documents and repository (25 Oct)

| What | Why |
|---|---|
| Wrote `README.md` following the outline in PRD §13.1 | Reviewers and teammates need a one-page entry point: problem, scope, datasets, setup, roadmap |
| Named the project **Flipwise** (was "FlipSim") | "It re-evaluates decision flips wisely"; renamed everywhere in PRD and README |
| Created the GitHub repository `Rohith-sp/flipwise` and pushed | One shared source of truth for the team |
| Wrote `Flipwise_Project_Guide.docx` (outside the repo, in `C:\5TH SEM EL\`) | A from-zero explanation for team members joining late; generated with the `docx` JavaScript library and checked by exporting through Microsoft Word |

**DRO discussion.** A teammate asked whether DRO (Distributionally Robust Optimization) should be part of the MVP. Decision: **no, not as the core**. DRO is a *planner* (where and when a job runs). Decision-flip is a *trigger* (when to ask the planner again). Changing both at once would make it impossible to say which caused any gain, and DRO for carbon scheduling is already published, so it can't be the new contribution. DRO stays extension X1; a simple DRO planner can later become a switchable setting.

## 3. Deployment track (28 Oct, PRD v0.4)

**Idea (Stavan):** run each virtual datacentre as its own service, mimicking three real sites: first as local processes, then in Docker, then on AWS.

**Decision:** accepted as a parallel **deployment track** (DT1 local split → DT2 Docker → DT3 AWS) with one strict rule. The coordinator owns a **simulated clock**, and every mode must produce **byte-identical** output files to the normal in-process run.

**Why the rule:** if the services ran in real time, a one-week experiment would take a week, and network delays would reorder events, so results could not be reproduced or compared fairly. With the rule, the services prove the scheduler works across machines without ever changing a research number.

Also added in this step:
- **The service API:** seven JSON-over-HTTP endpoints (PRD §13.5).
- **Requirements:** R-DEP-1…6.
- **`CLAUDE.md`:** project instructions for Claude Code, including how to read the 1,000-line PRD cheaply.
- **Naming:** the stages were renamed DT1–DT3 because D1–D16 were already the PRD's decision IDs.

## 4. India-only world (29 Oct, PRD v0.5)

**Request:** make the project India-centric. The datasets stay what is available, but the simulated conditions are Indian.

| Part | Before (GB) | After (India) |
|---|---|---|
| Datacentres | North Scotland, London, South Wales | **Delhi NCR** (Northern grid), **Mumbai** (Western), **Chennai** (Southern) |
| Carbon "truth" | NESO final regional forecast | Indian regional intensity = generation by fuel × **CEA** emission factors |
| Forecasts the scheduler sees | Real archived NESO forecasts | Indian truth + **real NESO forecast-error paths**, scaled to Indian levels |
| Clock | UK time | **IST** |
| Emissions reference | UK DESNZ factors | **CEA CO2 Baseline Database** (India's official source) |
| AWS stage region | London | **Mumbai** (`ap-south-1`) |

**Why borrow British forecast errors:** nobody has archived Indian carbon *forecasts*, but the simulator must only show the scheduler what it could have known at each moment. Random noise would jitter every half hour and unfairly favour decision-flip's noise margin. Real error paths grow with lead time and revise smoothly, like a real forecast. The limitation, stated in every report, is that the errors come from British weather, not Indian monsoon or solar.

## 5. Implementation (29 Oct, Stavan; PRD v0.5.1)

Stavan implemented build phases 1, 3 and 4 and most of 2, pushed as six commits:

| Build phase | What exists |
|---|---|
| 1. Setup and audit | `pyproject.toml` with **uv** (Python 3.12), **ruff** (lint and format), **pytest**; download scripts; a script that reproduces the Alibaba trace statistics |
| 2. Canonical data | Alibaba v2020 → `jobs_v2020.csv`; NESO archive → GB error paths; `build-forecasts`; `validate`; real-data findings recorded in the PRD (archive gaps, measured GB region intensities) |
| 3. Simulator core | Event engine (`heapq`), job states, `datacentre.py` behind the `DatacentreClient` interface, toy scenario, FCFS |
| 4. Emissions + place-once | Energy model, carbon views, planner (candidates, feasibility, scoring), place-once |

Code: 17 modules in `src/flipwise/`, 10 test files. All tests pass, ruff is clean, and `flipwise smoke` matches the hand-computed toy answers.

## 6. Phase 2 plan (29 Oct, PRD v0.6)

The team decided Phase 2 would also attempt Docker, after the local split. The PRD now has an eight-step order: seven local-split steps, then Docker.

1. Repo skeleton
2. `datacentre.py`
3. Client interface
4. HTTP service
5. **Scripted driver**
6. `local_cluster.sh`
7. Real simulator in remote mode
8. Docker

Steps 1–3 turned out to be already done by Stavan. Step 5 lets the local split be demonstrated **before** the simulator is finished. Our doc commit had to be rebased onto Stavan's six commits; three small conflicts in version and status lines were merged, keeping both changelog entries.

## 7. Getting real Indian data (29 Oct, PRD v0.7, blocker B4)

This was the main remaining blocker: without Indian carbon numbers the simulator cannot produce real Phase 2 results.

**What was tried, in order:**

| Source | Outcome |
|---|---|
| Electricity Maps (hourly regional carbon intensity) | Free CSV datasets **discontinued March 2026**; now academic access by application only. Not pursued. |
| Energymap | Paid. Not used. |
| Grid-India daily PSP reports | ✅ **Regional daily generation by fuel** (coal, lignite, hydro, nuclear, gas, wind, solar, other RES) for NR/WR/SR/ER. Free, official. |
| Grid-India SCADA on Mendeley Data | ✅ **All-India generation by fuel every 10 seconds**, CC BY 4.0. Gives the within-day shape. |
| CEA CO2 Baseline Database v19.0 | ✅ Emission factors: coal 978, lignite 1286, gas 478 gCO2/kWh (FY 2022-23) |

**Method:**

1. From the daily reports, take how much each region generated from each fuel on each day. This part is measured.
2. From the national SCADA data, take how each fuel's output is spread across that day, for example solar peaking at noon. This part is measured nationally.
3. Combine them: each region's daily total per fuel × the national shape of that fuel = regional generation per half-hour.
4. Carbon intensity per half-hour = Σ (generation × CEA factor) / Σ generation.

**Honest label:** each region's daily fuel mix is real; the timing inside the day is national, not regional. The PRD records this as option 3 of §6.2.2.

**What was built:**

- `scripts/download_india.py`: fetches about 330 daily reports through Grid-India's public file API, plus the SCADA workbooks from Mendeley, with a SHA-256 checksum per file.
- `scripts/build_india_generation.py`: parses the `.xls`/`.xlsx` files and writes `india_generation.csv`.
- `construct_india_generation` in `src/flipwise/ingest.py`: the method above as a tested function, with a hand-computed test.
- `configs/energy.yaml`: the CEA factors, with citations.
- An optional dependency extra `india-data` (openpyxl, xlrd), used only for reading the reports.

**Problems hit on the way, and fixes:**

| Problem | Fix |
|---|---|
| Mendeley rejected Python's default user-agent (HTTP 403) | Send a browser-style header |
| Git Bash on Windows rewrote the archive paths `/data/db/...` into `C:/Program Files/Git/data/...`, so the sparse checkout was empty | `MSYS_NO_PATHCONV=1` in `scripts/download_data.sh` |
| No report for 21 Mar 2023, and a corrupted cell in 10 Jun 2023 | Filled from the mean of the neighbouring days, listed in the manifest |
| The 2024 SCADA file has wind and solar only, hourly | Fossil, hydro and nuclear take their 2023 typical within-day shape for Jan–Feb 2024 |

**Results (all-India pipeline ran on 29 Oct; `flipwise validate: OK`):**

| | Delhi NCR (NR) | Mumbai (WR) | Chennai (SR) | Eastern (ER) |
|---|---|---|---|---|
| Mean intensity, gCO2/kWh | 657 | 831 | 667 | 883 |
| At 03:00 IST | 742 | 858 | 736 | 896 |
| At 12:00 IST (solar) | 532 | 780 | 533 | 882 |
| Lowest month | Aug 2023: 570 | Aug 2023: 759 | Jul 2023: 576 | Aug 2023: 796 |

- **Cross-check:** the generation-weighted all-India mean is 753 g/kWh, against CEA's published 716 g/kWh for FY 2022-23 including renewables. That's 5 % higher, as expected from gross vs net generation and the one-year difference.
- **Forecast scaling:** the British error paths are scaled by `s_r` = 3.95 (NR), 2.66 (WR) and 2.78 (SR), because India's grid is about 3–4 times more carbon-intensive than the British source regions.
- **Volume:** 2.2 million Indian forecast rows were built, with no error row lacking a truth value.
- **Reproducibility:** on a second machine, the Alibaba ingest and the British error-path ingest produced byte-identical outputs to Stavan's (same SHA-256 in the manifests).

**What the numbers mean for the research:** there is a real difference *between* regions (Mumbai is about 170 g/kWh dirtier than Delhi or Chennai on average) and a strong difference *across the day* (about 200 g/kWh lower at noon in Delhi and Chennai). Both spatial and temporal shifting therefore have room to help, which is what hypothesis H3 tests.

## 8. Design review of phases 5–7 (2 Nov, PRD v0.8)

Before coding the baselines and decision-flip, a teammate wrote a design for build phases 5–7 and tested the method on the first validation week. Two parts of the method as written in v0.7 would not have worked on real data:

| Problem found | Why it mattered | Change in v0.8 |
|---|---|---|
| The Stage-1 screen passed 100 % of checks | It searched for the cleanest window up to 8 days ahead, ignoring the deadline, so the screen saved no work and H1 would fail | The bound now searches only start times a feasible plan can have; 18.3 % of checks pass, against a floor of 9.7 % |
| θ had almost no effect | The noise width counted each option's full runtime spread, so it was "too wide" 98.7 % of the time and θ was switched off | Paired width: runtime counts only through the *difference* between the two options, since a long job costs more at either site; θ grid lowered to 0–0.5 |
| FCFS always broke ties towards Delhi (dc0) | The carbon-blind baseline was accidentally carbon-aware, which made carbon-aware placement look worse | FCFS ties rotate over the datacentres |
| Place-once tripled deadline misses (2.25 % → 7.30 %) | Carbon gains bought with late jobs | To investigate in phase 5, before decision-flip |
| Rescue could loop or cost a queued job its place every 30 min; v0.7 contradicted itself on missing carbon | Unstable runs | Rescue limited; missing carbon keeps the current plan |
| Trace day 21 is not a Monday | The weekday alignment with IST (6.3) was off | Slices start on trace Mondays (days 25, 32, …, 67), found from the weekend dips in submissions |

All the measurements came from validation data, so the test period is untouched. The cluster totals from `pai_machine_spec` (156,576 cores, 948,224 GB, 6,742 GPUs) and the placeholder powers for the Phase 2 review (0.3 kW per GPU, 0.01 kW per core, results labelled relative) were also fixed. Only the plan changed; the code follows in phase 5.

**v0.8.1 (4 Nov).** The first phase 5 build on real data led to two more fixes and one reporting rule:

- **C3:** a queued job was being compared against itself, as if staying put meant re-joining the back of its own queue. Its plan looked worse than it was, so it moved or was "rescued" for no reason. It now keeps its place when scored.
- **C7:** a job with zero power saves nothing by moving, but "saving 0 ≥ gate 0" passed, so it moved every 30 minutes. A move now needs a saving above zero.
- **Long jobs:** 35 of 6,975 jobs used half the energy, mostly jobs that ran for days when estimated at under an hour. Where they landed decided the week's total, hiding any scheduling effect. Results are now always reported twice: all jobs, and jobs that ran within their 90th-percentile estimate. The rule was fixed before further runs, and conclusions use several weeks, never one.
- **FCFS correction:** v0.8 guessed that FCFS looked clean because ties went to Delhi. After the tie-break fix FCFS got cleaner, not dirtier, so that guess was wrong.

## 9. First baselines on the new calendar (4 Nov, PRD v0.8.2)

The processed data moved to `data/processed/`, `.gitignore` now covers everything under `data/` except its README and manifests, and the plumbing for phase 5 went in: a real-trace scenario builder (`flipwise run --config`), runtime and residual fitting, prefix sums for scoring, and hooks for re-planning policies. Two runs on the first validation week gave a surprise:

| Policy | Mean intensity (g/kWh) | Jobs within `r_q90` only | Deadline misses |
|---|---|---|---|
| `fcfs` | 639.0 | 654.8 | 2.44 % |
| `place_once` | 638.9 | 635.1 | 7.34 % |

Placement alone gained nothing in total, and v0.8's explanation was wrong: rotating FCFS's tie-break made FCFS cleaner, not dirtier. The real cause is that **35 of 6,975 jobs use half the energy**. They run for days against an estimate of under an hour, so the scheduler can't plan around them, and one week's total mostly records where they landed. Comparisons therefore need several replicates, and intensity should be reported with and without those jobs.

## 10. Keeping decisions findable (4 Nov, PRD v0.8.2)

Design had started changing quickly, and the reasons were spread across the PRD changelog, this file and chat. The team asked for graphify to track them and to make handing over context easier. Graphify maps the project as it is now, so it can't hold history or reasons by itself. Three pieces now work together:

| Piece | Job |
|---|---|
| `docs/decisions.md` | The record: every decision and finding by phase, with why, status, PRD section and code module, checked by a test |
| `docs/HANDOFF.md` | Current state and next steps, read first by a teammate or new session |
| graphify, via `scripts/build_graph.py` | Navigation: a queryable graph linking code to decisions, parsed from the log, so it needs no LLM |

## 11. Building the baselines: when "C3" wasn't enough (4 Nov, PRD v0.8.3)

Phase 5 added rescue, throttling and the other baselines. The first real run looked wrong: `place_once` rescued 3,532 jobs out of 6,975, and its clean-job intensity got worse, not better. The v0.8.1 fix stopped queued jobs competing with themselves, but a job *placed* for later still was: it was scored behind every other plan at its datacentre, including plans that release after it. Letting every pending job keep its place cut rescues to 939 and brought intensity back to 638.3 g/kWh.

The deadline misses are now explained too. 87 % are jobs that outran their 90th-percentile estimate: deferring them spends slack they turn out to need. Rescue lowers misses from 7.34 % to 6.24 %, but nothing can rescue a job that has already started.

## 12. The core claim holds (4 Nov)

Decision-flip went in as a subclass of fixed-savings, so at θ = 0 the only difference is a cheap check that skips re-scorings which could not have moved the job. On the real week the two policies produced byte-identical job and event logs, with 66 % fewer full re-scorings. The pass rate is 33.8 %, not the 18.3 % estimated without queues, but well inside what the screen needs.

## 13. The experiment runner and the first table (4 Nov, PRD v0.8.4)

Metrics, `compare`, `sweep`, `report` and the dashboard went in, so one command now produces the table for the Phase 2 review. All seven policies ran on the real week. Two things stand out, and neither is a conclusion yet. FCFS has the lowest all-jobs emissions on this week, which is the long-job noise from section 9. And θ now really does turn down moves (3,834 to 1,795), which the v0.7 width could never do, though the width's fallback still fires on 30 % of comparisons, above its 10 % flag.

## 14. Tools used along the way

| Tool | Used for |
|---|---|
| Python 3.12, **uv** | Project, dependencies, running everything (`uv run …`) |
| pandas, numpy | Data processing and the simulator's numerics |
| pytest, ruff | Tests and code style; must pass before any commit |
| git, GitHub | Version control; teammates push to `main` |
| openpyxl, xlrd | Reading Grid-India Excel reports (optional extra) |
| PyMuPDF | Reading the CEA PDF to extract the emission-factor table |
| Grid-India file API, Mendeley public API | Downloading raw Indian data |
| docx (JavaScript) + Microsoft Word | Building and checking the Word guide |
| Claude Code | Drafting docs, research, code and checks, guided by `CLAUDE.md` |

## 15. Where things stand and what's next

**Done:**
- Spec (PRD v0.8.5) and docs.
- Build phases 1, 2, 3 and 4. Phase 2 is complete, with real Indian data, and `validate` passes.
- Local-split steps 1–3.
- Build phases 5, 6 and 7: every policy, P1 proved on real data, and the experiment runner.

**Next:**
1. Build phase 8: validation replicates, sweeps, threshold freeze.
2. Deployment step 4 (`dcservice.py`), then the scripted driver and `local_cluster.sh`.
3. Install Docker Desktop for step 8.

**Still open:**
- **B1:** the mentor confirms the scope, now including the v0.8 changes to the screen and θ.
- **B2:** NESO redistribution terms.
- **B3:** GPU and CPU power values (until resolved, kgCO2 is reported as relative).
