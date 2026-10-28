# Project Explanation: Efficient Re-Evaluation of Pending Workloads in Carbon-Aware Datacentre Scheduling

**Institution:** RV College of Engineering, Bengaluru  
**Programme context:** Experiential Learning, V Semester, Academic Year 2026–27  
**SDG theme:** SDG 9 — Industry, Innovation and Infrastructure  
**Document purpose:** Explain the project, its motivation, research direction, data, proposed simulation, evaluation plan, current decisions, and unresolved questions in one place.  
**Project name:** Flipwise (Python package and CLI `flipwise`): it re-evaluates decision flips wisely  
**Status:** Working explanation based on the submitted EL report, the team's subsequent discussion, and the implementation PRD (`prd.md`). Updated to match PRD v0.5 (India-only simulated world). Where the two disagree, the PRD is authoritative.  
**Last updated:** 28 October 2026

---

## 1. The project in plain English

Modern cloud services and AI workloads run in datacentres. Those datacentres use electricity, and the carbon emissions associated with that electricity depend on both **how much electricity a workload consumes** and **how carbon-intensive the electricity is at that location and time**.

A cloud scheduling system decides which job should run, where it should run, and when execution should begin. The scheduler normally makes these decisions using estimates: the job's runtime, the queue ahead of it, available computing capacity, its deadline, and the expected carbon intensity of electricity. These estimates are not perfectly reliable. New forecasts arrive, queue conditions change, and previously estimated execution times may prove inaccurate.

That creates a problem after a job has been assigned but before it starts. The original placement might no longer be the best feasible choice. Another datacentre or execution window might now offer lower modelled emissions, a shorter wait, or a better balance of emissions and deadline risk.

There are two obvious but imperfect responses:

- **Never reconsider:** keep the first decision. This has low scheduling overhead, but it can miss useful opportunities when the situation changes.
- **Reconsider all the time:** rerun the optimiser frequently or at fixed intervals. This reacts to changes, but it can waste computation, repeatedly change placements, and react to forecast noise even when the best decision has not actually changed.

The project investigates a middle path: **re-evaluate pending jobs selectively, when new information and uncertainty indicate that the best feasible placement may have changed and the likely benefit justifies the cost of reconsidering it.**

The team will build a trace-driven, discrete-event simulation of multiple *virtual* datacentres. It will replay workload information, use electricity carbon-intensity data, model energy consumption using documented assumptions, and compare the proposed trigger against alternative scheduling and replanning policies. The result will be an experimental study, not a production cloud scheduler.

### One-sentence description

We are building a simulation-based, uncertainty-aware mechanism that decides **when to revisit the placement of a pending computing job across virtual datacentres**, then tests whether this selective re-evaluation improves the trade-off between modelled carbon emissions, job performance, and scheduling overhead.

### What is the central idea?

The key question is not only **“Which datacentre is best?”** It is also **“Has enough changed that the scheduler should spend effort deciding again?”**

That distinction is the proposed research focus.

---

## 2. Project identity and context

### 2.1 Project title

**Efficient Re-Evaluation of Pending Workloads in Carbon-Aware Datacentre Scheduling**

### 2.2 Academic context

The submitted report identifies the project as an RV College of Engineering V Semester Experiential Learning project for AY 2026–27. It is aligned with **UN Sustainable Development Goal 9 (SDG 9): Industry, Innovation and Infrastructure**. The main SDG connections described in the report are:

- **Target 9.4 — Sustainable infrastructure:** investigate whether scheduling can reduce modelled emissions while respecting computing resource and deadline constraints.
- **Target 9.5 — Research and innovation:** develop and evaluate a scheduling mechanism through simulation, comparative experiments, and sensitivity analysis.
- **Target 9.1 — Reliable and resilient infrastructure:** consider operational feasibility, capacity limits, deadlines, and delayed scheduling information. The report correctly notes that the project does not directly test the resilience of physical infrastructure.

### 2.3 Current status of the design

There are two connected but distinct descriptions of the project that must be kept clear:

1. **The submitted EL report** proposes a hierarchical **Global–Local Distributionally Robust Optimization (DRO)** framework. A global fleet manager distributes capacity and workload targets across datacentres, and local schedulers plan jobs within those allocations.
2. **The more focused research direction discussed after the presentation** is **decision-flip-triggered re-evaluation**: a mechanism that decides when a pending job's existing placement should be reconsidered because the best feasible datacentre/window could have changed.

These are compatible in principle, but they are not the same contribution. DRO is an optimisation approach for making scheduling decisions under uncertainty; the trigger is a policy for deciding **when to invoke re-optimisation**. A DRO planner could eventually sit behind the trigger, but a complete global–local DRO implementation should not automatically become a prerequisite for the first working simulation.

**Recommended implementation order:** first create a correct simulator, a clear placement objective, simple planners, and the decision-flip trigger. Keep the planner behind an interface so that a deterministic planner and a robust/DRO planner can be compared later. Treat full Global–Local DRO as an extension unless the team and mentor explicitly decide it must be a central contribution.

---

## 3. The problem, step by step

Imagine that a company has three datacentres: A, B, and C. These are examples inside the simulation, not claims about specific real facilities.

### Step 1 — A job arrives

A computing job enters the system. It has resource requirements, an estimated runtime, and a deadline or an experiment-defined timing requirement. The scheduler needs to choose a feasible datacentre and execution window.

### Step 2 — The first placement is selected

At the initial decision time, Datacentre A might appear best because it has sufficient capacity and a relatively low forecast carbon intensity during the proposed execution window. The scheduler assigns the pending job to A, subject to the capacity and deadline rules.

### Step 3 — The system receives new information

Before the job starts, one or more conditions may change:

- the predicted carbon intensity for A's execution window rises;
- Datacentre B's predicted carbon intensity falls;
- queue waiting time at A increases;
- available capacity at B changes;
- the runtime estimate becomes wider or more accurate;
- a deadline becomes harder to meet under the updated estimates.

A different feasible choice may now be better than the original placement.

### Step 4 — The trigger checks whether the decision itself may have changed

A naive trigger might run the optimiser whenever a prediction changes by more than a fixed percentage. But a prediction can change without changing the best placement. For example, the carbon estimate at both A and B might rise by the same amount, leaving their ranking unchanged.

The project's proposed trigger instead asks whether the **identity or relative ranking of the best feasible `(datacentre, execution window)` candidate could plausibly change** when uncertainty and updated information are considered.

### Step 5 — The policy considers the net benefit

A possible decision flip is not automatically a reason to re-plan. The potential gain must be worth the computational effort and any placement-change cost. A candidate is also rejected if it violates resource capacity, a deadline rule, or another hard constraint.

### Step 6 — The scheduler either keeps or updates the placement

The trigger may request a new optimisation. The optimiser may then:

- retain the original placement if it is still best;
- select a different feasible datacentre/window if the expected benefit is adequate; or
- decide that no change clears the benefit threshold.

Thus, **a re-evaluation call is not the same thing as a placement change**. Both must be measured separately.

### Step 7 — The job executes and the simulator records outcomes

When the job starts, it becomes a running job and is not migrated in the primary scope. At completion, the simulator records the modelled energy/emissions, completion time, deadline outcome, waiting time, resource use, and scheduling overhead. The same workloads and scenario settings are used across policies to make comparisons fair.

---

## 4. Formal problem statement

In a multi-datacentre environment, the scheduler chooses where and when jobs execute based on job requirements, expected runtime, queue conditions, resource capacity, deadlines, and electricity carbon intensity. Information can change after an initial scheduling decision but before a pending job starts. Consequently, the existing placement may stop being the best feasible option.

Re-evaluating every pending job at every update can incur unnecessary optimisation overhead and placement churn. Never re-evaluating can miss opportunities to reduce emissions or improve job performance. Fixed thresholds and periodic policies may respond to raw prediction changes without checking whether those changes alter the best feasible scheduling decision.

This project investigates whether a **decision-impact-based re-evaluation trigger** can selectively initiate re-optimisation when uncertainty and new information indicate that the best feasible `(datacentre, execution window)` may have changed. The trigger must account for expected benefit, job deadlines, resource limits, re-optimisation overhead, and the cost of changing a pending placement.

The project will evaluate this mechanism in a discrete-event simulator and compare it with place-once, periodic, prediction-error-triggered, fixed-savings, and other appropriate scheduling policies. The project is intended to establish **when the approach helps, when it does not, and why**. It does not assume in advance that the proposed trigger will outperform every baseline.

---

## 5. Research question, objectives, and hypotheses

### 5.1 Main research question

**Under what workload, capacity, forecast-quality, and deadline conditions does decision-flip-triggered re-evaluation of pending jobs provide a better balance of modelled carbon emissions, deadline performance, and scheduling overhead than place-once, periodic, and threshold-triggered replanning policies?**

### 5.2 Supporting research questions

1. Can uncertainty intervals for runtime, queue wait, and carbon intensity be estimated and calibrated well enough to support a decision-impact trigger?
2. Does checking whether the **best feasible decision may change** outperform a trigger based only on a raw prediction-error threshold?
3. How does performance change when workload pressure, resource scarcity, deadline tightness, forecast error, or carbon-intensity differences between virtual datacentres change?
4. How many re-evaluation calls can be avoided without substantially worsening emissions or deadline performance?
5. In what regimes is periodic or fixed-savings re-planning competitive with the proposed trigger?
6. Does a more robust planner, including a future DRO variant, improve the quality of the decision made when a re-evaluation is actually triggered?

