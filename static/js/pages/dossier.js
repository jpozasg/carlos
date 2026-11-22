// Dossier of one listing: photos, facts, ranking explanation, maintenance plan, risks, checklist (viewing mode), log.
import { S, refreshTco, go } from '../app.js';
import { get, send } from '../api.js';
import { t, tv, comp } from '../i18n.js';
import { $, esc, euro, num, PEND, eP, sumKnown, totalP, perMonth, pct, consumptionTxt, consumptionSpread, yrs, empty, facts, media, modelsHref, unitName, unitSub, sevTag, lvlTag, qTag, safeUrl, statusTags, gaps, intervalTxt, toast, CAR_SVG, scoreTxt, notScoredTxt, critColor, researchLevels, flagsCard, faultProb, busy, fmtDate } from '../ui.js';

const ICON = { OK: ['ok', '✓'], PROBLEM: ['bad', '!'], PENDING: ['pend', '·'], 'N/A': ['na', '–'] };
let PHOTOS = [], PHOTO_IDS = [], cur = 0, VIEWING = false, root, D = null, SWEEP = true, TAB = 'overview';  // SWEEP: the score needle animates on open, not on quiet refreshes
const lb = $('lightbox');
const FMT = { cost_month: v => euro(v) + t('per_month'), cash_now: euro, budget: euro, safety: v => num(v, 0) + ' ★', distance: v => num(v, 0) + ' km', mileage: v => num(v, 0) + ' km', age: yrs, reliability: v => num(v, 1), inspection: v => num(v, 0),
  power: v => num(v, 0) + ' PS', confidence: v => num(v, 0) + ' %' };
const PARTS = ['ENGINE', 'GEARBOX', 'CHASSIS', 'ELECTRICS'];  // parts a fault belongs to (config.RELIABILITY_PARTS)
const SLOTS = ['ENGINE', 'HU', 'BREAKDOWNS'];  // reliability score slots (config.RATING_SLOTS)
// inline save errors by key (item `i<id>`, forms `vnote`, `newcheck`, `photos`, `decide`): shown until the next successful save
// of the same key, and kept across quiet redraws, so a failed tick is never silently shown as saved
const ERR = new Map(), BUSY_ITEMS = new Set();
const setErr = (k, msg = null) => { if (msg) ERR.set(k, msg); else ERR.delete(k); const el = document.getElementById('err-' + k); if (el) { el.textContent = msg || ''; el.hidden = !msg; } };
const errP = k => `<p class="hint err" id="err-${k}" role="alert"${ERR.has(k) ? '' : ' hidden'}>${esc(ERR.get(k) || '')}</p>`;
// a seller claim as the platform states it: claimed, never checked by Carlos (a null claim is not asked about)
const claim = x => x == null ? PEND() : `${esc(x)} <span class="tag">${t('claimed')}</span>`;

// an inline confirm for a photo action (remove, or delete for good): hidden until its button opens it
const askBox = (mode, question, yes, id = '') => `<div class="photo-ask" data-ask="${mode}" data-id="${id}" hidden><p class="small">${esc(question)}</p>
  <div class="row"><button type="button" class="btn danger sm" data-ask-yes>${yes}</button><button type="button" class="btn ghost sm" data-ask-no>${t('photo_cancel')}</button></div></div>`;
// photos removed (archived, #photo-remove): hidden from the strip; restorable, or deleted for good after a second confirm
function removedPhotos(list) {
  if (!list.length) return '';
  return `<details class="removed-photos"><summary class="small">${t('photos_removed', { n: list.length })}</summary><ul class="removed-list">${list.map(m => {
    const when = esc(fmtDate(m.captured_at));
    return `<li><span class="small">${t('photo_removed_item', { d: when })}</span>
      <span class="row"><button type="button" class="btn ghost sm" data-restore="${m.id}" aria-label="${t('photo_restore_aria', { d: when })}">${t('photo_restore')}</button>
      <button type="button" class="btn danger sm" data-delete-ask="${m.id}" aria-label="${t('photo_delete_aria', { d: when })}">${t('photo_delete')}</button></span>
      ${askBox('delete', t('photo_delete_ask'), t('photo_delete'), m.id)}</li>`; }).join('')}</ul></details>`;
}
function viewer(d) {
  PHOTOS = d.media.map(m => m.file_path); PHOTO_IDS = d.media.map(m => m.id); cur = 0;
  const removed = removedPhotos(d.removed_media || []);
  if (!PHOTOS.length) return `<div class="card"><div class="hero" style="cursor:default;aspect-ratio:16/10"><span class="nophoto"><span>${CAR_SVG}${t('no_photos_unit')}</span></span></div>${removed}</div>`;
  return `<div class="card viewer" style="padding:12px">
    <div style="position:relative"><button class="main" type="button" data-zoom aria-label="${t('zoom')}"><img id="vMain" src="${media(PHOTOS[0])}" alt="${t('photo_n', { n: 1 })} · ${unitName(d)}"><span class="count" id="vCount">1 / ${PHOTOS.length}</span></button>
      ${PHOTOS.length > 1 ? `<button class="navbtn prev" type="button" data-step="-1" aria-label="${t('prev_photo')}">‹</button><button class="navbtn next" type="button" data-step="1" aria-label="${t('next_photo')}">›</button>` : ''}</div>
    <div class="strip" role="group" aria-label="${t('thumbnails')}">${PHOTOS.map((p, i) => `<span class="thumb"><button type="button" data-photo="${i}" aria-current="${i === 0}" aria-label="${t('photo_n', { n: i + 1 })}"><img src="${media(p)}" alt="" loading="lazy"></button><button type="button" class="photo-rm" data-remove="${PHOTO_IDS[i]}" data-n="${i + 1}" aria-label="${t('photo_remove', { n: i + 1 })}">${t('photo_remove_btn')}</button></span>`).join('')}</div>
    ${askBox('remove', '', t('photo_remove_btn'))}${errP('photo')}${removed}</div>`;
}
function showPhoto(i) {
  if (!PHOTOS.length) return; cur = (i + PHOTOS.length) % PHOTOS.length;
  const m = $('vMain'); if (m) { m.src = media(PHOTOS[cur]); m.alt = t('photo_n', { n: cur + 1 }); $('vCount').textContent = `${cur + 1} / ${PHOTOS.length}`; }
  document.querySelectorAll('.strip [data-photo]').forEach(b => b.setAttribute('aria-current', +b.dataset.photo === cur));
  // centre the thumbnail by scrolling the strip itself; scrollIntoView also scrolled the page (issue #179)
  const th = document.querySelector(`.strip [data-photo="${cur}"]`), st = th?.closest('.strip');
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
  if (d.score == null) return `<div class="scorecard"><div class="sc-top">${title}</div><div class="sc-none"><span class="pending">${esc(notScoredTxt(d))}</span></div></div>`;
  const band = SCORE_BANDS.find(([min]) => d.score >= min)[1], word = t('score_' + band);
  const scored = S.units.filter(u => !u.is_reference && u.listing_status !== 'WITHDRAWN' && u.score != null);
  const n = scored.length + (d.is_reference || scored.some(u => u.id === d.id) ? 0 : 1);
  const avg = scored.length ? scored.reduce((a, u) => a + u.score, 0) / scored.length : null, gap = avg == null ? null : d.score - avg;
  const keys = Object.keys(S.ranking.criteria);
  const parts = (d.explain || []).filter(x => x.contribution > 0).sort((a, b) => b.contribution - a.contribution);
  const legend = parts.length > 5 ? [...parts.slice(0, 4), { criterion: null, contribution: parts.slice(4).reduce((a, x) => a + x.contribution, 0) }] : parts;
  let at = 0;
  // each criterion is a ring segment with small rounded corners that never leaves its own slot (issue #195): the
  // segment is inset by its corner radius and stroked with that radius and round joins, so tiny contributions become
  // short rounded pieces in sequence instead of full-size dots overlapping their neighbours
  const pt = (r, l) => { const a = l / 50 - Math.PI / 2; return `${(60 + r * Math.cos(a)).toFixed(2)} ${(60 + r * Math.sin(a)).toFixed(2)}`; };
  const arcs = parts.map(x => { const len = x.contribution / 100 * RC, slot = len - 2.5;  // 2.5: gap between segments
    const r = Math.max(0.3, Math.min(3, slot / 2)), s = at + 1.25 + r, e = Math.max(s + 0.01, at + len - 1.25 - r), big = (e - s) / 50 > Math.PI ? 1 : 0;
    at += len;
    if (slot <= 0.6) return '';  // too small to draw without touching a neighbour; still listed in the legend
    const ro = 56.5 - r, ri = 43.5 + r, c = critColor(x.criterion, keys);
    return `<path class="sr-arc" fill="${c}" stroke="${c}" stroke-width="${(2 * r).toFixed(2)}" d="M${pt(ro, s)}A${ro} ${ro} 0 ${big} 1 ${pt(ro, e)}L${pt(ri, e)}A${ri} ${ri} 0 ${big} 0 ${pt(ri, s)}Z"/>`; }).join('');
  const aria = `${t('plate_score')} ${num(d.score, 0)} / 100, ${word}; ${parts.map(x => `${t('c_' + x.criterion)} ${num(x.contribution, 0)}`).join(', ')}`;
  return `<div class="scorecard sc-${band}${SWEEP ? ' sc-sweep' : ''}">
    <div class="sc-top">${title}<span class="sc-rank">${d.rank ? t('sc_rank', { r: d.rank, n }) : t('ref_not_ranked')}</span></div>
    <div class="sr"><div class="sr-ring"><svg viewBox="0 0 120 120" role="img" aria-label="${esc(aria)}"><circle class="sr-track" r="50" cx="60" cy="60"/><g class="sr-arcs">${arcs}</g>${avg == null ? '' : `<line class="sr-avg" ${ringAt(avg, 40, 60)}/>`}</svg>
      <div class="sr-mid"><b class="sc-num">${scoreTxt(d)}</b><span class="sc-word">${word}</span></div></div>
      <ul class="sr-legend">${legend.map(x => `<li><i style="background:${x.criterion ? critColor(x.criterion, keys) : 'var(--text-3)'}"></i><span>${x.criterion ? t('c_' + x.criterion) : t('sc_other')}</span><b class="num">${num(x.contribution, 0)}</b></li>`).join('')}</ul></div>
    <p class="sc-cov">${gap == null ? '' : `<span class="sr-gap ${gap >= 0 ? 'up' : 'down'}">${gap >= 0 ? '▲' : '▼'} ${t('sc_vs_avg', { d: (gap >= 0 ? '+' : '−') + num(Math.abs(gap), 0), a: num(avg, 0) })}</span>`}</p></div>`;
}
// reliability plate (#358): one number 0-100 from external sources, n of 3 sources, one meter per slot (engine, HU defects, breakdowns)
const relBand = v => v >= 60 ? 'good' : v >= 35 ? 'avg' : 'poor';
const relValue = x => x.source_key === 'TUEV_REPORT' ? `${num(x.value, 1)} % ${t('rel_vs')} ${num(x.class_average, 1)} %`
  : x.source_key === 'ADAC_PANNENSTATISTIK' ? t('rel_band_of_5', { n: x.band, y: x.reg_year })
  : x.source_key === 'AUTOSCORE' ? t('rel_risk_of_10', { n: num(x.value, 1) }) : `${num(x.value, 0)} / 100`;
