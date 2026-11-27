// Guided demo: a dismissible Next/Back card that walks a presenter through the pages in order.
const STEPS = [
  ["overview", "Overview", "Datacentres across India's grids (Delhi, Mumbai, Chennai, Kolkata, Hyderabad in the five-site demo) run the same jobs. Two policies are compared: decision_flip and the one picked in the sidebar. The three tiles show carbon, work and moves; the chart shows the work gap growing."],
  ["h2h", "Head-to-head", "At every forecast update, how many jobs each policy fully re-scores. decision_flip's cheap screen skips most of them. 'Show more' lists every policy and the jobs at each site."],
  ["scheduler", "Scheduler", "The carbon forecast the planner sees for each site, and the 'Why this job moved' card: the saving, the bar it had to clear, and the reason. Click any row in the feed."],
  ["datacentres", "Datacentres", "One site at a time: how busy it is, its queue, and the grid carbon it sits on. Use the tabs to switch sites."],
  ["jobs", "Job tracker", "Submit your own job. Each policy handles it differently; click a chip to see the numbers behind each decision."],
  ["scale", "Scale projection", "How the savings and the work saved by the cheap screen grow as the load grows."],
  ["results", "Test results", "Frozen results on the held-out test period (three sites). The thresholds were never tuned on it."],
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
