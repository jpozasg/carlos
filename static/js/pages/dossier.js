// Dossier of one listing: photos, facts, ranking explanation, maintenance plan, risks, checklist (viewing mode), log.
import { S, refreshTco, go } from '../app.js';
import { get, send } from '../api.js';
import { t, tv, comp } from '../i18n.js';
import { $, esc, euro, num, PEND, eP, yrs, empty, facts, media, modelsHref, unitName, unitSub, sevTag, lvlTag, qTag, statusTags, gaps, intervalTxt, safeUrl, toast, CAR_SVG, scoreTxt, critColor, researchLevels } from '../ui.js';

const ICON = { OK: ['ok', '✓'], PROBLEM: ['bad', '!'], PENDING: ['pend', '·'], 'N/A': ['na', '–'] };
let PHOTOS = [], cur = 0, VIEWING = false, root, D = null, SWEEP = true, TAB = 'overview';  // SWEEP: the score needle animates on open, not on quiet refreshes
const lb = $('lightbox');
const FMT = { cost_month: v => euro(v) + t('per_month'), cash_now: euro, mileage: v => num(v, 0) + ' km', age: yrs, reliability: v => num(v, 1), inspection: v => num(v, 0),
  power: v => num(v, 0) + ' PS', confidence: v => num(v, 0) + ' %' };
const PARTS = ['ENGINE', 'GEARBOX', 'CHASSIS', 'ELECTRICS'];  // reliability parts (config.RELIABILITY_PARTS)

function viewer(d) {
  PHOTOS = d.media.map(m => m.file_path); cur = 0;
  if (!PHOTOS.length) return `<div class="card"><div class="hero" style="cursor:default;aspect-ratio:16/10"><span class="nophoto"><span>${CAR_SVG}${t('no_photos_unit')}</span></span></div></div>`;
  return `<div class="card viewer" style="padding:12px">
    <div style="position:relative"><button class="main" type="button" data-zoom aria-label="${t('zoom')}"><img id="vMain" src="${media(PHOTOS[0])}" alt="${t('photo_n', { n: 1 })} · ${unitName(d)}"><span class="count" id="vCount">1 / ${PHOTOS.length}</span></button>
      ${PHOTOS.length > 1 ? `<button class="navbtn prev" type="button" data-step="-1" aria-label="${t('prev_photo')}">‹</button><button class="navbtn next" type="button" data-step="1" aria-label="${t('next_photo')}">›</button>` : ''}</div>
    <div class="strip" role="group" aria-label="${t('thumbnails')}">${PHOTOS.map((p, i) => `<button type="button" data-photo="${i}" aria-current="${i === 0}" aria-label="${t('photo_n', { n: i + 1 })}"><img src="${media(p)}" alt="" loading="lazy"></button>`).join('')}</div></div>`;
}
function showPhoto(i) {
  if (!PHOTOS.length) return; cur = (i + PHOTOS.length) % PHOTOS.length;
  const m = $('vMain'); if (m) { m.src = media(PHOTOS[cur]); m.alt = t('photo_n', { n: cur + 1 }); $('vCount').textContent = `${cur + 1} / ${PHOTOS.length}`; }
  document.querySelectorAll('.strip [data-photo]').forEach(b => b.setAttribute('aria-current', +b.dataset.photo === cur));
  // centre the thumbnail by scrolling the strip itself; scrollIntoView also scrolled the page (issue #179)
  const th = document.querySelector(`.strip [data-photo="${cur}"]`), st = th?.parentElement;
  if (th && st) { const r = th.getBoundingClientRect(), sr = st.getBoundingClientRect();
    if (r.left < sr.left || r.right > sr.right) st.scrollLeft += r.left - sr.left - (sr.width - r.width) / 2; }
  if (lb.open) { lb.querySelector('img').src = media(PHOTOS[cur]); lb.querySelector('.count').textContent = `${cur + 1} / ${PHOTOS.length}`; }
}
lb.querySelector('.prev').onclick = () => showPhoto(cur - 1); lb.querySelector('.next').onclick = () => showPhoto(cur + 1); lb.querySelector('.close').onclick = () => lb.close();
lb.addEventListener('click', e => { if (e.target === lb || e.target.classList.contains('lb')) lb.close(); });
document.addEventListener('keydown', e => { if (!PHOTOS.length || !root || !document.contains(root)) return; if (e.target.closest('input,textarea,select')) return;
  if (e.key === 'ArrowRight') { showPhoto(cur + 1); e.preventDefault(); } else if (e.key === 'ArrowLeft') { showPhoto(cur - 1); e.preventDefault(); } });

