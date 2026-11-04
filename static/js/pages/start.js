// Setup wizard (#/start, issue #13): everything Carlos and the research agents need from the account holder, one topic
// per step, prefilled from what is stored. Saves through the same API as Settings: project_parameters for the
// calculation and the insurance profile, project_preferences for search, workshop and the extra insurance answers.
import { S, go, loadAll, renderShell, current } from '../app.js';
import { get, post } from '../api.js';
import { t } from '../i18n.js';
import { $, esc, num, euro, toast } from '../ui.js';
import { quiz, profileHtml } from '../quiz.js';

// Choice preferences store plain English (agents read them as text); the UI shows a translated label per code.
const CHOICE = {
  driving_mix: { town: 'Mostly town', mixed: 'Mixed', motorway: 'Mostly motorway' },
  preferred_fuel: { any: 'Any', petrol: 'Petrol', diesel: 'Diesel', hybrid: 'Hybrid', electric: 'Electric' },
  preferred_transmission: { any: 'Any', manual: 'Manual', automatic: 'Automatic' },
  insurance_claims_3y: { none: '0', one: '1', more: '2 or more' },
  insurance_parking: { street: 'Street', carport: 'Carport', garage: 'Garage' },
  insurance_club_member: { yes: 'Yes', no: 'No' },
  insurance_homeowner: { yes: 'Yes', no: 'No' },
};
const PARAM_CHOICE = { purchase_mode: ['cash', 'financing'], insurance_cover: ['Haftpflicht', 'Teilkasko', 'Vollkasko'] };
const DIY = { oil: 'oil and filters', plugs: 'spark plugs', service: 'yearly service', brakes: 'brake pads and discs', battery: 'battery',
  bulbs: 'bulbs', wipers: 'wipers', coolant: 'coolant', timing: 'timing belt or chain', clutch: 'clutch' };
const DIY_DEFAULT = ['oil', 'plugs', 'service', 'brakes', 'battery', 'bulbs', 'wipers'];  // docs/cost-research-protocol.md
const SF = ['SF 0', 'SF 1/2', ...Array.from({ length: 35 }, (_, i) => 'SF ' + (i + 1)), 'M', 'S'];
const STEPS = ['drive', 'money', 'search', 'insurance', 'workshop', 'priorities', 'done'];

let root, step = 0, prefs = {};
const P = k => S.saved?.[k] == null ? '' : String(S.saved[k]).replace(/\.0$/, '');
const field = (id, label, control, hint = '') => `<div class="field"><label for="${id}">${label}</label>${control}${hint ? `<p class="hint">${hint}</p>` : ''}</div>`;
const number = (id, value, attrs = '') => `<input id="${id}" type="number" inputmode="numeric" value="${esc(value)}" ${attrs}>`;
const text = (id, value, attrs = '') => `<input id="${id}" type="text" value="${esc(value)}" ${attrs}>`;
function choice(id, opts, current, labelKey) {  // segmented radio group; opts = [[code, stored value]]
  return `<div class="choice" role="radiogroup" aria-labelledby="${id}-l">${opts.map(([code, v]) => `<label><input type="radio" name="${id}" value="${esc(v)}" ${current === v ? 'checked' : ''}><span>${esc(t(labelKey(code)))}</span></label>`).join('')}</div>`;
}
const group = (id, label, control, hint = '') => `<div class="field" role="group" aria-labelledby="${id}-l"><span class="label" id="${id}-l">${label}</span>${control}${hint ? `<p class="hint">${hint}</p>` : ''}</div>`;
const prefChoice = (k, label, hint) => {
  const cur = prefs[k] ?? '', known = Object.values(CHOICE[k]).includes(cur);
  return group(k, label, choice(k, Object.entries(CHOICE[k]), cur, c => `o_${k}_${c}`) + (cur && !known ? `<p class="hint">${t('kept_note', { v: esc(cur) })}</p>` : ''), hint);
};
const radio = id => root.querySelector(`input[name="${id}"]:checked`)?.value ?? null;
const val = id => { const e = $(id); return e ? e.value.trim() : null; };

