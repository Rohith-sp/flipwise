# Decision-flip, explained

The proposed algorithm of this project, in plain steps with every formula and one worked example. For where it sits in the whole system, see `docs/WALKTHROUGH.md`; for the formal specification, PRD §10.

## 1. The problem it solves

- A job is placed using the carbon forecast available when it arrives.
- Every 30 minutes a new forecast is published, so a waiting job's plan may no longer be the cleanest.
- Re-checking every waiting job at every forecast is expensive (up to 147 options each, with queue simulation), and moving jobs costs them their queue place.
- Never re-checking misses real savings.
- **Decision-flip re-checks a job only when a move could be worth it, and moves it only when the saving is bigger than the forecast's own uncertainty.**

## 2. When it runs

| Event | What happens |
|---|---|
| **New carbon forecast** (every 30 simulated minutes) | The full decision-flip check, for every waiting job, one at a time, earliest deadline first |
| Job arrives | First placement only: the cleanest option that safely meets the deadline (same for every carbon-aware policy) |
| Job's start slot arrives | Rescue check only: if the plan can no longer meet the deadline, re-plan; otherwise the job joins the queue |
| Job finishes, deadline passes | Nothing; freed capacity is seen at the next forecast, at most 30 minutes later |

Running jobs are never moved.

## 3. What it may use

| Known to it | Not known to it |
|---|---|
| Each job's request, deadline and runtime guesses (q05, q50, q90, q95 from the user's past jobs) | The job's real runtime |
| The latest forecast and its usual error range per lead time (e05, e95) | The real future carbon |
| Queues and capacities of the three datacentres | When running jobs will actually end |

## 4. The check, step by step

Worked example: a 2-GPU job planned for Delhi 14:00–16:00, deadline 22:00, runtime guesses q50 = 2 h, q90 = 3 h. Scheduler power P = 0.6 kW. Now 10:00, and a new forecast has arrived.

Basic formula, used everywhere: **CO₂ (kg) = P (kW) × hours × intensity (g/kWh) ÷ 1000**.

### Step 1: throttle
- Skip the job if it was checked less than 30 minutes ago or has already moved 3 times (`THROTTLED`).
- Why: stops a job bouncing between sites.

### Step 2: rescue
- Re-price the current plan. If it can no longer meet the deadline, re-plan immediately, whatever the rules below say (`RESCUE`).
- Why: deadlines come before carbon.

### Step 3: re-price the current plan
- **Ŝ_a** = CO₂ of the current plan on the new forecast.
- Example: Delhi is now forecast at 650 g/kWh, so Ŝ_a = 0.6 × 2 × 650 / 1000 = **0.78 kg**.

### Step 4: the screen (cheap)
- **Lower bound LB** = the lowest CO₂ any alternative could possibly have: the cleanest q50-long window in any region, starting between now and the latest safe start (deadline − q90), with queues ignored.
  - Example: Chennai 12:00–14:00 at 450 g/kWh, LB = 0.6 × 2 × 450 / 1000 = **0.54 kg**.
  - Why it is a true bound: every real option starts somewhere in that window, and queues can only make it later, never cleaner.
- **Gate g_min** = the smallest saving worth a move:
  `g_min = max(g_abs, g_rel × Ŝ_a) + κ_switch + κ_queue (if queued) + λ_ovh`
  - Frozen values: g_rel = 0.05; g_abs, κ_switch, κ_queue, λ_ovh = 0. So g_min = 5 % of Ŝ_a = **0.039 kg**.
- **Test:** if `Ŝ_a − LB < g_min`, no move can ever pass the gate, so stop here (`SCREEN_FAIL`).
  - Example: 0.78 − 0.54 = 0.24 ≥ 0.039, so continue.
  - On real data this stops about 60–70 % of checks. This is where the work is saved.

### Step 5: the full check (expensive)
- Score every real option (each site × each half hour up to the deadline, at most 147), each with a projected queue wait and the conservative deadline check (start + pessimistic wait + q90 ≤ deadline).
- **Ŝ_b** = the best feasible alternative. Example: Chennai, joining at 12:00, starting 12:30 after a short queue, at 470 g/kWh, so Ŝ_b = **0.564 kg**.
- **Saving** = Ŝ_a − Ŝ_b = **0.216 kg**.

