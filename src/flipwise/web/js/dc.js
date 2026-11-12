// One datacentre's own dashboard. Reads this service's /live; carbon comes from the scheduler.
import { esc, int, num, chart, REGION_COLOURS, axisTime, tsToMs, gClass } from "./util.js";

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const SCHEDULER = (params.get("scheduler") || `${location.protocol}//${location.hostname}:8100`).replace(/\/$/, "");
const POLL_MS = 1000, SCHED_MS = 3000;
let lastKey = "", dcId = null, lastSched = 0, sched = null, schedErr = false;

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

function gauge(id, frac, colour, sub, text) {
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

const gpuLabel = (g) => (g == null ? "?" : g < 1 ? (String(+g.toFixed(2)).replace(/^0/, "") || "0") : String(Math.round(g)));
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
  const h = d.history, cap = d.capacity.gpu;
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
  if (schedErr || !sched) { box.className = "fw-muted"; box.textContent = "Scheduler not reachable"; return; }
  const st = sched.status, c = (st.carbon || []).find((x) => x.dc_id === dcId);
  if (!c) { box.textContent = "This site is not in the scheduler's scenario"; return; }
  const policy = (st.policies || [])[0] || "--";
  const kg = sched.dc ? sched.dc.kg_co2_so_far : null;
  const next = (c.forecast_next_6h || []).slice(0, 12);
  const g = c.actual_g_per_kwh;
  box.className = "";
  box.innerHTML = `<div class="dc-cbox">
    <div class="dbox"><div class="l">Carbon now (actual)</div><div class="v"><span class="chip-g ${gClass(g)}">${num(g, 0)}</span> gCO2/kWh</div><div class="n">${esc(c.region || "")}</div></div>
    <div class="dbox"><div class="l">Forecast for this slot</div><div class="v">${num(c.forecast_g_per_kwh, 0)} gCO2/kWh</div><div class="n">what the scheduler believes</div></div>
    <div class="dbox"><div class="l">CO2 so far at this site</div><div class="v">${num(kg, 2)} kg</div><div class="n">completed jobs</div></div>
    <div class="dbox"><div class="l">Scheduler policy</div><div class="v">${esc(policy)}</div><div class="n">${esc(st.remote_policy ? "calls this service over HTTP" : "in-process")}</div></div></div>
    <div class="dc-lab">Forecast for the next 6 hours (gCO2/kWh, per half hour)</div>
    <div class="chips">${next.map((v, i) => `<span class="chip-g ${gClass(v)}" title="in ${i * 30} min">${num(v, 0)}</span>`).join("")}</div>`;
}

async function pollScheduler() {
  lastSched = Date.now();
  try {
    const r = await fetch(SCHEDULER + "/status", { cache: "no-store" });
    if (!r.ok) throw new Error(String(r.status));
    const status = await r.json();
    let dc = null;
    try { const r2 = await fetch(`${SCHEDULER}/dc/${dcId}`, { cache: "no-store" }); if (r2.ok) dc = await r2.json(); } catch (e) { dc = null; }
    sched = { status, dc }; schedErr = false;
  } catch (e) { schedErr = true; }
  carbon();
}

function render(d) {
  dcId = d.dc_id;
  document.title = `${d.name} datacentre - Flipwise`;
  $("dc-name").textContent = `${d.name} datacentre`;
  $("dc-sub").textContent = `${d.grid} · Datacentre service · port ${d.port}`;
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
  gauge("g-gpu", d.utilisation.gpu, REGION_COLOURS[d.dc_id], "", `${num(d.used.gpu, 0)} of ${num(d.capacity.gpu, 0)} GPUs`);
  gauge("g-cpu", d.utilisation.cpu, "#4B5563", "", `${int(d.used.cpu)} of ${int(d.capacity.cpu)} CPUs`);
  gauge("g-mem", d.utilisation.mem_gb, "#7C3AED", "", `${int(d.used.mem_gb)} of ${int(d.capacity.mem_gb)} GB`);
  if (!sched && !schedErr) pollScheduler();
}

async function tick() {
  if (document.hidden) return;
  try {
    const r = await fetch("/live", { cache: "no-store" });
    if (!r.ok) throw new Error(String(r.status));
    render(await r.json());
    if (dcId !== null && Date.now() - lastSched > SCHED_MS) pollScheduler();
  } catch (e) {
    pill("bad", "Disconnected");
  }
}

function loop() { tick().finally(() => setTimeout(loop, POLL_MS)); }
document.addEventListener("visibilitychange", () => { if (!document.hidden) { lastKey = ""; tick(); } });
loop();
