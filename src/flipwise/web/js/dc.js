// One datacentre's own dashboard. Reads this service's /live; carbon comes from the scheduler.
import { esc, int, num, chart, REGION_COLOURS, axisTime, tsToMs, gClass, gpuLabel } from "./util.js";

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const SCHEDULER = (params.get("scheduler") || `${location.protocol}//${location.hostname}:8100`).replace(/\/$/, "");
const POLL_MS = 1000, SCHED_MS = 3000, HIST_KEEP = 2000;
let lastKey = "", dcId = null, lastSched = 0, sched = null, schedErr = false, schedBusy = false;
// The service's history, kept here: each poll asks only for samples newer than the last one held.
let hist = [], histRun = null;

$("dc-back").href = SCHEDULER + "/";

function pill(kind, text) {
  $("dc-conn").className = "fw-pill " + kind;
  $("dc-conn-text").textContent = text;
}

function kpis(d) {
  const c = d.counters, u = d.utilisation;
  const tile = (lab, val, note) => `<section class="fw-card kpi"><div class="lab">${lab}</div><div class="val">${val}</div><div class="note">${note}</div></section>`;
  $("dc-kpis").innerHTML =
    tile("GPU utilisation", `${num(u.gpu * 100, 0)}%`, `${num(d.used.gpu, 0)} of ${num(d.capacity.gpu, 0)} GPUs`) +
    tile("Running jobs", int(d.running.length), "started here, not yet finished") +
    tile("Queued jobs", int(d.queue_len), "waiting for resources") +
    tile("Jobs completed here", int(c.complete), `${int(c.started)} started`) +
    tile("Messages received", int(c.requests), `${int(c.enqueue)} enqueue, ${int(c.dispatch)} dispatch`);
}

function gauge(id, frac, colour, text) {
  $(id + "-sub").textContent = text;
  chart(id, $(id)).setOption({
    animation: false,
    series: [{
      type: "gauge", min: 0, max: 100, startAngle: 200, endAngle: -20, radius: "95%", center: ["50%", "62%"],
      progress: { show: true, width: 14, itemStyle: { color: colour } },
      axisLine: { lineStyle: { width: 14, color: [[1, "#E5E7EB"]] } },
      axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false }, pointer: { show: false },
      detail: { valueAnimation: false, formatter: "{value}%", fontSize: 24, fontWeight: 700, color: "#111827", offsetCenter: [0, "10%"] },
      data: [{ value: Math.round(frac * 100) }],
    }],
  });
}

const chipHtml = (j, cls, extra) => `<span class="jc ${cls}" title="${esc(j.job_id)} - ${num(j.gpu, 1)} GPU, ${num(j.cpu, 0)} CPU, ${num(j.mem_gb, 0)} GB${extra || ""}">${gpuLabel(j.gpu)}</span>`;

function panel(d) {
  const q = d.queue.slice(0, 60);
  $("q-count").textContent = `(${d.queue_len})`;
  $("q-chips").innerHTML = q.length
    ? q.map((j) => chipHtml(j, "jc-queued")).join("") + (d.queue_len > q.length ? `<span class="jc jc-more">+${d.queue_len - q.length}</span>` : "")
    : '<span class="fw-muted small">Queue is empty</span>';
  const r = d.running.slice(0, 80);
  $("r-count").textContent = `(${d.running.length})`;
  $("r-chips").innerHTML = r.length
    ? r.map((j) => chipHtml(j, "jc-running", `, started ${new Date((j.start_s + 19800) * 1000).toISOString().slice(5, 16).replace("T", " ")} IST`)).join("") + (d.running.length > r.length ? `<span class="jc jc-more">+${d.running.length - r.length}</span>` : "")
    : '<span class="fw-muted small">Nothing running</span>';
  const last = d.starts.slice(-8).reverse();
  $("dc-decisions").innerHTML = last.length
    ? last.map((s) => `<li><span class="fw-muted small">${esc(s.time)}</span><br>started <b>${esc(s.job_id)}</b>: fits ${s.gpu == null ? "its" : gpuLabel(s.gpu)} GPU${s.gpu === 1 ? "" : "s"}</li>`).join("")
    : '<li class="fw-muted">No job started yet</li>';
}

