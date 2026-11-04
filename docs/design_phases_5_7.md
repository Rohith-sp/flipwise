# Design: build phases 5, 6 and 7 (baselines, decision-flip, experiment runner)

Status: **design notes, 2 Nov 2026; updated 4 Nov.** `docs/prd.md` v0.8.3 is authoritative and differs from this proposal in these ways:

- **C2:** the PRD's `w_ab` adds a paired runtime term, `½ |Δ(r_q95) − Δ(r_q05)|`, instead of leaving runtime out. Default θ is 0.1.
- **C3 and C7 are in the PRD since v0.8.1.** C7 is written as a gain strictly above 0, not above `ε_tie`, in every policy with an acceptance rule. C3 covers every pending incumbent since v0.8.3 (D44), as §2 here proposed.
- **C5:** the PRD limits rescue differently: no repeat rescue on a fallback placement, a queued job is rescued only if a feasible alternative exists, and one rescue per release.
- **C6:** same instant, different labels. PRD day 25 equals this document's day 21.
- **FCFS tie-break rotation** is a PRD addition.

The FCFS and `place_once` figures in §1.3 predate those changes. Current figures are in PRD §10.11.

"Steps 5, 6, 7" means roadmap phases 5–7 in PRD §18. They are not deployment-track steps 5–7, which are a separate list.

---

## 1. What the real data showed

To test the design before building it, I ran throwaway scripts on the first validation week: trace days 21–28, carbon start 3 Jul 2023, 10 % sampling (6,976 jobs). Thresholds were not tuned on it, and no test-period data was touched.

There were two kinds of measurement:

- **Proxy:** 1,800 of those jobs, placed and re-evaluated at every forecast update under the fixed-savings rule with `g_rel = 0.05`. Queues are ignored (`w = 0`), which gives 12,966 "pending job × update" checks.
- **Real run:** the existing simulator running `fcfs` and `place_once` on all 6,976 jobs. Stand-ins: power 0.3 kW/GPU and 0.01 kW/core, and CPU/memory capacity set so GPUs bind. kgCO2 is relative (B3).

### 1.1 The PRD's screen filters nothing

The screen has to save full re-scorings, and H1 needs at least 50 % saved. Share of checks that pass the screen (lower is better):

| Bound | Pass rate |
|---|---|
| PRD §10.4 as written | **100 %** |
| PRD, also counting the partial slots it drops | 94 % |
| Also limited to slots before the job's deadline | 54 % |
| **Recommended: empty-queue bound (§4.2)** | **18.3 %** |
| Checks where a move really clears the gate (the floor) | 9.7 % |

Why the PRD bound fails:

- It drops partial slots, so a job with `r_q50 < 3600` gets `LB = 0` and always passes. That covers 57 % of checks.
- It searches 9 days for the cheapest window, although a job can only use slots before its deadline.

The recommended bound had zero soundness violations (`Ŝ_b < LB`) on all 12,966 checks. The proxy ignores queues, so the real pass rate will differ. Measuring it is part of phase 6.

### 1.2 The noise margin θ does almost nothing as specified

`w_ab` includes runtime spread, and median `(r_q95 − r_q05) / r_q50` is about 11. The result:

- `w_ab > 2 × Ŝ_a` on **98.7 %** of comparisons, so `INTERVAL_TOO_WIDE` sets θ to 0 there.
- On the remaining 1.3 %, the margin is so large that at θ = 0.5 no move survives.

So `decision_flip(θ > 0)` is nearly identical to `fixed_savings`, and H2 can't be tested. Runtime is also the wrong thing to count. A job that runs long costs more at both `a` and `b`, so this uncertainty mostly cancels in the comparison.

Share of fixed-savings moves that survive:

| θ | PRD width | Width without runtime spread |
|---|---|---|
| 0.05 | not in grid | 48.6 % |
| 0.10 | not in grid | 28.1 % |
| 0.25 | 98.7 % | 12.3 % |
| 0.50 | 98.6 % | 5.9 % |
| 1.00 | 98.6 % | 1.4 % |

Without runtime spread, θ behaves like a real dial, but the sensible range is lower than the PRD's grid. Calibration residuals are wide: `e05` is about −210 to −245 and `e95` about +174 to +277 g/kWh, so `w_ab ≈ Ŝ` (median 0.97).

