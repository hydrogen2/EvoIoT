/* The component library — the nouns of the app layer.
 *
 * Hand-built render primitives the view runtime mounts from a spec. This is
 * the one deliberately-traditional part of the app layer: small, tested,
 * dependency-free. Views compose these; they never ship their own JS.
 *
 * Palette: the dataviz reference instance, dark mode (validated as a set on
 * surface #1a1a19 — swap values only together with a validator re-run).
 */

const P = {
  series: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'],
  good: '#0ca30c', warning: '#fab219', serious: '#ec835a', critical: '#d03b3b',
  ink: '#ffffff', ink2: '#c3c2b7', muted: '#898781',
  grid: '#2c2c2a', axis: '#383835', surface: '#1a1a19',
};

const SVG = 'http://www.w3.org/2000/svg';

function el(tag, attrs = {}, parent = null) {
  const ns = ['svg', 'g', 'path', 'rect', 'line', 'text', 'circle'].includes(tag);
  const e = ns ? document.createElementNS(SVG, tag) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'text') e.textContent = v;
    else if (k === 'style') e.style.cssText = v;
    else e.setAttribute(k, v);
  }
  if (parent) parent.appendChild(e);
  return e;
}

function fmt(v, prec = 1) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  if (typeof v !== 'number') return String(v);
  const a = Math.abs(v);
  if (Number.isInteger(v) && a < 100000) return v.toLocaleString();
  if (a >= 10000) return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return v.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: prec });
}

function fmtAge(s) {
  if (s == null) return '';
  if (s < 90) return `${s}s ago`;
  if (s < 5400) return `${Math.round(s / 60)}m ago`;
  return `${Math.round(s / 3600)}h ago`;
}

function empty(root, msg) {
  el('div', { text: msg, style: `color:${P.muted};font-size:13px;padding:18px 4px` }, root);
}

/* one shared tooltip */
let tipEl = null;
function tip(html, x, y) {
  if (!tipEl) {
    tipEl = el('div', { style: `position:fixed;z-index:50;pointer-events:none;background:#26262a;border:1px solid rgba(255,255,255,.1);border-radius:7px;padding:7px 10px;font-size:12px;color:${P.ink2};box-shadow:0 4px 16px rgba(0,0,0,.5);max-width:320px` });
    document.body.appendChild(tipEl);
  }
  tipEl.innerHTML = html;
  tipEl.style.display = 'block';
  const w = tipEl.offsetWidth, sw = window.innerWidth;
  tipEl.style.left = `${Math.min(x + 14, sw - w - 8)}px`;
  tipEl.style.top = `${y + 14}px`;
}
function tipHide() { if (tipEl) tipEl.style.display = 'none'; }

function niceTicks(lo, hi, n = 4) {
  if (lo === hi) { lo -= 1; hi += 1; }
  const span = hi - lo, step0 = span / n;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => span / s <= n + 1) || mag * 10;
  const t0 = Math.ceil(lo / step) * step, ticks = [];
  for (let t = t0; t <= hi + 1e-9; t += step) ticks.push(+t.toFixed(10));
  return ticks;
}

/* ── stat ── */
function stat(root, data, props) {
  const prec = props.precision ?? 1;
  const unit = props.unit ?? data.unit ?? '';
  const wrap = el('div', { style: 'padding:2px 0' }, root);
  const row = el('div', { style: 'display:flex;align-items:baseline;gap:7px' }, wrap);
  el('span', { text: fmt(data.value, prec), style: `font-size:32px;font-weight:650;color:${P.ink};letter-spacing:-.5px` }, row);
  if (unit) el('span', { text: unit, style: `font-size:15px;color:${P.ink2}` }, row);
  if (data.n > 1) el('div', { text: `across ${data.n} points`, style: `color:${P.muted};font-size:12px;margin-top:3px` }, wrap);
  if (data.value === null) empty(wrap, 'no matching live points');
}