function charts(d) {
  const h = hist, cap = d.capacity.gpu;
  chart("ch-gpu", $("ch-gpu")).setOption({
    animation: false, grid: { left: 44, right: 16, top: 30, bottom: 28 }, tooltip: { trigger: "axis" },
    legend: { top: 0, textStyle: { color: "#4B5563" } }, xAxis: axisTime, yAxis: { type: "value", min: 0, max: Math.ceil(cap * 1.05), axisLabel: { color: "#4B5563" } },
    series: [
      { name: "GPUs in use", type: "line", step: "end", showSymbol: false, areaStyle: { opacity: 0.12 }, lineStyle: { width: 2 }, itemStyle: { color: REGION_COLOURS[d.dc_id] || "#1D4ED8" }, data: tsToMs(h, (p) => p.gpu) },
      { name: "Capacity", type: "line", showSymbol: false, lineStyle: { width: 1.5, type: "dashed" }, itemStyle: { color: "#4B5563" }, data: tsToMs(h, () => cap) },
    ],
  });
  chart("ch-q", $("ch-q")).setOption({
    animation: false, grid: { left: 44, right: 16, top: 30, bottom: 28 }, tooltip: { trigger: "axis" },
    legend: { top: 0, textStyle: { color: "#4B5563" } }, xAxis: axisTime, yAxis: { type: "value", minInterval: 1, axisLabel: { color: "#4B5563" } },
    series: [
      { name: "Queued", type: "line", step: "end", showSymbol: false, lineStyle: { width: 2 }, itemStyle: { color: "#B45309" }, data: tsToMs(h, (p) => p.queue) },
      { name: "Running", type: "line", step: "end", showSymbol: false, lineStyle: { width: 2 }, itemStyle: { color: "#15803D" }, data: tsToMs(h, (p) => p.running) },
    ],
  });
}

function logRows(d) {
  const details = (e) => {
    if (e.op === "enqueue") return `asks ${num(e.gpu, 1)} GPU, ${num(e.cpu, 0)} CPU, ${num(e.mem_gb, 0)} GB; ${esc(e.outcome)}`;
    if (e.op === "dispatch" && e.started && e.started.length) return `${esc(e.outcome)}: ${e.started.map((s) => esc(s.job_id)).join(", ")}`;
    return esc(e.outcome || "");
  };
  $("dc-log").innerHTML = d.log.slice().reverse().map((e) =>
    `<tr><td class="mono">${esc(e.time)}</td><td><span class="badge-k op-${esc(e.op)}">${esc(e.op)}</span></td><td class="mono">${esc(e.job_id || "")}</td><td>${details(e)}</td></tr>`).join("");
}

function carbon() {
  const box = $("carbon-body");
  if (schedErr || !sched) { box.className = "fw-muted"; box.textContent = sched === false ? "This site is not in the scheduler's scenario" : "Scheduler not reachable"; return; }
  const c = sched.carbon, policy = sched.policy, kg = sched.kg_co2_so_far;
  const next = (c.forecast_next_6h || []).slice(0, 12);
  const g = c.actual_g_per_kwh;
  box.className = "";
  box.innerHTML = `<div class="dc-cbox">
    <div class="dbox"><div class="l">Carbon now (actual)</div><div class="v"><span class="chip-g ${gClass(g)}">${num(g, 0)}</span> gCO2/kWh</div><div class="n">${esc(c.region || "")}</div></div>
    <div class="dbox"><div class="l">Forecast for this slot</div><div class="v">${num(c.forecast_g_per_kwh, 0)} gCO2/kWh</div><div class="n">what the scheduler believes</div></div>
    <div class="dbox"><div class="l">CO2 so far at this site</div><div class="v">${num(kg, 2)} kg</div><div class="n">completed jobs</div></div>
    <div class="dbox"><div class="l">Scheduler policy</div><div class="v">${esc(policy)}</div><div class="n">${esc(sched.remote ? "calls this service over HTTP" : "in-process")}</div></div></div>
    <div class="dc-lab">Forecast for the next 6 hours (gCO2/kWh, per half hour)</div>
    <div class="chips">${next.map((v, i) => `<span class="chip-g ${gClass(v)}" title="in ${i * 30} min">${num(v, 0)}</span>`).join("")}</div>`;
}

