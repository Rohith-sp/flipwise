// Test results: the 12 Nov test run, mean over 16 replicates, from GET /results.
import * as api from "./api.js";
import { esc, int, num, chart, colourOf } from "./util.js";

let root = null, data = null, err = null;
export const title = ["Test results", "The one-shot test run, shown as a reference next to the live session"];

export function mount(view) {
  root = view;
  view.innerHTML = `<p class="small fw-muted" id="note">kgCO2 from the 12 Nov test run; relative units. Mean over the test replicates.</p>
  <section class="fw-card"><div class="tw" id="tbl"><p class="fw-muted">Loading</p></div></section>
  <div class="fw-grid g11 fw-section" id="bars"></div>`;
  api.getResults().then((d) => { data = d; err = null; update(); }).catch((e) => { err = e.message; update(); });
}
export function unmount() { root = null; }

const METRICS = [["kg_co2", "kgCO2 (relative units)", "kg"], ["miss_rate", "Deadline miss rate", ""], ["stage2_calls", "Full re-scorings per replicate", ""], ["moves", "Moves per replicate", ""]];

export function update() {
  if (!root) return;
  if (err) { root.querySelector("#tbl").innerHTML = `<p class="err" role="alert">${esc(err)}</p>`; return; }
  if (!data) return;
  const pols = Object.entries(data.policies);
  const reps = pols.length ? pols[0][1].replicates : 0;
  root.querySelector("#note").textContent = `kgCO2 from the 12 Nov test run; relative units. Mean over ${reps} test replicates.`;
  root.querySelector("#tbl").innerHTML = `<table class="fw-t"><thead><tr><th>Policy</th>${METRICS.map((m) => `<th>${m[1]}</th>`).join("")}</tr></thead><tbody>` +
    pols.map(([p, r]) => `<tr class="${p === "decision_flip" ? "hl" : ""}"><td><i class="pdot" style="background:${colourOf(p)}"></i>${esc(p)}</td>${METRICS.map((m) => `<td>${r[m[0]] == null ? "--" : m[0] === "miss_rate" ? (r[m[0]] * 100).toFixed(2) + "%" : m[0] === "kg_co2" ? num(r[m[0]], 1) : int(r[m[0]])}</td>`).join("")}</tr>`).join("") + "</tbody></table>";
  const host = root.querySelector("#bars");
  if (!host.children.length) host.innerHTML = METRICS.map((m, i) => `<section class="fw-card"><h2>${m[1]}</h2><div class="ch-sm" style="height:230px" id="rb${i}" role="img" aria-label="${m[1]} per policy"></div></section>`).join("");
  METRICS.forEach((m, i) => chart(`rb${i}`, root.querySelector(`#rb${i}`)).setOption({
    animation: false, tooltip: { trigger: "axis", axisPointer: { type: "shadow" } }, grid: { left: 56, right: 12, top: 10, bottom: 28 },
    xAxis: { type: "category", data: pols.map(([p]) => p), axisLabel: { color: "#374151", fontSize: 11, interval: 0, rotate: 20 } },
    yAxis: { type: "value", axisLabel: { color: "#4B5563" }, splitLine: { lineStyle: { color: "#EEF0F3" } } },
    series: [{ type: "bar", barMaxWidth: 36, data: pols.map(([p, r]) => ({ value: r[m[0]], itemStyle: { color: colourOf(p) } })) }] }, true));
}
