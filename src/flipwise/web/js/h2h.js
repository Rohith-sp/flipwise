// Head-to-head: decision_flip above one challenger, same jobs and clock, lane by lane.
import * as api from "./api.js";
import { esc, int, num, chart, colourOf, shortRegion, timeOnly, istClock, jobChips, keepLast, gClass, POLICY_RULES, REGION_COLOURS } from "./util.js";

const MAIN = "decision_flip";
let root = null, challenger = "fixed_savings", act = {}, lanes = {}, repSeen = null, shownPolicies = "";
const MAX_BARS = 96;

export const title = ["Head-to-head", "decision_flip against one other policy on the same jobs, same clock"];

export function mount(view) {
  root = view; act = {}; lanes = {}; shownPolicies = "";
  view.innerHTML = `
  <section class="fw-card"><div class="h2h-head"><div class="picker"><label for="pick">Compare decision_flip with</label><select id="pick"></select></div>
    <p class="fw-muted small" style="margin:0">Measured live in this session; numbers count work done so far.</p></div>
    <div class="rlegend" style="margin-top:8px" aria-label="Chart legend"><span class="small fw-muted">Per forecast update, jobs checked:</span>${[["Screen-skipped", "#9CA3AF"], ["Re-scored and kept", "#DB2777"], ["Moved", "#D97706"], ["Rescued", "#B91C1C"]].map(([n, c]) => `<span><i class="sw" style="background:${c}"></i>${n}</span>`).join("")}</div>
    <div class="strip" id="strip"></div><p class="say" id="say"></p></section>
  <div id="lane-top"></div><div id="lane-bot"></div>`;
  view.querySelector("#pick").addEventListener("change", (e) => { challenger = e.target.value; update(window.__fwState); load(window.__fwState); });
}
export function unmount() { root = null; }

export async function load(s) {
  if (!s || !s.status) return;
  if (s.replicate !== repSeen) { act = {}; repSeen = s.replicate; }
  const names = [MAIN, challenger];
  await Promise.all(names.map(async (p) => {
    const have = act[p] || [];
    const since = have.length ? have[have.length - 1].t : null;
    const rows = await api.getActivity(p, since);
    act[p] = have.concat(rows);
    lanes[p] = await api.getLanes(p);
  }));
}

const checks = (c) => c.screen_skips + c.full_rescores;
const rescues = (c) => Object.entries(c.decisions || {}).reduce((a, [k, v]) => a + (k.startsWith("RESCUE") && k !== "RESCUE_NOOP" ? v : 0), 0);

function strip(st) {
  const a = st.compare[MAIN], b = st.compare[challenger];
  if (!a || !b) return;
  const saved = b.full_rescores - a.full_rescores, savedPct = b.full_rescores ? (saved / b.full_rescores) * 100 : 0;
  const mvAvoided = b.moves - a.moves, dco2 = a.kg_co2_so_far - b.kg_co2_so_far;
  const dpct = b.kg_co2_so_far ? (dco2 / b.kg_co2_so_far) * 100 : 0;
  const share = checks(a) ? (a.screen_skips / checks(a)) * 100 : 0;
  const tile = (lab, big, n) => `<div><div class="lab">${lab}</div><div class="big">${big}</div><div class="n">${n}</div></div>`;
  root.querySelector("#strip").innerHTML =
    tile("Re-scores saved (measured)", `${int(saved)} <span class="small">(${savedPct.toFixed(0)}%)</span>`, `${int(a.full_rescores)} vs ${int(b.full_rescores)} full re-scorings`) +
    tile("Moves avoided (measured)", int(mvAvoided), `${int(a.moves)} vs ${int(b.moves)} moves`) +
    tile("CO2 difference (measured)", `${dco2 <= 0 ? "" : "+"}${num(dco2, 3)} kg <span class="small">(${dpct <= 0 ? "" : "+"}${dpct.toFixed(1)}%)</span>`, "completed jobs only, so it depends on how many each policy has finished") +
    tile("Screen-avoided share (measured)", `${share.toFixed(0)}%`, `of decision_flip's ${int(checks(a))} checks`);
  root.querySelector("#say").textContent = `decision_flip skipped ${int(a.screen_skips)} of ${int(checks(a))} checks with the cheap screen, so it ran ${int(saved)} fewer full re-scorings than ${challenger}` +
    (Math.abs(dpct) < 1 ? " for about the same carbon." : dco2 < 0 ? ` and emitted ${Math.abs(dpct).toFixed(1)}% less carbon so far.` : ` and emitted ${dpct.toFixed(1)}% more carbon so far.`);
}

function dcPanel(d, i, st) {
  const c = st.carbon[i] || {};
  const g = keepLast("g" + i, c.actual_g_per_kwh ?? c.forecast_g_per_kwh);
  return d ? `<div class="dcp"><div class="dcp-h"><b style="color:${REGION_COLOURS[i]}">${esc(shortRegion(d.name))}</b><span class="chip-g ${gClass(g)}">${num(g, 0)} g/kWh</span></div>
    <div class="sbox"><div class="sl">Planned &middot; waiting for release (${int(d.planned.total)})</div><div class="jchips">${jobChips(d.planned, "planned")}</div></div>
    <div class="sbox"><div class="sl">Queue &middot; FIFO first-fit (${int(d.queued.total)})</div><div class="jchips">${jobChips(d.queued, "queued")}</div></div>
    <div class="sbox"><div class="sl">Running (${int(d.running.total)})</div><div class="jchips">${jobChips(d.running, "running")}</div></div>
    <div class="dcrow"><span>Completed</span><b>${int(d.completed)}</b></div></div>`
    : `<div class="dcp fw-muted">Loading</div>`;
}

