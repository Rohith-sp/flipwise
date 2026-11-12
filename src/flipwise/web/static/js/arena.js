// Live arena: polls the backend, where every selected policy runs on the unchanged simulator,
// and animates what each one does with the same jobs.
import { api, POLICIES, PCOLOR, PDESC, pname, fmtT, fmtH, fmtN } from './app.js';
import { lineChart } from './charts.js';

const SPEEDS = [[900, '15 min/s'], [3600, '1 h/s'], [10800, '3 h/s'], [21600, '6 h/s']];
const RCOL = { 1: '#f8fafc', 2: '#94a3b8', 3: '#64748b' };
const RDASH = { 1: '', 2: '6 4', 3: '2 3' };
const MAX_WATCH = 3;
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;

let M = null;           // session meta
let JOB = {};           // job id -> static info
let watched = [];
let cursors = {};
let lanes = {};         // policy -> LaneView (watched only)
let last = null;        // last poll reply
let timer = null;
let fc = { capture: null, series: {}, fetchedAt: 0, lastT: 0 };
let pulseMax = 1;
let selected = null;
let initDone = false;

const $ = id => document.getElementById(id);
const dcName = id => M.dcs[id]?.name ?? 'dc' + id;
const gpuClass = g => g <= 0 ? 'g0' : g <= 1 ? 'g1' : g <= 2 ? 'g2' : g <= 4 ? 'g3' : 'g4';
const gpuText = g => g <= 0 ? '·' : g < 1 ? g.toFixed(1).replace(/^0/, '') : (g % 1 ? g.toFixed(1) : String(g));
const sid = id => String(id).slice(0, 8);
const kg = v => v == null ? '–' : v < 10 ? v.toFixed(3) : v.toFixed(1);

export async function init() {
  if (initDone) return;
  initDone = true;
  const presets = await api('/api/presets');
  $('a-preset').innerHTML = Object.entries(presets).map(([k, v]) => `<option value="${k}" ${k === 'medium' ? 'selected' : ''}>${k} · ${v.label}</option>`).join('');
  $('a-policies').innerHTML = POLICIES.map(p => `<label class="check" title="${PDESC[p]}"><input type="checkbox" value="${p}" checked><span class="swatch" style="background:${PCOLOR[p]}"></span>${p}</label>`).join('');
  $('a-start').addEventListener('click', start);
  $('a-play').addEventListener('click', () => clock(last?.paused ? 'play' : 'pause'));
  $('a-jump').addEventListener('click', () => clock('jump', 6 * 3600));
  $('a-speed').innerHTML = SPEEDS.map(([v, l]) => `<button data-v="${v}" aria-pressed="${v === 3600}">${l}</button>`).join('');
  $('a-speed').querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
    $('a-speed').querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', x === b));
    clock('speed', +b.dataset.v);
  }));
  $('a-watch-add').addEventListener('change', e => { if (e.target.value) toggleWatch(e.target.value); e.target.value = ''; });
  $('a-lanes').addEventListener('click', e => {
    const c = e.target.closest('[data-j]');
    if (c) openJob(c.dataset.j);
  });
  $('drawer-close').addEventListener('click', closeJob);
  addEventListener('keydown', e => {
    if (e.key === 'Escape') closeJob();
    if (e.key === ' ' && location.hash === '#arena' && M && !['INPUT', 'SELECT', 'BUTTON'].includes(document.activeElement.tagName)) { e.preventDefault(); clock(last?.paused ? 'play' : 'pause'); }
  });
}

