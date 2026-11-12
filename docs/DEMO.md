# Demo guide

A step-by-step script for presenting Flipwise live, about 10 minutes, with the exact commands, what to click, what to point at and what to say. What every part of the dashboard shows is explained in [WEB_EXPLAINER.md](WEB_EXPLAINER.md).

**The story in one sentence:** *a carbon-aware scheduler has to decide when to re-check waiting jobs as forecasts change; decision-flip checks cheaply first and re-plans only when it can pay off, so it reaches the same carbon with about half the work.*

---

## 0. Before the demo (the day before, then 15 minutes before)

### The day before

Run these once on the presenting laptop. All commands run from the repository root; quote the path, it contains spaces.

| Step | Linux / Git Bash | Windows PowerShell |
|---|---|---|
| Go to the repo | `cd "~/Desktop/projects/5TH SEM EL/flipwise"` | `cd "C:\5TH SEM EL\flipwise"` |
| Install | `uv sync` | same |
| Check code | `uv run pytest -q` (expect 260 passed) | same |
| Check data | `uv run flipwise validate --config configs/base.yaml` (expect `validate: OK`) | same |
| Build the Docker image | `export GIT_COMMIT=$(git rev-parse HEAD)` then `docker compose --profile live build` | `$env:GIT_COMMIT = git rev-parse HEAD` then `docker compose --profile live build` |

Then rehearse the whole script below once.

### 15 minutes before

1. Close anything using ports **8100–8103** (an earlier demo, a test).
2. Start Docker (Docker Desktop on Windows) and wait until it is running.
3. Open a browser and a terminal, side by side; set the browser zoom to 90 % so a page fits the projector.
4. Open the slide with the architecture figure (`docs/figures/architecture_ppt.png`) as your opener.

---

## 1. Opening (1 minute, slide)

Show the architecture figure.

> "A GPU job's emissions depend on where and when it runs. Indian grids differ by region and by half hour. Our scheduler places each job using a carbon forecast, but forecasts change every 30 minutes, so the question is: **when is it worth re-checking a waiting job?** Re-checking everything is expensive; never re-checking misses savings. Our policy, decision-flip, answers that with a cheap check first."

Point at: three datacentres (Delhi, Mumbai, Chennai) → the scheduler in the middle → the three steps of decision-flip.

---

## 2. Act 1: the idea on six jobs (2 minutes)

**Terminal:**

```bash
uv run flipwise live --scenario tests/fixtures/toy --speed 120
```

**Browser:** http://localhost:8100. The clock reads *Mon 03 Jul 2023 05:30 IST*.

1. **Overview.** Point at the three datacentre cards and the carbon chart: *Delhi is cleanest right now (100), Chennai 200, Mumbai 300.*
   > "So every carbon-aware policy packs the first jobs into Delhi."
2. Click **+1 h** in the header. At 06:30 a new forecast says Delhi turns dirty (400).
3. **Decision feed** (Overview, bottom right): three **MOVE** rows appear.
   > "decision-flip moved three waiting jobs from Delhi to Chennai, each with its numbers: the saving, and what it needed to beat."
4. Click **+1 h** twice more so every job finishes. **Policy comparison table** (Overview): decision_flip ends at about **1.50 kg**, place_once (never re-plans) at about **2.31 kg**.
   > "Re-planning at the right moment matters: the plan made on the old forecast was worse than no carbon awareness at all."

Stop the server with **Ctrl-C**.

---

## 3. Act 2: a real week, real services (2 minutes)

**Terminal (one command: the scheduler starts the three datacentre services itself):**

```bash
uv run flipwise live --config configs/base.yaml --services local
```

It prints four URLs: the scheduler at **http://localhost:8100** and one page per datacentre, **http://localhost:8101** (Delhi NCR), **:8102** (Mumbai), **:8103** (Chennai). Open all four side by side. Ctrl-C stops everything.

*Or in Docker (three datacentres as separate containers; the same four URLs):*

```bash
docker compose --profile live up --build dc-delhi dc-mumbai dc-chennai live
```

Wait for the `live` container to print its line (10–20 s while it builds the week), then reload **http://localhost:8100**.

*Without separate services, in one process:* `uv run flipwise live --config configs/base.yaml`

1. Header pill reads **Live**; the clock starts on *Mon 03 Jul 2023 00:00 IST*.
   > "This is one real week of Alibaba's GPU jobs, about 7,000, on Indian grid data for July 2023."
2. **Architecture** page: three boxes, each with its URL (`http://dc-delhi:8101`…), request count and latency rising.
   > "The scheduler and the three datacentres are separate services talking over HTTP. We proved the results are byte-identical to running everything in one program."
