// Router, shared helpers, and every page except the live arena (arena.js).
import { lineChart, forest, stacked, bars, hideTip } from './charts.js';

export const POLICIES = ['fcfs', 'place_once', 'periodic', 'pred_error', 'fixed_savings', 'decision_flip', 'pig'];
export const PCOLOR = Object.fromEntries(POLICIES.map(p => [p, getComputedStyle(document.documentElement).getPropertyValue('--p-' + p).trim()]));
export const PDESC = {
  fcfs: 'Carbon-blind: earliest projected start at any datacentre; never deferred, never re-planned.',
  place_once: 'Best estimated emissions at arrival; after that, only rescues when a plan becomes infeasible.',
  periodic: 'Every 30 min, re-scores every waiting job and moves it on any gain.',
  pred_error: "Re-scores a job when its plan's forecast or projected wait drifts by more than 5%; moves on any gain.",
  fixed_savings: 'At every forecast update, re-scores every waiting job; moves it when the gain clears g_min (1%).',
  decision_flip: 'Ours. Stage-1 lower-bound screen, then full re-score only if a move could pay; noise margin θ·w on top of g_min (5%).',
  pig: 'Oracle reference: place_once with true carbon and true runtimes. Not achievable.',
};
export const pname = p => `<span class="pname"><span class="swatch" style="background:${PCOLOR[p]}"></span>${p}</span>`;

export async function api(path, body) {
  const r = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {});
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

const IST = 19800;
const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
export function fmtT(t, withDay = true) {
  const d = new Date((t + IST) * 1000);
  const hm = String(d.getUTCHours()).padStart(2, '0') + ':' + String(d.getUTCMinutes()).padStart(2, '0');
  return withDay ? `${DOW[d.getUTCDay()]} ${d.getUTCDate()} ${MON[d.getUTCMonth()]} ${hm}` : hm;
}
export const fmtH = s => s >= 3600 ? (s / 3600).toFixed(s >= 36000 ? 0 : 1) + ' h' : Math.round(s / 60) + ' min';
export const fmtN = (v, d = 0) => v == null ? '–' : Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (a, b) => (1 - a / b) * 100;