/* ── trend ── */
function trend(root, data, props) {
  const series = (data.series || []).filter(s => s.points && s.points.length);
  if (!series.length) return empty(root, 'no data in window');
  const prec = props.precision ?? 1;
  const unit = props.unit ?? series.find(s => s.unit)?.unit ?? '';
  const colors = series.map((_, i) => P.series[i % P.series.length]);

  const W = Math.max(root.clientWidth || 560, 280), H = 210;
  const m = { l: 46, r: series.length <= 4 ? 14 : 14, t: 10, b: 24 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;

  let xs = [], ys = [];
  series.forEach(s => s.points.forEach(([t, v]) => { xs.push(t); ys.push(v); }));
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  const pad = (y1 - y0) * 0.06 || Math.abs(y1) * 0.05 || 1;
  y0 -= pad; y1 += pad;
  const X = t => m.l + (x1 === x0 ? iw / 2 : (t - x0) / (x1 - x0) * iw);
  const Y = v => m.t + ih - (v - y0) / (y1 - y0) * ih;

  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, width: '100%', height: H, style: 'display:block' }, root);

  for (const t of niceTicks(y0, y1, 4)) {
    el('line', { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), stroke: P.grid, 'stroke-width': 1 }, svg);
    el('text', { x: m.l - 7, y: Y(t) + 3.5, 'text-anchor': 'end', fill: P.muted, 'font-size': 10.5, style: 'font-variant-numeric:tabular-nums', text: fmt(t, prec) }, svg);
  }
  el('line', { x1: m.l, x2: W - m.r, y1: m.t + ih, y2: m.t + ih, stroke: P.axis, 'stroke-width': 1 }, svg);

  const span = x1 - x0, fmtT = t => {
    const d = new Date(t);
    return span <= 26 * 3600e3
      ? d.toTimeString().slice(0, 5)
      : `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}h`;
  };
  const nx = Math.max(2, Math.min(6, Math.floor(iw / 90)));
  for (let i = 0; i <= nx; i++) {
    const t = x0 + span * i / nx;
    el('text', { x: X(t), y: H - 7, 'text-anchor': i === 0 ? 'start' : i === nx ? 'end' : 'middle', fill: P.muted, 'font-size': 10.5, text: fmtT(t) }, svg);
  }

  series.forEach((s, i) => {
    const d = s.points.map(([t, v], j) => `${j ? 'L' : 'M'}${X(t).toFixed(1)},${Y(v).toFixed(1)}`).join('');
    el('path', { d, fill: 'none', stroke: colors[i], 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }, svg);
  });

  /* direct end labels (≤4 series): colored dot carries identity, text stays ink */
  if (series.length >= 2 && series.length <= 4) {
    const used = [];
    series.forEach((s, i) => {
      const [t, v] = s.points[s.points.length - 1];
      let ly = Y(v);
      while (used.some(u => Math.abs(u - ly) < 12)) ly -= 12;
      used.push(ly);
      el('circle', { cx: X(t), cy: Y(v), r: 3, fill: colors[i] }, svg);
      el('text', { x: X(t) - 5, y: ly - 6, 'text-anchor': 'end', fill: P.ink2, 'font-size': 10.5, text: s.name.length > 26 ? s.name.slice(0, 25) + '…' : s.name }, svg);
    });
  }

  /* crosshair + tooltip over the whole plot */
  const cross = el('line', { y1: m.t, y2: m.t + ih, stroke: P.muted, 'stroke-width': 1, 'stroke-dasharray': '3,3', style: 'display:none' }, svg);
  const hot = el('rect', { x: m.l, y: m.t, width: iw, height: ih, fill: 'transparent' }, svg);
  hot.addEventListener('mousemove', ev => {
    const r = svg.getBoundingClientRect();
    const t = x0 + (ev.clientX - r.left - m.l * r.width / W) / (iw * r.width / W) * span;
    cross.style.display = '';
    const cx = X(Math.max(x0, Math.min(x1, t)));
    cross.setAttribute('x1', cx); cross.setAttribute('x2', cx);
    const lines = series.map((s, i) => {
      let best = s.points[0];
      for (const p of s.points) if (Math.abs(p[0] - t) < Math.abs(best[0] - t)) best = p;
      return `<div style="display:flex;gap:6px;align-items:center"><span style="width:8px;height:8px;border-radius:2px;background:${colors[i]};flex:none"></span><span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${s.name}</span><b style="color:${P.ink};font-variant-numeric:tabular-nums">${fmt(best[1], prec)}${unit ? ' ' + unit : ''}</b></div>`;
    });
    tip(`<div style="color:${P.muted};margin-bottom:4px">${fmtT(t)}</div>` + lines.join(''), ev.clientX, ev.clientY);
  });
  hot.addEventListener('mouseleave', () => { cross.style.display = 'none'; tipHide(); });

  /* legend (≥2 series) + accessibility table toggle */
  const foot = el('div', { style: 'display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-top:6px' }, root);
  if (series.length >= 2) series.forEach((s, i) => {
    const c = el('span', { style: `display:inline-flex;align-items:center;gap:5px;font-size:12px;color:${P.ink2}` }, foot);
    el('span', { style: `width:9px;height:9px;border-radius:2px;background:${colors[i]}` }, c);
    el('span', { text: s.name }, c);
  });
  if (data.dropped_series) el('span', { text: `+${data.dropped_series} more series folded`, style: `font-size:12px;color:${P.muted}` }, foot);
  const tbtn = el('button', { text: '⊞ data', title: 'show as table', style: `margin-left:auto;background:none;border:1px solid ${P.axis};color:${P.muted};border-radius:6px;font-size:11px;padding:2px 8px;cursor:pointer` }, foot);
  let tbl = null;
  tbtn.onclick = () => {
    if (tbl) { tbl.remove(); tbl = null; return; }
    const rows = {};
    series.forEach((s, i) => s.points.forEach(([t, v]) => { (rows[t] = rows[t] || {})[i] = v; }));
    tbl = el('div', { style: 'max-height:200px;overflow:auto;margin-top:6px' }, root);
    table(tbl, { rows: Object.entries(rows).sort((a, b) => a[0] - b[0]).map(([t, vs]) => Object.fromEntries([['time', fmtT(+t)], ...series.map((s, i) => [s.name, vs[i] ?? ''])])) }, {});
  };
}