### 1.3 First real results

| Policy | Wall time | Intensity (g/kWh) | Miss rate | Notes |
|---|---|---|---|---|
| `fcfs` | 29 s | 665.6 | 2.25 % | One job unfinished at the 15-day stop |
| `place_once` | 116 s | 644.9 | 7.30 % | 535 fallbacks; mean deferral 3.4 h; also one job unfinished |

Carbon-aware placement alone gains only 3.1 % here and triples misses, on one week. Re-planning may not add much on top. PRD §25 accepts that outcome, but the team should expect it.

Rough cost: about 50,000 pending checks per week at 12 ms per full re-score gives about 10 minutes per `fixed_savings` run. The saving from the screen is therefore real wall time too.

---

## 2. PRD changes that need your approval (v0.8)

| # | PRD | Change | Why |
|---|---|---|---|
| C1 | §10.3–10.4, R-TRIG-1 | Replace the `m_p` bound with the empty-queue bound (§4.2). The soundness test covers feasible candidates. | §1.1 |
| C2 | §10.5, §10.10, §14.6 | `w_ab` uses `r_q50` on both sides and keeps carbon and wait spread. θ grid becomes 0, 0.05, 0.1, 0.25, 0.5. Current width becomes new ablation A7. | §1.2 |
| C3 | §9.3 | An incumbent keeps its own place in the projected order, instead of being treated as last in priority. | §3.2 |
| C4 | §10.2 vs §10.7 | These contradict each other on an incumbent with unknown carbon: rescue or keep. Choose **keep**, since missing data isn't an operational violation. | Contradiction |
| C5 | §10.2 | Rescue moves a job only if it helps; otherwise it logs `RESCUE_NOOP`. Rescues don't count towards `max_moves`. | §3.4 |
| C6 | §6.3, §14.2 | Trace day 0 := Monday 1970-01-05 00:00 UTC+8 (`trace_epoch_s = 316800`). | Measured from the first job, day 21 is a Wednesday 14:38, but §6.3 needs a Monday. With this epoch, every slice starts on a Monday. |
| C7 | §10.5 | Acceptance also needs `gain > ε_tie`. | One real job has zero power, so `0 ≥ 0` would move it repeatedly. |

---

## 3. Phase 5: baselines and the plumbing they need

### 3.1 Scenario builder

Add `scenario.build_replicate(cfg, replicate, seed) -> Scenario`. Each step is from the PRD:

1. Read `jobs_v2020.csv`, filter to the trace slice, and sample with `sha256(seed:job_id)`.
2. `estimates.fit_runtime()`: per-user quantiles from trace days 0–21, with the GPU-class fallback (§6.5).
3. Convert time: `arrival = C0 + trace_arrival − T0`. Deadline: `arrival + 14400 + 2 × r_q90`.
4. Capacity from ρ (§8.1), then exclude and count jobs that don't fit. At 10 % sampling and ρ = 0.7, `cap_gpu ≈ 180` per datacentre and nothing is excluded.
5. `carbon.fit_residuals()` on 13 Mar – 30 Jun. It must **expand full vintages**. `carbon_forecast.csv` is a change-log, so using its rows directly would give biased quantiles. Cache the result to a file.
6. Load forecast rows for the replicate window only, and hash inputs into `scenario_hash`.

`Residuals` also needs to become per-region, because §6.8 will always pick per-region at these row counts. `flipwise run` needs `--config`.

### 3.2 Planner changes

| Change | Reason |
|---|---|
| `planner.rescore(view, job)` for incumbents, skipping the range check | `evaluate()` today rejects any queued incumbent as `OUT_OF_RANGE`, because its release slot is in the past. Every queued job would look infeasible. |
| Incumbent start read from its own place in the profile (C3); the profile records each job's start | Treating it as last overstates its wait, which biases towards moving and triggers false rescues. It also makes Stage 1 a lookup instead of 3 profile rebuilds per job. |
| Profile cache keyed with `exclude` only for a job actually placed at that datacentre | Today every job misses the cache at all 9 `(dc, q)` profiles. |
| Prefix-sum arrays per `(vintage, region)` for F, L and U | §9.4 asks for this. Today each score loops in Python over every slot the job crosses. |
| `best_alternative(view, job)`: best feasible candidate other than the incumbent | §10.5 |

### 3.3 Simulator changes

