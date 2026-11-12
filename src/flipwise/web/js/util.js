// Shared helpers: escaping, formatting, colours, decision text, chart registry.
export const POLICY_COLOURS = {
  decision_flip: "#1D4ED8", fixed_savings: "#B45309", periodic: "#7C3AED",
  pred_error: "#0F766E", place_once: "#4B5563", fcfs: "#9CA3AF", pig: "#BE185D",
};
export const REGION_COLOURS = ["#1E3A8A", "#C2410C", "#0F766E"];
export const REGION_SHORT = ["Delhi NCR", "Mumbai", "Chennai"];

export const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export const shortRegion = (name) => (name ? String(name).split(" (")[0] : "?");
export const num = (v, d = 2) => (v === null || v === undefined || Number.isNaN(v) ? "--" : Number(v).toFixed(d));
export const int = (v) => (v === null || v === undefined ? "--" : Math.round(v).toLocaleString("en-US"));
export const timeOnly = (ist) => (ist ? String(ist).replace(/^\w+ \d+ \w+ \d+ /, "").replace(" IST", "") : "");

// Unix seconds to "HH:MM" in IST, without relying on the browser's time zone.
export function istClock(t_s) {
  const d = new Date((t_s + 19800) * 1000);
  return d.toISOString().slice(11, 16);
}
export function istDayClock(t_s) {
  const d = new Date((t_s + 19800) * 1000);
  return d.toISOString().slice(5, 10) + " " + d.toISOString().slice(11, 16);
}

export const colourOf = (policy) => POLICY_COLOURS[policy] || "#4B5563";

export function badge(kind) {
  const k = String(kind || "OTHER");
  const cls = ["MOVE", "KEEP", "SCREEN_FAIL", "PLACE", "RESCUE", "FALLBACK", "RESCUE_NOOP", "RUNNING", "COMPLETED"].includes(k)
    ? k : k.startsWith("RESCUE") ? "RESCUE" : "OTHER";
  return `<span class="badge-k k-${cls}">${esc(k.replace("_", " "))}</span>`;
}

export const needed = (d) =>
  d && d.g_min_kg != null && d.w_ab_kg != null && d.theta != null ? d.g_min_kg + d.theta * d.w_ab_kg : null;

export function decisionText(d) {
  const from = shortRegion(d.from), to = shortRegion(d.to);
  const saves = d.S_a_kg != null && d.S_b_kg != null ? d.S_a_kg - d.S_b_kg : null;
  const need = needed(d);
  switch (d.kind) {
    case "MOVE":
      return `${d.job_id}: ${from} → ${to}` + (saves != null ? `, saves ${num(saves, 3)} kg` + (need != null ? ` ≥ needed ${num(need, 3)} kg` : "") : "");
    case "KEEP":
      return `${d.job_id} kept in ${from === "?" ? to : from}` + (saves != null ? `: best alternative saves ${num(saves, 3)} kg` + (need != null ? `, below the ${num(need, 3)} kg needed` : "") : "");
    case "SCREEN_FAIL":
      return `${d.job_id}: screen stopped the check, no alternative can clear the gate` + (d.LB_kg != null ? ` (bound ${num(d.LB_kg, 3)} kg)` : "");
    case "PLACE":
      return `${d.job_id} placed in ${to}` + (d.S_b_kg != null ? `, estimated ${num(d.S_b_kg, 3)} kg` : "");
    default:
      return `${d.job_id}: ${d.reason || d.kind}`;
  }
}