3. Submit a job on the scheduler's **Job tracker** and watch the datacentre pages: when a job is placed or moved, an `enqueue` (blue) message appears in the message log of the site it goes to, and a `remove` (amber) at the site it leaves. Each site then shows its own FIFO queue start the job (`dispatch`, green) and later `complete` (grey).
   > "Each datacentre is its own program with its own queue. It only knows what the scheduler sends it."
4. Optional, in a second terminal (Docker), to show the containers really exist:

   ```bash
   docker compose ps
   docker compose logs --tail 5 dc-mumbai
   ```

5. Back to **Overview**: click **+6 h**. A spinner shows while it replays six hours of history (20–30 s).
   > "The time skip replays the recorded history as fast as the computer can."

---

## 4. Act 3: submit a job and follow it (2 minutes)

1. Open **Job tracker**. Fill in: **GPUs 4, GPU type V100, CPU cores 24, memory 60, runtime 3 h, deadline 20 h**. Click **Submit job**.
   > "This job goes to every policy at the same simulated moment."
2. Each policy's lane shows a **PLACE** chip. Click **+6 h** in the header.
3. Lanes fill: decision-flip shows **KEEP** chips; fixed_savings may show **MOVE** chips.
4. Click a decision-flip **KEEP** chip. The detail card shows the current plan, the best alternative, the saving and what was needed.
   > "The best alternative would save 0.085 kg, less than the 5 % gate plus the forecast-noise margin. A saving that small could be a forecast error, so the job keeps its plan and its queue place. fixed_savings moved for gains like that."

(Exact numbers depend on when you submit; the pattern is what matters.)

---

## 5. Act 4: head-to-head, the core result (2 minutes)

1. Open **Head-to-head**. The picker reads *fixed_savings*.
2. Point at the summary strip:
   > "decision-flip skipped about 70 % of its checks with the cheap screen and ran far fewer full re-scores and moves, for about the same carbon."
3. Point at the two **activity charts** (same scale): decision-flip's bars are mostly **grey** (avoided by the screen); fixed_savings' bars are **pink** (every job re-scored) with **amber** moves.
   > "Every grey block is work we did not have to do."
4. Point at the datacentre panels in each lane: planned, queued and running jobs as chips; amber dots mark jobs that were moved.
5. Optionally switch the picker to **periodic** or **pred_error**.

---

## 6. Act 5: the evidence (1.5 minutes)

1. **Test results** page.
   > "These are the numbers from 16 held-out test weeks, run once with thresholds frozen beforehand. CO₂ is a cited range: measured GPU use to datasheet power. All re-planning policies land within each other's confidence intervals; decision-flip needs 54 % fewer full re-scores and 60 % fewer moves than re-checking everything."
2. **Scale projection** page: move the slider to **1,000,000 jobs**.
   > "Per job, that is about 2.6 fewer re-scores; at a million jobs, about 2.6 million re-scores and 390,000 moves avoided."

---

## 7. Close (30 seconds)

> "In short: same carbon as re-checking everything, half the re-planning work, and with the noise margin at zero it provably makes the same decisions. In Phase 3 we scale the tests up to the full trace and add a learned runtime model, because most deadline misses come from jobs that run longer than expected."

Stop: **Ctrl-C** in the Docker terminal, then

```bash
docker compose --profile live down
```

---

## If something goes wrong

| Problem | Fix |
|---|---|
| Browser says the page cannot be reached | The server is not running or still starting; wait for its start line, or start it again |
| Header pill says **Disconnected** | The server stopped; restart the command. If port 8100 is taken, add `--port 8200` and open that port |
| Docker build or start fails | Use the in-process version: `uv run flipwise live --config configs/base.yaml` (same dashboard; the Architecture page then shows "in-process") |
| A skip is slow | It is replaying history; wait. On the toy, skips are instant |
| Numbers differ from this script | They depend on the moment you submit or skip; the pattern (screen skips most checks, fewer moves) holds |
| Need a fresh start | Stop with Ctrl-C and start the same command again; every session starts from the same week |

---

## Likely questions, short answers

| Question | Answer |
|---|---|
| Is this running real jobs? | No. It replays a real job log and real grid data in a simulator, so every policy faces exactly the same conditions. |
| Why not just re-check everything? | It gives the same carbon here but needs about twice the work and moves jobs 2.5× as often, and each move costs the job its queue place. |
| Is it machine learning? | No, the decisions are rules, which is why we can prove the θ = 0 equivalence and explain every decision. ML is planned for the inputs (runtime prediction) in Phase 3. |
| Where do deadlines come from? | Real users would give them; the trace has none, so each job gets one at arrival from a fixed rule (4 h + 2 × its cautious runtime estimate). In the demo you type your own. |
| Why British forecast errors? | No archive of Indian carbon forecasts exists; we borrow the real error patterns of Britain's grid operator, scaled to Indian levels. |
| How much carbon does it save? | About the same as the other re-planning policies; clearly less than ignoring carbon. Even perfect foresight saves at most about 1–2 % here. The gain is the work saved. |
