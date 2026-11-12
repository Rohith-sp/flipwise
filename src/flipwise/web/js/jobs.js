import { esc, num, badge, colourOf, shortRegion, timeOnly, needed, explain } from "./util.js";
import { getJob, getJobs, postJob } from "./api.js";

export const title = ["Job tracker", "Submit a job and watch what every policy does with it"];
let root = null, timer = null, selected = null, data = null, chip = null, busy = false;
const STATE_KINDS = new Set(["RUNNING", "COMPLETED"]);

export function mount(view, ctx) {
  root = view; chip = null;
  view.innerHTML = `
  <section class="fw-card"><h2>Submit a job</h2><p class="sub">The same job goes to every policy at the current simulated moment</p>
    <form id="jf" novalidate><div class="form-row">
      <div><label for="f-gpus">GPUs</label><input class="form-control" id="f-gpus" type="number" min="0" step="0.5" value="1"></div>
      <div><label for="f-type">GPU type</label><select class="form-select" id="f-type"><option>V100</option><option>P100</option><option>T4</option><option>MISC</option></select></div>
      <div><label for="f-cpus">CPU cores</label><input class="form-control" id="f-cpus" type="number" min="0" step="1" value="4"></div>
      <div><label for="f-mem">Memory GB</label><input class="form-control" id="f-mem" type="number" min="0" step="1" value="16"></div>
      <div><label for="f-rt">Runtime h</label><input class="form-control" id="f-rt" type="number" min="0.1" step="0.1" value="2"></div>
      <div><label for="f-dl">Deadline h from now</label><input class="form-control" id="f-dl" type="number" min="0.1" step="0.5" value="8"></div>
      <div><label for="f-ut">GPU utilisation 0-1 (optional)</label><input class="form-control" id="f-ut" type="number" min="0" max="1" step="0.05" placeholder="1"></div>
    </div><div style="margin-top:12px;display:flex;gap:12px;align-items:center">
      <button class="btn btn-primary" type="submit" id="f-go">Submit job</button><span id="f-err" class="err" role="alert"></span></div></form></section>
  <section class="fw-card fw-section"><div style="display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between">
    <div><h2 id="jt">No job submitted yet</h2><p class="sub" style="margin:0">Fill in the form and press Submit to see each policy's decisions.</p></div>
    <div><label for="jsel" class="small fw-muted" style="display:block">Job</label><select class="form-select" id="jsel" disabled><option>none</option></select></div></div>
    <div id="lanes" class="fw-section"></div></section>
  <section class="fw-card fw-section" id="detail"><h2>Select a decision to see the numbers behind it</h2><p class="sub">Click any chip in a lane above.</p></section>`;
  const $ = (id) => view.querySelector(id);
  $("#jf").addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = { gpus: +$("#f-gpus").value, gpu_type: $("#f-type").value, cpus: +$("#f-cpus").value, mem_gb: +$("#f-mem").value,
      runtime_h: +$("#f-rt").value, deadline_h: +$("#f-dl").value };
    if ($("#f-ut").value !== "") body.gpu_util = +$("#f-ut").value;
    $("#f-err").textContent = ""; $("#f-go").disabled = true;
    try {
      const r = await postJob(body);
      selected = r.job_id; chip = null; await refreshList(); await refresh();
      ctx.toast(`${esc(r.job_id)} submitted at ${esc(timeOnly(r.submitted_at))} IST`);
    } catch (err) { $("#f-err").textContent = err.message; } finally { $("#f-go").disabled = false; }
  });
  $("#jsel").addEventListener("change", (e) => { selected = e.target.value; chip = null; refresh(); });
  $("#lanes").addEventListener("click", (e) => {
    const b = e.target.closest("button.chip"); if (!b) return;
    chip = { policy: b.dataset.p, idx: +b.dataset.i }; draw();
  });
  refreshList().then(refresh);
  timer = setInterval(() => { if (!document.hidden) refresh(); }, 2000);
}
export function unmount() { clearInterval(timer); timer = null; root = null; data = null; }
export function update() {}

