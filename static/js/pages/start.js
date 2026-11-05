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
  insurance_parking: { street: 'Street', carport: 'Carport', garage: 'Garage', private: 'Private ground' },
  insurance_usage: { private: 'Private (including commuting)', business: 'Business only', both: 'Private and business' },  // as CHECK24 asks
  insurance_main_user: { holder: 'Policyholder', driver2: 'Driver 2', other: 'Someone else' },
  insurance_keeper: { holder: 'Policyholder', driver2: 'Driver 2', other: 'Someone else' },
  insurance_cancelled: { no: 'No', yes: 'Yes' },
  insurance_seasonal_plate: { no: 'No', yes: 'Yes' },
  insurance_workshop_binding: { either: 'Either', yes: 'Yes', no: 'No' },
};
// People on the policy (CHECK24 "Versicherungsnehmer" and "Fahrer"): codes stored as they are; docs/data-model.md
const PERSON = { gender: ['female', 'male', 'diverse'], licence_country: ['germany', 'eu', 'other'],
  marital: ['single', 'married', 'partnership', 'divorced', 'widowed'],
  occupation: ['employee', 'worker', 'public_service', 'civil_servant', 'self_employed', 'student', 'trainee', 'retired', 'homemaker', 'not_working'],
  relationship: ['partner', 'child', 'other'], yesno: ['yes', 'no'] };
const DISCOUNTS = ['homeowner', 'children', 'transit_pass', 'bahncard', 'club', 'liability', 'household', 'legal', 'accident', 'other_policy'];
const PARAM_CHOICE = { purchase_mode: ['cash', 'financing'], insurance_cover: ['Haftpflicht', 'Teilkasko', 'Vollkasko'] };
const DIY = { oil: 'oil and filters', plugs: 'spark plugs', service: 'yearly service', brakes: 'brake pads and discs', battery: 'battery',
  bulbs: 'bulbs', wipers: 'wipers', coolant: 'coolant', timing: 'timing belt or chain', clutch: 'clutch' };
const DIY_DEFAULT = ['oil', 'plugs', 'service', 'brakes', 'battery', 'bulbs', 'wipers'];  // docs/cost-research-protocol.md
const SF = ['SF 0', 'SF 1/2', ...Array.from({ length: 35 }, (_, i) => 'SF ' + (i + 1)), 'M', 'S'];
const STEPS = ['drive', 'money', 'search', 'drivers', 'insurance', 'workshop', 'priorities', 'done'];

let root, step = 0, prefs = {}, drivers = [];
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
const sel = (id, opts, cur, lbl) => `<select id="${id}"><option value="">—</option>${opts.map(o => `<option value="${o}" ${o === cur ? 'selected' : ''}>${esc(t(lbl(o)))}</option>`).join('')}</select>`;
const codeChoice = (id, opts, cur, lbl) => choice(id, opts.map(o => [o, o]), cur, lbl);
function personFields(px, d, holder, first = '') {  // px: id prefix; d: stored values; first: an extra leading field
  return `<div class="fields two">${first}
    ${group(px + 'gender', t('p_gender'), codeChoice(px + 'gender', PERSON.gender, d.gender, c => 'o_gender_' + c))}
    ${field(px + 'birth_date', t('p_birth_date'), `<input id="${px}birth_date" type="date" value="${esc(d.birth_date ?? '')}" max="${new Date().toISOString().slice(0, 10)}">`)}
    ${field(px + 'licence_date', t('p_licence_date'), `<input id="${px}licence_date" type="date" value="${esc(d.licence_date ?? '')}">`, holder ? t('h_licence_date') : '')}
    ${field(px + 'occupation', t('p_occupation'), sel(px + 'occupation', PERSON.occupation, d.occupation, c => 'o_occ_' + c), t('h_occupation'))}
    ${field(px + 'marital', t('p_marital'), sel(px + 'marital', PERSON.marital, d.marital, c => 'o_marital_' + c))}
    ${holder ? group(px + 'licence_country', t('p_licence_country'), codeChoice(px + 'licence_country', PERSON.licence_country, d.licence_country, c => 'o_lc_' + c)) : ''}
    ${group(px + 'bf17', t('p_bf17'), codeChoice(px + 'bf17', PERSON.yesno, d.bf17, c => 'o_' + c))}
    ${field(px + 'points', t('p_points'), number(px + 'points', d.points ?? '', 'min="0" max="20"'), t('h_points'))}
    ${group(px + 'other_car', t('p_other_car'), codeChoice(px + 'other_car', PERSON.yesno, d.other_car, c => 'o_' + c), t('h_other_car'))}</div>`;
}
const HOLDER_KEYS = ['gender', 'birth_date', 'licence_date', 'occupation', 'marital', 'licence_country', 'bf17', 'points', 'other_car'];
const holderStored = () => Object.fromEntries(HOLDER_KEYS.map(k => [k, prefs['insurance_holder_' + k] ?? '']));
function readPerson(px, keys) {
  return Object.fromEntries(keys.map(k => [k, (root.querySelector(`input[name="${px}${k}"]:checked`)?.value ?? $(px + k)?.value ?? '').trim()]));
}
const DRIVER_KEYS = ['relationship', 'household', ...HOLDER_KEYS.filter(k => k !== 'licence_country')];
function readDrivers() { return [...root.querySelectorAll('[data-driver]')].map(el => readPerson('d' + el.dataset.driver + '_', DRIVER_KEYS)); }
const ageOn = (birth, today = new Date()) => { const b = new Date(birth + 'T00:00'); if (isNaN(b)) return null;
  return today.getFullYear() - b.getFullYear() - (today < new Date(today.getFullYear(), b.getMonth(), b.getDate()) ? 1 : 0); };