const VIEWS = {
  drive: () => `<div class="fields two">
      ${field('annual_km', t('p_annual_km'), `<div class="pair"><input id="annual_km_range" type="range" min="3000" max="40000" step="1000" value="${P('annual_km') || 15000}" aria-hidden="true" tabindex="-1">${number('annual_km', P('annual_km'), 'min="1" step="500"')}</div>`, t('h_annual_km'))}
      ${field('ownership_years', t('p_ownership_years'), `<div class="pair"><input id="ownership_years_range" type="range" min="1" max="12" step="1" value="${P('ownership_years') || 4}" aria-hidden="true" tabindex="-1">${number('ownership_years', P('ownership_years'), 'min="1" max="30"')}</div>`, t('h_ownership_years'))}</div>
    <p class="derived small" id="derived"></p>
    ${prefChoice('driving_mix', t('p_driving_mix'), t('h_driving_mix'))}
    ${field('current_car', t('p_current_car'), text('current_car', prefs.current_car ?? '', `placeholder="${esc(t('ph_current_car'))}" maxlength="200"`), t('h_current_car'))}`,
  money: () => `<div class="fields two">
      ${field('budget_ideal_eur', t('p_budget_ideal'), number('budget_ideal_eur', P('budget_ideal_eur'), 'min="1" step="100"'), t('h_budget_ideal'))}
      ${field('budget_max_eur', t('p_budget_max'), number('budget_max_eur', P('budget_max_eur'), 'min="1" step="100"'), t('h_budget_max'))}</div>
    ${group('purchase_mode', t('p_purchase'), choice('purchase_mode', PARAM_CHOICE.purchase_mode.map(v => [v, v]), P('purchase_mode'), c => 'pm_' + c))}
    <div class="fields two">
      ${field('fuel_price_eur_l', t('p_fuel_price'), number('fuel_price_eur_l', P('fuel_price_eur_l'), 'step=".01" min="0.01" inputmode="decimal"'))}
      ${field('diesel_price_eur_l', t('p_diesel_price'), number('diesel_price_eur_l', P('diesel_price_eur_l'), 'step=".01" min="0.01" inputmode="decimal"'))}</div>
    <p class="hint">${t('h_fuel')}</p>`,
  search: () => `<div class="fields two">
      ${field('search_center', t('p_search_center'), text('search_center', prefs.search_center ?? '', 'maxlength="100" autocomplete="address-level2"'), t('h_search_center'))}
      ${field('search_radius', t('p_search_radius'), `<select id="search_radius">${['', '25', '50', '100', '200', '300', 'Any'].map(v => `<option value="${v}" ${String(prefs.search_radius ?? '') === v ? 'selected' : ''}>${v === '' ? '—' : v === 'Any' ? t('o_any_distance') : v + ' km'}</option>`).join('')}${prefs.search_radius && !['25', '50', '100', '200', '300', 'Any'].includes(prefs.search_radius) ? `<option selected value="${esc(prefs.search_radius)}">${esc(prefs.search_radius)}</option>` : ''}</select>`)}</div>
    ${prefChoice('preferred_fuel', t('p_pref_fuel'))}${prefChoice('preferred_transmission', t('p_pref_gearbox'))}
    ${prefs.preferred_engine ? `<p class="hint">${t('kept_note', { v: esc(prefs.preferred_engine) })}</p>` : ''}`,
  insurance: () => `<p class="note">${t('ins_privacy')}</p>
    <div class="fields two">
      ${field('postal_code', t('p_postal'), text('postal_code', P('postal_code'), 'inputmode="numeric" pattern="[0-9]{5}" maxlength="5" autocomplete="postal-code"'), t('h_postal'))}
      ${field('driver_age', t('p_age'), number('driver_age', P('driver_age'), 'min="17" max="99"'), t('h_age'))}
      ${field('insurance_licence_years', t('p_licence_years'), number('insurance_licence_years', prefs.insurance_licence_years ?? '', 'min="0" max="80"'))}
      ${field('drivers_count', t('p_drivers'), number('drivers_count', P('drivers_count'), 'min="1" max="9"'))}
      ${field('sf_class', t('p_sf'), `<select id="sf_class">${['', ...SF, ...(P('sf_class') && !SF.includes(P('sf_class')) ? [P('sf_class')] : [])].map(v => `<option value="${esc(v)}" ${v === P('sf_class') ? 'selected' : ''}>${v || '—'}</option>`).join('')}</select>`, t('h_sf'))}</div>
    ${group('insurance_cover', t('p_cover'), choice('insurance_cover', PARAM_CHOICE.insurance_cover.map(v => [v, v]), P('insurance_cover'), c => 'cover_' + c), t('h_cover'))}
    <div class="fields two">
      ${field('insurance_deductible_eur', t('p_deductible'), `<select id="insurance_deductible_eur">${['', '0', '150', '300', '500', '1000'].map(v => `<option value="${v}" ${v === P('insurance_deductible_eur') ? 'selected' : ''}>${v === '' ? '—' : v + ' €'}</option>`).join('')}</select>`)}
      ${field('current_premium_eur_year', t('p_premium_now'), number('current_premium_eur_year', prefs.current_premium_eur_year ?? '', 'min="0" step="1"'), t('h_premium_now'))}</div>
    ${prefChoice('insurance_claims_3y', t('p_claims'))}${prefChoice('insurance_parking', t('p_parking'))}
    <div class="fields two">${prefChoice('insurance_club_member', t('p_club'))}${prefChoice('insurance_homeowner', t('p_homeowner'))}</div>`,
  workshop: () => { const have = prefs.diy_jobs != null ? prefs.diy_jobs.split(',').map(s => s.trim()) : DIY_DEFAULT.map(k => DIY[k]);
    return `<div class="role-group" role="group" aria-labelledby="diy-l"><span class="label" id="diy-l">${t('p_diy')}</span>
      <div class="chips">${Object.entries(DIY).map(([k, v]) => `<label class="chk"><input type="checkbox" value="${esc(v)}" data-diy ${have.includes(v) ? 'checked' : ''}><span>${t('diy_' + k)}</span></label>`).join('')}</div></div>
      <p class="hint">${t('h_diy')}</p>${prefs.diy_skills ? `<p class="hint">${t('kept_note', { v: esc(prefs.diy_skills) })}</p>` : ''}`; },
};

