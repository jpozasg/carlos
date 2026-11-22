// Setup wizard (#/start, issue #13): everything Carlos needs from the account holder, one topic per step, prefilled from
// what is stored. Saves through the same API as Settings: project_parameters for the calculation and the search origin,
// project_preferences for search, workshop and charging. Insurance is not asked here: quotes are entered per listing.
import { S, go, loadAll, renderShell, current } from '../app.js';
import { get, post } from '../api.js';
import { t } from '../i18n.js';
import { $, esc, num, euro, busy, unit } from '../ui.js';
import { quiz, profileHtml } from '../quiz.js';

// Choice preferences store plain English (agents read them as text); the UI shows a translated label per code.
const CHOICE = {
  driving_mix: { town: 'Mostly town', mixed: 'Mixed', motorway: 'Mostly motorway' },
  preferred_fuel: { any: 'Any', petrol: 'Petrol', diesel: 'Diesel', hybrid: 'Hybrid', phev: 'Plug-in hybrid', electric: 'Electric' },
  preferred_transmission: { any: 'Any', manual: 'Manual', automatic: 'Automatic' },
};
const PARAM_CHOICE = { purchase_mode: ['cash', 'financing'], home_charging: ['none', 'socket', 'wallbox', 'wallbox_planned'] };  // home_charging: electric cars (#121); leasing was removed: second-hand purchases only (#165)
const DIY = { oil: 'oil and filters', plugs: 'spark plugs', service: 'yearly service', brakes: 'brake pads and discs', battery: 'battery',
  bulbs: 'bulbs', wipers: 'wipers', coolant: 'coolant', timing: 'timing belt or chain', clutch: 'clutch' };
const DIY_DEFAULT = ['oil', 'plugs', 'service', 'brakes', 'battery', 'bulbs', 'wipers'];  // docs/cost-research-protocol.md
const STEPS = ['drive', 'money', 'search', 'workshop', 'charging', 'priorities', 'done'];  // the index is in the URL (#/start?step=n)
const OPTIONAL = ['workshop', 'charging'];  // a car ranks without them; the answers they give sharpen the costs

