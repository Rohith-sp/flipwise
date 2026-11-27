// Datacentres: one site at a time, one tab per site (any number of sites).
import * as api from "./api.js";
import { esc, int, num, chart, shortRegion, jobChips, keepLast, gClass, tsToMs, axisTime, siteColour, sitesOf, pairOf, dcLink, more, onMore, isOpen } from "./util.js";

let root = null, tab = 0, policy = null, dcData = null, lanes = null;
export const title = ["Datacentres", "Load, queue and grid carbon at one site at a time"];

export function mount(view) {
  root = view;
  view.innerHTML = `
  <div class="card-h"><div class="tabs" role="tablist" aria-label="Datacentre" id="tabs"></div>
    <div class="picker"><label for="dc-pol">Policy</label><select id="dc-pol"></select></div></div>
  <div class="fw-grid g5" id="kpis"></div>
  <section class="fw-card fw-section"><h2>Running and queued jobs</h2><p class="sub" id="rq-sub"></p>
    <div class="chart-lg" id="ch-rq" role="img" aria-label="Running and queued jobs over time"></div></section>
  ${more("d-more", "Show more: CO2 per half hour, the jobs here, service health", `<div class="fw-grid g11">
    <section class="fw-card"><h2>CO2 per half hour</h2><p class="sub">kg, completed jobs placed at this site</p><div class="chart" id="ch-co2" role="img" aria-label="CO2 per half hour"></div></section>
    <section class="fw-card"><h2>Service health</h2><p class="sub">Measured from the scheduler's calls</p><div id="health"></div></section></div>
    <section class="fw-card fw-section"><h2>Jobs here</h2><p class="sub" id="jobs-sub"></p><div id="jobs"></div></section>`)}`;
  view.querySelector("#tabs").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    tab = +b.dataset.i; dcData = null; lanes = null;
    load().then(() => update(window.__fwState), () => {});
  });
  view.querySelector("#dc-pol").addEventListener("change", (e) => { policy = e.target.value; dcData = null; lanes = null; load().then(() => update(window.__fwState), () => {}); });
  onMore(view, "d-more", () => load().then(() => update(window.__fwState), () => {}));
}
export function unmount() { root = null; dcData = null; lanes = null; }

export async function load() {
  if (!root || policy === null) return;
  const want = `${tab}|${policy}`;
  const [d, l] = await Promise.all([api.getDc(tab, policy), isOpen(root, "d-more") ? api.getLanes(policy) : null]);
  // A tab or policy switch while this was in flight: these answers are for the old choice.
  if (want === `${tab}|${policy}`) { dcData = d; if (l) lanes = l; }
}

function controls(s) {
  const st = s.status, list = sitesOf(st), names = st.policies;
  if (tab >= list.length) tab = 0;
  const tabs = root.querySelector("#tabs"), key = list.map((x) => x.short).join(",");
  if (tabs.dataset.k !== key) {
    tabs.innerHTML = list.map((x, i) => `<button type="button" role="tab" data-i="${i}" style="--sc:${siteColour(i)}">${esc(x.short)}</button>`).join("");
    tabs.dataset.k = key;
  }
  tabs.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", String(+b.dataset.i === tab)));
  const sel = root.querySelector("#dc-pol");
  if (policy === null || !names.includes(policy)) { policy = pairOf(s)[0]; dcData = null; }
  if (sel.dataset.names !== names.join(",")) { sel.innerHTML = names.map((p) => `<option value="${esc(p)}">${esc(p)}</option>`).join(""); sel.dataset.names = names.join(","); }
  sel.value = policy;
}