// ---------------------------------------------------------------- router
const pages = {};
const loaded = new Set();
function route() {
  const id = (location.hash || '#overview').slice(1);
  document.querySelectorAll('.page').forEach(p => p.classList.toggle('active', p.id === 'p-' + id));
  document.querySelectorAll('#nav a').forEach(a => { if (a.getAttribute('href') === '#' + id) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  if (!loaded.has(id) && pages[id]) { loaded.add(id); pages[id]().catch(e => console.error(e)); }
  hideTip();
  scrollTo(0, 0);
}
addEventListener('hashchange', route);

let RESULTS = {};
async function results(split) {
  if (!RESULTS[split]) RESULTS[split] = await api('/api/results?split=' + split);
  return RESULTS[split];
}
const pw = (R, against, metric) => R.pairwise.find(r => r.against === against && r.metric === metric);

// ---------------------------------------------------------------- 01 overview
pages.overview = async () => {
  const R = await results('test');
  const T = R.table;
  const vsF = T.decision_flip.delta_kg_co2_pct_vs_fcfs.mean;
  const fewer = pct(T.decision_flip.stage2_calls.mean, T.fixed_savings.stage2_calls.mean);
  const fewerMoves = pct(T.decision_flip.moves.mean, T.fixed_savings.moves.mean);
  const fs = pw(R, 'fixed_savings', 'kg_co2'), po = pw(R, 'place_once', 'kg_co2');
  const pigVs = T.pig.delta_kg_co2_pct_vs_fcfs.mean;
  const ns = r => r.ci95_lo < 0 && r.ci95_hi > 0;
  document.getElementById('ov-tiles').innerHTML = `
    <div class="tile good"><div class="k">CO₂ vs carbon-blind fcfs</div><div class="v">${vsF.toFixed(1)}%</div><div class="d">${fmtN(-pw(R, 'fcfs', 'kg_co2').mean_diff)} kg less per replicate · significant</div></div>
    <div class="tile good"><div class="k">Full re-scorings vs fixed_savings</div><div class="v">−${fewer.toFixed(0)}%</div><div class="d">${fmtN(T.decision_flip.stage2_calls.mean)} vs ${fmtN(T.fixed_savings.stage2_calls.mean)} per replicate</div></div>
    <div class="tile good"><div class="k">Plan changes (moves) vs fixed_savings</div><div class="v">−${fewerMoves.toFixed(0)}%</div><div class="d">${fmtN(T.decision_flip.moves.mean)} vs ${fmtN(T.fixed_savings.moves.mean)} per replicate</div></div>
    <div class="tile neutral"><div class="k">CO₂ vs fixed_savings</div><div class="v">${fs.mean_diff > 0 ? '+' : ''}${fmtN(fs.mean_diff)} kg</div><div class="d">95% CI ${fmtN(fs.ci95_lo)} … ${fmtN(fs.ci95_hi)} · ${ns(fs) ? 'statistically the same' : 'significant'}</div></div>`;
  const rows = ['periodic', 'pred_error', 'fixed_savings', 'decision_flip'].map(p => ({ label: p, color: PCOLOR[p], value: T[p].stage2_calls.mean, metric: 'full re-scorings / replicate' }));
  const box = document.getElementById('ov-work');
  box.insertAdjacentHTML('beforebegin', '<h4 style="margin-top:var(--s3)">Full re-scorings per replicate (test)</h4>');
  bars(box, rows, { fmt: v => fmtN(v) });
  box.insertAdjacentHTML('afterend', `<p class="small" style="margin-top:var(--s2)">Against <code>place_once</code> (never re-plans), decision-flip's CO₂ difference is ${fmtN(po.mean_diff)} kg (CI ${fmtN(po.ci95_lo)} … ${fmtN(po.ci95_hi)}): ${ns(po) ? 'not significant on the test set' : 'significant'}. The oracle reaches ${pigVs.toFixed(1)}% vs fcfs.</p>`);
};

// ---------------------------------------------------------------- 02 how it works
const NODES = {
  trace: ['Job trace', 'trace.py, ingest.py', 'The Alibaba PAI GPU cluster trace (2020): every ML job with its arrival time, user, GPU/CPU/memory request and actual runtime. A 7-day slice is sampled (10%) and replayed. The actual runtime is hidden from every scheduler except the oracle.', [['jobs', '~7,000 per week at 10% sampling'], ['deadline', 'arrival + 4 h + 2 × q90 runtime'], ['capacity', 'sized so offered load ρ = 0.7']]],
  estimates: ['Runtime estimates', 'estimates.py', "Schedulers never know how long a job will run. They get quantiles of the user's past runtimes (q05, q50, q90, q95), fitted only on trace days 0–21 and then frozen; per-class or global quantiles if the user has fewer than 20 past jobs.", [['r_q50', 'used for scores'], ['r_q90', 'used for deadline feasibility'], ['n_min', '20 jobs per user']]],
  forecast: ['Carbon forecasts', 'carbon.py', 'India publishes no regional carbon forecast. We take Indian truth and add real forecast errors from the GB national forecaster (NESO), matched by lead time, so the forecasts have realistic error size and structure. A new vintage arrives roughly every 30 minutes and is the only carbon signal schedulers see.', [['α', '1.0 (error scale)'], ['slots', '30 min'], ['horizon', 'about 48 h ahead']]],
  truth: ['Carbon truth', 'carbon.py, energy.py', 'Grid-India daily generation by fuel per region, shaped within the day by national SCADA data, times CEA emission factors (coal 978, lignite 1,286, gas 478 g/kWh). Used only by the evaluator to score what actually happened.', [['regions', 'NR, WR, SR'], ['unit', 'gCO₂/kWh']]],
  sim: ['Discrete-event simulator', 'simulator.py', 'Owns the simulated clock and an event heap. Events at the same time are handled in a fixed order: carbon update, job complete, arrival, release, periodic tick, deadline. Same config and seed give byte-identical logs.', [['events', 'CARBON_UPDATE, JOB_COMPLETE, JOB_ARRIVAL, JOB_RELEASE, PERIODIC_TICK'], ['rule', 'running jobs never move (no migration)']]],
  view: ['SchedulerView', 'simulator.py', 'Everything a policy may read: the current forecast vintage, runtime estimates, queue states, and its own pending jobs. It cannot see actual runtimes, end times of running jobs, carbon truth, or future forecasts. Leakage tests enforce this.', [['oracle', 'only pig gets OracleView']]],
  planner: ['Planner', 'planner.py', 'For a job it builds candidates: every datacentre × every 30-minute release slot from now up to 24 h ahead (or the deadline). For each, it projects the start time from the queue, scores estimated emissions Ŝ from the forecast, and checks feasibility in order: fits, in range, can start, meets the deadline, has carbon data. It also computes the lower bound LB used by decision-flip.', [['h_defer', '24 h'], ['Ŝ', 'power × ∫forecast over the projected run'], ['LB', 'cleanest window anywhere, ignoring queues']]],
  policy: ['Policy', 'policies.py', 'The only thing that differs between the seven schedulers: when to re-plan a waiting job and what gain to accept. Placement at arrival, rescue of infeasible plans, cooldown (30 min) and max moves (3) are shared.', POLICIES.map(p => [p, PDESC[p]])],
  client: ['DatacentreClient', 'datacentre.py, dcservice.py', 'The interface between the global and local layers: enqueue, remove, dispatch, complete, state. In-process it is a Python object; in deployment mode each datacentre is a separate HTTP process (or Docker container) and the coordinator sends the simulated time with every call. Results are byte-identical either way (R-DEP-1).', [['DT1', 'local processes'], ['DT2', 'Docker compose'], ['DT3', 'AWS (planned)']]],
  local: ['Local scheduler', 'datacentre.py', 'FIFO queue with first-fit dispatch: on every change, walk the queue front to back and start every job whose GPU, CPU and memory request fits in what is free. Not strict FCFS: small jobs can pass a blocked large one. No reservation, so large jobs can starve.', [['order', 'FIFO by release time'], ['dispatch', 'first-fit, no backfill reservation'], ['owner', 'the datacentre, not the global scheduler']]],
  eval: ['Evaluator', 'metrics.py, reporting.py', 'After the run: actual start × actual runtime × carbon truth gives each job its kg CO₂. Also computes waits, deadline misses, utilisation, planner work, moves, and the paired confidence intervals between policies.', [['energy', 'kW × h × PUE'], ['CO₂', 'Σ energy per slot × truth intensity']]],
};
const STEPS = [
  ['Job arrives', 'The trace releases a job: 4 GPUs, est. 2.5 h (q50), deadline in 9 h.', ['trace', 'sim']],
  ['Look at what is allowed', 'The policy reads the SchedulerView: forecasts, estimates, queues. No truth.', ['view', 'estimates', 'forecast']],
  ['Enumerate candidates', '3 datacentres × up to 48 release slots. Project each start from the queues and score Ŝ.', ['planner']],
  ['Place', 'Pick the feasible candidate with the lowest Ŝ (fcfs: the earliest start instead).', ['policy', 'planner']],
  ['Forecast changes', 'A new vintage arrives. Should this waiting job move? This is where policies differ.', ['forecast', 'policy']],
  ['Release', 'At its release slot the plan is re-checked once; if it became infeasible it is rescued.', ['sim', 'policy']],
  ['Local scheduling', 'The job joins the datacentre FIFO queue; first-fit dispatch starts it when it fits.', ['client', 'local']],
  ['Score the outcome', 'When it completes, actual runtime × carbon truth gives its real kg CO₂.', ['truth', 'eval']],
];
pages.how = async () => {
  const detail = document.getElementById('arch-detail');
  const show = key => {
    const [t, f, d, kv] = NODES[key];
    detail.innerHTML = `<div class="eyebrow">${f}</div><h3>${t}</h3><p>${d}</p><dl>${kv.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>`;
  };
  const nodes = [...document.querySelectorAll('#arch .node')];
  nodes.forEach(n => n.addEventListener('click', () => {
    nodes.forEach(x => x.classList.remove('sel', 'lit'));
    n.classList.add('sel');
    show(n.dataset.node);
  }));
  const steps = document.getElementById('steps');
  steps.innerHTML = STEPS.map((s, i) => `<button class="step" data-i="${i}"><span class="n">${i + 1}</span><span><b>${s[0]}</b><span>${s[1]}</span></span></button>`).join('');
  const lit = i => {
    steps.querySelectorAll('.step').forEach(b => b.classList.toggle('on', +b.dataset.i === i));
    nodes.forEach(n => { n.classList.remove('sel'); n.classList.toggle('lit', STEPS[i][2].includes(n.dataset.node)); });
    show(STEPS[i][2][STEPS[i][2].length - 1]);
  };
  steps.querySelectorAll('.step').forEach(b => b.addEventListener('click', () => lit(+b.dataset.i)));
  lit(0);
};

// ---------------------------------------------------------------- 03 decision flip
pages.flip = async () => {
  const S = { sa: 0.6, lb: 0.5, sb: 0.55, w: 0.12, grel: 0.05, theta: 0.1, mode: 'df' };
  const defs = [
    ['sa', 'Ŝₐ · incumbent plan', 0.05, 2, 0.01],
    ['lb', 'LB · cheapest conceivable alternative', 0, 2, 0.01],
    ['sb', 'Ŝ_b · best real alternative (after full re-score)', 0, 2.3, 0.01],
    ['w', 'w_ab · uncertainty of the comparison', 0, 0.8, 0.01],
    ['grel', 'g_rel · relative gate', 0, 0.2, 0.005],
    ['theta', 'θ · noise margin', 0, 0.5, 0.01],
  ];
  const box = document.getElementById('calc-sliders');
  box.innerHTML = defs.map(([k, l, lo, hi, st]) => `<div class="slider"><label for="s-${k}"><span>${l}</span></label><input type="range" id="s-${k}" min="${lo}" max="${hi}" step="${st}" value="${S[k]}"><output id="o-${k}"></output></div>`).join('');
  const seg = document.querySelectorAll('#p-flip .seg button');
  seg.forEach(b => b.addEventListener('click', () => {
    S.mode = b.dataset.mode;
    seg.forEach(x => x.setAttribute('aria-pressed', x === b));
    S.grel = S.mode === 'df' ? 0.05 : 0.01;
    document.getElementById('s-grel').value = S.grel;
    draw();
  }));
  defs.forEach(([k]) => document.getElementById('s-' + k).addEventListener('input', e => { S[k] = +e.target.value; draw(); }));
  function draw() {
    S.lb = Math.min(S.lb, S.sa); S.sb = Math.max(S.sb, S.lb);
    defs.forEach(([k]) => { document.getElementById('s-' + k).value = S[k]; document.getElementById('o-' + k).textContent = S[k].toFixed(k === 'grel' ? 3 : 2); });
    const df = S.mode === 'df';
    const g = S.grel * S.sa;
    const th = df ? S.theta : 0;
    const wide = df && S.w > 2 * S.sa;
    const thEff = wide ? 0 : th;
    const s1 = !df ? 'skip' : (S.sa - S.lb < g ? 'stop' : 'pass');
    const gain = S.sa - S.sb, need = g + thEff * S.w;
    const s2 = s1 === 'stop' ? 'skip' : (gain >= need && gain > 0 ? 'pass' : 'stop');
    const f = document.getElementById('calc-funnel');
    f.innerHTML = `
      <div class="stage pass"><span class="res">pass</span><b>0 · Throttle</b><div class="eq">not re-scored in the last 30 min, fewer than 3 moves</div></div>
      <div class="stage ${s1}"><span class="res">${!df ? 'not in fixed_savings' : s1 === 'stop' ? 'SKIP · no re-score' : 'pass → re-score'}</span><b>1 · Lower-bound screen</b>
        <div class="eq">Ŝₐ − LB = <b>${(S.sa - S.lb).toFixed(3)}</b> ${S.sa - S.lb < g ? '&lt;' : '≥'} g_min = <b>${g.toFixed(3)}</b></div>
        <div class="small">${!df ? 'fixed_savings always pays for the full re-score.' : s1 === 'stop' ? 'Even the cleanest conceivable alternative cannot clear the gate, so the expensive re-score is skipped. Exact, not a heuristic.' : 'A worthwhile alternative might exist; pay for the full re-score.'}</div></div>
      <div class="stage ${s2}"><span class="res">${s2 === 'skip' ? 'not reached' : s2 === 'pass' ? 'MOVE' : 'KEEP'}</span><b>2 · Full re-score + gate${df ? ' + noise margin' : ''}</b>
        <div class="eq">gain Ŝₐ − Ŝ_b = <b>${gain.toFixed(3)}</b> ${gain >= need ? '≥' : '&lt;'} g_min${df ? ' + θ·w' : ''} = <b>${need.toFixed(3)}</b>${wide ? ' (w > 2·Ŝₐ, so θ switched off)' : ''}</div>
        <div class="small">${s2 === 'pass' ? 'The gain is bigger than the gate' + (df ? ' and bigger than the forecast noise could fake' : '') + ': move the job.' : s2 === 'stop' ? 'Not worth it' + (df && gain >= g ? ': the gain is within the forecast noise, so decision-flip keeps the plan where fixed_savings would move.' : '.') : ''}</div></div>`;
    // scale bar
    const bar = document.getElementById('calc-bar');
    const lo = Math.min(S.lb, S.sb, S.sa - need) - 0.05, hi = Math.max(S.sa, S.sb) + 0.05;
    const X = v => ((v - lo) / (hi - lo) * 100).toFixed(2) + '%';
    const mk = (v, label, color, pos) => `<div class="mk ${pos || ''}" style="left:${X(v)};background:${color}"><span>${label}</span></div>`;
    bar.innerHTML = `<div class="track"></div>
      <div class="band" style="left:${X(S.sa - need)};width:calc(${X(S.sa)} - ${X(S.sa - need)});background:rgba(245,158,11,.25)" title="dead zone: gains here do not move the job"></div>
      ${mk(S.lb, 'LB', '#94a3b8', 'top')}${mk(S.sb, 'Ŝ_b', '#f9a8d4')}${mk(S.sa, 'Ŝₐ', '#f8fafc', 'top')}${mk(S.sa - need, 'move line', '#fbbf24', 'low')}`;
  }
  draw();
  const R = await results('test');
  const parts = [
    { key: 'THROTTLED', name: 'throttled (cooldown / max moves)', fill: '#475569' },
    { key: 'SCREEN_FAIL', name: 'skipped by the Stage-1 screen', fill: '#94a3b8' },
    { key: 'KEEP', name: 'full re-score, kept', fill: '#d55181' },
    { key: 'MOVE', name: 'moved', fill: '#fbbf24' },
  ];
  const rows = ['periodic', 'pred_error', 'fixed_savings', 'decision_flip'].map(p => {
    const d = R.decisions[p] || {};
    return { label: p, color: PCOLOR[p], parts: parts.map(x => ({ name: x.name, fill: x.fill, value: (d[x.key] || 0) + (x.key === 'KEEP' ? (d.NO_ALTERNATIVE || 0) : 0) })) };
  });
  stacked(document.getElementById('flip-funnel'), rows, { parts });
  document.getElementById('flip-funnel').insertAdjacentHTML('beforeend', `<p class="small">pred_error skips most jobs silently (no drift, no record), so its grey part is not shown. On the test set θ was switched off (interval too wide or malformed) for ${(R.theta_off_moves * 100).toFixed(0)}% of decision-flip's moves.</p>`);
};

// ---------------------------------------------------------------- 05 results
let forestMetric = 'kg_co2';
pages.results = async () => {
  document.querySelectorAll('#r-split button').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('#r-split button').forEach(x => x.setAttribute('aria-pressed', x === b));
    drawResults(b.dataset.split);
  }));
  const fm = document.getElementById('r-forest-metric');
  const mets = [['kg_co2', 'CO₂ kg'], ['stage2_calls', 'Re-scorings'], ['moves', 'Moves'], ['miss_rate', 'Miss rate']];
  fm.innerHTML = mets.map(([k, l]) => `<button data-m="${k}" aria-pressed="${k === forestMetric}">${l}</button>`).join('');
  fm.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
    forestMetric = b.dataset.m;
    fm.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', x === b));
    drawResults(document.querySelector('#r-split [aria-pressed=true]').dataset.split);
  }));
  await drawResults('test');
};
function fmtMetric(key, v) {
  if (v == null) return '–';
  if (['completion', 'miss_rate'].includes(key)) return (v * 100).toFixed(2) + '%';
  if (key.startsWith('delta_')) return (v > 0 ? '+' : '') + v.toFixed(2) + '%';
  if (key.endsWith('_h')) return v.toFixed(2);
  if (key === 'moves_per_job') return v.toFixed(3);
  if (key === 'scheduler_s') return v.toFixed(1);
  if (key === 'intensity_g_per_kwh') return v.toFixed(1);
  return fmtN(v, Math.abs(v) < 10 && v % 1 ? 2 : 0);
}
async function drawResults(split) {
  const R = await results(split);
  document.getElementById('r-meta').textContent = `${R.replicates} replicates · ~${fmtN(R.jobs_per_replicate)} jobs each · ± is the 95% CI half-width`;
  const t = document.getElementById('r-table');
  let html = `<thead><tr><th>Metric</th>${POLICIES.map(p => `<th class="${p === 'decision_flip' ? 'col-df' : ''}" title="${PDESC[p]}">${pname(p)}</th>`).join('')}</tr></thead><tbody>`;
  let group = '';
  for (const m of R.metrics) {
    if (m.group !== group) { group = m.group; html += `<tr class="group"><td colspan="${POLICIES.length + 1}">${group}</td></tr>`; }
    const vals = POLICIES.map(p => R.table[p][m.key]);
    let best = null;
    if (m.better !== 'none') {
      const cand = POLICIES.filter(p => p !== 'pig' && R.table[p][m.key].mean != null && !(m.key === 'stage2_calls' && R.table[p][m.key].mean === 0) && !(m.key === 'moves' && R.table[p][m.key].mean === 0) && !(m.key === 'moves_per_job' && R.table[p][m.key].mean === 0) && !(m.key.startsWith('delta_') && R.table[p][m.key].mean === 0));
      const by = m.better === 'low' ? (a, b) => R.table[a][m.key].mean - R.table[b][m.key].mean : (a, b) => R.table[b][m.key].mean - R.table[a][m.key].mean;
      const sorted = cand.sort(by);
      const v0 = R.table[sorted[0]]?.[m.key].mean, v1 = R.table[sorted[1]]?.[m.key].mean;
      best = sorted.length > 1 && Math.abs(v0 - v1) > 1e-9 * Math.max(1, Math.abs(v0)) ? sorted[0] : null;
    }
    html += `<tr><td><div class="metric-name"><span>${m.label} <span class="small">${m.unit}</span></span><small>${m.help}</small></div></td>` + vals.map((v, i) => {
      const p = POLICIES[i];
      const showCi = v.ci != null && v.mean != null && !(m.key === 'energy_kwh');
      return `<td class="num ${p === 'decision_flip' ? 'col-df' : ''} ${p === best ? 'best' : ''}">${fmtMetric(m.key, v.mean)}${showCi && v.ci > 0 ? `<span class="ci">±${fmtMetric(m.key.startsWith('delta_') ? 'x_h' : m.key, v.ci).replace('+', '')}</span>` : ''}</td>`;
    }).join('') + '</tr>';
  }
  t.innerHTML = html + '</tbody>';
  const unit = { kg_co2: 'kg', stage2_calls: '', moves: '', miss_rate: '' }[forestMetric];
  const fmt = forestMetric === 'miss_rate' ? v => (v * 100).toFixed(2) + ' pp' : v => fmtN(v);
  const rows = R.pairwise.filter(r => r.metric === forestMetric).map(r => ({ label: 'vs ' + r.against, color: PCOLOR[r.against], mean: r.mean_diff, lo: r.ci95_lo, hi: r.ci95_hi }));
  forest(document.getElementById('r-forest'), rows, { fmt, unit });
  const g = (a, m) => R.pairwise.find(r => r.against === a && r.metric === m);
  const sig = r => r.ci95_hi < 0 ? '<span class="badge sig-good">lower, significant</span>' : r.ci95_lo > 0 ? '<span class="badge sig-bad">higher, significant</span>' : '<span class="badge ns">not significant</span>';
  document.getElementById('r-honest').innerHTML = `
    <p><b>Against carbon-blind fcfs</b>: ${fmtN(g('fcfs', 'kg_co2').mean_diff)} kg CO₂ per replicate ${sig(g('fcfs', 'kg_co2'))}. This is the carbon-awareness itself, and every carbon-aware policy gets most of it.</p>
    <p><b>Against place_once</b>: ${fmtN(g('place_once', 'kg_co2').mean_diff)} kg ${sig(g('place_once', 'kg_co2'))}. Re-planning on top of a good first placement adds little carbon on these grids.</p>
    <p><b>Against fixed_savings</b>: ${fmtN(g('fixed_savings', 'kg_co2').mean_diff)} kg ${sig(g('fixed_savings', 'kg_co2'))}, with ${fmtN(g('fixed_savings', 'stage2_calls').mean_diff)} re-scorings ${sig(g('fixed_savings', 'stage2_calls'))} and ${fmtN(g('fixed_savings', 'moves').mean_diff)} moves ${sig(g('fixed_savings', 'moves'))}. <b>Same carbon, much less work and churn</b>: this is decision-flip's claim.</p>
    <p><b>Energy</b> is the same for every policy (${fmtN(R.table.fcfs.energy_kwh.mean)} kWh per replicate). Carbon-aware scheduling shifts energy to cleaner hours and places; it does not reduce it.</p>
    <p class="small">The miss rate rises for every carbon-aware policy (deferring jobs eats slack). The scheduler's runtime estimates are wrong for about 12% of jobs (actual runtime > q90), and those jobs account for nearly all misses.</p>`;
}

