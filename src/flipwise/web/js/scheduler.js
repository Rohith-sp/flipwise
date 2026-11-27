// Scheduler: the forecasts it sees, every decision it makes, and how the work splits up.
import { esc, int, badge, decisionText, whyCard, chart, carbonChart, policySelect, timeOnly, REGION_COLOURS, REGION_SHORT } from "./util.js";

let root = null, policy = "decision_flip", kind = "ALL", picked = null, lastRows = [];
export const title = ["Scheduler", "What the planner sees, and what it decides at each forecast update"];

export function mount(view) {
  root = view;
  view.innerHTML = `
  <section class="fw-card"><h2>Carbon forecast by region</h2><p class="sub">Forecast for the next 6 hours (dashed) and actual so far (solid), in gCO2 per kWh of grid electricity. The scheduler sees only the forecast.</p>
    <div class="rlegend">${REGION_SHORT.map((n, i) => `<span><i class="sw" style="background:${REGION_COLOURS[i]}"></i>${n}</span>`).join("")}</div>
    <div class="ch-md" id="ch-carbon" role="img" aria-label="Carbon forecast per region"></div></section>
  <section class="fw-card fw-section" id="why" aria-live="polite"><h2>Why this job moved</h2><p class="sub">Click any row in the decision feed below to see the plain-words reason and the numbers.</p><div id="why-body"><p class="fw-muted">Nothing selected yet.</p></div></section>
  <div class="fw-grid g21 fw-section">
    <section class="fw-card"><div class="h2h-head"><div><h2>Decision feed</h2><p class="sub" style="margin:2px 0 0">Newest first, from the live event stream. Click a row to see why.</p></div>
      <div style="display:flex;gap:12px;flex-wrap:wrap"><div class="picker"><label for="f-pol">Policy</label><select id="f-pol"></select></div>
      <div class="picker"><label for="f-kind">Kind</label><select id="f-kind"><option value="ALL">All</option><option>MOVE</option><option>KEEP</option><option value="SCREEN_FAIL">SCREEN_FAIL (screened out)</option><option value="RESCUE">RESCUE</option><option>PLACE</option></select></div></div></div>
      <div class="feed" id="feed" style="max-height:420px"></div></section>
    <section class="fw-card"><h2>What decision_flip does with each check</h2><p class="sub">Measured live in this session</p>
      <div class="ch-sm" style="height:260px" id="ch-donut" role="img" aria-label="Decision kinds donut"></div><p class="small fw-muted" id="donut-note"></p></section>
  </div>`;
  view.querySelector("#feed").addEventListener("click", (e) => {
    const r = e.target.closest(".frow"); if (!r) return;
    picked = lastRows[+r.dataset.i]; showWhy(); feed(window.__fwState);
  });
  view.querySelector("#f-pol").addEventListener("change", (e) => { policy = e.target.value; feed(window.__fwState); });
  view.querySelector("#f-kind").addEventListener("change", (e) => { kind = e.target.value; feed(window.__fwState); });
}
export function unmount() { root = null; }

function showWhy() {
  if (root && picked) root.querySelector("#why-body").innerHTML = whyCard(picked, picked.policy || policy);
}

function feed(s) {
  if (!root || !s) return;
  const all = (s.events[policy] || []).slice().reverse();
  const rows = all.filter((d) => kind === "ALL" || (kind === "RESCUE" ? d.kind.startsWith("RESCUE") : d.kind === kind)).slice(0, 120);
  lastRows = rows;
  root.querySelector("#feed").innerHTML = rows.map((d, i) => `<div class="frow clickable${picked && picked.job_id === d.job_id && picked.time_s === d.time_s && picked.kind === d.kind ? " sel" : ""}" data-i="${i}"><span class="t mono">${esc(timeOnly(d.time))}</span>${badge(d.kind)}<span>${esc(decisionText(d))}</span></div>`).join("") || '<p class="fw-muted">No decisions of this kind yet</p>';
}

const carbon = (st, hist) => carbonChart("sc-carbon", root.querySelector("#ch-carbon"), st, hist.decision_flip || [], { left: 48, right: 16, top: 32, bottom: 28 });

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
  policy = policySelect(root.querySelector("#f-pol"), s.status.policies, policy);
  carbon(s.status, s.history); donut(s.status); feed(s);
}