export function update(s) {
  if (!root || !s || !s.status) return;
  controls(s);
  const d = dcData, site = sitesOf(s.status)[tab] || {}, col = siteColour(tab);
  const g = d ? keepLast("g" + tab, d.carbon.actual_g_per_kwh ?? d.carbon.forecast_g_per_kwh) : null;
  const t = (lab, val, note) => `<section class="fw-card kpi" style="border-top:3px solid ${col}"><div class="lab">${lab}</div><div class="val">${val}</div><div class="note">${note}</div></section>`;
  root.querySelector("#kpis").innerHTML = d ?
    t("GPUs in use", `${Math.round((d.gpu_utilisation || 0) * 100)}<span class="u">%</span>`, `${num(d.used.gpus, 0)} of ${num(d.capacity.gpus, 0)} GPUs`) +
    t("Running jobs", int(d.running), `${int(d.completed)} completed here`) +
    t("Queued jobs", int(d.queue_length), `${int(d.planned_not_released)} planned for later`) +
    t("Grid carbon now", `<span class="chip-g big-chip ${gClass(g)}">${num(g, 0)}</span><span class="u"> g/kWh</span>`, esc(site.grid || shortRegion(d.name))) +
    t("CO2 so far", `${num(d.kg_co2_so_far, 1)}<span class="u"> kg</span>`, "completed jobs at this site") : "";
  root.querySelector("#rq-sub").textContent = `${site.short || "Site"} under ${policy}, sampled every simulated half hour`;
  const h = s.history[policy] || [], at = (p) => p.dcs[tab] || {};
  const base = { animation: false, tooltip: { trigger: "axis" }, grid: { left: 48, right: 20, top: 36, bottom: 30 }, xAxis: axisTime, legend: { top: 0, textStyle: { fontSize: 12, color: "#334155" } } };
  const yAx = { type: "value", min: 0, axisLabel: { color: "#64748B" }, splitLine: { lineStyle: { color: "#EEF2F6" } } };
  chart("dc-rq", root.querySelector("#ch-rq")).setOption({ ...base, yAxis: yAx,
    series: [{ name: "Running", type: "line", showSymbol: false, data: tsToMs(h, (p) => at(p).running), lineStyle: { color: col, width: 3 }, itemStyle: { color: col }, areaStyle: { color: col, opacity: 0.08 } },
      { name: "Queued", type: "line", showSymbol: false, data: tsToMs(h, (p) => at(p).queued), lineStyle: { color: "#94A3B8", width: 2, type: "dashed" }, itemStyle: { color: "#94A3B8" } }] }, true);
  if (!isOpen(root, "d-more")) return;
  const co2 = h.map((p, i) => [p.t * 1000, i ? Math.max(0, (at(p).kg_co2 || 0) - (at(h[i - 1]).kg_co2 || 0)) : 0]);
  chart("dc-co2", root.querySelector("#ch-co2")).setOption({ ...base, legend: { show: false }, yAxis: { ...yAx, name: "kg" },
    series: [{ type: "bar", data: co2, itemStyle: { color: col }, barMaxWidth: 10 }] }, true);
  const L = lanes && lanes.datacentres[tab];
  root.querySelector("#jobs-sub").textContent = `${policy}. Squares show GPUs; black outline: your job; amber dot: moved.`;
  root.querySelector("#jobs").innerHTML = L ? `<div class="fw-grid g3"><div class="sbox"><div class="sl">Planned, waiting for release (${int(L.planned.total)})</div><div class="jchips">${jobChips(L.planned, "planned")}</div></div>
    <div class="sbox"><div class="sl">Queue, FIFO first-fit (${int(L.queued.total)})</div><div class="jchips">${jobChips(L.queued, "queued")}</div></div>
    <div class="sbox"><div class="sl">Running (${int(L.running.total)})</div><div class="jchips">${jobChips(L.running, "running")}</div></div></div>` : '<p class="fw-muted">Loading</p>';
  const hd = s.health && s.health.datacentres[tab];
  root.querySelector("#health").innerHTML = hd ? `<div class="svc"><div><b>${esc(site.short || "")} &middot; dc${tab}</b><div class="small fw-muted">${esc(hd.url)}</div>${dcLink(hd)}</div><span class="chip-g ${s.connected === false ? "cg-red" : "cg-green"}">${hd.remote ? "service" : "in-process"}</span></div>
    <div class="dcrow"><span>Requests</span><b>${int(hd.requests)}</b></div><div class="dcrow"><span>Mean latency</span><b>${hd.mean_latency_ms == null ? "--" : hd.mean_latency_ms.toFixed(2) + " ms"}</b></div>
    <p class="small fw-muted" style="margin-top:8px">Measured for ${esc(s.health.policy)}, the policy whose calls are timed.</p>` : '<p class="fw-muted">No data</p>';
}
