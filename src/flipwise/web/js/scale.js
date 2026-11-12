// Scale projection: per-job rates scaled to a bigger workload. Every number is tagged.
import { esc, int, num, FLIP_REF, colourOf } from "./util.js";

let root = null, base = "fixed_savings", source = "ref", pos = 400;
export const title = ["Scale projection", "What the per-job savings add up to at larger workloads"];
const TRACE_JOBS = 730000;
const jobsAt = (p) => Math.round(10 ** (4 + (p / 1000) * 3));
const tag = (k) => `<span class="tag tag-${k[0]}">${k}</span>`;
const hum = (n) => (n >= 1e6 ? (n / 1e6).toFixed(1) + " million" : n >= 1e3 ? Math.round(n / 1e3).toLocaleString("en-US") + " thousand" : String(Math.round(n)));

export function mount(view) {
  root = view;
  view.innerHTML = `
  <section class="fw-card"><h2>Per-job rates</h2><p class="sub">Measured: this live session, totals divided by jobs arrived. Reference: 16 test replicates, 144,412 jobs (D57).</p><div class="tw" id="rates"></div></section>
  <section class="fw-card fw-section"><h2>Projection</h2>
    <div class="form-row" style="margin-bottom:12px">
      <div><label for="sl">Number of jobs <b id="njobs"></b></label><input class="slider" id="sl" type="range" min="0" max="1000" value="${pos}"></div>
      <div><label for="sb">Compared with</label><select id="sb" class="form-select"></select></div>
      <div><label for="ss">Rates from</label><select id="ss" class="form-select"><option value="ref">Test-set reference</option><option value="live">This session (re-scores and moves)</option></select></div>
    </div>
    <div class="strip" id="proj"></div>
    <p class="small fw-muted" style="margin-top:12px">Caveat: the Alibaba trace holds about ${TRACE_JOBS.toLocaleString("en-US")} unique jobs, so any count beyond that is a projection from per-job rates, not something this simulator ran. Scheduler time per job comes from the test set only.</p>
  </section>`;
  const sl = view.querySelector("#sl");
  sl.addEventListener("input", () => { pos = +sl.value; if (window.__fwState) update(window.__fwState); });
  view.querySelector("#sb").addEventListener("change", (e) => { base = e.target.value; update(window.__fwState); });
  view.querySelector("#ss").addEventListener("change", (e) => { source = e.target.value; update(window.__fwState); });
}
export function unmount() { root = null; }

export function update(s) {
  if (!root || !s || !s.status) return;
  window.__fwState = s;
  const cmp = s.status.compare, names = Object.keys(FLIP_REF).filter((p) => p !== "decision_flip");
  const sb = root.querySelector("#sb");
  if (!sb.options.length) sb.innerHTML = names.map((p) => `<option value="${p}">${p}</option>`).join("");
  sb.value = base;
  const live = (p) => { const c = cmp[p]; return c && c.jobs_arrived ? { rescores: c.full_rescores / c.jobs_arrived, moves: c.moves / c.jobs_arrived } : null; };
  root.querySelector("#rates").innerHTML = `<table class="fw-t"><thead><tr><th>Policy</th><th>Re-scores per job</th><th>Moves per job</th><th>Scheduler ms per job</th></tr></thead><tbody>` +
    Object.keys(FLIP_REF).map((p) => { const l = live(p), r = FLIP_REF[p];
      return `<tr class="${p === "decision_flip" ? "hl" : ""}"><td><i class="pdot" style="background:${colourOf(p)}"></i>${esc(p)}</td>
      <td>${l ? num(l.rescores, 3) : "--"} ${tag("measured")}<br>${r.rescores.toFixed(3)} ${tag("reference")}</td><td>${l ? num(l.moves, 3) : "--"} ${tag("measured")}<br>${r.moves.toFixed(3)} ${tag("reference")}</td>
      <td>${r.ms.toFixed(1)} ${tag("reference")}</td></tr>`; }).join("") + "</tbody></table>";
  const n = jobsAt(pos);
  root.querySelector("#njobs").textContent = `${n.toLocaleString("en-US")}${n > TRACE_JOBS ? " (beyond the trace)" : ""}`;
  const pick = (p) => (source === "live" ? live(p) : null) || FLIP_REF[p];
  const a = pick("decision_flip"), b = pick(base), ra = FLIP_REF.decision_flip, rb = FLIP_REF[base];
  const saved = (b.rescores - a.rescores) * n, mv = (b.moves - a.moves) * n, cpu = ((rb.ms - ra.ms) * n) / 3.6e6;
  const tile = (lab, big, note) => `<div><div class="lab">${lab} ${tag("projected")}</div><div class="big">${big}</div><div class="n">${note}</div></div>`;
  root.querySelector("#proj").innerHTML =
    tile("Re-scores saved", hum(saved), `${a.rescores.toFixed(2)} vs ${b.rescores.toFixed(2)} per job &times; ${hum(n)} jobs`) +
    tile("Moves avoided", hum(mv), `${a.moves.toFixed(2)} vs ${b.moves.toFixed(2)} per job`) +
    tile("Scheduler CPU-hours saved", cpu >= 10 ? int(cpu) : cpu.toFixed(1), `${ra.ms} vs ${rb.ms} ms per job (test set)`) +
    tile("Share of re-scores avoided", `${b.rescores ? (((b.rescores - a.rescores) / b.rescores) * 100).toFixed(0) : 0}%`, `against ${esc(base)}`);
}