// One-sentence explanation of a decision, built from its numbers.
export function explain(d) {
  const saves = d.S_a_kg != null && d.S_b_kg != null ? d.S_a_kg - d.S_b_kg : null;
  const need = needed(d);
  if (d.kind === "PLACE") return `First placement: the best plan found puts the job in ${shortRegion(d.to)} at an estimated ${num(d.S_b_kg, 3)} kg.`;
  if (saves != null && need != null) {
    const verdict = d.kind === "MOVE"
      ? `the saving clears the bar, so the job moves to ${shortRegion(d.to)}`
      : `the saving does not clear the bar, so the plan stays`;
    return `The best alternative saves ${num(saves, 3)} kg against a required ${num(need, 3)} kg (${num(d.g_min_kg, 3)} kg floor plus ${num(d.theta, 2)} × ${num(d.w_ab_kg, 3)} kg noise margin); ${verdict}.`;
  }
  if (d.kind === "SCREEN_FAIL") return "The cheap screen showed no alternative could beat the current plan by enough, so the full re-score was skipped.";
  return d.reason ? `${d.kind}: ${d.reason}` : `${d.kind} decision.`;
}

// ---- charts: one registry, disposed on route change ------------------------------------------
const charts = new Map();
export function chart(id, container) {
  let c = charts.get(id);
  if (c && c.getDom() !== container) { c.dispose(); c = null; }
  if (!c) { c = window.echarts.init(container, null, { renderer: "canvas" }); charts.set(id, c); }
  return c;
}
export function disposeCharts() { charts.forEach((c) => c.dispose()); charts.clear(); }
window.addEventListener("resize", () => charts.forEach((c) => c.resize()));

// ---- shared pieces for the stage-4 pages ------------------------------------------------------
export const POLICY_RULES = {
  decision_flip: "Cheap screen first; full re-score only if a gain is possible; moves only past a noise margin",
  fixed_savings: "Full re-score of every pending job at every forecast update; moves on a fixed saving",
  periodic: "Re-optimises all pending jobs on a timer, whatever the forecast did",
  pred_error: "Re-plans a job when its plan's forecast inputs drift past an error bound",
  place_once: "Places at arrival, never re-plans (rescue only)",
  fcfs: "Earliest start, ignores carbon",
  pig: "Oracle reference: places with perfect knowledge of the future",
};
export const FLIP_REF = { // 16 test replicates, 144,412 jobs (D57)
  decision_flip: { rescores: 2.220, moves: 0.261, ms: 10.3 },
  fixed_savings: { rescores: 4.824, moves: 0.653, ms: 17.7 },
  periodic: { rescores: 4.808, moves: 0.702, ms: 17.0 },
  pred_error: { rescores: 1.656, moves: 0.457, ms: 9.8 },
};

// The last non-missing value per key, so a chip never flashes "--" for one missing slot.
const lastSeen = new Map();
export function keepLast(key, v) {
  if (v !== null && v !== undefined && !Number.isNaN(v)) lastSeen.set(key, v);
  return lastSeen.has(key) ? lastSeen.get(key) : null;
}

export const gClass = (g) => (g == null ? "" : g < 600 ? "cg-green" : g < 800 ? "cg-amber" : "cg-red");

const gpuLabel = (g) => (g === 0 ? "0" : g < 1 ? String(+g.toFixed(2)).replace(/^0/, "") : String(Math.round(g)));
// Small squares labelled with GPUs: user jobs outlined black, moved jobs get an amber dot.
export function jobChips(box, kind) {
  if (!box || !box.total) return '<span class="fw-muted small">none</span>';
  const chips = box.jobs.map((j) => `<span class="jc jc-${kind}${j.user_job ? " jc-user" : ""}${j.moved ? " jc-moved" : ""}" title="${esc(j.job_id)} · ${j.gpus} GPU${j.user_job ? " · your job" : ""}${j.moved ? " · moved" : ""}">${gpuLabel(j.gpus)}</span>`);
  if (box.total > box.jobs.length) chips.push(`<span class="jc jc-more">+${box.total - box.jobs.length}</span>`);
  return chips.join("");
}

// Same-height line/bar chart option helpers.
export const axisTime = { type: "time", axisLabel: { color: "#4B5563", formatter: (v) => istClock(v / 1000) } };
export const tsToMs = (rows, f) => rows.map((p) => [p.t * 1000, f(p)]);
export const sentenceInt = int;
