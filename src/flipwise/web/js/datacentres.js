// Datacentres: capacity, load over time, job lists and service health, one tab per datacentre.
import * as api from "./api.js";
import { esc, int, num, chart, colourOf, shortRegion, jobChips, keepLast, gClass, tsToMs, axisTime, REGION_COLOURS, REGION_SHORT } from "./util.js";

let root = null, tab = 0, policy = "decision_flip", shown = "", dcData = null, lanes = null;
export const title = ["Datacentres", "Capacity, load and jobs at each site"];

export function mount(view) {
  root = view; shown = "";
  view.innerHTML = `
  <div class="h2h-head"><div class="tabs" role="tablist" aria-label="Datacentre">${REGION_SHORT.map((n, i) => `<button type="button" role="tab" id="tab${i}" aria-selected="${i === tab}" data-i="${i}">${n}</button>`).join("")}</div>
    <div class="picker"><label for="dc-pol">Policy</label><select id="dc-pol"></select></div></div>
  <div class="fw-grid g3" id="gauges"></div>
  <div class="fw-grid g11 fw-section">
    <section class="fw-card"><h2>Running and queued jobs</h2><p class="sub">decision_flip, every half hour</p><div class="chart" id="ch-rq" role="img" aria-label="Running and queued over time"></div></section>
    <section class="fw-card"><h2>CO2 per half hour</h2><p class="sub">decision_flip, completed jobs placed here, kg</p><div class="chart" id="ch-co2" role="img" aria-label="CO2 per half hour"></div></section>
  </div>
  <div class="fw-grid g21 fw-section">
    <section class="fw-card"><h2>Jobs here</h2><p class="sub" id="jobs-sub"></p><div id="jobs"></div></section>
    <section class="fw-card"><h2>Service health</h2><p class="sub">Measured from the scheduler's calls</p><div id="health"></div></section>
  </div>`;
  view.querySelector(".tabs").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    tab = +b.dataset.i; dcData = null; lanes = null;
    root.querySelectorAll(".tabs button").forEach((x) => x.setAttribute("aria-selected", String(+x.dataset.i === tab)));
    load(window.__fwState).then(() => update(window.__fwState));
  });
  view.querySelector("#dc-pol").addEventListener("change", (e) => { policy = e.target.value; dcData = null; lanes = null; load(window.__fwState).then(() => update(window.__fwState)); });
}
export function unmount() { root = null; dcData = null; lanes = null; }

export async function load() {
  const [d, l] = await Promise.all([api.getDc(tab, policy), api.getLanes(policy)]);
  dcData = d; lanes = l;
}

function gauge(id, name, used, cap) {
  const pct = cap ? Math.round((used / cap) * 100) : 0;
  chart(id, root.querySelector("#" + id)).setOption({
    animation: false, series: [{ type: "gauge", min: 0, max: 100, radius: "92%", progress: { show: true, width: 12, itemStyle: { color: "#1D4ED8" } },
      axisLine: { lineStyle: { width: 12, color: [[1, "#E5E7EB"]] } }, pointer: { show: false }, axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false },
      detail: { formatter: `{v|${pct}%}\n{n|${num(used, 0)} of ${num(cap, 0)}}`, rich: { v: { fontSize: 22, fontWeight: 700, color: "#111827" }, n: { fontSize: 12, color: "#4B5563", padding: [4, 0, 0, 0] } }, offsetCenter: [0, "10%"] },
      data: [{ value: pct }] }] }, true);
}