async function start() {
  const policies = [...document.querySelectorAll('#a-policies input:checked')].map(i => i.value);
  const mode = $('a-mode').value;
  $('a-err').textContent = '';
  $('a-start').disabled = true;
  $('a-start').textContent = 'Building scenario…';
  try {
    if (M) await api('/api/stop', { sid: M.sid }).catch(() => {});
    clearInterval(timer);
    M = await api('/api/session', { preset: $('a-preset').value, policies, mode, speed: 3600 });
  } catch (e) {
    $('a-err').textContent = e.message;
    return;
  } finally {
    $('a-start').disabled = false;
    $('a-start').textContent = 'Restart';
  }
  JOB = {};
  const c = M.job_cols;
  for (const row of M.jobs) { const j = {}; c.forEach((k, i) => j[k] = row[i]); JOB[j.id] = j; }
  cursors = {}; lanes = {}; pulseMax = 1; fc = { capture: null, series: {}, fetchedAt: 0, lastT: 0 }; selected = null;
  const prefer = ['decision_flip', 'fixed_savings', 'place_once'];
  watched = prefer.filter(p => M.policies.includes(p)).slice(0, 2);
  if (watched.length < 2) watched = M.policies.slice(0, 2);
  $('a-lanes').innerHTML = '';
  for (const p of watched) addLane(p);
  $('arena-live').hidden = false;
  $('arena-empty').hidden = true;
  $('a-speed').querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', x.dataset.v === '3600'));
  const span = M.last_arrival_s + 2 * 86400 - M.start_s;
  $('a-lastarr').style.left = ((M.last_arrival_s - M.start_s) / span * 100) + '%';
  watchOptions();
  await clock('play');
  timer = setInterval(poll, 250);
}

async function clock(action, value) {
  if (!M) return;
  try { await api('/api/clock', { sid: M.sid, action, value }); } catch (e) { $('a-err').textContent = e.message; }
  poll();
}

function toggleWatch(p) {
  if (watched.includes(p)) {
    watched = watched.filter(x => x !== p);
    lanes[p]?.root.remove();
    delete lanes[p]; delete cursors[p];
  } else {
    if (watched.length >= MAX_WATCH) { const drop = watched.shift(); lanes[drop]?.root.remove(); delete lanes[drop]; delete cursors[drop]; }
    watched.push(p);
    addLane(p);
  }
  watchOptions();
  renderScore();
}
function watchOptions() {
  $('a-watch-add').innerHTML = `<option value="">add / remove lane…</option>` + M.policies.map(p => `<option value="${p}">${watched.includes(p) ? '− ' : '+ '}${p}</option>`).join('');
}
function addLane(p) {
  const lv = new LaneView(p);
  lanes[p] = lv;
  cursors[p] = 0;
  $('a-lanes').appendChild(lv.root);
}

let busy = false;
async function poll() {
  if (!M || busy) return;
  busy = true;
  try {
    const cur = watched.map(p => `${p}:${cursors[p] || 0}`).join(',');
    const r = await api(`/api/poll?sid=${M.sid}&watch=${watched.join(',')}&cur=${cur}`);
    last = r;
    for (const p of watched) {
      const L = r.lanes[p];
      if (!L || !lanes[p]) continue;
      const recs = L.records || [];
      cursors[p] = L.cursor ?? cursors[p];
      lanes[p].apply(recs, recs.length < 80 && !REDUCED && location.hash === '#arena');
      lanes[p].tick(r.now, L);
    }
    renderClock(r);
    renderScore();
    await carbonStrip(r.now);
  } catch (e) {
    $('a-err').textContent = e.message;
    if (/session ended/.test(e.message)) clearInterval(timer);
  } finally { busy = false; }
}

function renderClock(r) {
  const all = Object.values(r.lanes);
  const finished = all.every(l => l.finished);
  const shown = finished ? Math.max(...all.map(l => l.t)) : r.now;
  $('a-clock').innerHTML = `${fmtT(Math.floor(shown))}<small>IST · day ${Math.floor((shown - M.start_s) / 86400) + 1}${finished ? ' · all finished' : ''}</small>`;
  $('a-play').textContent = r.paused ? 'Play' : 'Pause';
  $('a-dot').classList.toggle('on', !r.paused && !finished);
  const span = M.last_arrival_s + 2 * 86400 - M.start_s;
  $('a-prog').style.width = Math.min(100, (shown - M.start_s) / span * 100) + '%';
  if (finished) clearInterval(timer), timer = null;
}

