// Small SVG chart helpers. Mark specs follow the dataviz skill: 2px lines, thin bars with 4px
// rounded data ends, recessive grid, hover tooltip on every chart, legend for >= 2 series.
const NS = 'http://www.w3.org/2000/svg';
const tipEl = () => document.getElementById('tip');

export function showTip(html, x, y) {
  const t = tipEl();
  t.innerHTML = html;
  t.classList.add('on');
  const w = t.offsetWidth, h = t.offsetHeight;
  const px = x + 14 + w > innerWidth ? x - w - 14 : x + 14;
  const py = Math.min(Math.max(8, y - h / 2), innerHeight - h - 8);
  t.style.left = px + 'px';
  t.style.top = py + 'px';
}
export function hideTip() { tipEl().classList.remove('on'); }

export function el(tag, attrs = {}, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}

export function niceTicks(lo, hi, n = 5) {
  if (!isFinite(lo) || !isFinite(hi)) return [0, 1];
  if (lo === hi) { hi = lo + 1; }
  const span = hi - lo, step0 = span / n;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= step0);
  const out = [];
  const end = Math.ceil(hi / step - 1e-9) * step;
  for (let v = Math.floor(lo / step + 1e-9) * step; v <= end + step * 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

function legend(container, series) {
  if (series.length < 2) return;
  const lg = document.createElement('div');
  lg.className = 'legend';
  for (const s of series) {
    const sp = document.createElement('span');
    sp.innerHTML = `<svg width="18" height="10" aria-hidden="true"><line x1="1" y1="5" x2="17" y2="5" stroke="${s.color}" stroke-width="${s.width || 2}" ${s.dash ? `stroke-dasharray="${s.dash}"` : ''}/></svg>${s.name}`;
    lg.appendChild(sp);
  }
  container.appendChild(lg);
}

/** Line chart with crosshair tooltip. points: [[x, y|null], ...] sorted by x. */
export function lineChart(container, opt) {
  const { series, height = 240, xFmt = String, yFmt = v => v, yLabel = '', xTicks, yMin, yMax,
    directLabels = series.length <= 4, markers = false, bands = [], vlines = [] } = opt;
  container.innerHTML = '';
  legend(container, series);
  const W = container.clientWidth || 600, H = height;
  const m = { l: 52, r: directLabels ? 92 : 14, t: 12, b: 26 };
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': opt.label || yLabel }, container);
  const xs = series.flatMap(s => s.points.map(p => p[0]));
  const ys = series.flatMap(s => s.points.map(p => p[1]).filter(v => v != null));
  let x0 = opt.xMin ?? Math.min(...xs), x1 = opt.xMax ?? Math.max(...xs);
  if (x0 === x1) x1 = x0 + 1;
  let y0 = yMin ?? Math.min(...ys), y1 = yMax ?? Math.max(...ys);
  const yt = niceTicks(y0, y1, 4);
  y0 = Math.min(y0, yt[0]); y1 = Math.max(y1, yt[yt.length - 1]);
  const X = v => m.l + (v - x0) / (x1 - x0) * (W - m.l - m.r);
  const Y = v => H - m.b - (v - y0) / (y1 - y0 || 1) * (H - m.t - m.b);
  const g = el('g', { class: 'grid' }, svg);
  for (const t of yt) el('line', { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t) }, g);
  const ax = el('g', { class: 'axis' }, svg);
  for (const t of yt) el('text', { x: m.l - 8, y: Y(t) + 4, 'text-anchor': 'end' }, ax).textContent = yFmt(t);
  const xt = xTicks || niceTicks(x0, x1, 6);
  for (const t of xt) {
    if (t < x0 || t > x1) continue;
    el('text', { x: X(t), y: H - 6, 'text-anchor': 'middle' }, ax).textContent = xFmt(t);
  }
  if (yLabel) el('text', { x: m.l, y: 8, class: 'lbl' }, svg).textContent = yLabel;
  for (const b of bands) el('rect', { x: X(b[0]), y: m.t, width: Math.max(0, X(b[1]) - X(b[0])), height: H - m.t - m.b, fill: b[2] || 'rgba(148,163,184,.07)' }, svg);
  for (const v of vlines) {
    if (v.x < x0 || v.x > x1) continue;
    el('line', { x1: X(v.x), x2: X(v.x), y1: m.t, y2: H - m.b, stroke: v.color || '#f8fafc', 'stroke-width': 1.5, 'stroke-dasharray': v.dash || '' }, svg);
    if (v.label) el('text', { x: X(v.x) + 4, y: m.t + 10, class: 'lbl', fill: v.color || '#f8fafc' }, svg).textContent = v.label;
  }
  const placed = [];
  for (const s of series) {
    let d = '', pen = false;
    for (const [x, y] of s.points) {
      if (y == null) { pen = false; continue; }
      d += (pen ? 'L' : 'M') + X(x).toFixed(1) + ' ' + Y(y).toFixed(1);
      pen = true;
    }
    el('path', { d, fill: 'none', stroke: s.color, 'stroke-width': s.width || 2, 'stroke-dasharray': s.dash || '', 'stroke-linejoin': 'round', 'stroke-linecap': 'round', opacity: s.opacity ?? 1 }, svg);
    if (markers) for (const [x, y] of s.points) if (y != null) el('circle', { cx: X(x), cy: Y(y), r: 4, fill: s.color, stroke: 'var(--card)', 'stroke-width': 2 }, svg);
    if (directLabels && !s.noLabel) {
      const last = [...s.points].reverse().find(p => p[1] != null);
      if (last) {
        let ly = Y(last[1]) + 4;
        for (const p of placed) if (Math.abs(p - ly) < 13) ly = p + 13 * Math.sign(ly - p || 1);
        placed.push(ly);
        el('text', { x: X(last[0]) + 6, y: ly, class: 'lbl', fill: 'var(--text-2)' }, svg).textContent = s.short || s.name;
      }
    }
  }
  // hover layer
  const cross = el('line', { y1: m.t, y2: H - m.b, stroke: '#64748b', 'stroke-width': 1, opacity: 0 }, svg);
  const hit = el('rect', { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: 'transparent' }, svg);
  const allX = [...new Set(xs)].sort((a, b) => a - b);
  hit.addEventListener('mousemove', ev => {
    const r = svg.getBoundingClientRect();
    const px = (ev.clientX - r.left) * (W / r.width);
    const xv = x0 + (px - m.l) / (W - m.l - m.r) * (x1 - x0);
    let best = allX[0];
    for (const v of allX) if (Math.abs(v - xv) < Math.abs(best - xv)) best = v;
    cross.setAttribute('x1', X(best)); cross.setAttribute('x2', X(best)); cross.setAttribute('opacity', 1);
    const rows = series.map(s => {
      const p = s.points.find(q => q[0] === best);
      return p && p[1] != null ? `<div class="r"><span><span class="swatch" style="background:${s.color}"></span> ${s.name}</span><b>${yFmt(p[1])}</b></div>` : '';
    }).join('');
    showTip(`<b>${xFmt(best)}</b>${rows}`, ev.clientX, ev.clientY);
  });
  hit.addEventListener('mouseleave', () => { cross.setAttribute('opacity', 0); hideTip(); });
  return { svg, X, Y };
}

