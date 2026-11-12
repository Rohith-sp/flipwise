# The live dashboard, explained

What every part of the Flipwise dashboard shows, where its numbers come from and how to read it. The dashboard is served by `flipwise live` at http://localhost:8100 (how to start it: [DEMO.md](DEMO.md) or [USAGE.md §8a](USAGE.md)). It is for showing the system, not for producing results: a live session can include jobs you submit, so it is never saved to `results/`.

## How the dashboard works

- **One simulated clock, several policies.** The server runs the same week of jobs and carbon through five policies at once (decision_flip, fixed_savings, periodic, pred_error, place_once; `--policies all` adds fcfs and the oracle pig). They share the clock, the jobs and the carbon, so any difference comes from the policy.
- **Simulated time moves with real time.** The speed is set in the header (for example *30 min/s* = half an hour of simulated time per real second). A carbon forecast arrives every 30 simulated minutes; that is when the policies re-check waiting jobs.
- **Data.** The browser polls the server's JSON API about every 1.5 s and listens to a live event stream for decisions and messages. Nothing leaves the laptop; the chart and style libraries are bundled, so no internet is needed.
- **Units.** kgCO₂ on the live pages counts completed jobs only and uses the evaluator's power model (measured GPU use by default). Early in a run, totals are small and differences between policies can look large; they settle as more jobs finish.

## Everywhere: header and sidebar

| Part | What it shows or does |
|---|---|
| **Simulated clock** (monospace pill) | Current simulated time in IST, e.g. *Mon 03 Jul 2023 14:30 IST* |
| **Play / Pause** | Stops or resumes the simulated clock |
| **Speed** (1 min/s · 5 min/s · 30 min/s · 2 h/s) | How much simulated time passes per real second |
| **Time skip** (+1 h · +6 h · +1 day) | Replays the recorded history as fast as possible up to that time; buttons show a spinner while it runs (seconds on the toy, 20–60 s on a real week) |
| **Submit job** | Opens the Job tracker form |
| **Connection pill** | *Live* (green) while the server answers; *Disconnected* (red) if it stopped |
| **Sidebar, Monitor** | Overview, Head-to-head, Scheduler, Datacentres, Policy comparison, Job tracker |
| **Sidebar, Evidence** | Scale projection, Test results, Architecture |
| **Scenario** (sidebar footer) | How many policies run side by side and the simulated period (start and end) |
| **Toasts** (pop-ups, bottom right) | A skip finished; a job you submitted was moved by decision_flip; your job completed |

## Overview

The whole system on one page.

| Component | What it shows | How to read it |
|---|---|---|
| **KPI tiles** (5) | For decision_flip: CO₂ so far · full re-scores · jobs moved · checks stopped by the screen · jobs completed and deadline misses. Each has a sparkline (its history) and, where possible, a comparison with fixed_savings ("54 % less work than fixed_savings") | The headline: same CO₂, far fewer re-scores and moves; most checks stop at the screen |
| **Grid carbon intensity** chart | One line per region: actual carbon so far (solid) and the latest forecast for the next hours (dashed); a "now" marker | Lower = cleaner. Where the dashed lines cross is where the best site changes, which is when re-planning can pay off |
| **Services** card | The scheduler and the three datacentres; for each, whether it is a separate service (URL) or in-process, its request count and mean latency | Shows the datacentres really are separate services when running with Docker or local services |
| **Latest messages** | The newest calls from the scheduler to the datacentres: `enqueue`, `remove`, `dispatch`, `complete` | The actual communication; a `remove` then `enqueue` at another site is a job being moved |
| **Datacentre cards** (Delhi NCR, Mumbai, Chennai) | Grid carbon now (chip coloured green below 600, amber below 800, red from 800 g/kWh), GPU load bar (used / capacity), running jobs, queued jobs, CO₂ so far | Where the load and the emissions are going right now |
| **Policy comparison, live** | Table: each policy's CO₂ so far, full re-scores, moves, and a "work vs fixed_savings" bar (full re-scores relative to fixed_savings); decision_flip highlighted | The core trade-off in one table |
| **Decision feed · decision_flip** | Newest decisions first: time, a coloured badge and one line, e.g. *MOVE · Delhi NCR → Chennai, saves 0.31 kg ≥ needed 0.12 kg* | Shows the algorithm's reasoning as it happens |

