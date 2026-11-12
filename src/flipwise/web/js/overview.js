import { keepLast, esc, num, int, badge, decisionText, colourOf, chart, shortRegion, timeOnly, istClock, REGION_COLOURS, REGION_SHORT } from "./util.js";

const MAIN = "decision_flip", REF = "fixed_savings";
let root = null;

export const title = ["Overview", "Three datacentres, one scheduler, several re-planning policies running side by side"];

export function mount(view) {
  root = view;
  view.innerHTML = `
  <div class="fw-grid g5" id="kpis"></div>
  <div class="fw-grid g21 fw-section">
    <section class="fw-card"><h2>Grid carbon intensity</h2>
      <p class="sub">Forecast ahead (dashed) and actual so far (solid), gCO2/kWh</p>
      <div class="rlegend">${REGION_SHORT.map((n, i) => `<span><i class="sw" style="background:${REGION_COLOURS[i]}"></i>${n}</span>`).join("")}</div>
      <div class="chart" id="ch-carbon" role="img" aria-label="Grid carbon intensity chart"></div></section>
    <section class="fw-card"><h2>Services</h2><p class="sub">Scheduler and datacentres talk over HTTP</p>
      <div id="services"></div><h2 style="font-size:13px;margin-top:8px">Latest messages</h2><div class="msgs mono" id="msgs"></div></section>
  </div>
  <div class="fw-grid g3 fw-section" id="dcs"></div>
  <div class="fw-grid g21 fw-section">
    <section class="fw-card"><h2>Policy comparison, live</h2>
      <p class="sub">Same jobs, same carbon, same clock. Only the re-planning rule differs.</p>
      <div class="tw" id="cmp"></div></section>
    <section class="fw-card"><h2>Decision feed &middot; decision_flip</h2>
      <p class="sub">Every check the algorithm makes, newest first</p><div class="feed" id="feed"></div></section>
  </div>`;
}
export function unmount() { root = null; }

const pct = (a, b, word) => {
  if (a == null || !b) return "";
  const p = ((a - b) / b) * 100;
  return `${Math.abs(p).toFixed(0)}% ${p <= 0 ? "less" : "more"} ${word} than ${REF}`;
};
const series = (h, f) => (h || []).map((p) => [p.t, f(p)]);
const shareOf = (p) => (p.screen_skips + p.full_rescores ? p.screen_skips / (p.screen_skips + p.full_rescores) : 0);

function spark(id, el, data) {
  const c = chart(id, el);
  c.setOption({ animation: false, grid: { left: 0, right: 0, top: 2, bottom: 2 }, xAxis: { type: "value", show: false, min: "dataMin", max: "dataMax" },
    yAxis: { type: "value", show: false, min: "dataMin", max: "dataMax" },
    series: [{ type: "line", data, showSymbol: false, smooth: true, lineStyle: { width: 2, color: "#1D4ED8" }, areaStyle: { color: "rgba(29,78,216,.10)" } }] });
}