// the Carlos score as its own element (issue #80): number, 0–100 meter and a rating word by band; the score is
// relative to the compared cars (best ≈ 100), so the bands read: ≥70 good, 40–69 average, <40 poor
const SCORE_BANDS = [[70, 'good'], [40, 'avg'], [0, 'poor']];
// "Your Carlos score" as a ring split by criteria (issue #110): the ring fills to the score, one arc per criterion as
// long as the points it adds (the Ranking page's colours), a notch at the average score of the compared cars; the
// number and word take the rating colour. No other cars as points: that stops reading once there are dozens.
const RC = 2 * Math.PI * 50;  // ring circumference, r = 50 in a 120 × 120 box
const ringAt = (v, r1, r2) => { const a = (v / 100) * 2 * Math.PI - Math.PI / 2; return `x1="${(60 + r1 * Math.cos(a)).toFixed(1)}" y1="${(60 + r1 * Math.sin(a)).toFixed(1)}" x2="${(60 + r2 * Math.cos(a)).toFixed(1)}" y2="${(60 + r2 * Math.sin(a)).toFixed(1)}"`; };
function scoreBox(d) {
  const tip = `<span class="tipicon" tabindex="0" role="img" aria-label="${esc(t('plate_score_note'))}" data-tip="${esc(t('plate_score_note'))}">${INFO_SVG}</span>`;
  const title = `<span class="sc-title">${t('plate_score')} ${tip}</span>`;
  if (d.score == null) return `<div class="scorecard"><div class="sc-top">${title}</div><div class="sc-none">${PEND()}</div></div>`;
  const band = SCORE_BANDS.find(([min]) => d.score >= min)[1], word = t('score_' + band);
  const scored = S.units.filter(u => !u.is_reference && u.listing_status !== 'WITHDRAWN' && u.score != null);
  const n = scored.length + (d.is_reference || scored.some(u => u.id === d.id) ? 0 : 1);
  const avg = scored.length ? scored.reduce((a, u) => a + u.score, 0) / scored.length : null, gap = avg == null ? null : d.score - avg;
  const keys = Object.keys(S.ranking.criteria);
  const parts = (d.explain || []).filter(x => x.contribution > 0).sort((a, b) => b.contribution - a.contribution);
  const legend = parts.length > 5 ? [...parts.slice(0, 4), { criterion: null, contribution: parts.slice(4).reduce((a, x) => a + x.contribution, 0) }] : parts;
  let at = 0;
  // round caps reach half the stroke (6.5) past each end: shorten every arc by a cap plus a 2.5 gap so neighbours never
  // overlap; an arc shorter than that is drawn as a dot
  const CUT = 13 + 2.5;
  const arcs = parts.map(x => { const len = x.contribution / 100 * RC, draw = Math.max(0.01, len - CUT), off = at + (len - draw) / 2;
    at += len; return `<circle class="sr-arc" r="50" cx="60" cy="60" stroke="${critColor(x.criterion, keys)}" stroke-dasharray="${draw.toFixed(2)} ${RC.toFixed(2)}" stroke-dashoffset="${(-off).toFixed(2)}"/>`; }).join('');
  const aria = `${t('plate_score')} ${num(d.score, 0)} / 100, ${word}; ${parts.map(x => `${t('c_' + x.criterion)} ${num(x.contribution, 0)}`).join(', ')}`;
  return `<div class="scorecard sc-${band}${SWEEP ? ' sc-sweep' : ''}">
    <div class="sc-top">${title}<span class="sc-rank">${d.rank ? t('sc_rank', { r: d.rank, n }) : t('ref_not_ranked')}</span></div>
    <div class="sr"><div class="sr-ring"><svg viewBox="0 0 120 120" role="img" aria-label="${esc(aria)}"><circle class="sr-track" r="50" cx="60" cy="60"/><g class="sr-arcs" transform="rotate(-90 60 60)">${arcs}</g>${avg == null ? '' : `<line class="sr-avg" ${ringAt(avg, 40, 60)}/>`}</svg>
      <div class="sr-mid"><b class="sc-num">${scoreTxt(d)}</b><span class="sc-word">${word}</span></div></div>
      <ul class="sr-legend">${legend.map(x => `<li><i style="background:${x.criterion ? critColor(x.criterion, keys) : 'var(--text-3)'}"></i><span>${x.criterion ? t('c_' + x.criterion) : t('sc_other')}</span><b class="num">${num(x.contribution, 0)}</b></li>`).join('')}</ul></div>
    <p class="sc-cov">${gap == null ? '' : `<span class="sr-gap ${gap >= 0 ? 'up' : 'down'}">${gap >= 0 ? '▲' : '▼'} ${t('sc_vs_avg', { d: (gap >= 0 ? '+' : '−') + num(Math.abs(gap), 0), a: num(avg, 0) })}</span> · `}${t('coverage', { n: num(d.coverage * 100, 0) })}</p></div>`;
}
// reliability as its own element (issue #80): total out of 36 and one meter per part out of 9; each part starts at 9
// and loses its 3 worst points, so higher is better: ≥6 green, ≥3 amber, below 3 red
const relBand = v => v >= 6 ? 'good' : v >= 3 ? 'avg' : 'poor';
// an unknown part: not researched yet, or too new for any reliability statistic (issue #150)
const partUnknown = (d, k) => (d.reliability_too_new || []).includes(k) ? 'part_too_new' : 'part_unknown';
function relBox(d) {
  const total = (d.metrics || {}).reliability;
  const tip = `<span class="tipicon" tabindex="0" role="img" aria-label="${esc(t('plate_rel_note'))}" data-tip="${esc(t('plate_rel_note'))}">${INFO_SVG}</span>`;
  const head = `<div class="rb-head">${t('plate_reliability')} ${tip}<span class="rb-total num">${total == null ? PEND() : t('plate_rel_total', { n: num(total, 1) })}</span></div>`;
  return `<div class="relbox">${head}<div class="rb-rows">${PARTS.map(k => { const v = (d.reliability_parts || {})[k];
    if (v == null) return `<span class="rb-part">${esc(t('part_' + k))}</span><span class="rb-meter"></span><span class="rb-val small muted">${t(partUnknown(d, k))}</span>`;
    return `<span class="rb-part">${esc(t('part_' + k))}</span><span class="rb-meter rb-${relBand(v)}" role="img" aria-label="${esc(t('part_' + k))} ${num(v, 1)} / 9"><i style="width:${Math.max(2, v / 9 * 100)}%"></i></span><span class="rb-val num">${num(v, 1)}</span>`; }).join('')}</div></div>`;
}
// the cost per month, the other key figure, as a strip at the top of the plate (issue #80)
const costStrip = d => `<div class="plate-cost"><span>${t('plate_cost_short')}</span><b>${d.known_cost_per_month == null ? PEND() : `${euro(d.known_cost_per_month)}<small>${t('per_month')}</small>`}</b></div>`;  // total cost of ownership per month
function plate(d) {
  const row = (k, v, cls = '') => `<dt class="${cls}">${k}</dt><dd class="${cls}">${v}</dd>`;
  return `<aside class="plate" aria-label="${esc(t('plate_title'))}">${costStrip(d)}<dl>
    ${d.is_reference ? '' : row(t('asking_price'), eP(d.price_eur))}
    ${row(t('mileage'), d.mileage_km == null ? PEND() : num(d.mileage_km, 0) + ' km')}
    ${row(t('registration'), d.first_registration ? esc(d.first_registration) : PEND())}
    ${row(t('age'), (d.metrics || {}).age == null ? PEND() : yrs(d.metrics.age))}
    ${row(t('engine'), `<a href="${modelsHref({ engine: d.engine_code })}">${esc(d.engine_code)}</a>`)}
    ${row(t('power'), d.power_ps == null ? PEND() : num(d.power_ps, 0) + ' PS')}
    ${row(t('consumption'), d.consumption == null ? PEND() : num(d.consumption) + ' ' + esc(d.consumption_unit || 'l/100 km'))}
    ${row(t('plate_position'), d.rank ? `#${d.rank}` : `<span class="pending">${t(d.is_reference ? 'ref_not_ranked' : 'not_ranked')}</span>`)}
    ${row(t('tco_complete'), d.tco_complete ? `<span class="tag good">${t('yes')}</span>` : `<span class="tag warn">${t('subtotal_partial')}</span>`)}</dl>${relBox(d)}
    ${d.verdict ? `<div class="stamp">${t('plate_stamp')}: ${esc(d.verdict)}</div>` : ''}</aside>`;
}
function valuationRow(v) {
  const r = v.low_eur != null && v.high_eur != null && v.high_eur > v.low_eur ? `<div class="range" aria-hidden="true"><i style="left:${(v.expected_eur - v.low_eur) / (v.high_eur - v.low_eur) * 100}%"></i></div><div class="small muted" style="display:flex;justify-content:space-between"><span>${euro(v.low_eur)}</span><span>${euro(v.high_eur)}</span></div>` : '';
  return `<div style="margin-bottom:12px"><div style="display:flex;justify-content:space-between;gap:8px"><b class="small">${v.kind === 'sale_today' ? t('sale_today') : t('resale_end')}${v.horizon_years ? ` (${yrs(v.horizon_years)})` : ''}</b><b>${euro(v.expected_eur)}</b></div>${r}<div class="small muted">${esc(tv(v.status))} · ${t('source')} ${esc(v.source_id)}${v.notes ? ' · ' + esc(v.notes) : ''}</div></div>`;
}
// the seller's rating as the platform publishes it (issue #135): read from the newest capture that has one (mobile.de
// "Händlerbewertung": "3.2 Sterne (28 Bewertungen)"); private sellers have none, so no row
function sellerRating(d) {
  for (const snap of d.snapshots.slice().reverse()) {
    let a = {}; try { a = JSON.parse(snap.attributes_json || '{}'); } catch (e) { continue; }
    const m = /([\d]+[.,]?\d*)\s*Sterne\s*\((\d+)/.exec(a['Händlerbewertung'] || '');
    if (m) return `<span class="stars" aria-hidden="true">★</span> ${num(parseFloat(m[1].replace(',', '.')), 1)} / 5 · ${t('reviews_n', { n: +m[2] })}`;
  }
  return null;
}
function archive(d) {
  if (!d.snapshots.length && !d.media.length) return empty(t('no_archive'));
  const s = d.snapshots[d.snapshots.length - 1]; let attrs = {}; try { attrs = s && s.attributes_json ? JSON.parse(s.attributes_json) : {}; } catch (e) {}
  return `${s ? `<p class="small muted" style="margin-top:0">${t('last_capture', { d: esc(s.captured_at), n: d.snapshots.length })}${s.title ? ' · ' + esc(s.title) : ''}${s.price_eur != null ? ' · ' + euro(s.price_eur) : ''}</p>` : ''}
    ${d.media.length ? `<p class="small muted">${t('photos_archived', { n: d.media.length })}</p>` : ''}
    ${d.price_history.length > 1 ? `<p class="small"><b>${t('price_history')}:</b> ${d.price_history.map(x => `${esc(x.date)} ${euro(x.price_eur)}`).join(' → ')}</p>` : ''}
    ${Object.keys(attrs).length ? facts(Object.entries(attrs).map(([k, v]) => [esc(k), esc(typeof v === 'string' ? v : JSON.stringify(v))])) : ''}
    ${s && s.description ? `<details style="margin-top:10px"><summary class="small" style="cursor:pointer">${t('listing_description')}</summary><p class="desc">${esc(s.description)}</p></details>` : ''}`;
}
// a lease offer (#129): the offer as the ad states it, the cost per month of each way, and what is not predicted
function leaseFacts(d) {
  if (d.lease_monthly_eur == null) return [];
  const o = d.offers || {}, pm = x => x && x.cost_month != null ? euro(x.cost_month) + t('per_month') + (x.complete ? '' : ' ' + t('partial_short')) : PEND();
  const offer = [euro(d.lease_monthly_eur) + t('per_month'), d.lease_term_months ? t('lease_term_n', { n: d.lease_term_months }) : PEND(),
    d.lease_km_per_year ? num(d.lease_km_per_year, 0) + ' km/' + t('year_short') : PEND(), `${t('lease_down')} ${eP(d.lease_down_payment_eur)}`,
    `${t('lease_fees')} ${eP(d.lease_fees_eur)}`, `${t('lease_includes')}: ${d.lease_includes ? esc(d.lease_includes.split(',').map(k => t('li_' + k)).join(', ')) : t('lease_nothing')}`].join(' · ');
  return [[t('lease_offer') + (d.lease_kind ? ` (${esc(t('lk_' + d.lease_kind))})` : ''), offer],
    [t('lease_vs_buy'), `${t('am_buy')}: ${pm(o.purchase)} · ${t('am_lease')}: ${pm(o.lease)} · <b>${t(d.offer === 'lease' ? 'costed_lease' : 'costed_buy')}</b><div class="small muted">${t('lease_note')}</div>`]];
}
function rankCard(d) {  // the reference car is scored too (issue #72), only not ranked
  const R = S.ranking;
  const rows = (d.explain && d.explain.length ? d.explain : Object.keys(R.criteria).map(k => ({ criterion: k, weight: R.weights[k], value: d.metrics[k], score: null, contribution: null, why_missing: 'no value for this car' }))).map(x => {
    const k = x.criterion;
    return `<tr><td><b>${t('c_' + k)}</b><div class="small muted">${esc(t('cb_' + k))}</div></td><td class="n">${x.weight || '<span class="muted">0</span>'}</td><td class="n">${x.value == null ? PEND() : FMT[k](x.value)}${x.bounds ? `<div class="small muted">${FMT[k](x.bounds.min)} – ${FMT[k](x.bounds.max)}</div>` : ''}</td>
      <td style="min-width:120px">${x.score == null ? `<span class="muted small">${t('why_' + (x.why_missing || 'no value for this car').replace(/ /g, '_'))}</span>` : `<div class="scorebar" title="${x.score}"><i style="width:${x.score}%"></i></div><span class="small">${x.score} · ${t('contribution')} ${num(x.contribution, 0)}%</span>`}</td></tr>`; }).join('');
  const head = d.score == null ? `<span class="pending">${t('not_ranked')}</span>` : `<b class="big" style="font-size:22px">${scoreTxt(d)}</b> <span class="muted small">${d.rank ? t('rank_n', { n: d.rank }) : t('ref_not_ranked')} · ${t('coverage', { n: num(d.coverage * 100, 0) })}</span>`;
  const rel = d.reliability_detail || [];
  return `<div class="card span2"><h3>${t('ranking')}</h3><div style="margin-bottom:8px">${head} ${R.manual ? `<span class="tag warn">${t('weights_manual')}</span>` : ''}</div><div class="tags">${statusTags(d).join('')}</div>
    <div class="tablewrap" style="margin-top:10px"><table><thead><tr><th>${t('criterion')}</th><th class="n">${t('weight')}</th><th class="n">${t('value')}</th><th>${t('score')}</th></tr></thead><tbody>${rows}</tbody></table></div>
    <details style="margin-top:10px"><summary class="small" style="cursor:pointer">${t('research_title')}: ${t('c_confidence')} ${d.metrics.confidence == null ? '–' : num(d.metrics.confidence, 0) + ' %'}</summary><p class="small muted" style="margin:6px 0 0">${t('research_lead')}</p>${researchLevels(d.research_levels)}
      ${rel.length ? `<p class="small" style="margin:8px 0 0"><b>${t('c_reliability')}:</b> ${rel.map(r => `${esc(r.component)} ${sevTag(r.severity)} −${num(r.points, 1)}`).join(' · ')}</p>` : ''}</details>
    <p class="small muted" style="margin:8px 0 0"><a href="#/ranking">${t('ranking_edit')}</a></p></div>`;
}
const srcLink = (d, id) => { const x = d.sources.find(s => s.id === id); return x ? qTag(x.quality, x.title + (x.limitations ? ' — ' + x.limitations : '')) : ''; };
// one row per certain one-off cost of this car (unit_costs of a category), named, so a total never hides what it includes
const certainOf = (d, cat) => d.unit_costs.filter(x => x.category === cat).map(x => ({ ...x, eur: (x.parts_eur || 0) + (x.labor_eur || 0) }));
// row notes open on click/tap (a title tooltip is hover-only and never shows on a phone); an SVG renders in every theme font
const INFO_SVG = '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="8" cy="8" r="6.5"/><path d="M8 7.2v4M8 4.6v.1" stroke-linecap="round"/></svg>';
const noteBox = text => text ? `<details class="rownote"><summary aria-label="${esc(t('notes'))}" title="${esc(t('notes'))}">${INFO_SVG}</summary><p>${esc(text)}</p></details>` : '';
// why a scheduled job counts as done at the start of ownership (maintenance_resets.basis) and what that does to the cost
const RESET = { 'CERTAIN REPAIR': ['rs_due', ''], 'SELLER CLAIM': ['rs_claim', 'warn'], DOCUMENTED: ['rs_documented', 'good'] };
function resetTag(d, itemId) {
  const r = (d.maintenance_resets || []).find(x => x.maintenance_item_id === itemId); if (!r) return '';
  const [key, cls] = RESET[r.basis] || ['rs_documented', 'good'];
  return `<details class="rownote reset"><summary><span class="tag ${cls}">${t(key)}</span></summary><p>${t(key + '_x')} ${t('rs_effect')}${r.notes ? `<br><span class="muted">${esc(r.notes)}</span>` : ''}</p></details>`;
}
const certainRows = (d, rows) => rows.map(x => `<tr><td colspan="6">${esc(x.item)} <span class="tag">${t('certain_tag')}</span> ${noteBox(x.notes)}</td><td class="n">${euro(x.eur)}</td><td>${srcLink(d, x.source_id)}</td></tr>`).join('');
function maintenanceCard(d) {
  const rows = d.maintenance_plan || [], cm = certainOf(d, 'maintenance'); if (!rows.length && !cm.length) return `<div class="card span2"><h3>${t('mp_title')}</h3>${empty(t('mp_none'))}</div>`;
  const tot = rows.reduce((a, r) => a + (r.cost_eur || 0), 0) + cm.reduce((a, x) => a + x.eur, 0), hrs = rows.reduce((a, r) => a + (r.diy_hours || 0), 0);
  return `<div class="card span2"><h3>${t('mp_title')}</h3><p class="small muted" style="margin-top:0">${t('mp_lead', { km: num(d.period_km, 0), m: num(S.p.ownership_years * 12, 0) })}</p>
    <div class="tablewrap"><table><thead><tr><th>${t('mp_job')}</th><th>${t('level')}</th><th>${t('mp_interval')}</th><th>${t('mp_who')}</th><th class="n">${t('mp_price')}</th><th class="n">${t('mp_times')}</th><th class="n">${t('mp_cost')}</th><th>${t('mp_src')}</th></tr></thead><tbody>
    ${rows.map(r => `<tr><td>${esc(r.item)}${r.restarted ? ` ${resetTag(d, r.id)}` : ''}<div class="small muted">${esc(tv(r.status) ?? '')} ${noteBox(r.notes)}</div></td><td>${lvlTag(r.level, r)}</td>
      <td>${intervalTxt(r.interval_km, r.interval_months)}</td><td>${r.diy ? t('mp_diy') : t('mp_ws')}</td><td class="n">${eP(r.price_eur)}</td>
      <td class="n">×${num(r.occurrences, 2)}</td><td class="n">${eP(r.cost_eur)}${r.diy_hours ? `<div class="small muted">${num(r.diy_hours, 1)} h</div>` : ''}</td><td>${srcLink(d, r.source_id)}</td></tr>`).join('')}
    ${certainRows(d, cm)}
    <tr><td colspan="6"><b>${t('mp_total')}</b></td><td class="n"><b>${euro(tot)}</b>${hrs ? `<div class="small muted">${num(hrs, 1)} h</div>` : ''}</td><td></td></tr></tbody></table></div></div>`;
}
function risksCard(d) {
  const rows = (d.repair_risks || []).slice().sort((a, b) => (b.expected_eur || 0) - (a.expected_eur || 0));
  if (!rows.length) return `<div class="card span2"><h3>${t('rk_title')}</h3>${empty(t('rk_none'))}</div>`;
  const tot = rows.reduce((a, r) => a + (r.expected_eur || 0), 0), cr = certainOf(d, 'repairs'), cert = cr.reduce((a, x) => a + x.eur, 0);
  return `<div class="card span2"><h3>${t('rk_title')}</h3><p class="small muted" style="margin-top:0">${t('rk_lead')}</p>
    <div class="tablewrap"><table><thead><tr><th>${t('rk_comp')}</th><th>${t('level')}</th><th>${t('rk_window')}</th><th class="n">${t('rk_prob')}</th><th class="n">${t('mp_price')}</th><th class="n">${t('rk_share')}</th><th class="n">${t('rk_exp')}</th><th>${t('mp_src')}</th></tr></thead><tbody>
    ${rows.map(r => `<tr${r.share ? '' : ' class="muted"'}><td><span title="${esc(r.evidence ?? '')}${r.notes ? ' — ' + esc(r.notes) : ''}">${esc(r.component)}</span>${r.diy ? ` <span class="tag">DIY</span>` : ''}</td><td>${lvlTag(r.level, r)}</td>
      <td>${num(r.km_from, 0)}–${num(r.km_to, 0)}</td><td class="n">${num(r.probability * 100, 0)} %</td><td class="n">${eP(r.price_eur)}</td>
      <td class="n">${num(r.share * 100, 0)} %</td><td class="n">${eP(r.expected_eur)}</td><td>${srcLink(d, r.source_id)}</td></tr>`).join('')}
    <tr><td colspan="6"><b>${t('rk_total')}</b></td><td class="n"><b>${euro(tot)}</b></td><td></td></tr>
    ${cert ? `<tr><td colspan="8" class="small muted">${t('rk_certain')}</td></tr>${certainRows(d, cr)}<tr><td colspan="6"><b>${esc(comp('repairs'))}</b></td><td class="n"><b>${euro(tot + cert)}</b></td><td></td></tr>` : ''}</tbody></table></div></div>`;
}
// weak points grouped by part; each part counts its 3 worst (issue #54), a recall drops out once checked as done
function reliabilityCard(d) {
  if (!d.reliability.length) return `<div class="card"><h3>${t('reliability')}</h3>${empty(t('no_reliability'))}</div>`;
  const det = Object.fromEntries((d.reliability_detail || []).map(x => [x.id, x]));
  const state = r => { const x = det[r.id] || {};
    return x.excluded ? `<span class="tag good">${t('rel_recall_done')}</span>` : x.counted ? `<span class="tag">${t('rel_counted')} −${num(x.points, 1)}</span>` : `<span class="small muted">${t('rel_not_counted')}</span>`; };
  const group = (part, rows) => rows.length ? `<h4 class="small" style="margin:12px 0 4px">${part ? esc(t('part_' + part)) : esc(t('rel_no_part'))}${part ? ` <span class="muted num">${(d.reliability_parts || {})[part] == null ? t(partUnknown(d, part)) : `${num(d.reliability_parts[part], 1)} / 9 ${t('rel_pts')}`}</span>` : ''}</h4>
    <ul class="check">${rows.sort((a, b) => (det[b.id]?.points || 0) - (det[a.id]?.points || 0)).map(r => `<li><span class="ico pend" aria-hidden="true">i</span><div><b>${esc(r.component)}</b> · ${esc(r.issue ?? '')}<div class="small" style="margin:4px 0">${sevTag(r.severity)} ${lvlTag(r.level, r)}${r.is_recall ? ` <span class="tag warn">${t('rel_recall')}</span>` : ''} ${state(r)}</div>${r.inspection_action ? `<div class="small muted">→ ${esc(r.inspection_action)}</div>` : ''}</div></li>`).join('')}</ul>` : '';
  const total = (d.metrics || {}).reliability;
  return `<div class="card"><h3>${t('reliability')} ${total == null ? '' : `<span class="muted small num">${t('plate_rel_total', { n: num(total, 1) })}</span>`}</h3><p class="small muted" style="margin-top:0">${t('rel_lead')}</p>
    ${[...PARTS, null].map(p => group(p, d.reliability.filter(r => (r.part ?? null) === p))).join('')}</div>`;
}
function inspectionCard(d) {
  const c = d.inspection_counts, tot = d.inspection.length, ok = c.OK ?? 0;
  if (!VIEWING) return `<div class="card"><h3>${t('inspection')} ${tot ? `<span class="muted small">${ok}/${tot} OK</span>` : ''}</h3>
      ${tot ? `<div class="meter good" style="margin-bottom:10px" aria-hidden="true"><i style="width:${ok / tot * 100}%"></i></div><ul class="check">${d.inspection.map(i => { const [cls, ch] = ICON[i.status] || ICON.PENDING;
        return `<li><span class="ico ${cls}" aria-hidden="true">${ch}</span><div>${esc(i.item)}<div class="small muted">${esc(tv(i.status))}${i.checked_date ? ' · ' + esc(i.checked_date) : ''}${i.notes ? ' · ' + esc(i.notes) : ''}</div></div></li>`; }).join('')}</ul>` : empty(t('no_checklist_short'))}</div>`;
  return `<div class="card span2 viewing-on"><h3>${t('inspection')} <span class="muted small">${ok}/${tot} OK</span></h3>
    <ul class="check">${d.inspection.map(i => { const [cls, ch] = ICON[i.status] || ICON.PENDING;
      return `<li><span class="ico ${cls}" aria-hidden="true">${ch}</span><div><div>${esc(i.item)}</div>
        <div class="vbtns" role="group" aria-label="${esc(i.item)}">${['OK', 'PROBLEM', 'N/A', 'PENDING'].map(st => `<button type="button" data-insp="${i.id}" data-st="${st}" aria-pressed="${i.status === st}" title="${esc(tv(st))}">${t('vb_' + st.replace('/', ''))}</button>`).join('')}</div>
        <input class="vnote" data-inote="${i.id}" value="${esc(i.notes ?? '')}" placeholder="${t('note_ph')}" aria-label="${t('note_ph')}"></div></li>`; }).join('')}</ul>
    <div style="margin-top:12px"><input class="vnote" id="newcheck" placeholder="${t('add_check_ph')}" aria-label="${t('add_check_ph')}"><button class="btn ghost sm" type="button" data-addcheck style="margin-top:6px">${t('add_check')}</button></div></div>`;
}
function viewingPanel() {
  if (!VIEWING) return '';
  return `<div class="card span2 viewing-on"><h3>📋 ${t('viewing_title')}</h3><p class="small muted" style="margin-top:0">${t('viewing_hint')}</p>
    <div class="row"><label class="btn">📷 ${t('add_photos')}<input type="file" accept="image/*" capture="environment" multiple data-photos hidden></label></div>
    <textarea class="vnote" id="vnote" placeholder="${t('log_ph')}" aria-label="${t('log_ph')}" lang="en"></textarea>
    <button class="btn" type="button" data-addnote style="margin-top:6px">${t('add_note')}</button></div>`;
}
async function shrink(file) {  // phone photos are 3–5 MB: resize to 1280 px JPEG in the browser (also drops EXIF, including GPS)
  const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' }).catch(() => null); if (!bmp) return file;
  const k = Math.min(1, 1280 / Math.max(bmp.width, bmp.height)), c = document.createElement('canvas');
  c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k); c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height);
  return await new Promise(r => c.toBlob(r, 'image/jpeg', .82));
}
const ui = (method, path, body, ctype) => send(method, '/api/ui/' + path, body, ctype);
// a refresh of the same car keeps the page (no loading skeleton) and the scroll position, so marking a checklist
// item in viewing mode does not jump back to the top
async function refresh() { const y = window.scrollY; await draw(D.id, true); window.scrollTo(0, y); refreshTco().catch(() => {}); }

// tabs under a fixed top (issue #178): photos, score and spec plate always shown; the tab is kept in the URL (?tab=)
const TABS = ['overview', 'costs', 'maintenance', 'reliability', 'viewing', 'log'];
const hid = k => k === TAB ? '' : ' hidden';
const tabBar = () => `<div class="dtabs" role="tablist" aria-label="${esc(t('dt_label'))}">${TABS.map(k => `<button type="button" role="tab" data-tab-pick="${k}" aria-selected="${k === TAB}">${t('dt_' + k)}</button>`).join('')}</div>`;
function pickTab(k) {  // switches without redrawing or moving the top; replaceState so the router doesn't re-render
  TAB = k;
  root.querySelectorAll('.dtab').forEach(g => { g.hidden = g.dataset.tab !== k; });
  root.querySelectorAll('[data-tab-pick]').forEach(b => b.setAttribute('aria-selected', b.dataset.tabPick === k));
  const [path, q] = location.hash.split('?'), sp = new URLSearchParams(q || ''); sp.set('tab', k);
  history.replaceState(null, '', `${path}?${sp}`);
}
async function draw(id, quiet = false) {
  SWEEP = !quiet;
  const label = u => `${unitName(u)} ${u.is_reference ? '(' + t('reference').toLowerCase() + ')' : esc(u.listing_id ?? '')}`;
  const picker = `<div class="field unit-select"><label for="unitsel">${t('units_group')}</label><select id="unitsel" data-unitsel>${S.units.map(u => `<option value="${u.id}" ${u.id === id ? 'selected' : ''}>${label(u)}</option>`).join('')}</select></div>`;
  if (!quiet) root.innerHTML = picker + '<div class="grid"><div class="skel"></div><div class="skel"></div></div>';
  let d; try { d = await get('/api/listings/' + id); } catch (e) { root.innerHTML = picker + `<div class="card err">${t('dossier_failed', { m: esc(e.message) })}</div>`; return; }
  D = d;
  const claim = x => x == null ? PEND() : `${esc(x)} <span class="tag">${t('claimed')}</span>`;
  root.innerHTML = picker + `<div class="dossier-top">${viewer(d)}<div class="dossier-side">${scoreBox(d)}${plate(d)}</div></div>${tabBar()}<div class="grid dtab" data-tab="overview"${hid('overview')}>
    <div class="card span2"><div class="unit-head"><div><div class="unit-name"><a class="carlink" href="#/models/${d.vehicle_id}">${unitName(d)} ${esc(d.trim ?? '')}</a></div><div class="unit-sub">${unitSub(d)} · ${esc(tv(d.listing_status) ?? '')} <a href="#/models/${d.vehicle_id}" style="margin-left:8px">${t('open_model')}</a></div></div>
      <div class="row">${d.url ? `<a class="btn ghost sm" href="${safeUrl(d.url)}" target="_blank" rel="noopener">${t('open_listing')}</a>` : ''}<button class="btn sm${VIEWING ? '' : ' ghost'}" type="button" data-viewing>${VIEWING ? t('viewing_exit') : '📋 ' + t('viewing_start')}</button></div></div>
      ${d.is_reference ? '' : decisionBar(d)}
      ${gaps(S.todo.listings.find(x => x.listing_id === d.id)?.todo)}
      <div style="margin-top:12px">${facts([[t('asking_price'), d.is_reference ? t('owned') : eP(d.price_eur)], ...leaseFacts(d), [t('mileage'), d.mileage_km == null ? PEND() : num(d.mileage_km, 0) + ' km'], [t('registration'), d.first_registration ? esc(d.first_registration) : PEND()],
        [t('engine'), `<a href="${modelsHref({ engine: d.engine_code })}">${esc(d.engine_code)}</a> · ${esc(d.engine_description ?? '')}`], [t('generation'), `<a href="${modelsHref({ make: d.make, model: d.model })}">${esc(d.generation)}</a> ${d.generation_start_year ?? '?'}–${d.generation_end_year ?? '?'}`],
        ...(d.is_reference ? [] : [[t('seller'), d.seller ? esc(d.seller) + (d.location ? ', ' + esc(d.location) : '') : PEND()], ...(sellerRating(d) ? [[t('seller_rating'), sellerRating(d)]] : []), [t('accident_free'), d.accident_free_claim == null ? PEND() : claim(d.accident_free_claim ? t('yes') : t('no'))], [t('owners'), claim(d.owners_claim)],
        [t('hu'), claim(d.hu_claim)], [t('history'), claim(d.service_history_claim)], [t('equipment'), d.equipment ? esc(d.equipment) : PEND()], [t('verdict'), d.verdict ? `<b>${esc(d.verdict)}</b>` : PEND()]]), [t('notes'), d.notes ? esc(d.notes) : PEND()]])}</div></div>
    ${rankCard(d)}</div>
    <div class="grid dtab" data-tab="maintenance"${hid('maintenance')}>${maintenanceCard(d)}${risksCard(d)}</div>
    <div class="grid dtab" data-tab="viewing"${hid('viewing')}>${viewingPanel()}${inspectionCard(d)}</div>
    <div class="grid dtab" data-tab="costs"${hid('costs')}>
    <div class="card"><h3>${t('valuations')}</h3>${d.valuations.length ? d.valuations.map(valuationRow).join('') : empty(t('no_valuations'))}
      <h3 style="margin-top:16px">${t('own_costs')}</h3>${d.unit_costs.length ? `<div class="tablewrap"><table><thead><tr><th>${t('concept')}</th><th class="n">${t('parts')}</th><th class="n">${t('labour')}</th><th class="n">DIY</th></tr></thead><tbody>${d.unit_costs.map(x => `<tr><td>${esc(x.item)}<div class="small muted">${esc(tv(x.category))} · ${esc(tv(x.status))}</div></td><td class="n">${eP(x.parts_eur)}</td><td class="n">${eP(x.labor_eur)}</td><td class="n">${x.diy_hours == null ? '—' : num(x.diy_hours, 1) + ' h'}</td></tr>`).join('')}</tbody></table></div>` : empty(t('no_own_costs'))}</div>
    </div>
    <div class="grid dtab" data-tab="reliability"${hid('reliability')}>${reliabilityCard(d)}</div>
    <div class="grid dtab" data-tab="log"${hid('log')}>
    <div class="card"><h3>${t('archive')}</h3>${archive(d)}</div>
    <div class="card"><h3>${t('log')}</h3>${d.events.length ? `<ol class="timeline">${d.events.slice().reverse().map(ev => `<li><time>${esc(ev.event_date)}</time> <span class="tag">${esc(tv(ev.kind))}</span><div>${esc(ev.text)}</div></li>`).join('')}</ol>` : empty(t('no_events'))}</div>
    <div class="card span2"><h3>${t('tab_sources')} <span class="muted small">${d.sources.length}</span></h3><div class="small">${d.sources.map(s => `<div class="src"><div class="src-title">${qTag(s.quality)} <span>${esc(s.title)}</span> ${lvlTag(s.vehicle_id ? 'variant' : s.engine_id ? 'engine' : s.generation_id ? 'generation' : 'shared')}</div>${s.url ? `<a href="${safeUrl(s.url)}" target="_blank" rel="noopener">${esc(s.url)}</a>` : ''}</div>`).join('')}</div></div></div>`;
}
function bind() {
  root.addEventListener('change', async e => {
    if (e.target.matches('[data-unitsel]')) { go('listing/' + e.target.value); return; }
    const n = e.target.closest('[data-inote]'); if (n) { try { await ui('PATCH', 'inspection_items/' + n.dataset.inote, { notes: n.value }); toast(t('saved_short')); } catch (err) { toast(err.message, true); } return; }
    const ph = e.target.closest('[data-photos]'); if (ph && ph.files.length) { let ok = 0;
      for (const [i, f] of [...ph.files].entries()) { toast(t('uploading', { i: i + 1, n: ph.files.length })); try { await ui('POST', 'media/' + D.id, await shrink(f), 'image/jpeg'); ok++; } catch (err) { toast(err.message, true); } }
      if (ok) toast(t('photos_added', { n: ok })); await refresh(); } });
  root.addEventListener('click', async e => {
    const tp = e.target.closest('[data-tab-pick]'); if (tp) { pickTab(tp.dataset.tabPick); return; }
    if (e.target.closest('[data-viewing]')) { VIEWING = !VIEWING; if (VIEWING) TAB = 'viewing'; await draw(D.id); return; }
    const dc = e.target.closest('[data-decide]'); if (dc) { const k = dc.dataset.decide;
      if (k === 'reject') { const w = root.querySelector('.decide-why'); w.hidden = false; $('rejectWhy').focus(); return; }
      try { await send('POST', '/api/ui/decision/' + D.id, { decision: k === 'reject-confirm' ? 'reject' : k, reason: k === 'reject-confirm' ? $('rejectWhy').value : '' });
        toast(t('decision_saved')); await refresh(); } catch (err) { toast(err.message, true); } return; }
    const b = e.target.closest('[data-insp]'); if (b) { try { await ui('PATCH', 'inspection_items/' + b.dataset.insp, { status: b.dataset.st }); await refresh(); } catch (err) { toast(err.message, true); } return; }
    if (e.target.closest('[data-addnote]')) { const v = $('vnote').value.trim(); if (!v) return; try { await ui('POST', 'listing_events', { listing_id: D.id, text: v }); toast(t('note_added')); await refresh(); } catch (err) { toast(err.message, true); } return; }
    if (e.target.closest('[data-addcheck]')) { const v = $('newcheck').value.trim(); if (!v) return; try { await ui('POST', 'inspection_items', { listing_id: D.id, item: v }); await refresh(); } catch (err) { toast(err.message, true); } return; }
    const ph = e.target.closest('[data-photo]'); if (ph) { showPhoto(+ph.dataset.photo); return; }
    const st = e.target.closest('[data-step]'); if (st) { showPhoto(cur + +st.dataset.step); return; }
    if (e.target.closest('[data-zoom]')) { lb.showModal(); showPhoto(cur); return; }
  });
}
// the owner's decision: shortlist, plan a viewing or reject (archives the car out of the ranking), with a reason
function decisionBar(d) {
  const cur = /^Shortlisted/.test(d.verdict || '') ? 'shortlist' : /^Viewing planned/.test(d.verdict || '') ? 'viewing' : /^Rejected/.test(d.verdict || '') ? 'reject' : '';
  return `<div class="decide" role="group" aria-label="${esc(t('decision_label'))}"><span class="small muted">${t('decision_label')}</span>
    ${['shortlist', 'viewing', 'reject'].map(k => `<button type="button" class="btn sm ${cur === k ? '' : 'ghost'}" data-decide="${k}" aria-pressed="${cur === k}">${t('decide_' + k)}</button>`).join('')}
    ${cur ? `<button type="button" class="linkbtn small" data-decide="reset">${t('decide_reset')}</button>` : ''}
    <span class="decide-why" hidden><input id="rejectWhy" type="text" maxlength="300" placeholder="${esc(t('decide_reason_ph'))}" aria-label="${esc(t('decide_reason_ph'))}"><button type="button" class="btn sm danger" data-decide="reject-confirm">${t('decide_reject_confirm')}</button></span></div>`;
}
export async function render(main, r) {
  const id = r.id ?? S.units[0]?.id;
  if (TABS.includes(r.q?.tab)) TAB = r.q.tab;
  if (!root || !main.contains(root)) { main.innerHTML = '<div data-page="dossier"></div>'; root = main.firstElementChild; bind(); }
  if (id == null) { root.innerHTML = empty(t('no_units')); return; }
  await draw(id);
}