### 5.3 Core objectives from the report

- Model scheduling uncertainty using workload traces, carbon-intensity information, queue conditions, and resource availability.
- Develop a selective re-evaluation mechanism that identifies pending jobs for which a materially better feasible placement may exist.
- Evaluate the mechanism against alternative scheduling and replanning strategies.
- Measure modelled carbon emissions, deadline-miss rate, resource utilisation, queue delay, workload completion, scheduling overhead, and robustness under uncertainty.
- Use sensitivity analysis and ablation studies to identify the operating conditions where the method is useful and its limitations.

### 5.4 Proposed hypotheses to test

These are hypotheses, not results:

- **H1:** Compared with periodic re-planning, a decision-flip trigger can reduce optimisation calls while keeping carbon and deadline outcomes within an acceptable range in at least some workload regimes.
- **H2:** Its value should be most visible when conditions change enough to alter relative candidate rankings, but re-optimisation itself has a meaningful cost.
- **H3:** Poorly calibrated uncertainty intervals can cause missed useful re-evaluations or too many unnecessary ones.
- **H4:** A fixed carbon-savings threshold may be competitive in some regimes; the project must identify those cases rather than assume it is inferior.
- **H5:** If all feasible candidates have nearly identical emissions, the trigger should avoid excessive changes unless another objective, such as deadline feasibility, creates a material difference.

### 5.5 What would count as a useful result?

A useful result is not necessarily “our method wins on every metric.” Credible findings might show that it:

- reduces optimisation calls with similar emissions and deadline performance;
- reduces emissions in high-variability cases at the cost of some additional replanning;
- helps only when datacentre carbon-intensity differences are large enough;
- fails when forecast uncertainty is poorly calibrated or when placements are already capacity-constrained; or
- performs no better than a simpler baseline in most tested conditions.

An honest, repeatable negative or mixed result is more informative than an apparent win caused by unrealistic assumptions or unfair baselines.

---

## 6. Important concepts and terminology

| Term | Meaning in this project |
|---|---|
| **Workload/job** | A unit of computing work represented by the selected workload trace or an explicitly documented scenario generator. |
| **Datacentre** | A virtual site in the simulator with configured compute capacity, queue state, an electricity carbon-intensity profile, and an energy model. It is not automatically a real Alibaba facility. |
| **Placement** | The assignment of a job to a datacentre and an intended execution time/window. |
| **Pending job** | A job that has been submitted and/or assigned but has not started executing. The exact lifecycle states must be defined in the simulator. |
| **Running job** | A job whose execution has begun. Running-job migration is excluded from the primary scope. |
| **Carbon intensity** | Carbon emissions per unit of electricity, for example in grams of CO₂ per kilowatt-hour (`gCO2/kWh`). |
| **Energy consumption** | Electricity consumed by the job or the relevant share of facility load, measured or modelled in kWh. |
| **Modelled emissions** | Estimated energy multiplied by a chosen carbon-intensity factor, with the accounting boundary and units stated explicitly. |
| **Runtime estimate** | The runtime estimate available to the scheduler at a decision time. It must be distinguished from actual/simulated runtime used for evaluation. |
| **Queue wait** | Time from job submission or eligible release to the start of execution, according to the defined measurement convention. |
| **Uncertainty interval** | A range expected to contain an input value at a stated coverage level. It should be evaluated for calibration; it is not simply a guessed range. |
| **Decision flip** | A change or plausible change in the identity/ranking of the best feasible placement candidate when updated information or plausible input values are considered. |
| **Re-evaluation trigger** | The rule that decides whether the scheduler should invoke a new placement optimisation. |
| **Placement churn** | The number or rate of placement changes made while jobs are still pending. |
| **Optimisation overhead** | Time and/or computational resources spent deciding what to schedule. It is distinct from job runtime and placement churn. |
| **DRO** | Distributionally Robust Optimization: an optimisation approach that protects decisions against a specified set of plausible probability distributions, rather than relying only on one estimated distribution. Its exact formulation is not yet finalised. |
| **PUE** | Power Usage Effectiveness, a ratio that can be used to approximate facility energy relative to IT equipment energy. Whether PUE is included must be stated; it must not be multiplied in twice. |

---

## 7. What we are building — and what we are not building

### 7.1 The deliverable

A reproducible research simulator and evaluation pipeline with these major capabilities:

1. Import and normalise a selected workload trace.
2. Import and align carbon-intensity data to simulated time and virtual datacentre profiles.
3. Configure multiple virtual datacentres with resource capacities and energy assumptions.
4. Replay job arrivals and lifecycle events in simulated time.
5. Select an initial feasible placement for each job.
6. Update the scheduler's view as forecasts, queue conditions, and capacity change.
7. Use a decision-flip trigger to determine whether a pending job needs re-evaluation.
8. Invoke a planner when the trigger fires and change the placement only when a feasible alternative justifies it.
9. Record the actual/simulated environment separately from the information visible to the scheduling policy.
10. Compare several policies under common workloads, scenarios, random seeds, and accounting assumptions.
11. Export run configurations, raw metrics, aggregated tables, figures, and logs so results can be reproduced.
12. Generate a static, self-contained `dashboard.html` from saved results (no server needed).
13. Run the same simulation with each virtual datacentre as a separate service, first as local processes, then in Docker, then on AWS, with results identical to the normal run (the **deployment track**, Section 8.3).

### 7.2 Non-goals for the first working version

- Deploying a scheduler into real cloud infrastructure.
- Controlling actual datacentres or migrating live production jobs.
- Claiming measured real-world energy or emission reductions.
- Pretending that Alibaba's workload trace and the Indian regional grids correspond to real, geographically matched cloud facilities.
- Assuming that a public workload trace contains exact job-level power consumption, job deadlines, or every requested resource field.
- Building a complex forecasting model before a clean data pipeline and baseline simulator exist.
- Implementing the entire original Global–Local DRO architecture before the core trigger can be evaluated.
- Adding a live web dashboard before the simulator, experiments, and data accounting are correct. The static `dashboard.html` is in scope; a live viewer (Streamlit) is optional extension X9.
- Treating the deployment track as a real cloud scheduler. Its datacentre services hold simulated queues and never run real jobs, and running them on AWS does not measure AWS's energy or emissions.

### 7.3 MVP versus extensions

**Minimum viable research simulator (MVP):** one fully understood workload-trace release; a configurable fleet of virtual datacentres; a documented energy model; replayed carbon-intensity profiles; a valid event loop; FCFS and carbon-aware place-once baselines; periodic re-planning; a fixed-savings or prediction-error trigger; the decision-flip trigger; core metrics; and sensitivity experiments.

**Possible extensions:** stronger historical forecast calibration; additional workload traces; robust runtime quantiles; a deterministic mathematical optimiser; global–local coordination; a DRO planner; network transfer costs; richer PUE/power modelling; more workload classes; and large-scale stress tests.

---

## 8. Proposed system architecture

The architecture should be modular. It should be possible to replace the planner, energy model, uncertainty model, and trigger policy without rewriting the simulation engine.

### 8.1 High-level flow

```text
Workload Trace                 Carbon-Intensity Data
(Alibaba Cluster Data)         (Indian grid + NESO error paths)
         |                                  |
         v                                  v
  Workload Adapter                     Carbon Adapter
         |                                  |
         +---------------+------------------+
                         v
                 Data Normalisation
         timestamps, units, provenance, schema checks
                         |
                         v
                Scenario Configuration
       virtual DCs, capacities, power model, deadlines,
       uncertainty model, policy thresholds, random seeds
                         |
                         v
               Discrete-Event Simulator
      arrivals, queues, starts, finishes, forecasts, capacity
                         |
             +-----------+------------+
             |                        |
             v                        v
     Simulated Truth            Scheduler View
 actual runtime/energy,       forecasts, intervals,
 actual carbon profile,       delayed/inexact reports,
 actual completion          visible capacity/queue estimates
             |                        |
             |                        v
             |                Initial Placement Planner
             |                        |
             |                        v
             |                 Pending Placements
             |                        |
             +---------------> Re-Evaluation Trigger
                                      |
                          decision may have flipped?
                                      |
                                      v
                               Planner Interface
                         feasible candidates + score
                                      |
                                      v
                           Keep or update placement
                                      |
                                      v
                           Execution and event queue
                                      |
                                      v
                         Metrics, logs, experiment outputs
```

The separation between **simulated truth** and **scheduler-visible information** is essential. It prevents a policy from choosing based on future data or actual values that would not yet be available in a real system.

### 8.2 Main components

#### A. Data adapters

Each adapter reads a specific source release and maps source columns into the canonical schema. Adapters should preserve the original source, raw field name, unit, and any transformations. The core simulator should not depend directly on one trace's column names.

#### B. Data validation and normalisation

This layer checks duplicate identifiers, invalid timestamps, negative runtime/resource values, missing fields, unit consistency, data coverage, gaps in carbon time series, time zones, and forecast-versus-actual joins. It should write a data-quality report before experiments begin.

#### C. Workload model