### Step 6: how uncertain is the comparison? (noise width)
`w_ab = ½ [(U′_a − L′_a) + (U′_b − L′_b)] + ½ |Δ(q95) − Δ(q05)|`
- First part: forecast and queue-wait uncertainty of each option (U′ uses forecast + e95 and the long wait, L′ uses forecast + e05 and the short wait, runtime held at q50).
- Second part: runtime uncertainty, counted only through how it changes the *difference* between the two options, `Δ(r) = Ŝ_a(r) − Ŝ_b(r)`. A longer run costs more at both sites, so only the part that changes the gap matters.
- Example: forecast part 0.46 kg + runtime part 0.162 kg, so **w_ab = 0.62 kg**.
- **Sanity check:** if `w_ab > w_max × Ŝ_a` (w_max = 2), the uncertainty says nothing useful, so θ is set to 0 for this comparison (`INTERVAL_TOO_WIDE`). Example: 0.62 < 1.56, so θ stays on.

### Step 7: the decision-flip condition
Move to b only if

**`Ŝ_a − Ŝ_b ≥ g_min + θ × w_ab`** (and the saving is positive)

- Frozen θ = 0.1, so the margin is 0.1 × 0.62 = 0.062 kg and the move needs 0.039 + 0.062 = **0.101 kg**.
- Example: 0.216 ≥ 0.101, so **MOVE**.
- Counter-example: a best alternative of 0.72 kg saves only 0.06 kg, below 0.101, so **KEEP**. A saving that small could be a forecast error, and moving would cost the job its queue place.

### Step 8: apply the move
1. Remove the job from its queue if it was queued (it loses its place).
2. Give it the new site and start slot; count one move.
3. Rebuild the queue estimates of both sites **before** checking the next job, so jobs do not all rush into the same cheap slot.
4. Log `MOVE` with Ŝ_a, Ŝ_b, LB, w_ab, g_min and θ.

## 5. Settings

| Setting | Value | Meaning | Chosen how |
|---|---|---|---|
| g_rel (gate) | 5 % | Minimum saving, as a share of the job's CO₂ | Frozen on validation data (D47) |
| θ (theta) | 0.1 | How much of the noise width a saving must also beat | Frozen on validation data |
| w_max | 2 | Above 2 × Ŝ_a the noise width is ignored | Frozen on validation data (D49) |
| Cooldown | 30 min | Minimum time between checks of one job | Fixed |
| Max moves | 3 | Per job | Fixed |

## 6. Why each part exists

| Part | What goes wrong without it |
|---|---|
| Screen | Every waiting job gets a full re-score every 30 minutes (what `fixed_savings` does) |
| Gate | Jobs move for tiny savings |
| Noise margin | Jobs move for "savings" that are really forecast error |
| Sanity check on w_ab | An uninformative, huge uncertainty would block every move |
| Throttle | A job can bounce between sites |
| Rescue | A job can miss its deadline while waiting for a cleaner slot |
| Rebuild queues after each move | Many jobs pile into the same cheap slot |

## 7. The guarantee (P1)

- With θ = 0, the condition in step 7 is exactly `fixed_savings`' rule, and the screen only skips jobs for which that rule could never fire.
- So decision-flip at θ = 0 makes **exactly the same decisions** as re-scoring everything, only cheaper.
- Proven on all 12 validation weeks: identical `jobs.csv` and `events.log`, with 62 % fewer full re-scores (`docs/validation/p1.csv`, requirement R-TRIG-2).
- With θ = 0.1 it is also more careful: it ignores savings smaller than the forecast noise.

## 8. Results (test set, 16 weeks, run once)

- Same carbon as the other re-planning policies (differences within noise).
- **54 % fewer full re-scores and 60 % fewer moves** than `fixed_savings`.
- Clearly less carbon than `fcfs` (no carbon awareness).
- Not distinguishable from `place_once` on carbon; its advantage is the work saved, not lower emissions.
- With cited power (D58), test kgCO₂ per replicate is 3,853 (measured) to 11,862 (nameplate); the conclusions are the same at both ends (`docs/power_bracket/`).

## 9. Where it is in the code

| Piece | Code |
|---|---|
| The policy | `DecisionFlip` in `src/flipwise/policies.py` |
| Lower bound LB (screen) | `planner.lower_bound` in `src/flipwise/planner.py` |
| Full re-score (all options) | `planner.alternatives`, `planner.evaluate` |
| Noise width w_ab | `planner.paired_width` |
| Sanity check (θ off) | `planner.interval_problem` |
| Moving a job | `Simulator._apply` / `_place` in `src/flipwise/simulator.py` |
