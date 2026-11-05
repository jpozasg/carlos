// Dossier of one listing: photos, facts, ranking explanation, maintenance plan, risks, checklist (viewing mode), log.
import { S, refreshTco, go } from '../app.js';
import { get, send } from '../api.js';
import { t, tv, comp } from '../i18n.js';
import { $, esc, euro, num, PEND, eP, yrs, empty, facts, media, modelsHref, unitName, unitSub, sevTag, lvlTag, qTag, statusTags, gaps, intervalTxt, safeUrl, toast, CAR_SVG, scoreTxt } from '../ui.js';

const ICON = { OK: ['ok', '✓'], PROBLEM: ['bad', '!'], PENDING: ['pend', '·'], 'N/A': ['na', '–'] };
let PHOTOS = [], cur = 0, VIEWING = false, root, D = null;
const lb = $('lightbox');
const FMT = { cost_month: v => euro(v) + t('per_month'), cash_now: euro, mileage: v => num(v, 0) + ' km', age: yrs, reliability: v => num(v, 1), inspection: v => num(v, 0),
  power: v => num(v, 0) + ' PS', confidence: v => num(v, 0) + ' %' };
const PARTS = ['ENGINE', 'GEARBOX', 'CHASSIS', 'ELECTRICS'];  // reliability parts (config.RELIABILITY_PARTS)
const partsLine = d => PARTS.map(k => `${t('part_' + k)} ${num((d.reliability_parts || {})[k] ?? 0, 1)}`).join(' · ');

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
  document.querySelector(`.strip [data-photo="${cur}"]`)?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  if (lb.open) { lb.querySelector('img').src = media(PHOTOS[cur]); lb.querySelector('.count').textContent = `${cur + 1} / ${PHOTOS.length}`; }
}
lb.querySelector('.prev').onclick = () => showPhoto(cur - 1); lb.querySelector('.next').onclick = () => showPhoto(cur + 1); lb.querySelector('.close').onclick = () => lb.close();
lb.addEventListener('click', e => { if (e.target === lb || e.target.classList.contains('lb')) lb.close(); });
document.addEventListener('keydown', e => { if (!PHOTOS.length || !root || !document.contains(root)) return; if (e.target.closest('input,textarea,select')) return;
  if (e.key === 'ArrowRight') { showPhoto(cur + 1); e.preventDefault(); } else if (e.key === 'ArrowLeft') { showPhoto(cur - 1); e.preventDefault(); } });

