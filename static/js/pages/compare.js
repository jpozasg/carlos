// Compare: overview table, cost composition, break-even, detail table, photo cards. State in S (app.js).
import { S, refreshTco, go } from '../app.js';
import { t, tv, comp } from '../i18n.js';
import { $, esc, euro, num, PEND, eP, yrs, store, thumb, unitName, carShort, carLabel, carLink, unitSub, statusTags, CAR_SVG, media, scoreTxt } from '../ui.js';
import { costStack, beChart, beTable, beHover, beColors } from '../charts.js';

const RUNNING = ['fuel', 'insurance', 'tax', 'maintenance', 'repairs', 'tyres'];
const VIEWS = ['ruler', 'overview', 'costs', 'breakeven', 'details', 'photos'];
const SORTS = { score: [u => u.score, 'desc'], price: [u => u.metrics.price, 'asc'], mileage: [u => u.metrics.mileage, 'asc'], age: [u => u.metrics.age, 'asc'],
  km_per_year: [u => u.metrics.km_per_year, 'asc'], consumption: [u => u.metrics.consumption, 'asc'], insurance: [u => u.metrics.insurance, 'asc'],
  tax: [u => u.metrics.tax, 'asc'], cost_month: [u => u.metrics.cost_month, 'asc'], known_month: [u => u.known_cost_per_month, 'asc'],
  power: [u => u.metrics.power, 'desc'], reliability: [u => u.metrics.reliability, 'asc'], inspection: [u => u.metrics.inspection, 'asc'],
  simplicity: [u => u.metrics.simplicity, 'desc'], confidence: [u => u.metrics.confidence, 'desc'],
  selected_cost: [u => { const r = selCost(u); return r.complete ? r.sum : null; }, 'asc'] };
let sortState = store.get('sort', { key: 'score', dir: 'desc' });
let filters = store.get('filters', { overBudget: false, withdrawn: true, pinRef: false });
let selected = new Set(store.get('selected', []));
let costSel = new Set(store.get('costSel', null) ?? []);
let beHi = store.get('beHi', null);
let view = 'overview';

const selComps = () => S.components.filter(k => costSel.has(k));
function selCost(u) { const ks = selComps(), miss = ks.filter(k => u.components[k] == null);
  return { sum: ks.reduce((a, k) => a + (u.components[k] ?? 0), 0), missing: miss, complete: ks.length > 0 && !miss.length }; }
function ordered() {
  const [getv] = SORTS[sortState.key] || SORTS.score, sign = sortState.dir === 'asc' ? 1 : -1;
  const vis = S.units.filter(u => u.is_reference || !((filters.overBudget && u.budget_status === 'over_max') || (filters.withdrawn && u.listing_status === 'WITHDRAWN')));
  return vis.sort((a, b) => { if (a.is_reference !== b.is_reference && (filters.pinRef || getv(a.is_reference ? a : b) == null)) return b.is_reference - a.is_reference;
    const x = getv(a), y = getv(b); if (x == null && y == null) return a.id - b.id; if (x == null) return 1; if (y == null) return -1; return (x - y) * sign || a.id - b.id; });
}
const tagsHtml = u => { const tg = statusTags(u); return tg.length ? `<div class="tags">${tg.join('')}</div>` : ''; };

