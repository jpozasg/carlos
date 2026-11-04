// Models browser: make → model → generation → engine → variant, with filters and the listings of each variant;
// variant detail with every inherited row and its level.
import { S, go } from '../app.js';
import { get } from '../api.js';
import { t, tv } from '../i18n.js';
import { esc, num, PEND, eP, euro, empty, facts, gaps, lvlTag, qTag, sevTag, intervalTxt, safeUrl, store } from '../ui.js';

let root, filters = store.get('mfilters', { make: '', model: '', engine: '', transmission: '', fuel: '' });
const vlist = tree => tree.makes.flatMap(mk => mk.models.flatMap(md => md.generations.flatMap(g => g.engines.flatMap(e => e.variants.map(v => ({ v, mk, md, g, e }))))));
function filterTree(tree) {
  const f = filters;
  return { makes: tree.makes.filter(mk => !f.make || mk.make === f.make).map(mk => ({ ...mk, models: mk.models.filter(md => !f.model || md.model === f.model).map(md => ({ ...md,
    generations: md.generations.map(g => ({ ...g, engines: g.engines.filter(e => (!f.engine || e.code === f.engine) && (!f.fuel || e.fuel_type === f.fuel)).map(e => ({ ...e,
      variants: e.variants.filter(v => !f.transmission || v.transmission === f.transmission) })).filter(e => e.variants.length) })).filter(g => g.engines.length) })).filter(md => md.generations.length) })).filter(mk => mk.models.length) };
}
function listTree(tree) {
  const all = vlist(S.models), opts = (key, fn) => [...new Set(all.map(fn).filter(Boolean))].sort().map(v => `<option value="${esc(v)}" ${filters[key] === v ? 'selected' : ''}>${esc(v)}</option>`).join('');
  const sel = (key, label, fn) => `<div class="field"><label for="f-${key}">${label}</label><select class="inline" id="f-${key}" data-mf="${key}"><option value="">${t('all')}</option>${opts(key, fn)}</select></div>`;
  const ft = filterTree(tree), n = vlist(ft).length;
  const body = ft.makes.map(mk => mk.models.map(md => md.generations.map(g => `<section class="gen"><div class="gen-head"><b>${esc(mk.make)} ${esc(md.model)} · ${esc(g.name)}</b><span class="small muted">${g.start_year ?? '?'}–${g.end_year ?? '?'}${g.facelift_year ? ' · ' + t('facelift') + ' ' + g.facelift_year : ''} · <span class="tag">${esc(tv(g.status) ?? '—')}</span></span></div>
    ${g.engines.map(e => `<div class="engine"><div class="ehead"><b>${esc(e.code)}</b><span class="muted">${esc(e.description ?? '')}</span><span class="tag">${esc(tv(e.fuel_type) ?? '')}</span>${e.power_ps ? `<span class="tag">${num(e.power_ps, 0)} PS</span>` : ''}${e.aspiration ? `<span class="tag">${esc(tv(e.aspiration))}</span>` : ''}${e.injection ? `<span class="tag">${esc(tv(e.injection))}</span>` : ''}${e.timing_drive ? `<span class="tag">${esc(tv(e.timing_drive))}</span>` : ''}</div>
      <ul class="variants">${e.variants.map(v => `<li><a href="#/models/${v.id}">${esc(v.trim ?? t('variant'))}</a><span class="muted">${esc(v.transmission ?? '')}${v.hsn ? ' · ' + esc(v.hsn) + '/' + esc(v.tsn ?? '?') : ''}</span>
        ${v.listings.map(l => `<a class="tag ${l.is_reference ? 'ref' : ''}" href="#/listing/${l.id}" style="text-decoration:none">${l.is_reference ? t('reference') : esc(l.listing_id ?? '#' + l.id)}${l.price_eur ? ' ' + euro(l.price_eur) : ''}</a>`).join('')}
        ${v.listings.length ? '' : `<span class="small muted">${t('no_listings')}</span>`}${gapsShort(v.id)}</li>`).join('')}</ul></div>`).join('')}</section>`).join('')).join('')).join('');
  root.innerHTML = `<div class="section"><h2>${t('models_title')}</h2><p class="lead">${t('models_lead')}</p>
    <div class="filters">${sel('make', t('make'), x => x.mk.make)}${sel('model', t('model'), x => x.md.model)}${sel('engine', t('engine'), x => x.e.code)}${sel('fuel', t('fuel_type'), x => x.e.fuel_type)}${sel('transmission', t('gearbox'), x => x.v.transmission)}</div>
    <p class="small muted">${t('variants_n', { n })} · <span class="lvl-variant"><i class="dot"></i> ${t('level_variant')}</span> <span class="lvl-engine"><i class="dot"></i> ${t('level_engine')}</span> <span class="lvl-generation"><i class="dot"></i> ${t('level_generation')}</span> · ${t('levels_hint')}</p>
    <div class="tree">${body || empty(t('no_match'))}</div></div>`;
}
const gapsShort = vid => { const n = (S.todo.models.find(m => m.vehicle_id === vid)?.todo || []).length; return n ? `<span class="tag warn" title="${t('gaps', { n })}">${n}</span>` : ''; };
function rowsTable(title, rows, cols) {
  return `<div class="card span2"><h3>${title} <span class="muted small">${rows.length}</span></h3>${rows.length ? `<div class="tablewrap"><table><thead><tr>${cols.map(c => `<th>${c[0]}</th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr>${cols.map(c => `<td>${c[1](r)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : empty(t('no_rows'))}</div>`;
}
async function variant(id) {
  root.innerHTML = '<div class="skel"></div>';
  let v; try { v = await get('/api/vehicles/' + id); } catch (e) { root.innerHTML = `<div class="card err">${esc(e.message)}</div>`; return; }
  const src = sid => { const s = v.sources.find(x => x.id === sid); return s ? qTag(s.quality, s.title) : ''; };
  const lvl = r => lvlTag(r.level);
  root.innerHTML = `<p class="small"><a href="#/models">${t('models_title')}</a></p><div class="section"><h2>${esc(v.make)} ${esc(v.model)} ${esc(v.trim ?? '')}</h2><p class="lead">${esc(v.generation)} · ${esc(v.engine_code)} · ${esc(v.transmission ?? '')}</p>
    <div class="grid">
      <div class="card"><h3>${t('variant')} ${lvlTag('variant')}</h3>${facts([[t('gearbox'), v.transmission ? esc(v.transmission) : PEND()], [t('body'), v.body_style ? esc(v.body_style) : PEND()], ['HSN/TSN', v.hsn ? `${esc(v.hsn)} / ${esc(v.tsn ?? '?')}` : PEND()], [t('emissions'), v.emissions_standard ? esc(v.emissions_standard) : PEND()], ['CO₂', v.co2_g_km ? num(v.co2_g_km, 0) + ' g/km' : PEND()], [t('status'), `<span class="tag">${esc(tv(v.technical_status) ?? '—')}</span>`], [t('notes'), v.vehicle_notes ? esc(v.vehicle_notes) : '—']])}${gaps(S.todo.models.find(m => m.vehicle_id === v.id)?.todo)}
        <p class="small" style="margin:10px 0 0"><b>${t('listings')}:</b> ${v.listings.map(l => `<a href="#/listing/${l.id}">${l.is_reference ? t('reference') : esc(l.listing_id ?? '#' + l.id)}</a>`).join(', ') || t('no_listings')}</p></div>
      <div class="card"><h3>${t('engine')} ${lvlTag('engine')}</h3>${facts([[t('code'), esc(v.engine_row.code)], [t('description'), esc(v.engine_row.description ?? '') || PEND()], [t('fuel_type'), v.engine_row.fuel_type ? esc(tv(v.engine_row.fuel_type)) : PEND()], [t('displacement'), v.engine_row.displacement_cc ? num(v.engine_row.displacement_cc, 0) + ' cm³' : PEND()], [t('power'), v.engine_row.power_ps ? num(v.engine_row.power_ps, 0) + ' PS' : PEND()], [t('aspiration'), v.engine_row.aspiration ? esc(tv(v.engine_row.aspiration)) : PEND()], [t('injection'), v.engine_row.injection ? esc(tv(v.engine_row.injection)) : PEND()], [t('timing_drive'), v.engine_row.timing_drive ? esc(tv(v.engine_row.timing_drive)) : PEND()], [t('notes'), v.engine_row.notes ? esc(v.engine_row.notes) : '—']])}
        <p class="small muted" style="margin:10px 0 0">${t('same_engine')}: ${v.siblings.same_engine.map(i => `<a href="#/models/${i}">#${i}</a>`).join(', ') || '—'}</p></div>
      <div class="card"><h3>${t('generation')} ${lvlTag('generation')}</h3>${facts([[t('make'), esc(v.make)], [t('model'), esc(v.model)], [t('generation'), esc(v.generation)], [t('years'), `${v.generation_start_year ?? '?'}–${v.generation_end_year ?? '?'}`], [t('facelift'), v.facelift_year ?? PEND()], [t('status'), `<span class="tag">${esc(tv(v.generation_status) ?? '—')}</span>`], [t('notes'), v.generation_row.notes ? esc(v.generation_row.notes) : '—']])}
        <p class="small muted" style="margin:10px 0 0">${t('same_generation')}: ${v.siblings.same_generation.map(i => `<a href="#/models/${i}">#${i}</a>`).join(', ') || '—'}</p></div>
      ${rowsTable(t('mp_title'), v.maintenance_items.filter(m => m.active), [[t('mp_job'), r => esc(r.item)], [t('level'), lvl], [t('mp_interval'), r => intervalTxt(r.interval_km, r.interval_months)], [t('mp_who'), r => r.diy ? t('mp_diy') : t('mp_ws')], [t('mp_price'), r => eP(r.diy ? r.diy_parts_cost_eur : r.reference_cost_eur)], [t('status'), r => esc(tv(r.status) ?? '')], [t('mp_src'), r => src(r.source_id)]])}
      ${rowsTable(t('rk_title'), v.repair_risks, [[t('rk_comp'), r => esc(r.component)], [t('level'), lvl], [t('rk_window'), r => `${num(r.km_from, 0)}–${num(r.km_to, 0)}`], [t('rk_prob'), r => num(r.probability * 100, 0) + ' %'], [t('parts'), r => eP(r.parts_eur)], [t('labour'), r => eP(r.labor_eur)], [t('mp_src'), r => src(r.source_id)]])}
      ${rowsTable(t('reliability'), v.reliability_items, [[t('rk_comp'), r => `<b>${esc(r.component)}</b> ${esc(r.issue ?? '')}`], [t('level'), lvl], [t('severity'), r => sevTag(r.severity)], [t('inspection_action'), r => esc(r.inspection_action ?? '')], [t('mp_src'), r => src(r.source_id)]])}
      ${rowsTable(t('consumption'), v.observations, [[t('metric'), r => esc(r.metric)], [t('level'), lvl], [t('value'), r => `${r.value_num ?? esc(r.value_text ?? '')} ${esc(r.unit ?? '')}`], ['n / min / max', r => `${r.sample_count ?? '—'} / ${r.min_value ?? '—'} / ${r.max_value ?? '—'}`], [t('status'), r => esc(tv(r.status) ?? '')], [t('mp_src'), r => src(r.source_id)]])}
      ${rowsTable(t('insurance_year'), v.insurance_data, [['HSN/TSN', r => `${esc(r.hsn ?? '')}/${esc(r.tsn ?? '')}`], [t('level'), lvl], [t('premium'), r => eP(r.annual_premium_eur)], [t('status'), r => esc(tv(r.premium_status) ?? '')], [t('date'), r => esc(r.quote_date ?? '')], [t('mp_src'), r => src(r.source_id)]])}
      ${rowsTable(t('tax_year'), v.tax_data, [[t('amount'), r => eP(r.annual_tax_eur)], [t('level'), lvl], [t('basis'), r => esc(r.basis ?? '')], [t('status'), r => esc(tv(r.status) ?? '')], [t('mp_src'), r => src(r.source_id)]])}
      ${rowsTable(t('tyres'), v.tyre_data, [[t('size'), r => esc(r.size ?? '')], [t('level'), lvl], [t('price_per_tyre'), r => eP(r.price_per_tyre_eur)], [t('life_km'), r => r.life_km ? num(r.life_km, 0) + ' km' : PEND()], [t('status'), r => esc(tv(r.status) ?? '')], [t('mp_src'), r => src(r.source_id)]])}
      ${rowsTable(t('tab_sources'), v.sources, [[t('quality'), r => qTag(r.quality)], [t('level'), r => lvlTag(r.vehicle_id ? 'variant' : r.engine_id ? 'engine' : r.generation_id ? 'generation' : 'shared')], [t('title'), r => `${esc(r.title)}${r.url ? ` <a href="${safeUrl(r.url)}" target="_blank" rel="noopener">↗</a>` : ''}`], [t('supports'), r => esc(r.supports ?? '')]])}
    </div></div>`;
}
export async function render(main, r) {
  if (!root || !main.contains(root)) { main.innerHTML = '<div data-page="models"></div>'; root = main.firstElementChild;
    root.addEventListener('change', e => { const k = e.target.dataset.mf; if (!k) return; filters[k] = e.target.value; store.set('mfilters', filters); listTree(S.models); }); }
  if (r.id) { await variant(r.id); return; }
  if (!S.models) { root.innerHTML = '<div class="skel"></div>'; S.models = await get('/api/models'); }
  listTree(S.models);
}