function driverCards() {
  return drivers.map((d, i) => `<fieldset class="person" data-driver="${i}"><legend>${t('driver_n', { n: i + 2 })}</legend>
    <div class="fields two">${group(`d${i}_relationship`, t('p_relationship'), codeChoice(`d${i}_relationship`, PERSON.relationship, d.relationship, c => 'o_rel_' + c))}
      ${group(`d${i}_household`, t('p_household'), codeChoice(`d${i}_household`, PERSON.yesno, d.household, c => 'o_' + c))}</div>
    ${personFields(`d${i}_`, d, false)}<button class="btn ghost sm" type="button" data-rm-driver="${i}">${t('driver_remove')}</button></fieldset>`).join('');
}
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
  drivers: () => `<p class="note">${t('ins_privacy')}</p>
    <fieldset class="person"><legend>${t('holder_title')}</legend>
      ${personFields('h_', holderStored(), true, field('postal_code', t('p_postal'), text('postal_code', P('postal_code'), 'inputmode="numeric" pattern="[0-9]{5}" maxlength="5" autocomplete="postal-code"'), t('h_postal')))}</fieldset>
    <div id="driverList">${driverCards()}</div>
    <div class="row"><button class="btn ghost" type="button" data-add-driver>${t('driver_add')}</button><span class="hint" style="margin:0">${t('h_drivers')}</span></div>
    <div class="fields two">${prefChoice('insurance_main_user', t('p_main_user'))}${prefChoice('insurance_keeper', t('p_keeper'), t('h_keeper'))}</div>`,
  insurance: () => { const disc = (prefs.insurance_discounts ?? [prefs.insurance_homeowner === 'Yes' ? 'homeowner' : '', prefs.insurance_club_member === 'Yes' ? 'club' : ''].filter(Boolean).join(',')).split(',').map(x => x.trim());
    return `<div class="fields two">
      ${field('sf_class', t('p_sf'), `<select id="sf_class">${['', ...SF, ...(P('sf_class') && !SF.includes(P('sf_class')) ? [P('sf_class')] : [])].map(v => `<option value="${esc(v)}" ${v === P('sf_class') ? 'selected' : ''}>${v || '—'}</option>`).join('')}</select>`, t('h_sf'))}
      ${field('insurance_start_date', t('p_ins_start'), `<input id="insurance_start_date" type="date" value="${esc(prefs.insurance_start_date ?? '')}">`, t('h_ins_start'))}</div>
    ${group('insurance_cover', t('p_cover'), choice('insurance_cover', PARAM_CHOICE.insurance_cover.map(v => [v, v]), P('insurance_cover'), c => 'cover_' + c), t('h_cover'))}
    <div class="fields two">
      ${field('insurance_deductible_eur', t('p_deductible'), `<select id="insurance_deductible_eur">${['', '0', '150', '300', '500', '1000'].map(v => `<option value="${v}" ${v === P('insurance_deductible_eur') ? 'selected' : ''}>${v === '' ? '—' : v + ' €'}</option>`).join('')}</select>`)}
      ${prefChoice('insurance_workshop_binding', t('p_workshop_binding'), t('h_workshop_binding'))}</div>
    ${prefChoice('insurance_claims_3y', t('p_claims'))}
    <div class="fields two">
      ${field('insurance_previous_insurer', t('p_prev_insurer'), text('insurance_previous_insurer', prefs.insurance_previous_insurer ?? '', 'maxlength="80"'), t('h_prev_insurer'))}
      ${field('insurance_previous_years', t('p_prev_years'), number('insurance_previous_years', prefs.insurance_previous_years ?? '', 'min="0" max="80"'))}</div>
    ${prefChoice('insurance_cancelled', t('p_cancelled'))}
    ${prefChoice('insurance_usage', t('p_usage'))}${prefChoice('insurance_parking', t('p_parking'))}${prefChoice('insurance_seasonal_plate', t('p_seasonal'))}
    <div class="role-group" role="group" aria-labelledby="disc-l"><span class="label" id="disc-l">${t('p_discounts')}</span>
      <div class="chips">${DISCOUNTS.map(k => `<label class="chk"><input type="checkbox" value="${k}" data-disc ${disc.includes(k) ? 'checked' : ''}><span>${t('disc_' + k)}</span></label>`).join('')}</div></div>
    <div class="fields two">
      ${field('insurance_club_name', t('p_club_name'), text('insurance_club_name', prefs.insurance_club_name ?? '', 'maxlength="60" placeholder="ADAC"'))}
      ${field('insurance_liability_insurer', t('p_liability_insurer'), text('insurance_liability_insurer', prefs.insurance_liability_insurer ?? '', 'maxlength="60"'))}
      ${field('current_premium_eur_year', t('p_premium_now'), number('current_premium_eur_year', prefs.current_premium_eur_year ?? '', 'min="0" step="1"'), t('h_premium_now'))}</div>`; },
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
  if (name === 'drivers') {
    const h = readPerson('h_', HOLDER_KEYS), ds = readDrivers();
    for (const k of HOLDER_KEYS) pr['insurance_holder_' + k] = h[k];
    for (const k of ['insurance_main_user', 'insurance_keeper']) pr[k] = radio(k);
    pr.insurance_drivers = ds.length ? JSON.stringify(ds) : null;
    params.postal_code = val('postal_code');
    // the calculation's "drivers" and "youngest driver's age" follow from the people entered
    params.drivers_count = 1 + ds.length;
    const ages = [h, ...ds].map(p => p.birth_date && ageOn(p.birth_date)).filter(a => a != null && a >= 16);
    if (ages.length) params.driver_age = Math.min(...ages);
  }
  if (name === 'insurance') {
    Object.assign(params, { sf_class: val('sf_class'), insurance_cover: radio('insurance_cover'), insurance_deductible_eur: num_('insurance_deductible_eur') });
    for (const k of ['insurance_start_date', 'insurance_previous_insurer', 'insurance_previous_years', 'insurance_club_name', 'insurance_liability_insurer', 'current_premium_eur_year']) pr[k] = val(k);
    for (const k of ['insurance_claims_3y', 'insurance_cancelled', 'insurance_usage', 'insurance_parking', 'insurance_seasonal_plate', 'insurance_workshop_binding']) pr[k] = radio(k);
    pr.insurance_discounts = [...root.querySelectorAll('[data-disc]:checked')].map(e => e.value).join(', ') || 'none';
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
  return `<ol class="rail" aria-label="${esc(t('setup_steps'))}">${STEPS.map((s, i) => `<li ${i === step ? 'aria-current="step"' : ''} class="${i < step ? 'done' : ''}"><button type="button" data-goto="${i}" ${i > step && !prefs.onboarding_done ? 'disabled' : ''}><span class="n num">${i + 1}</span><span class="l">${t('step_' + s)}</span></button></li>`).join('')}</ol>`;
}
const shown = k => { const v = prefs[k]; if (v == null) return null;  // stored English value → label in the UI language
  const code = CHOICE[k] && Object.keys(CHOICE[k]).find(c => CHOICE[k][c] === v); return code ? t(`o_${k}_${code}`) : v; };
