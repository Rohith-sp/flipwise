// App shell: hash routing, header controls, polling, event stream, toasts.
import * as api from "./api.js";
import * as overview from "./overview.js";
import * as jobs from "./jobs.js";
import { disposeCharts, esc, shortRegion, timeOnly } from "./util.js";

const STUBS = { scheduler: "Scheduler", datacentres: "Datacentres", compare: "Policy comparison", scale: "Scale projection", results: "Test results", architecture: "Architecture" };
const SPEEDS = [[60, "1 min/s"], [300, "5 min/s"], [1800, "30 min/s"], [7200, "2 h/s"]];
const state = { status: null, clock: null, health: null, dcs: [null, null, null], history: {}, lastT: null, connected: false };
let page = null, skipping = false, polling = false;
const $ = (id) => document.getElementById(id);

export function toast(html) {
  const t = document.createElement("div");
  t.className = "toast-i"; t.innerHTML = html; $("toasts").appendChild(t);
  setTimeout(() => t.remove(), 7000);
}

// ---- routing ------------------------------------------------------------------------------------
function route() {
  const name = (location.hash.replace(/^#\//, "") || "overview").split("?")[0];
  if (page && page.unmount) page.unmount();
  disposeCharts();
  document.querySelectorAll(".fw-nav").forEach((a) => {
    const on = a.dataset.route === name; a.classList.toggle("active", on);
    if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  const view = $("view");
  if (name === "overview") page = overview;
  else if (name === "jobs") page = jobs;
  else if (STUBS[name]) {
    page = { title: [STUBS[name], "Coming in stage 4"], mount(v) { v.innerHTML = `<section class="fw-card empty"><h2>${esc(STUBS[name])}</h2><p class="fw-muted">Coming in stage 4</p></section>`; }, update() {} };
  } else { location.hash = "#/overview"; return; }
  $("page-title").textContent = page.title[0]; $("page-sub").textContent = page.title[1];
  document.title = `${page.title[0]} - Flipwise live`;
  view.innerHTML = ""; page.mount(view, { toast });
  render();
}

function render() { if (page && page.update) page.update(state); }

// ---- header -----------------------------------------------------------------------------------
function header() {
  const c = state.clock;
  if (c) {
    $("clock").textContent = String(c.sim_time).replace(" IST", " IST");
    const paused = c.paused;
    $("ico-pause").hidden = paused; $("ico-play").hidden = !paused;
    $("play-label").textContent = paused ? "Play" : "Pause";
    $("btn-play").setAttribute("aria-label", paused ? "Resume simulation" : "Pause simulation");
    document.querySelectorAll("#speed-seg button").forEach((b) => b.classList.toggle("on", Math.abs(+b.dataset.speed - c.speed) < 1e-9));
  }
  const pill = $("conn");
  pill.className = "fw-pill " + (state.connected ? "ok" : "bad");
  const st = state.status;
  $("conn-text").textContent = !state.connected ? "Disconnected" : st && st.remote_policy ? "Live · services" : "Live";
  if (st) {
    const n = st.policies.length;
    $("scenario-text").innerHTML = `${n} policies side by side<br>${esc(st.clock.start)} to<br>${esc(st.clock.end)}`;
  }
  document.querySelectorAll("#skip-seg button").forEach((b) => (b.disabled = skipping));
  $("skip-busy").hidden = !skipping;
}

async function control(body) {
  try { state.clock = await api.postControl(body); header(); await poll(true); }
  catch (e) { toast(esc(e.message)); }
}

function wireHeader() {
  $("speed-seg").innerHTML = SPEEDS.map(([v, l]) => `<button type="button" data-speed="${v}">${l}</button>`).join("");
  $("speed-seg").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) control({ speed: +b.dataset.speed }); });
  $("btn-play").addEventListener("click", () => control({ paused: !(state.clock && state.clock.paused) }));
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
async function watchCompletions() {
  for (const id of (state.status && state.status.user_jobs) || []) {
    if (completed.has(id)) continue;
    try {
      const j = await api.getJob(id), v = j.by_policy.decision_flip;
      if (v && v.state === "COMPLETED") { completed.add(id); toast(`${esc(id)} completed${v.kg_co2 != null ? `: ${v.kg_co2.toFixed(3)} kg CO2` : ""}${v.datacentre ? ` in ${esc(shortRegion(v.datacentre))}` : ""}`); }
    } catch (e) { /* retried next poll */ }
  }
}

async function poll(force) {
  if ((document.hidden && !force) || polling) return;
  polling = true;
  try {
    const wantDcs = location.hash.startsWith("#/overview") || location.hash === "";
    const [st, clk] = await Promise.all([api.getStatus(), api.getClock()]);
    state.status = st; state.clock = clk; state.connected = true;
    const jobs_ = [api.getHistory(state.lastT).then((h) => {
      for (const [p, rows] of Object.entries(h.policies)) {
        (state.history[p] = state.history[p] || []).push(...rows);
        if (rows.length) state.lastT = Math.max(state.lastT ?? 0, rows[rows.length - 1].t);
      }
    }), api.getHealth().then((h) => (state.health = h))];
    if (wantDcs) st.carbon.forEach((_, i) => jobs_.push(api.getDc(i).then((d) => (state.dcs[i] = d))));
    await Promise.all(jobs_);
    header(); render(); watchCompletions();
  } catch (e) { state.connected = false; header(); }
  finally { polling = false; }
}

// ---- event stream -----------------------------------------------------------------------------
function stream() {
  const es = new EventSource("/stream");
  es.addEventListener("decision", (ev) => {
    let d; try { d = JSON.parse(ev.data); } catch (e) { return; }
    if (d.policy === "decision_flip" && String(d.job_id).startsWith("USER-") && d.kind === "MOVE")
      toast(`${esc(d.job_id)} moved ${esc(shortRegion(d.from))} → ${esc(shortRegion(d.to))} at ${esc(timeOnly(d.time))}`);
  });
  es.onerror = () => { /* EventSource reconnects by itself; the poll drives the pill */ };
}

wireHeader();
window.addEventListener("hashchange", route);
document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
route();
poll();
setInterval(poll, 1500);
stream();