/** Horizontal interval chart (forest plot). rows: {label, color, mean, lo, hi, note} */
export function forest(container, rows, { fmt = v => v.toFixed(1), unit = '' } = {}) {
  container.innerHTML = '';
  const W = container.clientWidth || 560, rowH = 34, m = { l: 128, r: 24, t: 10, b: 28 };
  const H = m.t + m.b + rows.length * rowH;
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'interval chart' }, container);
  const vals = rows.flatMap(r => [r.lo, r.hi, r.mean]).concat([0]);
  const ticks = niceTicks(Math.min(...vals), Math.max(...vals), 5);
  const x0 = ticks[0], x1 = ticks[ticks.length - 1];
  const X = v => m.l + (v - x0) / (x1 - x0 || 1) * (W - m.l - m.r);
  const g = el('g', { class: 'grid' }, svg);
  for (const t of ticks) el('line', { x1: X(t), x2: X(t), y1: m.t, y2: H - m.b }, g);
  const ax = el('g', { class: 'axis' }, svg);
  for (const t of ticks) el('text', { x: X(t), y: H - 8, 'text-anchor': 'middle' }, ax).textContent = fmt(t);
  el('line', { x1: X(0), x2: X(0), y1: m.t - 4, y2: H - m.b, stroke: '#94a3b8', 'stroke-width': 1.5 }, svg);
  rows.forEach((r, i) => {
    const y = m.t + i * rowH + rowH / 2;
    el('rect', { x: 0, y: y - 9, width: 10, height: 10, rx: 2, fill: r.color }, svg).setAttribute('transform', `translate(0,2)`);
    el('text', { x: 16, y: y + 4, class: 'lbl', fill: 'var(--text-2)' }, svg).textContent = r.label;
    const sig = r.lo > 0 || r.hi < 0;
    el('line', { x1: X(r.lo), x2: X(r.hi), y1: y, y2: y, stroke: r.color, 'stroke-width': 2 }, svg);
    for (const v of [r.lo, r.hi]) el('line', { x1: X(v), x2: X(v), y1: y - 6, y2: y + 6, stroke: r.color, 'stroke-width': 2 }, svg);
    el('circle', { cx: X(r.mean), cy: y, r: 5.5, fill: sig ? r.color : 'var(--card)', stroke: r.color, 'stroke-width': 2 }, svg);
    const hit = el('rect', { x: m.l, y: y - rowH / 2, width: W - m.l - m.r, height: rowH, fill: 'transparent' }, svg);
    hit.addEventListener('mousemove', ev => showTip(`<b>${r.label}</b><div class="r"><span>mean</span><b>${fmt(r.mean)} ${unit}</b></div><div class="r"><span>95% CI</span><b>${fmt(r.lo)} … ${fmt(r.hi)}</b></div><div>${sig ? 'Significant: the interval excludes 0' : 'Not significant: the interval includes 0'}</div>${r.note ? `<div>${r.note}</div>` : ''}`, ev.clientX, ev.clientY));
    hit.addEventListener('mouseleave', hideTip);
  });
}