function renderScore() {
  if (!last) return;
  const L = last.lanes;
  const ps = M.policies;
  const maxR = Math.max(1, ...ps.map(p => L[p].rescores));
  const head = `<thead><tr><th>Scheduler</th><th>arrived</th><th>done</th><th title="Full re-scorings: every datacentre × slot evaluated for one job">full re-scorings</th><th title="Re-scorings skipped by decision-flip's lower-bound screen">skipped by screen</th><th>moves</th><th>rescues</th><th title="CO₂ of completed jobs against carbon truth">CO₂ kg</th><th>kg / job</th><th title="Planner CPU time so far">planner s</th><th></th></tr></thead>`;
  const rows = ps.map(p => {
    const l = L[p];
    return `<tr class="${watched.includes(p) ? 'watched' : ''}"><td>${pname(p)}${l.error ? ` <span class="err" title="${l.error}">error</span>` : ''}</td>
      <td class="num">${fmtN(l.arrived)}</td><td class="num">${fmtN(l.done)}</td>
      <td class="num bar"><div class="row" style="gap:8px;flex-wrap:nowrap"><div class="mini-bar" style="flex:1"><i style="width:${l.rescores / maxR * 100}%;background:${PCOLOR[p]}"></i></div><span style="min-width:48px">${fmtN(l.rescores)}</span></div></td>
      <td class="num">${p === 'decision_flip' ? fmtN(l.screen_fail) : '–'}</td>
      <td class="num">${fmtN(l.moves)}</td><td class="num">${fmtN(l.rescues)}</td>
      <td class="num">${fmtN(l.kg, 1)}</td><td class="num">${l.done ? (l.kg / l.done).toFixed(3) : '–'}</td>
      <td class="num">${l.planner_s.toFixed(1)}</td>
      <td><button class="ghost" style="min-height:30px;padding:0 10px;font-size:12px" data-watch="${p}">${watched.includes(p) ? 'Hide' : 'Watch'}</button></td></tr>`;
  }).join('');
  const t = $('a-score');
  t.innerHTML = head + '<tbody>' + rows + '</tbody>';
  t.querySelectorAll('[data-watch]').forEach(b => b.addEventListener('click', () => toggleWatch(b.dataset.watch)));
  const done = ps.every(p => L[p].finished);
  if (done && ps.includes('decision_flip') && ps.includes('fixed_savings') && !$('a-final')) {
    const d = L.decision_flip, f = L.fixed_savings;
    t.closest('.card').insertAdjacentHTML('beforeend', `<div class="callout good" id="a-final" style="margin-top:var(--s3)"><b>Run complete.</b> decision_flip made ${fmtN(d.rescores)} full re-scorings and ${fmtN(d.moves)} moves; fixed_savings made ${fmtN(f.rescores)} and ${fmtN(f.moves)} (−${((1 - d.rescores / f.rescores) * 100).toFixed(0)}% and −${((1 - d.moves / Math.max(f.moves, 1)) * 100).toFixed(0)}%). CO₂: ${fmtN(d.kg, 1)} vs ${fmtN(f.kg, 1)} kg (${((d.kg / f.kg - 1) * 100).toFixed(1)}%). One small run is one sample: the Results page has the 16-replicate test.</div>`);
  }
  if (!done) $('a-final')?.remove();
}