/* ── bars ── */
function bars(root, data, props) {
  const rows = data.rows || [];
  if (!rows.length) return empty(root, 'no matching live points');
  const prec = props.precision ?? 1;
  const unit = props.unit ?? data.unit ?? '';
  const maxV = Math.max(...rows.map(r => r.value), 0) || 1;
  const wrap = el('div', { style: 'display:flex;flex-direction:column;gap:6px' }, root);
  rows.forEach(r => {
    const row = el('div', { style: 'display:grid;grid-template-columns:130px 1fr 74px;gap:9px;align-items:center;font-size:12.5px' }, wrap);
    el('span', { text: r.label, title: r.label, style: `color:${P.ink2};overflow:hidden;text-overflow:ellipsis;white-space:nowrap` }, row);
    const track = el('div', { style: 'height:15px;position:relative' }, row);
    const w = Math.max(r.value / maxV * 100, 0.5);
    const bar = el('div', { style: `position:absolute;inset:0 auto 0 0;width:${w}%;background:${P.series[0]};border-radius:0 4px 4px 0` }, track);
    el('span', { text: `${fmt(r.value, prec)}${unit ? ' ' + unit : ''}`, style: `color:${P.ink};text-align:right;font-variant-numeric:tabular-nums` }, row);
    bar.addEventListener('mousemove', ev => tip(`${r.label}: <b style="color:${P.ink}">${fmt(r.value, prec)} ${r.unit || unit}</b>`, ev.clientX, ev.clientY));
    bar.addEventListener('mouseleave', tipHide);
  });
}

/* ── table ── */
function table(root, data, props) {
  const rows = data.rows || [];
  if (!rows.length) return empty(root, 'no rows');
  const cols = props.columns && props.columns.length ? props.columns : Object.keys(rows[0]);
  const shown = rows.slice(0, 40);
  const numeric = cols.map(c => shown.every(r => r[c] === '' || r[c] == null || typeof r[c] === 'number'));
  const box = el('div', { style: 'overflow-x:auto' }, root);
  const t = el('table', { style: 'width:100%;border-collapse:collapse;font-size:12.5px' }, box);
  const tr0 = el('tr', {}, el('thead', {}, t));
  cols.forEach((c, i) => el('th', { text: c === 'age_s' ? 'age' : c.replace(/_/g, ' '), style: `text-align:${numeric[i] ? 'right' : 'left'};color:${P.muted};font-weight:500;padding:4px 8px;border-bottom:1px solid ${P.axis};white-space:nowrap` }, tr0));
  const tb = el('tbody', {}, t);
  shown.forEach(r => {
    const tr = el('tr', {}, tb);
    cols.forEach((c, i) => {
      let v = r[c];
      if (c === 'age_s') v = fmtAge(v);
      else if (typeof v === 'number') v = fmt(v, 2);
      el('td', { text: v ?? '', style: `text-align:${numeric[i] ? 'right' : 'left'};color:${P.ink2};padding:4px 8px;border-bottom:1px solid ${P.grid};${numeric[i] ? 'font-variant-numeric:tabular-nums;' : ''}white-space:nowrap` }, tr);
    });
  });
  if (rows.length > shown.length) el('div', { text: `…and ${rows.length - shown.length} more rows`, style: `color:${P.muted};font-size:12px;padding:6px 8px` }, box);
}

/* ── alarms ── */
function alarms(root, data) {
  const rows = data.rows || [];
  if (!rows.length) {
    const ok = el('div', { style: 'display:flex;align-items:center;gap:9px;padding:10px 2px' }, root);
    el('span', { text: '✓', style: `color:${P.good};font-size:18px;font-weight:700` }, ok);
    const t = el('div', {}, ok);
    el('div', { text: 'All clear', style: `color:${P.ink};font-weight:600` }, t);
    el('div', { text: `${data.monitored ?? 0} abnormal-state points monitored, none active`, style: `color:${P.muted};font-size:12px` }, t);
    return;
  }
  const wrap = el('div', { style: 'display:flex;flex-direction:column;gap:7px' }, root);
  rows.forEach(r => {
    const row = el('div', { style: `display:flex;align-items:center;gap:9px;border-left:3px solid ${P.critical};background:rgba(208,59,59,.08);border-radius:4px;padding:7px 10px` }, wrap);
    el('span', { text: '▲', style: `color:${P.critical};font-size:12px` }, row);
    el('span', { text: 'ACTIVE', style: `color:${P.critical};font-size:10.5px;font-weight:700;letter-spacing:.5px` }, row);
    el('span', { text: `${r.equipment} — ${r.point}`, style: `color:${P.ink};font-size:13px;flex:1` }, row);
    el('span', { text: fmtAge(r.age_s), style: `color:${P.muted};font-size:11.5px` }, row);
  });
}

/* ── note ── */
function note(root, _data, props) {
  el('div', { text: props.text || '', style: `color:${P.ink2};font-size:13.5px;line-height:1.6` }, root);
}

window.Components = { stat, trend, bars, table, alarms, note };
window.VizPalette = P;