function barChart(id, el, rows, ymax) {
  const r = rows.slice(-MAX_BARS);
  const seg = (name, key, col) => ({ name, type: "bar", stack: "a", data: r.map((x) => x[key]), itemStyle: { color: col }, barMaxWidth: 14 });
  chart(id, el).setOption({
    animation: false, tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: { show: false },
    grid: { left: 36, right: 8, top: 8, bottom: 24 },
    xAxis: { type: "category", data: r.map((x) => istClock(x.t)), axisLabel: { color: "#4B5563", fontSize: 10, interval: "auto" } },
    yAxis: { type: "value", min: 0, max: Math.max(1, ymax), axisLabel: { color: "#4B5563" }, splitLine: { lineStyle: { color: "#EEF0F3" } } },
    series: [seg("Screen-skipped", "screen_skipped", "#9CA3AF"), seg("Re-scored and kept", "rescored_kept", "#DB2777"),
      seg("Moved", "moved", "#D97706"), seg("Rescued", "rescued", "#B91C1C")] }, true);
}

function logRows(p, st, ev) {
  const lines = [];
  for (const r of (act[p] || []).slice(-80)) {
    lines.push({ t: r.t, o: 0, text: `${timeOnly(r.time)} forecast update &middot; ${r.checked} checked &middot; ${r.screen_skipped} skipped &middot; ${r.rescored_kept + r.moved} re-scored &middot; ${r.moved} moved` });
  }
  for (const d of (ev[p] || []).filter((e) => e.kind === "MOVE").slice(-80)) {
    const gain = d.S_a_kg != null && d.S_b_kg != null ? d.S_a_kg - d.S_b_kg : null;
    const need = d.g_min_kg != null && d.w_ab_kg != null ? d.g_min_kg + d.theta * d.w_ab_kg : null;
    lines.push({ t: d.time_s, o: 1, text: `<b>MOVE</b> ${esc(String(d.job_id).slice(0, 8))} ${esc(shortRegion(d.from))} → ${esc(shortRegion(d.to))}` + (gain != null ? ` &middot; gain ${num(gain, 3)}${need != null ? ` ≥ needed ${num(need, 3)}` : ""}` : "") });
  }
  lines.sort((a, b) => b.t - a.t || b.o - a.o);
  return lines.slice(0, 60).map((l) => `<div>${l.text}</div>`).join("") || "<div>Waiting for the first forecast update</div>";
}

function lane(host, p, st, ev, ymax, first) {
  const c = st.compare[p], L = lanes[p], colour = colourOf(p);
  if (!host.firstChild) host.innerHTML = `<section class="fw-card h2h-lane" style="--lc:${colour}"><div id="hd"></div><div class="h2h-body"><div class="dcp3" id="dcs"></div><div><div class="ch-sm" id="ch"></div><div class="evlog mono" id="log" tabindex="0" role="log" aria-label="${esc(p)} event log"></div></div></div></section>`;
  if (!c) return;
  const chip = (lab, v) => `<span class="cnt"><b>${v}</b><span>${lab}</span></span>`;
  host.querySelector("#hd").innerHTML = `<div class="h2h-head"><div><h2><i class="pdot" style="background:${colour}"></i>${esc(p)}</h2><p class="h2h-rule">${esc(POLICY_RULES[p] || "")}</p></div>
    <div class="cnts">${chip("full re-scorings", int(c.full_rescores))}${first ? chip("skipped by screen", int(c.screen_skips)) : ""}${chip("moves", int(c.moves))}${chip("rescues", int(rescues(c)))}${chip("CO2 so far", num(c.kg_co2_so_far, 2) + " kg")}${chip("deadline misses", int(c.deadline_misses))}</div></div>`;
  host.querySelector("#dcs").innerHTML = [0, 1, 2].map((i) => dcPanel(L && L.datacentres[i], i, st)).join("");
  barChart(`h2h-${first ? "a" : "b"}`, host.querySelector("#ch"), act[p] || [], ymax);
  host.querySelector("#log").innerHTML = logRows(p, st, ev);
}

export function update(s) {
  if (!root || !s || !s.status) return;
  window.__fwState = s;
  const st = s.status, pick = root.querySelector("#pick");
  const opts = st.policies.filter((p) => p !== MAIN);
  if (!opts.includes(challenger)) challenger = opts.includes("fixed_savings") ? "fixed_savings" : opts[0];
  if (shownPolicies !== opts.join(",")) { pick.innerHTML = opts.map((p) => `<option value="${esc(p)}">${esc(p)}</option>`).join(""); shownPolicies = opts.join(","); }
  pick.value = challenger;
  if (!challenger) return;
  strip(st);
  const tot = (p) => (act[p] || []).slice(-MAX_BARS).reduce((m, x) => Math.max(m, x.screen_skipped + x.rescored_kept + x.moved + x.rescued), 0);
  const ymax = Math.max(tot(MAIN), tot(challenger));
  const top = root.querySelector("#lane-top"), bot = root.querySelector("#lane-bot");
  if (bot.dataset.p !== challenger) { bot.innerHTML = ""; bot.dataset.p = challenger; }
  lane(top, MAIN, st, s.events, ymax, true);
  lane(bot, challenger, st, s.events, ymax, false);
}