Represents jobs, their arrival times, resource requests, runtime information, optional priorities/classes, and deadlines or timing constraints. The provenance of every derived or synthetic field must be retained.

#### D. Virtual datacentre model

Represents compute capacity, resource availability, queue state, power assumptions, a carbon-intensity profile, and any additional constraints. Datacentres are configurable simulation objects rather than claims about real cloud providers.

#### E. Energy and carbon model

Estimates job energy from execution time and a documented power model, optionally accounts for facility overhead with a stated PUE, and converts energy to modelled emissions using the carbon-intensity value associated with the simulated execution time and datacentre profile.

#### F. State and event engine

Processes events in timestamp order, updates queue and resource state, starts and completes jobs, introduces new forecasts, and notifies relevant policy components when information changes.

#### G. Candidate generation and feasibility checker

Generates possible datacentre/window placements, and rejects candidates that exceed available resources, miss hard deadlines, violate eligibility requirements, or conflict with reservations. The same feasibility rules must apply to every policy.

#### H. Placement planner

Scores feasible candidates and chooses one. Begin with a simple deterministic planner whose behaviour is easy to inspect. Later planners can include robust runtime assumptions or DRO. The planner must be separable from the decision trigger.

#### I. Uncertainty estimator

Produces intervals or distributions for the inputs that the scheduler does not know exactly, such as runtime, queue wait, and carbon intensity. Inputs may be estimated from historical data, derived from a calibration split, or generated synthetically for controlled stress tests. The method and coverage level need to be recorded.

#### J. Trigger policy

Decides whether a pending placement should be re-evaluated. The decision-flip trigger is the target policy. Baseline triggers should be separate implementations with independent configuration parameters.

#### K. Metrics and experiment runner

Collects per-job and per-run measurements, runs the same scenarios across policies, saves seeds/configurations, aggregates results, and creates reproducible tables and figures.

### 8.3 Deployment track: datacentres as separate services

The research runs keep everything in one Python process because that is fast and exactly reproducible. The **deployment track** (PRD §13.5) shows that the same scheduler also works when each virtual datacentre is a separate service reached over a network, as it would be across real sites.

**Who does what.**

- **Coordinator** (`flipwise run --mode remote`): the event loop, the simulated clock, the policy, the planner and the evaluator. It decides everything.
- **Datacentre service** (`flipwise dc-serve`, one per datacentre): holds that site's capacity, queue and running jobs, and starts queued jobs when there is room. It answers seven small JSON-over-HTTP requests (`/health`, `/reset`, `/enqueue`, `/remove`, `/dispatch`, `/complete`, `/state`).

**The rule that keeps it honest: simulated time, not real time.** The services never look at the wall clock. Every request carries the simulated time, and the coordinator sends requests one at a time in event order. If the services ran in real time, a one-week slice would take a week, and network delays would reorder events so that runs could not be repeated or compared fairly. With a simulated clock, the outputs (`jobs.csv`, `decisions.csv`, `events.log`) must be **byte-identical** to the in-process run. Any difference is a bug.

**Three stages, each built on the previous one.**

| Stage | What it means | When |
|---|---|---|
| **DT1 Local split** | Three service processes on one laptop (ports 8101–8103), started and stopped by `scripts/local_cluster.sh` | EL Phase 2, in parallel with the research work |
| **DT2 Docker** | The same four programs in four containers via `docker compose up`, so any machine gets an identical environment | EL Phase 3 |
| **DT3 AWS** | The Docker image on three small EC2 instances (default Mumbai region, `ap-south-1`), with a budget alert and a teardown script | EL Phase 3, after the main results exist |

AWS regions only host the services; the carbon signal still comes from the Indian carbon data. A datacentre labelled "Chennai" uses Southern-grid carbon data whether its service runs on a laptop or in Mumbai. The deployment track adds engineering realism and a measured network overhead. It does not change, or produce, research results.

The simulator must be designed for this from the start: datacentre state and dispatch live in their own module behind a `DatacentreClient` interface, with an in-process and an HTTP implementation.

---

## 9. How the simulation should behave

### 9.1 Job lifecycle

A useful starting state machine is:

```text
SUBMITTED -> PENDING_UNPLACED -> PENDING_PLACED -> RUNNING -> COMPLETED
                  |                  |
                  +---- infeasible / deadline-expired handling ----> REJECTED or MISSED
```

The precise states can change during implementation, but the simulator must define them clearly. For example, a job might be pending but not yet assigned a particular future window, or it might be pending with a reservation for a future window. That distinction affects resource reservations and candidate feasibility.

### 9.2 Discrete events

At minimum, the event engine should handle:

- job arrival/submission;
- initial placement decision;
- execution-window or scheduled-start eligibility;
- job start;
- job completion;
- carbon forecast update;
- actual/simulated carbon-intensity time-step change;
- resource/capacity update if the scenario models one;
- queue or runtime estimate update;
- decision-trigger evaluation;
- optional periodic re-planning tick;
- deadline expiry or job cancellation/rejection, where defined.

Events are processed chronologically. A deterministic tie-breaking rule is required when events share the same timestamp.

### 9.3 Execution and capacity

When a job starts, the simulator reserves or consumes its requested resources for the duration of execution, then releases them at completion. It must not schedule jobs in a way that overbooks the configured capacities. If the simulator permits future-window reservations, those reservations must be tracked and updated consistently when a pending placement changes.

A job's **actual/simulated execution duration** should be the basis for its completion time. The scheduler may use an estimate or an uncertainty interval, but must not see the future actual runtime at decision time.

### 9.4 Future information and forecast leakage

The scheduler may only see data that would be available at the current simulated decision time. The simulator's evaluator can hold the actual carbon intensity and actual/simulated execution values, but the scheduling policy must not access future realisations when making a placement.

For carbon data, distinguish:

- **forecast issue time:** when the forecast was produced/available;
- **target time:** the future interval the forecast describes;
- **realised/actual time:** the interval when the electricity carbon intensity is evaluated.

A historical dataset containing target-hour values is not necessarily a true historical forecast-vintage archive. To reconstruct what the scheduler could have known, the data must preserve or support the forecast issue time and target time. If it does not, the experiment must clearly use a proxy or synthetic forecast model rather than claiming an exact historical replay of forecast information.

### 9.5 No running-job migration in the main scope

The submitted report explicitly states that running jobs will not be migrated as part of the proposed mechanism. The first simulator should therefore only change pending placements. Do not silently include live migration costs or claims unless a later scope decision adds them.

---

## 10. How the decision-flip trigger is intended to work

This is the project's central mechanism. The exact mathematics and threshold values are implementation decisions to validate, not facts already established.

### 10.1 Placement candidates

For each pending job, a candidate can be represented as:

`candidate = (datacentre_id, execution_window)`

A candidate is considered only if it satisfies hard constraints such as:

- compute resource capacity;
- job/datacentre eligibility;
- any deadline or latest-start constraints;
- no conflict with reserved resources;
- any required transfer or execution-window constraints included in the scenario.

Infeasible candidates must not be treated as good options simply because their carbon score is low.

### 10.2 Candidate scoring

A candidate score may consider several terms:

- expected job energy and carbon emissions;
- expected queue wait and completion time;
- deadline-miss risk or lateness penalties;
- any modeled data-transfer or placement-change cost;
- the overhead of re-running the optimiser, where this is included in the decision rule.

The project must settle the objective formulation explicitly. For example, it might first remove candidates that violate hard deadlines and then minimise modelled carbon emissions subject to a bounded queue-delay/performance cost. Alternatively, it may use a documented multi-objective score. If using weighted sums, normalise units, justify weights, and run sensitivity analysis; arbitrary weights can dictate the results.

### 10.3 Uncertainty representation

For each input, the scheduler may have a point estimate and an uncertainty interval, such as:

- runtime estimate: `[runtime_low, runtime_high]`;
- queue waiting-time estimate: `[wait_low, wait_high]`;
- carbon intensity for the target window: `[carbon_low, carbon_high]`;
- available capacity or feasibility state, when uncertainty is explicitly modelled.

Each interval needs a method, stated coverage target, and empirical calibration check where the data permit it. Do not call an interval “calibrated” just because it has lower and upper bounds.

### 10.4 Decision-flip test

At the original decision time, the planner selects the best feasible candidate based on the information then available. At a later update, the trigger examines the current candidate estimates and their uncertainty.

Conceptually, the trigger asks:

1. Is the current placement still feasible under the updated state?
2. Is there another candidate that is feasible and plausibly better under the new information?
3. Is the uncertainty large enough that the current candidate's ranking could change relative to the alternative?
4. Is this possibility material rather than a tiny numerical change or pure tie-breaking noise?

One possible implementation is interval/rank analysis: if candidate-score intervals overlap in a way that permits a different candidate to rank first, a decision flip is possible. More sophisticated implementations could sample plausible inputs and estimate the probability that the best candidate changes. These are alternative designs; they should not be mixed without a documented choice.

### 10.5 Net-benefit gate

Even when a flip is possible, re-evaluation should happen only if its expected benefit is large enough. A conceptual rule is:

`expected improvement from reconsideration > optimisation cost + placement-change cost + configured safety margin`

