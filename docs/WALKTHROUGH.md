# Flipwise, step by step

A complete walkthrough of what Flipwise does, from the raw data to the final results, for a team member who knows the project is "about re-evaluation" but not how it works. Every step names the file or function that does it, and the core of the document traces a real six-job scenario minute by minute with the real numbers from its decision log.

Read in order. Section 13 is a glossary of every term; section 14 answers whether the system could use machine learning.

**Contents**

1. [The question we are answering](#1-the-question-we-are-answering)
2. [Step 1: the inputs we prepare](#2-step-1-the-inputs-we-prepare)
3. [Step 2: from inputs to a scenario](#3-step-2-from-inputs-to-a-scenario)
4. [Step 3: the simulator loop](#4-step-3-the-simulator-loop)
5. [Step 4: how one job is planned](#5-step-4-how-one-job-is-planned)
6. [Step 5: what happens when the forecast changes](#6-step-5-what-happens-when-the-forecast-changes)
7. [Step 6: decision-flip in detail](#7-step-6-decision-flip-in-detail)
8. [The toy scenario, minute by minute](#8-the-toy-scenario-minute-by-minute)
9. [Step 7: from one run to a result](#9-step-7-from-one-run-to-a-result)
10. [Step 8: running the datacentres as separate services](#10-step-8-running-the-datacentres-as-separate-services)
11. [What we found](#11-what-we-found)
12. [The phases, and where each step was built](#12-the-phases-and-where-each-step-was-built)
13. [Glossary](#13-glossary)
14. [Is it rule-based, and could it use machine learning?](#14-is-it-rule-based-and-could-it-use-machine-learning)

---

## 1. The question we are answering

A computing job (here, a machine-learning job on GPUs) uses electricity. How much CO2 that electricity causes depends on **where** and **when** it runs, because each regional grid burns a different mix of coal, gas, hydro, solar and wind, and the mix changes through the day. So a scheduler that can choose the datacentre and the start time can lower emissions, as long as the job still meets its deadline. This is **carbon-aware scheduling**, and it is well studied.

Our project is about the part that is *not* well studied. The scheduler decides using a **forecast** of grid carbon, and the forecast is revised every half hour. A job planned at 9:00 for "Chennai at 15:00" may, by 11:00, have a clearly better option. Every waiting job can therefore be **re-evaluated**: score all its options again and perhaps move it. Re-evaluating costs computation, and moving a job costs it its place in the queue. The question is:

> **When is it worth re-evaluating a waiting job?**

We propose a rule, **decision-flip**, that re-evaluates only when a cheap check says the decision could actually change, and moves the job only when the gain is larger than the forecast's own uncertainty. We test it against simpler rules in a simulator.

Three limits apply throughout:

- **Nothing real is scheduled.** We replay history in a simulator.
- **Running jobs are never moved** (no migration). Only jobs still waiting can be re-planned.
- **Emissions are a bracket.** GPU power comes from NVIDIA datasheets per GPU type, and how hard each job really used its GPUs comes from Alibaba's own measurements. Because an idle GPU's draw is unknown, kgCO2 is given as a range: `measured` (lower bound) to `nameplate` (upper bound). CPU power per core is still an assumption (10 W). Until 12 Nov every kgCO2 figure was relative, using a placeholder of 0.3 kW for every GPU.

## 2. Step 1: the inputs we prepare

Before any simulation, four kinds of data are prepared once and stored in `data/processed/`. The commands are `flipwise ingest` and `flipwise build-forecasts`; `flipwise validate` checks the result.

**2.1 Jobs, from the Alibaba GPU trace.** Alibaba published a two-month log of its GPU cluster (cluster-trace-gpu-v2020, 1,897 machines, 6,742 GPUs). For every job we keep: when it arrived, how many GPUs, CPU cores and GB of memory it asked for, its user, and how long it really ran (`runtime_actual_s`). Code: `ingest.py`, output `jobs_v2020.csv`. The trace has no deadlines and no locations, so we add both (2.4 and 3.1).

**2.2 Carbon "truth", for India.** For three regional grids, Northern (Delhi NCR), Western (Mumbai) and Southern (Chennai), we need the real carbon intensity of every half hour: grams of CO2 per kWh. India publishes generation by fuel, so:

1. From Grid-India reports, take each region's electricity generation by fuel per day (coal, lignite, gas, hydro, nuclear, solar, wind, ...), and shape it within the day using Grid-India's national SCADA profile by fuel (`scripts/download_india.py`, `scripts/build_india_generation.py`).
2. Multiply each fuel by its **emission factor** from the official CEA CO2 Baseline Database (v19.0): coal 978, lignite 1,286, gas 478 gCO2/kWh; hydro, nuclear, solar and wind 0 (`configs/energy.yaml`).
3. Divide total emissions by total generation: that is the region's intensity for that half hour.

The result is `carbon_truth.csv`: `A(r, k)`, the true intensity of region `r` in slot `k`. Only the evaluator sees it.

**2.3 Carbon forecasts.** The scheduler must act on forecasts, not truth. No archive of Indian carbon forecasts exists, so we build realistic ones:

1. Britain's grid operator (NESO) publishes a carbon forecast every half hour, and someone archived every published version (the "forecast-vintage archive"). For British regions we therefore know exactly how wrong each forecast was, at each lead time, and how it was revised over time. These are the **error paths** (`gb_error_paths.csv`).
2. Each Indian region borrows the error path of one British region (NR from London, WR from South Wales, SR from East Midlands), scaled to the Indian level: `F(r, k, v) = max(0, A(r, k) + α × s_r × E(k, v))`. Here `v` is the time the forecast was published (its **capture** or **vintage**), `E` is the British error for that slot and capture, `s_r` rescales British errors to Indian intensities, and `α` (base 1) can make forecasts better or worse for sensitivity tests.
3. Output: `carbon_forecast.csv`, one row per slot per capture.

Why not just add random noise? Random noise would make each new forecast jump around, so every re-planning policy would see fake opportunities. Real forecast errors drift smoothly, and that is what the error paths keep. The honest limitation: the errors have a real forecast's statistical shape, but their causes are British weather.

**2.4 Forecast uncertainty.** From the error history we learn how large errors usually are, per **lead time** (how far ahead the forecast slot is): the 5th and 95th percentiles of the error, `e05` and `e95`. Every forecast value then has an interval: "probably between F + e05 and F + e95". Code: `carbon.py` (`Residuals`), fitted on March to June 2023 only.

**2.5 Runtime estimates.** The scheduler is not allowed to know how long a job will really run. Instead, for each user with at least 20 jobs in trace days 0 to 21, we store the 5th, 50th, 90th and 95th percentiles of their past runtimes (`r_q05`, `r_q50`, `r_q90`, `r_q95`). New users get the percentiles of their GPU-size class. Code: `estimates.py` (`fit_runtime`). These are frozen before any evaluated job, so no job helps estimate itself.

## 3. Step 2: from inputs to a scenario

A **scenario** is one self-contained world to simulate. `scenario.py` (`build_replicate`) builds it:

1. **Pick a slice.** One week of trace arrivals (for example trace days 25 to 32) and one Monday of Indian carbon (for example 3 July 2023). The pair is a **replicate**. The run horizon is 15 days: 7 days of arrivals plus 8 days for the last jobs to finish.
2. **Sample jobs.** Keep 10 % of the week's jobs (sampling 0.1, D46), chosen by a hash of the job id so it is the same every time.
3. **Map trace time to Indian time.** Trace clock hours are lined up with IST clock hours, so daytime job submissions meet the Indian solar midday.
4. **Add deadlines.** `deadline = arrival + 4 h + 2 × r_q90`. It uses only the estimate, so it tells the scheduler nothing new about the real runtime.
5. **Set up three datacentres.** dc0 Delhi NCR (region 1), dc1 Mumbai (region 2), dc2 Chennai (region 3), each with GPU, CPU and memory capacity sized from the trace's cluster totals so the offered load is about 70 % (`rho = 0.7`).
6. **Attach carbon** truth and the forecast vintages for those weeks, and the power model (PRD §7.2, D58). The scheduler scores every job with one fixed scale, `GPUs requested × 0.3 kW + CPU cores requested × 0.01 kW`: power multiplies all options of a job alike, so the scale doesn't change which option wins, and keeping it fixed keeps the frozen thresholds meaningful. The evaluator charges either **nameplate** power, `GPUs requested × datasheet kW of that GPU type + cores × 0.01 kW` (V100 0.30, P100 0.25, T4 0.07, older MISC GPUs 0.15 kW; upper bound), or the **measured** power: `GPUs requested × datasheet kW × share actually used + cores actually used × 0.01 kW`, with the use measured by Alibaba (`pai_sensor_table`, summed per job by `flipwise ingest usage`). The evaluator's power is applied after all decisions are made, so it changes only the kgCO2.

Validation uses 12 replicates (3 trace weeks × 4 carbon Mondays in July and August 2023); the test set uses 16 (4 × 4, September 2023 to January 2024). The train, validation and test periods never overlap, in jobs or in carbon (`configs/base.yaml`, `splits`).

The **toy scenario** (`tests/fixtures/toy/`) is a hand-made scenario with 6 jobs, 3 datacentres of 4 GPUs each and 12 slots, whose correct answers were worked out by hand in `expected.yaml`. Section 8 walks through it.

## 4. Step 3: the simulator loop

`simulator.py` is a **discrete-event simulator**: instead of ticking every second, it keeps a list of future events and jumps from one to the next.

Event kinds, with their priority when several happen at the same second (lower goes first):

| Priority | Event | What happens |
|---|---|---|
| 1 | `CARBON_UPDATE` | A new forecast is published. The policy may re-evaluate pending jobs. Every 30 minutes |
| 2 | `JOB_COMPLETE` | A running job finishes and frees its GPUs; the datacentre then starts queued jobs that now fit |
| 3 | `JOB_ARRIVAL` | A job enters the system; the policy places it |
| 4 | `JOB_RELEASE` | A placed job's chosen start slot arrives; it joins that datacentre's queue |
| 5 | `PERIODIC_TICK` | For `periodic` only: its timer |
| 6 | `DEADLINE` | Bookkeeping when a deadline passes |

Events are ordered by `(time_s, priority, seq)`, where `seq` is a counter, so the order is always the same. With the same config and seed, every run produces byte-identical `events.log`, `jobs.csv` and `decisions.csv` (requirement R-SIM-1). No wall clock and no unseeded randomness are allowed in the simulation.

**A job's life:**

```
ARRIVAL -> planned (waiting for its release slot) -> RELEASE -> queued at a datacentre
        -> started when capacity is free -> running -> COMPLETE
```

While a job is **planned** or **queued** it is *pending* and may be re-planned. Once **running** it is never moved.

**Who knows what.** The policy works through a `SchedulerView`: it sees the forecasts published up to now, the runtime *estimates*, queues and capacities. It never sees the carbon truth, a job's real runtime, when running jobs will end, or future forecasts. Only `pig`, the oracle used as a reference, gets an `OracleView` with the truth. Tests R-LEAK-1 and R-LEAK-2 fail if this boundary leaks.

**Datacentres.** `datacentre.py` holds each datacentre's capacity, its FIFO queue and its running jobs, with five operations: `enqueue`, `remove`, `dispatch` (start every queued job that fits, first-fit in queue order), `complete`, and `state`. Removing a running job raises `MigrationError`.

## 5. Step 4: how one job is planned

When a job arrives, every carbon-aware policy calls the shared **planner** (`planner.py`). The planner works in five steps.

**Step 4.1: list the candidates** (`candidates`). A candidate is a pair *(datacentre, release slot)*: "join datacentre `d`'s queue at slot `s`". The slots run from the next half-hour boundary (`slot0`) to the latest slot that could still meet the deadline, at most 24 h ahead. Three datacentres × up to 49 slots = **at most 147 candidates**.

**Step 4.2: estimate the queue wait** (`estimates.build_profile`, `SchedulerView.projected_start`). Joining a queue at slot `s` does not mean starting at `s`; the datacentre may be busy. So for each datacentre the planner builds a **usage profile**: when each running job is expected to end (using its runtime estimate) and when each queued or planned job is expected to start and end. Then it finds the earliest time at or after `s` when this job fits. That gives the **wait** `w`, computed three times with different runtime percentiles: optimistic `w_lo`, middle `w_mid`, pessimistic `w_hi`.

**Step 4.3: score each candidate** (`evaluate`). The **score** `Ŝ` is the estimated kgCO2 of that candidate: power × the time the job runs in each half-hour slot × the forecast intensity of that slot, using start `s + w_mid` and runtime `r_q50`:

`Ŝ = P × Σ_slots (seconds in slot / 3600) × F(slot) / 1000`

It also gets an **interval** `[L, U]`: `L` uses the optimistic wait, the short runtime `r_q05` and the forecast plus `e05`; `U` uses `w_hi`, `r_q95` and `F + e95`.

**Step 4.4: check feasibility.** A candidate counts only if all hold:

| Check | Rule | If it fails |
|---|---|---|
| Fit | The job's request fits the datacentre's capacity | `NO_FIT` |
| Range | The slot is between `slot0` and the latest allowed | `OUT_OF_RANGE` |
| Start | A start exists in the profile | `NO_START` |
| Deadline | `s + w_hi + r_q90 ≤ deadline` (pessimistic) | `DEADLINE_RISK` |
| Carbon | Forecast exists for the slots needed | `NO_CARBON` |

**Step 4.5: choose.** Among feasible candidates, take the lowest `Ŝ`; ties go to the earlier start, then the lower `dc_id`, then the earlier slot. If none is feasible, take the candidate that would finish earliest under the pessimistic numbers, and flag the job as at deadline risk (`FALLBACK`).

The policy records the choice as a `PLACE` decision. The chosen candidate is the job's **incumbent** (its current plan).

## 6. Step 5: what happens when the forecast changes

Every 30 minutes a `CARBON_UPDATE` brings a new forecast. Each pending job's plan was chosen on an older forecast. The seven policies differ only in what they do now; everything else (planner, feasibility, datacentres, rescue) is shared, so the comparison is fair.

| Policy | At each forecast update |
|---|---|
| `fcfs` | Nothing. It never looked at carbon: each job went to whichever datacentre could start it soonest |
| `place_once` | Nothing. It placed each job carbon-aware once, on the forecast at arrival |
| `periodic` | Every `T` seconds (1,800), fully re-score every pending job; move if better by the gate |
| `pred_error` | Re-score a job only if the forecast over its planned window moved by more than `ε` (5 %) |
| `fixed_savings` | Fully re-score every pending job at every update; move if the saving beats the gate `g_rel` (1 % of its score) |
| `decision_flip` | Cheap screen first; full re-score only if the screen passes; move only if the gain beats the gate plus a noise margin |
| `pig` | Places once using the true future (truth and real runtimes); a reference, not a usable policy |

**Full re-score** means running steps 4.1 to 4.5 again for that job: up to 147 candidates, each needing a wait estimate. This is the expensive part, counted as `stage2_calls`.

**Moving a job** (`MOVE`): remove it from its queue if queued (it loses its place), set the new datacentre and slot, schedule a new release, and rebuild the affected wait profiles **before** the next job is considered, so two jobs do not both rush to the same cheap slot.

**Shared safety rules:**

- **Rescue.** If a pending job's plan can no longer meet its deadline, it is re-planned regardless of the policy's own rule (`RESCUE`, or `RESCUE_NOOP` if nothing better exists).
- **Throttle.** A job is re-planned at most once per 30 minutes and moved at most 3 times (`THROTTLED`).

## 7. Step 6: decision-flip in detail

Decision-flip (`policies.DecisionFlip`) handles each pending job, at each forecast update, in two stages.

**Stage 1: the screen (cheap).** Re-score only the incumbent `a` with the new forecast: `Ŝ_a`. Then compute a **lower bound** `LB`: the lowest score *any* feasible alternative could possibly have. It takes the cleanest carbon window available in any region between now and the latest start that still meets the deadline, and pretends there are no queues (`planner.lower_bound`). No real alternative can score below `LB`, because every feasible alternative starts somewhere in that window.

Compute the **gate**: the minimum gain worth moving for,

`g_min = max(g_abs, g_rel × Ŝ_a) + κ_switch + κ_queue (if queued) + λ_ovh`

With the frozen settings this is `0.05 × Ŝ_a`: 5 % of the current score (the other terms are 0).

If `Ŝ_a − LB < g_min`, then even the best imaginable alternative could not save enough, so a full re-score cannot change the decision. **Skip it** and log `SCREEN_FAIL`. This is where decision-flip saves its work: on real data about 60 % of checks stop here.

**Stage 2: full re-score.** Otherwise, run the planner over all candidates and take the best alternative `b`. Then decide.

1. **Noise width** `w_ab`: how uncertain is the comparison between `a` and `b`? Half the width of each option's interval (forecast and wait uncertainty, with runtime held at `r_q50`), plus half of how much the difference between them changes when the runtime is short (`r_q05`) or long (`r_q95`). Runtime enters only as a *difference*, because a long job costs more at either site.
2. **Fallback.** If `w_ab > w_max × Ŝ_a` (`w_max = 2`), the interval is too wide to mean anything: set θ to 0 for this comparison (`INTERVAL_TOO_WIDE`).
3. **The decision-flip condition.** Move to `b` only if

   `Ŝ_a − Ŝ_b ≥ g_min + θ × w_ab`

   that is, the gain beats both the gate and θ times the noise. θ is 0.1, frozen on validation data.

**Why it is safe: property P1.** With θ = 0 the condition is exactly `fixed_savings`'s condition, and the screen only skips jobs where that condition could not hold. So decision-flip makes exactly the same decisions as `fixed_savings` with fewer full re-scorings. This was checked on all 12 validation replicates: identical `jobs.csv` and `events.log`, with 62 % fewer full re-scorings (`docs/validation/p1.csv`).

## 8. The toy scenario, minute by minute

The toy (`tests/fixtures/toy/`) is small enough to follow every decision. All numbers below come from `expected.yaml` (worked out by hand) and from the run's real `decisions.csv`; `uv run flipwise smoke` checks they agree.

**Setup.** Three datacentres with 4 GPUs each: dc0 Delhi NCR (region 1), dc1 Mumbai (region 2), dc2 Chennai (region 3). Power is 1 kW per GPU (plus 0.01 kW per CPU core). Times are seconds after the start.

| Job | GPUs | Runtime | Arrives | Deadline |
|---|---|---|---|---|
| J1 | 2 | 3,600 s (1 h) | 0 | 21,600 |
| J2 | 2 | 3,600 s | 0 | 21,600 |
| J3 | 4 (+4 CPU cores) | 1,800 s | 0 | 21,600 |
| J4 | 1 | 1,800 s | 900 | 21,600 |
| J5 | 1 | 3,600 s | 900 | **2,000** (impossible) |
| J6 | 3 | 1,800 s | 1,800 | 21,600 |

Runtimes equal all their percentiles, so wait estimates are exact and the noise width is 0.

**Carbon.**

| Region | Forecast at t = 0 | Forecast from t = 3,600 | Truth |
|---|---|---|---|
| 1, Delhi (dc0) | 100 everywhere | **400 from t = 3,600 on** | 100, 100, then 400 |
| 2, Mumbai (dc1) | 300 | 300 | 300 |
| 3, Chennai (dc2) | 200 | 200 | 200 |

So at the start Delhi looks cleanest, and it is, but only for the first hour. The forecast published at t = 3,600 reveals that Delhi turns dirty. Jobs planned on the first forecast are now in the wrong place: this is exactly the situation re-evaluation is for.

### 8.1 What decision-flip does

**t = 0, carbon update and three arrivals** (log: `PLACE` ×3).

- **J1** (2 GPUs, 1 h): dc0 at 100 g/kWh scores 2 kW × 1 h × 100 / 1000 = **0.2 kg**, the lowest. Placed on dc0, slot 0. It starts at once.
- **J2**: the same, **0.2 kg** on dc0. dc0 now has all 4 GPUs busy until 3,600.
- **J3** (4.04 kW, 0.5 h): on dc0 it cannot start until J1 and J2 finish at 3,600, but its score there is still 4.04 × 0.5 × 100 / 1000 = **0.202 kg**, against 0.404 on dc2 and 0.606 on dc1. Placed on dc0, slot 0; it **queues** behind J1 and J2. This is the wait estimate at work: the planner knew J3 would start at 3,600, not 0.

**t = 900, two arrivals.**

- **J5** (1 GPU, 1 h, deadline 2,000): the earliest slot is 1,800, and 1,800 + 3,600 is after 2,000, so every candidate fails the deadline check. Fallback: the earliest finish is 5,400 at dc1 or dc2; the tie goes to dc1. Log: `FALLBACK`, score 0.3, `FALLBACK_EARLIEST_FINISH`. J5 will miss its deadline under any policy.
- **J4** (1 GPU, 0.5 h): on dc0 it would start at 5,400 (after J1, J2 and J3), scoring 1 × 0.5 × 100 / 1000 = **0.05 kg**, against 0.1 on dc2. Placed on dc0, slot 1,800. Log: `PLACE`, 0.05.

**t = 1,800, J6 arrives; releases.**

- **J6** (3 GPUs, 0.5 h): dc0 from 5,400, score **0.15 kg**, against 0.3 on dc2. Placed on dc0. Log: `PLACE`, 0.15.
- J5 is released and starts on dc1. J4 and J6 join dc0's queue behind J3: the queue is [J3, J4, J6].
- J5's release triggers a rescue check: it is already on a fallback placement, so it is left alone. Log: `RESCUE_NOOP`, `ON_FALLBACK`.

So far decision-flip has behaved exactly like `place_once`: everything is packed into Delhi because the forecast says Delhi is cleanest.

**t = 3,600, the new forecast arrives** (priority 1, so before J1 and J2's completions). Delhi will be 400 from now on. Pending jobs, in order: J3, J4, J6, all queued on dc0.

**J3.**

1. Stage 1. Re-score the incumbent with the new forecast: dc0 at 400 gives Ŝ_a = 4.04 × 0.5 × 400 / 1000 = **0.808 kg**.
2. Lower bound: the cleanest window anywhere before the deadline is Chennai at 200, so LB = 4.04 × 0.5 × 200 / 1000 = **0.404 kg**.
3. Gate: g_min = 0.05 × 0.808 = **0.0404 kg**.
4. Screen: 0.808 − 0.404 = 0.404, which is at least 0.0404, so it **passes**; a move might be worth it.
5. Stage 2. Full re-score: the best alternative is dc2 at slot 3,600, Ŝ_b = **0.404 kg** (dc2 is free).
6. Noise width w_ab = 0 (toy runtimes and forecasts have no spread), so the margin θ × w_ab = 0.1 × 0 = 0.
7. Condition: 0.808 − 0.404 = 0.404 ≥ 0.0404 + 0, so **move**.
8. Log: `MOVE` from dc0 to dc2, S_a 0.808, S_b 0.404, LB 0.404, w_ab 0, g_min 0.0404, θ 0.1. J3 leaves dc0's queue and is released on dc2. The dc0 and dc2 wait profiles are rebuilt before the next job.

**J4.**

1. Incumbent on dc0 at 400 is now Ŝ_a = 1 × 0.5 × 400 / 1000 = **0.2 kg**.
2. LB = 1 × 0.5 × 200 / 1000 = **0.1 kg**.
3. g_min = 0.05 × 0.2 = **0.01 kg**.
4. Screen: 0.2 − 0.1 = 0.1, which is at least 0.01, so it passes.
5. Stage 2: dc2 is now busy with J3 (4 GPUs) until 5,400, so J4 would start there at 5,400: Ŝ_b = **0.1 kg**.
6. Condition: 0.1 ≥ 0.01, so **move** to dc2, release at 3,600 (it waits in dc2's queue until 5,400).

**J6.**

1. Ŝ_a on dc0 = 3 × 0.5 × 400 / 1000 = **0.6 kg**.
2. LB = 3 × 0.5 × 200 / 1000 = **0.3 kg**.
3. g_min = **0.03 kg**.
4. Screen: 0.6 − 0.3 = 0.3, passes.
5. Stage 2: on dc2 from 5,400 next to J4 (3 + 1 = 4 GPUs fit): Ŝ_b = **0.3 kg**.
6. Condition: 0.3 ≥ 0.03, so **move** to dc2.

Then J1 and J2 complete. J3 starts on dc2 at 3,600 and ends at 5,400; J4 and J6 start on dc2 at 5,400 and end at 7,200; J5 ends on dc1 at 5,400, late.

**Emissions, measured against the truth** (not the forecast):

| Job | Ran on | Truth | kgCO2 |
|---|---|---|---|
| J1 | dc0, 0 to 3,600 | 100 | 0.2 |
| J2 | dc0, 0 to 3,600 | 100 | 0.2 |
| J3 | dc2, 3,600 to 5,400 | 200 | 0.404 |
| J4 | dc2, 5,400 to 7,200 | 200 | 0.1 |
| J5 | dc1, 1,800 to 5,400 | 300 | 0.3 (deadline missed) |
| J6 | dc2, 5,400 to 7,200 | 200 | 0.3 |
| | | **Total** | **1.504** |

### 8.2 The same scenario under the other policies

| Policy | Total kgCO2 | What happened |
|---|---|---|
| `place_once` | **2.308** | Same plan as above until t = 3,600, but it never re-plans. J3, J4 and J6 run on dc0 after Delhi turned to 400: J3 0.808, J4 0.2, J6 0.6 |
| `fcfs` | 1.904 | Ignores carbon; spreads jobs to whichever datacentre starts them first, by luck partly avoiding Delhi |
| `periodic` | 1.904 | Its timer fires after J1 and J2 complete at 3,600, so J4 and J6 have already started on dc0; only J3 is moved |
| `fixed_savings`, `pred_error` | 1.504 | Same moves as decision-flip |
| `decision_flip` | **1.504** | As traced above |
| `pig` (oracle) | 1.504 | Knew the truth at arrival and put J3, J4 and J6 on dc2 from the start |

The toy shows the whole idea: a carbon-aware plan made on an old forecast (2.308 kg) can be worse than not being carbon-aware at all (1.904 kg), and re-evaluating at the right moment recovers the oracle's result (1.504 kg). On the toy every pending job's decision really did flip, so the screen passed every time. On real data the screen fails about 60 % of the time; that is the work it saves.

## 9. Step 7: from one run to a result

**One run** (`flipwise run`, `experiment.execute_run`): one policy on one replicate writes a folder `results/<run_id>/`:

| File | Contents |
|---|---|
| `jobs.csv` | Each job: datacentre, release, start, end, wait, energy, kgCO2, deadline missed, number of moves |
| `decisions.csv` | Each decision: time, job, kind (`PLACE`, `KEEP`, `MOVE`, `SCREEN_FAIL`, ...), and the numbers `S_a`, `S_b`, `LB`, `w_ab`, `g_min`, `theta_eff` |
| `events.log` | Every event in order |
| `metrics.json` | Totals (below) |
| `manifest.json` | How it was made: config, git commit, data checksums, versions, mode, overhead |

The `run_id` is a hash of everything the run depends on, so a finished run is reused rather than repeated.

**Metrics** (`metrics.py`): total kgCO2 and energy; intensity in g/kWh; **deadline miss rate**; mean wait; `stage2_calls` (full re-scorings: the cost of re-planning); moves; and for decision-flip, the share of comparisons where θ was switched off. Emissions always use the truth and the real runtime, whatever the policy believed.

**Compare** (`flipwise compare`): every policy on the same replicates, so each comparison is paired: same jobs, same carbon, different policy.

**Statistics** (`reporting.py`): for each policy, the mean difference from `place_once` (or from `decision_flip`) over replicates, with a 95 % **bootstrap confidence interval**: resample the replicates 10,000 times and take the middle 95 % of the resampled means. If the interval does not contain 0, the difference is clear; if it does, the two policies cannot be told apart. No p-values, because replicates share data.

**Choosing thresholds** (PRD §14.5): sweep each policy's settings on the **validation** replicates only, pick the setting with the lowest emissions whose miss rate is within 1 point of `place_once`'s, and freeze it in `configs/policies.yaml`. Done on 5 Nov (D47): θ = 0.1, `w_max` = 2, `g_rel` = 0.05 for decision-flip.

**The test set**: run once with the frozen settings, never tuned on. Done on 12 Nov (D57): 16 replicates × 7 policies, in `docs/test_results/`.

**Ablations** (PRD §14.6) switch off one piece of decision-flip at a time to see what each contributes: A1 θ = 0 (that is P1), A2 no screen, A3 no wait uncertainty, A4 carbon uncertainty only, A5 point deadline rule, A6 a cost for leaving a queue. **Sensitivity sweeps** (§14.4) change one condition of the world: load, deadline slack, and others. Both are queued in `scripts/run_ablations.sh` on validation data.

## 10. Step 8: running the datacentres as separate services

In a real system, three datacentres would be three separate sites reached over a network. The **deployment track** shows the simulator works that way too, without changing a single result.

1. `datacentre.py` holds the datacentre logic once.
2. `dcservice.py` wraps it in a small HTTP server: `flipwise dc-serve --dc-id 0 --port 8101`. Its endpoints are `/health`, `/enqueue`, `/remove`, `/dispatch`, `/complete` and `/state`. The simulated time travels in each request; the service never reads a clock.
3. The coordinator, `flipwise run --mode remote --dc-urls ...`, is the same simulator, talking to the three services through `HttpDatacentre` instead of in-process objects.
4. **DT1 local split**: `scripts/local_cluster.sh` starts three services on ports 8101 to 8103, runs the coordinator, and stops the services afterwards.
5. **DT2 Docker**: `docker compose up` runs the three services and the coordinator as four containers.

Both give byte-identical `jobs.csv`, `decisions.csv` and `events.log` to the in-process run, on every policy on the toy and on a full dev week; if a service dies, the run stops with `DeploymentError` instead of producing wrong numbers. **DT3** (AWS) is not started. `docs/USAGE.md` shows how to run all of this.

## 11. What we found

| | Validation (12 replicates) | Test (16 replicates, the claim) |
|---|---|---|
| `decision_flip` against `place_once` | −146 kg, clearly lower | −55 kg, **not distinguishable** (CI −128 to +12) |
| against `fixed_savings`, `periodic`, `pred_error` | Not distinguishable | Not distinguishable |
| against `fcfs` | −161 kg, clearly lower | −427 kg, clearly lower |
| Full re-scorings against `fixed_savings` | 58 % fewer | 54 % fewer |
| Moves against `fixed_savings` | 61 % fewer | 60 % fewer |
| P1 (θ = 0 equals `fixed_savings`) | Holds on all 12 | Not re-checked on test |
| Oracle `pig` against `place_once` | About −1.8 % | About −1.6 % |

What this means:

- **The cost claim holds.** Decision-flip reaches the same carbon as the policies that re-score everything, with about half the re-scoring and far fewer moves.
- **It is not the lowest-emissions policy.** On the test set it cannot be told apart from never re-planning (`place_once`).
- **There is little carbon to win.** Even perfect foresight beats `place_once` by under 2 %, so no trigger rule can win much on this data.
- **Deadlines.** About 4.1 % of jobs miss against 2.1 % under `fcfs`. Carbon-aware placement causes it, not re-planning: `place_once` is at about 4 % too. About 93 % of misses are jobs that ran longer than their 90th-percentile estimate.
- **The noise margin is often off.** θ was switched off on 23 to 28 % of comparisons because the interval was too wide.

The claim the team agreed (D51) is: *about the same carbon as the other re-planners, at much lower re-planning cost*.

## 12. The phases, and where each step was built

| Build phase (PRD §18) | Built | Status |
|---|---|---|
| 1. Setup and audit | Repository, tooling, data download, trace audit | Done |
| 2. Canonical data | Steps 2.1 to 2.5: `ingest`, `build-forecasts`, `validate` | Done |
| 3. Deterministic core | Simulator, events, datacentres, toy scenario, `fcfs` | Done |
| 4. Energy and place-once | Energy model, carbon views, planner, `place_once` | Done |
| 5. Baselines | Runtime and wait estimates, real scenarios, `periodic`, `pred_error`, `fixed_savings`, rescue | Done |
| 6. Decision-flip | Screen, noise width, fallbacks, P1 | Done |
| 7. Experiment runner | `compare`, `sweep`, `report`, `dashboard` | Done |
| 8. Real-trace evaluation | Validation and freeze, test set once, sensitivity, ablations | Validation and test done; sensitivity and ablations queued |
| 9. Analysis and package | Report figures, limitations, reproducibility | Open |

| EL review | Must show | Status |
|---|---|---|
| Phase 1 (pitch) | Problem, objectives, method | Done |
| Phase 2 (partial results) | Toy check, P1, one comparison table, dashboard, local split, Docker | Done, except one Docker run on Windows |
| Phase 3 (final) | Full results, sweeps, ablations, paper | Test results in; sweeps and ablations open |

Open blockers: B1, the mentor confirms the scope. B3 is mostly resolved (D58): kgCO2 is a cited bracket, with CPU power per core still assumed.

## 13. Glossary

| Term | Meaning |
|---|---|
| Ablation | A run with one part of decision-flip switched off, to measure that part's contribution |
| `A(r, k)`, truth | The real carbon intensity of region `r` in slot `k`; only the evaluator sees it |
| Bootstrap CI | A 95 % range for a mean difference, from resampling the replicates 10,000 times |
| Candidate | One option for a job: (datacentre, release slot) |
| Capture, vintage `v` | The time a forecast was published; each capture forecasts many future slots |
| Carbon intensity | Grams of CO2 emitted per kWh of electricity (gCO2/kWh) |
| CEA factors | Official Indian emission factors per fuel, from the CEA CO2 Baseline Database |
| Deadline risk, fallback | No candidate can meet the deadline; the job takes the earliest pessimistic finish |
| Discrete-event simulation | A simulator that jumps from event to event in time order |
| `e05`, `e95` | The 5th and 95th percentiles of forecast error at a given lead time |
| `F(r, k, v)`, forecast | The intensity of region `r` in slot `k` as forecast at capture `v` |
| Feasible | A candidate that fits capacity and meets the deadline under pessimistic estimates |
| `g_min`, gate | The minimum saving worth moving a job for: 5 % of its current score with frozen settings |
| Incumbent `a` | A job's current plan |
| Information boundary | What policies may see: forecasts up to now and estimates; never the truth or real runtimes |
| `INTERVAL_TOO_WIDE` | The noise width exceeds `w_max × Ŝ_a`, so θ is switched off for that comparison |
| `L`, `U` | The low and high ends of a candidate's score interval |
| Lead time, lead bucket | How far ahead of its capture a forecast slot is; errors grow with it |
| `LB` | Lower bound on any feasible alternative's score; used by the screen |
| Miss rate | Share of jobs that finished after their deadline |
| Move | Changing a pending job's datacentre or slot |
| Oracle, `pig` | A policy that sees the true future; a reference for how much could be won |
| P1 | At θ = 0, decision-flip makes exactly `fixed_savings`'s decisions with fewer full re-scorings |
| Paired comparison | Policies compared on the same replicate, so only the policy differs |
| Pending | Planned or queued, not yet running; only pending jobs can be re-planned |
| Policy | The rule for when to re-plan and when to accept a move |
| Profile | A datacentre's projected use over time; used to estimate waits |
| `r_q05` to `r_q95` | Percentiles of a job's runtime, estimated from the user's past jobs |
| Release slot | The half hour at which a planned job joins its datacentre's queue |
| Replicate | One scenario: a trace week paired with a carbon Monday |
| Rescue | Re-planning a job whose plan can no longer meet its deadline, whatever the policy |
| `rho` | Offered load: how busy the datacentres are on average (0.7) |
| `Ŝ`, score | A candidate's estimated kgCO2 on the current forecast |
| Screen, `SCREEN_FAIL` | Stage 1 of decision-flip; skips the full re-score when no alternative could clear the gate |
| Slot | A half hour (1,800 s); the unit of time for carbon |
| `stage2_calls` | Number of full re-scorings; the cost measure |
| θ, theta | How strongly a gain must exceed the noise width (0.1) |
| Validation, test | Separate periods: thresholds are tuned on validation; the test set is run once |
| `w_ab`, noise width | How uncertain the comparison between the incumbent and the best alternative is |
| `w_lo`, `w_mid`, `w_hi` | Optimistic, middle and pessimistic queue-wait estimates |
| `w_max` | Above `w_max × Ŝ_a` the noise width is treated as uninformative (2) |

## 14. Is it rule-based, and could it use machine learning?

**Today the decisions are rule-based.** The screen, the gate, the noise margin and the fallbacks are explicit formulas with frozen thresholds. The parts that come from data are statistics, not trained models: runtime percentiles per user (a lookup of past runtimes) and forecast-error percentiles per lead time. There is no learning step that changes behaviour from experience.

That is deliberate. Because the rules are explicit, two properties can be proven and tested: the screen never skips a re-score that would have moved a job, and at θ = 0 decision-flip makes exactly `fixed_savings`'s decisions (P1). A learned model gives neither guarantee.

**Where machine learning would genuinely help:**

1. **Runtime prediction (the strongest case).** Replace the per-user percentiles with a model that predicts runtime percentiles from the user, GPU request, time of day and recent history (for example quantile regression with gradient boosting). The planner already takes percentiles as input, so nothing else changes. It targets the largest measured weakness: about 93 % of deadline misses are jobs that outran their 90th-percentile estimate. Better estimates would mean fewer misses and narrower intervals, so θ would be active more often.
2. **A learned trigger.** A classifier trained on past decision logs to predict whether a full re-score will lead to a move. It could skip more re-scorings than the screen, but it would sometimes skip a needed move, so P1 would no longer hold. It would be a different, weaker claim.
3. **A learned carbon forecaster.** Not meaningful here: the Indian forecasts are built from British error paths, so there is no real Indian forecast to learn from. It becomes possible only with real Indian forecast data.
4. **Reinforcement learning for the whole scheduler.** Possible in principle, but far beyond this project's scope and hard to validate.

**What any ML addition must respect:**

- Train only on the training period (trace days 0 to 21 for runtimes), never on validation or test data.
- Stay deterministic: fixed seeds, byte-identical outputs.
- Respect the information boundary: no real runtimes, end times or carbon truth as inputs at decision time.
- The PRD's allowed dependencies are pandas, numpy, PyYAML and matplotlib; adding scikit-learn or similar needs a PRD change first.

**Recommendation:** keep the core rule-based. If one ML extension is added, make it the runtime model, as a Phase 3 extension tested as an ablation against the current per-user percentiles. It fixes the measured weakness without touching the proven trigger. Do not expect large carbon gains from any change: on this data even perfect foresight saves under 2 %.