async function refreshList() {
  if (!root) return;
  try {
    const r = await getJobs(), ids = r.user_jobs || [], sel = root.querySelector("#jsel");
    if (ids.length) { if (!selected || !ids.includes(selected)) selected = ids[ids.length - 1]; }
    sel.disabled = !ids.length;
    sel.innerHTML = ids.length ? ids.map((i) => `<option ${i === selected ? "selected" : ""}>${esc(i)}</option>`).join("") : "<option>none</option>";
  } catch (e) { /* list is best-effort; the next tick retries */ }
}

async function refresh() {
  if (!root || !selected || busy) return;
  busy = true;
  try { data = await getJob(selected); draw(); } catch (e) { /* keep the last view */ } finally { busy = false; }
}

function lane(p, v, i0) {
  const chips = v.decisions.map((d, i) => `<button type="button" class="chip k-${badgeCls(d.kind)}${chip && chip.policy === p && chip.idx === i ? " sel" : ""}" data-p="${esc(p)}" data-i="${i}" aria-label="${esc(d.kind)} at ${esc(timeOnly(d.time))}">${esc(d.kind.replace("_", " "))}<small>${esc(timeOnly(d.time))}</small></button>`);
  if (STATE_KINDS.has(v.state)) chips.push(`<span class="chip k-${v.state}" style="cursor:default">${v.state}<small>${esc(timeOnly(v.state === "COMPLETED" ? v.end : v.start))}</small></span>`);
  else chips.push(`<span class="chip k-OTHER" style="cursor:default">${esc(v.state)}</span>`);
  const done = v.kg_co2 != null;
  return `<div class="lane"><div class="nm"><i class="pdot" style="background:${colourOf(p)}"></i>${esc(p)}<div class="sm">${v.datacentre ? esc(shortRegion(v.datacentre)) : "not placed"}</div></div>
    <div><div class="chips">${chips.join("")}</div><div class="sm" style="margin-top:4px">${v.moves} ${v.moves === 1 ? "move" : "moves"}, ${v.decisions.length} ${v.decisions.length === 1 ? "decision" : "decisions"}${v.deadline_missed ? ", deadline missed" : ""}</div></div>
    <div class="kg">${num(done ? v.kg_co2 : v.estimated_kg, 3)} kg<small>${done ? "measured" : "estimate"}</small></div></div>`;
}
const badgeCls = (k) => (["MOVE", "KEEP", "SCREEN_FAIL", "PLACE", "RESCUE", "FALLBACK", "RESCUE_NOOP"].includes(k) ? k : k.startsWith("RESCUE") ? "RESCUE" : "OTHER");

function draw() {
  if (!root || !data) return;
  root.querySelector("#jt").textContent = `${data.job_id} · one lane per policy`;
  root.querySelector("#lanes").innerHTML = Object.entries(data.by_policy).map(([p, v], i) => lane(p, v, i)).join("");
  const host = root.querySelector("#detail");
  if (!chip || !data.by_policy[chip.policy]) return;
  const d = data.by_policy[chip.policy].decisions[chip.idx];
  if (!d) return;
  const saves = d.S_a_kg != null && d.S_b_kg != null ? d.S_a_kg - d.S_b_kg : null, need = needed(d);
  const box = (l, v, n) => `<div class="dbox"><div class="l">${l}</div><div class="v">${v}</div><div class="n">${n || ""}</div></div>`;
  host.innerHTML = `<div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;align-items:center"><h2><i class="pdot" style="background:${colourOf(chip.policy)}"></i>${esc(chip.policy)} &middot; ${esc(timeOnly(d.time))}</h2>${badge(d.kind)}</div>
    <div class="detail-grid">${box("Current plan S_a", d.S_a_kg == null ? "--" : num(d.S_a_kg, 3) + " kg", d.from ? esc(shortRegion(d.from)) : "")}
    ${box("Best alternative S_b", d.S_b_kg == null ? "--" : num(d.S_b_kg, 3) + " kg", d.to ? esc(shortRegion(d.to)) : "")}
    ${box("Saving S_a - S_b", saves == null ? "--" : num(saves, 3) + " kg", "")}
    ${box("Needed", need == null ? "--" : num(need, 3) + " kg", need == null ? "" : `g_min ${num(d.g_min_kg, 3)} + ${num(d.theta, 2)} &times; w_ab ${num(d.w_ab_kg, 3)}`)}</div>
    <p style="margin:0">${esc(explain(d))}</p>`;
}
