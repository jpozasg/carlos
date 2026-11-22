// Charts: cost composition (stacked bars with 2px surface gaps) and the break-even line chart (SVG).
import { t, comp } from './i18n.js';
import { esc, euro, num, PEND, thumb, unitName, carShort, carLabel, carLink, store } from './ui.js';

export function costStack(us, comps, costSel, selCost) {
  const on = k => costSel.has(k), idx = k => comps.indexOf(k) + 1, sel = comps.filter(on), all = sel.length === comps.length;
  const pos = u => sel.reduce((a, k) => a + Math.max(0, u.components[k] ?? 0), 0);
  const max = Math.max(1, ...us.map(pos));
  const rows = us.map(u => {
    const segs = sel.map(k => { const v = u.components[k]; if (v == null || v <= 0) return '';
      return `<div class="segm" data-style="flex:${v} 1 0;background:var(--s${idx(k)})" data-tip="${esc(comp(k))}: ${esc(euro(v))} (${num(v / pos(u) * 100, 0)} %)"></div>`; }).join('');
    const neg = sel.filter(k => (u.components[k] ?? 0) < 0);
    const sc = selCost(u), miss = sc.missing.length, nsel = sel.length;
    const tot = miss && miss === nsel ? PEND() : euro(sc.sum);
    // per month only from the server's figure, and only when every component is counted (the browser never divides a subset)
    const pm = sc.complete && all && u.period_months && u.known_cost_per_month != null ? ` <span class="muted small">· ${euro(u.known_cost_per_month)}${t('per_month')}</span>` : '';
    const name = [u.make, u.model].filter(Boolean).join(' ');
    const items = sel.filter(k => u.components[k] != null).map(k => `${comp(k)} ${euro(u.components[k])}`).join(', ');
    const label = t('cs_summary', { car: name, items, total: miss === nsel ? t('pending') : euro(sc.sum) })
      + (miss ? ' ' + t('cs_missing', { list: sc.missing.map(comp).join(', ') }) : '');
    return `<div class="crow"><div class="lbl who">${thumb(u)}<span>${carLink(u, unitName(u))}<small>${u.is_reference ? t('reference') : esc(u.listing_id ?? '')}</small></span></div>
      <div class="track" role="img" aria-label="${esc(label)}"><div class="cstack" data-style="width:${pos(u) / max * 100}%">${segs}</div></div>
      <div class="after"><span class="tot">${tot}${pm}</span>
        ${miss && miss < nsel ? `<span class="gap" title="${esc(sc.missing.map(comp).join(', '))}"><i class="segm hatch"></i>+${t('pendings', { n: miss })}</span>` : ''}
        ${neg.length ? `<span class="gap">${neg.map(k => esc(comp(k)) + ' ' + esc(euro(u.components[k]))).join(', ')}</span>` : ''}</div></div>`;
  }).join('');
  if (!us.length) return '';
  // the text alternative of the bars (screen readers and no-hover users): the same figures, one row per car
  const table = `<table class="sr-only"><caption>${t('cs_table')}</caption><thead><tr><th scope="col">${t('g_unit')}</th>${sel.map(k => `<th scope="col">${esc(comp(k))}</th>`).join('')}<th scope="col">${t('cs_total')}</th></tr></thead><tbody>${us.map(u => {
    const sc = selCost(u);
    return `<tr><th scope="row">${esc([u.make, u.model].filter(Boolean).join(' '))}</th>${sel.map(k => `<td>${u.components[k] == null ? esc(t('pending')) : esc(euro(u.components[k]))}</td>`).join('')}<td>${sc.missing.length === sel.length ? esc(t('pending')) : esc(euro(sc.sum))}</td></tr>`; }).join('')}</tbody></table>`;
  return rows + table;
}

const BE = { W: 1100, H: 380, L: 72, R: 200, T: 16, B: 40 };
const beSeries = u => { const b = u.breakeven, N = b.months;
  return { keep: [...Array(N + 1)].map((_, m) => b.ref_monthly * m), buy: [...Array(N + 1)].map((_, m) => b.upfront + b.monthly * m),
    keepEnd: b.ref_monthly * N + b.ref_tx - b.ref_resale_end, buyEnd: b.upfront + b.monthly * N - b.resale_end }; };