function relBox(d) {
  const rs = d.reliability_sources || { slots: {}, present: 0, of: 3 }, total = (d.metrics || {}).reliability;
  const tip = `<span class="tipicon" tabindex="0" role="img" aria-label="${esc(t('plate_rel_note'))}" data-tip="${esc(t('plate_rel_note'))}">${INFO_SVG}</span>`;
  const head = `<div class="rb-head">${t('plate_reliability')} ${tip}<span class="rb-total num">${total == null ? PEND() : num(total, 0)}</span></div>`;
  const rows = SLOTS.map(k => { const sl = rs.slots[k], name = esc(t('rel_slot_' + k));
    if (!sl) return `<span class="rb-part">${name}</span><span class="rb-meter"></span><span class="rb-val small muted">${t('rel_not_covered')}</span>`;
    return `<span class="rb-part">${name}</span><span class="rb-meter rb-${relBand(sl.points)}" role="img" aria-label="${name} ${num(sl.points, 0)} / 100"><i style="width:${Math.max(2, sl.points)}%"></i></span><span class="rb-val num">${num(sl.points, 0)}</span>`; }).join('');
  return `<div class="relbox">${head}<div class="rb-rows">${rows}</div><p class="small muted" style="margin:6px 0 0">${t('rel_coverage', { n: rs.present, m: rs.of })} · ${goTab('reliability', t('dt_reliability'))}</p></div>`;
}
// the cost per month, the other key figure, as a strip at the top of the plate (issue #80)
const costStrip = d => `<div class="plate-cost"><span>${t(d.tco_complete ? 'plate_cost_short' : 'plate_cost_partial')}</span><b>${perMonth(d, `<small>${t('per_month')}</small>`)}</b></div>`;  // total cost of ownership per month
function plate(d) {
  const row = (k, v, cls = '') => `<dt class="${cls}">${k}</dt><dd class="${cls}">${v}</dd>`;
  return `<aside class="plate" aria-label="${esc(t('plate_title'))}">${costStrip(d)}<details class="plate-more"${matchMedia('(max-width:640px)').matches ? '' : ' open'}><summary>${t('plate_more')}</summary><dl>
    ${d.is_reference ? '' : row(t('asking_price'), eP(d.price_eur))}
    ${row(t('mileage'), d.mileage_km == null ? PEND() : num(d.mileage_km, 0) + ' km')}
    ${row(t('registration'), d.first_registration ? esc(d.first_registration) : PEND())}
    ${row(t('age'), (d.metrics || {}).age == null ? PEND() : yrs(d.metrics.age))}
    ${row(t('engine'), `<a href="${modelsHref({ engine: d.engine_code })}">${esc(d.engine_code)}</a>`)}
    ${row(t('power'), d.power_ps == null ? PEND() : num(d.power_ps, 0) + ' PS')}
    ${row(t('consumption'), consumptionTxt(d))}
    ${row(t('plate_position'), d.rank ? `#${d.rank}` : `<span class="pending">${t(d.is_reference ? 'ref_not_ranked' : 'not_ranked')}</span>`)}
    ${row(t('tco_complete'), d.tco_complete ? `<span class="tag good">${t('yes')}</span>` : `<span class="tag warn">${t('subtotal_partial')}</span>`)}</dl>${relBox(d)}</details>
    ${d.verdict ? `<div class="stamp">${t('plate_stamp')}: ${esc(d.verdict)}</div>` : ''}</aside>`;
}
function valuationRow(d, v) {
  const r = v.expected_eur != null && v.low_eur != null && v.high_eur != null && v.high_eur > v.low_eur ? `<div class="range" aria-hidden="true"><i style="left:${(v.expected_eur - v.low_eur) / (v.high_eur - v.low_eur) * 100}%"></i></div><div class="small muted" style="display:flex;justify-content:space-between"><span>${euro(v.low_eur)}</span><span>${euro(v.high_eur)}</span></div>` : '';
  return `<div style="margin-bottom:12px"><div style="display:flex;justify-content:space-between;gap:8px"><b class="small">${v.kind === 'sale_today' ? t('sale_today') : t('resale_end')}${v.horizon_years ? ` (${yrs(v.horizon_years)})` : ''}</b><b>${eP(v.expected_eur)}</b></div>${r}<div class="small muted">${esc(tv(v.status))} · ${srcName(d, v.source_id)}${v.notes ? ' · ' + esc(v.notes) : ''}</div></div>`;
}
// the seller's rating as the platform publishes it (issue #135): read from the newest capture that has one (mobile.de
// "Händlerbewertung": "3.2 Sterne (28 Bewertungen)"); private sellers have none, so no row
function sellerRating(d) {
  if (d.seller_rating != null) return `<span class="stars" aria-hidden="true">★</span> ${num(d.seller_rating, 1)} / 5${d.seller_reviews != null ? ' · ' + t('reviews_n', { n: d.seller_reviews }) : ''}`;
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
function rankCard(d) {  // the reference car is scored too (issue #72), only not ranked
  const R = S.ranking;
  const rows = (d.explain && d.explain.length ? d.explain : Object.keys(R.criteria).map(k => ({ criterion: k, weight: R.weights[k], value: d.metrics[k], score: null, contribution: null, why_missing: 'no value for this car' }))).map(x => {
    const k = x.criterion;
    return `<tr><td><b>${t('c_' + k)}</b><div class="small muted">${esc(t('cb_' + k))}</div></td><td class="n">${x.weight || '<span class="muted">0</span>'}</td><td class="n">${x.value == null ? PEND() : FMT[k](x.value)}${x.anchor ? `<div class="small muted">${t('anchor_note', { v: FMT[k](x.anchor) })}</div>` : ''}</td>
      <td class="sc-cell">${x.score == null ? `<span class="muted small">${t('why_' + (x.why_missing || 'no value for this car').replace(/ /g, '_'))}</span>` : `<div class="scorebar" title="${x.score}"><i style="width:${x.score}%"></i></div><span class="small">${x.score} · ${t('contribution')} ${num(x.contribution, 0)}%</span>`}</td></tr>`; }).join('');
  const head = d.score == null ? `<span class="pending">${esc(notScoredTxt(d))}</span>` : `<b class="big" style="font-size:22px">${scoreTxt(d)}</b> <span class="muted small">${d.rank ? t('rank_n', { n: d.rank }) : t('ref_not_ranked')}</span>`;
  return `<div class="card span2"><h3>${t('ranking')}</h3><div style="margin-bottom:8px">${head} ${R.manual ? `<span class="tag warn">${t('weights_manual')}</span>` : ''}</div><div class="tags">${statusTags(d).join('')}</div>
    <div class="tablewrap" style="margin-top:10px"><table class="rank-tbl"><thead><tr><th>${t('criterion')}</th><th class="n">${t('weight')}</th><th class="n">${t('value')}</th><th>${t('score')}</th></tr></thead><tbody>${rows}</tbody></table></div>
    <details style="margin-top:10px"><summary class="small" style="cursor:pointer">${t('research_title')}: ${t('c_confidence')} ${d.metrics.confidence == null ? '–' : num(d.metrics.confidence, 0) + ' %'}</summary><p class="small muted" style="margin:6px 0 0">${t('research_lead')}</p>${researchLevels(d.research_levels)}</details>
    <p class="small muted" style="margin:8px 0 0"><a href="#/ranking">${t('ranking_edit')}</a></p></div>`;
}
// the source as a visible link (title, quality letter), not a bare id
const srcName = (d, id) => { const x = id == null ? null : d.sources.find(s => s.id === id); return id == null ? PEND() : !x ? `#${id}` : `${x.url ? `<a href="${safeUrl(x.url)}" target="_blank" rel="noopener">${esc(x.title)}</a>` : esc(x.title)} ${qTag(x.quality)}`; };
const srcLink = (d, id) => { const x = d.sources.find(s => s.id === id); return x ? qTag(x.quality, x.title + (x.limitations ? ' — ' + x.limitations : '')) : ''; };
// one row per certain one-off cost of this car (unit_costs of a category), named, so a total never hides what it includes
const certainOf = (d, cat) => d.unit_costs.filter(x => x.category === cat).map(x => ({ ...x, eur: x.parts_eur == null && x.labor_eur == null ? null : (x.parts_eur || 0) + (x.labor_eur || 0) }));  // no price = pending, never 0
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
const certainRows = (d, rows) => rows.map(x => `<tr><td colspan="6">${esc(x.item)} <span class="tag">${t('certain_tag')}</span> ${noteBox(x.notes)}</td><td class="n">${eP(x.eur)}</td><td>${srcLink(d, x.source_id)}</td></tr>`).join('');
function maintenanceCard(d) {
  const rows = d.maintenance_plan || [], cm = certainOf(d, 'maintenance'); if (!rows.length && !cm.length) return `<div class="card span2"><h3>${t('mp_title')}</h3>${empty(t('mp_none'))}</div>`;
  const tot = sumKnown([...rows.map(r => r.cost_eur), ...cm.map(x => x.eur)], v => v), hrs = rows.reduce((a, r) => a + (r.diy_hours || 0), 0);
  return `<div class="card span2"><h3>${t('mp_title')}</h3><p class="small muted" style="margin-top:0">${t('mp_lead', { km: num(d.period_km, 0), m: d.period_months == null ? '…' : num(d.period_months, 0) })}</p>
    <div class="tablewrap"><table><thead><tr><th>${t('mp_job')}</th><th>${t('level')}</th><th>${t('mp_interval')}</th><th>${t('mp_who')}</th><th class="n">${t('mp_price')}</th><th class="n">${t('mp_times')}</th><th class="n">${t('mp_cost')}</th><th>${t('mp_src')}</th></tr></thead><tbody>
    ${rows.map(r => `<tr><td>${esc(r.item)}${r.restarted ? ` ${resetTag(d, r.id)}` : ''}<div class="small muted">${esc(tv(r.status) ?? '')} ${noteBox(r.notes)}</div></td><td>${lvlTag(r.level, r)}</td>
      <td>${intervalTxt(r.interval_km, r.interval_months)}</td><td>${r.diy ? t('mp_diy') : t('mp_ws')}</td><td class="n">${eP(r.price_eur)}</td>
      <td class="n">×${num(r.occurrences, 2)}</td><td class="n">${eP(r.cost_eur)}${r.diy_hours ? `<div class="small muted">${num(r.diy_hours, 1)} h</div>` : ''}</td><td>${srcLink(d, r.source_id)}</td></tr>`).join('')}
    ${certainRows(d, cm)}
    <tr><td colspan="6"><b>${t('mp_total')}</b></td><td class="n"><b>${d.components?.maintenance != null ? euro(d.components.maintenance) : totalP(tot)}</b>${hrs ? `<div class="small muted">${num(hrs, 1)} h</div>` : ''}</td><td></td></tr></tbody></table></div></div>`;
}
function risksCard(d) {
  const fp = d.fault_plan || [], cr = certainOf(d, 'repairs');
  if (!fp.length && !cr.length) return `<div class="card span2"><h3>${t('rk_title')}</h3>${empty(t('rk_none'))}</div>`;
  // the repairs component = certain + weak points (carlos/costs.py). The total is the server's figure: it is unknown
  // (NULL) without a mileage, without any researched weak point, or with an unpriced one, and it also counts the
  // PRESENT items of the car's history. The expected row is shown only while the server knows that part.
  const cd = d.cost_detail || {}, expKnown = cd.repairs_expected != null;
  return `<div class="card span2"><h3>${t('rk_title')}</h3>
    <div class="tablewrap"><table><thead><tr><th colspan="6">${t('rk_comp')}</th><th class="n">${t('rk_exp')}</th><th>${t('mp_src')}</th></tr></thead><tbody>
    ${fp.length ? `<tr><td colspan="6"><b>${t('rk_faults_total', { n: fp.length })}</b> ${goTab('reliability', t('dt_reliability'))}</td><td class="n"><b>${expKnown ? totalP(sumKnown(fp, f => f.expected_eur)) : PEND()}</b></td><td></td></tr>` : ''}
    ${cr.length ? `<tr><td colspan="8" class="small muted">${t('rk_certain')}</td></tr>${certainRows(d, cr)}` : ''}
    ${cd.repairs_certain != null ? `<tr><td colspan="6"><b>${t('co_certain')}</b></td><td class="n"><b>${euro(cd.repairs_certain)}</b></td><td></td></tr>` : ''}
    <tr><td colspan="6"><b>${t('rk_repairs_total')}</b></td><td class="n"><b>${eP(d.components?.repairs)}</b></td><td></td></tr></tbody></table></div></div>`;
}
// what is known about this car (#174): jobs done, faults present or ruled out, recalls checked; and its insurance quotes
function historyCard(d) {
  const h = d.history || [], q = [];  // insurance quotes moved to the Costs tab (#340)
  if (!h.length) return '';
  return `<div class="card"><h3>${t('history_title')}</h3>${h.length ? `<ul class="check">${h.map(x => `<li><span class="ico ${x.status === 'PRESENT' || x.status === 'OPEN' ? 'bad' : 'ok'}" aria-hidden="true">${x.status === 'PRESENT' || x.status === 'OPEN' ? '!' : '✓'}</span><div><b>${esc(x.item)}</b> <span class="tag">${esc(tv(x.status))}</span> <span class="tag">${esc(tv(x.evidence))}</span><div class="small muted">${[x.event_date, x.km == null ? null : num(x.km, 0) + ' km', x.parts_eur == null && x.labor_eur == null ? null : euro((x.parts_eur || 0) + (x.labor_eur || 0)) + (x.parts_eur == null || x.labor_eur == null ? ' ' + t('partial_short') : '')].filter(Boolean).map(esc).join(' · ')}</div></div></li>`).join('')}</ul>` : empty(t('no_rows'))}
    ${q.length ? `<h3 style="margin-top:16px">${t('quotes_title')}</h3><div class="tablewrap"><table><thead><tr><th>${t('date')}</th><th class="n">${t('premium')}</th><th>${t('status')}</th><th>${t('mp_src')}</th></tr></thead><tbody>${q.map(x => `<tr><td>${esc(x.quote_date ?? '')}</td><td class="n">${eP(x.annual_premium_eur)}</td><td>${esc(tv(x.premium_status))}${x.insurer ? ' · ' + esc(x.insurer) : ''}</td><td>${srcLink(d, x.source_id)}</td></tr>`).join('')}</tbody></table></div>` : ''}</div>`;
}
// the TÜV / ADAC figures of the model by age (#289), as published; the class average (when the report gives one) feeds the score
// Reliability tab (#340): per part, its score out of 9, weak points (faults with chance, price, expected cost, what to check), recalls
// with their checklist state, and any older weak-point rows; then TÜV/ADAC figures and the known history of this car
function partCard(d, part) {
  const faults = (d.fault_plan || []).filter(f => (f.part ?? null) === part).sort((a, b) => (b.expected_eur || 0) - (a.expected_eur || 0));
  const recalls = (d.recalls || []).filter(r => (r.part ?? null) === part);
  const legacy = (d.reliability || []).filter(r => (r.part ?? null) === part);
  const fRows = faults.map(r => `<tr${r.expected_eur ? '' : ' class="muted"'}><td><b>${esc(r.component)}</b> ${esc(r.issue ?? '')}${r.fixed ? ` <span class="tag good">${t('f_fixed')}</span>` : ''}${r.window_uncertain ? ` <span class="tag warn">${t('f_window_uncertain')}</span>` : ''}${r.inspection_action ? `<div class="small muted">→ ${esc(r.inspection_action)}</div>` : ''}${r.notes ? noteBox(r.notes) : ''}</td><td>${lvlTag(r.level, r)}</td><td>${faultProb(r)}</td><td>${sevTag(r.severity)} </td><td class="n">${pct(r.probability, 1)}</td><td class="n">${eP(r.price_eur)}</td><td class="n">${eP(r.expected_eur)}</td><td>${srcLink(d, r.source_id)}</td></tr>`);
  const rcRows = recalls.map(r => `<li><span class="ico ${'bad'}" aria-hidden="true">${'!'}</span><div><b>${esc(r.code)}</b> <span class="tag warn">${t('rel_recall')}</span> ${lvlTag(r.level, r)}  ${srcLink(d, r.source_id)}<div class="small">${esc(r.defect ?? '')}</div>${r.remedy ? `<div class="small muted">${t('rel_remedy')}: ${esc(r.remedy)}</div>` : ''}${r.notes ? noteBox(r.notes) : ''}</div></li>`).join('');
  const lgRows = legacy.map(r => `<li><span class="ico pend" aria-hidden="true">i</span><div><b>${esc(r.component)}</b> · ${esc(r.issue ?? '')}<div class="small" style="margin:4px 0">${sevTag(r.severity)} ${lvlTag(r.level, r)}${r.is_recall ? ` <span class="tag warn">${t('rel_recall')}</span>` : ''} </div>${r.inspection_action ? `<div class="small muted">→ ${esc(r.inspection_action)}</div>` : ''}</div></li>`).join('');
  return `<div class="card span2"><h3>${esc(t('part_' + part))} <span class="muted small num"></span></h3>
    ${fRows.length ? `<h4 class="small" style="margin:8px 0 4px">${t('rel_weak')}</h4>${tbl([[t('rk_comp')], [t('level')], [t('f_band')], [t('severity')], [t('rk_prob'), 1], [t('mp_price'), 1], [t('rk_exp'), 1], [t('mp_src')]], fRows)}` : ''}
    ${rcRows ? `<h4 class="small" style="margin:12px 0 4px">${t('rel_recalls')}</h4><ul class="check">${rcRows}</ul>` : ''}${lgRows ? `<ul class="check">${lgRows}</ul>` : ''}
    ${fRows.length || rcRows || lgRows ? '' : empty(t('rel_none_known'))}</div>`;
}
const RATING_ORDER = ['AUTOSCORE', 'ENGINESCOPE', 'TUEV_REPORT', 'ADAC_PANNENSTATISTIK', 'ADAC_GWINFO'];
const extLink = (url, label) => `<a href="${safeUrl(url)}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>`;
// the slots with the sources behind them (#358): value as published, edition, source name linking to its page; a slot without a rating is "not covered"
function slotsCard(d) {
  const rs = d.reliability_sources || { slots: {}, present: 0, of: 3 };
  const rows = SLOTS.map(k => { const sl = rs.slots[k];
    return `<tr><td><b>${esc(t('rel_slot_' + k))}</b></td>${sl ? `<td>${sl.sources.map(x => `<div>${extLink(x.url, x.source)} <span class="muted small">${t('rel_edition')} ${esc(x.edition)}${x.nearest_class ? ' · ' + t('rel_nearest_class') : ''}</span></div>`).join('')}</td>
      <td>${sl.sources.map(x => `<div>${esc(relValue(x))}${x.value_text ? ` <span class="muted small">${esc(x.value_text)}</span>` : ''}</div>`).join('')}</td><td class="n">${num(sl.points, 0)}</td>`
      : `<td colspan="2" class="muted">${t('rel_not_covered')}</td><td class="n">–</td>`}</tr>`; });
  return `<div class="card span2"><h3>${t('reliability')} <span class="muted small num">${rs.score == null ? t('rel_coverage', { n: rs.present, m: rs.of }) : `${num(rs.score, 0)} · ${t('rel_coverage', { n: rs.present, m: rs.of })}`}</span></h3>
    <p class="small muted" style="margin:0 0 8px">${t('rel_lead')}</p>${tbl([[t('rel_slot')], [t('mp_src')], [t('value')], [t('score'), 1]], rows)}
    <p class="small muted" style="margin:8px 0 0">${t('rel_gearbox_gap')} ${t('rel_vin_check')} <a href="https://www.kba.de/DE/Themen/Marktueberwachung/Rueckrufe/rueckrufe_node.html" target="_blank" rel="noopener noreferrer">${t('rel_recall_kba')} ↗</a></p></div>`;
}
// every key of this car's engine and generation, also those without a score (link only); TÜV and ADAC list the whole table
function sourceCards(d) {
  const keys = d.rating_keys || [], rats = d.ratings || [], used = (d.reliability_sources || { slots: {} }).slots;
  const usedOf = (src, f) => Object.values(used).some(sl => sl && sl.sources.some(x => x.source_key === src && f(x)));
  return RATING_ORDER.map(src => {
    const ks = keys.filter(k => k.source_key === src), rs = rats.filter(r => r.source_key === src && ks.some(k => k.external_key.toUpperCase() === r.external_key.toUpperCase()));
    const name = esc(t('rel_src_' + src));
    if (!ks.length) return `<div class="card"><h3>${name}</h3>${empty(t('rel_not_covered'))}</div>`;
    const links = ks.map(k => `<div>${extLink(k.url, k.fuel_type ? `${t('rel_open_source')} (${tv(k.fuel_type)})` : t('rel_open_source'))} <span class="muted small">${esc(k.external_key)}</span></div>`).join('');
    let body = '';
    if (src === 'TUEV_REPORT') body = tbl([[t('age')], [t('rel_defects'), 1], [t('rel_class_avg'), 1], [t('rel_edition')]], rs.map(r => `<tr${usedOf(src, x => x.age_class && x.age_class[0] === r.age_from) ? ' class="hl"' : ''}><td>${r.age_from}–${r.age_to}</td><td class="n">${num(r.value_num, 1)} %</td><td class="n">${num(r.class_average, 1)} %</td><td>${esc(r.edition)}</td></tr>`));
    else if (src === 'ADAC_PANNENSTATISTIK') body = tbl([[t('rel_reg_year')], [t('rel_band_col'), 1], [t('rel_edition')]], rs.map(r => `<tr${usedOf(src, x => x.reg_year === r.reg_year) ? ' class="hl"' : ''}><td>${r.reg_year}</td><td class="n">${r.band} / 5</td><td>${esc(r.edition)}</td></tr>`));
    else if (rs.length) body = rs.map(r => `<div>${esc(relValue({ source_key: src, value: r.value_num }))}${r.value_text ? ` · ${esc(r.value_text)}` : ''} <span class="muted small">${t('rel_edition')} ${esc(r.edition)}</span></div>`).join('');
    else if (src === 'ENGINESCOPE') body = `<p class="small muted">${t('rel_no_permission')}</p>`;
    return `<div class="card${rs.length > 3 ? ' span2' : ''}"><h3>${name}</h3>${links}${body}</div>`;
  }).join('');
}
function reliabilityTab(d) {
  const other = ['fault_plan', 'recalls', 'reliability'].some(k => (d[k] || []).some(r => !PARTS.includes(r.part)));
  return `${slotsCard(d)}${sourceCards(d)}
    ${[...PARTS, ...(other ? [null] : [])].map(p => p ? partCard(d, p) : `<div class="card span2"><h3>${t('rel_no_part')}</h3>${(d.fault_plan || []).filter(f => !PARTS.includes(f.part)).map(f => `<div>${esc(f.component)}</div>`).join('')}</div>`).join('')}
    ${historyCard(d)}`;
}
function inspectionCard(d) {
  const c = d.inspection_counts, tot = d.inspection.length, ok = c.OK ?? 0;
  if (!VIEWING) return `<div class="card"><h3>${t('inspection')} ${tot ? `<span class="muted small">${ok}/${tot} OK</span>` : ''}</h3>
      ${tot ? `<div class="meter good" style="margin-bottom:10px" aria-hidden="true"><i style="width:${ok / tot * 100}%"></i></div><ul class="check">${d.inspection.map(i => { const [cls, ch] = ICON[i.status] || ICON.PENDING;
        return `<li><span class="ico ${cls}" aria-hidden="true">${ch}</span><div>${esc(i.item)}<div class="small muted">${esc(tv(i.status))}${i.checked_date ? ' · ' + esc(i.checked_date) : ''}${i.notes ? ' · ' + esc(i.notes) : ''}</div></div></li>`; }).join('')}</ul>` : empty(t('no_checklist_short'))}</div>`;
  return `<div class="card span2 viewing-on"><h3>${t('inspection')} <span class="muted small" id="insp-count">${ok}/${tot} OK</span></h3>
    <ul class="check">${d.inspection.map(i => { const [cls, ch] = ICON[i.status] || ICON.PENDING;
      return `<li data-item="${i.id}"><span class="ico ${cls}" aria-hidden="true">${ch}</span><div><div>${esc(i.item)}</div>
        <div class="vbtns" role="group" aria-label="${esc(i.item)}">${['OK', 'PROBLEM', 'N/A', 'PENDING'].map(st => `<button type="button" data-insp="${i.id}" data-st="${st}" aria-pressed="${i.status === st}" title="${esc(tv(st))}">${t('vb_' + st.replace('/', ''))}</button>`).join('')}</div>
        <input class="vnote" data-inote="${i.id}" value="${esc(i.notes ?? '')}" placeholder="${t('note_ph')}" aria-label="${esc(t('note_ph') + ' (' + i.item + ')')}" aria-describedby="err-i${i.id}"${ERR.has('i' + i.id) ? ' aria-invalid="true"' : ''}></div>${errP('i' + i.id)}</li>`; }).join('')}</ul>
    <div style="margin-top:12px"><input class="vnote" id="newcheck" placeholder="${t('add_check_ph')}" aria-label="${t('add_check_ph')}" aria-describedby="err-newcheck"><button class="btn ghost sm" type="button" id="addCheck" data-addcheck style="margin-top:6px">${t('add_check')}</button>${errP('newcheck')}</div></div>`;
}
// the seller's claims and the jobs the seller says are done, to ask at the viewing (only what the listing already has; none = no card)
function askSellerCard(d) {
  const q = [];
  if (d.accident_free_claim != null) q.push([t('accident_free'), claim(d.accident_free_claim ? t('yes') : t('no'))]);
  if (d.owners_claim != null) q.push([t('owners'), claim(d.owners_claim)]);
  if (d.hu_claim != null) q.push([t('hu'), claim(d.hu_claim)]);
  if (d.service_history_claim != null) q.push([t('history'), claim(d.service_history_claim)]);
  const names = Object.fromEntries((d.maintenance_plan || []).map(r => [r.id, r.item]));
  (d.maintenance_resets || []).filter(r => r.basis === 'SELLER CLAIM').forEach(r => q.push([esc(names[r.maintenance_item_id] ?? ''), `${t('rs_claim')}${r.notes ? ` <span class="muted">${esc(r.notes)}</span>` : ''}`]));
  if (!q.length) return '';
  return `<div class="card span2 ask-seller"><h3>${t('ask_seller')}</h3><p class="small muted" style="margin-top:0">${t('ask_seller_lead')}</p>${facts(q)}</div>`;
}
function viewingPanel() {
  if (!VIEWING) return '';
  return `<div class="card span2 viewing-on"><h3>📋 ${t('viewing_title')}</h3><p class="small muted" style="margin-top:0">${t('viewing_hint')}</p>
    <div class="row"><button class="btn" type="button" id="addPhotos" data-pick-photos aria-describedby="err-photos">${t('add_photos')}</button>
      <input type="file" accept="image/*" multiple data-photos id="photoFile" class="sr-only" tabindex="-1" aria-hidden="true"></div>${errP('photos')}
    <textarea class="vnote" id="vnote" placeholder="${t('log_ph')}" aria-label="${t('log_ph')}" aria-describedby="err-vnote"></textarea>${errP('vnote')}
    <button class="btn" type="button" id="addNote" data-addnote style="margin-top:6px">${t('add_note')}</button></div>`;
}
async function shrink(file) {  // phone photos are 3–5 MB: resize to 1280 px JPEG in the browser (the canvas copy carries no EXIF, GPS included)
  // never fall back to the original: it may carry the location (#411), so an unreadable photo is refused with a message
  const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' }).catch(() => null); if (!bmp) throw new Error(t('photo_not_shrunk'));
  const k = Math.min(1, 1280 / Math.max(bmp.width, bmp.height)), c = document.createElement('canvas');
  c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k); c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height);
  const blob = await new Promise(r => c.toBlob(r, 'image/jpeg', .82)); if (!blob) throw new Error(t('photo_not_shrunk'));
  return blob;
}
const ui = (method, path, body, ctype) => send(method, '/api/ui/' + path, body, ctype);
// a refresh of the same car keeps the page (no loading skeleton) and the scroll position, so marking a checklist
// item in viewing mode does not jump back to the top
// keepUi: a quiet redraw keeps open details, the drafts and the focused control; false after a decision (the reject field closes)
async function refresh(keepUi = true) { const y = window.scrollY; await draw(D.id, true, keepUi); window.scrollTo(0, y); refreshTco().catch(() => {}); }
// the phone top folds to a thin strip while the reader works the checklist (the viewing tab or viewing mode): the checklist starts high on the screen
const compactTop = () => VIEWING || TAB === 'viewing';
const DRAFTS = ['vnote', 'newcheck', 'rejectWhy'];
function keep() {
  const a = document.activeElement, dd = a && root.contains(a) ? Object.entries(a.dataset) : [];
  const focus = a && root.contains(a) ? (a.id ? '#' + a.id : dd.length ? dd.map(([k, v]) => `[data-${k.replace(/[A-Z]/g, c => '-' + c.toLowerCase())}="${v}"]`).join('') : '') : '';
  const why = root.querySelector('.decide-why');
  return { open: [...root.querySelectorAll('details')].map(x => x.open), drafts: DRAFTS.map(id => $(id)?.value ?? null), why: why ? !why.hidden : null, focus };
}
function restore(s) {
  root.querySelectorAll('details').forEach((x, i) => { if (s.open[i] != null) x.open = s.open[i]; });
  DRAFTS.forEach((id, i) => { const el = $(id); if (el && s.drafts[i] != null) el.value = s.drafts[i]; });
  const why = root.querySelector('.decide-why'); if (why && s.why != null) why.hidden = !s.why;
  if (s.focus) root.querySelector(s.focus)?.focus();
}