The terms need defined units and semantics. Optimisation CPU time is not automatically an emission quantity; if the team wants to add optimisation energy to the carbon total, it must measure/model that energy and use a clear accounting boundary. Otherwise, report compute time separately and treat it as an overhead metric.

### 10.6 Trigger versus planner

Keep these operations separate:

- **Trigger:** decides whether re-optimisation is warranted.
- **Planner:** chooses the best feasible placement when called.
- **Acceptance/change rule:** decides whether the new result is materially better than the old placement and therefore whether to apply it.

Separating them makes experiments interpretable. It also allows the same planner to be evaluated with different triggers and lets the team study trigger quality independently from optimiser quality.

### 10.7 Important edge cases

- If there is no alternative feasible candidate, do not call a re-optimisation merely because uncertainty exists.
- If the current placement is no longer feasible, the system may need emergency re-planning regardless of the ordinary trigger; count this separately.
- If candidates are tied or nearly tied, use a deterministic tie-breaker and avoid placement thrashing.
- Apply a cooldown or hysteresis rule if repeated near-identical updates would cause oscillation; report the rule and test its impact.
- Ensure every trigger is evaluated only for jobs that remain pending.
- A trigger that fires must be recorded even if the planner retains the original placement.

---

## 11. Dataset plan

The submitted report names two principal datasets: **Alibaba Cluster Data** for workload characteristics and **NESO regional carbon-intensity information** for electricity carbon signals. Since PRD v0.5 the simulated world is Indian: carbon truth comes from Indian grid data and CEA factors, and the NESO archive supplies only the shape of real forecast errors (Section 11.2).

### 11.1 Workload trace: Alibaba Cluster Data

Official repository: <https://github.com/alibaba/clusterdata>

Alibaba publishes multiple production-cluster trace releases. The repository currently lists several GPU trace releases, including v2020, v2023, v2025, and v2026, as well as other cluster and serving traces. The exact release must be chosen after reviewing the schema, licence/access terms, file size, and suitability for the simulation.

The working PRD recommends starting with a manageable, fully understood trace. The v2020 GPU trace is a plausible first candidate because the repository describes it as covering over 6,500 GPUs on around 1,800 machines over roughly two months, for AI/ML workloads. The v2026 GPU release is much larger and is described as a six-month anonymised trace covering up to 155,410 GPUs across 37,707 GPU servers, with tables for workload mix, job/model types, priorities, resource requests and utilisation, inventory/topology, network traffic, and execution-time analysis. It may be useful for larger validation but has additional data-processing cost. **Decision (PRD v0.2, D5): v2020 is the MVP dataset.** It was downloaded, checksum-verified and audited (PRD §6.1); v2026 is extension X6.

#### Fields to audit

The selected release should be checked for:

- stable job/task identifiers;
- arrival/submission timestamps;
- start/end timestamps, or enough information to derive duration;
- resource requests and observed usage (GPU, CPU, memory, where available);
- resource type and machine/server characteristics;
- job/model/workload type;
- priority or service class;
- queue or execution information needed to reconstruct resource occupation;
- terms and documentation required for proper citation.

Do not assume every field is available in every trace release. Fields missing from the selected dataset must either be derived from legitimate source fields or generated synthetically for controlled scenarios, with the distinction recorded.

#### Canonical job representation

The internal representation can include the following fields when supported:

| Field | Meaning | Evidence/provenance rule |
|---|---|---|
| `job_id` | Stable job identifier | Source identifier or documented generated key |
| `arrival_time` | Submission/arrival time, normalised to UTC | Source field or justified transformation |
| `observed_start_time` | Historical start time | Source if available |
| `observed_end_time` | Historical completion time | Source if available |
| `observed_runtime_s` | Observed duration | Source or derived from valid start/end timestamps |
| `gpu_request` | GPU count/type request | Source if available; otherwise synthetic or omitted |
| `cpu_request` | CPU request | Source if available; otherwise synthetic/omitted |
| `memory_request_gb` | Memory request | Source if available; otherwise synthetic/omitted |
| `workload_class` | Training/inference/other category | Source or documented mapping |
| `priority` | Priority class | Source or explicitly marked default/synthetic |
| `deadline_time` | Completion deadline | Source if available; otherwise scenario-generated and marked synthetic |
| `runtime_estimate` | Runtime information available to the scheduler | Estimated from past data/model; never future actual runtime |
| `runtime_actual_s` | Actual duration used in replay/evaluation | Source-derived or simulated value; not visible to policy in advance |
| `field_provenance` | Source/derived/synthetic marker | Required for every field not directly present in source |

Historical start/end times can be useful for deriving durations and analysing workloads, but replaying historical schedules exactly is not the same as simulating a new scheduling policy. If a policy changes a job's datacentre or start time, execution time and workload context should be treated consistently; the simulator must state whether it assumes runtime is independent of placement or models hardware heterogeneity.

#### Synthetic data handling

Deadlines, job runtime estimates, power values, region mappings, or resources may not be available directly in the selected release. If the simulator generates any of these, it must:

1. document the distribution or rule used;
2. give the field a provenance marker;
3. use fixed seeds where randomness is involved;
4. run sensitivity experiments across reasonable alternatives; and
5. avoid presenting synthetic fields as measurements from Alibaba.

### 11.2 Carbon-intensity data: Indian grid conditions (PRD v0.5)

The simulated world is **India only** (decision D17). The workload data stay as available (the Alibaba trace), but the datacentres, the grid and the clock are Indian:

| Virtual datacentre | Regional grid |
|---|---|
| Delhi NCR | Northern (NR) |
| Mumbai | Western (WR) |
| Chennai | Southern (SR) |

These are India's main datacentre hubs; the virtual datacentres are not real facilities. Job submission times are aligned to **IST**, so daytime jobs meet the Indian solar midday.

#### Truth: what the Indian grid actually emitted