// /dc/<id> holds everything this page shows from the scheduler (carbon, policy, CO2 so far), so
// the much larger /status is not needed. One request at a time.
async function pollScheduler() {
  if (schedBusy) return;
  schedBusy = true; lastSched = Date.now();
  try {
    const r = await fetch(`${SCHEDULER}/dc/${dcId}`, { cache: "no-store" });
    if (r.status === 404) { sched = false; schedErr = false; }
    else if (!r.ok) throw new Error(String(r.status));
    else { sched = await r.json(); schedErr = false; }
  } catch (e) { schedErr = true; }
  finally { schedBusy = false; }
  carbon();
}

function render(d) {
  dcId = d.dc_id;
  document.title = `${d.name} datacentre - Flipwise`;
  $("dc-name").textContent = `${d.name} datacentre`;
  $("dc-sub").textContent = `${d.grid} · Datacentre service · port ${location.port || d.port}`;
  $("dc-root").style.setProperty("--accent", REGION_COLOURS[d.dc_id] || "#1D4ED8");
  if (d.state !== "ready" || d.t == null) {
    $("dc-waiting").hidden = false; $("dc-ready").hidden = true;
    $("dc-clock").textContent = "--";
    $("dc-waiting-text").textContent = d.state === "ready"
      ? "Configured, but no request has arrived yet. Start or unpause the scheduler."
      : "This service has no configuration yet. It receives its capacity from the scheduler's first request.";
    pill("", "Waiting for scheduler");
    return;
  }
  $("dc-waiting").hidden = true; $("dc-ready").hidden = false;
  $("dc-clock").textContent = d.time;
  pill("ok", "Live");
  const key = `${d.counters.requests}|${d.t}`;
  if (key === lastKey) return;
  lastKey = key;
  kpis(d); panel(d); charts(d); logRows(d);
  gauge("g-gpu", d.utilisation.gpu, REGION_COLOURS[d.dc_id], `${num(d.used.gpu, 0)} of ${num(d.capacity.gpu, 0)} GPUs`);
  gauge("g-cpu", d.utilisation.cpu, "#4B5563", `${int(d.used.cpu)} of ${int(d.capacity.cpu)} CPUs`);
  gauge("g-mem", d.utilisation.mem_gb, "#7C3AED", `${int(d.used.mem_gb)} of ${int(d.capacity.mem_gb)} GB`);
  if (sched === null && !schedErr) pollScheduler();
}

async function getLive(query) {
  const r = await fetch("/live" + query, { cache: "no-store" });
  if (!r.ok) throw new Error(String(r.status));
  return r.json();
}

// Polls ask only for history newer than the last sample held; after a reset (a new run) that
// answer belongs to the wrong run, so the whole history is fetched again.
async function fetchLive() {
  const since = hist.length ? hist[hist.length - 1].t : null;
  let d = await getLive(since == null ? "" : `?since=${since}`);
  if (since != null && d.run !== histRun) d = await getLive("");
  if (since == null || d.run !== histRun) { hist = d.history || []; histRun = d.run; }
  else if (d.history.length) { hist.push(...d.history); if (hist.length > HIST_KEEP) hist.splice(0, hist.length - HIST_KEEP); }
  return d;
}

async function tick() {
  if (document.hidden) return;
  try {
    render(await fetchLive());
    if (dcId !== null && Date.now() - lastSched > SCHED_MS) pollScheduler();
  } catch (e) {
    pill("bad", "Disconnected");
  }
}

function loop() { tick().finally(() => setTimeout(loop, POLL_MS)); }
document.addEventListener("visibilitychange", () => { if (!document.hidden) { lastKey = ""; tick(); } });
loop();