// Costs tab (#340): the eight components with total, per month, state; then one block per component with its inputs and sources
const COMP_KEYS = ['fuel', 'insurance', 'tax', 'maintenance', 'repairs', 'tyres', 'purchase_sale', 'depreciation'];
const stTag = x => x ? ` <span class="tag">${esc(tv(x))}</span>` : '';
const tbl = (head, rows) => `<div class="tablewrap"><table><thead><tr>${head.map(h => `<th${h[1] ? ' class="n"' : ''}>${h[0]}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
const certainTbl = (d, cat) => { const r = certainOf(d, cat); return r.length ? `<h4 class="small" style="margin:10px 0 4px">${t('co_certain_items')}</h4>` + tbl([[t('concept')], [t('parts'), 1], [t('labour'), 1], [t('mp_src')]], r.map(x => `<tr><td>${esc(x.item)}${stTag(x.status)} ${noteBox(x.notes)}</td><td class="n">${eP(x.parts_eur)}</td><td class="n">${eP(x.labor_eur)}</td><td>${srcLink(d, x.source_id)}</td></tr>`)) : ''; };
const none = () => empty(t('co_none'));
const goTab = (k, label) => `<a href="#" data-tab-pick="${k}" class="small">${label} →</a>`;
// a quote expires after the server's QUOTE_MAX_AGE_DAYS (60): when it stops counting as fresh, in text
function quoteExpiry(d, x) {
  if (x.premium_status !== 'QUOTE' || !x.quote_date || d.quote_max_age_days == null) return '';
  const end = new Date(x.quote_date.slice(0, 10) + 'T12:00:00'); end.setDate(end.getDate() + d.quote_max_age_days);
  const iso = `${end.getFullYear()}-${String(end.getMonth() + 1).padStart(2, '0')}-${String(end.getDate()).padStart(2, '0')}`;
  return end < new Date() ? `<div class="small"><span class="tag warn">${t('q_expired', { d: fmtDate(iso) })}</span></div>` : `<div class="small muted">${t('q_valid_until', { d: fmtDate(iso) })}</div>`;
}
// a manual insurance quote (#399): typed in by the account, never fetched by Carlos; the comparison site is a plain link
let QUOTE_OK = false;
const COVERS = ['Haftpflicht', 'Teilkasko', 'Vollkasko'];
function quoteForm(d, hasQuote) {
  const ok = QUOTE_OK; QUOTE_OK = false;
  const today = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  const fld = (id, label, input, err = false) => `<div class="field"><label for="${id}">${label}</label>${input}${err ? `<p class="hint err" id="${id}-err" hidden></p>` : ''}</div>`;
  const inp = (id, attrs = '') => `<input id="${id}" type="text" autocomplete="off" spellcheck="false" ${attrs}>`;
  const car = [d.hsn && d.tsn ? `HSN/TSN ${esc(d.hsn)}/${esc(d.tsn)}` : '', d.first_registration ? `${t('registration')} ${esc(d.first_registration)}` : ''].filter(Boolean).join(' · ');
  return `<details class="quote-entry"${hasQuote && !ok ? '' : ' open'}><summary>${t('q_title')}</summary>
    ${ok ? `<p class="hint" id="quoteOk" role="status" tabindex="-1"><span class="tag good">${t('q_saved')}</span></p>` : ''}
    <p class="small muted">${t('q_lead')}</p>
    <div class="howto"><b class="small">${t('q_how_title')}</b><p class="small" style="margin:4px 0">${t('q_how')}</p>
      ${car ? `<p class="small muted" style="margin:4px 0">${t('q_car')}: ${car}</p>` : ''}
      <a class="small" href="https://www.check24.de/kfz-versicherungen/" target="_blank" rel="noopener noreferrer">${t('q_how_link')}</a></div>
    <form id="quoteForm" novalidate><div class="fields two">
      ${fld('q_premium', t('q_premium'), inp('q_premium', 'inputmode="decimal" required aria-describedby="q_premium-err" maxlength="12"'), true)}
      ${fld('q_period', t('q_period'), `<select id="q_period"><option value="year">${t('q_per_year')}</option><option value="month">${t('q_per_month')}</option></select>`)}
      ${fld('q_insurer', t('q_insurer'), inp('q_insurer', 'maxlength="80"'))}
      ${fld('q_tariff', t('q_tariff'), inp('q_tariff', 'maxlength="80"'))}
      ${fld('q_date', t('q_date'), `<input id="q_date" type="date" required max="${today}" value="${today}" aria-describedby="q_date-err">`, true)}
      ${fld('q_cover', t('q_cover'), `<select id="q_cover"><option value="">${t('q_unstated')}</option>${COVERS.map(v => `<option value="${v}">${t('cover_' + v)}</option>`).join('')}</select>`)}
      ${fld('q_deductible', t('q_deductible'), inp('q_deductible', 'inputmode="decimal" maxlength="6" aria-describedby="q_deductible-err"'), true)}
      ${fld('q_sf', t('q_sf'), inp('q_sf', 'maxlength="8"'))}
    </div><p class="hint err" id="q-err" role="alert" hidden></p><div class="row" style="margin-top:10px"><button class="btn" type="submit">${t('q_submit')}</button></div></form></details>`;
}
async function saveQuote(form) {
  // "1.234,56", "1,234.56", "45,90 EUR": spaces, NBSP and the euro sign go; when both separators appear the last one is the decimal point;
  // anything that is not a finite number is NaN (never sent: Infinity would reach the server as null)
  const dec = id => {
    let v = $(id).value.replace(/[\s\u00a0\p{Sc}]/gu, ''); if (v === '') return null;
    const i = Math.max(v.lastIndexOf(','), v.lastIndexOf('.'));
    if (i >= 0) v = v.slice(0, i).replace(/[.,]/g, '') + '.' + v.slice(i + 1);
    const n = /^\d+(\.\d*)?$|^\.\d+$/.test(v) ? Number(v) : NaN; return Number.isFinite(n) ? n : NaN;
  };
  const bad = (id, key) => { const e = $(id + '-err'); e.textContent = t(key); e.hidden = false; $(id).setAttribute('aria-invalid', 'true'); return $(id); };
  form.querySelectorAll('.hint.err').forEach(e => { e.hidden = true; e.textContent = ''; }); form.querySelectorAll('[aria-invalid]').forEach(e => e.removeAttribute('aria-invalid'));
  const premium = dec('q_premium'), ded = dec('q_deductible'), date = $('q_date').value;
  const first = [(premium == null || !(premium > 0)) && bad('q_premium', 'q_err_premium'),
    (!date || date > $('q_date').max) && bad('q_date', 'q_err_date'),
    ded != null && !(ded >= 0) && bad('q_deductible', 'q_err_deductible')].find(Boolean);
  if (first) { first.focus(); return; }
  const btn = form.querySelector('button[type=submit]'), err = $('q-err');
  try {
    await busy(btn, () => ui('POST', 'listing_quotes', { listing_id: D.id, premium_eur: premium, period: $('q_period').value, insurer: $('q_insurer').value, tariff: $('q_tariff').value,
      quote_date: date, cover: $('q_cover').value, deductible_eur: ded, sf_class: $('q_sf').value }));
    QUOTE_OK = true; await refresh(); $('quoteOk')?.focus();
  } catch (e) { err.textContent = t('q_err_server', { m: e.message }); err.hidden = false; }  // stays until the next try: no timeout
}
function costBlocks(d) {
  const cd = d.cost_detail || {}, C = d.components || {};
  const cons = (d.observations || []).filter(o => o.category === 'consumption');
  const split = (a, b) => [a, b].filter(x => x && x[1] != null).map(([l, v]) => `${l} ${euro(v)}`).join(' · ');
  const B = {};
  B.fuel = facts([[t('co_consumption'), d.consumption == null ? PEND() : `${consumptionTxt(d)}${d.consumption_metric ? ` · ${esc(d.consumption_metric)}` : ''}${consumptionSpread(d) ? ` · ${consumptionSpread(d)}` : ''} ${srcLink(d, d.consumption_source_id)}`],
    ...(cd.fuel_price_eur_l != null ? [[t('co_fuel_price'), `${num(cd.fuel_price_eur_l, 2)}\u00a0${t('unit_eur_l')}`]] : []), ...(cd.electricity_eur_kwh != null ? [[t('co_elec_price'), `${num(cd.electricity_eur_kwh, 2)}\u00a0${t('unit_eur_kwh')}`]] : []),
    [t('co_period'), `${num(d.period_km, 0)} km · ${num(d.period_months, 0)} ${t('co_months')}`]])
    + (cons.length ? `<div class="small muted">${cons.map(o => `${esc(o.metric)}${stTag(o.status)} ${qTag(o.evidence_quality)} ${noteBox(o.notes)}`).join('<br>')}</div>` : '');
  const ins = [...(d.insurance || []), ...(d.quotes || [])];
  B.insurance = (ins.length ? tbl([[t('date')], [t('premium'), 1], [t('status')], [t('mp_src')]], ins.map(x => `<tr><td>${esc(x.quote_date ?? x.year ?? '')}${quoteExpiry(d, x)}</td><td class="n">${eP(x.annual_premium_eur)}</td><td>${esc(tv(x.premium_status) ?? '')}${[x.insurer, x.tariff].filter(Boolean).map(v => ' · ' + esc(v)).join('')} ${noteBox(x.notes)}</td><td>${srcLink(d, x.source_id)}</td></tr>`)) : (d.annual_insurance != null ? facts([[t('premium'), euro(d.annual_insurance)]]) : none()))
    + (d.is_reference ? '' : quoteForm(d, ins.length > 0));
  B.tax = (d.tax || []).length ? d.tax.map(x => `${facts([[t('co_tax_year'), eP(x.annual_tax_eur) + stTag(x.status) + ' ' + srcLink(d, x.source_id)], ...(x.registered_from || x.registered_to ? [[t('co_window'), `${esc(x.registered_from ?? '…')} – ${esc(x.registered_to ?? '…')}`]] : []), ...(d.tax_exempt_months ? [[t('co_exempt'), `${num(d.tax_exempt_months, 0)} ${t('co_months')}`]] : [])])}${x.basis ? `<div class="small muted">${esc(x.basis)}</div>` : ''}`).join('') : (d.annual_tax != null ? facts([[t('co_tax_year'), euro(d.annual_tax)]]) : none());
  B.maintenance = facts([[t('co_scheduled'), eP(cd.maintenance_scheduled)], [t('co_certain'), eP(cd.maintenance_certain)], ...(cd.maintenance_diy_hours ? [[t('co_hours'), num(cd.maintenance_diy_hours, 1) + ' h']] : [])]) + certainTbl(d, 'maintenance') + goTab('maintenance', t('dt_maintenance'));
  B.repairs = facts([[t('co_certain'), eP(cd.repairs_certain)], [t('co_expected'), eP(cd.repairs_expected)]]) + certainTbl(d, 'repairs') + goTab('maintenance', t('dt_maintenance')) + ' ' + goTab('reliability', t('dt_reliability'));
  B.tyres = (d.tyres || []).length ? d.tyres.map(x => facts([[t('co_tyre_size'), `${esc(x.size ?? '')} ${esc(tv(x.tyre_type) ?? '')}${stTag(x.status)} ${srcLink(d, x.source_id)}`], [t('co_tyre_price'), `${eP(x.price_per_tyre_eur)} × ${x.tyres_per_set == null ? PEND() : x.tyres_per_set}`], [t('co_tyre_life'), x.life_km == null ? PEND() : num(x.life_km, 0) + ' km'], [t('co_fitting'), eP(x.fitting_per_set_eur)]]) + (x.notes ? `<div class="small muted">${esc(x.notes)}</div>` : '')).join('') + certainTbl(d, 'tyres') : none();
  if (cd.tyre_wear !== undefined) B.tyres += facts([[t('co_tyre_wear'), eP(cd.tyre_wear)]]);  // wear left after the certain set (#388): tyres_certain + this = the component
  const ps = certainOf(d, 'purchase_sale');
  B.purchase_sale = (d.is_reference ? '' : facts([[t('asking_price'), eP(d.price_eur)]])) + (ps.length ? certainTbl(d, 'purchase_sale') : none());
  B.depreciation = (d.is_reference ? '' : facts([[t('asking_price'), eP(d.price_eur)]])) + (d.valuations.length ? d.valuations.map(v => valuationRow(d, v)).join('') : none());
  if (cd.resale_rescaled_from_years != null) B.depreciation += `<div class="small muted">${t('co_resale_rescaled', { y: yrs(cd.resale_rescaled_from_years) })}</div>`;
  return COMP_KEYS.map(k => `<div class="card" id="co-${k}"><h3>${comp(k)} <span class="muted small num">${C[k] == null ? t('co_unknown') : euro(C[k])}</span></h3>${B[k]}</div>`).join('');
}
function costsTab(d) {
  const C = d.components || {}, mo = d.period_months, known = d.known_cost_subtotal, miss = d.missing_components || [];
  const rows = COMP_KEYS.map(k => `<tr><td><a href="#co-${k}" data-jump="co-${k}">${comp(k)}</a></td><td class="n">${eP(C[k])}</td><td class="n">${C[k] == null || !mo ? PEND() : euro(C[k] / mo) + t('per_month')}</td><td style="min-width:90px">${C[k] == null || !known ? '' : `<div class="scorebar" aria-hidden="true"><i style="width:${Math.max(2, C[k] / known * 100)}%"></i></div>`}</td></tr>`);
  const own = '';
  return `<div class="card span2"><h3>${t('co_title')}</h3><p class="small muted" style="margin-top:0">${t('co_lead', { m: mo == null ? '…' : num(mo, 0), km: num(d.period_km, 0) })}</p>
    ${tbl([[t('concept')], [t('co_total'), 1], [t('co_month'), 1], ['']], [...rows, `<tr><td><b>${miss.length ? t('co_subtotal') : t('plate_cost_short')}</b></td><td class="n"><b>${eP(known)}</b></td><td class="n"><b>${d.known_cost_per_month == null ? PEND() : euro(d.known_cost_per_month) + t('per_month')}</b></td><td></td></tr>`]).replace('<table>', '<table class="co-sum">')}
    ${miss.length ? `<p class="small muted">${t('co_missing')}: ${miss.map(k => comp(k)).join(', ')}</p>` : ''}${own}</div>${costBlocks(d)}`;
}
// tabs under a fixed top (issue #178): photos, score and spec plate always shown; the tab is kept in the URL (?tab=)
const TABS = ['overview', 'costs', 'maintenance', 'reliability', 'viewing', 'log'];
const hid = k => k === TAB ? '' : ' hidden';
const tabBar = () => `<div class="dtabs" role="tablist" aria-label="${esc(t('dt_label'))}">${TABS.map(k => `<button type="button" role="tab" data-tab-pick="${k}" aria-selected="${k === TAB}">${t('dt_' + k)}</button>`).join('')}</div>`;
function pickTab(k) {  // switches without redrawing or moving the top; replaceState so the router doesn't re-render
  TAB = k;
  root.querySelectorAll('.dtab').forEach(g => { g.hidden = g.dataset.tab !== k; });
  root.querySelectorAll('[data-tab-pick]').forEach(b => b.setAttribute('aria-selected', b.dataset.tabPick === k));
  root.querySelector('.dossier-top')?.classList.toggle('compact', compactTop());
  const [path, q] = location.hash.split('?'), sp = new URLSearchParams(q || ''); sp.set('tab', k);
  history.replaceState(null, '', `${path}?${sp}`);
}
async function draw(id, quiet = false, keepUi = true) {
  SWEEP = !quiet;
  const label = u => `${unitName(u)} ${u.is_reference ? '(' + t('reference').toLowerCase() + ')' : esc(u.listing_id ?? '')}`;
  const picker = `<div class="field unit-select"><label for="unitsel">${t('units_group')}</label><select id="unitsel" data-unitsel>${S.units.map(u => `<option value="${u.id}" ${u.id === id ? 'selected' : ''}>${label(u)}</option>`).join('')}</select></div>`;
  if (!quiet) root.innerHTML = picker + '<div class="grid"><div class="skel"></div><div class="skel"></div></div>';
  let d; try { d = await get('/api/listings/' + id); } catch (e) { root.innerHTML = picker + `<div class="card err">${t('dossier_failed', { m: esc(e.message) })}</div>`; return; }
  D = d;
  const kept = quiet && keepUi ? keep() : null;  // taken right before the swap: what the reader typed or opened since the request
  root.innerHTML = picker + `<div class="dossier-top${compactTop() ? ' compact' : ''}">${viewer(d)}<div class="dossier-side">${scoreBox(d)}${plate(d)}</div></div>${tabBar()}<div class="grid dtab" data-tab="overview"${hid('overview')}>
    <div class="card span2"><div class="unit-head"><div><h1 class="unit-name"><a class="carlink" href="#/models/${d.vehicle_id}">${unitName(d)} ${esc(d.trim ?? '')}</a></h1><div class="unit-sub">${unitSub(d)} · ${esc(tv(d.listing_status) ?? '')} <a href="#/models/${d.vehicle_id}" style="margin-left:8px">${t('open_model')}</a></div></div>
      <div class="row">${d.url ? `<a class="btn ghost sm" href="${safeUrl(d.url)}" target="_blank" rel="noopener">${t('open_listing')}</a>` : ''}<button class="btn sm${VIEWING ? '' : ' ghost'}" type="button" data-viewing>${VIEWING ? t('viewing_exit') : '📋 ' + t('viewing_start')}</button></div></div>
      ${d.is_reference ? '' : decisionBar(d)}
      ${gaps(S.todo.listings.find(x => x.listing_id === d.id)?.todo)}
      <div style="margin-top:12px">${facts([[t('asking_price'), d.is_reference ? t('owned') : eP(d.price_eur)], [t('mileage'), d.mileage_km == null ? PEND() : num(d.mileage_km, 0) + ' km'], [t('registration'), d.first_registration ? esc(d.first_registration) : PEND()],
        [t('engine'), `<a href="${modelsHref({ engine: d.engine_code })}">${esc(d.engine_code)}</a> · ${esc(d.engine_description ?? '')}`], [t('generation'), `<a href="${modelsHref({ make: d.make, model: d.model })}">${esc(d.generation)}</a> ${d.generation_start_year ?? '?'}–${d.generation_end_year ?? '?'}`],
        ...(d.is_reference ? [] : [[t('seller'), d.seller ? esc(d.seller) + (d.location ? ', ' + esc(d.location) : '') : PEND()], ...(sellerRating(d) ? [[t('seller_rating'), sellerRating(d)]] : []), [t('accident_free'), d.accident_free_claim == null ? PEND() : claim(d.accident_free_claim ? t('yes') : t('no'))], [t('owners'), claim(d.owners_claim)],
        [t('hu'), claim(d.hu_claim)], [t('history'), claim(d.service_history_claim)], [t('equipment'), d.equipment ? esc(d.equipment) : PEND()], [t('verdict'), d.verdict ? `<b>${esc(d.verdict)}</b>` : PEND()]]), [t('notes'), d.notes ? esc(d.notes) : PEND()]])}</div></div>
    ${flagsCard(d.review_flags)}${rankCard(d)}</div>
    <div class="grid dtab" data-tab="maintenance"${hid('maintenance')}>${maintenanceCard(d)}${risksCard(d)}</div>
    <div class="grid dtab" data-tab="viewing"${hid('viewing')}>${askSellerCard(d)}${inspectionCard(d)}${viewingPanel()}</div>
    <div class="grid dtab" data-tab="costs"${hid('costs')}>${costsTab(d)}</div>
    <div class="grid dtab" data-tab="reliability"${hid('reliability')}>${reliabilityTab(d)}</div>
    <div class="grid dtab" data-tab="log"${hid('log')}>
    <div class="card"><h3>${t('archive')}</h3>${archive(d)}</div>
    <div class="card"><h3>${t('log')}</h3>${d.events.length ? `<ol class="timeline">${d.events.slice().reverse().map(ev => `<li><time>${esc(ev.event_date)}</time> <span class="tag">${esc(tv(ev.kind))}</span><div>${esc(ev.text)}</div></li>`).join('')}</ol>` : empty(t('no_events'))}</div>
    <div class="card span2"><h3>${t('tab_sources')} <span class="muted small">${d.sources.length}</span></h3><div class="small">${d.sources.map(s => `<div class="src"><div class="src-title">${qTag(s.quality)} <span>${esc(s.title)}</span> ${lvlTag(s.vehicle_id ? 'variant' : s.engine_id ? 'engine' : s.generation_id ? 'generation' : 'shared')}</div>${s.url ? `<a href="${safeUrl(s.url)}" target="_blank" rel="noopener">${esc(s.url)}</a>` : ''}</div>`).join('')}</div></div></div>`;
  if (kept) restore(kept);
}
// a checklist tap: one request per item at a time (busy button, guard against the same item), then only that row changes:
// no redraw, so focus, open details and drafts stay; the failure stays on the item until its next successful save
async function tapItem(b) {
  const id = +b.dataset.insp, st = b.dataset.st; if (BUSY_ITEMS.has(id)) return; BUSY_ITEMS.add(id);
  try { await busy(b, () => ui('PATCH', 'inspection_items/' + id, { status: st }));
    setErr('i' + id); const it = D.inspection.find(x => x.id === id); if (it) it.status = st; paintItem(id, st); refreshTco().catch(() => {}); }
  catch (err) { setErr('i' + id, t('not_saved', { m: err.message })); toast(err.message, true); }
  finally { BUSY_ITEMS.delete(id); }
}
function paintItem(id, st) {
  const li = root.querySelector(`[data-item="${id}"]`); if (!li) return;
  li.querySelectorAll('[data-insp]').forEach(x => x.setAttribute('aria-pressed', x.dataset.st === st));
  const [cls, ch] = ICON[st] || ICON.PENDING, ico = li.querySelector('.ico'); ico.className = `ico ${cls}`; ico.textContent = ch;
  const c = $('insp-count'); if (c) c.textContent = `${D.inspection.filter(x => x.status === 'OK').length}/${D.inspection.length} OK`;
}
function bind() {
  root.addEventListener('change', async e => {
    if (e.target.matches('[data-unitsel]')) { go('listing/' + e.target.value); return; }
    const n = e.target.closest('[data-inote]');
    if (n) { const k = 'i' + n.dataset.inote; try { await ui('PATCH', 'inspection_items/' + n.dataset.inote, { notes: n.value }); n.removeAttribute('aria-invalid'); setErr(k); toast(t('saved_short')); } catch (err) { n.setAttribute('aria-invalid', 'true'); setErr(k, t('not_saved', { m: err.message })); toast(err.message, true); } return; }
    const ph = e.target.closest('[data-photos]'); if (ph && ph.files.length) { const files = [...ph.files], photos = $('addPhotos'); let ok = 0; ph.value = '';
      await busy(photos, async () => {
        setErr('photos');
        for (const [i, f] of files.entries()) { toast(t('uploading', { i: i + 1, n: files.length })); try { await ui('POST', 'media/' + D.id, await shrink(f), 'image/jpeg'); ok++; } catch (err) { setErr('photos', t('not_saved', { m: err.message })); toast(err.message, true); } }
        if (ok) { toast(t('photos_added', { n: ok })); await refresh(); } }); } });
  root.addEventListener('submit', e => { if (e.target.id === 'quoteForm') { e.preventDefault(); saveQuote(e.target); } });
  root.addEventListener('click', async e => {
    const tp = e.target.closest('[data-tab-pick]'); if (tp) { e.preventDefault(); pickTab(tp.dataset.tabPick); return; }
    const jp = e.target.closest('[data-jump]'); if (jp) { e.preventDefault(); document.getElementById(jp.dataset.jump)?.scrollIntoView({ behavior: 'smooth', block: 'start' }); return; }
    if (e.target.closest('[data-viewing]')) { VIEWING = !VIEWING; if (VIEWING) TAB = 'viewing'; await draw(D.id); return; }
    const dc = e.target.closest('[data-decide]'); if (dc) { const k = dc.dataset.decide;
      if (k === 'reject') { const w = root.querySelector('.decide-why'); w.hidden = false; $('rejectWhy').focus(); return; }
      try { await busy(dc, async () => { await send('POST', '/api/ui/decision/' + D.id, { decision: k === 'reject-confirm' ? 'reject' : k, reason: k === 'reject-confirm' ? $('rejectWhy').value : '' });
        setErr('decide'); toast(t('decision_saved')); await refresh(false); }); } catch (err) { setErr('decide', t('not_saved', { m: err.message })); } return; }
    const b = e.target.closest('[data-insp]'); if (b) { await tapItem(b); return; }
    if (e.target.closest('[data-pick-photos]')) { $('photoFile').click(); return; }
    const an = e.target.closest('[data-addnote]'); if (an) { const v = $('vnote').value.trim(); if (!v) return;
      try { await busy(an, async () => { await ui('POST', 'listing_events', { listing_id: D.id, text: v }); $('vnote').value = ''; setErr('vnote'); toast(t('note_added')); await refresh(); }); } catch (err) { setErr('vnote', t('not_saved', { m: err.message })); } return; }
    const ac = e.target.closest('[data-addcheck]'); if (ac) { const v = $('newcheck').value.trim(); if (!v) return;
      try { await busy(ac, async () => { await ui('POST', 'inspection_items', { listing_id: D.id, item: v }); $('newcheck').value = ''; setErr('newcheck'); await refresh(); }); } catch (err) { setErr('newcheck', t('not_saved', { m: err.message })); } return; }
    const rm = e.target.closest('[data-remove]'); if (rm) { const box = root.querySelector('.photo-ask[data-ask="remove"]'); box._from = rm; box.dataset.id = rm.dataset.remove;
      box.querySelector('p').textContent = t('photo_remove_ask', { n: rm.dataset.n }); box.hidden = false; box.querySelector('[data-ask-yes]').focus(); return; }
    const da = e.target.closest('[data-delete-ask]'); if (da) { const box = da.closest('li').querySelector('.photo-ask'); box._from = da; box.hidden = false; box.querySelector('[data-ask-yes]').focus(); return; }
    const no = e.target.closest('[data-ask-no]'); if (no) { const box = no.closest('.photo-ask'); box.hidden = true; box._from?.focus(); return; }
    const yes = e.target.closest('[data-ask-yes]'); if (yes) { const box = yes.closest('.photo-ask'), id = box.dataset.id;
      try { await busy(yes, async () => { if (box.dataset.ask === 'remove') { await ui('PATCH', 'photo/' + id, { archived: 1 }); toast(t('photo_removed_toast')); }
        else { await ui('DELETE', 'photo/' + id, { id: +id, confirm: true }); toast(t('photo_deleted')); }
        setErr('photo'); await refresh(); }); } catch (err) { setErr('photo', t('not_saved', { m: err.message })); toast(err.message, true); } return; }
    const rs = e.target.closest('[data-restore]'); if (rs) { try { await busy(rs, async () => { await ui('PATCH', 'photo/' + rs.dataset.restore, { archived: 0 }); toast(t('photo_restored')); setErr('photo'); await refresh(); }); } catch (err) { setErr('photo', t('not_saved', { m: err.message })); toast(err.message, true); } return; }
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
    <span class="decide-why" hidden><input id="rejectWhy" type="text" maxlength="300" placeholder="${esc(t('decide_reason_ph'))}" aria-label="${esc(t('decide_reason_ph'))}"><button type="button" class="btn sm danger" data-decide="reject-confirm">${t('decide_reject_confirm')}</button></span></div>${errP('decide')}`;
}
export async function render(main, r) {
  const id = r.id ?? S.units[0]?.id;
  if (TABS.includes(r.q?.tab)) TAB = r.q.tab;
  if (!root || !main.contains(root)) { main.innerHTML = '<div data-page="dossier"></div>'; root = main.firstElementChild; bind(); }
  if (id == null) { root.innerHTML = empty(t('no_units')); return; }
  await draw(id);
}