function collect(name) {
  const params = {}, pr = {};
  const num_ = id => { const v = val(id); return v === '' || v == null ? null : Number(v); };
  if (name === 'drive') { params.annual_km = num_('annual_km'); params.ownership_years = num_('ownership_years'); pr.driving_mix = radio('driving_mix'); pr.current_car = val('current_car'); }
  if (name === 'money') { const today = new Date().toISOString().slice(0, 10);
    Object.assign(params, { budget_ideal_eur: num_('budget_ideal_eur'), budget_max_eur: num_('budget_max_eur'), purchase_mode: radio('purchase_mode'), fuel_price_eur_l: num_('fuel_price_eur_l'), diesel_price_eur_l: num_('diesel_price_eur_l') });
    if (String(params.fuel_price_eur_l) !== P('fuel_price_eur_l')) params.fuel_price_date = today;
    if (params.diesel_price_eur_l != null && String(params.diesel_price_eur_l) !== P('diesel_price_eur_l')) params.diesel_price_date = today; }
  if (name === 'search') Object.assign(pr, { search_center: val('search_center'), search_radius: val('search_radius'), preferred_fuel: radio('preferred_fuel'), preferred_transmission: radio('preferred_transmission') });
  if (name === 'insurance') {
    Object.assign(params, { postal_code: val('postal_code'), driver_age: num_('driver_age'), drivers_count: num_('drivers_count'), sf_class: val('sf_class'), insurance_cover: radio('insurance_cover'), insurance_deductible_eur: num_('insurance_deductible_eur') });
    for (const k of ['insurance_licence_years', 'current_premium_eur_year']) pr[k] = val(k);
    for (const k of ['insurance_claims_3y', 'insurance_parking', 'insurance_club_member', 'insurance_homeowner']) pr[k] = radio(k);
  }
  if (name === 'workshop') pr.diy_jobs = [...root.querySelectorAll('[data-diy]:checked')].map(e => e.value).join(', ') || 'none';
  // a radio left empty keeps what is stored (it may be free text an agent wrote); empty text fields clear
  for (const k of Object.keys(pr)) if (pr[k] === null && CHOICE[k]) delete pr[k];
  for (const k of Object.keys(params)) if (params[k] === null && PARAM_CHOICE[k]) delete params[k];
  return { params, prefs: pr };
}
async function saveStep(name) {
  const { params, prefs: pr } = collect(name);
  root.querySelectorAll('[aria-invalid]').forEach(e => e.removeAttribute('aria-invalid'));
  try {
    if (Object.keys(params).length) S.saved = S.p = await post('/api/parameters', params);
    if (Object.keys(pr).length) prefs = Object.fromEntries((await post('/api/preferences', pr)).map(r => [r.preference_key, r.preference_value]));
    return true;
  } catch (e) {
    const k = Object.keys(params).find(k => (e.message || '').startsWith(k));
    if (k && $(k)) { $(k).setAttribute('aria-invalid', 'true'); $(k).focus(); if (k === 'budget_ideal_eur') $('budget_max_eur')?.setAttribute('aria-invalid', 'true'); }
    toast(t('not_saved', { m: e.message }), true); return false;
  }
}