const diyShown = () => prefs.diy_jobs == null ? null : prefs.diy_jobs.split(',').map(s => s.trim()).map(v => { const k = Object.keys(DIY).find(k => DIY[k] === v); return k ? t('diy_' + k) : v; }).join(', ');
function summary() {
  const p = S.saved, yes = v => v == null || v === '' ? `<span class="pending">${t('pending')}</span>` : esc(v);
  const rows = [[t('step_drive'), [[t('p_annual_km'), p.annual_km && num(p.annual_km, 0) + ' km'], [t('p_ownership_years'), p.ownership_years], [t('p_driving_mix'), shown('driving_mix')], [t('p_current_car'), prefs.current_car]]],
    [t('step_money'), [[t('p_budget_ideal'), p.budget_ideal_eur && euro(p.budget_ideal_eur)], [t('p_budget_max'), p.budget_max_eur && euro(p.budget_max_eur)], [t('p_purchase'), p.purchase_mode && t('pm_' + p.purchase_mode)]]],
    [t('step_search'), [[t('p_search_center'), prefs.search_center], [t('p_search_radius'), /^\d+$/.test(prefs.search_radius ?? '') ? prefs.search_radius + ' km' : prefs.search_radius === 'Any' ? t('o_any_distance') : prefs.search_radius], [t('p_pref_fuel'), shown('preferred_fuel')], [t('p_pref_gearbox'), shown('preferred_transmission')]]],
    [t('step_drivers'), [[t('p_postal'), p.postal_code], [t('holder_title'), [prefs.insurance_holder_gender && t('o_gender_' + prefs.insurance_holder_gender), prefs.insurance_holder_birth_date && ageOn(prefs.insurance_holder_birth_date) + ' ' + t('years_old'), prefs.insurance_holder_occupation && t('o_occ_' + prefs.insurance_holder_occupation)].filter(Boolean).join(', ')], [t('p_drivers'), p.drivers_count], [t('p_age'), p.driver_age]]],
    [t('step_insurance'), [[t('p_sf'), p.sf_class], [t('p_cover'), p.insurance_cover && t('cover_' + p.insurance_cover)], [t('p_deductible'), p.insurance_deductible_eur != null ? euro(p.insurance_deductible_eur) : null], [t('p_claims'), shown('insurance_claims_3y')], [t('p_usage'), shown('insurance_usage')], [t('p_parking'), shown('insurance_parking')], [t('p_discounts'), prefs.insurance_discounts && prefs.insurance_discounts !== 'none' ? prefs.insurance_discounts.split(',').map(x => t('disc_' + x.trim())).join(', ') : prefs.insurance_discounts && t('none_word')]]],
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
  if (name === 'priorities') quiz(root.querySelector('#qzHost'), { tasks: S.ranking.tasks, answers: S.ranking.answers, params: S.saved, doneLabel: t('quiz_finish_setup'),
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
    else if (e.target.closest('[data-goto]')) { const to = +e.target.closest('[data-goto]').dataset.goto; if (to < step || prefs.onboarding_done) move(to); }
    else if (e.target.closest('[data-skip]')) await finish();
    else if (e.target.closest('[data-add-driver]')) { drivers = [...readDrivers(), {}]; $('driverList').innerHTML = driverCards(); $('driverList').lastElementChild?.querySelector('input')?.focus(); }
    else if (e.target.closest('[data-rm-driver]')) { const i = +e.target.closest('[data-rm-driver]').dataset.rmDriver; drivers = readDrivers().filter((_, j) => j !== i); $('driverList').innerHTML = driverCards(); }
    else if (e.target.closest('[data-later]')) { await post('/api/preferences', { onboarding_done: 'skipped' }); S.prefs = { ...S.prefs, onboarding_done: 'skipped' }; go('compare'); }
  });
}
export async function render(main, r = current()) {
  prefs = Object.fromEntries((await get('/api/preferences')).map(x => [x.preference_key, x.preference_value]));
  try { drivers = JSON.parse(prefs.insurance_drivers || '[]'); } catch (e) { drivers = []; }
  if (!root || !main.contains(root)) { main.innerHTML = '<div data-page="start"></div>'; root = main.firstElementChild; bind(); }
  step = Math.min(Math.max(+(r.q.step || 0), 0), STEPS.length - 1);
  draw();
}
