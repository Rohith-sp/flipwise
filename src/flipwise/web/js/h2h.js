// Head-to-head: decision_flip against the challenger picked in the sidebar, per forecast update.
import * as api from "./api.js";
import { esc, int, num, chart, colourOf, shortRegion, istClock, jobChips, keepLast, gClass, POLICY_RULES, siteColour, sitesOf, pairOf, dot, more, onMore, isOpen } from "./util.js";

let root = null, act = {}, lanes = {}, repSeen = null;
const MAX_BARS = 48;

export const title = ["Head-to-head", (s) => { const [a, b] = pairOf(s); return `${a} against ${b}: what each does at every forecast update`; }];

export function mount(view) {
  root = view; act = {}; lanes = {};
  view.innerHTML = `
  <div class="fw-grid g4" id="strip"></div>
  <section class="fw-card fw-section rules" id="say"></section>
  <section class="fw-card fw-section"><h2>Full re-scores at each forecast update</h2>
    <p class="sub" id="main-sub">Each new forecast, a policy may re-check pending jobs. Bars show how many it fully re-scored. The last 48 updates.</p>
    <div class="chart-lg" id="ch-main" role="img" aria-label="Full re-scores per forecast update, two policies"></div></section>
  ${more("h-more", "Show more: what decision_flip's checks became, jobs at each site, all policies", `
    <section class="fw-card"><h2>What decision_flip's checks became</h2><p class="sub">Per forecast update: stopped by the cheap screen, re-scored and kept, moved, rescued</p>
      <div class="chart" id="ch-mix" role="img" aria-label="decision_flip checks by outcome"></div></section>
    <section class="fw-card fw-section"><h2>Jobs at each site</h2><p class="sub">Squares show GPUs. Indigo: planned, amber: queued, green: running. Black outline: your job; amber dot: moved.</p><div id="lanes"></div></section>
    <section class="fw-card fw-section"><h2>All policies so far</h2><p class="sub">Every policy runs in the background on the same jobs; sorted by CO2</p><div class="tw" id="lb"></div></section>`)}`;
  onMore(view, "h-more", () => load(window.__fwState).then(() => update(window.__fwState), () => {}));
}
export function unmount() { root = null; }

export async function load(s) {
  if (!s || !s.status || !root) return;
  if (s.replicate !== repSeen) { act = {}; repSeen = s.replicate; }
  const pair = pairOf(s), withLanes = isOpen(root, "h-more");
  await Promise.all(pair.map(async (p) => {
    const have = act[p] || [];
    const since = have.length ? have[have.length - 1].t : null;
    const [rows, l] = await Promise.all([api.getActivity(p, since), withLanes ? api.getLanes(p) : null]);
    // Another load may have appended while this one was in flight: keep only newer rows.
    const now = act[p] || [], last = now.length ? now[now.length - 1].t : -1;
    act[p] = now.concat(rows.filter((r) => r.t > last));
    if (l) lanes[p] = l;
  }));
}

const checks = (c) => c.screen_skips + c.full_rescores;

function strip(st, a, b) {
  const A = st.compare[a], B = st.compare[b];
  if (!A || !B) return;
  const saved = B.full_rescores - A.full_rescores, savedPct = B.full_rescores ? (saved / B.full_rescores) * 100 : 0;
  const dco2 = A.kg_co2_so_far - B.kg_co2_so_far, dpct = B.kg_co2_so_far ? (dco2 / B.kg_co2_so_far) * 100 : 0;
  const share = checks(A) ? (A.screen_skips / checks(A)) * 100 : 0;
  const t = (lab, big, n) => `<section class="fw-card kpi"><div class="lab">${lab}</div><div class="val">${big}</div><div class="note">${n}</div></section>`;
  root.querySelector("#strip").innerHTML =
    t("Re-scores saved", `${int(saved)}<span class="u"> (${savedPct.toFixed(0)}%)</span>`, `${int(A.full_rescores)} vs ${int(B.full_rescores)}`) +
    t("Moves avoided", int(B.moves - A.moves), `${int(A.moves)} vs ${int(B.moves)} moves`) +
    t("CO2 difference", `${dco2 <= 0 ? "" : "+"}${num(dco2, 2)}<span class="u"> kg (${dpct <= 0 ? "" : "+"}${dpct.toFixed(1)}%)</span>`, "completed jobs only") +
    t("Checks stopped by the screen", `${share.toFixed(0)}<span class="u">%</span>`, `${int(A.screen_skips)} of ${esc(a)}'s ${int(checks(A))} checks`);
  root.querySelector("#say").innerHTML = `<div class="rule">${dot(a)}<b>${esc(a)}</b><span>${esc(POLICY_RULES[a] || "")}</span></div><div class="rule">${dot(b)}<b>${esc(b)}</b><span>${esc(POLICY_RULES[b] || "")}</span></div>`;
}

