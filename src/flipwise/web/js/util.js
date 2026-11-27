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

export const colourOf = (policy) => POLICY_COLOURS[policy] || "#4B5563";

const KIND_CLASSES = new Set(["MOVE", "KEEP", "SCREEN_FAIL", "PLACE", "RESCUE", "FALLBACK", "RESCUE_NOOP", "RUNNING", "COMPLETED"]);
export const kindClass = (kind) => { const k = String(kind || "OTHER"); return KIND_CLASSES.has(k) ? k : k.startsWith("RESCUE") ? "RESCUE" : "OTHER"; };
export const badge = (kind) => `<span class="badge-k k-${kindClass(kind)}">${esc(String(kind || "OTHER").replace("_", " "))}</span>`;

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

export const gpuLabel = (g) => (g == null ? "?" : g === 0 ? "0" : g < 1 ? String(+g.toFixed(2)).replace(/^0/, "") : String(Math.round(g)));
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

// Actual carbon so far (solid) and the forecast ahead (dashed) for every region, as on the
// Overview and Scheduler pages. `hist` is one policy's history; `st` is /status.
export function carbonChart(id, el, st, hist, grid) {
  const nowS = st.clock.sim_time_s, slot0 = Math.floor(nowS / 1800) * 1800, sers = [];
  st.carbon.forEach((c, i) => {
    const col = REGION_COLOURS[i % 3];
    sers.push({ name: REGION_SHORT[i] + " actual", type: "line", showSymbol: false, connectNulls: true, lineStyle: { color: col, width: 2 }, itemStyle: { color: col },
      data: hist.map((p) => [p.t, p.dcs[i] ? p.dcs[i].actual_g_per_kwh : null]),
      markLine: i === 0 ? { symbol: "none", silent: true, lineStyle: { color: "#111827", type: "dashed" }, label: { formatter: "now", color: "#111827" }, data: [{ xAxis: nowS }] } : undefined });
    sers.push({ name: REGION_SHORT[i] + " forecast", type: "line", showSymbol: false, lineStyle: { color: col, width: 2, type: "dashed" }, itemStyle: { color: col },
      data: (c.forecast_next_6h || []).map((v, k) => [slot0 + k * 1800, v]) });
  });
  chart(id, el).setOption({
    animation: false, tooltip: { trigger: "axis", valueFormatter: (v) => (v == null ? "--" : Number(v).toFixed(0) + " g/kWh"), axisPointer: { type: "line" } },
    grid, legend: { show: false },
    xAxis: { type: "value", min: "dataMin", max: "dataMax", axisLabel: { formatter: (v) => istClock(v), color: "#4B5563" } },
    yAxis: { type: "value", name: "g/kWh", scale: true, axisLabel: { color: "#4B5563" }, splitLine: { lineStyle: { color: "#EEF0F3" } } },
    series: sers }, true);
}

// A <select> of policy names, rebuilt only when the list changes; returns the value to use.
export function policySelect(sel, names, current) {
  const key = names.join(",");
  if (sel.dataset.names !== key) { sel.innerHTML = names.map((p) => `<option value="${esc(p)}">${esc(p)}</option>`).join(""); sel.dataset.names = key; }
  const value = names.includes(current) ? current : names[0];
  sel.value = value;
  return value;
}

// Each remote datacentre serves its own page; the published port is 8101 + dc_id (local and Docker).
export const dcPageUrl = (dcId) => `${location.protocol}//${location.hostname}:${8101 + dcId}/?scheduler=${encodeURIComponent(location.origin)}`;
export const dcLink = (d) => (d.remote
  ? `<a class="small" href="${dcPageUrl(d.dc_id)}" target="_blank" rel="noopener">Open its own page</a>` : "");

