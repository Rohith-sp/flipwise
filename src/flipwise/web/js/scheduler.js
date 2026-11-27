// Scheduler: the forecasts it sees, and why each job moved or stayed.
import { esc, int, badge, decisionText, whyCard, chart, carbonChart, timeOnly, pairOf, sitesOf, more, onMore, isOpen } from "./util.js";

let root = null, policy = null, kind = "MOVE", picked = null, lastRows = [];
export const title = ["Scheduler", (s) => `What the planner sees at the ${sitesOf(s.status).length || "several"} sites, and why each job moved`];

export function mount(view) {
  root = view; picked = null;
  view.innerHTML = `
  <section class="fw-card"><h2>Grid carbon at each site</h2><p class="sub">Solid: what the grid actually emitted (last 2 days). Dashed: the forecast for the next 6 hours, the only thing the scheduler sees. gCO2 per kWh; click a site name to hide it.<span id="shared"></span></p>
    <div class="chart-lg" id="ch-carbon" role="img" aria-label="Carbon forecast and actual per site"></div></section>
  <div class="fw-grid g21 fw-section">
    <section class="fw-card"><div class="card-h"><div><h2>Decision feed</h2><p class="sub" style="margin:2px 0 0">Newest first. Click a row to see why.</p></div>
      <div class="filters"><div class="picker"><label for="f-pol">Policy</label><select id="f-pol"></select></div>
      <div class="picker"><label for="f-kind">Show</label><select id="f-kind"><option value="MOVE">Moves only</option><option value="ALL">Every check</option><option value="KEEP">Kept</option><option value="SCREEN_FAIL">Stopped by screen</option><option value="RESCUE">Rescues</option><option value="PLACE">First placements</option></select></div></div></div>
      <div class="feed" id="feed"></div></section>
    <section class="fw-card why-card" id="why" aria-live="polite"><h2>Why this job moved</h2><p class="sub" id="why-sub">The latest move, until you click a row.</p><div id="why-body"><p class="fw-muted">No move yet.</p></div></section>
  </div>
  ${more("s-more", "Show more: how decision_flip's checks split up", `<section class="fw-card"><h2>What decision_flip does with each check</h2><p class="sub">Measured live in this session</p>
      <div class="chart" id="ch-donut" role="img" aria-label="Decision kinds"></div><p class="small fw-muted" id="donut-note"></p></section>`)}`;
  view.querySelector("#f-kind").value = kind;
  view.querySelector("#feed").addEventListener("click", (e) => {
    const r = e.target.closest(".frow"); if (!r) return;
    picked = lastRows[+r.dataset.i]; feed(window.__fwState);
  });
  view.querySelector("#f-pol").addEventListener("change", (e) => { policy = e.target.value; picked = null; feed(window.__fwState); });
  view.querySelector("#f-kind").addEventListener("change", (e) => { kind = e.target.value; feed(window.__fwState); });
  onMore(view, "s-more", () => donut(window.__fwState.status));
}
export function unmount() { root = null; }

function feed(s) {
  if (!root || !s) return;
  const all = (s.events[policy] || []).slice().reverse();
  const rows = all.filter((d) => kind === "ALL" || (kind === "RESCUE" ? d.kind.startsWith("RESCUE") : d.kind === kind)).slice(0, 60);
  lastRows = rows;
  const same = (d) => picked && picked.job_id === d.job_id && picked.time_s === d.time_s && picked.kind === d.kind;
  root.querySelector("#feed").innerHTML = rows.map((d, i) => `<div class="frow clickable${same(d) ? " sel" : ""}" data-i="${i}"><span class="t mono">${esc(timeOnly(d.time))}</span>${badge(d.kind)}<span>${esc(decisionText(d))}</span></div>`).join("") || '<p class="fw-muted">Nothing of this kind yet</p>';
  // Never an empty card: show the latest move of this policy until the presenter picks a row.
  const shown = picked || all.find((d) => d.kind === "MOVE");
  root.querySelector("#why-sub").textContent = picked ? "The row you picked." : "The latest move, until you click a row.";
  if (shown) root.querySelector("#why-body").innerHTML = whyCard(shown, policy);
}

function donut(st) {
  const c = st && st.compare.decision_flip;
  if (!c || !root) return;
  const d = c.decisions || {}, skip = d.SCREEN_FAIL || 0, moved = d.MOVE || 0, kept = d.KEEP || 0;
  const total = skip + moved + kept;
  chart("sc-donut", root.querySelector("#ch-donut")).setOption({
    animation: false, tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
    legend: { bottom: 0, textStyle: { fontSize: 12, color: "#334155" } },
    series: [{ type: "pie", radius: ["48%", "72%"], center: ["50%", "44%"], label: { show: false },
      data: [{ name: "Stopped by screen", value: skip, itemStyle: { color: "#CBD5E1" } }, { name: "Re-scored, kept", value: kept, itemStyle: { color: "#94A3B8" } }, { name: "Moved", value: moved, itemStyle: { color: "#2563EB" } }] }] }, true);
  root.querySelector("#donut-note").textContent = total ? `${int(skip)} of ${int(total)} checks (${((skip / total) * 100).toFixed(0)}%) were stopped by the cheap screen; ${int(moved)} led to a move.` : "No checks yet.";
}

export function update(s) {
  if (!root || !s || !s.status) return;
  const pair = pairOf(s), sel = root.querySelector("#f-pol");
  if (!pair.includes(policy)) policy = pair[0];
  if (sel.dataset.names !== pair.join(",")) { sel.innerHTML = pair.map((p) => `<option value="${esc(p)}">${esc(p)}</option>`).join(""); sel.dataset.names = pair.join(","); }
  sel.value = policy;
  carbonChart("sc-carbon", root.querySelector("#ch-carbon"), s.status, s.history[pair[0]] || [], { left: 52, right: 20, top: 40, bottom: 30 });
  // Sites on the same grid get the same carbon, so their lines lie on top of each other.
  const byGrid = {};
  sitesOf(s.status).forEach((x) => (byGrid[x.region_id] = (byGrid[x.region_id] || []).concat(x.short)));
  const shared = Object.values(byGrid).filter((v) => v.length > 1).map((v) => v.join(" and ")).join("; ");
  root.querySelector("#shared").textContent = shared ? ` ${shared} share one grid, so their lines overlap.` : "";
  feed(s);
  if (isOpen(root, "s-more")) donut(s.status);
}