function niceTicks(lo, hi, n = 5) { const raw = (hi - lo) / n || 1, mag = 10 ** Math.floor(Math.log10(raw)), step = [1, 2, 2.5, 5, 10].map(f => f * mag).find(s => s >= raw);
  const a = Math.floor(lo / step) * step, b = Math.ceil(hi / step) * step; return { lo: a, hi: b, ticks: [...Array(Math.round((b - a) / step) + 1)].map((_, i) => a + i * step) }; }
function spread(items, minGap, top, bottom) { items.sort((a, b) => a.y - b.y);
  items.forEach((it, i) => { it.ly = i ? Math.max(it.y, items[i - 1].ly + minGap) : Math.max(it.y, top); });
  const over = items.length ? items[items.length - 1].ly - bottom : 0;
  if (over > 0) { items[items.length - 1].ly -= over; for (let i = items.length - 2; i >= 0; i--) items[i].ly = Math.min(items[i].ly, items[i + 1].ly - minGap); }
  return items; }
export function beColors(ready, beHi) {
  const end = u => u.breakeven.upfront + u.breakeven.monthly * u.breakeven.months - u.breakeven.resale_end;
  const ids = new Set(beHi ? beHi.filter(id => ready.some(u => u.id === id)) : ready.slice().sort((a, b) => end(a) - end(b)).slice(0, 5).map(u => u.id));
  const col = {}; ready.forEach((u, i) => { col[u.id] = ids.has(u.id) ? `var(--s${(i % 8) + 1})` : null; });
  return col;  // null = not drawn (toggle in the legend)
}
export function beChart(ref, ready, beHi) {
  beArgs = { ref, ready, beHi };
  const N = ready[0].breakeven.months, { W, H, L, R, T, B } = BE;
  const colr = beColors(ready, beHi), ser = ready.map(beSeries);
  const all = [...ser[0].keep, ser[0].keepEnd, ...ser.filter((_, i) => colr[ready[i].id]).flatMap(s => [...s.buy, s.buyEnd])];
  const nt = niceTicks(Math.min(0, ...all), Math.max(...all)), lo = nt.lo, hi = nt.hi;
  const x = m => L + (W - L - R) * m / N, y = v => T + (H - T - B) * (1 - (v - lo) / ((hi - lo) || 1));
  const mt = [...Array(Math.floor(N / 12) + 1)].map((_, i) => i * 12).filter(m => m <= N); if (mt[mt.length - 1] !== N) mt.push(N);
  const run = arr => 'M' + arr.map((v, m) => `${x(m).toFixed(1)},${y(v).toFixed(1)}`).join('L');
  const drop = (from, to, col) => `<line x1="${x(N)}" x2="${x(N)}" y1="${y(from)}" y2="${y(to)}" stroke="${col}" stroke-width="2" stroke-dasharray="2 3" opacity=".8"/><circle cx="${x(N)}" cy="${y(to)}" r="4" fill="${col}" stroke="var(--surface)" stroke-width="2"/>`;
  const keep = ser[0], refCol = 'var(--text-3)';
  const series = [{ name: carShort(ref), col: refCol, end: keep.keepEnd }, ...ready.map((u, i) => ({ name: carShort(u), col: colr[u.id], end: ser[i].buyEnd })).filter(s => s.col)];
  const labels = spread(series.map(s => ({ ...s, y: y(s.end) })), 15, T + 4, H - B);
  const lines = ready.map((u, i) => { const s = ser[i], b = u.breakeven, pb = b.payback_months, col = colr[u.id];
    if (!col) return '';
    const dot = pb != null && pb <= N ? `<circle cx="${x(pb)}" cy="${y(b.upfront + b.monthly * pb)}" r="5" fill="${col}" stroke="var(--surface)" stroke-width="2"><title>${esc(t('pays_off', { n: num(pb, 0) }))}</title></circle>` : '';
    return `<path d="${run(s.buy)}" fill="none" stroke="${col}" stroke-width="2" stroke-linejoin="round"/>${drop(s.buy[N], s.buyEnd, col)}${dot}`; }).join('');
  const lbl = labels.map(l => `${Math.abs(l.ly - l.y) > 3 ? `<line x1="${x(N) + 5}" x2="${x(N) + 12}" y1="${l.y}" y2="${l.ly}" stroke="${l.col}" stroke-width="1"/>` : ''}<text class="lbl" x="${x(N) + 14}" y="${l.ly + 4}">${l.name} <tspan class="lblv">${euro(l.end)}</tspan></text>`).join('');
  return `<div class="card be be-wrap"><div class="legend"><span><i class="sw bg-text3"></i>${t('be_keep', { u: carLabel(ref) })}</span>${ready.map(u => `<button type="button" class="chipbtn" data-behi="${u.id}" aria-pressed="${!!colr[u.id]}" title="${t('be_hi_hint')}"><i class="sw" data-style="background:${colr[u.id] || 'transparent'}"></i>${carLabel(u)}</button>`).join('')}</div>
    <div class="row small muted mb8"><span>${t('be_hi_lead')}</span><button type="button" class="linkbtn" data-beset="top">${t('be_hi_top')}</button><button type="button" class="linkbtn" data-beset="all">${t('cp_all')}</button><button type="button" class="linkbtn" data-beset="none">${t('cp_none')}</button></div>
    <svg viewBox="0 0 ${W} ${H}" role="img" tabindex="0" aria-label="${t('be_title')}" data-be>
      <g class="grid">${nt.ticks.map(v => `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/>`).join('')}</g>
      <g class="axis">${nt.ticks.map(v => `<text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${euro(v)}</text>`).join('')}${mt.map(m => `<text x="${x(m)}" y="${H - B + 18}" text-anchor="middle">${m}</text>`).join('')}<text x="${(L + W - R) / 2}" y="${H - 2}" text-anchor="middle">${t('months')}</text></g>
      <path d="${run(keep.keep)}" fill="none" stroke="${refCol}" stroke-width="2" stroke-dasharray="6 4"/>${drop(keep.keep[N], keep.keepEnd, refCol)}
      ${lines}${lbl}<line class="xhair op0" y1="${T}" y2="${H - B}" x1="0" x2="0" /><rect x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent"/>
    </svg><div id="betip"></div><p class="small muted mt8 mx0 mb0">${t('be_note')}</p></div>`;
}
export function beTable(ready) {
  return `<div class="tablewrap mt12"><table><thead><tr><th>${t('g_unit')}</th><th class="n">${t('be_upfront')}</th><th class="n">${t('be_running')}</th><th class="n">${t('be_saving')}</th><th class="n">${t('be_payback')}</th><th class="n">${t('be_end')}</th></tr></thead><tbody>
    ${ready.map(u => { const b = u.breakeven, sv = b.ref_monthly - b.monthly; return `<tr><td>${carLink(u)}</td><td class="n">${euro(b.upfront)}</td><td class="n">${euro(b.monthly)}${t('per_month')}</td>
      <td class="n"><span class="${sv > 0 ? 'down' : 'up'}">${euro(sv)}${t('per_month')}</span></td><td class="n">${b.payback_months == null ? t('never') : b.payback_months > b.months ? t('after_period', { n: num(b.payback_months, 0) }) : t('n_months', { n: num(b.payback_months, 0) })}</td>
      <td class="n"><span class="${b.end_advantage >= 0 ? 'down' : 'up'}">${b.end_advantage >= 0 ? t('be_switch_better', { v: euro(b.end_advantage) }) : t('be_keep_better', { v: euro(-b.end_advantage) })}</span></td></tr>`; }).join('')}</tbody></table></div>`;
}
// the break-even tooltip: pointer, tap and keyboard focus show the same one. beCur = the month drawn (null = hidden);
// beArgs = the chart on screen (beChart and beHover set it); one pointer frame per animation frame (one layout read)
let beCur = null, beArgs = null, beFrame = 0, beEv = null;
function beMonth(svg, clientX, ready) {
  const N = ready[0].breakeven.months, box = svg.getBoundingClientRect(), { W, L, R } = BE, sx = box.width / W;
  return Math.max(0, Math.min(N, Math.round(((clientX - box.left) / sx - L) / (W - L - R) * N)));
}
function beHide() {
  if (beCur === null) return;  // already hidden
  beCur = null; const tipEl = document.getElementById('betip'); if (tipEl) tipEl.style.opacity = 0;
  document.querySelectorAll('.xhair').forEach(l => l.style.opacity = 0);
}
function beDraw(svg, m, x, y) {  // x, y: the pointer (client px) the tooltip sits under
  const { ref, ready, beHi } = beArgs, N = ready[0].breakeven.months, { W, L, R } = BE, tipEl = document.getElementById('betip');
  beCur = m;
  const xh = svg.querySelector('.xhair'), px = L + (W - L - R) * m / N; xh.setAttribute('x1', px); xh.setAttribute('x2', px); xh.style.opacity = 1;
  const b0 = ready[0].breakeven, end = m === N, colr = beColors(ready, beHi);
  const row = (col, name, v, after) => `<div class="tiprow"><i class="sw" data-style="background:${col}"></i><span>${name}</span><b>${euro(v)}</b>${end ? `<span class="tipend">→ ${euro(after)}</span>` : ''}</div>`;
  const rows = [{ col: 'var(--text-3)', name: carLabel(ref), v: b0.ref_monthly * m, after: b0.ref_monthly * N + b0.ref_tx - b0.ref_resale_end },
    ...ready.filter(u => colr[u.id]).map(u => { const b = u.breakeven; return { col: colr[u.id], name: carLabel(u), v: b.upfront + b.monthly * m, after: b.upfront + b.monthly * N - b.resale_end }; })];
  rows.sort((a, b) => (end ? a.after - b.after : a.v - b.v));
  tipEl.innerHTML = `<b>${t('month_n', { n: m })}</b>${end ? ` <span class="tipend">→ ${t('be_end')}</span>` : ''}${rows.map(r => row(r.col, r.name, r.v, r.after)).join('')}`;
  tipEl.style.opacity = 1; const wrap = svg.parentElement.getBoundingClientRect(), cx = x - wrap.left;
  tipEl.style.left = (cx + 12 + tipEl.offsetWidth > wrap.width - 8 ? Math.max(8, cx - 12 - tipEl.offsetWidth) : cx + 12) + 'px'; tipEl.style.top = (y - wrap.top + 12) + 'px';
}
function beAtPointer(e) {
  const svg = e.target.closest('[data-be]');
  if (!svg) return beHide();
  if (!beArgs.ready.length) return;
  const m = beMonth(svg, e.clientX, beArgs.ready);
  if (m !== beCur) beDraw(svg, m, e.clientX, e.clientY);  // same month: nothing to redraw
}
export function beHover(e, ref, ready, beHi) {
  if (!ready.length) return beHide();
  beArgs = { ref, ready, beHi }; beEv = e;
  if (!beFrame) beFrame = requestAnimationFrame(() => { beFrame = 0; beAtPointer(beEv); });
}
// a tap shows the tooltip under the finger; a tap elsewhere hides it
document.addEventListener('click', e => {
  if (!beArgs) return;
  const svg = e.target.closest?.('[data-be]');
  if (!svg) return beHide();
  const m = beMonth(svg, e.clientX, beArgs.ready); if (m !== beCur) beDraw(svg, m, e.clientX, e.clientY);
});
// keyboard: focus shows the tooltip at the start, arrows and Home/End move along the months, Escape or leaving hides it
function beKeyPoint(svg, m) { const box = svg.getBoundingClientRect(), { W, L, R } = BE, N = beArgs.ready[0].breakeven.months;
  return { x: box.left + (L + (W - L - R) * m / N) * box.width / W, y: box.top + 16 }; }
document.addEventListener('focusin', e => {
  const svg = e.target.closest?.('[data-be]'); if (!svg || !beArgs) return;
  const m = beCur ?? 0, p = beKeyPoint(svg, m); beDraw(svg, m, p.x, p.y);
});
document.addEventListener('focusout', e => { if (e.target.closest?.('[data-be]')) beHide(); });
document.addEventListener('keydown', e => {
  const svg = e.target.closest?.('[data-be]'); if (!svg || !beArgs) return;
  if (e.key === 'Escape') return beHide();
  const N = beArgs.ready[0].breakeven.months, m0 = beCur ?? 0;
  const m = ({ ArrowLeft: m0 - 1, ArrowRight: m0 + 1, Home: 0, End: N })[e.key];
  if (typeof m !== 'number') return;
  e.preventDefault(); const mm = Math.max(0, Math.min(N, m)), p = beKeyPoint(svg, mm); beDraw(svg, mm, p.x, p.y);
});
