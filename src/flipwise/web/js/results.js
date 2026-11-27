// Test results: the 12 Nov test run, mean over 16 replicates, from GET /results.
import * as api from "./api.js";
import { esc, int, num, chart, colourOf, dot, more, onMore, isOpen } from "./util.js";

let root = null, data = null, err = null;
export const title = ["Test results", "The one-shot test run (three sites), shown as a reference next to the live session"];

const METRICS = [["kg_co2_measured", "kgCO2, measured (lower)", "kg"], ["kg_co2_nameplate", "kgCO2, nameplate (upper)", "kg"], ["miss_rate", "Deadline miss rate", ""], ["stage2_calls", "Full re-scorings per replicate", ""], ["moves", "Moves per replicate", ""]];

export function mount(view) {
  root = view;
  view.innerHTML = `<p class="lede" id="note">Loading the frozen test results...</p>
  <section class="fw-card"><h2>Full re-scorings per replicate</h2><p class="sub">The work each policy did on the held-out test weeks. Fewer is cheaper.</p>
    <div class="chart-lg" id="rb-main" role="img" aria-label="Full re-scorings per policy"></div></section>
  <section class="fw-card fw-section"><h2>Every measure</h2><div class="tw" id="tbl"><p class="fw-muted">Loading</p></div></section>
  ${more("r-more", "Show more: one chart per measure", `<div class="fw-grid g11" id="bars"></div>`)}`;
  onMore(view, "r-more", () => update());
  api.getResults().then((d) => { data = d; err = null; update(); }).catch((e) => { err = e.message; update(); });
}
export function unmount() { root = null; }

function bars(id, el, pols, key) {
  chart(id, el).setOption({
    animation: false, tooltip: { trigger: "axis", axisPointer: { type: "shadow" } }, grid: { left: 64, right: 16, top: 12, bottom: 32 },
    xAxis: { type: "category", data: pols.map(([p]) => p), axisLabel: { color: "#334155", fontSize: 12, interval: 0 } },
    yAxis: { type: "value", axisLabel: { color: "#64748B" }, splitLine: { lineStyle: { color: "#EEF2F6" } } },
    series: [{ type: "bar", barMaxWidth: 44, data: pols.map(([p, r]) => ({ value: r[key], itemStyle: { color: colourOf(p) } })) }] }, true);
}

export function update() {
  if (!root) return;
  if (err) { root.querySelector("#tbl").innerHTML = `<p class="err" role="alert">${esc(err)}</p>`; return; }
  if (!data) return;
  const pols = Object.entries(data.policies);
  const reps = pols.length ? pols[0][1].replicates : 0;
  root.querySelector("#note").textContent = `Test set (${reps} replicates, the three-site setup), run once on 12 Nov and never tuned on. kgCO2 is a range: measured power (lower) to datasheet power (upper). Mean per replicate.`;
  root.querySelector("#tbl").innerHTML = `<table class="fw-t"><thead><tr><th>Policy</th>${METRICS.map((m) => `<th>${m[1]}</th>`).join("")}</tr></thead><tbody>` +
    pols.map(([p, r]) => `<tr class="${p === "decision_flip" ? "hl" : ""}"><td>${dot(p)}${esc(p)}</td>${METRICS.map((m) => `<td>${r[m[0]] == null ? "--" : m[0] === "miss_rate" ? (r[m[0]] * 100).toFixed(2) + "%" : m[0].startsWith("kg_co2") ? num(r[m[0]], 1) : int(r[m[0]])}</td>`).join("")}</tr>`).join("") + "</tbody></table>";
  bars("rb-main", root.querySelector("#rb-main"), pols, "stage2_calls");
  if (!isOpen(root, "r-more")) return;
  const host = root.querySelector("#bars");
  if (!host.children.length) host.innerHTML = METRICS.map((m, i) => `<section class="fw-card"><h2>${m[1]}</h2><div class="chart" id="rb${i}" role="img" aria-label="${m[1]} per policy"></div></section>`).join("");
  METRICS.forEach((m, i) => bars(`rb${i}`, root.querySelector(`#rb${i}`), pols, m[0]));
}
