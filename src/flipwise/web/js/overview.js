// Overview: three headline numbers for the two compared policies, one chart, the sites at a glance.
import { tip, keepLast, esc, num, int, badge, dcLink, decisionText, colourOf, chart, gClass, timeOnly, siteColour, sitesOf, pairOf, dot, rel, more, onMore, isOpen, tsToMs, axisTime } from "./util.js";

let root = null;

export const title = ["Overview", (s) => {
  const n = sitesOf(s.status).length, [a, b] = pairOf(s);
  return `One scheduler, ${n || "several"} grid sites in India: ${a} against ${b} on the same jobs and the same carbon`;
}];

export function mount(view) {
  root = view;
  view.innerHTML = `
  <p class="lede" id="lede">Waiting for the first numbers...</p>
  <div class="fw-grid g3" id="kpis"></div>
  <section class="fw-card fw-section"><h2>Re-planning work over time</h2>
    <p class="sub">Full re-scores run so far: the expensive check of a job's plan against the latest forecast. Lower means less scheduler work for the same jobs.</p>
    <div class="chart-lg" id="ch-main" role="img" aria-label="Full re-scores over time for the two policies"></div></section>
  <section class="fw-section"><h2 class="sec-h" id="sites-h">The sites right now</h2><div class="sites" id="sites"></div></section>
  ${more("ov-more", "Show more: services and the latest decisions", `<div class="fw-grid g11">
    <section class="fw-card"><h2>Services</h2><p class="sub">Scheduler and datacentres talk over HTTP</p><div id="services"></div>
      <h3 class="h3">Latest messages</h3><div class="msgs mono" id="msgs"></div></section>
    <section class="fw-card"><h2 id="feed-h">Decision feed</h2><p class="sub">Every check, newest first</p><div class="feed" id="feed"></div></section></div>`)}`;
  onMore(view, "ov-more", () => update(window.__fwState));
}
export function unmount() { root = null; }

// One tile: the same measure for both policies, side by side, and how they differ.
function tile(label, a, b, va, vb, unit, fmt, word) {
  const r = rel(va, vb, word[0], word[1]);
  const side = (p, v) => `<div class="pv"><div class="pn">${dot(p)}${esc(p)}</div><div class="big">${fmt(v)}<span class="u">${unit}</span></div></div>`;
  return `<section class="fw-card kpi2"><div class="lab">${label}</div><div class="pvs">${side(a, va)}${side(b, vb)}</div>
    <div class="verdict ${/more/.test(r) ? "bad" : ""}">${r ? `${esc(a)}: ${r}` : "&nbsp;"}</div></section>`;
}

function kpis(st, pair) {
  const [a, b] = pair, A = st.compare[a], B = st.compare[b];
  if (!A || !B) return;
  root.querySelector("#kpis").innerHTML =
    tile("CO2 emitted so far", a, b, A.kg_co2_so_far, B.kg_co2_so_far, " kg", (v) => num(v, 1), ["less", "more"]) +
    tile(tip("re-score", "Full re-scores (work)"), a, b, A.full_rescores, B.full_rescores, "", int, ["fewer", "more"]) +
    tile("Jobs moved to a new site or time", a, b, A.moves, B.moves, "", int, ["fewer", "more"]);
  const w = rel(A.full_rescores, B.full_rescores), c = rel(A.kg_co2_so_far, B.kg_co2_so_far, "less", "more");
  root.querySelector("#lede").innerHTML = B.full_rescores
    ? `So far <b>${esc(a)}</b> did <b>${w}</b> full re-scores than ${esc(b)}, for <b>${c === "about the same" ? "about the same" : c}</b> carbon. ${int(A.jobs_completed)} jobs completed, ${int(A.deadline_misses)} deadline ${A.deadline_misses === 1 ? "miss" : "misses"}.`
    : "Waiting for the first forecast update, when re-planning starts.";
}

