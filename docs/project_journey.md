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

## 8. Tools used along the way

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

## 9. Where things stand and what's next

**Done:**
- Spec (PRD v0.7) and docs.
- Build phases 1, 2, 3 and 4. Phase 2 is complete, with real Indian data, and `validate` passes.
- Local-split steps 1–3.

**Next:**
1. Build phase 5 (baselines), then 6 (decision-flip).
2. Deployment step 4 (`dcservice.py`), then the scripted driver and `local_cluster.sh`.
3. Install Docker Desktop for step 8.

**Still open:**
- **B1:** the mentor confirms the scope.
- **B2:** NESO redistribution terms.
- **B3:** GPU and CPU power values (until resolved, kgCO2 is reported as relative).
