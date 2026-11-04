// Charts: cost composition (stacked bars with 2px surface gaps) and the break-even line chart (SVG).
import { t, comp } from './i18n.js';
import { esc, euro, num, PEND, thumb, unitName, carShort, carLabel, carLink, store } from './ui.js';

export function costStack(us, comps, costSel, p, selCost) {
  const on = k => costSel.has(k), idx = k => comps.indexOf(k) + 1;
  const pos = u => comps.filter(on).reduce((a, k) => a + Math.max(0, u.components[k] ?? 0), 0);
  const max = Math.max(1, ...us.map(pos));
  return us.map(u => {
    const segs = comps.filter(on).map(k => { const v = u.components[k]; if (v == null || v <= 0) return '';
      return `<div class="segm" style="flex:${v} 1 0;background:var(--s${idx(k)})" data-tip="${esc(comp(k))}: ${esc(euro(v))} (${num(v / pos(u) * 100, 0)} %)"></div>`; }).join('');
    const neg = comps.filter(on).filter(k => (u.components[k] ?? 0) < 0);
    const sc = selCost(u), miss = sc.missing.length, nsel = comps.filter(on).length;
    return `<div class="crow"><div class="lbl who">${thumb(u)}<span>${carLink(u, unitName(u))}<small>${u.is_reference ? t('reference') : esc(u.listing_id ?? '')}</small></span></div>
      <div class="track"><div class="cstack" style="width:${pos(u) / max * 100}%">${segs}</div></div>
      <div class="after"><span class="tot">${miss && miss === nsel ? PEND() : euro(sc.sum)}${sc.complete ? ` <span class="muted small">· ${euro(sc.sum / (p.ownership_years * 12))}${t('per_month')}</span>` : ''}</span>
        ${miss && miss < nsel ? `<span class="gap" title="${esc(sc.missing.map(comp).join(', '))}"><i class="segm hatch"></i>+${t('pendings', { n: miss })}</span>` : ''}
        ${neg.length ? `<span class="gap">${neg.map(k => esc(comp(k)) + ' ' + esc(euro(u.components[k]))).join(', ')}</span>` : ''}</div></div>`;
  }).join('');
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
  const col = {}; let k = 0; for (const u of ready) col[u.id] = ids.has(u.id) ? `var(--s${(k++ % 8) + 1})` : null;
  return col;  // null = not drawn (toggle in the legend)
}
export function beChart(ref, ready, beHi) {
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
  return `<div class="card be be-wrap"><div class="legend"><span><i class="sw" style="background:var(--text-3)"></i>${t('be_keep', { u: carLabel(ref) })}</span>${ready.map(u => `<button type="button" class="chipbtn" data-behi="${u.id}" aria-pressed="${!!colr[u.id]}" title="${t('be_hi_hint')}"><i class="sw" style="background:${colr[u.id] || 'transparent'}"></i>${carLabel(u)}</button>`).join('')}</div>
    <div class="row small muted" style="margin-bottom:8px"><span>${t('be_hi_lead')}</span><button type="button" class="linkbtn" data-beset="top">${t('be_hi_top')}</button><button type="button" class="linkbtn" data-beset="all">${t('cp_all')}</button><button type="button" class="linkbtn" data-beset="none">${t('cp_none')}</button></div>
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${t('be_title')}" data-be>
      <g class="grid">${nt.ticks.map(v => `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/>`).join('')}</g>
      <g class="axis">${nt.ticks.map(v => `<text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${euro(v)}</text>`).join('')}${mt.map(m => `<text x="${x(m)}" y="${H - B + 18}" text-anchor="middle">${m}</text>`).join('')}<text x="${(L + W - R) / 2}" y="${H - 2}" text-anchor="middle">${t('months')}</text></g>
      <path d="${run(keep.keep)}" fill="none" stroke="${refCol}" stroke-width="2" stroke-dasharray="6 4"/>${drop(keep.keep[N], keep.keepEnd, refCol)}
      ${lines}${lbl}<line class="xhair" y1="${T}" y2="${H - B}" x1="0" x2="0" style="opacity:0"/><rect x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent"/>
    </svg><div id="betip"></div><p class="small muted" style="margin:8px 0 0">${t('be_note')}</p></div>`;
}
export function beTable(ready) {
  return `<div class="tablewrap" style="margin-top:12px"><table><thead><tr><th>${t('g_unit')}</th><th class="n">${t('be_upfront')}</th><th class="n">${t('be_running')}</th><th class="n">${t('be_saving')}</th><th class="n">${t('be_payback')}</th><th class="n">${t('be_end')}</th></tr></thead><tbody>
    ${ready.map(u => { const b = u.breakeven, sv = b.ref_monthly - b.monthly; return `<tr><td>${carLink(u)}</td><td class="n">${euro(b.upfront)}</td><td class="n">${euro(b.monthly)}${t('per_month')}</td>
      <td class="n"><span class="${sv > 0 ? 'down' : 'up'}">${euro(sv)}${t('per_month')}</span></td><td class="n">${b.payback_months == null ? t('never') : b.payback_months > b.months ? t('after_period', { n: num(b.payback_months, 0) }) : t('n_months', { n: num(b.payback_months, 0) })}</td>
      <td class="n"><span class="${b.end_advantage >= 0 ? 'down' : 'up'}">${b.end_advantage >= 0 ? t('be_switch_better', { v: euro(b.end_advantage) }) : t('be_keep_better', { v: euro(-b.end_advantage) })}</span></td></tr>`; }).join('')}</tbody></table></div>`;
}
export function beHover(e, ref, ready, beHi) {
  const svg = e.target.closest('[data-be]'); const tipEl = document.getElementById('betip');
  if (!svg) { if (tipEl) { tipEl.style.opacity = 0; document.querySelectorAll('.xhair').forEach(l => l.style.opacity = 0); } return; }
  if (!ready.length) return;
  const N = ready[0].breakeven.months, box = svg.getBoundingClientRect(), { W, L, R } = BE, sx = box.width / W;
  const m = Math.max(0, Math.min(N, Math.round(((e.clientX - box.left) / sx - L) / (W - L - R) * N)));
  const xh = svg.querySelector('.xhair'), px = L + (W - L - R) * m / N; xh.setAttribute('x1', px); xh.setAttribute('x2', px); xh.style.opacity = 1;
  const b0 = ready[0].breakeven, end = m === N, colr = beColors(ready, beHi);
  const row = (col, name, v, after) => `<div class="tiprow"><i class="sw" style="background:${col}"></i><span>${name}</span><b>${euro(v)}</b>${end ? `<span class="tipend">→ ${euro(after)}</span>` : ''}</div>`;
  const rows = [{ col: 'var(--text-3)', name: carLabel(ref), v: b0.ref_monthly * m, after: b0.ref_monthly * N + b0.ref_tx - b0.ref_resale_end },
    ...ready.filter(u => colr[u.id]).map(u => { const b = u.breakeven; return { col: colr[u.id], name: carLabel(u), v: b.upfront + b.monthly * m, after: b.upfront + b.monthly * N - b.resale_end }; })];
  rows.sort((a, b) => (end ? a.after - b.after : a.v - b.v));
  tipEl.innerHTML = `<b>${t('month_n', { n: m })}</b>${end ? ` <span class="tipend">→ ${t('be_end')}</span>` : ''}${rows.map(r => row(r.col, r.name, r.v, r.after)).join('')}`;
  tipEl.style.opacity = 1; const wrap = svg.parentElement.getBoundingClientRect(), cx = e.clientX - wrap.left;
  tipEl.style.left = (cx + 12 + tipEl.offsetWidth > wrap.width - 8 ? Math.max(8, cx - 12 - tipEl.offsetWidth) : cx + 12) + 'px'; tipEl.style.top = (e.clientY - wrap.top + 12) + 'px';
}
