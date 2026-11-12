// Policy comparison: all policies over time, a leaderboard and the headline claim.
import { esc, int, num, chart, colourOf, tsToMs, axisTime } from "./util.js";

let root = null;
export const title = ["Policy comparison", "Every policy on the same jobs and carbon, measured live"];

export function mount(view) {
  root = view;
  view.innerHTML = `<div class="callout" id="call" role="status">Waiting for data</div>
  <div class="rlegend" id="leg" aria-label="Policy colours"></div>
  <div class="fw-grid g3">
    <section class="fw-card"><h2>Cumulative CO2</h2><p class="sub">kg, completed jobs</p><div class="chart" id="c1" role="img" aria-label="Cumulative CO2 per policy"></div></section>
    <section class="fw-card"><h2>Moves</h2><p class="sub">plan changes accepted, cumulative</p><div class="chart" id="c2" role="img" aria-label="Cumulative moves per policy"></div></section>
    <section class="fw-card"><h2>Full re-scores</h2><p class="sub">expensive checks run, cumulative</p><div class="chart" id="c3" role="img" aria-label="Cumulative full re-scores per policy"></div></section>
  </div>
  <section class="fw-card fw-section"><h2>Leaderboard</h2><p class="sub">Measured so far in this session; sorted by CO2</p><div class="tw" id="lb"></div></section>`;
}
export function unmount() { root = null; }

function lines(id, el, s, f) {
  chart(id, el).setOption({
    animation: false, tooltip: { trigger: "axis" }, legend: { show: false },
    grid: { left: 48, right: 12, top: 10, bottom: 26 }, xAxis: axisTime,
    yAxis: { type: "value", min: 0, axisLabel: { color: "#4B5563" }, splitLine: { lineStyle: { color: "#EEF0F3" } } },
    series: s.status.policies.map((p) => ({ name: p, type: "line", showSymbol: false, lineStyle: { width: p === "decision_flip" ? 3 : 2, color: colourOf(p) }, itemStyle: { color: colourOf(p) }, data: tsToMs(s.history[p] || [], f) })) }, true);
}

export function update(s) {
  if (!root || !s || !s.status) return;
  const st = s.status, cmp = st.compare, flip = cmp.decision_flip, ref = cmp.fixed_savings;
  root.querySelector("#leg").innerHTML = st.policies.map((p) => `<span><i class="sw" style="background:${colourOf(p)}"></i>${esc(p)}</span>`).join("");
  lines("cp1", root.querySelector("#c1"), s, (p) => p.kg_co2);
  lines("cp2", root.querySelector("#c2"), s, (p) => p.moves);
  lines("cp3", root.querySelector("#c3"), s, (p) => p.full_rescores);
  if (flip && ref && ref.full_rescores > 0) {
    const fewer = ((ref.full_rescores - flip.full_rescores) / ref.full_rescores) * 100;
    const dco2 = ref.kg_co2_so_far ? ((flip.kg_co2_so_far - ref.kg_co2_so_far) / ref.kg_co2_so_far) * 100 : 0;
    const carbon = Math.abs(dco2) < 1 ? "Same carbon" : dco2 < 0 ? `${Math.abs(dco2).toFixed(1)}% less carbon` : `${dco2.toFixed(1)}% more carbon`;
    root.querySelector("#call").textContent = `${carbon}, ${fewer.toFixed(0)}% fewer re-scores than fixed_savings (decision_flip ${int(flip.full_rescores)} vs ${int(ref.full_rescores)}, measured so far).`;
  } else root.querySelector("#call").textContent = "The comparison with fixed_savings appears once it has re-scored something.";
  const rows = Object.entries(cmp).sort((a, b) => a[1].kg_co2_so_far - b[1].kg_co2_so_far);
  root.querySelector("#lb").innerHTML = `<table class="fw-t"><thead><tr><th>#</th><th>Policy</th><th>CO2 so far (kg)</th><th>Deadline misses</th><th>Moves</th><th>Full re-scores</th><th>Jobs completed</th></tr></thead><tbody>` +
    rows.map(([n, c], i) => `<tr class="${n === "decision_flip" ? "hl" : ""}"><td>${i + 1}</td><td><i class="pdot" style="background:${colourOf(n)}"></i>${esc(n)}</td><td>${num(c.kg_co2_so_far, 2)}</td><td>${int(c.deadline_misses)}</td><td>${int(c.moves)}</td><td>${int(c.full_rescores)}</td><td>${int(c.jobs_completed)}</td></tr>`).join("") + "</tbody></table>";
}