function rail() {
  return `<ol class="rail" aria-label="${esc(t('setup_steps'))}">${STEPS.map((s, i) => `<li ${i === step ? 'aria-current="step"' : ''} class="${i < step ? 'done' : ''}"><button type="button" data-goto="${i}" ${i > step ? 'disabled' : ''}><span class="n num">${i + 1}</span><span class="l">${t('step_' + s)}</span></button></li>`).join('')}</ol>`;
}
const shown = k => { const v = prefs[k]; if (v == null) return null;  // stored English value → label in the UI language
  const code = CHOICE[k] && Object.keys(CHOICE[k]).find(c => CHOICE[k][c] === v); return code ? t(`o_${k}_${code}`) : v; };
const diyShown = () => prefs.diy_jobs == null ? null : prefs.diy_jobs.split(',').map(s => s.trim()).map(v => { const k = Object.keys(DIY).find(k => DIY[k] === v); return k ? t('diy_' + k) : v; }).join(', ');
function summary() {
  const p = S.saved, yes = v => v == null || v === '' ? `<span class="pending">${t('pending')}</span>` : esc(v);
  const rows = [[t('step_drive'), [[t('p_annual_km'), p.annual_km && num(p.annual_km, 0) + ' km'], [t('p_ownership_years'), p.ownership_years], [t('p_driving_mix'), shown('driving_mix')], [t('p_current_car'), prefs.current_car]]],
    [t('step_money'), [[t('p_budget_ideal'), p.budget_ideal_eur && euro(p.budget_ideal_eur)], [t('p_budget_max'), p.budget_max_eur && euro(p.budget_max_eur)], [t('p_purchase'), p.purchase_mode && t('pm_' + p.purchase_mode)]]],
    [t('step_search'), [[t('p_search_center'), prefs.search_center], [t('p_search_radius'), /^\d+$/.test(prefs.search_radius ?? '') ? prefs.search_radius + ' km' : prefs.search_radius === 'Any' ? t('o_any_distance') : prefs.search_radius], [t('p_pref_fuel'), shown('preferred_fuel')], [t('p_pref_gearbox'), shown('preferred_transmission')]]],
    [t('step_insurance'), [[t('p_postal'), p.postal_code], [t('p_age'), p.driver_age], [t('p_drivers'), p.drivers_count], [t('p_sf'), p.sf_class], [t('p_cover'), p.insurance_cover && t('cover_' + p.insurance_cover)], [t('p_deductible'), p.insurance_deductible_eur != null ? euro(p.insurance_deductible_eur) : null], [t('p_claims'), shown('insurance_claims_3y')], [t('p_parking'), shown('insurance_parking')]]],
    [t('step_workshop'), [[t('p_diy'), diyShown()]]]];
  return `<div class="sum">${rows.map(([h, kv]) => `<section><h3>${h}</h3><dl class="facts">${kv.map(([k, v]) => `<dt>${k}</dt><dd>${yes(v)}</dd>`).join('')}</dl></section>`).join('')}</div>`;
}
function draw() {
  const name = STEPS[step];
  const body = name === 'priorities' ? '<div id="qzHost"></div>'
    : name === 'done' ? `<p class="lead">${t('done_lead')}</p>${summary()}<h3 style="margin-top:22px">${t('prio_title')}</h3>${S.ranking.answered ? profileHtml(S.ranking) : `<p class="empty">${t('prio_skipped')}</p>`}`
    : VIEWS[name]();
  root.innerHTML = `<div class="setup">${rail()}
    <section class="setup-step" aria-labelledby="stepTitle"><h2 id="stepTitle" tabindex="-1">${t('st_' + name)}</h2>${name === 'done' ? '' : `<p class="lead">${t('sl_' + name)}</p>`}${name === 'priorities' ? `<p class="small"><button class="linkbtn" type="button" data-skip>${t('quiz_later')}</button></p>` : ''}
      <form id="stepForm" novalidate>${body}
      ${name === 'priorities' ? '' : name === 'done' ? `<div class="setup-nav"><button class="btn ghost" type="button" data-back>${t('back')}</button><span class="spacer"></span><a class="btn ghost" href="#/ranking">${t('open_ranking')}</a><a class="btn" href="#/compare">${t('open_compare')}</a></div>`
        : `<div class="setup-nav">${step ? `<button class="btn ghost" type="button" data-back>${t('back')}</button>` : `<button class="linkbtn" type="button" data-later>${t('setup_later')}</button>`}<span class="spacer"></span><button class="btn" type="submit">${t('save_next')}</button></div>`}</form></section></div>`;
  if (name === 'priorities') quiz(root.querySelector('#qzHost'), { questions: S.ranking.questions, answers: S.ranking.answers, doneLabel: t('quiz_finish_setup'),
    onDone: async answers => { try { await post('/api/parameters', { ranking_answers: answers, ranking_weights: null }); await finish(); } catch (e) { toast(t('not_saved', { m: e.message }), true); } } });
  if (name === 'drive') derived();
  if (name === 'done' && !prefs.onboarding_done) post('/api/preferences', { onboarding_done: new Date().toISOString().slice(0, 10) }).then(r => { prefs.onboarding_done = 1; S.prefs = Object.fromEntries(r.map(x => [x.preference_key, x.preference_value])); });
}
function derived() { const km = +val('annual_km'), y = +val('ownership_years'); $('derived').textContent = km > 0 && y > 0 ? t('derived', { km: num(km * y, 0), m: y * 12 }) : ''; }
async function finish() { await loadAll(); renderShell(); step = STEPS.length - 1; history.replaceState(null, '', '#/start?step=' + step); draw(); $('stepTitle').focus(); }
function move(to) { step = to; history.replaceState(null, '', '#/start?step=' + to); draw(); scrollTo({ top: 0 }); $('stepTitle').focus({ preventScroll: true }); }