async function carbonStrip(now) {
  const lead = lanes[watched[0]];
  const wantFc = lead && lead.lastFc !== fc.lastT && performance.now() - fc.fetchedAt > 1200;
  if (wantFc || !fc.capture) {
    fc.fetchedAt = performance.now();
    fc.lastT = lead?.lastFc;
    try { const f = await api(`/api/forecast?sid=${M.sid}&t=${Math.floor(now)}`); fc.capture = f.capture; fc.series = f.series; } catch { /* next poll */ }
  }
  const C = M.carbon;
  const lo = now - 12 * 3600, hi = now + 36 * 3600;
  const series = [];
  for (const r of Object.keys(C.series)) {
    const pts = [];
    C.series[r].forEach((v, i) => { const t = C.t0 + i * C.step; if (t >= lo && t <= now) pts.push([t, v]); });
    series.push({ name: C.names[r] + ' truth', short: C.names[r], color: RCOL[r], dash: RDASH[r], points: pts, noLabel: true });
    const f = (fc.series[r] || []).filter(([t]) => t >= now - 1800 && t <= hi);
    series.push({ name: C.names[r] + ' forecast', short: C.names[r], color: RCOL[r], dash: '3 4', opacity: .75, points: f.map(([t, v]) => [t, v]) });
  }
  if (!series.some(s => s.points.length)) return;
  lineChart($('a-carbon'), {
    series, height: 190, xMin: lo, xMax: hi, xFmt: t => fmtT(t, false), yLabel: 'gCO₂/kWh', directLabels: true,
    xTicks: Array.from({ length: 9 }, (_, i) => Math.ceil(lo / 21600) * 21600 + i * 21600),
    vlines: [{ x: now, color: '#22c55e', label: 'now' }], label: 'Grid carbon intensity, truth and forecast',
  });
  // the legend helper prints every series; keep it short here
  const lg = $('a-carbon').querySelector('.legend');
  if (lg) lg.innerHTML = Object.keys(C.series).map(r => `<span><svg width="18" height="10" aria-hidden="true"><line x1="1" y1="5" x2="17" y2="5" stroke="${RCOL[r]}" stroke-width="2" stroke-dasharray="${RDASH[r]}"/></svg>${C.names[r]}</span>`).join('') + `<span class="small">forecast ${fc.capture ? 'captured ' + fmtT(fc.capture, false) : ''}</span>`;
  for (const lv of Object.values(lanes)) lv.intensity(now);
}

function fcAt(region, t) {
  const s = fc.series[region];
  if (!s || !s.length) return null;
  let best = s[0];
  for (const p of s) if (p[0] <= t) best = p;
  return best[1];
}

// ------------------------------------------------------------------------------- one lane
class LaneView {
  constructor(policy) {
    this.p = policy;
    this.jobs = new Map();
    this.grp = null;
    this.pulses = [];
    this.lastFc = null;
    this.doneByDc = M.dcs.map(() => 0);
    const root = this.root = document.createElement('article');
    root.className = 'lane';
    root.style.borderTop = `3px solid ${PCOLOR[policy]}`;
    root.innerHTML = `
      <div class="lane-head">
        <h3><span class="swatch" style="background:${PCOLOR[policy]};width:12px;height:12px"></span>${policy}</h3>
        <span class="lt"></span>
        <div class="kpis"></div>
      </div>
      <p class="small" style="margin:-6px 0 10px">${PDESC[policy]}</p>
      <div class="lane-body">
        <div class="inbox" aria-label="Latest arrivals"><div class="small">Arrivals appear here.</div></div>
        <div class="dcs" style="--ndc:${M.dcs.length}">${M.dcs.map(d => `
          <div class="dc" data-dc="${d.id}">
            <div class="dc-h"><b>${d.name} <span class="small">${d.grid}</span></b><span class="ci mono">– g</span></div>
            <div class="dc-meta"></div>
            <div class="util" title="GPU utilisation"><i style="width:0"></i></div>
            <div class="zone plan"><div class="zl"><span>planned · waiting for release</span><b>0</b></div><div class="chips"></div></div>
            <div class="zone queue"><div class="zl"><span>local queue · FIFO first-fit</span><b>0</b></div><div class="chips"></div></div>
            <div class="zone run"><div class="zl"><span>running</span><b>0</b></div><div class="chips"></div></div>
            <div class="dc-done">0 completed</div>
          </div>`).join('')}
        </div>
        <div class="feed">
          <div class="small">Re-plan activity per forecast update (same scale in every lane)</div>
          <div class="pulses" aria-hidden="true"></div>
          <div class="legend" style="margin:0"><span><span class="swatch" style="background:#94a3b8"></span>skipped</span><span><span class="swatch" style="background:#d55181"></span>re-scored, kept</span><span><span class="swatch" style="background:#fbbf24"></span>moved</span></div>
          <div class="log" aria-live="off"></div>
        </div>
      </div>`;
    this.el = {
      lt: root.querySelector('.lt'), kpis: root.querySelector('.kpis'), inbox: root.querySelector('.inbox'),
      pulses: root.querySelector('.pulses'), log: root.querySelector('.log'),
      dc: M.dcs.map(d => {
        const e = root.querySelector(`[data-dc="${d.id}"]`);
        return {
          root: e, ci: e.querySelector('.ci'), meta: e.querySelector('.dc-meta'), util: e.querySelector('.util i'), done: e.querySelector('.dc-done'),
          plan: e.querySelector('.plan .chips'), queue: e.querySelector('.queue .chips'), run: e.querySelector('.run .chips'),
          nplan: e.querySelector('.plan .zl b'), nqueue: e.querySelector('.queue .zl b'), nrun: e.querySelector('.run .zl b'),
        };
      }),
    };
    this.cards = [];
  }