function kpis(st, hist) {
  const m = st.compare[MAIN], f = st.compare[REF], h = hist[MAIN] || [];
  if (!m) return;
  const stop = m.screen_skips + m.full_rescores ? m.screen_skips / (m.screen_skips + m.full_rescores) : null;
  const tiles = [
    { id: "co2", label: "CO2 so far", value: `${num(m.kg_co2_so_far, 2)} kg`, delta: f ? pct(m.kg_co2_so_far, f.kg_co2_so_far, "") .replace("  ", " ") : "", note: "decision_flip, completed jobs", f: (p) => p.kg_co2 },
    { id: "resc", label: "Full re-scores", value: int(m.full_rescores), delta: f ? pct(m.full_rescores, f.full_rescores, "work") : "", note: "expensive checks run", f: (p) => p.full_rescores },
    { id: "mv", label: "Jobs moved", value: int(m.moves), delta: f ? pct(m.moves, f.moves, "churn") : "", note: "plan changes accepted", f: (p) => p.moves },
    { id: "scr", label: "Checks stopped by screen", value: stop == null ? "--" : `${(stop * 100).toFixed(0)}%`, delta: "", note: `${int(m.screen_skips)} of ${int(m.screen_skips + m.full_rescores)} checks`, f: shareOf },
    { id: "done", label: "Jobs completed", value: int(m.jobs_completed), delta: "", note: `${int(m.deadline_misses)} deadline misses, ${int(m.jobs_arrived)} arrived`, f: (p) => p.jobs_completed },
  ];
  const host = root.querySelector("#kpis");
  if (!host.children.length) host.innerHTML = tiles.map((t) => `<section class="fw-card kpi"><div class="lab">${t.label}</div><div class="val" data-v="${t.id}"></div><div class="delta" data-d="${t.id}"></div><div class="note" data-n="${t.id}"></div><div class="spark" id="sp-${t.id}"></div></section>`).join("");
  for (const t of tiles) {
    host.querySelector(`[data-v="${t.id}"]`).textContent = t.value;
    host.querySelector(`[data-d="${t.id}"]`).textContent = t.delta;
    host.querySelector(`[data-n="${t.id}"]`).textContent = t.note;
    spark(`sp-${t.id}`, host.querySelector(`#sp-${t.id}`), series(h, t.f));
  }
}

function carbon(st, hist) {
  const h = hist[MAIN] || [];
  const nowS = st.clock.sim_time_s, slot0 = Math.floor(nowS / 1800) * 1800;
  const sers = [];
  st.carbon.forEach((c, i) => {
    const col = REGION_COLOURS[i % 3];
    sers.push({ name: REGION_SHORT[i] + " actual", type: "line", showSymbol: false, lineStyle: { color: col, width: 2 }, itemStyle: { color: col },
      data: h.map((p) => [p.t, p.dcs[i] ? p.dcs[i].actual_g_per_kwh : null]),
      markLine: i === 0 ? { symbol: "none", silent: true, lineStyle: { color: "#111827", type: "dashed" }, label: { formatter: "now", color: "#111827" }, data: [{ xAxis: nowS }] } : undefined });
    sers.push({ name: REGION_SHORT[i] + " forecast", type: "line", showSymbol: false, lineStyle: { color: col, width: 2, type: "dashed" }, itemStyle: { color: col },
      data: (c.forecast_next_6h || []).map((v, k) => [slot0 + k * 1800, v]) });
  });
  chart("carbon", root.querySelector("#ch-carbon")).setOption({
    animation: false, tooltip: { trigger: "axis", valueFormatter: (v) => (v == null ? "--" : Number(v).toFixed(0) + " g/kWh"), axisPointer: { type: "line" } },
    grid: { left: 44, right: 16, top: 30, bottom: 28 }, legend: { show: false },
    xAxis: { type: "value", min: "dataMin", max: "dataMax", axisLabel: { formatter: (v) => istClock(v), color: "#4B5563" } },
    yAxis: { type: "value", name: "g/kWh", scale: true, axisLabel: { color: "#4B5563" }, splitLine: { lineStyle: { color: "#EEF0F3" } } },
    series: sers }, true);
}

function services(health, st) {
  const host = root.querySelector("#services");
  const rows = (health ? health.datacentres : []).map((d) => `<div class="svc"><div><b>Datacentre ${d.dc_id} &middot; ${REGION_SHORT[d.dc_id] || ""}</b><div class="small fw-muted">${esc(d.url)}</div></div>
    <div class="small" style="text-align:right">${int(d.requests)} requests<br>${d.mean_latency_ms == null ? "--" : d.mean_latency_ms.toFixed(2)} ms mean</div></div>`).join("");
  host.innerHTML = `<div class="svc"><div><b>Scheduler &middot; ${esc(MAIN)}</b><div class="small fw-muted">owns the simulated clock</div></div><div class="small">${esc(st.remote_policy ? "calls services" : "in-process")}</div></div>${rows}`;
  root.querySelector("#msgs").innerHTML = st.recent_messages.slice().reverse().slice(0, 20).map((m) =>
    `<div>${esc(timeOnly(m.t))} dc${esc(m.dc_id)} ${esc(m.op)} ${esc(m.job_id || m.detail || "")}</div>`).join("") || "<div>No messages yet</div>";
}