function bind() {
  root.addEventListener('input', e => { const id = e.target.id;
    if (id.endsWith('_range')) $(id.replace('_range', '')).value = e.target.value;
    else if ($(id + '_range')) $(id + '_range').value = e.target.value;
    if (/annual_km|ownership_years/.test(id)) derived(); });
  root.addEventListener('submit', async e => { e.preventDefault(); if (await saveStep(STEPS[step])) move(step + 1); });
  root.addEventListener('click', async e => {
    if (e.target.closest('[data-back]')) move(step - 1);
    else if (e.target.closest('[data-goto]')) { const to = +e.target.closest('[data-goto]').dataset.goto; if (to < step) move(to); }
    else if (e.target.closest('[data-skip]')) await finish();
    else if (e.target.closest('[data-later]')) { await post('/api/preferences', { onboarding_done: 'skipped' }); S.prefs = { ...S.prefs, onboarding_done: 'skipped' }; go('compare'); }
  });
}
export async function render(main, r = current()) {
  prefs = Object.fromEntries((await get('/api/preferences')).map(x => [x.preference_key, x.preference_value]));
  if (!root || !main.contains(root)) { main.innerHTML = '<div data-page="start"></div>'; root = main.firstElementChild; bind(); }
  step = Math.min(Math.max(+(r.q.step || 0), 0), STEPS.length - 1);
  draw();
}