  job(id) {
    let j = this.jobs.get(id);
    if (!j) {
      const info = JOB[id];
      const chip = document.createElement('button');
      chip.className = 'chip ' + gpuClass(info.gpu);
      chip.dataset.j = id;
      chip.textContent = gpuText(info.gpu);
      chip.title = `${id} · ${info.gpu} GPU · est. ${fmtH(info.q50)}`;
      chip.setAttribute('aria-label', `job ${id}`);
      j = { id, st: 'new', dc: null, slot: null, moves: 0, chip, hist: [], start: null, end: null };
      this.jobs.set(id, j);
    }
    return j;
  }

  put(j, zone, animate) {
    const target = this.el.dc[j.dc][zone];
    const chip = j.chip;
    if (animate && chip.isConnected && chip.offsetParent) {
      const a = chip.getBoundingClientRect();
      target.appendChild(chip);
      const b = chip.getBoundingClientRect();
      const dx = a.left - b.left, dy = a.top - b.top;
      if (dx || dy) chip.animate([{ transform: `translate(${dx}px,${dy}px) scale(1.25)`, zIndex: 5 }, { transform: 'none' }], { duration: 650, easing: 'cubic-bezier(.2,.8,.2,1)' });
    } else {
      target.appendChild(chip);
      if (animate && chip.offsetParent) chip.animate([{ opacity: 0, transform: 'scale(.4)' }, { opacity: 1, transform: 'none' }], { duration: 300 });
    }
    if (selected === j.id) chip.classList.add('sel');
  }

  apply(recs, animate) {
    const arrivals = [];
    for (const r of recs) {
      if (this.grp && (r.k === 'fc' || r.k === 'tick' || r.t > this.grp.t)) this.flush();
      switch (r.k) {
        case 'arr': {
          const j = this.job(r.j);
          j.st = 'arrived';
          j.hist.push([r.t, 'arr', 'arrived']);
          arrivals.push(r.j);
          break;
        }
        case 'fc': this.lastFc = r.t; this.grp = { t: r.t, kind: 'update', skip: 0, keep: 0, move: 0, thr: 0, resc: 0 }; break;
        case 'tick': this.grp = { t: r.t, kind: 'timer', skip: 0, keep: 0, move: 0, thr: 0, resc: 0 }; break;
        case 'd': this.decision(r, animate); break;
        case 'q': { const j = this.job(r.j); j.st = 'queue'; j.dc = r.dc; this.put(j, 'queue', animate); j.hist.push([r.t, 'q', `released → local queue at ${dcName(r.dc)}`]); break; }
        case 'run': { const j = this.job(r.j); j.st = 'run'; j.dc = r.dc; j.start = r.t; j.end = r.end; this.put(j, 'run', animate); j.chip.insertAdjacentHTML('beforeend', '<span class="pb"><i></i></span>'); j.hist.push([r.t, 'run', `started at ${dcName(r.dc)} (local first-fit)`]); break; }
        case 'done': {
          const j = this.job(r.j); j.st = 'done'; j.chip.remove();
          this.doneByDc[j.dc]++;
          j.hist.push([r.t, 'done', `completed · ${kg(r.kg)} kg CO₂ (truth)`]);
          break;
        }
      }
    }
    if (this.grp && recs.length && recs[recs.length - 1].t > this.grp.t) this.flush();
    // job cards: only the newest few arrivals of this batch
    for (const id of arrivals.slice(-3)) this.card(id, animate);
    this.counts();
  }

