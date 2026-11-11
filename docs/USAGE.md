# Flipwise usage guide

A hands-on guide to running Flipwise: the simulator, the experiment commands, the local split (three datacentres as separate processes) and the Docker cluster. Every command here was run against this repository on 11 Nov 2026. For what the project is and why, read `README.md` and `docs/explanation.md`; for the exact specification, `docs/prd.md`.

**Contents**

1. [Before you start](#1-before-you-start)
2. [Five-minute demo on the toy scenario](#2-five-minute-demo-on-the-toy-scenario)
3. [Reading the outputs](#3-reading-the-outputs)
4. [Real data: the dev week and comparisons](#4-real-data-the-dev-week-and-comparisons)
5. [The policies and how to change them](#5-the-policies-and-how-to-change-them)
6. [Local split demo (DT1)](#6-local-split-demo-dt1)
7. [Docker demo (DT2)](#7-docker-demo-dt2)
8. [Checking that all modes agree](#8-checking-that-all-modes-agree)
9. [Troubleshooting](#9-troubleshooting)
10. [Rules to keep](#10-rules-to-keep)

---

## 1. Before you start

**Needs:** Linux (bash) or Windows 11 (PowerShell or Git Bash), [uv](https://docs.astral.sh/uv/), and Python 3.12 (uv installs it). Docker is needed only for section 7. Quote every path: the project folder name contains spaces.

**Install and check** (identical on Linux and Windows):

```bash
uv sync                                   # install from uv.lock
uv run ruff check . && uv run ruff format --check .
uv run pytest -q                          # 248 tests, about 30 s; needs no real data
```

**Real data** is only needed for sections 4 and 7's dev-week run. It lives in `data/processed/` (not in git; get the data zip from the team) and is checked with:

```bash
uv run flipwise validate --config configs/base.yaml     # prints "validate: OK"
```

If `validate` fails, stop: runs on different data cannot be compared with the team's results (see `data/README.md`).

**All commands at a glance** (`uv run flipwise <command> --help` shows every flag):

| Command | What it does |
|---|---|
| `smoke` | Toy scenario, all policies, compared with the hand-computed answers in `expected.yaml` |
| `run` | One policy on one scenario, written to `results/<run_id>/` |
| `compare` | All (or chosen) policies on identical replicates, with summary tables and figures |
| `sweep` | A grid over parameters; each cell is a `compare` |
| `report` | Rebuild tables and figures from saved logs only |
| `dashboard` | A static `dashboard.html` from saved results |
| `validate` | Check config, data checksums, coverage and the train/validation/test split |
| `ingest`, `build-forecasts` | Rebuild `data/processed/` from raw data (not needed day to day) |
| `dc-serve` | Run one datacentre as an HTTP service (used by the local split and Docker) |

## 2. Five-minute demo on the toy scenario

The toy scenario (`tests/fixtures/toy/`) has 3 datacentres and 6 jobs, small enough to check by hand. It needs no real data.

**Step 1: the correctness check.**

```bash
uv run flipwise smoke
```

Prints `smoke: OK` when every policy's emissions, placements and counts match `tests/fixtures/toy/expected.yaml`. Outputs go to `results/smoke/<policy>/`.

**Step 2: run one policy.**

```bash
uv run flipwise run --scenario tests/fixtures/toy --policy decision_flip --out demo
```

Prints `wrote demo/b6cb4fdc4c19`. The folder name is the run id, a hash of everything the run depends on, so the same inputs always give the same folder. Inside:

```
decisions.csv  events.log  jobs.csv  manifest.json  metrics.json  policy_stats.json
```

**Step 3: compare all seven policies.**

```bash
uv run flipwise compare --scenario tests/fixtures/toy --policies all --out demo
```

Prints `wrote demo/compare_<hash>`, holding `summary.csv` (one row per policy), `paired.csv`, `carbon_timeline.csv`, `carbon_coverage.csv`, `runs.json` and `figures/*.png`. Open `summary.csv` first: columns include `kg_co2`, `energy_kwh`, `miss_rate` and the re-score counts.

**Step 4: the dashboard.**

```bash
uv run flipwise dashboard --runs demo/compare_<hash> --out demo/dashboard.html
```

Open `demo/dashboard.html` in a browser (no server needed). It shows the timeline, a Pareto chart and the results table.

**Step 5: the core claim (P1).** At θ = 0, `decision_flip` makes exactly the same decisions as `fixed_savings` but with fewer full re-scorings. This runs on the real dev week, so it needs the data:

```bash
uv run python scripts/check_p1.py        # prints "P1: HOLDS"
```

## 3. Reading the outputs

**A run folder** (`results/<run_id>/`):

| File | Contents |
|---|---|
| `jobs.csv` | One row per job: where and when it ran (`dc_id`, `start_s`, `end_s`), `wait_s`, `energy_kwh`, `kg_co2`, `deadline_missed`, `n_moves` |
| `decisions.csv` | Every scheduling decision, in order: `time_s`, `job_id`, `kind`, the candidate it considered, and the numbers behind it (`S_a`, `S_b`, `w_ab`, `theta_eff`, `reason`) |
| `events.log` | The raw event stream: arrivals, dispatches, completions |
| `metrics.json` | Totals: emissions, energy, completion, decision counts, `fallback_share` (comparisons with θ switched off) |
| `manifest.json` | How the run was made: config, git commit, data checksums, package versions, mode, and the `overhead` block (wall-clock time and calls per datacentre) |
| `policy_stats.json` | Per-policy counters, such as full re-scorings |

**Decision kinds** in `decisions.csv`:

| `kind` | Meaning |
|---|---|
| `PLACE` | First placement of a job |
| `KEEP` | Re-evaluated, and the current plan stayed |
| `MOVE` | The job was moved to a better pending placement |
| `SCREEN_FAIL` | The cheap screen showed no alternative could clear the gate, so the full re-score was skipped (this is what makes `decision_flip` cheap) |
| `NO_ALTERNATIVE` | No other feasible placement existed |
| `FALLBACK` | No candidate met the deadline, so the job takes the earliest conservative finish and is flagged as deadline risk (`reason` = `FALLBACK_EARLIEST_FINISH`) |
| `RESCUE` | A pending job at deadline risk was moved to a placement that finishes sooner |
| `RESCUE_NOOP` | A rescue was considered and the plan stayed (its `reason` says why, for example `NOT_EARLIER`) |
| `THROTTLED` | Re-planning skipped by the cooldown or the move limit |

Separately, when the uncertainty interval is too wide to be informative (`w_ab` above `w_max × Ŝ_a`), the noise margin θ is switched off for that comparison and the row's `reason` is `INTERVAL_TOO_WIDE`. The share of such comparisons is `fallback_share` in `metrics.json`; the team accepted it at the frozen `w_max` = 2 and reports it with the results (D49).

**Emissions are relative.** Until the power values are cited (blocker B3), every kgCO2 figure compares policies with each other and is not an absolute number. The `power_label` column says so.

## 4. Real data: the dev week and comparisons

All of this needs `data/processed/` (section 1).

```bash
# One policy on the dev week (about 70 s)
uv run flipwise run --config configs/base.yaml --policy decision_flip

# All seven policies, in parallel (about 8 minutes with 7 jobs)
uv run flipwise compare --config configs/base.yaml --jobs 7

# A threshold sweep (θ) over four policies
uv run flipwise sweep --config configs/base.yaml --sweep configs/sweeps/theta.yaml \
  --policies fcfs,place_once,fixed_savings,decision_flip --jobs 4

# Dashboard with the sweep tab
uv run flipwise dashboard --runs results/compare_<hash> --sweep results/sweep_<hash>

# Rebuild tables and figures from saved logs without re-running anything
uv run flipwise report --runs results/compare_<hash>
```

**Splits.** `--split dev` (the default) is one week for development. `--split validation` is the 12 replicates the thresholds were frozen on (about 6 hours). **`--split test` may be run once only**, after everything is frozen (PRD §14.3); do not use it to try things out.

**Reusing results.** A finished run is reused when its `run_id` matches. The `run_id` does not include the code, so after changing simulator, planner or policy code, delete `results/` or old runs come back as if they were current.

**Reference numbers.** The validation results (12 replicates, 300 runs) are in `docs/validation/`, with its own README. `docs/validation/dashboard.html` opens with no setup.

## 5. The policies and how to change them

Policy names for `--policy` and `--policies`:

| Policy | What it does |
|---|---|
| `fcfs` | First come, first served; no carbon awareness |
| `place_once` | Carbon-aware first placement, never re-plans |
| `periodic` | Full re-score every `T_s` seconds |
| `fixed_savings` | Re-score on every update; move if the saving exceeds `g_rel` |
| `pred_error` | Re-score when the forecast error exceeds `epsilon` |
| `decision_flip` | Cheap screen first, then a full re-score, then the gate and the noise margin `theta` |
| `pig` | Perfect-information oracle, an upper bound; the only policy allowed to see the future |

All policies share one scenario, planner, feasibility check and dispatcher, so they differ only in when they re-plan and when they accept a move.

**Parameters** live in `configs/policies.yaml` (frozen on validation data, so do not edit them to improve a test result) and in `configs/base.yaml` (data paths, the load `rho`, the splits). Override one value for a single run with `--set`:

```bash
uv run flipwise run --config configs/base.yaml --policy decision_flip --set scenario.rho=0.5
```

`--set` needs `--config`; the toy scenario has no config sections to override. An unknown key stops with a `ConfigError` rather than being ignored.

## 6. Local split demo (DT1)

The simulator normally keeps the three datacentres as objects in one program. In the local split, each datacentre is its own process with an HTTP server, and the coordinator (`flipwise run --mode remote`) talks to them. The coordinator owns the simulated clock; the services never read the wall clock. The result must be byte-identical to the in-process run.

**One command** (starts three services on ports 8101–8103, waits for `/health`, runs, stops them):

```bash
bash scripts/local_cluster.sh --scenario tests/fixtures/toy --policy decision_flip
```

```powershell
.\scripts\local_cluster.ps1 --scenario tests/fixtures/toy --policy decision_flip
```

Expected: `local_cluster: 3 services up on http://127.0.0.1:8101,...`, then `wrote results/<run_id>`, then `local_cluster: done`. The run folder also holds `dc-0.log`, `dc-1.log`, `dc-2.log`, and its `manifest.json` records `"mode": "remote"` and the three URLs. Any run arguments after the script's own flags go to `flipwise run`, so the dev week is:

```bash
bash scripts/local_cluster.sh --config configs/base.yaml --policy decision_flip
```

Script flags: `--base-port 8101`, `--n-dc 3`, and `--crash DC:N`.

**Crash demo.** `--crash 1:5` makes datacentre 1 exit on its fifth request:

```bash
bash scripts/local_cluster.sh --crash 1:5 --scenario tests/fixtures/toy --policy decision_flip
```

Expected: the coordinator stops with `DeploymentError: POST http://127.0.0.1:8102/enqueue: Remote end closed connection without response`, the script prints `run failed (exit 1)` and exits 1, no `metrics.json` is written, and no process is left on ports 8101–8103.

**By hand, in four terminals** (to see what the script does):

```bash
uv run flipwise dc-serve --dc-id 0 --port 8101     # terminal 1
uv run flipwise dc-serve --dc-id 1 --port 8102     # terminal 2
uv run flipwise dc-serve --dc-id 2 --port 8103     # terminal 3
curl http://127.0.0.1:8101/health                  # {"status": "ok", "dc_id": 0, ...}
uv run flipwise run --mode remote --scenario tests/fixtures/toy --policy decision_flip   # terminal 4
```

Stop the services with Ctrl-C. `/health`, `/enqueue`, `/remove`, `/dispatch`, `/complete` and `/state` are the whole interface (PRD §13.5). The services enforce the rules themselves: removing a running job returns 409 `MIGRATION`, and time going backwards returns 409 `TIME_BACKWARDS`.

## 7. Docker demo (DT2)

One image runs the three datacentre containers (`dc-delhi`, `dc-mumbai`, `dc-chennai`, ids 0, 1, 2) and the coordinator. The services are reachable only from the coordinator: no ports are published.

```bash
export GIT_COMMIT=$(git rev-parse HEAD)          # PowerShell: $env:GIT_COMMIT = git rev-parse HEAD
docker compose up --build --abort-on-container-exit --exit-code-from coordinator
docker compose down
```

Expected: the three services become healthy, the coordinator prints `wrote results/<run_id>`, and `docker compose up` exits 0. Results appear in `./results/` on the host. `GIT_COMMIT` is stored in the manifest because the image has no `.git`.

**Other runs.** The default run is the toy with `decision_flip`. Set `FLIPWISE_RUN_ARGS` for anything else, for example the dev week (needs `data/processed/`, which is mounted read-only):

```bash
FLIPWISE_RUN_ARGS="--config configs/base.yaml --policy decision_flip" \
  docker compose up --abort-on-container-exit --exit-code-from coordinator
```

`FLIPWISE_RESULTS` changes where results are written, and `FLIPWISE_TAG` the image tag.

**Notes.**
- Fedora and other SELinux systems: the compose file already labels its mounts (`:z`); a hand-written `docker run -v` needs the same suffix or you get `PermissionError`.
- The first build takes a few minutes and makes a 733 MB image (mostly pandas, numpy and matplotlib).
- Windows needs Docker Desktop. `docker_check.sh` is bash, so on Windows run the compose commands above by hand or from Git Bash.

## 8. Checking that all modes agree

`scripts/docker_check.sh` is the acceptance test for DT2. It runs the cluster in Compose and compares it with an in-process run:

```bash
bash scripts/docker_check.sh toy      # every policy on the toy (R-DEP-1)
bash scripts/docker_check.sh dev      # decision_flip on the dev week, about 4 minutes (R-DEP-2)
bash scripts/docker_check.sh crash    # kill a datacentre container mid-run (R-DEP-3)
bash scripts/docker_check.sh all      # all three; the default
```

It prints `PASS` or `FAIL` for each case and exits non-zero on any failure. `dev` and `crash` need `data/processed/`.

**Comparing two runs by hand** (any two modes). The three files below must be byte-identical; `manifest.json` and `metrics.json` differ only in the mode and the overhead block:

```bash
cmp inproc/<run_id>/jobs.csv      remote/<run_id>/jobs.csv
cmp inproc/<run_id>/decisions.csv remote/<run_id>/decisions.csv
cmp inproc/<run_id>/events.log    remote/<run_id>/events.log
```

```powershell
Get-FileHash inproc\<run_id>\jobs.csv, remote\<run_id>\jobs.csv    # the two hashes must match
```

A remote run gets its own `run_id` (the mode is part of it), so the two folders have different names. Reference hashes: the toy `decision_flip` run has `jobs.csv` SHA-256 starting `07e367b1`, and the dev week starts `3f222d58`.

**Where the time goes.** On one Linux machine the dev week took 69 s in-process, 101 s as a local split and 130 s in Docker, with the same 58,454 datacentre calls each. The overhead is per call and depends on the host (finding F20 in `docs/decisions.md`); `manifest.json` records it for every run.

## 9. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `validate` fails, or `FileNotFoundError` for `data/processed/...` | The data is missing or different. Unzip the team's data zip into the repo root so `data/processed/` exists |
| `port 8101 is in use; nothing started` | A previous cluster is still running. Find it with `ss -ltn \| grep 810` (Linux) or `Get-NetTCPConnection -LocalPort 8101` (PowerShell) and stop that process. Never run two copies of `tests/test_local_cluster.py` at once: they pick the same ports |
| Old numbers come back after a code change | Results are reused by `run_id`, which does not cover code. Delete `results/` |
| `ConfigError: --set ...: 'scenario' is not a section of the config` | `--set` needs `--config configs/base.yaml`; the toy scenario has no config |
| `PermissionError: ... results/...` in a container | SELinux: add `:z` to the bind mount. Or the host folder is not writable by uid 1000 |
| `docker compose up` hangs on the coordinator | A service is not healthy. Run `docker compose logs dc-delhi` (or the other two) |
| The coordinator ends with `DeploymentError` | A datacentre service died or was killed. This is the intended failure: the run aborts rather than continue with wrong numbers |
| `ruff format --check` fails | Run `uv run ruff format .` |

## 10. Rules to keep

- **Same inputs, same outputs.** A fixed config and seed give byte-identical `events.log`, `jobs.csv` and `decisions.csv`. Do not add wall-clock time or unseeded randomness to the simulation.
- **No tuning on the test period.** Thresholds are frozen; the test split runs once.
- **kgCO2 is relative** until B3 is resolved. Say so in anything you show.
- **Do not commit** `data/raw/`, `data/processed/`, `results/`, `.venv`, `.env`, `*.pem` or AWS credentials.
- After any design change, update `docs/prd.md` and `docs/decisions.md` together, and `docs/HANDOFF.md` before ending a session.