For each region and half-hour, carbon intensity is computed from **generation by fuel** multiplied by **fuel emission factors from the CEA CO2 Baseline Database** (India's official emission-factor source), divided by total generation. Hydro, nuclear, solar and wind count as zero. Power flows between regions are ignored (a production-based figure), which is stated as a limitation. The preferred source of regional generation by fuel is Grid-India; whether it is available at hourly or 15-minute resolution for 2023 is not yet confirmed (blocker B4), and the PRD lists fallbacks.

#### Forecasts: why and how they are built

The decision-flip trigger needs the forecasts a scheduler would really have seen at each moment, not the final values. Nobody has archived Indian carbon-intensity forecasts. Great Britain is the one place where every half-hourly forecast was saved (the NESO forecast-tracking archive), so the project borrows **the shape of real forecast errors** from there:

1. From the archive, compute how wrong each British forecast was at each lead time, and how it was revised capture by capture.
2. Scale those errors to Indian intensity levels.
3. Add them to the Indian truth: Indian forecast = Indian truth + scaled real error.

This keeps the behaviour of a real operational forecast: errors that grow with lead time, revisions that drift smoothly, and the same missing captures. Plain random noise would make forecasts jitter every half hour, which would cause extra job moves for every policy and unfairly favour decision-flip's noise margin.

The honest limitation: the errors have the right statistical shape, but they come from British weather, not Indian monsoon or solar variability. Every report must say so, and the forecast-error scaling sweep shows how sensitive results are to it.

#### What to expect from Indian data

India's regions share one synchronous national grid, so the carbon difference *between* Delhi, Mumbai and Chennai may be smaller than between countries, while the difference *across the day* (solar midday) may be large. Spatial shifting may therefore help less than temporal shifting. That is a result to measure (hypothesis H3), not a problem.

### 11.3 Mapping traces to virtual datacentres

Alibaba traces and Indian regional carbon-intensity series do not automatically describe the same physical facilities or geography. The simulation should therefore define **virtual datacentres**, each with a transparent mapping to a carbon profile and a configured capacity/power model.

A virtual datacentre configuration should specify at least:

- `datacenter_id`;
- carbon-intensity profile (Indian regional grid);
- CPU/GPU/memory capacity;
- hardware/resource-type assumptions;
- power-model parameters;
- optional PUE setting and its source/assumption;
- permitted job types and any transfer/eligibility constraints.

Make the mapping configurable and publish it as part of the experimental configuration. Do not imply that a virtual facility is a real Alibaba facility or a real datacentre in that Indian hub.

### 11.4 Data citation and reproducibility

For every input dataset, record:

- official URL and access date;
- trace release/version;
- licence or access terms;
- files downloaded and their checksums where practical;
- schema version and processing steps;
- filters or excluded records;
- timestamp and unit conversions;
- derived and synthetic fields;
- known data gaps or limitations.

Do not commit large raw dataset files to source control if their size or terms make that inappropriate. Provide a script and instructions for a user with legitimate access to download and preprocess the data.

---

## 12. Energy and carbon-emission calculation

This is a critical part of the project because carbon results are only as defensible as the energy model and carbon-intensity inputs behind them.

### 12.1 Base calculation

If the job's average IT power is represented in kilowatts and its execution time in hours:

`job_energy_kWh = average_power_kW × execution_time_hours`

If electricity carbon intensity is in grams of CO₂ per kilowatt-hour:

`job_emissions_kgCO2 = job_energy_kWh × carbon_intensity_gCO2_per_kWh / 1000`

For a job whose power varies over time, the more accurate calculation is a sum/integral across intervals:

`job_energy_kWh = Σ(power_kW(t) × interval_duration_hours)`

`job_emissions_kgCO2 = Σ(energy_kWh(t) × carbon_intensity_gCO2_per_kWh(t)) / 1000`

The time alignment matters: use the carbon intensity for the intervals when the energy is consumed, not merely the carbon intensity at job submission or placement time.

### 12.2 What if the dataset does not contain energy?

The workload trace may provide resource requests and utilisation without exact job-level power. If direct energy measurements are unavailable, use an explicit energy model. Possible model forms include:

- a documented power estimate for each GPU/CPU resource type multiplied by active resource count and execution time;
- a power curve that depends on utilisation, when the necessary source data or defensible assumptions exist;
- a simplified constant-average-power-per-resource model for the MVP, followed by low/base/high sensitivity analyses.

The PRD fixes the formula (PRD §7.1: allocated power from GPU and CPU requests × actual runtime × truth intensity per half-hour slot). Power coefficients are only partly sourced: NVIDIA datasheet values for V100 (300 W), P100 (250 W) and T4 (70 W) are cited, while older GPUs, CPU per-core power and the utilisation factor remain open (blocker B3). Until B3 is closed, results are reported as relative. **Do not invent a “standard” wattage and present it as measured fact.** Each coefficient needs a source or a clearly labelled scenario assumption.

### 12.3 Facility power and PUE

If the model estimates IT-equipment energy only and the study intends to estimate total facility electricity, it may apply a stated PUE factor:

`facility_energy_kWh = IT_energy_kWh × PUE`

This should only be done when the meaning/source of PUE is documented and is appropriate for the model. If the power input already represents total facility energy, do not multiply by PUE again. For the MVP, it may be safer to begin with a clear IT-energy model and add facility overhead as a sensitivity parameter rather than obscure an uncertain assumption.

### 12.4 Which carbon factor should be used?

For time-shifting experiments, the primary scheduling signal is the time- and region-varying Indian carbon-intensity series of Section 11.2. A fixed annual-average factor cannot represent hour-by-hour changes and does not replace the dynamic series in the main experiment.

The principal also suggested using an established emissions table. With an Indian simulated world, the working answer is the **CEA CO2 Baseline Database for the Indian Power Sector** (Central Electricity Authority): it supplies the fuel emission factors used to build the Indian series, and its grid-average factor is used in a constant-carbon sanity check. Other possibilities, if the principal meant something else:

- **Electricity-generation technology/lifecycle factors:** if he meant a comparison table for coal, gas, hydro, wind, solar and other sources, use a clearly scoped IPCC-based lifecycle reference and keep lifecycle separate from operational grid intensity.
- **Carbon budget or target:** if he meant a recommended emissions limit, implement it as a separate constraint, not as a conversion factor.

The exact table the principal intended was not recorded. Confirm with him that the CEA database is what he meant.

### 12.5 Avoid double-counting and mixed boundaries

Do not multiply the Indian grid carbon intensity (already built from CEA factors) by another electricity-generation factor describing the same electricity. That would generally count the electricity emissions twice. State whether each result is `CO2` or `CO2e`, and whether it represents operational/grid-related emissions or lifecycle emissions. Do not mix those definitions without an explicit reason.

### 12.6 What the results may claim

The simulator can report **modelled emissions under stated energy and grid-intensity assumptions**. It cannot claim that it directly measured a real-world emissions reduction. This limitation is already explicit in the submitted report.

---

## 13. Scheduling objective and feasibility

### 13.1 Hard constraints before scoring

The feasibility checker should be common to all policies. Before comparing candidates, reject any candidate that fails constraints such as:

- requested GPU/CPU/memory exceed the available capacity;
- reserved resources would overlap incompatibly with another job;
- execution cannot finish by a hard deadline or violates a stated latest-start rule;
- the job is ineligible for the chosen resource type or datacentre;
- any modelled data-transfer, location, or operational constraint is violated.

Not all of these fields are necessarily available in the source trace; some may be experiment parameters. Their provenance must be documented.

### 13.2 Multi-objective nature of the problem

A lower-emissions placement is not automatically best if it misses the deadline or creates unreasonable queue delay. Conversely, a small carbon improvement may not justify expensive scheduling computation or repeated placement changes.

The system needs an explicit objective formulation. Reasonable choices include:

1. **Constraint-first design:** remove candidates violating hard deadlines and capacity; then minimise modelled emissions subject to configured queue-delay or performance bounds.
2. **Lexicographic design:** first satisfy essential job/operational constraints, then minimise emissions, then use wait/overhead as tie-breakers.
3. **Weighted multi-objective design:** combine normalised carbon, latency, delay, and change cost in a score. If weights are used, justify them and vary them in sensitivity experiments.

No single formulation is finalised yet. It must be decided before comparing the main policies. Otherwise the score can be tuned after the fact to manufacture a favourable result.

### 13.3 Deadline handling

The selected trace may not contain explicit deadlines. In that case, the project can generate deadline scenarios from runtime or submission time, but those deadlines must be labelled synthetic. Test multiple levels of deadline tightness. Report the proportion of jobs that miss deadlines and clarify if jobs that cannot be scheduled are rejected, marked missed, or left pending through the evaluation horizon.

### 13.4 Queue and capacity interaction

A policy that moves too many jobs toward a temporarily cleaner datacentre may create a “stampede” effect: congestion rises, wait times increase, and some of the apparent carbon benefit may disappear because jobs run later or miss deadlines. Candidate scoring must use the shared capacity/queue state and reserve resources consistently, rather than independently treating every job as if it had a dedicated datacentre.

---

## 14. Baselines and alternative policies

The project must compare the proposed trigger with alternatives that solve the same task under the same simulator assumptions. The baseline set should be fixed before final experiments.

### 14.1 FCFS or simple queue-based policy

A First-Come, First-Served (FCFS) policy provides a simple non-carbon-aware reference. It should respect the simulator's resource constraints. It establishes how carbon-aware decisions compare with a basic scheduling approach.

### 14.2 Carbon-aware place-once

Use current estimates to choose an initial carbon-aware placement, then do not reconsider the job unless an operational violation forces re-planning. This tests whether re-evaluation adds value beyond making a good initial choice.

### 14.3 Periodic re-planning

Run re-optimisation on a fixed schedule, such as every configured interval. The interval is a configuration parameter. Periodic re-planning is a key baseline because it is straightforward and responsive to updated information, but can make unnecessary calls.

### 14.4 Prediction-error trigger

Reconsider when a prediction changes or its error exceeds a configured threshold. Define exactly which prediction and error are used, and ensure the trigger does not use future actual values unavailable to the scheduler. If actual values are used for offline evaluation, keep them out of the live decision path.

### 14.5 Fixed carbon-savings threshold

Reconsider only when the estimated emissions savings of an alternative exceed a fixed threshold or percentage. This tests whether a simple benefit gate can achieve similar performance without examining whether candidate rankings could flip under uncertainty.

A “CATS-style savings-gate baseline” should not be confused with implementing or reproducing the whole CATS simulator. The PRD therefore names this baseline the **fixed-savings gate** (`fixed_savings(g)`) and claims no CATS equivalence (PRD §5, D8).

### 14.6 Decision-flip-triggered re-evaluation (proposed policy)

Reconsider when updated information and the specified uncertainty model indicate that a different feasible candidate may become best, and when the expected net benefit clears the configured gate. It should record:

- why the trigger fired;
- which candidate(s) could change the ranking;
- whether re-optimisation ran;
- whether the placement changed;
- estimated benefit and actual/simulated outcome;
- trigger and planner overhead.

### 14.7 Robust runtime or uncertainty-aware placement

A baseline such as `q90` runtime placement chooses capacity/window decisions using a high runtime quantile rather than the mean. It may help distinguish the value of robust placement from the value of selective triggering. The exact percentile and its calibration data must be stated. This is an optional extension if not feasible for the first set of runs.

### 14.8 Oracle reference

An oracle can use future information to estimate a theoretical best-case result. It is not an implementable scheduler and must never be presented as a deployable baseline. State exactly which future information it can see. Use it as a lower-bound/reference for possible emissions or an upper-bound for a clearly defined benefit, not as an equivalent competitor.

### 14.9 Deterministic and DRO planner variants

The original report's intended comparison includes deterministic/expected-value scheduling and versions in which global or local DRO is replaced by a deterministic counterpart. This can be implemented after the core trigger. To isolate contributions, compare triggers using the same planner and compare planners using the same trigger. Otherwise it will be difficult to tell whether an improvement came from the trigger, the optimiser, or both.

---

## 15. Metrics and their meaning

Every result should be reported with its definition, unit, aggregation method, and whether lower or higher is better.

| Metric | Suggested definition | Typical interpretation |
|---|---|---|
| **Total modelled emissions** | Sum job emissions over completed/executed work, with the treatment of unfinished jobs stated | Lower is better only when work completed and deadline performance are comparable |
| **Emissions per completed job** | Total emissions divided by the number of completed jobs | Helps control for differing completion counts |
| **Deadline-miss rate** | Jobs completing after the deadline divided by jobs with deadlines, plus a declared rule for uncompleted jobs | Lower is better |
| **Queue delay** | Start time minus arrival/eligible-release time | Lower is generally better; define whether it is mean, median, p95, etc. |
| **Completion/throughput** | Jobs completed within the experiment horizon, and/or completed per unit time | Higher is generally better for comparable workloads |
| **Resource utilisation** | Used resource-time divided by available resource-time, calculated per resource type where possible | Contextual metric; extremely high utilisation can also increase queue delays |
| **Re-evaluation calls** | Number of times the trigger invokes the planner | Lower indicates less repeated optimisation, but cannot be interpreted without outcome metrics |
| **Placement changes / churn** | Number of changed pending assignments; optionally normalised per job | Lower can mean stability, but zero changes can also mean the policy missed useful opportunities |
| **Scheduling overhead** | Wall-clock and/or simulated CPU time spent in trigger/planner calls | Lower is usually better for comparable result quality |
| **Energy consumption** | Modelled kWh under the chosen energy accounting boundary | Needed to interpret the emission results; report assumptions |
| **Interval coverage** | Fraction of true/simulated values falling inside nominal uncertainty intervals | Should be close to the intended coverage, with subgroup/horizon checks |
| **Interval width** | Width of runtime/queue/carbon interval, with units stated | Narrower is useful only when coverage remains adequate |
| **Robustness** | Metric changes under defined perturbations to forecast error, demand, or capacity | Shows operating conditions where the policy degrades |

### Important comparison rule

Emissions alone are not sufficient. A policy could lower total emissions simply because it completes fewer jobs or delays work beyond the evaluation horizon. Always report emissions alongside completed work, deadline misses, queue delay, and workload completion. When feasible, show both absolute emissions and normalised values such as emissions per completed job.

### Overhead accounting

Record actual wall-clock time spent by each policy and the number of optimisation calls. If the study claims that optimisation overhead also affects emissions, it must model the energy used by the scheduling computation and clearly describe that additional accounting. Otherwise, keep scheduling overhead as a separate performance metric.

---

## 16. Experiment plan

A sound experiment plan should make the policy comparisons fair, reproducible, and capable of revealing when the trigger fails.

### 16.1 Start with a small, deterministic validation scenario

Before using a large trace, construct a small scenario whose correct behaviour can be manually reasoned about. Example:

- two or three virtual datacentres with known capacities;
- a small number of jobs with explicit arrival/runtime/deadline values;
- carbon intensity that changes at known times;
- one case where the best placement remains the same despite a forecast change;
- one case where the best placement changes;
- one case where a cleaner option becomes infeasible due to capacity;
- one case where a possible flip is too small to clear the net-benefit gate.

Unit tests should establish that the simulator respects capacity, does not use future data, and changes a placement only when the policy permits it.

### 16.2 Trace-replay baseline experiment

Once the basic simulator passes validation, replay a selected Alibaba workload sample across a configurable fleet of virtual datacentres with a carbon series and explicit energy model. Use the same input trace and scenario configuration for each policy.

### 16.3 Sensitivity variables

Vary one factor at a time initially, then study carefully selected interactions:

- **Workload intensity:** low, medium, and high offered load relative to configured capacity.
- **Capacity pressure:** generous versus constrained resource availability.
- **Carbon-intensity spread:** little difference versus substantial difference between regions/windows.
- **Forecast error:** low, moderate, and high error; include biased and noisy cases where relevant.
- **Interval calibration:** calibrated intervals versus deliberately under/over-covering intervals.
- **Deadline tightness:** loose, moderate, and tight deadlines.
- **Job-size heterogeneity:** similar-sized jobs versus a mix of short and long jobs.
- **Update frequency and delay:** faster/slower forecasts and delayed state reports.
- **Trigger benefit threshold:** sweep thresholds rather than selecting a single convenient value.
- **Re-planning interval:** compare several periodic baselines.
- **Energy-model parameters:** low/base/high power assumptions and optional PUE scenarios.

### 16.4 Chronological data splits

Where data-based estimates are trained or calibrated, use chronological splits so information from the evaluation future does not leak into the calibration process. For time-series carbon forecasts, a possible scheme is:

- an earlier period to fit the uncertainty model;
- a subsequent calibration period to choose interval quantiles/coverage;
- a later held-out test period for final comparisons.

The exact period lengths depend on data availability and seasonality. If historical forecast vintages are not available, state that limitation and use an alternative uncertainty experiment rather than pretending the split solves the archive gap.

### 16.5 Repeated runs and statistical reporting

Use fixed seeds and repeat runs when any component is random. Where possible, use the same seeds and workload subsets for every policy so comparisons are paired. Report means and variability (for example, standard deviation or confidence intervals), not one lucky run. Do not overstate statistical significance if the sample size or independence assumptions do not support it.

### 16.6 Ablation experiments

Ablations can isolate:

- trigger without uncertainty intervals;
- decision-flip check without the net-benefit gate;
- net-benefit gate without decision-flip analysis;
- point estimates versus interval estimates;
- runtime uncertainty versus carbon-intensity uncertainty;
- placement-change penalty disabled/enabled;
- delayed/inaccurate queue-state information disabled/enabled;
- deterministic planner versus robust/DRO planner, if implemented.

The aim is to learn which mechanism accounts for any observed result.

### 16.7 Fairness requirements

All policies must use:

- the same job trace and evaluated time horizon;
- the same virtual datacentre capacities;
- the same energy/power assumptions;
- the same carbon-intensity target values used by the evaluator;
- the same feasibility and deadline semantics;
- the same initial information, except for explicitly defined policy differences;
- the same stopping rule and treatment of unfinished jobs.

The only intended difference should be the policy/trigger/optimizer being tested. A policy must not receive extra future information unless it is explicitly the oracle reference.

---

## 17. Implementation structure

The core research logic lives in ordinary source modules, not in exploratory notebooks. The PRD fixes one small package (PRD §13.1, decision D14):

```text
flipwise/
├── pyproject.toml, uv.lock, README.md, CLAUDE.md, LICENSE, .gitignore
├── Dockerfile, docker-compose.yml       # deployment track DT2
├── docs/            prd.md, explanation.md, helpfullinks.md
├── configs/         base.yaml, energy.yaml, policies.yaml, sweeps/*.yaml
├── scripts/         download/checksum scripts, local_cluster.sh (DT1), aws/ (DT3)
├── src/flipwise/
│   ├── cli.py, config.py, models.py
│   ├── ingest.py          # Alibaba, Indian grid and NESO-archive adapters, manifests
│   ├── carbon.py          # forecasts by vintage, truth, residual quantiles
│   ├── energy.py          # power, energy, emissions
│   ├── estimates.py       # runtime quantiles, queue-wait profiles
│   ├── simulator.py       # event loop, simulated clock, SchedulerView
│   ├── datacentre.py      # one site's capacity, queue and dispatch
│   ├── dcservice.py       # the same datacentre as an HTTP service (DT1–DT3)
│   ├── planner.py         # candidates, feasibility, scoring, lower bound
│   ├── policies.py        # the seven policies
│   ├── metrics.py, reporting.py, dashboard.py
├── tests/           fixtures/toy/ + one test file per module
├── data/            README.md; raw/ and processed/ are git-ignored
└── results/         git-ignored run outputs and dashboard.html
```

Data preparation, simulation mechanics, energy accounting, uncertainty, planning, triggers, metrics and experiment orchestration stay in separate modules so each can be tested alone.

### 17.1 Technical stack (decided in the PRD)

- **Language and environment:** Python 3.12, managed with `uv` (lockfile committed).
- **Data processing:** pandas and NumPy (decision D4; no Polars).
- **Simulation engine:** a small custom `heapq` event queue (decision D3; SimPy cannot cleanly cancel future events, which re-placement needs).
- **Configuration:** YAML (PyYAML), validated in `config.py`.
- **Storage:** CSV for processed data and results; JSON manifests. Parquet only if CSV becomes a measured bottleneck.
- **Plots:** Matplotlib; Plotly optional for an interactive `dashboard.html`.
- **Testing and linting:** pytest and ruff.
- **Optimisation:** deterministic candidate scoring only. LP/MILP/robust solvers are needed only for the DRO extension (X1).
- **Deployment track:** stdlib `http.server` and `urllib` for the services (no web framework), Bash for the local cluster script, Docker Compose for DT2, and AWS EC2 + ECR for DT3.
- **Reproducibility:** pinned dependencies, configuration files, seeds, data manifests and saved per-run outputs.

---

## 18. Implementation phases

The PRD roadmap (PRD §18) has nine build phases plus a parallel deployment track. No phase starts before the previous one's exit criterion is met.

| Phase | Build | Exit criterion |
|---|---|---|
| 1. Setup and audit | Repo, `uv`, ruff, pytest; download the v2020 trace; clone the forecast archive at a fixed commit | Checksums match; audit numbers reproduced by a script |
| 2. Canonical data | `ingest alibaba`, `ingest india`, `ingest carbon`, `build-forecasts`, manifests, `validate` | Clean job, Indian truth and forecast CSVs with coverage reports; Indian data source (B4) and archive coverage (B2) checked |
| 3. Deterministic core | Job and datacentre models, event loop, queues and dispatch behind `DatacentreClient`, toy scenario, FCFS | Toy FCFS output equals the hand-computed `expected.yaml` |
| 4. Energy and place-once | Emissions model, carbon views, planner (candidates, feasibility, scores), place-once | Toy emissions exactly right; constant-carbon test passes |
| 5. Baselines | Runtime and wait estimates, periodic, pred_error, fixed-savings, rescue, throttling | All baselines run on the toy scenario |
| 6. Decision-flip | Lower-bound screen, noise margin, interval fallbacks | Flip / no-flip / small-gain toy cases pass; θ = 0 decisions equal fixed-savings |
| 7. Experiment runner | `compare`, `sweep`, `report`, metrics, plots, manifests | A comparison on toy and one dev replicate produces `summary.csv` and figures |
| 8. Real-trace evaluation | Fit estimators, tune thresholds on validation data, freeze them, run the test set once, sweeps and ablations | Frozen configs committed; test results and worse-regime table produced |
| 9. Analysis and package | Report figures, limitations, reproducibility README, EL report updated to match what was built | A new machine reproduces the summary tables from raw downloads |

**Deployment track** (Section 8.3), owned by one team member, never blocking the phases above:

| Stage | Build | Exit criterion |
|---|---|---|
| DT1. Local split | Datacentre HTTP service, `flipwise dc-serve`, `--mode remote`, `scripts/local_cluster.sh` | Toy run through three local services is byte-identical to the in-process run; killing a service aborts the run cleanly |
| DT2. Docker | `Dockerfile`, `docker-compose.yml` with three datacentre containers and a coordinator | `docker compose up` from a clean clone reproduces the in-process toy and dev-replicate outputs |
| DT3. AWS | Image in ECR, three small EC2 instances, budget alert, launch and teardown scripts | Same outputs on AWS; network latency and cost reported; no resources left running |

### 18.1 How the phases map to the EL reviews

| EL review | Work | Must show |
|---|---|---|
| **Phase 1: pitch** | Done | — |
| **Phase 2: partial results** | Build phases 1–6 on one validation week (10 % job sample), the minimum of phase 7 (`run`, metrics, dashboard), and DT1. Policies: FCFS, place-once, periodic, fixed-savings, decision-flip | (1) Hand-checked toy emissions. (2) At θ = 0, decision-flip makes identical decisions to fixed-savings with fewer planner calls. (3) One results table for the week. (4) `dashboard.html`. (5) DT1: toy scenario through three local services with identical outputs (presented without it if late). |
| **Phase 3: full results and paper** | Rest of phases 5 and 7 (pred_error, perfect-information reference, `compare`/`sweep`/`report`), phases 8–9, DT2, then DT3 once the main results exist. DRO (X1) and a live viewer (X9) only after that | Final test results, worse-regime table, full dashboard, reproducibility package, Docker run, AWS run matching the in-process output, paper/report |

---

## 19. Principal's Phase 1 feedback and how it affects the work

The team reported two suggestions from the principal after the presentation. The presentation was received positively, but the precise identity of the emissions table was not recorded.

### 19.1 Suggestion 1 — Use an established carbon-emissions table/reference

The principal mentioned an established table containing approximate/average carbon-emission values or reference values. The team should use this suggestion to make the emissions calculations more defensible, but must first clarify which kind of table he intended.

Possibilities include:

1. **Electricity conversion factors** for converting kWh purchased/consumed into greenhouse-gas emissions.
2. **Emission factors by electricity-generation technology**, such as coal, gas, hydro, wind, and solar, potentially including operational versus lifecycle emissions.
3. **An emissions threshold, benchmark, or carbon budget**, which would be a target rather than a conversion factor.

With the Indian setting (PRD v0.5), the **CEA CO2 Baseline Database for the Indian Power Sector** is the natural candidate: India's official source of grid and station emission factors, published with a user guide per version. The UK Government's 2026 conversion factors were the earlier candidate for the GB setting. The principal's wording does not establish which table he meant, so confirm it.

For the project, use the dynamic Indian carbon-intensity series (Section 11.2) for the main time/location scheduling signal. Use a standard emissions conversion table as a documented reference or validation source when appropriate. Do not substitute a static annual-average factor for the dynamic signal in the main shifting experiment, and do not apply two factors to the same electricity in a way that double-counts emissions.

**Action:** ask the principal for the table name, URL, paper/book, or a sample row. Record the answer in the data/accounting methodology.

### 19.2 Suggestion 2 — Refer to Pinedo's book

The likely reference is:

**Michael L. Pinedo, _Scheduling: Theory, Algorithms, and Systems_, 6th edition, Springer, 2022.**  
Official publisher page: <https://link.springer.com/book/10.1007/978-3-031-05921-6>  
DOI: <https://doi.org/10.1007/978-3-031-05921-6>

The Springer description says the sixth edition covers deterministic scheduling, stochastic scheduling models where processing times and other data are uncertain, and scheduling in practice including algorithms and system design. These are relevant to this project because the simulator needs clear scheduling models and constraints, and because the research includes uncertainty and practical replanning overhead.

Topics worth focusing on include:

- scheduling models and notation;
- parallel-machine scheduling;
- deterministic versus stochastic scheduling;
- processing-time uncertainty;
- scheduling objectives and constraints;
- practical heuristics and system design.

The book provides scheduling theory; it is not the source of electricity-emission factors. The title above is a strong match for “Pinedo,” but the team should confirm whether the principal meant a different book.

### 19.3 How to document the feedback in the final report

The methodology/report should eventually state:

- the exact emissions table/reference selected and why it matches the chosen accounting boundary;
- how it is used to build the Indian time-varying carbon intensity;
- the relevant scheduling concepts taken from Pinedo;
- which modelling choices are literature-grounded and which remain scenario assumptions.

Do not claim that the principal endorsed a specific table or a specific implementation method unless that detail was actually confirmed.

---

## 20. Literature context already present in the submitted EL report

The submitted report reviews six works and positions the research gap around the decision to re-evaluate pending workloads. The descriptions below reflect the report's framing; they are not a substitute for reading and verifying the original publications.

### 20.1 Carbon-aware scheduling

**Radovanović et al., “Carbon-Aware Computing for Datacenters” (2023).** The report describes this work as using electricity carbon-intensity forecasts and Virtual Capacity Curves to coordinate flexible workload demand with periods of lower-carbon electricity availability. It provides background for using the grid carbon signal in scheduling.

**Hall et al., “Carbon-Aware Computing for Data Centers with Probabilistic Performance Guarantees” (2025).** The report describes a combination of day-ahead planning and real-time placement, with uncertainty and performance requirements accounted for. It is relevant to scheduling under uncertain operating conditions.

### 20.2 Uncertainty-aware carbon scheduling

**Li, Liu, and Ding, “Uncertainty-Aware Decarbonization for Datacenters” (HotCarbon 2024).** The report describes the use of conformal prediction to account for uncertainty in carbon-related estimates. It motivates studying uncertainty-aware decisions, while the project's narrower question is whether uncertainty should trigger re-optimisation.

### 20.3 Limits and trade-offs of workload shifting

**Sukprasert et al., “On the Limitations of Carbon-Aware Temporal and Spatial Workload Shifting in the Cloud” (EuroSys 2024).** The report cites this work to emphasise that theoretical shifting opportunities can be limited by actual operational constraints.

**Hanafy et al., “Untangling the Carbon-Cost Tradeoffs and Stampede Effect Challenges in Cloud Computing” (2026, as cited in the report).** The report uses this work to motivate attention to carbon/cost/performance trade-offs and the risk that coordinated shifting concentrates demand and creates congestion.

### 20.4 Simulation work

**Chen and Zong, “CATS: A Carbon-Aware Task Simulator for Reducing AI Data Center Emissions” (2026, as cited in the report).** The report identifies CATS as a carbon-aware task simulator and uses it to justify simulation-based evaluation. The team should inspect the paper and its available code/data to decide how to make a fair baseline comparison. A fixed-savings trigger inspired by a paper is not the same thing as reproducing the full simulator.

### 20.5 Research gap as currently stated

The report's proposed gap is not that carbon-aware scheduling or uncertainty-aware optimisation is new. The narrower question is whether a **decision-impact-based trigger for re-evaluating pending jobs** can improve the balance among emissions, job performance, and scheduling overhead compared with periodic, static, error-triggered, or savings-triggered approaches.

This is a proposed gap, not a proven novelty claim. A focused literature review must establish the closest prior work, especially work that considers changing rankings among feasible placement options, forecast uncertainty, re-planning overhead, and placement churn.

### 20.6 References cited in the report and subsequent planning

1. A. Radovanović et al., “Carbon-Aware Computing for Datacenters,” *IEEE Transactions on Power Systems*, 38(2), 1270–1280, 2023. DOI: <https://doi.org/10.1109/TPWRS.2022.3173250>.
2. S. Hall, F. Micheli, G. Belgioioso, A. Radovanović, and F. Dörfler, “Carbon-Aware Computing for Data Centers with Probabilistic Performance Guarantees,” *IEEE Transactions on Power Systems*, 2025. DOI as listed in the report: <https://doi.org/10.1109/TPWRS.2025.3630499>.
3. A. Li, S. Liu, and Y. Ding, “Uncertainty-Aware Decarbonization for Datacenters,” HotCarbon ’24, 2024. <https://hotcarbon.org/assets/2024/pdf/hotcarbon24-final84.pdf>.
4. T. Sukprasert, A. Souza, N. Bashir, D. Irwin, and P. Shenoy, “On the Limitations of Carbon-Aware Temporal and Spatial Workload Shifting in the Cloud,” EuroSys ’24, 2024. DOI: <https://doi.org/10.1145/3627703.3650079>.
5. W. A. Hanafy et al., “Untangling the Carbon-Cost Tradeoffs and Stampede Effect Challenges in Cloud Computing,” *IEEE Transactions on Computers*, 2026, as listed in the report. DOI: <https://doi.org/10.1109/TC.2026.3667610>.
6. D. Chen and Z. Zong, “CATS: A Carbon-Aware Task Simulator for Reducing AI Data Center Emissions,” arXiv:2609.14775, 2026, as listed in the report. <https://arxiv.org/abs/2609.14775>.
7. Alibaba Group, “Alibaba Cluster Data.” <https://github.com/alibaba/clusterdata>.
8. National Energy System Operator, “Regional Carbon Intensity Forecast.” <https://www.neso.energy/data-portal/regional-carbon-intensity-forecast>.
9. National Energy System Operator, “Historic Generation Mix.” <https://www.neso.energy/data-portal/historic-generation-mix>.
10. United Nations, “Goal 9: Industry, Innovation and Infrastructure.” <https://sdgs.un.org/goals/goal9>.
11. Michael L. Pinedo, _Scheduling: Theory, Algorithms, and Systems_, 6th ed., Springer, 2022. <https://doi.org/10.1007/978-3-031-05921-6>.
12. Central Electricity Authority (India), “CO2 Baseline Database for the Indian Power Sector.” <https://cea.nic.in/> (replaces the UK DESNZ 2026 conversion factors cited before PRD v0.5).
13. Electricity Maps, “Methodology.” <https://www.electricitymaps.com/data/methodology>.
14. GHG Protocol, _Scope 2 Guidance_. <https://ghgprotocol.org/scope-2-guidance>.

Bibliographic metadata, versions, and claims from these works should be checked against the original sources before final submission.

---

## 21. Risks, assumptions, and threats to validity

### 21.1 Scope creep

Trying to make decision-flip triggering, global capacity allocation, local scheduling, and full DRO optimisation all major contributions can make the project too broad. Keep one central research question and modular extensions.

### 21.2 Dataset mismatch

Workload data and carbon-intensity data come from different systems and geographic contexts. The mapping to virtual datacentres is an experimental abstraction, not a claim about actual physical co-location.

### 21.3 Missing fields

If the chosen trace has no job-level energy or deadlines, the resulting values are assumptions. The study must show sensitivity to them, not hide them.

### 21.4 Energy-model uncertainty

Power assumptions can dominate emission estimates. Report the model, its source/assumptions, and low/base/high sensitivity results. Compare policies under identical energy models.

### 21.5 Forecast leakage

A scheduler that sees future realised carbon intensity or actual runtime is unrealistic. The system must test information access explicitly, and the oracle should be the only policy allowed to use future information by design.

### 21.6 Poorly calibrated intervals

Overly wide intervals can cause too many triggers; too-narrow intervals can hide meaningful changes. Report empirical coverage and width, and assess calibration by forecast horizon/region where data allow.

### 21.7 Arbitrary weights and thresholds

Choosing thresholds after seeing test results can create a misleading advantage. Define a validation/tuning process and a held-out evaluation period. Report performance across a range of thresholds.

### 21.8 Work completed versus emissions

A policy might appear to emit less simply because it completes fewer jobs. Report total and per-completed-job emissions alongside deadline misses, queue delay, throughput, and unfinished jobs.

### 21.9 Novelty overlap

The proposed trigger may overlap with existing policies or papers. The literature review must establish the closest competing mechanisms and state the contribution narrowly.

### 21.10 Generalisability

A result from one trace, one region mapping, one power model, or one seed may not generalise. Add further traces/scenarios if feasible and state limits clearly.

---

## 22. Decisions that remain open

The following choices are not fully settled and should be recorded in configuration files and team notes before they affect final experiments.

Ticked items were decided in the PRD (decision IDs in brackets); unticked items are still open (PRD §17.3).

- [ ] Confirm the exact emissions table intended by the principal (O1; the CEA CO2 Baseline Database is the working answer).
- [ ] Confirm that Pinedo's sixth edition is the book the principal meant (O2).
- [x] Choose the primary Alibaba trace release: v2020 (D5).
- [x] Simulated world: India only, with Indian truth from generation by fuel × CEA factors and forecasts from real NESO error paths (D17–D20). Indian generation data source still to be confirmed (B4); archive coverage still to be checked (B2).
- [x] Map virtual datacentres to carbon profiles: Delhi NCR (Northern), Mumbai (Western), Chennai (Southern).
- [ ] Choose the base power values (B3; partly sourced). PUE is fixed at 1.0, IT energy only.
- [x] Deadlines: synthetic, derived only from the frozen runtime estimate (D15).
- [x] Objective, hard constraints, tie-breaking and candidate windows (PRD §9).
- [x] Decision-flip criterion: lower-bound screen plus a noise-adjusted gate using interval widths (PRD §10). Monte Carlo flip probability is extension X8.
- [x] Overhead is reported as wall-clock time and call counts, not converted to carbon (D13).
- [x] Baseline policies fixed (PRD §11).
- [x] Chronological calibration, validation and test splits (PRD §14.3).
- [ ] Confirm with the mentor that decision-flip is the core contribution and full Global–Local DRO is extension X1 (B1).
- [x] Deployment track: local split, then Docker, then AWS, with results identical to the in-process run (PRD v0.4, §13.5).
- [ ] AWS account and spending limit for the AWS stage (O8).
- [ ] Update the submitted report's methodology after implementation choices are finalised.

---

## 23. What the finished project should deliver

A credible completed project should include:

1. A documented, tested discrete-event simulator for pending workload placement across virtual datacentres.
2. A trace adapter and data manifest for the chosen Alibaba release.
3. A carbon data adapter and explicit record of forecast-vintage availability and limitations.
4. A transparent energy/emissions method with units, factors, assumptions, and sensitivity settings.
5. A tested implementation of the decision-flip trigger.
6. Precisely defined baseline policies.
7. Reproducible experiment configurations, seeds, and per-run outputs.
8. Tables and figures for modelled emissions, deadline performance, queue delay, workload completion, resource utilisation, optimisation calls, placement churn, and overhead.
9. Uncertainty-calibration results wherever the data support them.
10. Ablation and sensitivity experiments explaining when the trigger helps or fails.
11. A limitations section that clearly separates measured trace facts from simulated or synthetic assumptions.
12. A literature-supported description of the research gap, without overclaiming novelty.
13. An updated EL report that describes what was actually implemented—not merely what was originally proposed.
14. A static `dashboard.html` summarising the results.
15. A deployment demonstration: the same simulation with the datacentres as separate services, locally, in Docker and on AWS, with outputs identical to the in-process run and the network overhead reported.

---

## 24. Glossary

- **Carbon-aware scheduling:** scheduling that considers the carbon intensity of electricity when choosing where or when to execute work.
- **Carbon intensity:** emissions per unit of electricity, such as `gCO2/kWh`.
- **Discrete-event simulation:** a simulation in which time advances between events such as arrivals, starts, finishes, and forecast updates.
- **Decision flip:** a change, or a plausible change under uncertainty, in which candidate is considered best.
- **DRO:** Distributionally Robust Optimization; optimisation under uncertainty over a set of plausible probability distributions.
- **Emission factor/conversion factor:** a factor used to convert activity such as electricity consumption into estimated emissions, with a clearly defined unit and accounting boundary.
- **Forecast vintage:** the version of a forecast that was actually available at a particular issue time.
- **PUE:** Power Usage Effectiveness, a facility-to-IT energy ratio; its use depends on how the power model is defined.
- **Placement churn:** repeated changes to pending-job assignments.
- **Pending workload:** a submitted job that has not yet begun execution and may still be considered for reassignment in this project.
- **Virtual datacentre:** a configured simulation entity, not a claim that an actual facility exists in the mapped region.
- **Coordinator:** in the deployment track, the program that runs the event loop, simulated clock, policy and planner, and sends requests to the datacentre services.
- **Datacentre service:** in the deployment track, one virtual datacentre running as its own process or container, holding its queue and running jobs.
- **Simulated clock:** the simulation's own notion of time, advanced event by event. It is never the computer's wall clock, which is what keeps runs reproducible.
- **Docker / Docker Compose:** tools that package the program into an identical container image and start several containers together.
- **AWS (EC2, ECR):** Amazon's cloud. EC2 provides virtual machines; ECR stores container images.

---

## 25. Final guiding principle

Build the **smallest simulator that can test—and potentially disprove—the central hypothesis**. Start with sound event semantics, explicit constraints, a transparent energy model, and fair baselines. Then add uncertainty and the decision-flip trigger. Only after those pieces work should the team invest in sophisticated optimisation such as Global–Local DRO.

The research succeeds if the results clearly explain when selective re-evaluation is worthwhile, what it costs, where it fails, and which assumptions control the outcome. The goal is not to make the proposed method look superior; it is to measure its actual trade-offs rigorously.