// ---------------------------------------------------------------- 06 scale
pages.scale = async () => {
  const S = await api('/api/scale');
  const body = document.getElementById('scale-body');
  if (!S) { body.innerHTML = `<div class="empty">No scale study yet. Run <code>uv run python scripts/scale_study.py</code> (10–20 min), then reload.</div>`; return; }
  const pols = S.meta.policies;
  const sizes = S.meta.sizes;
  const avg = {};
  for (const r of S.rows) {
    const k = r.policy + '|' + r.n_dcs;
    avg[k] ??= { n: 0 };
    for (const f of ['n_jobs', 'planner_s', 'rescore_s', 'stage2_calls', 'moves', 'kg_co2', 'miss_rate', 'wait_mean_h', 'screened']) avg[k][f] = (avg[k][f] || 0) + r[f];
    avg[k].n++;
  }
  for (const v of Object.values(avg)) for (const f in v) if (f !== 'n') v[f] /= v.n;
  const A = (p, n, f) => avg[p + '|' + n]?.[f];
  const big = sizes[sizes.length - 1];
  const r = f => pct(A('decision_flip', big, f), A('fixed_savings', big, f));
  const kgD = (A('decision_flip', big, 'kg_co2') / A('fixed_savings', big, 'kg_co2') - 1) * 100;
  body.innerHTML = `
    <div class="grid g4">
      <div class="tile good"><div class="k">Full re-scorings at ${big} DCs vs fixed_savings</div><div class="v">−${r('stage2_calls').toFixed(0)}%</div><div class="d">${fmtN(A('fixed_savings', big, 'stage2_calls') - A('decision_flip', big, 'stage2_calls'))} fewer per run (${fmtN(A('fixed_savings', sizes[0], 'stage2_calls') - A('decision_flip', sizes[0], 'stage2_calls'))} at ${sizes[0]} DCs)</div></div>
      <div class="tile good"><div class="k">Moves at ${big} DCs vs fixed_savings</div><div class="v">−${r('moves').toFixed(0)}%</div><div class="d">${fmtN(A('decision_flip', big, 'moves'))} vs ${fmtN(A('fixed_savings', big, 'moves'))} plan changes</div></div>
      <div class="tile ${r('planner_s') > 40 ? 'good' : 'neutral'}"><div class="k">Planner CPU time at ${big} DCs vs fixed_savings</div><div class="v">−${r('planner_s').toFixed(0)}%</div><div class="d">${A('decision_flip', big, 'planner_s').toFixed(0)} s vs ${A('fixed_savings', big, 'planner_s').toFixed(0)} s per simulated week</div></div>
      <div class="tile neutral"><div class="k">CO₂ at ${big} DCs vs fixed_savings</div><div class="v">${kgD > 0 ? '+' : ''}${kgD.toFixed(1)}%</div><div class="d">${S.meta.mondays.length} carbon weeks only: indicative, not significance-tested</div></div>
    </div>
    <div class="grid g2" style="margin-top:var(--s4)">
      <div class="card"><h3>Full re-scorings per run</h3><div id="sc-a" class="chart"></div></div>
      <div class="card"><h3>Moves (plan changes) per run</h3><div id="sc-b" class="chart"></div></div>
      <div class="card"><h3>Planner CPU time per run (s)</h3><div id="sc-c" class="chart"></div></div>
      <div class="card"><h3>CO₂ vs fcfs (%)</h3><div id="sc-d" class="chart"></div></div>
    </div>
    <div class="grid g2" style="margin-top:var(--s4)">
      <div class="card"><h3>What this shows</h3>
        <p><b>The work gap grows with the federation.</b> fixed_savings and periodic re-score every waiting job at every update, and each re-score evaluates every datacentre × slot, so their cost grows with jobs × datacentres. Decision-flip's screen throws away most of those re-scorings before they happen, and the absolute saving grows from ${fmtN(A('fixed_savings', sizes[0], 'stage2_calls') - A('decision_flip', sizes[0], 'stage2_calls'))} to ${fmtN(A('fixed_savings', big, 'stage2_calls') - A('decision_flip', big, 'stage2_calls'))} re-scorings per run.</p>
        <p><b>Churn stays low.</b> Its moves stay at about a third of fixed_savings' at every size, with CO₂ in the same range as the other re-planners.</p>
      </div>
      <div class="card"><h3>What it does not show (yet)</h3>
        <p><b>The CPU-time gap narrows at 12 datacentres.</b> The Stage-1 screen also loops over every datacentre, and placement at arrival is shared work. In this setup datacentres repeat the 3 grid regions, so the lower bound is computed up to 4× per region; caching it per region is an obvious next optimisation (not done here: no code was changed for this study).</p>
        <p><b>No new carbon diversity.</b> Only 3 Indian grids have forecasts, so datacentre i sits in region i mod 3. More datacentres add queues and choices, not cleaner grids. CO₂ differences here come from ${S.meta.mondays.length} carbon weeks and are indicative only.</p>
        <p class="small">Setup: validation trace days ${S.meta.trace_days.join('–')}, jobs sampled at ${S.meta.base_sampling} × N/3 so each datacentre keeps the same load (ρ ≈ 0.7); carbon weeks ${S.meta.mondays.join(', ')}. Produced by <code>scripts/scale_study.py</code>.</p>
      </div>
    </div>
    <div class="card" style="margin-top:var(--s4)"><h3>All numbers</h3><div class="table-wrap"><table id="sc-t"></table></div></div>`;
  const xFmt = v => v + ' DCs';
  const line = (id, f, yFmt = v => fmtN(v), which = pols, extra = {}) => lineChart(document.getElementById(id), {
    series: which.map(p => ({ name: p, color: PCOLOR[p], points: sizes.map(n => [n, f(p, n)]) })),
    xTicks: sizes, xFmt, yFmt, markers: true, height: 250, ...extra,
  });
  line('sc-a', (p, n) => A(p, n, 'stage2_calls'), v => fmtN(v), ['periodic', 'pred_error', 'fixed_savings', 'decision_flip'], { yMin: 0 });
  line('sc-b', (p, n) => A(p, n, 'moves'), v => fmtN(v), ['periodic', 'pred_error', 'fixed_savings', 'decision_flip'], { yMin: 0 });
  line('sc-c', (p, n) => A(p, n, 'planner_s'), v => fmtN(v), pols, { yMin: 0 });
  line('sc-d', (p, n) => (A(p, n, 'kg_co2') / A('fcfs', n, 'kg_co2') - 1) * 100, v => v.toFixed(1) + '%', pols.filter(p => p !== 'fcfs'));
  const cols = [['n_jobs', 'jobs'], ['stage2_calls', 're-scorings'], ['moves', 'moves'], ['planner_s', 'planner s'], ['kg_co2', 'kg CO₂'], ['miss_rate', 'miss rate'], ['wait_mean_h', 'mean wait h']];
  document.getElementById('sc-t').innerHTML = `<thead><tr><th>DCs · policy</th>${cols.map(c => `<th>${c[1]}</th>`).join('')}</tr></thead><tbody>` +
    sizes.flatMap(n => pols.map(p => `<tr><td>${n} · ${pname(p)}</td>${cols.map(([f]) => `<td class="num">${f === 'miss_rate' ? (A(p, n, f) * 100).toFixed(1) + '%' : f === 'planner_s' || f === 'wait_mean_h' ? A(p, n, f).toFixed(1) : fmtN(A(p, n, f))}</td>`).join('')}</tr>`)).join('') + '</tbody>';
};

