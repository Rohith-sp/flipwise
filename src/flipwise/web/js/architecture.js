// Architecture: how the scheduler talks to the datacentres, with live service numbers.
import { esc, int, REGION_SHORT, REGION_COLOURS } from "./util.js";

let root = null;
export const title = ["Architecture", "One scheduler, three datacentre services, one simulated clock"];

export function mount(view) {
  root = view;
  view.innerHTML = `<section class="fw-card"><h2>How the pieces connect</h2><p class="sub">Requests and latency are measured live for the policy whose calls are timed.</p>
    <div class="arch">
      <div class="abox" style="border-color:#1D4ED8"><h3>Scheduler (coordinator)</h3><div class="small fw-muted">Owns the simulated clock. Decides when to re-plan, what to move, and talks to each datacentre.</div><div class="small" id="sched" style="margin-top:6px"></div></div>
      <svg viewBox="0 0 120 200" width="120" height="200" aria-hidden="true" style="display:block;margin:0 auto" fill="none" stroke="#4B5563" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M2 100h50M52 100V30h56M52 100h56M52 100v70h56"/><path d="M100 24l8 6-8 6M100 94l8 6-8 6M100 164l8 6-8 6"/></svg>
      <div id="dcs" style="display:grid;gap:10px"></div></div></section>
  <div class="fw-grid g11 fw-section">
    <section class="fw-card"><h2>Local split</h2><p class="small" style="margin:0">Each datacentre can run as its own small HTTP service on this machine (<code>flipwise dc-serve</code>, started together by <code>scripts/local_cluster.sh</code>). The scheduler sends enqueue, dispatch, complete and state requests over HTTP; the services never read the wall clock, so remote runs match in-process runs byte for byte.</p></section>
    <section class="fw-card"><h2>Docker</h2><p class="small" style="margin:0">The same services run as containers with <code>docker compose up</code>: one coordinator and three datacentre containers on a private network. The datacentre logic exists once, in the datacentre module; the service only wraps it, so a transport change never changes a decision.</p></section>
  </div>`;
}
export function unmount() { root = null; }

export function update(s) {
  if (!root || !s || !s.status) return;
  const h = s.health, st = s.status;
  root.querySelector("#sched").textContent = `Policy timed: ${h ? h.policy : "--"} · ${st.remote_policy ? "calls services over HTTP" : "in-process calls"}`;
  root.querySelector("#dcs").innerHTML = (h ? h.datacentres : []).map((d) => `<div class="abox" style="border-color:${REGION_COLOURS[d.dc_id]}"><h3>Datacentre ${d.dc_id} &middot; ${esc(REGION_SHORT[d.dc_id] || "")}</h3>
    <div class="small fw-muted">${esc(d.url)}</div><div class="small">${int(d.requests)} requests &middot; ${d.mean_latency_ms == null ? "--" : d.mean_latency_ms.toFixed(2)} ms mean latency</div></div>`).join("");
}