  decision(r, animate) {
    const j = this.job(r.j);
    const k = r.kind;
    const g = this.grp;
    const to = r.tdc != null ? `${dcName(r.tdc)} @ ${fmtT(r.tslot, false)}` : '';
    if (k === 'PLACE' || k === 'FALLBACK') {
      j.st = 'plan'; j.dc = r.tdc; j.slot = r.tslot;
      if (k === 'FALLBACK') j.chip.classList.add('risk');
      this.put(j, 'plan', animate);
      j.hist.push([r.t, k, `${k === 'PLACE' ? 'placed' : 'fallback (deadline at risk)'} → ${to}${r.sb != null ? ` · Ŝ ${kg(r.sb)} kg` : ''}`]);
      j.verdict = `<b>${k === 'PLACE' ? 'Placed' : 'Fallback'}</b> → ${dcName(r.tdc)}, release ${fmtT(r.tslot, false)}${r.tslot > r.t + 60 ? ` (deferred ${fmtH(r.tslot - r.t)})` : ' (now)'}${r.sb != null ? ` · Ŝ ${kg(r.sb)} kg` : ''}`;
      this.updateCard(j);
    } else if (k === 'MOVE' || k === 'RESCUE') {
      const from = `${dcName(r.fdc)} @ ${fmtT(r.fslot, false)}`;
      j.st = 'plan'; j.dc = r.tdc; j.slot = r.tslot;
      if (k === 'MOVE') { j.moves++; j.chip.classList.add('moved'); }
      this.put(j, 'plan', animate);
      if (animate) { j.chip.classList.remove('flash'); void j.chip.offsetWidth; j.chip.classList.add('flash'); }
      const why = k === 'MOVE'
        ? `gain ${kg(r.sa - r.sb)} ≥ g ${kg(r.g ?? 0)}${r.th ? ` + θ·w ${kg(r.th * (r.w || 0))}` : ''}`
        : `plan infeasible (${(r.why || '').toLowerCase().replace(/_/g, ' ')})`;
      j.hist.push([r.t, k, `${k === 'MOVE' ? 'moved' : 'rescued'} ${from} → ${to} · ${why}`]);
      this.log(r.t, k, `${k} ${sid(r.j)} ${from} → ${to} · ${why}`);
      if (g) { if (k === 'MOVE') g.move++; else g.resc++; }
    } else if (k === 'REJECT') {
      j.st = 'rej'; j.chip.remove(); j.hist.push([r.t, k, 'rejected: no feasible start']);
      this.log(r.t, 'RESCUE', `REJECT ${sid(r.j)}: no feasible start`);
    } else if (k === 'SCREEN_FAIL') {
      if (g) g.skip++;
      j.hist.push([r.t, k, `screened out: Ŝₐ − LB = ${kg(r.sa - r.lb)} < g ${kg(r.g)} (no re-score)`]);
    } else if (k === 'KEEP' || k === 'NO_ALTERNATIVE') {
      if (g) g.keep++;
      j.hist.push([r.t, k, k === 'KEEP' ? `re-scored, kept: best alternative ${kg(r.sb)} kg vs current ${kg(r.sa)} kg${r.th ? ' (within the noise margin)' : ''}` : 're-scored: no feasible alternative']);
    } else if (k === 'THROTTLED') {
      if (g) g.thr++;
    } else if (k === 'RESCUE_NOOP') {
      j.hist.push([r.t, k, `rescue not possible (${(r.why || '').toLowerCase().replace(/_/g, ' ')})`]);
    }
  }

  flush() {
    const g = this.grp;
    this.grp = null;
    const checked = g.skip + g.keep + g.move + g.thr;
    if (!checked && !g.resc) return;
    this.pulses.push(g);
    if (this.pulses.length > 60) this.pulses.shift();
    const tot = g.skip + g.thr + g.keep + g.move;
    if (tot > pulseMax) pulseMax = tot;
    const label = g.kind === 'timer' ? 'timer' : 'forecast update';
    this.log(g.t, 'UPD', `${label} · <b>${checked}</b> checked · <span class="s-skip">${g.skip + g.thr} skipped</span> · <span class="s-full">${g.keep + g.move} full re-scores</span> · <span class="s-move">${g.move} moved</span>`, true);
    this.drawPulses();
  }