**Decision badges** (used on several pages):

| Badge | Meaning |
|---|---|
| PLACE | First placement of a job when it arrives |
| SCREEN_FAIL | The cheap screen showed no move could pay off; the full re-score was skipped (work saved) |
| KEEP | Fully re-scored, but the saving did not beat the gate plus the noise margin |
| MOVE | Moved to a better option; the saving beat what was needed |
| RESCUE / RESCUE_NOOP | The plan could no longer meet the deadline, so it was re-planned (or nothing better existed) |
| FALLBACK | No option could meet the deadline; the job takes the earliest possible finish |
| THROTTLED | Skipped this round: checked less than 30 minutes ago or already moved 3 times |

## Head-to-head

decision_flip against one other policy, chosen with the picker, on the same jobs and clock. This is the page that shows the contribution.

| Component | What it shows | How to read it |
|---|---|---|
| **Policy picker** | Which policy to compare with (default fixed_savings) | Try fixed_savings (re-checks everything), periodic and pred_error |
| **Summary strip** | Re-scores saved (count and %), moves avoided, CO₂ difference, and the share of decision_flip's checks the screen avoided, with a one-line plain-English summary | The result in words, e.g. *"decision_flip skipped 1,106 of 1,504 checks with the cheap screen…"* |
| **Lane headers** (one per policy) | Counters: full re-scorings, skipped by screen (decision_flip only), moves, rescues, CO₂ so far, deadline misses | Compare the two lanes number by number |
| **Datacentre panels** (3 per lane) | Grid carbon now, GPU load, and three boxes: *Planned · waiting for release*, *Queue · FIFO first-fit*, *Running*, each with job chips; completed count | Each chip is one job, labelled with its GPUs (".5" = half a GPU); an **amber dot** marks a job that was moved, a black outline a job you submitted; "+N" means more jobs than shown |
| **Re-plan activity chart** | One stacked bar per forecast update: **grey** = checks avoided by the screen, **pink** = re-scored and kept, **amber** = moved, **red** = rescued. Both lanes use the same vertical scale | The key picture: decision_flip's bars are mostly grey; fixed_savings' are pink. Grey is work not done |
| **Event log** | Newest first, per lane: one line per forecast update (*"06:00 forecast update · 232 checked · 173 skipped · 58 re-scored · 1 moved"*) and one per move | The same story as the chart, in text |

## Scheduler

What the algorithm sees and decides.

| Component | What it shows |
|---|---|
| **Carbon forecast by region** | A larger version of the Overview chart: the forecast the scheduler is acting on, against the actual values |
| **What decision_flip does with each check** | Donut chart: share of checks stopped by the screen, fully re-scored and kept, and moved |
| **Decision feed** | Table of recent decisions for a chosen policy, filterable by kind (MOVE, KEEP, SCREEN_FAIL…), with each decision's numbers: current plan Ŝ_a, best alternative Ŝ_b, lower bound LB, noise width w_ab, gate g_min, θ |

## Datacentres

One tab per site: Delhi NCR, Mumbai, Chennai.

| Component | What it shows |
|---|---|
| **Gauges** | GPU, CPU and memory in use against capacity |
| **Running and queued jobs** | Over time, from the history of the session |
| **CO₂ per half hour** | Emissions from jobs at this site, per slot |
| **Jobs here** | The job chips (planned, queued, running) for the selected policy, as on Head-to-head |
| **Service health** | Whether this site is a separate service, its URL, request count and mean latency |

## Policy comparison

All policies over time, not just now.

| Component | What it shows |
|---|---|
| **Cumulative CO₂, moves, full re-scores** | One line per policy over simulated time |
| **Leaderboard** | Policies ranked by CO₂ so far, with full re-scores, moves, jobs completed and deadline misses |
| **Callout** | e.g. *"same carbon, X % fewer re-scores than fixed_savings"* |

Read it as: lines close together on CO₂, far apart on re-scores and moves.

## Job tracker

Submit a job and see what every policy does with it.