function versus() {
  const ref = S.units.find(u => u.is_reference); if (!ref) return '';
  const best = S.units.filter(u => u.rank && u.tco_complete).sort((a, b) => a.rank - b.rank)[0];
  const side = (u, label, cls) => `<a class="side ${cls}" href="#/listing/${u.id}">${u.cover ? `<img src="${media(u.cover)}" alt="">` : `<span class="nophoto-sm" aria-hidden="true">${CAR_SVG}</span>`}
    <span style="min-width:0"><span class="who-l">${label}</span><span class="name">${carLabel(u)}</span><span class="cost">${eP(u.known_cost_per_month)}${u.known_cost_per_month == null ? '' : t('per_month')}</span></span></a>`;
  let mid;
  if (!best || ref.known_cost_per_month == null) mid = `<p class="empty-v">${t('versus_none')}</p>`;
  else { const d = ref.known_cost_per_month - best.known_cost_per_month;
    mid = `<div class="n ${d > 0 ? 'down' : d < 0 ? 'up' : ''}">${d === 0 ? '=' : (d > 0 ? '−' : '+') + euro(Math.abs(d))}</div><div class="l">${d > 0 ? t('versus_saves', { v: euro(Math.abs(d)) }) : d < 0 ? t('versus_costs_more', { v: euro(Math.abs(d)) }) : t('versus_even')}</div>
      ${best.delta_vs_reference != null ? `<div class="s">${t('versus_over', { y: S.p.ownership_years, v: euro(-best.delta_vs_reference) })}</div>` : ''}<div class="s">${t('versus_hint')}</div>`; }
  return `<section class="versus" aria-label="${esc(t('versus_title'))}">${side(ref, t('versus_keep'), 'left')}<div class="mid">${mid}</div>${best ? side(best, t('versus_best'), 'right') : '<div></div>'}</section>`;
}
function ruler(all) {
  const ref = S.units.find(u => u.is_reference);
  const vals = all.map(u => u.known_cost_per_month).filter(v => v != null);
  if (!all.length) return `<p class="empty">${t('no_units')}</p>`;
  const none = !vals.length;  // cars exist but no cost is known yet: list them, say why the ruler is empty
  const lo = none ? 0 : Math.min(...vals) * 0.9, hi = none ? 1 : Math.max(...vals) * 1.05 || 1, x = v => (v - lo) / (hi - lo) * 100;
  const step = [10, 20, 25, 50, 100, 200][[10, 20, 25, 50, 100, 200].findIndex(s => (hi - lo) / s <= 7)] || 200;
  const ticks = []; if (!none) for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) ticks.push(v);
  const refX = ref && ref.known_cost_per_month != null ? x(ref.known_cost_per_month) : null;
  const rows = all.map(u => { const v = u.known_cost_per_month, d = u.delta_vs_reference;
    return `<a class="rrow${u.is_reference ? ' ref' : ''}${u.rank === 1 ? ' top' : ''}" href="#/listing/${u.id}">
      <span class="car">${u.is_reference ? '' : `<span class="rk">${u.rank ?? '–'}</span>`}${thumb(u, 'sm')}<span style="min-width:0"><span class="nm">${carLabel(u)}</span><small>${u.is_reference ? t('your_car') : esc(u.location ?? u.platform ?? '')}</small></span></span>
      <span class="rtrack">${refX != null && !u.is_reference ? `<i class="rline" style="left:${refX}%"></i>` : ''}${v == null ? '' : `<i class="rmark${u.is_reference ? ' refmark' : u.tco_complete ? '' : ' partial'}" style="left:${refX ?? x(v)}%" data-x="${x(v)}" title="${esc(euro(v))}${t('per_month')}"></i>`}</span>
      <span class="rval">${v == null ? PEND() : `<b>${euro(v)}</b>${u.is_reference ? '' : d == null ? (u.tco_complete ? '' : `<small class="muted">${t('ruler_partial')}</small>`) : `<small class="${d > 0 ? 'up' : 'down'}">${d > 0 ? '+' : '−'}${euro(Math.abs(d) / (S.p.ownership_years * 12))}${t('per_month')}</small>`}`}</span></a>`; }).join('');
  return `<div class="section"><h2>${t('ruler_title')}</h2><p class="lead">${t(none ? 'ruler_waiting' : 'ruler_lead')}</p>
    <div class="ruler"><div class="rhead"><span class="car-h">${t('g_unit')}</span><span class="ticks">${ticks.map(v => `<span style="left:${x(v)}%">${euro(v)}</span>`).join('')}</span><span style="text-align:right">${t('ruler_axis')}</span></div>${rows}</div></div>`;
}
function overview(all) {
  const dash = '<span class="muted">—</span>';
  const rows = all.map(u => { const on = selected.has(u.id), d = u.delta_vs_reference;
    return `<tr class="${u.is_reference ? 'refrow' : ''}${on || u.is_reference ? '' : ' off'}">
      <td>${u.is_reference ? '' : `<input type="checkbox" ${on ? 'checked' : ''} data-toggle="${u.id}" aria-label="${esc(t('compare'))}: ${esc(u.make + ' ' + u.model)}">`}</td>
      <td class="n">${u.rank ? `<b>${u.rank}</b>` : dash}</td>
      <td><a class="linkbtn car" href="#/listing/${u.id}" title="${t('open_dossier')}">${thumb(u, 'sm')}<span>${esc(u.make)} ${carShort(u)}<small>${u.is_reference ? t('your_car') : esc(u.location ?? u.platform ?? '')}</small></span></a></td>
      <td><div class="sc">${u.score == null ? dash : `<div class="scorebar" aria-hidden="true"><i style="width:${u.score}%"></i></div><b>${scoreTxt(u)}</b>`}</div></td>
      <td class="n">${u.is_reference ? `<span class="muted">${t('owned')}</span>` : eP(u.price_eur)}</td>
      <td class="n">${u.mileage_km == null ? PEND() : num(u.mileage_km, 0)}</td>
      <td class="n">${u.metrics.age == null ? PEND() : num(u.metrics.age, 1)}</td>
      <td class="n">${eP(u.known_cost_per_month)}</td>
      <td class="n"><b>${eP(u.known_cost_subtotal)}</b>${u.tco_complete ? '' : ` <span class="tag warn" title="${esc(u.missing_components.map(comp).join(', '))}">${t('subtotal_partial')}</span>`}</td>
      <td class="n">${u.is_reference ? dash : d == null ? PEND() : `<span class="${d > 0 ? 'up' : 'down'}">${d > 0 ? '▲ +' : '▼ '}${euro(d)}</span>`}</td>
      <td>${tagsHtml(u)}</td></tr>`; }).join('');
  return `<div class="tablewrap"><table class="ov"><thead><tr><th><span class="sr-only">${t('compare')}</span></th><th class="n">#</th><th>${t('g_unit')}</th><th>${t('score')}</th>
    <th class="n">${t('asking_price')}</th><th class="n">${t('km')}</th><th class="n">${t('age')}</th><th class="n">${t('eur_month')}</th><th class="n">${t('ov_total', { y: S.p.ownership_years })}</th>
    <th class="n"><abbr title="${esc(t('delta_help'))}">${t('delta')}</abbr></th><th>${t('ov_status')}</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
function unitCard(u) {
  const n = S.components.length, known = n - u.missing_components.length, on = selected.has(u.id);
  return `<article class="card unit${u.is_reference ? ' is-ref' : ''}${on ? '' : ' off'}">
    <a class="hero" href="#/listing/${u.id}" aria-label="${esc(t('open_dossier_aria', { u: u.make + ' ' + u.model }))}">
      ${u.cover ? `<img src="${media(u.cover)}" alt="${unitName(u)}" loading="lazy">` : `<span class="nophoto"><span>${CAR_SVG}${t('no_photos')}</span></span>`}
      ${u.photo_count ? `<span class="count">📷 ${u.photo_count}</span>` : ''}${u.is_reference ? `<span class="tag ref reftag">${t('reference')}</span>` : ''}
      ${u.rank ? `<span class="rankbadge">${t('rank_n', { n: u.rank })} · ${scoreTxt(u)}</span>` : ''}</a>
    ${tagsHtml(u)}
    <div class="unit-head"><div><div class="unit-name">${carLink(u, unitName(u))}</div><div class="unit-sub">${esc(u.trim ?? '')} · ${unitSub(u)}</div></div></div>
    <div class="kv">${u.is_reference ? `<span>${t('owned')}</span>` : `<span>${t('asking_price')} <b>${eP(u.price_eur)}</b></span>`}<span>${t('km')} <b>${u.mileage_km == null ? PEND() : num(u.mileage_km, 0)}</b></span><span>${t('age')} <b>${u.metrics.age == null ? PEND() : yrs(u.metrics.age)}</b></span>${u.metrics.km_per_year != null ? `<span>${t('km_per_year')} <b>${num(u.metrics.km_per_year, 0)}</b></span>` : ''}</div>
    <div><div class="small muted">${u.tco_complete ? t('tco_complete') : t('subtotal_partial')}</div><div class="big">${eP(u.known_cost_subtotal)}</div>
      <div class="small muted">${u.known_cost_per_month == null ? '' : euro(u.known_cost_per_month) + t('per_month') + ' · ' + num(u.known_cost_per_km, 3) + ' €/km'}</div></div>
    <div><div class="small" style="display:flex;justify-content:space-between"><span>${t('cost_data')}</span><b>${known}/${n}</b></div>
      <div class="meter${known === n ? ' good' : ''}" role="meter" aria-valuemin="0" aria-valuemax="${n}" aria-valuenow="${known}" aria-label="${t('cost_known_aria')}"><i style="width:${known / n * 100}%"></i></div>
      ${u.missing_components.length ? `<div class="tags" style="margin-top:6px">${u.missing_components.map(m => `<span class="tag">${esc(tv(m))}</span>`).join('')}</div>` : ''}</div>
    <div class="small"><span class="muted">${t('verdict')}:</span> ${u.verdict ? esc(u.verdict) : PEND()}</div>
    <div class="unit-foot"><label class="toggle"><input type="checkbox" ${on ? 'checked' : ''} data-toggle="${u.id}"> ${t('compare')}</label><a class="linkbtn" href="#/listing/${u.id}">${t('open_dossier')}</a></div></article>`;
}
function costs(us) {
  const comps = S.components, on = k => costSel.has(k), idx = k => comps.indexOf(k) + 1;
  const legend = `<div class="row" role="group" aria-label="${t('cost_pick')}">${comps.map(k => `<button type="button" class="chipbtn" data-cost="${k}" aria-pressed="${on(k)}"><i class="sw" style="background:var(--s${idx(k)})"></i>${esc(comp(k))}</button>`).join('')}</div>
    <div class="row small" style="margin-top:8px"><span class="muted">${t('cost_presets')}:</span><button type="button" class="linkbtn" data-costset="all">${t('cp_all')}</button><button type="button" class="linkbtn" data-costset="running">${t('cp_running')}</button><button type="button" class="linkbtn" data-costset="none">${t('cp_none')}</button>
      <span class="spacer"></span><button type="button" class="btn ghost sm" data-sortsel aria-pressed="${sortState.key === 'selected_cost'}" ${selComps().length ? '' : 'disabled'}>${sortState.key === 'selected_cost' ? '✓ ' : ''}${t('sort_by_selected')}</button></div>
    <div class="legend" style="margin-top:6px"><span><i class="sw hatch"></i>${t('legend_pending')}</span></div>`;
  if (!selComps().length) return `<div class="card">${legend}<p class="empty">${t('cost_none_selected')}</p></div>`;
  return `<div class="card">${legend}${costStack(us, comps, costSel, S.p, selCost) || `<p class="empty">${t('select_one')}</p>`}<p class="small muted" style="margin:8px 0 0">${t('chart_note')}</p></div>`;
}
function details(us) {
  if (!us.length) return '';
  const dash = '<span class="muted">—</span>';
  const groups = [
    [t('g_unit'), [[t('asking_price'), u => u.is_reference ? `<span class="muted">${t('owned')}</span>` : eP(u.price_eur)], [t('mileage'), u => u.mileage_km == null ? PEND() : num(u.mileage_km, 0) + ' km'],
      [t('age'), u => u.metrics.age == null ? PEND() : yrs(u.metrics.age)], [t('km_per_year'), u => u.metrics.km_per_year == null ? PEND() : num(u.metrics.km_per_year, 0)],
      [t('power'), u => u.power_ps == null ? PEND() : num(u.power_ps, 0) + ' PS'], [t('insurance_year'), u => eP(u.annual_insurance)], [t('tax_year'), u => eP(u.annual_tax)],
      [t('c_reliability'), u => u.metrics.reliability == null ? PEND() : num(u.metrics.reliability, 1)], [t('c_simplicity'), u => u.metrics.simplicity == null ? PEND() : num(u.metrics.simplicity, 1) + ' / 4'],
      [t('c_confidence'), u => u.metrics.confidence == null ? PEND() : num(u.metrics.confidence, 0) + ' %'],
      [t('score'), u => u.is_reference ? dash : u.score == null ? `<span class="pending">${t('not_ranked')}</span>` : `<b>${scoreTxt(u)}</b> <span class="muted">${t('rank_n', { n: u.rank })} · ${num(u.coverage * 100, 0)}% ${t('coverage_short')}</span>`],
      [t('consumption'), u => u.consumption == null ? PEND() : `${num(u.consumption)} l/100 km<br><span class="muted">${num(u.consumption_min)}–${num(u.consumption_max)} · n=${u.consumption_sample ?? '?'}</span>`]]],
    [t('g_use'), ['fuel', 'insurance', 'tax', 'maintenance'].map(k => [esc(comp(k)), u => eP(u.components[k])])],
    [t('g_own'), ['repairs', 'tyres', 'purchase_sale'].map(k => [esc(comp(k)), u => eP(u.components[k])])],
    [t('g_dep'), [[`<abbr title="${esc(t('dep_help'))}">${esc(comp('depreciation'))}</abbr>`, u => eP(u.components.depreciation)]]],
    [t('g_tot'), [[t('selected_total', { n: selComps().length }), u => { const r = selCost(u); return !selComps().length ? dash : r.complete ? `<b>${euro(r.sum)}</b>` : `<span class="pending" title="${esc(r.missing.map(comp).join(', '))}">${t('incomplete_n', { n: r.missing.length })}</span>`; }, 'total'],
      [t('subtotal'), u => eP(u.known_cost_subtotal)], [t('eur_month'), u => eP(u.known_cost_per_month)],
      [t('range'), u => u.tco_pessimistic == null ? PEND() : euro(u.tco_pessimistic) + ' – ' + euro(u.tco_optimistic)],
      [`<abbr title="${esc(t('delta_help'))}">${t('delta')}</abbr>`, u => u.is_reference ? dash : u.delta_vs_reference == null ? `<span class="pending">${t('needs_tco')}</span>` : `<span class="${u.delta_vs_reference > 0 ? 'up' : 'down'}">${u.delta_vs_reference > 0 ? '▲ +' : '▼ '}${euro(u.delta_vs_reference)}</span>`],
      [t('outlay'), u => u.is_reference ? dash : eP(u.initial_outlay)], [t('diy_hours'), u => u.diy_hours == null ? PEND() : num(u.diy_hours, 1) + ' h']]]];
  const head = `<tr><th scope="col">${t('concept')}</th>${us.map(u => `<th scope="col" class="n${u.is_reference ? ' refcol' : ''}"><span class="who" style="justify-content:flex-end">${thumb(u, 'sm')}<span>${carLink(u, unitName(u))}${u.is_reference ? ` <span class="tag ref">${t('ref_short')}</span>` : ''}</span></span></th>`).join('')}</tr>`;
  const body = groups.map(([g, rows]) => `<tr class="grp"><td>${g}</td><td colspan="${us.length}"></td></tr>` + rows.map(([l, f, cls]) => `<tr class="${cls || ''}"><td>${l}</td>${us.map(u => `<td class="n${u.is_reference ? ' refcol' : ''}">${f(u)}</td>`).join('')}</tr>`).join('')).join('');
  return `<div class="tablewrap"><table class="cmp"><thead>${head}</thead><tbody>${body}</tbody></table></div>`;
}
const MISS = s => { const [who, what] = s.split(': '); return `${t(who === 'reference' ? 'reference' : 'car_word')}: ${esc(tv(what) === what ? t('m_' + what.replace(/ /g, '_')) : tv(what))}`; };
function breakeven(us) {
  const ref = S.units.find(u => u.is_reference), cands = us.filter(u => !u.is_reference);
  if (!ref || !cands.length) return `<p class="empty">${t('select_one')}</p>`;
  const ready = cands.filter(u => u.breakeven.ready), notReady = cands.filter(u => !u.breakeven.ready);
  const miss = notReady.length ? `<div class="card" style="margin-top:12px"><b class="small">${t('be_missing_title')}</b>${notReady.map(u => `<details style="margin-top:10px"><summary style="cursor:pointer"><span class="who" style="display:inline-flex">${thumb(u, 'sm')}<span><b>${unitName(u)}</b> <a class="small" href="#/listing/${u.id}">${esc(u.listing_id ?? t('open_dossier'))}</a> <span class="tag warn">${t('n_missing', { n: u.breakeven.missing.length })}</span></span></span></summary><ul class="missing-list">${u.breakeven.missing.map(m => `<li>${MISS(m)}</li>`).join('')}</ul></details>`).join('')}</div>` : '';
  return `<div class="section"><h2>${t('be_title')}</h2><p class="lead">${t('be_lead')}</p>${ready.length ? beChart(ref, ready, beHi) + beTable(ready) : ''}${miss}</div>`;
}
function selBar(all) {
  const cands = all.filter(u => !u.is_reference), n = cands.filter(u => selected.has(u.id)).length;
  return `<div class="selbar"><b>${t('sel_count', { n, m: cands.length })}</b><span class="muted">${t('sel_pick')}:</span>${['all', 'none', 'best5', 'budget'].map(k => `<button type="button" class="linkbtn" data-selset="${k}">${t('sel_' + k)}</button>`).join('')}</div>`;
}
function toolbar() {
  return `<div class="toolbar"><label>${t('sort_by')} <select class="inline" data-sort>${Object.keys(SORTS).map(k => `<option value="${k}" ${k === sortState.key ? 'selected' : ''}>${t('s_' + k)}</option>`).join('')}</select></label>
    <button class="btn ghost sm" type="button" data-dir aria-label="${t('toggle_dir')}">${sortState.dir === 'asc' ? '↑ ' + t('asc') : '↓ ' + t('desc')}</button>
    <label class="toggle"><input type="checkbox" data-filter="pinRef" ${filters.pinRef ? 'checked' : ''}> ${t('pin_ref')}</label>
    <label class="toggle"><input type="checkbox" data-filter="overBudget" ${filters.overBudget ? 'checked' : ''}> ${t('hide_over_budget')}</label>
    <label class="toggle"><input type="checkbox" data-filter="withdrawn" ${filters.withdrawn ? 'checked' : ''}> ${t('hide_withdrawn')}</label>
    <span class="spacer"></span><button class="btn ghost sm" type="button" data-csv>⤓ ${t('export_csv')}</button></div>`;
}
function exportCsv() {
  const us = ordered(), cols = [['rank', u => u.rank], ['score', u => u.score], ['coverage', u => u.coverage], ['make', u => u.make], ['model', u => u.model], ['trim', u => u.trim], ['listing_id', u => u.listing_id],
    ['reference', u => u.is_reference ? 1 : 0], ['status', u => u.listing_status], ['price_eur', u => u.price_eur], ['mileage_km', u => u.mileage_km], ['age_years', u => u.metrics.age], ['km_per_year', u => u.metrics.km_per_year],
    ['consumption_l_100km', u => u.consumption], ['insurance_eur_year', u => u.annual_insurance], ['tax_eur_year', u => u.annual_tax], ['power_ps', u => u.power_ps],
    ['reliability_points', u => u.metrics.reliability], ['simplicity', u => u.metrics.simplicity], ['confidence_pct', u => u.metrics.confidence],
    ...S.components.map(k => [k + '_eur_period', u => u.components[k]]), ['known_subtotal_eur', u => u.known_cost_subtotal], ['known_eur_month', u => u.known_cost_per_month],
    ['tco_complete', u => u.tco_complete ? 1 : 0], ['budget_status', u => u.budget_status], ['url', u => u.url]];
  const q = v => v == null ? '' : /[",\n]/.test(String(v)) ? '"' + String(v).replace(/"/g, '""') + '"' : String(v);
  const csv = [cols.map(c => c[0]).join(','), ...us.map(u => cols.map(c => q(c[1](u))).join(','))].join('\n');
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  a.download = `carlos-${new Date().toISOString().slice(0, 10)}.csv`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
const selNote = us => `<p class="small muted" style="margin:0 0 12px">${t('sel_showing', { n: us.filter(u => !u.is_reference).length })} <button type="button" class="linkbtn" data-view="overview">${t('sel_change')}</button></p>`;

let root;
function draw() {
  if (!S.p) return;
  const ids = new Set(S.units.map(u => u.id));
  selected = new Set([...selected].filter(id => ids.has(id)));
  if (!selected.size) S.units.forEach(u => selected.add(u.id));
  if (store.get('costSel', null) == null) costSel = new Set(S.components);
  const all = ordered(), us = all.filter(u => selected.has(u.id));
  const body = {
    ruler: () => ruler(all),
    overview: () => `<div class="section"><p class="lead">${t('units_lead', { n: S.components.length })}</p>${all.length ? overview(all) : `<p class="empty">${t('no_units')}</p>`}<p class="small muted" style="margin-top:10px">${t('ranking_hint')} <a href="#/ranking">${t('tab_ranking')}</a></p></div>`,
    costs: () => `<div class="section"><h2>${t('composition')}</h2><p class="lead">${t('composition_lead', { y: yrs(S.p.ownership_years), km: num(S.p.annual_km * S.p.ownership_years, 0) })} ${t('cost_pick_lead')}</p>${selNote(us)}${costs(us)}</div>`,
    breakeven: () => `${selNote(us)}${breakeven(us)}`,
    details: () => `<div class="section"><h2>${t('detail')}</h2>${selNote(us)}${details(us) || `<p class="empty">${t('select_one')}</p>`}</div>`,
    photos: () => `<div class="section"><div class="grid">${all.map(unitCard).join('') || `<p class="empty">${t('no_units')}</p>`}</div></div>` }[view]();
  // the one authored motion: markers leave your car's line and settle where they belong (not under reduced motion)
  if (view === 'ruler') requestAnimationFrame(() => root.querySelectorAll('.rmark[data-x]').forEach(m => { m.style.left = m.dataset.x + '%'; }));
  root.innerHTML = `${S.preview ? `<div class="banner">⚠ ${t('preview_banner')} <a class="btn sm" href="#/settings">${t('save_params')}</a></div>` : ''}${versus()}
    <div class="cbar">${selBar(all)}${toolbar()}<nav class="views" aria-label="${t('cv_nav')}">${VIEWS.map(k => `<button type="button" data-view="${k}" aria-pressed="${k === view}">${t('cv_' + k)}</button>`).join('')}</nav></div>${body}`;
}
function bind() {
  root.addEventListener('change', e => {
    if (e.target.matches('[data-sort]')) { const k = e.target.value; sortState = { key: k, dir: SORTS[k][1] }; store.set('sort', sortState); draw(); return; }
    if (e.target.dataset.filter) { filters[e.target.dataset.filter] = e.target.checked; store.set('filters', filters); draw(); return; }
    const id = e.target.dataset.toggle; if (id == null) return;
    e.target.checked ? selected.add(+id) : selected.delete(+id); store.set('selected', [...selected]); draw(); });
  root.addEventListener('click', e => {
    if (e.target.closest('[data-dir]')) { sortState.dir = sortState.dir === 'asc' ? 'desc' : 'asc'; store.set('sort', sortState); draw(); return; }
    if (e.target.closest('[data-csv]')) { exportCsv(); return; }
    const vw = e.target.closest('[data-view]'); if (vw) { view = vw.dataset.view; store.set('cview', view); go('compare?view=' + view + '&keep=1'); return; }
    const ss = e.target.closest('[data-selset]'); if (ss) { const c = S.units.filter(u => !u.is_reference), k = ss.dataset.selset;
      const ids = k === 'all' ? c : k === 'none' ? [] : k === 'best5' ? c.filter(u => u.rank).sort((a, b) => a.rank - b.rank).slice(0, 5) : c.filter(u => u.budget_status === 'within');
      selected = new Set(ids.map(u => u.id)); const ref = S.units.find(u => u.is_reference); if (ref) selected.add(ref.id); store.set('selected', [...selected]); draw(); return; }
    const bh = e.target.closest('[data-behi]'); if (bh) { const ready = S.units.filter(u => selected.has(u.id) && !u.is_reference && u.breakeven.ready), colr = beColors(ready, beHi), id = +bh.dataset.behi;
      const cur = Object.keys(colr).filter(k => colr[k]).map(Number); beHi = colr[id] ? cur.filter(x => x !== id) : [...cur, id]; store.set('beHi', beHi); draw(); return; }
    const bs = e.target.closest('[data-beset]'); if (bs) { const k = bs.dataset.beset; beHi = k === 'top' ? null : k === 'all' ? S.units.map(u => u.id) : []; store.set('beHi', beHi); draw(); return; }
    const cb = e.target.closest('[data-cost]'); if (cb) { const k = cb.dataset.cost; costSel.has(k) ? costSel.delete(k) : costSel.add(k); store.set('costSel', [...costSel]); draw(); return; }
    const cs = e.target.closest('[data-costset]'); if (cs) { costSel = new Set(cs.dataset.costset === 'all' ? S.components : cs.dataset.costset === 'running' ? RUNNING : []); store.set('costSel', [...costSel]); draw(); return; }
    if (e.target.closest('[data-sortsel]')) {
      if (sortState.key === 'selected_cost') { const prev = store.get('sortPrev', null); sortState = prev && SORTS[prev.key] && prev.key !== 'selected_cost' ? prev : { key: 'score', dir: 'desc' }; }
      else { store.set('sortPrev', sortState); sortState = { key: 'selected_cost', dir: 'asc' }; }
      store.set('sort', sortState); draw(); } });
  root.addEventListener('mousemove', e => { const ref = S.units.find(u => u.is_reference); if (!ref) return;
    beHover(e, ref, ordered().filter(u => selected.has(u.id) && !u.is_reference && u.breakeven.ready), beHi); });
}
export async function render(main, r) {
  view = VIEWS.includes(r.q.view) ? r.q.view : store.get('cview', 'ruler');
  if (!VIEWS.includes(view)) view = 'ruler';
  if (!root || !main.contains(root)) { main.innerHTML = '<div data-page="compare"></div>'; root = main.firstElementChild; bind(); }
  draw();
}