function dcCards(dcs) {
  const host = root.querySelector("#dcs");
  host.innerHTML = dcs.map((d, i) => {
    if (!d) return `<section class="fw-card"><h2>${REGION_SHORT[i]}</h2><p class="sub">Loading</p></section>`;
    const g = keepLast("g" + i, d.carbon.actual_g_per_kwh ?? d.carbon.forecast_g_per_kwh);
    const cls = g == null ? "" : g < 600 ? "cg-green" : g < 800 ? "cg-amber" : "cg-red";
    const u = Math.round((d.gpu_utilisation || 0) * 100);
    return `<section class="fw-card"><div style="display:flex;justify-content:space-between;align-items:start"><div><h2 style="color:${REGION_COLOURS[i]}">${esc(shortRegion(d.name))}</h2>
      <p class="sub" style="margin-bottom:8px">${esc(d.name.replace(/.*\((.*)\)/, "$1"))} &middot; dc${d.dc_id}${d.remote ? " &middot; service" : ""}</p></div>
      <span class="chip-g ${cls}">${num(g, 0)} g/kWh</span></div>
      <div class="dcrow"><span>GPU load</span><b>${num(d.used.gpus, 1)} / ${num(d.capacity.gpus, 0)} (${u}%)</b></div>
      <div class="bar" role="progressbar" aria-valuenow="${u}" aria-valuemin="0" aria-valuemax="100" aria-label="GPU load"><i style="width:${u}%"></i></div>
      <div class="dcrow"><span>Running</span><b>${d.running}</b></div><div class="dcrow"><span>Queued</span><b>${d.queue_length}</b></div>
      <div class="dcrow"><span>CO2 so far</span><b>${num(d.kg_co2_so_far, 2)} kg</b></div></section>`;
  }).join("");
}

function compare(st) {
  const names = Object.keys(st.compare);
  const ref = st.compare[REF] ? st.compare[REF].full_rescores : Math.max(1, ...names.map((n) => st.compare[n].full_rescores));
  const label = st.compare[REF] ? REF : "the maximum";
  root.querySelector("#cmp").innerHTML = `<table class="fw-t"><thead><tr><th>Policy</th><th>CO2 so far</th><th>Full re-scores</th><th>Moves</th><th>Work vs ${label}</th></tr></thead><tbody>` +
    names.map((n) => { const c = st.compare[n], w = ref ? c.full_rescores / ref : 0;
      return `<tr class="${n === MAIN ? "hl" : ""}"><td><i class="pdot" style="background:${colourOf(n)}"></i>${esc(n)}</td><td>${num(c.kg_co2_so_far, 2)} kg</td><td>${int(c.full_rescores)}</td><td>${int(c.moves)}</td>
      <td><i class="wbar" style="width:${Math.min(120, w * 100)}px;background:${colourOf(n)}"></i> ${(w * 100).toFixed(0)}%</td></tr>`; }).join("") + "</tbody></table>";
}

function feed(st) {
  const ds = (st.recent_decisions[MAIN] || []).slice().reverse();
  root.querySelector("#feed").innerHTML = ds.map((d) => `<div class="frow"><span class="t mono">${esc(timeOnly(d.time))}</span>${badge(d.kind)}<span>${esc(decisionText(d))}</span></div>`).join("") || '<p class="fw-muted">No decisions yet</p>';
}

export function update(s) {
  if (!root || !s.status) return;
  const st = s.status;
  kpis(st, s.history); carbon(st, s.history); services(s.health, st); dcCards(s.dcs); compare(st); feed(st);
}