export function update(s) {
  if (!root || !s || !s.status) return;
  window.__fwState = s;
  const sel = root.querySelector("#dc-pol"), names = s.status.policies;
  if (shown !== names.join(",")) { sel.innerHTML = names.map((p) => `<option value="${esc(p)}">${esc(p)}</option>`).join(""); shown = names.join(","); }
  sel.value = policy;
  const d = dcData;
  const g = d ? keepLast("g" + tab, d.carbon.actual_g_per_kwh ?? d.carbon.forecast_g_per_kwh) : null;
  if (!root.querySelector("#gauges").children.length)
    root.querySelector("#gauges").innerHTML = ["GPU", "CPU cores", "Memory (GB)"].map((n, i) => `<section class="fw-card"><h2>${n}</h2><p class="sub" id="gs${i}"></p><div style="height:170px" id="gg${i}" role="img" aria-label="${n} in use"></div></section>`).join("");
  if (d) {
    root.querySelector("#gs0").innerHTML = `${esc(shortRegion(d.name))} &middot; <span class="chip-g ${gClass(g)}">${num(g, 0)} g/kWh</span>`;
    root.querySelector("#gs1").textContent = "in use right now";
    root.querySelector("#gs2").textContent = "in use right now";
    gauge("gg0", "GPU", d.used.gpus, d.capacity.gpus); gauge("gg1", "CPU", d.used.cpus, d.capacity.cpus); gauge("gg2", "Mem", d.used.mem_gb, d.capacity.mem_gb);
  }
  const h = s.history.decision_flip || [], at = (p) => p.dcs[tab] || {};
  const base = { animation: false, tooltip: { trigger: "axis" }, grid: { left: 44, right: 16, top: 28, bottom: 28 }, xAxis: axisTime, legend: { top: 0, textStyle: { fontSize: 11, color: "#374151" } } };
  chart("dc-rq", root.querySelector("#ch-rq")).setOption({ ...base, yAxis: { type: "value", min: 0, axisLabel: { color: "#4B5563" }, splitLine: { lineStyle: { color: "#EEF0F3" } } },
    series: [{ name: "Running", type: "line", showSymbol: false, data: tsToMs(h, (p) => at(p).running), lineStyle: { color: "#047857" }, itemStyle: { color: "#047857" } },
      { name: "Queued", type: "line", showSymbol: false, data: tsToMs(h, (p) => at(p).queued), lineStyle: { color: "#B45309" }, itemStyle: { color: "#B45309" } }] }, true);
  const co2 = h.map((p, i) => [p.t * 1000, i ? Math.max(0, (at(p).kg_co2 || 0) - (at(h[i - 1]).kg_co2 || 0)) : 0]);
  chart("dc-co2", root.querySelector("#ch-co2")).setOption({ ...base, legend: { show: false }, yAxis: { type: "value", min: 0, name: "kg", axisLabel: { color: "#4B5563" }, splitLine: { lineStyle: { color: "#EEF0F3" } } },
    series: [{ type: "bar", data: co2, itemStyle: { color: REGION_COLOURS[tab] }, barMaxWidth: 10 }] }, true);
  const L = lanes && lanes.datacentres[tab];
  root.querySelector("#jobs-sub").textContent = `${policy}${d ? ` · ${int(d.completed)} completed here` : ""}. Squares show GPUs; black outline: your job; amber dot: moved.`;
  root.querySelector("#jobs").innerHTML = L ? `<div class="sbox"><div class="sl">Planned &middot; waiting for release (${int(L.planned.total)})</div><div class="jchips">${jobChips(L.planned, "planned")}</div></div>
    <div class="sbox"><div class="sl">Queue &middot; FIFO first-fit (${int(L.queued.total)})</div><div class="jchips">${jobChips(L.queued, "queued")}</div></div>
    <div class="sbox"><div class="sl">Running (${int(L.running.total)})</div><div class="jchips">${jobChips(L.running, "running")}</div></div>` : '<p class="fw-muted">Loading</p>';
  const hd = s.health && s.health.datacentres[tab];
  root.querySelector("#health").innerHTML = hd ? `<div class="svc"><div><b>${esc(REGION_SHORT[tab])} &middot; dc${tab}</b><div class="small fw-muted">${esc(hd.url)}</div></div><span class="chip-g ${s.connected === false ? "cg-red" : "cg-green"}">${hd.remote ? "service" : "in-process"}</span></div>
    <div class="dcrow"><span>Requests</span><b>${int(hd.requests)}</b></div><div class="dcrow"><span>Mean latency</span><b>${hd.mean_latency_ms == null ? "--" : hd.mean_latency_ms.toFixed(2) + " ms"}</b></div>
    <p class="small fw-muted" style="margin-top:8px">Health is measured for ${esc(s.health.policy)}, the policy whose calls are timed.</p>` : '<p class="fw-muted">No data</p>';
}
