# Flipwise

**Efficient Re-Evaluation of Pending Workloads in Carbon-Aware Datacentre Scheduling**

An offline research simulator that tests *when* a carbon-aware scheduler should re-plan a job that is still waiting to run.

RV College of Engineering · Experiential Learning, V Semester, AY 2026–27 · UN SDG 9 (Industry, Innovation and Infrastructure)

> Status: **EL Phase 1 (pitch) complete. Now on EL Phase 2 (partial results).** No code exists yet. The spec is [docs/prd.md](docs/prd.md) (v0.5).

---

## 1. Problem and contribution

A scheduler picks a datacentre and start time for each job using carbon-intensity forecasts. Those forecasts are revised every 30 minutes, so a job's placement can stop being the best one before the job starts. If you never re-plan, you miss savings. If you re-plan on a timer or at every update, you spend planner time, and jobs bounce around on forecast noise.

**Decision-flip-triggered re-evaluation** (the proposed policy) works in two stages. On each forecast update:

1. **Stage 1, a cheap screen.** A lower bound on every candidate's score checks whether *any* alternative could beat the current placement by the benefit gate `g_min`. If none could, the job is skipped.
2. **Stage 2, a full re-score.** The job moves only if the best alternative wins by `g_min + θ · w_ab`, where `w_ab` is the combined width of the forecast, runtime and queue-wait uncertainty intervals.

The key property: **at θ = 0 the policy makes exactly the same decisions as a fixed-savings gate that re-scores every job, but it makes fewer planner calls.** Any difference in emissions therefore comes from θ, and any difference in overhead comes from the screen.

## 2. Scope

- An offline, deterministic, command-line **research simulator**. It is not a production scheduler.
- **Indian conditions.** Three *virtual* datacentres in India's datacentre hubs, each on its own regional grid: **Delhi NCR** (Northern), **Mumbai** (Western), **Chennai** (Southern), with pooled GPU, CPU and memory capacity. Time runs in IST.
- It replays one-week slices of the Alibaba PAI GPU trace v2020. Carbon "truth" is Indian regional intensity built from generation by fuel × CEA emission factors. No archive of Indian carbon *forecasts* exists, so the forecasts the scheduler sees are Indian truth plus the **real forecast-error paths** of an archived operational forecast (NESO, Great Britain), scaled to Indian levels. Policies only see forecasts available at that moment; an evaluator scores outcomes against the truth they never see.
- Running jobs are never migrated. Results are **modelled** operational CO2 (IT energy only), not measured reductions.
- **Deployment track** (PRD §13.5): the same simulation can run with each virtual datacentre as a separate service: **DT1** local processes, then **DT2** Docker, then **DT3** AWS. The coordinator keeps a simulated clock, so every mode must produce byte-identical results to the normal in-process run. Research results always come from the in-process mode.
- Out of scope: real infrastructure control, a web app (the dashboard is a static HTML file), measuring real cloud emissions, and DRO (extension X1).

## 3. Datasets

Raw and processed data are never committed. Download links and checksums will go in `data/README.md`. The full link list is in [docs/helpfullinks.md](docs/helpfullinks.md).