function mainChart(s, pair) {
  chart("ov-main", root.querySelector("#ch-main")).setOption({
    animation: false, tooltip: { trigger: "axis" },
    legend: { top: 0, textStyle: { color: "#334155" } }, grid: { left: 56, right: 20, top: 36, bottom: 30 }, xAxis: axisTime,
    yAxis: { type: "value", min: 0, name: "re-scores", nameTextStyle: { color: "#64748B" }, axisLabel: { color: "#64748B" }, splitLine: { lineStyle: { color: "#EEF2F6" } } },
    series: pair.map((p) => ({ name: p, type: "line", showSymbol: false, lineStyle: { width: 3, color: colourOf(p) }, itemStyle: { color: colourOf(p) },
      data: tsToMs(s.history[p] || [], (h) => h.full_rescores) })) }, true);
}

// The latest half-hour snapshot of the main policy: no extra requests per site.
function sites(s, pair) {
  const st = s.status, list = sitesOf(st), h = s.history[pair[0]] || [], last = h[h.length - 1];
  root.querySelector("#sites-h").textContent = `The ${list.length} sites right now (${pair[0]})`;
  root.querySelector("#sites").innerHTML = list.map((site, i) => {
    const d = last && last.dcs[i], c = st.carbon[i] || {};
    const g = keepLast("g" + i, c.actual_g_per_kwh ?? c.forecast_g_per_kwh);
    const cap = site.capacity ? site.capacity.gpus : null, used = d ? d.gpus_used : null;
    const u = cap && used != null ? Math.round((used / cap) * 100) : 0;
    return `<section class="fw-card site" style="--sc:${siteColour(i)}"><div class="site-h"><b>${esc(site.short)}</b><span class="chip-g ${gClass(g)}">${num(g, 0)} g/kWh</span></div>
      <div class="small fw-muted">${esc(site.grid || "")}</div>
      <div class="dcrow"><span>GPUs in use</span><b>${u}%</b></div>
      <div class="bar" role="progressbar" aria-valuenow="${u}" aria-valuemin="0" aria-valuemax="100" aria-label="GPU load at ${esc(site.short)}"><i style="width:${u}%;background:${siteColour(i)}"></i></div>
      <div class="dcrow"><span>Running / queued</span><b>${d ? int(d.running) : "--"} / ${d ? int(d.queued) : "--"}</b></div>
      <div class="dcrow"><span>CO2 so far</span><b>${d ? num(d.kg_co2, 1) : "--"} kg</b></div></section>`;
  }).join("");
}

function services(health, st) {
  const names = sitesOf(st);
  const rows = (health ? health.datacentres : []).map((d) => `<div class="svc"><div><b>${esc((names[d.dc_id] || {}).short || "dc" + d.dc_id)}</b><div class="small fw-muted">${esc(d.url)}</div>${dcLink(d)}</div>
    <div class="small" style="text-align:right">${int(d.requests)} requests<br>${d.mean_latency_ms == null ? "--" : d.mean_latency_ms.toFixed(2)} ms mean</div></div>`).join("");
  root.querySelector("#services").innerHTML = `<div class="svc"><div><b>Scheduler &middot; ${esc(health ? health.policy : st.policies[0])}</b><div class="small fw-muted">owns the simulated clock</div></div><div class="small">${esc(st.remote_policy ? "calls services" : "in-process")}</div></div>${rows}`;
  root.querySelector("#msgs").innerHTML = st.recent_messages.slice().reverse().slice(0, 12).map((m) =>
    `<div>${esc(timeOnly(m.t))} dc${esc(m.dc_id)} ${esc(m.op)} ${esc(m.job_id || m.detail || "")}</div>`).join("") || "<div>No messages yet</div>";
}

function feed(st, p) {
  root.querySelector("#feed-h").textContent = `Decision feed · ${p}`;
  const ds = (st.recent_decisions[p] || []).slice().reverse();
  root.querySelector("#feed").innerHTML = ds.map((d) => `<div class="frow"><span class="t mono">${esc(timeOnly(d.time))}</span>${badge(d.kind)}<span>${esc(decisionText(d))}</span></div>`).join("") || '<p class="fw-muted">No decisions yet</p>';
}

export function update(s) {
  if (!root || !s.status) return;
  const st = s.status, pair = pairOf(s);
  kpis(st, pair); mainChart(s, pair); sites(s, pair);
  if (isOpen(root, "ov-more")) { services(s.health, st); feed(st, pair[0]); }
}