- **Moves apply one at a time.** `on_carbon_update` becomes a **generator**. The existing `for d in ...: self._apply(d)` loop then applies each move before the policy resumes, so later jobs see the new congestion (§10.6). No simulator API change is needed. If a policy built a list instead, every job would pile into the same cheap slot.
- New hooks: `on_release(view, job_id)` for rescue at release, and `on_tick(view)` with `PERIODIC_TICK` events.
- `Decision` gains `LB, w_ab, g_min, theta_eff, w_lo, w_hi`. `decisions.csv` already has most of those columns, unfilled.
- Kinds get separate counting: `MOVE` adds to `n_moves`, `RESCUE` adds to `rescued` (never set today). Check-only kinds just log.
- `PolicyStats` holds call counts and `perf_counter` seconds, and goes to `metrics.json` only. Those files aren't in the byte-identity check, so determinism holds.
- Replace the per-event `all(...)` finish check with a counter, and default `debug=False` on real runs.

### 3.4 Rescue

Used by every policy except `fcfs`, at every `CARBON_UPDATE` and at `JOB_RELEASE`:

```text
inc = rescore(job)
if inc is feasible:                  no rescue
if inc.reason == NO_CARBON:          log NO_CARBON_INCUMBENT, keep (C4)
b = best_alternative(job)
if b exists:                         RESCUE to b
else f = earliest-finish fallback
  if f finishes strictly earlier:    RESCUE to f, deadline_risk = 1
  else:                              RESCUE_NOOP, keep
```

The `RESCUE_NOOP` branch prevents two real bugs the PRD doesn't cover:

- **Queue-loss spiral.** A job with no feasible option would be "rescued" every 30 minutes, going to the back of the queue each time. 535 jobs (7.7 %) already hit the fallback at arrival.
- **Infinite loop.** A rescue at `JOB_RELEASE` pushes a new release at the same instant, which triggers another rescue.

### 3.5 Policy structure

```text
Policy
├── Fcfs                  no rescue, never re-plans
└── Replanner             initial_placement, rescue, throttling (cooldown_s, max_moves)
    ├── PlaceOnce         rescue only
    ├── Periodic(T)       rescue on updates; on_tick re-plans all; accept gain > ε_tie
    ├── PredError(ε)      EL Phase 3
    └── FixedSavings(g)   every update: Stage 2, then accept gain ≥ g_min
        └── DecisionFlip(g, θ)   adds the screen and θ margin
```

`DecisionFlip` subclasses `FixedSavings` on purpose: sharing the code makes P1 close to true by construction. Throttling state stays in a policy-owned dict, so `SchedulerView` stays read-only. Parameters live in `configs/policies.yaml`. `pig` waits for EL Phase 3 (§18.1).

### 3.6 Exit tests

R-LEAK-1 (extended to all policies), R-TRIG-7, R-SIM-5, part of R-POL-1. Periodic tick ordering: at T = 30 min a tick falls after `JOB_RELEASE` (§8.4), so its behaviour legitimately differs from `fixed_savings`.

---

## 4. Phase 6: decision-flip

### 4.1 The idea

Every 30 minutes the forecast changes and each pending job faces the question: "should you still run where and when you planned?" Answering it properly means scoring up to 147 candidates per job, and usually the answer is no. Decision-flip answers it in three rising-cost steps:

| Step | Question | Cost |
|---|---|---|
| Incumbent re-score | What does my current plan cost now, and is it still feasible? | One lookup |
| **Stage 1: screen** | Even with empty queues, could any option save enough? | Cheap array operations |
| **Stage 2: full re-score and flip test** | Is the real best option better by more than forecast noise? | Up to 147 candidates |

The screen only skips work and can't change a decision, which is the claim P1 tests. θ is what can change decisions, and it's a separate question (H2). That separation keeps results attributable.

### 4.2 Stage 1: the empty-queue bound

`LB_j` is the lowest score any feasible candidate could have, using the job's own forecast but pretending no other job exists:

```text
for each eligible datacentre d:
    for every start a in [slot0, deadline − r_q90]:
        cost(d, a) = K × Σ τ_k(a, r_q50) × F(r_d, k, v)
LB = min over all d, a  × (1 − 1e-12)
pass iff Ŝ_a − LB ≥ g_min
```

Why it is sound, for all three parts of a feasible alternative:

- **Queues can only delay.** Waiting moves the start later but still inside the searched range. A feasible candidate has `s + w_hi + r_q90 ≤ deadline`, and `w_mid ≤ w_hi`, so its start is at most `deadline − r_q90`. The `feasibility = point` ablation uses `deadline − r_q50` as the limit instead.
- **Checking finite starts is enough.** `cost(a)` is piecewise linear in `a`, with corners only where the start or end hits a slot boundary. Evaluating those two families therefore finds the true minimum over all start seconds.
- **Unknown carbon is excluded.** A window containing an unknown slot counts as infinite cost, because such candidates are `NO_CARBON` and can't be chosen.

The `(1 − 1e-12)` guards against rounding breaking P1. With prefix sums, each datacentre costs two numpy operations.

### 4.3 Stage 2: the flip test

```text
b = best_alternative(job)
w_ab = ½[(U_a − L_a) + (U_b − L_b)]     # at r_q50, spanning w_lo..w_hi and e05..e95 (C2)
need = g_min + θ_eff × w_ab
MOVE iff (Ŝ_a − Ŝ_b) > ε_tie and (Ŝ_a − Ŝ_b) ≥ need
```

`θ_eff` is 0 when an interval is malformed or too wide (§10.7). After C2 these fallbacks should become rare, and a run where they exceed 10 % is flagged.

### 4.4 Full algorithm

```python
def on_carbon_update(self, view):  # generator: moves apply one at a time
    for job in view.pending_jobs():  # (deadline, arrival, job_id)
        inc = planner.rescore(view, job)
        if not inc.feasible:
            yield self.rescue(view, job, inc)
            continue
        if job.n_moves >= self.max_moves or view.now_s < self.last_rescore[job] + self.cooldown_s:
            yield log("THROTTLED")
            continue
        g = self.gate(job, inc.s_hat)  # max(g_abs, g_rel × Ŝ_a) + κ…
        if self.screen:  # False only for fixed_savings and A2
            lb = planner.lower_bound(view, job)
            if inc.s_hat - lb < g:
                yield log("SCREEN_FAIL", lb=lb, g_min=g)
                continue
        self.stats.stage2_calls += 1
        b = planner.best_alternative(view, job)
        self.last_rescore[job] = view.now_s
        if b is None:
            yield log("NO_ALTERNATIVE")
            continue
        theta, w = self.margin(inc, b)
        gain = inc.s_hat - b.s_hat
        if gain > EPS_TIE_KG and gain >= g + theta * w:
            yield move(b, ...)
        else:
            yield log("KEEP", ...)
```

Worked example, with `g_rel = 0.05` and θ = 0.05:

| Update | Ŝ_a | LB | Max possible gain | `g_min` | Outcome |
|---|---|---|---|---|---|
| 14:00 | 10.0 kg | 9.7 kg | 0.3 | 0.5 | `SCREEN_FAIL`, no planner call |
| 14:30 (forecast revised) | 10.0 kg | 8.6 kg | 1.4 | 0.5 | Stage 2 |

At 14:30, queues push the real best option to `Ŝ_b = 8.9` kg, so the gain is 1.1. With `w_ab = 9.7`, `need = 0.5 + 0.05 × 9.7 = 0.985`, so the job **moves**. With a gain of 0.8 it would log `KEEP`: a real improvement, but too small to trust against forecast noise.

### 4.5 Properties and tests

| Test | Method |
|---|---|
| R-TRIG-1 soundness | 2,000 random forecasts and jobs: `LB ≤ Ŝ_c` for every feasible candidate. Include non-slot starts and unknown slots. |
| **R-TRIG-2 / P1 (the core claim)** | At θ = 0 with the same parameters as `fixed_savings`: identical `jobs.csv` and `events.log` bytes, identical state-changing rows in `decisions.csv`, and fewer `stage2_calls`. On toy and the dev replicate. |
| R-TRIG-3, 4, 5 | Hand-computed toy cases: flip, uniform shift (no flip), small gain |
| R-TRIG-6 | One unit test per §10.7 fallback row |
| P2 | Report `screen_pass_rate` from a real run. The design fails if it is above about 0.9. |
| A2 | Screen off at θ > 0: same decisions as the base policy |