| Dataset | Use | Source | Licence / terms |
|---|---|---|---|
| Alibaba Cluster Trace GPU v2020 (`pai_job_table`, `pai_task_table`, `pai_machine_spec`) | Job arrivals, runtimes, resource requests | [alibaba/clusterdata](https://github.com/alibaba/clusterdata/tree/master/cluster-trace-gpu-v2020) · [split-file mirror](https://github.com/qzweng/clusterdata-cluster-trace-gpu-v2020-data) | Research/study use; cite Weng et al., NSDI '22 |
| Indian regional generation by fuel, Mar 2023 – Feb 2024 (≤ 1 h) | Indian carbon truth (PRD §6.2.2) | Grid-India reports first; fallbacks in PRD §6.2.2 | **To confirm (blocker B4)** |
| CEA CO2 Baseline Database | Emission factor per fuel; grid-average factor for the static check | [cea.nic.in](https://cea.nic.in/) | Government of India publication |
| NESO forecast-vintage archive, Mar 2023 – Feb 2024 | Real forecast-error paths, applied to Indian truth (PRD §6.2.4) | [nmpowell/carbon-intensity-forecast-tracking](https://github.com/nmpowell/carbon-intensity-forecast-tracking) | MIT (archive); NESO terms still to check (blocker B2) |

One script downloads and extracts the three Alibaba archives, clones the NESO forecast archive (the source of forecast-error paths) at the pinned commit and runs the audit. Details, checksums and the pinned archive commit are in [data/README.md](data/README.md).

```bash
# Linux / macOS / Git Bash
bash scripts/download_data.sh
```

```powershell
# Windows PowerShell
powershell -ExecutionPolicy Bypass -File scripts\download_data.ps1
```

`flipwise ingest` checks the archives' SHA-256 against the upstream README and exits if they don't match.

## 4. Setup

Requires [uv](https://docs.astral.sh/uv/); uv installs Python 3.12 itself (`.python-version`), so the system Python version does not matter. Works on Linux and Windows 11.

Install uv once:

```bash
# Linux / macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```powershell
# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then, identical on both (quote the path if it contains spaces):

```bash
uv sync                                    # create .venv from uv.lock
uv run ruff check . && uv run ruff format --check .   # PowerShell 5: use ';' instead of '&&'
uv run pytest -q                           # unit, invariant and toy-scenario tests
uv run flipwise smoke                      # toy scenario, all policies, < 5 s
uv run python scripts/audit_v2020.py       # reproduce the PRD §6.1 trace audit
```

Stack: pandas, numpy, PyYAML and matplotlib. Optional: plotly, via `uv sync --extra dashboard`. Dev tools: pytest and ruff. The event engine is a custom `heapq` loop, not SimPy (see PRD §5, D3).

### Planned CLI

| Command | Purpose |
|---|---|
| `flipwise ingest alibaba --raw data/raw/v2020 --out data/processed` | Verify checksums, build `jobs_v2020.csv` and a manifest |
| `flipwise ingest carbon --archive <clone> --start 2023-03-13 --end 2024-01-31 --regions 1,13,7 --out data/processed` | Build forecast, truth and coverage CSVs |
| `flipwise validate --config configs/base.yaml` | Check config, data, coverage and that calibration/test windows don't overlap |
| `flipwise run --config configs/base.yaml --policy decision_flip` | One run → `results/<run_id>/` |
| `flipwise compare` / `sweep` / `report` | All policies on identical inputs; parameter grids; rebuild tables from saved logs |
| `flipwise dashboard --runs results/compare_<hash>` | Write a static, offline `dashboard.html` from saved CSVs |
| `flipwise dc-serve --dc-id 0 --port 8101` | Run one datacentre as an HTTP service (deployment track) |
| `bash scripts/local_cluster.sh --config configs/base.yaml --policy decision_flip` | DT1: start three local datacentre services, run with `--mode remote`, stop them on exit |
| `docker compose up --build --abort-on-container-exit` | DT2: the same run in four containers |

## 5. Repository layout

Current:

```text
flipwise/
├── README.md
├── CLAUDE.md               # instructions for Claude Code
└── docs/
    ├── prd.md              # authoritative spec (v0.5)
    ├── explanation.md      # plain-language explanation (matches PRD v0.5)
    ├── helpfullinks.md     # dataset, paper and tool links
    └── helpfullinks.txt    # original plain-text version of the links
```

Target (PRD §13.1):

```text
├── pyproject.toml, uv.lock, LICENSE, .gitignore
├── Dockerfile, docker-compose.yml           # deployment track DT2
├── configs/          base.yaml, energy.yaml, policies.yaml, sweeps/*.yaml
├── scripts/          download/checksum scripts, local_cluster.sh (DT1), aws/ (DT3)
├── src/flipwise/     cli, config, models, ingest, carbon, energy, estimates,
│                     simulator, datacentre, dcservice, planner, policies,
│                     metrics, reporting, dashboard
├── tests/            fixtures/toy/ (6 jobs, 3 DCs, hand-checked expected.yaml) + test_*.py
├── data/             README.md; raw/ and processed/ are git-ignored; manifests/
└── results/          git-ignored; run outputs and dashboard.html
```

## 6. Roadmap

The PRD defines nine build phases (§18). The EL reviews map onto them as follows (§18.1).

| EL phase | Build phases | Deployment track | Status |
|---|---|---|---|
| 1. Pitch | — | — | ✅ Done |
| **2. Partial results** | 1–6, plus a minimal part of 7 | DT1 local split | ⏳ **Current** |
| 3. Full results and paper (final) | Rest of 5 and 7, then 8–9 | DT2 Docker, then DT3 AWS | Not started |

The deployment track runs in parallel, owned by one team member, and never blocks the research phases.

### EL Phase 2: partial results

**Precondition:** the mentor confirms that decision-flip is the core contribution and DRO is an extension (blocker B1).

Work on a small slice: **one validation week** of the Alibaba trace (dev sampling 0.1) with the matching Indian truth and forecast vintages.

| # | Build phase | What gets built | Exit criterion |
|---|---|---|---|
| 1 | Setup and audit | Repo, `pyproject.toml`, `uv.lock`, ruff, pytest; download v2020; clone the archive at a fixed commit | Checksums match; a script reproduces the PRD §6.1 audit numbers |
| 2 | Canonical data | `ingest alibaba`, `ingest india` (truth), `ingest carbon` (error paths), `build-forecasts`, manifests, `validate` | Processed CSVs plus ingest/coverage reports; B2 and B4 answered |
| 3 | Deterministic core | `models`, `simulator` (events, job states), `datacentre` (queue, dispatch) behind a `DatacentreClient` interface, toy fixture, `fcfs` | Toy FCFS output equals `expected.yaml` |
| 4 | Energy and place-once | `energy`, `carbon` views, `planner` (candidates, feasibility, scoring), `place_once` | Toy emissions exact; static-factor test passes |
| 5 | Baselines (partial) | `estimates` (runtime quantiles, wait profiles), `periodic(T)`, `fixed_savings(g)`, rescue, throttling | Baselines run on the toy scenario |
| 6 | Decision-flip | Lower-bound screen, noise margin, interval fallbacks | Toy flip / no-flip / small-gain cases pass; P1 holds |
| 7 (min) | Runner | `run`, metrics, `dashboard` only | One table and `dashboard.html` |

Policies in Phase 2: `fcfs`, `place_once`, `periodic(T)`, `fixed_savings(g)`, `decision_flip(g, θ)`.

**Must show at the Phase 2 review:**
1. A toy scenario whose kgCO2 is checked by hand (R-EN-1, toy `expected.yaml`), showing the simulator is correct.
2. At θ = 0, decision-flip makes **identical decisions** to fixed-savings with fewer `stage2_calls` (P1, R-TRIG-2). This is the core claim.
3. One comparison table for the validation week: kgCO2, deadline-miss rate and re-score count per policy.
4. A `dashboard.html` with the timeline, Pareto and results-table tabs. The θ-sweep tab may show "no data".
5. **DT1 local split:** the toy scenario run through three local datacentre services (`scripts/local_cluster.sh`), with output hashes equal to the in-process run. If DT1 is late, items 1–4 are presented without it.

kgCO2 stays labelled **relative** until power parameters are cited (blocker B3).

#### Deployment track DT1: local split

| What gets built | Exit criterion |
|---|---|
| `dcservice.py` (stdlib HTTP service and client), `flipwise dc-serve`, `flipwise run --mode remote`, `scripts/local_cluster.sh` (starts services on ports 8101–8103, waits for `/health`, runs, cleans up on exit or Ctrl-C) | Toy run through three services is byte-identical to in-process for every Phase 2 policy; killing a service aborts the run cleanly |

The service skeleton and script can start now against the API in PRD §13.5. The equivalence test needs build phase 3.

### EL Phase 3: full results and paper (final)

| Build phase | What gets built |
|---|---|
| 5 (rest) | `pred_error(ε)`, the error-magnitude trigger and key comparison for the contribution, plus the `pig` perfect-information reference |
| 7 (rest) | `compare`, `sweep`, `report`, paired bootstrap statistics, full plots and manifests |
| 8 | Real-trace evaluation: fit residual and runtime quantiles; validation sweeps (`g_rel`, θ, ε, T); freeze thresholds; run the test set **once**; sensitivity sweeps (load, carbon spread, forecast-error and interval scaling, deadline slack, energy multipliers); ablations A0–A6 |
| 9 | Analysis and packaging: report figures, limitations, a reproducibility README (a clean clone reproduces the summary tables from raw downloads) |
| DT2 Docker | One image, `docker-compose.yml` with three datacentre containers and a coordinator; `docker compose up` from a clean clone reproduces the in-process toy and dev-replicate outputs |
| DT3 AWS | The DT2 image on three small EC2 instances (default `ap-south-1`, Mumbai); same outputs as in-process; latency and cost reported; budget alert first and `teardown.sh` after every session. Starts only after the main test results exist and the AWS account question (O8) is settled |

Data split: runtime fit on trace days 0–20 · residual fit on carbon data from 13 Mar – 30 Jun 2023 · validation on trace days 21–41 with Jul–Aug 2023 · test on trace days 42–69 with Sep 2023 – Jan 2024. That gives 12 validation and 16 test replicates per policy.

**Phase 3 deliverables:** final test results with bootstrap intervals, the **worse-regime table** (every setting where a simpler baseline beats decision-flip), the full dashboard including the θ sweep, the reproducibility package, the Docker setup, an AWS run matching the in-process output, and the paper/report. B3 must be resolved before any absolute kgCO2 is reported.

Optional, only after the main results exist: X1 (Global–Local DRO planner) and X9 (live Streamlit viewer).

### Hypotheses under test

| ID | Hypothesis |
|---|---|
| H1 | At θ = 0, decision-flip makes ≥ 50 % fewer full re-scorings than fixed-savings, with identical decisions |
| H2 | With θ > 0 it moves jobs less often, and emissions stay within the seed-to-seed spread |
| H3 | The benefit of re-planning over place-once grows with carbon spread across regions and with deadline slack |
| H4 | Carbon intervals that are too narrow increase churn; intervals that are too wide suppress useful moves |

## 7. Open items

| ID | Item | Needed by |
|---|---|---|
| B1 | Mentor confirms decision-flip is the core contribution and DRO is extension X1 | Before Phase 2 work |
| B2 | Archive coverage for the three GB error-source regions and NESO redistribution terms | Build phase 2 |
| B4 | Indian regional generation-by-fuel data at ≤ 1 h resolution for Mar 2023 – Feb 2024, its licence, and the CEA database version | Build phase 2 |
| B3 | Cited power values: MISC GPU, CPU per core, utilisation factor `f` | Before absolute kgCO2 (build phase 8) |
| O1 | Confirm the principal meant the CEA CO2 Baseline Database | Report |
| O7 | Check that the name `flipwise` is free on PyPI | Before publishing the package |
| O8 | AWS account and spending limit for DT3 (credits, free tier, or a member's account) | Before DT3 |

## 8. References

- **Docs:** [PRD](docs/prd.md) · [Plain-language explanation](docs/explanation.md) · [Links](docs/helpfullinks.md)

Key references (full list in PRD §19):

- Weng et al., "MLaaS in the Wild," USENIX NSDI '22. [link](https://www.usenix.org/conference/nsdi22/presentation/weng)
- Hanafy et al., "CarbonScaler," SIGMETRICS 2024 (source of the `pred_error` baseline).
- Xu et al., "GREEN," USENIX NSDI 2025 (source of the `periodic` baseline).
- Li, Liu, Ding, "Uncertainty-Aware Decarbonization for Datacenters," HotCarbon '24 (closest prior work to the θ margin).
- Pinedo, *Scheduling: Theory, Algorithms, and Systems*, 6th ed., Springer, 2022. [doi](https://doi.org/10.1007/978-3-031-05921-6)
- Central Electricity Authority, CO2 Baseline Database for the Indian Power Sector. [link](https://cea.nic.in/)
- N. Powell, carbon-intensity-forecast-tracking (NESO forecast archive). [link](https://github.com/nmpowell/carbon-intensity-forecast-tracking)

Licence: MIT, if the mentor approves (open).
