// Scheduler: the forecasts it sees, every decision it makes, and how the work splits up.
import { esc, int, badge, decisionText, chart, timeOnly, istClock, REGION_COLOURS, REGION_SHORT } from "./util.js";

let root = null, policy = "decision_flip", kind = "ALL", shown = "";
export const title = ["Scheduler", "What the planner sees, and what it decides at each forecast update"];

export function mount(view) {
  root = view; shown = "";
  view.innerHTML = `
  <section class="fw-card"><h2>Carbon forecast by region</h2><p class="sub">Forecast for the next 6 hours (dashed) and actual so far (solid), gCO2/kWh. The scheduler sees only the forecast.</p>
    <div class="rlegend">${REGION_SHORT.map((n, i) => `<span><i class="sw" style="background:${REGION_COLOURS[i]}"></i>${n}</span>`).join("")}</div>
    <div class="ch-md" id="ch-carbon" role="img" aria-label="Carbon forecast per region"></div></section>
  <div class="fw-grid g21 fw-section">
    <section class="fw-card"><div class="h2h-head"><div><h2>Decision feed</h2><p class="sub" style="margin:2px 0 0">Newest first, from the live event stream</p></div>
      <div style="display:flex;gap:12px;flex-wrap:wrap"><div class="picker"><label for="f-pol">Policy</label><select id="f-pol"></select></div>
      <div class="picker"><label for="f-kind">Kind</label><select id="f-kind"><option value="ALL">All</option><option>MOVE</option><option>KEEP</option><option>SCREEN_FAIL</option><option value="RESCUE">RESCUE</option><option>PLACE</option></select></div></div></div>
      <div class="feed" id="feed" style="max-height:420px"></div></section>
    <section class="fw-card"><h2>What decision_flip does with each check</h2><p class="sub">Measured live in this session</p>
      <div class="ch-sm" style="height:260px" id="ch-donut" role="img" aria-label="Decision kinds donut"></div><p class="small fw-muted" id="donut-note"></p></section>
  </div>`;
  view.querySelector("#f-pol").addEventListener("change", (e) => { policy = e.target.value; feed(window.__fwState); });
  view.querySelector("#f-kind").addEventListener("change", (e) => { kind = e.target.value; feed(window.__fwState); });
}
export function unmount() { root = null; }

function feed(s) {
  if (!root || !s) return;
  const all = (s.events[policy] || []).slice().reverse();
  const rows = all.filter((d) => kind === "ALL" || (kind === "RESCUE" ? d.kind.startsWith("RESCUE") : d.kind === kind)).slice(0, 120);
  root.querySelector("#feed").innerHTML = rows.map((d) => `<div class="frow"><span class="t mono">${esc(timeOnly(d.time))}</span>${badge(d.kind)}<span>${esc(decisionText(d))}</span></div>`).join("") || '<p class="fw-muted">No decisions of this kind yet</p>';
}

function carbon(st, hist) {
  const h = hist.decision_flip || [], nowS = st.clock.sim_time_s, slot0 = Math.floor(nowS / 1800) * 1800, sers = [];
  st.carbon.forEach((c, i) => {
    const col = REGION_COLOURS[i % 3];
    sers.push({ name: REGION_SHORT[i] + " actual", type: "line", showSymbol: false, connectNulls: true, lineStyle: { color: col, width: 2 }, itemStyle: { color: col },
      data: h.map((p) => [p.t, p.dcs[i] ? p.dcs[i].actual_g_per_kwh : null]),
      markLine: i === 0 ? { symbol: "none", silent: true, lineStyle: { color: "#111827", type: "dashed" }, label: { formatter: "now", color: "#111827" }, data: [{ xAxis: nowS }] } : undefined });
    sers.push({ name: REGION_SHORT[i] + " forecast", type: "line", showSymbol: false, lineStyle: { color: col, width: 2, type: "dashed" }, itemStyle: { color: col },
      data: (c.forecast_next_6h || []).map((v, k) => [slot0 + k * 1800, v]) });
  });
  chart("sc-carbon", root.querySelector("#ch-carbon")).setOption({
    animation: false, tooltip: { trigger: "axis", valueFormatter: (v) => (v == null ? "--" : Number(v).toFixed(0) + " g/kWh") },
    grid: { left: 48, right: 16, top: 32, bottom: 28 },
    xAxis: { type: "value", min: "dataMin", max: "dataMax", axisLabel: { formatter: (v) => istClock(v), color: "#4B5563" } },
    yAxis: { type: "value", name: "g/kWh", scale: true, axisLabel: { color: "#4B5563" }, splitLine: { lineStyle: { color: "#EEF0F3" } } }, series: sers }, true);
}

function donut(st) {
  const c = st.compare.decision_flip;
  if (!c) return;
  const d = c.decisions || {}, skip = d.SCREEN_FAIL || 0, moved = d.MOVE || 0, kept = d.KEEP || 0;
  const total = skip + moved + kept;
  chart("sc-donut", root.querySelector("#ch-donut")).setOption({
    animation: false, tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
    legend: { bottom: 0, textStyle: { fontSize: 11, color: "#374151" } },
    series: [{ type: "pie", radius: ["48%", "72%"], center: ["50%", "44%"], label: { show: false },
      data: [{ name: "Screen-skipped", value: skip, itemStyle: { color: "#9CA3AF" } }, { name: "Re-scored and kept", value: kept, itemStyle: { color: "#DB2777" } }, { name: "Moved", value: moved, itemStyle: { color: "#D97706" } }] }] }, true);
  root.querySelector("#donut-note").textContent = total ? `${int(skip)} of ${int(total)} checks (${((skip / total) * 100).toFixed(0)}%) were stopped by the cheap screen; ${int(moved)} led to a move.` : "No checks yet.";
}

export function update(s) {
  if (!root || !s || !s.status) return;
  window.__fwState = s;
  const sel = root.querySelector("#f-pol"), names = s.status.policies;
  if (shown !== names.join(",")) { sel.innerHTML = names.map((p) => `<option value="${esc(p)}">${esc(p)}</option>`).join(""); shown = names.join(","); }
  sel.value = policy;
  carbon(s.status, s.history); donut(s.status); feed(s);
}
