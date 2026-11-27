// Guided demo: a dismissible Next/Back card that walks a presenter through the pages in order.
const STEPS = [
  ["overview", "Overview", "Three datacentres in Delhi, Mumbai and Chennai run the same jobs under several re-planning policies. The KPI tiles show emissions, work done and jobs moved so far."],
  ["h2h", "Head-to-head", "Pick two policies and compare them on identical jobs and identical carbon. Only the re-planning rule differs."],
  ["scheduler", "Scheduler", "The forecast the planner sees, and its decisions. Click a row in the feed to open 'Why this job moved'."],
  ["datacentres", "Datacentres", "What each site is running and queueing right now, and the grid carbon it sits on."],
  ["compare", "Policy comparison", "All policies side by side: kg CO2, deadline misses and how much re-planning work each does."],
  ["jobs", "Job tracker", "Submit your own job. Every policy handles it differently; click a chip to see the numbers behind each decision."],
  ["scale", "Scale projection", "How the savings and the work saved by the cheap screen grow as the load grows."],
  ["results", "Test results", "Frozen results on the held-out test period. The thresholds were never tuned on it."],
  ["architecture", "Architecture", "How the scheduler and datacentre services fit together, with identical results in-process or over HTTP."],
];
let i = 0, box = null;
const go = () => { location.hash = "#/" + STEPS[i][0]; draw(); };

function draw() {
  if (!box) return;
  const [, name, text] = STEPS[i];
  box.innerHTML = `<div class="tour-h"><b>Tour ${i + 1} of ${STEPS.length}: ${name}</b><button type="button" class="tour-x" aria-label="Close tour">&times;</button></div>
    <p>${text}</p><div class="tour-b"><button type="button" class="btn btn-sm" data-t="back" ${i === 0 ? "disabled" : ""}>Back</button>
    <button type="button" class="btn btn-primary btn-sm" data-t="next">${i === STEPS.length - 1 ? "Finish" : "Next"}</button></div>`;
}

export function close() { if (box) { box.remove(); box = null; } }
export function open() {
  close(); i = 0;
  box = document.createElement("aside");
  box.className = "tour"; box.setAttribute("role", "dialog"); box.setAttribute("aria-label", "Guided demo");
  box.addEventListener("click", (e) => {
    if (e.target.closest(".tour-x")) return close();
    const b = e.target.closest("[data-t]"); if (!b) return;
    if (b.dataset.t === "back" && i > 0) i--;
    else if (b.dataset.t === "next") { if (i === STEPS.length - 1) return close(); i++; }
    go();
  });
  document.body.appendChild(box); go();
}
document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