// ---- plain-words helpers: jargon tooltips and the "why" explanation -----------------------------
export const GLOSSARY = {
  screen: "A cheap check that bounds the best possible saving. If even that bound cannot clear the gate, the expensive re-score is skipped.",
  gate: "The minimum saving (g_min) a move must beat, plus a noise margin for forecast error. Stops jobs hopping for tiny gains.",
  "re-score": "Re-running the full planner on the latest forecast to compare the current plan against the best alternative.",
  "S_a": "Estimated emissions (kg CO2) of the current plan, using today's forecast.",
  "S_b": "Estimated emissions (kg CO2) of the best alternative plan.",
  "g_min": "Smallest saving worth acting on (the gate floor).",
  "w_ab": "Forecast uncertainty on the saving, in kg CO2. Multiplied by theta to form the noise margin.",
  theta: "How many noise-margin widths the saving must clear. Larger means more cautious.",
};
export const tip = (term, label) => `<abbr class="tip" tabindex="0" title="${esc(GLOSSARY[term] || "")}">${label || esc(term)}</abbr>`;

const siteSlot = (d) => {
  const from = shortRegion(d.from), to = shortRegion(d.to);
  const at = d.to_slot ? ` from ${esc(timeOnly(d.to_slot))} IST` : "";
  return d.from && d.to && d.from !== d.to ? `${esc(from)} &rarr; ${esc(to)}${at}` : esc(to === "?" ? from : to) + at;
};

// Plain-words headline for one decision, e.g. "Moved: saves 1.8 kg (needed 1.2 kg = ...)".
export function whyHeadline(d) {
  const saves = d.S_a_kg != null && d.S_b_kg != null ? d.S_a_kg - d.S_b_kg : null, need = needed(d);
  const bar = need == null ? "" : `needed ${num(need, 3)} kg = ${num(d.g_min_kg, 3)} kg gate + noise margin`;
  switch (d.kind) {
    case "MOVE": return `Moved: saves ${num(saves, 3)} kg${bar ? ` (${bar})` : ""}`;
    case "KEEP": return `Kept: best alternative saves only ${num(saves, 3)} kg${bar ? ` (${bar})` : ""}`;
    case "SCREEN_FAIL": return `Not re-scored: the cheap screen ruled out any move${d.LB_kg != null ? ` (best possible saving bound ${num(d.LB_kg, 3)} kg)` : ""}`;
    case "PLACE": return `Placed: estimated ${num(d.S_b_kg, 3)} kg`;
    default: return `${String(d.kind).replace("_", " ")}${d.reason ? ": " + d.reason : ""}`;
  }
}

// Card body: old vs new site and slot, the numbers, and the reason code.
export function whyCard(d, policy) {
  const saves = d.S_a_kg != null && d.S_b_kg != null ? d.S_a_kg - d.S_b_kg : null, need = needed(d);
  const row = (l, v) => `<div class="why-row"><span class="why-l">${l}</span><span>${v}</span></div>`;
  return `<div class="why-head">${badge(d.kind)}<b>${esc(d.job_id)}</b><span class="fw-muted small">${esc(policy || "")} &middot; ${esc(timeOnly(d.time))} IST</span></div>
    <p class="why-line">${esc(whyHeadline(d))}</p>
    ${row("Old plan", d.from ? esc(shortRegion(d.from)) : "none yet")}
    ${row("New plan", d.to ? siteSlot(d) : "unchanged")}
    ${row(tip("S_a", "Current plan (S_a)"), d.S_a_kg == null ? "--" : `${num(d.S_a_kg, 3)} kg CO2`)}
    ${row(tip("S_b", "Best alternative (S_b)"), d.S_b_kg == null ? "--" : `${num(d.S_b_kg, 3)} kg CO2`)}
    ${row("Saving", saves == null ? "--" : `${num(saves, 3)} kg CO2`)}
    ${row(tip("gate", "Gate") + " " + tip("g_min", "(g_min)"), d.g_min_kg == null ? "--" : `${num(d.g_min_kg, 3)} kg`)}
    ${row(tip("theta", "theta") + " &times; " + tip("w_ab", "w_ab"), d.w_ab_kg == null ? "--" : `${num(d.theta, 2)} &times; ${num(d.w_ab_kg, 3)} = ${num(d.theta * d.w_ab_kg, 3)} kg`)}
    ${row("Needed to move", need == null ? "--" : `${num(need, 3)} kg`)}
    ${row("Reason code", `<code>${esc(d.reason || d.kind)}</code>`)}`;
}