| Component | What it shows |
|---|---|
| **Submit a job** form | GPUs, GPU type (V100, P100, T4, MISC), CPU cores, memory (GB), runtime (h), deadline (hours from now), optional GPU utilisation (0–1). The scheduler only sees the runtime estimate; the job reaches every policy at the same simulated moment. Invalid values show the server's message |
| **Job selector** | Your submitted jobs (USER-1, USER-2, …) |
| **Swim lanes** | One lane per policy: a chip for each decision (PLACE, KEEP, MOVE, …) and a final RUNNING or COMPLETED chip; lane summary (moves, decisions); CO₂ (final when completed, otherwise the estimate, labelled) |
| **Decision detail** (click a chip) | Current plan, best alternative, the saving, what was needed (gate g_min + θ × noise width w_ab, with its parts), the verdict and a one-sentence explanation |

Typical reading: decision_flip KEEPs where fixed_savings MOVEs, because the saving is smaller than the forecast could be wrong.

## Scale projection

What the savings would mean at millions of jobs.

| Component | What it shows |
|---|---|
| **Per-job rates** | Full re-scores, moves and scheduler time per job, per policy. *Measured* = this live session (totals ÷ jobs arrived); *Reference* = the 16 test replicates (144,412 jobs) |
| **Projection** | A slider from 10 thousand to 10 million jobs, showing re-scores saved, moves avoided and scheduler CPU-hours saved against the chosen baseline, labelled *projected* |

Caveat shown on the page: the trace has about 730,000 unique jobs, so beyond that the numbers are projections from per-job rates, not measurements.

## Test results

The evidence from the one test run (16 weeks, thresholds frozen beforehand), not the live session.

| Component | What it shows |
|---|---|
| **Table** | Per policy, mean per replicate: kgCO₂ measured (lower bound), kgCO₂ nameplate (upper bound), deadline miss rate, full re-scorings, moves |
| **Bar charts** | One per column of the table |

Read it as: CO₂ bars almost equal across re-planning policies; full re-scores and moves much lower for decision_flip than for fixed_savings and periodic.

## Architecture

| Component | What it shows |
|---|---|
| **How the pieces connect** | The scheduler and the three datacentres as boxes, with each site's URL (or in-process), request count and latency |
| **Local split / Docker** | Short explanations of the two ways the datacentres run as separate services, and that both give byte-identical results to the single-process run |

## Datacentre dashboards (ports 8101–8103)

Each datacentre service serves its own page: **8101** Delhi NCR (Northern grid), **8102** Mumbai (Western), **8103** Chennai (Southern). They are display only: they show what the service has been told and add nothing to the simulation. The pages poll once a second (paused while the tab is hidden).

| Component | What it shows |
|---|---|
| **Header** | Site name, grid, port, the simulated clock last sent by the scheduler, a connection pill (Live, Waiting for scheduler, Disconnected) and a link back to the scheduler dashboard |
| **Waiting state** | Before the scheduler's first request the service has no capacity configured; the page says so instead of showing errors |
| **KPI tiles** | GPU utilisation, running jobs, queued jobs, jobs completed here, messages received |
| **Gauges** | GPU, CPU and memory in use against this site's capacity |
| **Local scheduler · FIFO first-fit** | The queue in order (head first) and the running set as chips labelled with GPUs requested; beside them the last dispatch decisions ("started job X: fits 4 GPUs") |
| **GPUs in use / Queue and running** | Time series sampled once per simulated half hour, from the times in the scheduler's requests |
| **Grid carbon at this site** | Carbon now, the forecast for this slot, the next 6 hours, CO2 so far and the scheduler's policy. The service does not know carbon, so the page reads it from the scheduler; if that is unreachable it says "Scheduler not reachable" and the rest keeps working |
| **Messages from the scheduler** | The last 200 requests, newest first: time, operation (enqueue blue, remove amber, dispatch green, complete grey), job and details |

The scheduler's **Overview** (Services card) and **Architecture** page link to each datacentre's page when the datacentre runs as a service.

## Where the data comes from (for the curious)

| Endpoint | Used by |
|---|---|
| `GET /status` | KPIs, comparison table, decision feed, carbon now, messages |
| `GET /clock`, `POST /control` | Header clock, play/pause, speed, time skip |
| `GET /history` | Sparklines, charts over time |
| `GET /dc/<id>` | Datacentre cards and tabs |
| `GET /activity`, `GET /lanes` | Head-to-head activity chart and job chips |
| `GET /jobs`, `GET /jobs/<id>`, `POST /jobs` | Job tracker |
| `GET /health` | Services card, Architecture page |
| `GET /results` | Test results page |
| `GET /stream` | Live toasts and event feeds (server-sent events) |
