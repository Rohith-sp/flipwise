// Architecture: how the scheduler talks to the datacentres (any number), with live service numbers.
import { esc, int, dcLink, siteColour, sitesOf } from "./util.js";

let root = null;
export const title = ["Architecture", (s) => `One scheduler, ${sitesOf(s.status).length || "several"} datacentre services, one simulated clock`];

// Arrows from the scheduler to each datacentre box, for however many sites there are: the box
// centres are measured after layout, so the arrows meet the boxes at any height.
function arrows(host) {
  const boxes = [...host.querySelectorAll(".abox-dc")];
  if (!boxes.length) return "";
  const top = host.getBoundingClientRect().top, h = Math.round(host.getBoundingClientRect().height), mid = h / 2;
  const ys = boxes.map((b) => { const r = b.getBoundingClientRect(); return Math.round(r.top - top + r.height / 2); });
  const paths = ys.map((y) => `M52 ${mid}V${y}h56M100 ${y - 6}l8 6-8 6`).join("");
  return `<svg viewBox="0 0 120 ${h}" width="120" height="${h}" aria-hidden="true" style="display:block;margin:0 auto" fill="none" stroke="#94A3B8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 ${mid}h50${paths}"/></svg>`;
}

export function mount(view) {
  root = view;
  view.innerHTML = `<section class="fw-card"><h2>How the pieces connect</h2><p class="sub">Requests and latency are measured live for the policy whose calls are timed.</p>
    <div class="arch">
      <div class="abox" style="border-color:#2563EB"><h3>Scheduler (coordinator)</h3><div class="small fw-muted">Owns the simulated clock. Decides when to re-plan, what to move, and talks to each datacentre.</div><div class="small" id="sched" style="margin-top:6px"></div></div>
      <div id="arrows"></div>
      <div id="dcs" class="arch-dcs"></div></div></section>
  <div class="fw-grid g11 fw-section">
    <section class="fw-card"><h2>Local split</h2><p class="small" style="margin:0" id="local"></p></section>
    <section class="fw-card"><h2>Docker</h2><p class="small" style="margin:0" id="docker"></p></section>
  </div>`;
}
export function unmount() { root = null; }

export function update(s) {
  if (!root || !s || !s.status) return;
  const h = s.health, st = s.status, sites = sitesOf(st), n = sites.length;
  root.querySelector("#sched").textContent = `Policy timed: ${h ? h.policy : "--"} · ${st.remote_policy ? "calls services over HTTP" : "in-process calls"}`;
  const host = root.querySelector("#dcs");
  host.innerHTML = (h ? h.datacentres : []).map((d) => `<div class="abox abox-dc" style="border-left:4px solid ${siteColour(d.dc_id)}"><h3>${esc((sites[d.dc_id] || {}).short || "dc" + d.dc_id)} <span class="fw-muted small">dc${d.dc_id} &middot; ${esc((sites[d.dc_id] || {}).grid || "")}</span></h3>
    <div class="small fw-muted">${esc(d.url)} ${dcLink(d)}</div><div class="small">${int(d.requests)} requests &middot; ${d.mean_latency_ms == null ? "--" : d.mean_latency_ms.toFixed(2)} ms mean latency</div></div>`).join("");
  root.querySelector("#arrows").innerHTML = arrows(host);
  root.querySelector("#local").innerHTML = `Each datacentre can run as its own small HTTP service on this machine (<code>flipwise dc-serve</code>, started together by <code>flipwise live --services local</code>), and each serves its own dashboard on ports 8101 to ${8100 + n}. The scheduler sends enqueue, dispatch, complete and state requests over HTTP; the services never read the wall clock, so remote runs match in-process runs byte for byte.`;
  root.querySelector("#docker").innerHTML = `The same services run as containers: the live demo starts one scheduler and ${n} datacentre containers on a private network (<code>docker compose --profile live up</code>). The datacentre logic exists once, in the datacentre module; the service only wraps it, so a transport change never changes a decision.`;
}