// ---------------------------------------------------------------- 07 data
const RCOL = { 1: '#f8fafc', 2: '#94a3b8', 3: '#64748b' };
const RDASH = { 1: '', 2: '6 4', 3: '2 3' };
pages.data = async () => {
  const D = await api('/api/carbon?preset=medium');
  const body = document.getElementById('data-body');
  body.innerHTML = `
    <div class="card"><h3>Carbon truth, the demo fortnight (gCO₂/kWh)</h3><p class="small">Half-hourly intensity of the three regional grids. They share one national daily shape (solar at midday), which limits what moving jobs between them can gain.</p><div id="d-truth" class="chart"></div></div>
    <div class="grid g2" style="margin-top:var(--s4)">
      <div class="card"><h3>What a scheduler sees vs what happens</h3><p class="small">One forecast vintage (captured ${fmtT(D.forecast.capture)}) against the truth that followed, Delhi NCR grid. The gap is real NESO forecast error, scaled to India.</p><div id="d-fc" class="chart"></div></div>
      <div class="card"><h3>The jobs (${fmtN(D.jobs.length)} in the medium demo)</h3><p class="small">GPU requests and actual runtimes are heavy-tailed: the largest 1% of jobs carry over half of all energy, so a few placements decide most of the carbon.</p><div id="d-gpu" class="chart"></div><div id="d-rt" class="chart" style="margin-top:var(--s3)"></div></div>
    </div>`;
  const C = D.carbon;
  const series = Object.keys(C.series).map(r => ({ name: C.names[r], color: RCOL[r], dash: RDASH[r], points: C.series[r].map((v, i) => [C.t0 + i * C.step, v]) }));
  lineChart(document.getElementById('d-truth'), { series, xFmt: t => fmtT(t).slice(0, 10), height: 280, yLabel: 'gCO₂/kWh', xTicks: Array.from({ length: 15 }, (_, i) => C.t0 + i * 86400) });
  const r1 = D.forecast.series['1'] || [];
  const truthAt = t => { const i = Math.round((t - C.t0) / C.step); return C.series['1'][i]; };
  lineChart(document.getElementById('d-fc'), {
    series: [
      { name: 'truth', color: '#f8fafc', points: r1.map(([t]) => [t, truthAt(t)]) },
      { name: 'forecast', color: '#38bdf8', dash: '6 4', points: r1.map(([t, v]) => [t, v]) },
    ], xFmt: t => fmtT(t).replace(/ \d+ \w{3}/, ''), height: 240, yLabel: 'gCO₂/kWh', xTicks: r1.filter((_, i) => i % 16 === 0).map(p => p[0]),
  });
  const gb = {}; for (const j of D.jobs) { const k = j[1] === 0 ? '0' : j[1] <= 1 ? '≤1' : j[1] <= 2 ? '2' : j[1] <= 4 ? '3–4' : j[1] <= 8 ? '5–8' : '>8'; gb[k] = (gb[k] || 0) + 1; }
  bars(document.getElementById('d-gpu'), ['0', '≤1', '2', '3–4', '5–8', '>8'].map(k => ({ label: k + ' GPUs', color: '#818cf8', value: gb[k] || 0, metric: 'jobs' })));
  const rb = {}; const lbl = ['<10 min', '10 min–1 h', '1–4 h', '4–12 h', '12–48 h', '>48 h'];
  for (const j of D.jobs) { const s = j[2]; const k = s < 600 ? 0 : s < 3600 ? 1 : s < 14400 ? 2 : s < 43200 ? 3 : s < 172800 ? 4 : 5; rb[k] = (rb[k] || 0) + 1; }
  bars(document.getElementById('d-rt'), lbl.map((l, i) => ({ label: l, color: '#38bdf8', value: rb[i] || 0, metric: 'jobs by actual runtime' })));
};

// ---------------------------------------------------------------- 04 arena (separate module)
pages.arena = async () => { const m = await import('./arena.js'); await m.init(); };
pages.limits = async () => {};

route();