  drawPulses() {
    const h = 54;
    this.el.pulses.innerHTML = this.pulses.map(g => {
      const s = v => `${(v / pulseMax * h).toFixed(1)}px`;
      return `<i title="${fmtT(g.t, false)}: ${g.skip + g.thr} skipped, ${g.keep} kept, ${g.move} moved"><s style="height:${s(g.skip + g.thr)};background:#94a3b8"></s><s style="height:${s(g.keep)};background:#d55181"></s><s style="height:${s(g.move)};background:#fbbf24"></s></i>`;
    }).join('');
  }

  log(t, cls, html, raw = false) {
    const d = document.createElement('div');
    d.className = cls;
    d.innerHTML = `<span class="tm">${fmtT(t, false)}</span>${raw ? html : html.replace(/</g, '&lt;')}`;
    this.el.log.prepend(d);
    while (this.el.log.childElementCount > 160) this.el.log.lastChild.remove();
  }

  card(id, animate) {
    const j = this.jobs.get(id), info = JOB[id];
    const c = document.createElement('div');
    c.className = 'jobcard' + (animate ? ' enter' : '');
    c.dataset.j = id;
    c.innerHTML = `<div class="jh"><b title="${id}">${sid(id)}…</b><span class="small">${fmtT(info.arrival, false)} · user ${String(info.user).slice(0, 8)}</span></div>
      <dl><div><dt>GPU</dt><dd>${info.gpu}</dd></div><div><dt>CPU</dt><dd>${info.cpu}</dd></div><div><dt>Mem</dt><dd>${fmtN(info.mem)} GB</dd></div>
      <div><dt>Est. q50</dt><dd>${fmtH(info.q50)}</dd></div><div><dt>Est. q90</dt><dd>${fmtH(info.q90)}</dd></div><div><dt>Deadline</dt><dd>+${fmtH(info.deadline - info.arrival)}</dd></div>
      <div><dt>Power</dt><dd>${info.kw} kW</dd></div><div><dt>Actual</dt><dd title="hidden from the scheduler">${fmtH(info.actual)}*</dd></div></dl>
      <div class="verdict">${j.verdict || 'Scoring candidates…'}</div>`;
    const first = this.el.inbox.firstElementChild;
    if (first && !first.classList.contains('jobcard')) first.remove();
    this.el.inbox.prepend(c);
    [...this.el.inbox.children].forEach((x, i) => { x.classList.toggle('old', i > 0); if (i > 2) x.remove(); });
    j.card = c;
  }
  updateCard(j) { const v = j.card?.querySelector('.verdict'); if (v && j.card.isConnected) v.innerHTML = j.verdict; }

  counts() {
    this.el.dc.forEach((d, i) => {
      d.nplan.textContent = d.plan.childElementCount;
      d.nqueue.textContent = d.queue.childElementCount;
      d.nrun.textContent = d.run.childElementCount;
      d.done.textContent = `${fmtN(this.doneByDc[i])} completed`;
    });
  }

  tick(now, L) {
    // progress bars and utilisation of running jobs
    this.el.dc.forEach((d, i) => {
      let gpu = 0;
      for (const chip of d.run.children) {
        const j = this.jobs.get(chip.dataset.j);
        gpu += JOB[j.id].gpu;
        const bar = chip.querySelector('.pb i');
        if (bar && j.end > j.start) bar.style.width = Math.min(100, (now - j.start) / (j.end - j.start) * 100) + '%';
      }
      d.util.style.width = Math.min(100, gpu / M.dcs[i].cap_gpu * 100) + '%';
      d.util.parentElement.title = `GPU utilisation ${(gpu / M.dcs[i].cap_gpu * 100).toFixed(0)}% of ${M.dcs[i].cap_gpu.toFixed(0)} GPUs`;
      const dc = L.dcs[i];
      d.meta.textContent = dc && dc.pid ? `PID ${dc.pid} · :${dc.port} · ${fmtN(dc.calls)} calls · ${dc.ms.toFixed(2)} ms` : dc ? `in-process · ${fmtN(dc.calls)} calls` : '';
    });
    this.el.lt.textContent = L.finished ? `finished ${fmtT(L.t)}` : L.t ? `lane clock ${fmtT(L.t, false)}` : 'starting…';
    const hl = this.p === 'decision_flip' ? 'hl' : '';
    this.el.kpis.innerHTML = `<span class="kpi ${hl}">full re-scorings<b>${fmtN(L.rescores)}</b></span>${this.p === 'decision_flip' ? `<span class="kpi">skipped by screen<b>${fmtN(L.screen_fail)}</b></span>` : ''}<span class="kpi ${hl}">moves<b>${fmtN(L.moves)}</b></span><span class="kpi">rescues<b>${fmtN(L.rescues)}</b></span><span class="kpi">CO₂<b>${fmtN(L.kg, 1)}</b> kg</span>`;
  }

