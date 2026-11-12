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