P1 holds with `cooldown_s = 1800`, because `capture_coverage.csv` has no two captures less than 1,800 s apart (checked over the whole file). With a 7,200 s cooldown the two policies can legitimately diverge, as §10.9 notes.

**Toy fixtures.** PRD §15.3 describes a toy with one job per case (J2 moves, J4 small gain, and so on), but the committed toy is a different scenario with hand-computed results and tests that depend on them. Keep it, and add `tests/fixtures/toy_replan/` for those cases, with non-zero residuals so θ has an effect.

---

## 5. Phase 7: experiment runner

**For EL Phase 2** (§18.1), build `metrics`, a one-replicate `compare` and `dashboard`. The rest waits for EL Phase 3.

| Module | Design | Tests | When |
|---|---|---|---|
| `metrics.py` | Pure function from `jobs.csv`, `decisions.csv` and `PolicyStats` to `metrics.json`, following §14.1. Reports `null` when a denominator is 0. Needs `plan_w_lo/hi` saved at the last placement for wait coverage. | R-MET-1 | EL2 |
| Run layout | `results/<run_id>/` with `run_id = sha256(config + scenario_hash + policy + seed)[:12]`. A manifest with git commit, `uv.lock` hash and `uses_oracle` (hard-coded today). | R-REP-1 | EL2 |
| `compare` | Builds one scenario per replicate, runs every policy on it, skips runs whose `run_id` exists, and writes `summary.csv`. `ProcessPoolExecutor` (stdlib) for parallelism; outputs don't depend on completion order. | R-FAIR-1 | EL2 (one replicate) |
| `dashboard.py` | Static HTML from saved CSVs with embedded Matplotlib PNGs. Tabs: timeline, Pareto, results table; θ sweep shows "no data" if absent. kgCO2 labelled relative. | Missing CSV doesn't crash it | EL2 |
| `sweep` | Grid in `configs/sweeps/*.yaml`; each cell is a `compare`. Adds `dflip_worse_than` (§14.8). | Small toy grid | EL3 |
| `report` | Rebuilds tables and figures from saved logs only; `paired.csv` with 10,000-resample bootstrap (fixed seed). Refuses mismatched scenario hashes. | R-REP-2, R-FAIR-1 | EL3 |

Carbon-interval coverage depends only on the replicate, not the policy, so it is computed once per replicate.

---

## 6. Build order

| # | Work | Done when |
|---|---|---|
| 0 | Data path and `.gitignore` fix; approve §2 and write PRD v0.8 | `flipwise validate` is OK |
| 1 | Prefix sums, profile changes, generator hooks, new decision fields | Existing 41 tests and `smoke` still pass |
| 2 | `fit_runtime`, `fit_residuals`, `build_replicate`, `run --config` | `fcfs` and `place_once` run on the dev week, reproducibly |
| 3 | `rescore`, rescue, throttling, `FixedSavings`, `Periodic` | Phase 5 exit tests pass; decision logs readable |
| 4 | `lower_bound`, screen, θ, fallbacks | Toy flip, no-flip and small-gain pass; **P1 holds on toy** |
| 5 | P1 and `screen_pass_rate` on the dev week | Measured. If P1 fails, stop and fix: it is a bug. |
| 6 | `metrics`, one-replicate `compare`, `dashboard` | Comparison table and `dashboard.html` for the review |
| 7 | `sweep`, `report`, `pred_error`, `pig` | EL Phase 3 |

Step 4 is the riskiest and step 5 is the proof, so finish them before polishing step 6. The deployment track continues in parallel. Moving rescue logic into the simulator doesn't affect `datacentre.py`, so `dcservice.py` work is safe to start now.

---

## 7. Data status (2 Nov 2026)

- All processed files in `data/flipwise-data-v1-2861e79/data/processed/` match the SHA-256 values in `data/manifests/`.
- `data/raw/` is gone. Phases 5–7 need only processed files, except for one number: §8.1 scales CPU and memory capacity from `pai_machine_spec` cluster totals, which the PRD doesn't record.
- `configs/base.yaml` still points at `data/processed/`, so `flipwise validate` fails until the path changes.
- The new folder is **not** covered by `.gitignore` (`git status` lists it), so `git add .` would commit about 250 MB of data, against CLAUDE.md.
- `prd (1).md` in the repo root is an old v0.3 copy (still "FlipSim", GB world). It shouldn't be treated as current.