  intensity(now) {
    const vals = M.dcs.map(d => fcAt(String(d.region), now));
    const min = Math.min(...vals.filter(v => v != null));
    this.el.dc.forEach((d, i) => {
      const v = vals[i];
      d.ci.textContent = v == null ? '– g' : `${Math.round(v)} g/kWh`;
      d.ci.style.background = v === min ? 'rgba(34,197,94,.18)' : 'var(--muted)';
      d.ci.style.color = v === min ? 'var(--df-hi)' : 'var(--text-2)';
      d.ci.title = v === min ? 'cleanest grid in the current forecast' : 'current forecast';
    });
  }
}

// ------------------------------------------------------------------------------- job drawer
function openJob(id) {
  document.querySelectorAll('.chip.sel').forEach(c => c.classList.remove('sel'));
  selected = id;
  for (const lv of Object.values(lanes)) lv.jobs.get(id)?.chip.classList.add('sel');
  const info = JOB[id];
  const where = p => {
    const j = lanes[p].jobs.get(id);
    if (!j || j.st === 'new') return 'not arrived yet';
    return { arrived: 'arrived', plan: `planned at ${dcName(j.dc)}, release ${fmtT(j.slot)}`, queue: `in the local queue at ${dcName(j.dc)}`, run: `running at ${dcName(j.dc)}`, done: 'completed', rej: 'rejected' }[j.st];
  };
  $('drawer-body').innerHTML = `<div class="eyebrow">Job</div><h2 class="mono">${id}</h2>
    <div class="grid g3" style="gap:8px;margin-bottom:var(--s4)">
      ${[['GPUs', info.gpu], ['CPU cores', info.cpu], ['Memory', fmtN(info.mem) + ' GB'], ['Arrival', fmtT(info.arrival)], ['Deadline', fmtT(info.deadline)], ['Power', info.kw + ' kW'], ['Est. runtime q50', fmtH(info.q50)], ['Est. runtime q90', fmtH(info.q90)], ['Actual runtime*', fmtH(info.actual)]].map(([k, v]) => `<div class="tile" style="padding:8px 10px"><div class="k">${k}</div><div class="mono">${v}</div></div>`).join('')}
    </div>
    <p class="small">* Hidden from every scheduler except the oracle. Schedulers plan with q50/q90 from the user's past jobs.</p>
    ${watched.map(p => {
      const j = lanes[p].jobs.get(id);
      return `<h3 style="margin-top:var(--s4)">${pname(p)}</h3><div class="small">${where(p)} · ${j?.moves || 0} moves</div><div class="hist">${(j?.hist || []).map(([t, k, s]) => `<div class="${k === 'MOVE' ? 'MOVE' : k === 'RESCUE' ? 'RESCUE' : k}"><span class="tm">${fmtT(t, false)}</span> ${s}</div>`).join('') || '<div>nothing yet</div>'}</div>`;
    }).join('')}`;
  $('drawer').classList.add('open');
  $('drawer').setAttribute('aria-hidden', 'false');
  $('drawer-close').focus();
}
function closeJob() {
  $('drawer').classList.remove('open');
  $('drawer').setAttribute('aria-hidden', 'true');
  document.querySelectorAll('.chip.sel').forEach(c => c.classList.remove('sel'));
  selected = null;
}
