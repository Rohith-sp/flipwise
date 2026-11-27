// App shell: hash routing, header controls, polling, event stream, toasts.
// Calm by design: the page re-renders once per poll (every 2 s), never per stream event, and the
// sidebar picks the one policy compared with decision_flip on every page.
import * as api from "./api.js";
import * as overview from "./overview.js";
import * as jobs from "./jobs.js";
import * as h2h from "./h2h.js";
import * as scheduler from "./scheduler.js";
import * as datacentres from "./datacentres.js";
import * as scale from "./scale.js";
import * as results from "./results.js";
import * as architecture from "./architecture.js";
import * as tour from "./tour.js";
import { disposeCharts, esc, shortRegion, timeOnly, MAIN, colourOf, sitesOf } from "./util.js";

const PAGES = { overview, h2h, scheduler, datacentres, jobs, scale, results, architecture };
const SPEEDS = [[300, "5 min/s"], [900, "15 min/s"], [1800, "30 min/s"], [3600, "1 h/s"]];
const POLL_MS = 2000;
const state = { status: null, clock: null, health: null, history: {}, lastT: null, connected: false, events: {}, replicate: null, pair: [MAIN, "fixed_savings"] };
let page = null, skipping = false, polling = false;
const $ = (id) => document.getElementById(id);
window.__fwState = state; // one shared object: pages read it from their own event handlers

try { const c = localStorage.getItem("fw-challenger"); if (c) state.pair[1] = c; } catch (e) { /* no storage */ }

export function toast(html) {
  const t = document.createElement("div");
  t.className = "toast-i"; t.innerHTML = html; $("toasts").appendChild(t);
  setTimeout(() => t.remove(), 6000);
}