function mainChart(pair) {
  const rows = pair.map((p) => (act[p] || []).slice(-MAX_BARS));
  const times = [...new Set(rows.flat().map((r) => r.t))].sort((x, y) => x - y).slice(-MAX_BARS);
  const by = pair.map((p, i) => new Map(rows[i].map((r) => [r.t, r.checked - r.screen_skipped])));
  chart("h2h-main", root.querySelector("#ch-main")).setOption({
    animation: false, tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: { top: 0, textStyle: { color: "#334155" } }, grid: { left: 48, right: 16, top: 36, bottom: 30 },
    xAxis: { type: "category", data: times.map((t) => istClock(t)), axisLabel: { color: "#64748B" } },
    yAxis: { type: "value", min: 0, axisLabel: { color: "#64748B" }, splitLine: { lineStyle: { color: "#EEF2F6" } } },
    series: pair.map((p, i) => ({ name: p, type: "bar", barMaxWidth: 14, itemStyle: { color: colourOf(p) }, data: times.map((t) => by[i].get(t) ?? 0) })) }, true);
}

function mixChart(p) {
  const r = (act[p] || []).slice(-MAX_BARS);
  const seg = (name, key, col) => ({ name, type: "bar", stack: "a", data: r.map((x) => x[key]), itemStyle: { color: col }, barMaxWidth: 14 });
  chart("h2h-mix", root.querySelector("#ch-mix")).setOption({
    animation: false, tooltip: { trigger: "axis", axisPointer: { type: "shadow" } }, legend: { top: 0, textStyle: { color: "#334155" } },
    grid: { left: 40, right: 8, top: 34, bottom: 26 },
    xAxis: { type: "category", data: r.map((x) => istClock(x.t)), axisLabel: { color: "#64748B" } },
    yAxis: { type: "value", min: 0, axisLabel: { color: "#64748B" }, splitLine: { lineStyle: { color: "#EEF2F6" } } },
    series: [seg("Stopped by screen", "screen_skipped", "#CBD5E1"), seg("Re-scored, kept", "rescored_kept", "#94A3B8"),
      seg("Moved", "moved", "#2563EB"), seg("Rescued", "rescued", "#DC2626")] }, true);
}

function lanesHtml(st, pair) {
  const names = sitesOf(st);
  return pair.map((p) => { const L = lanes[p];
    return `<div class="lane-p"><h3 class="h3">${dot(p)}${esc(p)}</h3><div class="dcgrid">${names.map((site, i) => {
      const d = L && L.datacentres[i], c = st.carbon[i] || {}, g = keepLast("g" + i, c.actual_g_per_kwh ?? c.forecast_g_per_kwh);
      return d ? `<div class="dcp" style="border-top:3px solid ${siteColour(i)}"><div class="dcp-h"><b>${esc(shortRegion(d.name))}</b><span class="chip-g ${gClass(g)}">${num(g, 0)}</span></div>
        <div class="sbox"><div class="sl">Planned (${int(d.planned.total)})</div><div class="jchips">${jobChips(d.planned, "planned")}</div></div>
        <div class="sbox"><div class="sl">Queued (${int(d.queued.total)})</div><div class="jchips">${jobChips(d.queued, "queued")}</div></div>
        <div class="sbox"><div class="sl">Running (${int(d.running.total)})</div><div class="jchips">${jobChips(d.running, "running")}</div></div></div>`
        : `<div class="dcp fw-muted">Loading</div>`; }).join("")}</div></div>`; }).join("");
}

function leaderboard(st) {
  const rows = Object.entries(st.compare).sort((x, y) => x[1].kg_co2_so_far - y[1].kg_co2_so_far);
  return `<table class="fw-t"><thead><tr><th>Policy</th><th>CO2 so far (kg)</th><th>Full re-scores</th><th>Moves</th><th>Deadline misses</th><th>Jobs completed</th></tr></thead><tbody>` +
    rows.map(([n, c]) => `<tr class="${n === "decision_flip" ? "hl" : ""}"><td>${dot(n)}${esc(n)}</td><td>${num(c.kg_co2_so_far, 2)}</td><td>${int(c.full_rescores)}</td><td>${int(c.moves)}</td><td>${int(c.deadline_misses)}</td><td>${int(c.jobs_completed)}</td></tr>`).join("") + "</tbody></table>";
}

export function update(s) {
  if (!root || !s || !s.status) return;
  const st = s.status, pair = pairOf(s);
  strip(st, pair[0], pair[1]); mainChart(pair);
  if (isOpen(root, "h-more")) { mixChart(pair[0]); root.querySelector("#lanes").innerHTML = lanesHtml(st, pair); root.querySelector("#lb").innerHTML = leaderboard(st); }
}