/** Horizontal stacked bars. rows: {label, color, parts: [{name, value, fill}]} */
export function stacked(container, rows, { fmt = v => Math.round(v).toLocaleString(), parts } = {}) {
  container.innerHTML = '';
  const lg = document.createElement('div');
  lg.className = 'legend';
  lg.innerHTML = parts.map(p => `<span><span class="swatch" style="background:${p.fill}"></span>${p.name}</span>`).join('');
  container.appendChild(lg);
  const W = container.clientWidth || 560, rowH = 30, m = { l: 128, r: 70, t: 6, b: 6 };
  const H = m.t + m.b + rows.length * rowH;
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'stacked bars' }, container);
  const max = Math.max(...rows.map(r => r.parts.reduce((a, p) => a + p.value, 0)), 1);
  const X = v => v / max * (W - m.l - m.r);
  rows.forEach((r, i) => {
    const y = m.t + i * rowH + 7, h = rowH - 14;
    el('rect', { x: 0, y: y + 2, width: 10, height: 10, rx: 2, fill: r.color }, svg);
    el('text', { x: 16, y: y + 12, class: 'lbl', fill: 'var(--text-2)' }, svg).textContent = r.label;
    let x = m.l, total = 0;
    r.parts.forEach(p => {
      const w = X(p.value);
      if (w > 0.5) {
        const rect = el('rect', { x, y, width: Math.max(w - 2, 1), height: h, rx: 3, fill: p.fill }, svg);
        rect.addEventListener('mousemove', ev => showTip(`<b>${r.label}</b><div class="r"><span>${p.name}</span><b>${fmt(p.value)}</b></div>`, ev.clientX, ev.clientY));
        rect.addEventListener('mouseleave', hideTip);
      }
      x += w; total += p.value;
    });
    el('text', { x: x + 6, y: y + 12, class: 'lbl' }, svg).textContent = fmt(total);
  });
}

/** Simple horizontal bars, one per row. rows: {label, color, value, text} */
export function bars(container, rows, { fmt = v => v.toLocaleString(), max } = {}) {
  container.innerHTML = '';
  const W = container.clientWidth || 520, rowH = 30, m = { l: 128, r: 92 };
  const H = rows.length * rowH + 4;
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'bars' }, container);
  const mx = max ?? Math.max(...rows.map(r => r.value), 1);
  rows.forEach((r, i) => {
    const y = i * rowH + 8, h = rowH - 16;
    el('rect', { x: 0, y: y + 1, width: 10, height: 10, rx: 2, fill: r.color }, svg);
    el('text', { x: 16, y: y + 11, class: 'lbl', fill: 'var(--text-2)' }, svg).textContent = r.label;
    const w = Math.max(2, r.value / mx * (W - m.l - m.r));
    const rect = el('rect', { x: m.l, y, width: w, height: h, rx: 4, fill: r.color }, svg);
    el('text', { x: m.l + w + 6, y: y + 11, class: 'lbl' }, svg).textContent = r.text ?? fmt(r.value);
    rect.addEventListener('mousemove', ev => showTip(`<b>${r.label}</b><div class="r"><span>${r.metric || ''}</span><b>${r.text ?? fmt(r.value)}</b></div>`, ev.clientX, ev.clientY));
    rect.addEventListener('mouseleave', hideTip);
  });
}