function plate(d) {
  const row = (k, v, cls = '') => `<dt class="${cls}">${k}</dt><dd class="${cls}">${v}</dd>`;
  return `<aside class="plate"><span class="rv"></span><h3>${t('plate_title')}</h3><dl>
    ${row(`${t('plate_score')} <span class="tipicon" tabindex="0" role="img" aria-label="${esc(t('plate_score_note'))}" data-tip="${esc(t('plate_score_note'))}">${INFO_SVG}</span>`, d.score == null ? PEND() : scoreTxt(d), 'hi')}
    ${row(t('plate_cost'), d.known_cost_per_month == null ? PEND() : euro(d.known_cost_per_month) + t('per_month'), 'hi')}
    ${d.is_reference ? '' : row(t('asking_price'), eP(d.price_eur))}
    ${row(t('mileage'), d.mileage_km == null ? PEND() : num(d.mileage_km, 0) + ' km')}
    ${row(t('registration'), d.first_registration ? esc(d.first_registration) : PEND())}
    ${row(t('age'), (d.metrics || {}).age == null ? PEND() : yrs(d.metrics.age))}
    ${row(t('engine'), `<a href="${modelsHref({ engine: d.engine_code })}">${esc(d.engine_code)}</a>`)}
    ${row(t('power'), d.power_ps == null ? PEND() : num(d.power_ps, 0) + ' PS')}
    ${row(t('consumption'), d.consumption == null ? PEND() : num(d.consumption) + ' l/100 km')}
    ${row(`${t('plate_reliability')}<span class="muted" style="display:block;font-size:.8em">(${t('plate_lower_better')})</span>`, (d.metrics || {}).reliability == null ? PEND() : `${t('plate_rel', { n: num(d.metrics.reliability, 1) })}<span class="small muted" style="display:block;font-family:inherit">${partsLine(d)}</span>`)}
    ${row(t('plate_position'), d.rank ? `#${d.rank}` : `<span class="pending">${t(d.is_reference ? 'ref_not_ranked' : 'not_ranked')}</span>`)}
    ${row(t('tco_complete'), d.tco_complete ? `<span class="tag good">${t('yes')}</span>` : `<span class="tag warn">${t('subtotal_partial')}</span>`)}</dl>
    ${d.verdict ? `<div class="stamp">${t('plate_stamp')}: ${esc(d.verdict)}</div>` : ''}</aside>`;
}
function valuationRow(v) {
  const r = v.low_eur != null && v.high_eur != null && v.high_eur > v.low_eur ? `<div class="range" aria-hidden="true"><i style="left:${(v.expected_eur - v.low_eur) / (v.high_eur - v.low_eur) * 100}%"></i></div><div class="small muted" style="display:flex;justify-content:space-between"><span>${euro(v.low_eur)}</span><span>${euro(v.high_eur)}</span></div>` : '';
  return `<div style="margin-bottom:12px"><div style="display:flex;justify-content:space-between;gap:8px"><b class="small">${v.kind === 'sale_today' ? t('sale_today') : t('resale_end')}${v.horizon_years ? ` (${yrs(v.horizon_years)})` : ''}</b><b>${euro(v.expected_eur)}</b></div>${r}<div class="small muted">${esc(tv(v.status))} · ${t('source')} ${esc(v.source_id)}${v.notes ? ' · ' + esc(v.notes) : ''}</div></div>`;
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
    return `<tr><td><b>${t('c_' + k)}</b><div class="small muted">${esc(t('cb_' + k))}</div></td><td class="n">${x.weight || '<span class="muted">0</span>'}</td><td class="n">${x.value == null ? PEND() : FMT[k](x.value)}${x.bounds ? `<div class="small muted">${FMT[k](x.bounds.min)} – ${FMT[k](x.bounds.max)}</div>` : ''}</td>
      <td style="min-width:120px">${x.score == null ? `<span class="muted small">${t('why_' + (x.why_missing || 'no value for this car').replace(/ /g, '_'))}</span>` : `<div class="scorebar" title="${x.score}"><i style="width:${x.score}%"></i></div><span class="small">${x.score} · ${t('contribution')} ${num(x.contribution, 0)}%</span>`}</td></tr>`; }).join('');
  const head = d.score == null ? `<span class="pending">${t('not_ranked')}</span>` : `<b class="big" style="font-size:22px">${scoreTxt(d)}</b> <span class="muted small">${d.rank ? t('rank_n', { n: d.rank }) : t('ref_not_ranked')} · ${t('coverage', { n: num(d.coverage * 100, 0) })}</span>`;
  const ev = d.evidence || [], rel = d.reliability_detail || [];
  return `<div class="card span2"><h3>${t('ranking')}</h3><div style="margin-bottom:8px">${head} ${R.manual ? `<span class="tag warn">${t('weights_manual')}</span>` : ''}</div><div class="tags">${statusTags(d).join('')}</div>
    <div class="tablewrap" style="margin-top:10px"><table><thead><tr><th>${t('criterion')}</th><th class="n">${t('weight')}</th><th class="n">${t('value')}</th><th>${t('score')}</th></tr></thead><tbody>${rows}</tbody></table></div>
    <details style="margin-top:10px"><summary class="small" style="cursor:pointer">${t('evidence_title', { n: ev.length })}</summary><div class="tablewrap" style="margin-top:8px"><table><thead><tr><th>${t('ev_table')}</th><th>${t('status')}</th><th>${t('quality')}</th><th class="n">${t('ev_points')}</th></tr></thead><tbody>${ev.map(e => `<tr><td>${esc(tv(e.table))} #${e.id}</td><td>${esc(tv(e.status) ?? '—')}</td><td>${qTag(e.quality)}</td><td class="n">${num(e.points, 2)}</td></tr>`).join('')}</tbody></table></div>
      ${rel.length ? `<p class="small" style="margin:8px 0 0"><b>${t('c_reliability')}:</b> ${rel.map(r => `${esc(r.component)} ${sevTag(r.severity)} ${num(r.points, 1)}`).join(' · ')}</p>` : ''}</details>
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
    ${rows.map(r => `<tr><td>${esc(r.item)}${r.restarted ? ` ${resetTag(d, r.id)}` : ''}<div class="small muted">${esc(tv(r.status) ?? '')} ${noteBox(r.notes)}</div></td><td>${lvlTag(r.level)}</td>
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
    ${rows.map(r => `<tr${r.share ? '' : ' class="muted"'}><td><span title="${esc(r.evidence ?? '')}${r.notes ? ' — ' + esc(r.notes) : ''}">${esc(r.component)}</span>${r.diy ? ` <span class="tag">DIY</span>` : ''}</td><td>${lvlTag(r.level)}</td>
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
    return x.excluded ? `<span class="tag good">${t('rel_recall_done')}</span>` : x.counted ? `<span class="tag">${t('rel_counted')}</span>` : `<span class="small muted">${t('rel_not_counted')}</span>`; };
  const group = (part, rows) => rows.length ? `<h4 class="small" style="margin:12px 0 4px">${part ? esc(t('part_' + part)) : esc(t('rel_no_part'))}${part ? ` <span class="muted num">${num((d.reliability_parts || {})[part] ?? 0, 1)} ${t('rel_pts')}</span>` : ''}</h4>
    <ul class="check">${rows.sort((a, b) => (det[b.id]?.points || 0) - (det[a.id]?.points || 0)).map(r => `<li><span class="ico pend" aria-hidden="true">i</span><div><b>${esc(r.component)}</b> · ${esc(r.issue ?? '')}<div class="small" style="margin:4px 0">${sevTag(r.severity)} ${lvlTag(r.level)}${r.is_recall ? ` <span class="tag warn">${t('rel_recall')}</span>` : ''} ${state(r)}</div>${r.inspection_action ? `<div class="small muted">→ ${esc(r.inspection_action)}</div>` : ''}</div></li>`).join('')}</ul>` : '';
  const total = (d.metrics || {}).reliability;
  return `<div class="card"><h3>${t('reliability')} ${total == null ? '' : `<span class="muted small num">${t('plate_rel', { n: num(total, 1) })}</span>`}</h3><p class="small muted" style="margin-top:0">${t('rel_lead')}</p>
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

async function draw(id, quiet = false) {
  const label = u => `${unitName(u)} ${u.is_reference ? '(' + t('reference').toLowerCase() + ')' : esc(u.listing_id ?? '')}`;
  const picker = `<div class="field unit-select"><label for="unitsel">${t('units_group')}</label><select id="unitsel" data-unitsel>${S.units.map(u => `<option value="${u.id}" ${u.id === id ? 'selected' : ''}>${label(u)}</option>`).join('')}</select></div>`;
  if (!quiet) root.innerHTML = picker + '<div class="grid"><div class="skel"></div><div class="skel"></div></div>';
  let d; try { d = await get('/api/listings/' + id); } catch (e) { root.innerHTML = picker + `<div class="card err">${t('dossier_failed', { m: esc(e.message) })}</div>`; return; }
  D = d;
  const claim = x => x == null ? PEND() : `${esc(x)} <span class="tag">${t('claimed')}</span>`;
  root.innerHTML = picker + `<div class="dossier-top">${viewer(d)}${plate(d)}</div><div class="grid">${viewingPanel()}
    <div class="card span2"><div class="unit-head"><div><div class="unit-name"><a class="carlink" href="#/models/${d.vehicle_id}">${unitName(d)} ${esc(d.trim ?? '')}</a></div><div class="unit-sub">${unitSub(d)} · ${esc(tv(d.listing_status) ?? '')} <a href="#/models/${d.vehicle_id}" style="margin-left:8px">${t('open_model')}</a></div></div>
      <div class="row">${d.url ? `<a class="btn ghost sm" href="${safeUrl(d.url)}" target="_blank" rel="noopener">${t('open_listing')}</a>` : ''}<button class="btn sm${VIEWING ? '' : ' ghost'}" type="button" data-viewing>${VIEWING ? t('viewing_exit') : '📋 ' + t('viewing_start')}</button></div></div>
      ${d.is_reference ? '' : decisionBar(d)}
      ${gaps(S.todo.listings.find(x => x.listing_id === d.id)?.todo)}
      <div style="margin-top:12px">${facts([[t('asking_price'), d.is_reference ? t('owned') : eP(d.price_eur)], [t('mileage'), d.mileage_km == null ? PEND() : num(d.mileage_km, 0) + ' km'], [t('registration'), d.first_registration ? esc(d.first_registration) : PEND()],
        [t('engine'), `<a href="${modelsHref({ engine: d.engine_code })}">${esc(d.engine_code)}</a> · ${esc(d.engine_description ?? '')}`], [t('generation'), `<a href="${modelsHref({ make: d.make, model: d.model })}">${esc(d.generation)}</a> ${d.generation_start_year ?? '?'}–${d.generation_end_year ?? '?'}`],
        ...(d.is_reference ? [] : [[t('seller'), d.seller ? esc(d.seller) + (d.location ? ', ' + esc(d.location) : '') : PEND()], [t('accident_free'), d.accident_free_claim == null ? PEND() : claim(d.accident_free_claim ? t('yes') : t('no'))], [t('owners'), claim(d.owners_claim)],
        [t('hu'), claim(d.hu_claim)], [t('history'), claim(d.service_history_claim)], [t('equipment'), d.equipment ? esc(d.equipment) : PEND()], [t('verdict'), d.verdict ? `<b>${esc(d.verdict)}</b>` : PEND()]]), [t('notes'), d.notes ? esc(d.notes) : PEND()]])}</div></div>
    ${rankCard(d)}${maintenanceCard(d)}${risksCard(d)}${inspectionCard(d)}
    <div class="card"><h3>${t('valuations')}</h3>${d.valuations.length ? d.valuations.map(valuationRow).join('') : empty(t('no_valuations'))}
      <h3 style="margin-top:16px">${t('own_costs')}</h3>${d.unit_costs.length ? `<div class="tablewrap"><table><thead><tr><th>${t('concept')}</th><th class="n">${t('parts')}</th><th class="n">${t('labour')}</th><th class="n">DIY</th></tr></thead><tbody>${d.unit_costs.map(x => `<tr><td>${esc(x.item)}<div class="small muted">${esc(tv(x.category))} · ${esc(tv(x.status))}</div></td><td class="n">${eP(x.parts_eur)}</td><td class="n">${eP(x.labor_eur)}</td><td class="n">${x.diy_hours == null ? '—' : num(x.diy_hours, 1) + ' h'}</td></tr>`).join('')}</tbody></table></div>` : empty(t('no_own_costs'))}</div>
    ${reliabilityCard(d)}
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
    if (e.target.closest('[data-viewing]')) { VIEWING = !VIEWING; await draw(D.id); return; }
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
  if (!root || !main.contains(root)) { main.innerHTML = '<div data-page="dossier"></div>'; root = main.firstElementChild; bind(); }
  if (id == null) { root.innerHTML = empty(t('no_units')); return; }
  await draw(id);
}