let root, step = 0, prefs = {}, finishing = false;
const P = k => S.saved?.[k] == null ? '' : String(S.saved[k]).replace(/\.0$/, '');
const field = (id, label, control, hint = '') => `<div class="field"><label for="${id}">${label}</label>${control}${hint ? `<p class="hint">${hint}</p>` : ''}</div>`;
// one inputmode per field: numeric for whole numbers, decimal where the value can have a fraction (prices per litre or kWh)
const number = (id, value, attrs = '', mode = 'numeric') => `<input id="${id}" type="number" inputmode="${mode}" value="${esc(value)}" ${attrs}>`;
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
      ${field('fuel_price_eur_l', t('p_fuel_price'), number('fuel_price_eur_l', P('fuel_price_eur_l'), 'step=".01" min="0.01"', 'decimal'))}
      ${field('diesel_price_eur_l', t('p_diesel_price'), number('diesel_price_eur_l', P('diesel_price_eur_l'), 'step=".01" min="0.01"', 'decimal'))}</div>
    <p class="hint">${t('h_fuel')}</p>`,
  search: () => `<div class="fields two">
      ${field('postal_code', t('p_postal'), text('postal_code', P('postal_code'), 'inputmode="numeric" pattern="[0-9]{5}" maxlength="5" autocomplete="postal-code"'), t('h_postal'))}
      ${field('search_center', t('p_search_center'), text('search_center', prefs.search_center ?? '', 'maxlength="100" autocomplete="address-level2"'), t('h_search_center'))}
      ${field('search_radius', t('p_search_radius'), `<select id="search_radius">${['', '25', '50', '100', '200', '300', 'Any'].map(v => `<option value="${v}" ${String(prefs.search_radius ?? '') === v ? 'selected' : ''}>${v === '' ? '—' : v === 'Any' ? t('o_any_distance') : unit(+v, 'km')}</option>`).join('')}${prefs.search_radius && !['25', '50', '100', '200', '300', 'Any'].includes(prefs.search_radius) ? `<option selected value="${esc(prefs.search_radius)}">${esc(prefs.search_radius)}</option>` : ''}</select>`)}</div>
    ${prefChoice('preferred_fuel', t('p_pref_fuel'))}${prefChoice('preferred_transmission', t('p_pref_gearbox'))}
    ${prefs.preferred_engine ? `<p class="hint">${t('kept_note', { v: esc(prefs.preferred_engine) })}</p>` : ''}`,
  workshop: () => { const have = prefs.diy_jobs != null ? prefs.diy_jobs.split(',').map(s => s.trim()) : DIY_DEFAULT.map(k => DIY[k]);
    return `<div class="role-group" role="group" aria-labelledby="diy-l"><span class="label" id="diy-l">${t('p_diy')}</span>
      <div class="chips">${Object.entries(DIY).map(([k, v]) => `<label class="chk"><input type="checkbox" value="${esc(v)}" data-diy ${have.includes(v) ? 'checked' : ''}><span>${t('diy_' + k)}</span></label>`).join('')}</div></div>
      <p class="hint">${t('h_diy')}</p>${prefs.diy_skills ? `<p class="hint">${t('kept_note', { v: esc(prefs.diy_skills) })}</p>` : ''}`; },
  // electric cars (#121): only what the energy cost needs; all optional, a car without electricity never asks for it
  charging: () => `${group('home_charging', t('p_home_charging'), choice('home_charging', PARAM_CHOICE.home_charging.map(v => [v, v]), P('home_charging'), c => 'hc_' + c))}
    <div class="fields two">
      ${field('home_charging_pct', t('p_home_pct'), `<div class="pair"><input id="home_charging_pct_range" type="range" min="0" max="100" step="5" value="${P('home_charging_pct') || 80}" aria-hidden="true" tabindex="-1">${number('home_charging_pct', P('home_charging_pct'), 'min="0" max="100" step="5"')}</div>`, t('h_home_pct'))}
      ${field('wallbox_cost_eur', t('p_wallbox_cost'), number('wallbox_cost_eur', P('wallbox_cost_eur'), 'min="0" step="50"'), t('h_wallbox_cost'))}
      ${field('electricity_home_eur_kwh', t('p_elec_home'), number('electricity_home_eur_kwh', P('electricity_home_eur_kwh'), 'step=".01" min="0.01"', 'decimal'), t('h_elec_home'))}
      ${field('electricity_public_eur_kwh', t('p_elec_public'), number('electricity_public_eur_kwh', P('electricity_public_eur_kwh'), 'step=".01" min="0.01"', 'decimal'), t('h_elec_public'))}</div>`,
};

function collect(name) {
  const params = {}, pr = {};
  const num_ = id => { const v = val(id); return v === '' || v == null ? null : Number(v); };
  if (name === 'drive') { params.annual_km = num_('annual_km'); params.ownership_years = num_('ownership_years'); pr.driving_mix = radio('driving_mix'); pr.current_car = val('current_car'); }
  if (name === 'money') { const today = new Date().toISOString().slice(0, 10);
    Object.assign(params, { budget_ideal_eur: num_('budget_ideal_eur'), budget_max_eur: num_('budget_max_eur'), purchase_mode: radio('purchase_mode'), fuel_price_eur_l: num_('fuel_price_eur_l'), diesel_price_eur_l: num_('diesel_price_eur_l') });
    if (String(params.fuel_price_eur_l) !== P('fuel_price_eur_l')) params.fuel_price_date = today;
    if (params.diesel_price_eur_l != null && String(params.diesel_price_eur_l) !== P('diesel_price_eur_l')) params.diesel_price_date = today; }
  if (name === 'search') { Object.assign(pr, { search_center: val('search_center'), search_radius: val('search_radius'), preferred_fuel: radio('preferred_fuel'), preferred_transmission: radio('preferred_transmission') });
    params.postal_code = val('postal_code'); }  // the origin of the distance (costs.py)
  if (name === 'charging') { const today = new Date().toISOString().slice(0, 10);
    Object.assign(params, { home_charging: radio('home_charging'), home_charging_pct: radio('home_charging') === 'none' ? 0 : num_('home_charging_pct'), wallbox_cost_eur: num_('wallbox_cost_eur'),
      electricity_home_eur_kwh: num_('electricity_home_eur_kwh'), electricity_public_eur_kwh: num_('electricity_public_eur_kwh') });
    for (const k of ['electricity_home', 'electricity_public']) if (params[k + '_eur_kwh'] != null && String(params[k + '_eur_kwh']) !== P(k + '_eur_kwh')) params[k + '_date'] = today; }
  if (name === 'workshop') pr.diy_jobs = [...root.querySelectorAll('[data-diy]:checked')].map(e => e.value).join(', ') || 'none';
  // a radio left empty keeps what is stored (it may be free text an agent wrote); empty text fields clear
  for (const k of Object.keys(pr)) if (pr[k] === null && CHOICE[k]) delete pr[k];
  for (const k of Object.keys(params)) if (params[k] === null && PARAM_CHOICE[k]) delete params[k];
  return { params, prefs: pr };
}
// a failure stays on this page as text next to the form (#stepErr), never a toast that vanishes after 3.5 s
const fail = msg => { const el = $('stepErr'); if (el) el.textContent = msg; };
// a request-sending control that is busy while `work` runs; an error is shown inline
const run = (btn, work) => busy(btn, async () => { try { await work(); } catch (e) { fail(t('not_saved', { m: e.message })); } });
async function saveStep(name) {
  const { params, prefs: pr } = collect(name);
  root.querySelectorAll('[aria-invalid]').forEach(e => { e.removeAttribute('aria-invalid'); e.removeAttribute('aria-describedby'); });
  try {
    if (Object.keys(params).length) S.saved = S.p = await post('/api/parameters', params);
    if (Object.keys(pr).length) prefs = Object.fromEntries((await post('/api/preferences', pr)).map(r => [r.preference_key, r.preference_value]));
    return true;
  } catch (e) {
    const k = Object.keys(params).find(k => (e.message || '').startsWith(k));
    if (k && $(k)) { $(k).setAttribute('aria-invalid', 'true'); $(k).setAttribute('aria-describedby', 'stepErr'); $(k).focus(); if (k === 'budget_ideal_eur') $('budget_max_eur')?.setAttribute('aria-invalid', 'true'); }
    fail(t('not_saved', { m: e.message })); return false;
  }
}

function rail() {
  return `<ol class="rail" aria-label="${esc(t('setup_steps'))}">${STEPS.map((s, i) => `<li ${i === step ? 'aria-current="step"' : ''} class="${i < step ? 'done' : ''}"><button type="button" data-goto="${i}" ${i > step && !prefs.onboarding_done ? 'disabled' : ''}><span class="n num">${i + 1}</span><span class="l">${t('step_' + s)}${OPTIONAL.includes(s) ? ` <small class="muted">${t('optional_step')}</small>` : ''}</span></button></li>`).join('')}</ol>`;
}
const shown = k => { const v = prefs[k]; if (v == null) return null;  // stored English value → label in the UI language
  const code = CHOICE[k] && Object.keys(CHOICE[k]).find(c => CHOICE[k][c] === v); return code ? t(`o_${k}_${code}`) : v; };
const diyShown = () => prefs.diy_jobs == null ? null : prefs.diy_jobs.split(',').map(s => s.trim()).map(v => { const k = Object.keys(DIY).find(k => DIY[k] === v); return k ? t('diy_' + k) : v; }).join(', ');
function summary() {
  const p = S.saved, yes = v => v == null || v === '' ? `<span class="pending">${t('pending')}</span>` : esc(v);
  const rows = [[t('step_drive'), [[t('p_annual_km'), p.annual_km && unit(p.annual_km, 'km')], [t('p_ownership_years'), p.ownership_years], [t('p_driving_mix'), shown('driving_mix')], [t('p_current_car'), prefs.current_car]]],
    [t('step_money'), [[t('p_budget_ideal'), p.budget_ideal_eur && euro(p.budget_ideal_eur)], [t('p_budget_max'), p.budget_max_eur && euro(p.budget_max_eur)], [t('p_purchase'), p.purchase_mode && t('pm_' + p.purchase_mode)]]],
    [t('step_search'), [[t('p_search_center'), prefs.search_center], [t('p_search_radius'), /^\d+$/.test(prefs.search_radius ?? '') ? unit(+prefs.search_radius, 'km') : prefs.search_radius === 'Any' ? t('o_any_distance') : prefs.search_radius], [t('p_pref_fuel'), shown('preferred_fuel')], [t('p_pref_gearbox'), shown('preferred_transmission')], [t('p_postal'), p.postal_code]]],
    [t('step_workshop'), [[t('p_diy'), diyShown()]]],
    [t('step_charging'), [[t('p_home_charging'), p.home_charging && t('hc_' + p.home_charging)], [t('p_home_pct'), p.home_charging_pct != null ? unit(p.home_charging_pct, 'pct') : null],
      [t('p_elec_home'), p.electricity_home_eur_kwh && num(p.electricity_home_eur_kwh, 2) + '\u00a0' + t('unit_eur_kwh')], [t('p_elec_public'), p.electricity_public_eur_kwh && num(p.electricity_public_eur_kwh, 2) + '\u00a0' + t('unit_eur_kwh')]]]];
  return `<div class="sum">${rows.map(([h, kv]) => `<section><h3>${h}</h3><dl class="facts">${kv.map(([k, v]) => `<dt>${k}</dt><dd>${yes(v)}</dd>`).join('')}</dl></section>`).join('')}</div>`;
}
function draw() {
  const name = STEPS[step];
  const body = name === 'priorities' ? '<div id="qzHost"></div>'
    : name === 'done' ? `<p class="lead">${t('done_lead')}</p>${summary()}<h3 class="mt22">${t('prio_title')}</h3>${S.ranking.answered ? profileHtml(S.ranking) : `<p class="empty">${t('prio_skipped')}</p>`}`
    : VIEWS[name]();
  root.innerHTML = `<div class="setup">${rail()}
    <section class="setup-step" aria-labelledby="stepTitle"><h2 id="stepTitle" tabindex="-1">${t('st_' + name)}</h2>${OPTIONAL.includes(name) ? `<p class="tag">${t('optional_step')}</p>` : ''}${name === 'done' ? '' : `<p class="lead">${t('sl_' + name)}</p>`}${name === 'priorities' ? `<p class="small"><button class="linkbtn" type="button" data-skip>${t('quiz_later')}</button></p>` : ''}
      <form id="stepForm" novalidate>${body}<p class="hint err" id="stepErr" role="alert"></p>
      ${name === 'priorities' ? '' : name === 'done' ? `<div class="setup-nav"><button class="btn ghost" type="button" data-back>${t('back')}</button><span class="spacer"></span><a class="btn ghost" href="#/ranking">${t('open_ranking')}</a><a class="btn" href="#/compare">${t('open_compare')}</a></div>`
        : `<div class="setup-nav">${step ? `<button class="btn ghost" type="button" data-back>${t('back')}</button>` : `<button class="linkbtn" type="button" data-later>${t('setup_later')}</button>`}${OPTIONAL.includes(name) ? `<button class="linkbtn" type="button" data-skip-step>${t('skip_step')}</button><span class="small muted">${t('skip_keeps')}</span>` : ''}<span class="spacer"></span><button class="btn" type="submit">${t('save_next')}</button></div>`}</form></section></div>`;
  // the last answer finishes the page; a second press while that request runs (Enter, double click) is ignored
  if (name === 'priorities') quiz(root.querySelector('#qzHost'), { tasks: S.ranking.tasks, answers: S.ranking.answers, params: S.saved, doneLabel: t('quiz_finish_setup'),
    onDone: answers => { if (finishing) return; finishing = true;
      run(root.querySelector('[data-qz-next]'), async () => { await post('/api/parameters', { ranking_answers: answers, ranking_weights: null }); await finish(); }).finally(() => finishing = false); } });
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
    if (/annual_km|ownership_years/.test(id) && $('derived')) derived(); });
  root.addEventListener('submit', async e => { e.preventDefault(); fail('');
    const btn = e.submitter || root.querySelector('#stepForm [type="submit"]');
    if (await busy(btn, () => saveStep(STEPS[step]))) move(step + 1); });
  root.addEventListener('click', async e => {
    if (e.target.closest('[data-back]')) move(step - 1);
    else if (e.target.closest('[data-skip-step]')) move(step + 1);  // nothing is posted: answers already saved stay as they are
    else if (e.target.closest('[data-goto]')) { const to = +e.target.closest('[data-goto]').dataset.goto; if (to < step || prefs.onboarding_done) move(to); }
    else if (e.target.closest('[data-skip]')) await run(e.target.closest('[data-skip]'), finish);
    else if (e.target.closest('[data-later]')) await run(e.target.closest('[data-later]'), async () => { await post('/api/preferences', { onboarding_done: 'skipped' }); S.prefs = { ...S.prefs, onboarding_done: 'skipped' }; go('compare'); });
  });
}
export async function render(main, r = current()) {
  prefs = Object.fromEntries((await get('/api/preferences')).map(x => [x.preference_key, x.preference_value]));
  if (!root || !main.contains(root)) { main.innerHTML = '<div data-page="start"></div>'; root = main.firstElementChild; bind(); }
  step = Math.min(Math.max(+(r.q.step || 0), 0), STEPS.length - 1);
  draw();
}