// ---- routing ------------------------------------------------------------------------------------
const subtitle = () => (typeof page.title[1] === "function" ? page.title[1](state) : page.title[1]);
function route() {
  const name = (location.hash.replace(/^#\//, "") || "overview").split("?")[0];
  if (page && page.unmount) page.unmount();
  disposeCharts();
  document.querySelectorAll(".fw-nav").forEach((a) => {
    const on = a.dataset.route === name; a.classList.toggle("active", on);
    if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  const view = $("view");
  if (PAGES[name]) page = PAGES[name];
  else { location.hash = "#/overview"; return; }
  $("page-title").textContent = page.title[0]; $("page-sub").textContent = subtitle();
  document.title = `${page.title[0]} - Flipwise live`;
  view.innerHTML = ""; page.mount(view, { toast });
  render(); loadPage();
}

let loadBusy = false;
async function loadPage() { // pages that need their own endpoints fetch them here, then render
  if (!page || !page.load || loadBusy) return;
  loadBusy = true;
  const mine = page;
  try { await mine.load(state); } catch (e) { /* the next poll retries */ } finally { loadBusy = false; }
  if (mine === page) render();
}

function render() { if (page && page.update) page.update(state); }

// ---- header and sidebar ---------------------------------------------------------------------------
function header() {
  const c = state.clock;
  if (c) {
    $("clock").textContent = c.sim_time;
    const paused = c.paused;
    $("ico-pause").hidden = paused; $("ico-play").hidden = !paused;
    $("play-label").textContent = paused ? "Play" : "Pause";
    $("btn-play").classList.toggle("paused", paused);
    $("btn-play").setAttribute("aria-label", paused ? "Resume simulation" : "Pause simulation");
    document.querySelectorAll("#speed-seg button").forEach((b) => b.classList.toggle("on", Math.abs(+b.dataset.speed - c.speed) < 1e-9));
  }
  const pill = $("conn");
  pill.className = "fw-pill " + (state.connected ? "ok" : "bad");
  const st = state.status;
  $("conn-text").textContent = !state.connected ? "Disconnected" : st && st.remote_policy ? "Live · services" : "Live";
  if (st) {
    const n = sitesOf(st).length, rep = st.clock.replicate;
    $("scenario-text").innerHTML = `${n} sites: ${esc(sitesOf(st).map((s) => s.short).join(", "))}<br>${esc(st.clock.start)} to<br>${esc(st.clock.end)}` +
      (rep ? `<br><b>Replicate ${rep.index} of ${rep.total}</b><br>${esc(rep.name)}${rep.building ? "<br>building next..." : ""}` : "");
    pairPicker(st);
    if (page) $("page-sub").textContent = subtitle();
  }
  document.querySelectorAll("#skip-seg button").forEach((b) => (b.disabled = skipping));
  $("skip-busy").hidden = !skipping;
}

function pairPicker(st) {
  const opts = st.policies.filter((p) => p !== MAIN), sel = $("pair-pick");
  if (!opts.length) { sel.disabled = true; return; }
  if (!opts.includes(state.pair[1])) state.pair[1] = opts.includes("fixed_savings") ? "fixed_savings" : opts[0];
  if (sel.dataset.names !== opts.join(",")) { sel.innerHTML = opts.map((p) => `<option value="${esc(p)}">${esc(p)}</option>`).join(""); sel.dataset.names = opts.join(","); }
  sel.value = state.pair[1];
  sel.style.borderLeftColor = colourOf(state.pair[1]);
}

async function control(body) {
  try { state.clock = await api.postControl(body); header(); await poll(true); }
  catch (e) { toast(esc(e.message)); }
}

function wireHeader() {
  $("btn-tour").addEventListener("click", () => tour.open());
  $("speed-seg").innerHTML = SPEEDS.map(([v, l]) => `<button type="button" data-speed="${v}">${l}</button>`).join("");
  $("speed-seg").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) control({ speed: +b.dataset.speed }); });
  $("btn-play").addEventListener("click", () => control({ paused: !(state.clock && state.clock.paused) }));
  $("pair-pick").addEventListener("change", (e) => {
    state.pair = [MAIN, e.target.value];
    try { localStorage.setItem("fw-challenger", e.target.value); } catch (err) { /* no storage */ }
    header(); render(); loadPage();
  });
  $("skip-seg").addEventListener("click", async (e) => {
    const b = e.target.closest("button"); if (!b || skipping) return;
    skipping = true; header();
    try { state.clock = await api.postControl({ skip_hours: +b.dataset.skip }); toast(`Skipped ${esc(b.textContent.replace("+", ""))} using the recorded history`); }
    catch (err) { toast(esc(err.message)); }
    finally { skipping = false; header(); poll(true); }
  });
}

// ---- polling ----------------------------------------------------------------------------------
const completed = new Set();
let watching = false;
async function watchCompletions() {
  if (watching) return; // a slow round must not overlap the next poll's, or a toast shows twice
  watching = true;
  try {
    const st = state.status, main = st && (st.policies.includes(MAIN) ? MAIN : st.policies[0]);
    for (const id of (st && st.user_jobs) || []) {
      if (completed.has(id)) continue;
      try {
        const j = await api.getJob(id), v = j.by_policy[main];
        if (v && v.state === "COMPLETED") { completed.add(id); toast(`${esc(id)} completed${v.kg_co2 != null ? `: ${v.kg_co2.toFixed(3)} kg CO2` : ""}${v.datacentre ? ` in ${esc(shortRegion(v.datacentre))}` : ""}`); }
      } catch (e) { /* retried next poll */ }
    }
  } finally { watching = false; }
}

async function poll(force) {
  if ((document.hidden && !force) || polling) return;
  polling = true;
  try {
    const st = await api.getStatus(), clk = st.clock; // /status already carries the clock
    state.status = st; state.clock = clk; state.connected = true;
    await Promise.all([api.getHistory(state.lastT).then((h) => {
      for (const [p, rows] of Object.entries(h.policies)) {
        (state.history[p] = state.history[p] || []).push(...rows);
        if (rows.length) state.lastT = Math.max(state.lastT ?? 0, rows[rows.length - 1].t);
      }
    }), api.getHealth().then((h) => (state.health = h))]);
    const rep = clk.replicate ? clk.replicate.index : null;
    if (state.replicate !== null && rep !== state.replicate) { state.history = {}; state.lastT = null; state.events = {}; seen.clear(); if (rep !== null) toast(`Replicate ${rep} of ${clk.replicate.total} started: ${esc(clk.replicate.name)}`); }
    state.replicate = rep;
    seedEvents(st);
    header(); render(); watchCompletions(); loadPage();
  } catch (e) { state.connected = false; header(); }
  finally { polling = false; }
}

// Every decision seen, per policy, newest last: the stream fills it, /status seeds it.
const seen = new Set();
function addEvent(p, d) {
  const key = `${p}|${d.job_id}|${d.time_s}|${d.kind}`;
  if (seen.has(key)) return;
  seen.add(key);
  const a = (state.events[p] = state.events[p] || []);
  a.push({ ...d, policy: p });
  if (a.length > 600) a.splice(0, a.length - 600);
  if (seen.size > 20000) seen.clear();
}
function seedEvents(st) {
  for (const [p, ds] of Object.entries(st.recent_decisions || {})) if (!(state.events[p] || []).length) ds.forEach((d) => addEvent(p, d));
}

// ---- event stream -----------------------------------------------------------------------------
// Events only fill the buffer; the next poll draws them, so the screen changes at most every 2 s.
function stream() {
  const es = new EventSource("/stream");
  es.addEventListener("decision", (ev) => {
    let d; try { d = JSON.parse(ev.data); } catch (e) { return; }
    addEvent(d.policy, d);
    if (d.policy === MAIN && String(d.job_id).startsWith("USER-") && d.kind === "MOVE")
      toast(`${esc(d.job_id)} moved ${esc(shortRegion(d.from))} → ${esc(shortRegion(d.to))} at ${esc(timeOnly(d.time))}`);
  });
  es.onerror = () => { /* EventSource reconnects by itself; the poll drives the pill */ };
}

wireHeader();
window.addEventListener("hashchange", route);
document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
route();
poll();
setInterval(poll, POLL_MS);
stream();
