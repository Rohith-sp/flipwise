# CLAUDE.md

Flipwise: an offline, deterministic discrete-event simulator that tests **when** to re-plan pending jobs across three virtual datacentres under **Indian conditions** (Delhi NCR, Mumbai, Chennai on the NR/WR/SR grids, IST), using the Alibaba GPU trace v2020, Indian carbon truth (generation by fuel × CEA factors) and forecasts built from real NESO forecast-error paths (PRD §6.2). RVCE EL V sem project. Repo: https://github.com/Rohith-sp/flipwise

## Source of truth

- `docs/prd.md` (v0.6) is authoritative: formulas, data rules, requirement IDs (R-*), decisions (D*), open items (B*/O*). If code and PRD disagree, flag it; don't silently pick one.
- `docs/explanation.md` is the plain-language version. `README.md` is the short overview and roadmap.
- A design change means editing the PRD (and its changelog) in the same change.

## Reading the docs cheaply

`prd.md` is about 1,150 lines and `explanation.md` about 1,200. Never read either whole. Grep for the heading, then read only that range:

| Need | Grep in `docs/prd.md` |
|---|---|
| Indian carbon truth, synthetic forecasts, data schema | `^#### 6\.2\.` and `^### 6\.` |
| Emissions equations and units | `^### 7\.1` |
| Job states, event priorities, information boundary | `^### 8\.` |
| Candidates, wait estimate, scoring, feasibility | `^### 9\.` |
| Decision-flip screen, gate, pseudocode | `^### 10\.` |
| Baseline policies | `^## 11\.` |
| Stack and allowed dependencies | `^### 12\.1` |
| Layout, module contracts, CLI | `^### 13\.[1-4]` |
| Deployment track (services, API, DT1–DT3) | `^### 13\.5` |
| Metrics definitions | `^### 14\.1` |
| A requirement and its acceptance test | the ID, e.g. `R-TRIG-2` |
| Roadmap, EL phase mapping | `^## 18\.` |

Other token rules: use Grep/Glob, not whole-file reads, for search. Never open `data/raw/`, `data/processed/` or `results/` files whole; use `head`, or pandas `nrows=`, or `wc -l`. Don't re-read a file you just edited. Run the narrowest test first (`uv run pytest -q tests/test_x.py -x`), then the full suite once at the end.

## Commands

```bash
uv sync                                   # install from uv.lock
uv run ruff check . && uv run ruff format --check .
uv run pytest -q                          # all tests; toy scenario only, no real data needed
uv run flipwise smoke                     # toy scenario, all policies, compare to expected.yaml
uv run flipwise run --config configs/base.yaml --policy decision_flip
bash scripts/local_cluster.sh --config configs/base.yaml --policy fcfs   # DT1 (Linux bash / Git Bash)
docker compose up --build --abort-on-container-exit                      # DT2
```

Before finishing any code change: ruff check, ruff format, and the relevant tests pass. Report failures with their output; don't claim success otherwise.

## Rules that must not break

1. **Determinism.** Same config + seed gives byte-identical `events.log`, `jobs.csv`, `decisions.csv` (R-SIM-1). No wall clock in simulation logic (`time.perf_counter` only for overhead metrics), no unseeded randomness, no iteration over unordered sets where order matters. Tie order: events `(time_s, priority, seq)`; jobs `(deadline_s, arrival_s, job_id)`; datacentres `dc_id`.
2. **Information boundary.** Policies see only `SchedulerView` (PRD §8.7): never `runtime_actual_s`, `end_s` of running jobs, carbon truth, or forecast captures later than now. Only `pig` gets `OracleView`. Leakage tests R-LEAK-1/2 enforce this.
3. **No migration.** Running jobs are never moved (`MigrationError`).
4. **Units.** Times are integer Unix seconds UTC; slots are 1,800 s; power kW, energy kWh, intensity gCO2/kWh, emissions kgCO2. Keep units in variable names when ambiguous (`runtime_s`, `p_gpu_kw`).
5. **Same inputs for every policy.** Policies share one scenario object, planner, feasibility checker, dispatcher and rescue rule; only trigger and acceptance differ (PRD §11).
6. **Deployment modes are transports, not new logic.** The coordinator owns the simulated clock; datacentre services never read the wall clock. `--mode remote` must give byte-identical outputs to `--mode inproc` (R-DEP-1). Datacentre logic lives once, in `datacentre.py`; `dcservice.py` only wraps it.
7. **Train/validate/test split.** Never tune thresholds on test-period data (PRD §14.3).

## Code conventions

- Python 3.12, ruff line length 100, type hints on public functions, `dataclasses` for models.
- Dependencies: only those in PRD §12.1 (pandas, numpy, PyYAML, matplotlib; plotly optional; stdlib `http.server`/`urllib` for services). Adding one requires a PRD edit first.
- Errors are explicit: `ConfigError`, `CarbonDataError`, `MigrationError`, `SimulationInvariantError`, `DeploymentError`. No bare `except`; no silent retries.
- Tests mirror modules (`tests/test_<module>.py`). Toy fixtures live in `tests/fixtures/toy/`, with hand-computed answers in `expected.yaml`. Every requirement test names its R-ID in the test name or docstring.
- Comments explain *why* (a PRD decision, an invariant), not *what*.

## Environment

- Supported on **Linux** (bash) and **Windows 11** (PowerShell or Git Bash). Every documented command must have a form for both; `uv run ...` commands are identical on both.
- Paths may contain spaces (Linux: `~/Desktop/Carbon aware scheduer/flipwise`, Windows: `C:\5TH SEM EL\flipwise`), so always quote paths. Use `pathlib` in Python, never hard-coded separators.
- Shell scripts (`*.sh`) target bash (native on Linux, Git Bash on Windows); a PowerShell twin (`*.ps1`) exists where Windows users need one without Git Bash. Prefer `uv run` over activating the venv.
- Raw data layout: `data/raw/v2020/` (Alibaba archives + extracted CSVs), `data/raw/carbon-intensity-forecast-tracking/` (NESO archive clone: GB error paths only), `data/raw/india/` (Indian generation, B4), `data/raw/carbon/` (NESO portal cross-check CSV). See `data/README.md`.
- Never commit `data/raw/`, `data/processed/`, `results/`, `.venv`, `.env`, `*.pem` or AWS credentials. DT3 scripts read credentials from the AWS CLI profile only. Run `scripts/aws/teardown.sh` after any AWS session.
- Commit or push only when asked.

## Current status

EL Phase 1 done; Phase 2 in progress. Build phases 1, 3 and 4 done; phase 2 partly done (`ingest alibaba`, `ingest carbon` → GB error paths, `build-forecasts`, `validate`; `ingest india` waits for B4 data). Toy `smoke` matches `expected.yaml`. Next: phase 5 (`estimates`, real-trace scenario builder, `periodic`, `fixed_savings`, rescue, throttling), then 6 (decision-flip). In parallel, DT1 local split and DT2 Docker (stretch) in the order of PRD §18 "Deployment track": `DatacentreClient` → `dcservice.py` → scripted driver → `local_cluster.sh` → `--mode remote` → Docker (`datacentre.py` already exists). Open blockers: B1 (mentor confirms scope), B2 (NESO redistribution terms; coverage answered), B3 (power values; until resolved, report kgCO2 as relative), B4 (Indian generation-by-fuel data). Update this section when a phase completes.
