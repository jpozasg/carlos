// Settings: calculation parameters (with live preview), insurance profile, appearance (theme, light/dark, language),
// account (password, agent token).
import { S, THEMES, applyTheme, loadAll, renderShell } from '../app.js';
import { post, get } from '../api.js';
import * as i18n from '../i18n.js';
import { t } from '../i18n.js';
import { $, esc, num, store, toast } from '../ui.js';

const KEYS = ['annual_km', 'ownership_years', 'fuel_price_eur_l', 'fuel_price_date', 'diesel_price_eur_l', 'diesel_price_date', 'budget_ideal_eur', 'budget_max_eur', 'postal_code', 'drivers_count', 'driver_age', 'sf_class', 'insurance_cover', 'insurance_deductible_eur', 'purchase_mode',
  'home_charging', 'home_charging_pct', 'electricity_home_eur_kwh', 'electricity_home_date', 'electricity_public_eur_kwh', 'electricity_public_date', 'wallbox_cost_eur',
  'acquisition_mode', 'lease_rate_max_eur'];
const CALC = ['annual_km', 'ownership_years', 'fuel_price_eur_l', 'diesel_price_eur_l', 'budget_ideal_eur', 'budget_max_eur', 'electricity_home_eur_kwh', 'electricity_public_eur_kwh', 'home_charging_pct', 'wallbox_cost_eur', 'lease_rate_max_eur'];
const OPTS = { insurance_cover: ['Haftpflicht', 'Teilkasko', 'Vollkasko'], sf_class: ['SF 0', 'SF 1/2', ...Array.from({ length: 35 }, (_, i) => 'SF ' + (i + 1)), 'M', 'S'],
  insurance_deductible_eur: ['0', '150', '300', '500', '1000'], purchase_mode: ['cash', 'financing'], home_charging: ['none', 'socket', 'wallbox', 'wallbox_planned'], acquisition_mode: ['buy', 'lease', 'both'] };
let root, previewTimer;
const val = k => { const e = $(k); return e.type === 'number' ? (e.value === '' ? null : Number(e.value)) : e.value; };
const dirty = () => KEYS.some(k => String(val(k) ?? '').replace(/\.0$/, '') !== String(S.saved[k] ?? '').replace(/\.0$/, ''));
const THEME_SW = { friendly: ['#f5f7fb', '#2f6fed', '#1f2933'], garage: ['#0e0e0e', '#f5d60a', '#f4f4f0'], cluster: ['#0b0d10', '#f5a524', '#f2f3f5'], retro: ['#f3e7cf', '#d35400', '#5f7d2a'],
  olive: ['#efe9d8', '#5c6b2a', '#b08a3a'], terminal: ['#000000', '#9cff9c', '#ffb000'], kawaii: ['#fff0f6', '#ff6fa5', '#5fd6b4'], circuit: ['#0b2b1e', '#b87333', '#e0a24a'], arcade: ['#000000', '#2121de', '#ffe100'], hyrule: ['#ece2c4', '#2e6b2f', '#c9a227'] };

function form() {
  const p = S.saved, f = (k, label, extra = '') => `<div class="field"><label for="${k}">${label}</label>${extra}</div>`;
  const inp = (k, type, attrs = '') => `<input id="${k}" type="${type}" ${attrs} value="${p[k] == null ? '' : esc(String(p[k]).replace(/\.0$/, ''))}">`;
  const sel = k => { const cur = p[k] == null ? '' : String(p[k]).replace(/\.0$/, ''); const vals = [...new Set(['', ...OPTS[k], ...(cur && !OPTS[k].includes(cur) ? [cur] : [])])];
    return `<select id="${k}">${vals.map(v => `<option value="${esc(v)}" ${v === cur ? 'selected' : ''}>${v === '' ? '—' : k === 'purchase_mode' ? t('pm_' + v) : k === 'home_charging' ? t('hc_' + v) : k === 'acquisition_mode' ? t('am_' + v) : k === 'insurance_deductible_eur' ? v + ' €' : esc(v)}</option>`).join('')}</select>`; };
  return `<form id="paramForm" novalidate>
    <fieldset><legend>${t('calc_group')}</legend><p class="small muted" style="margin:0 0 10px">${t('calc_group_hint')}</p><div class="fields">
      ${f('annual_km', t('p_annual_km'), `<div class="pair"><input id="annual_km_range" type="range" min="5000" max="40000" step="1000" value="${p.annual_km}" aria-hidden="true" tabindex="-1">${inp('annual_km', 'number', 'min="1" step="500" inputmode="numeric"')}</div>`)}
      ${f('ownership_years', t('p_ownership_years'), `<div class="pair"><input id="ownership_years_range" type="range" min="1" max="10" step="1" value="${p.ownership_years}" aria-hidden="true" tabindex="-1">${inp('ownership_years', 'number', 'min="1" max="30" step="1" inputmode="numeric"')}</div>`)}
      ${f('fuel_price_eur_l', t('p_fuel_price'), inp('fuel_price_eur_l', 'number', 'step=".01" min="0.01" inputmode="decimal"'))}
      ${f('fuel_price_date', t('p_fuel_date'), `<div class="pair">${inp('fuel_price_date', 'date')}<button class="btn ghost sm" type="button" id="fuelToday">${t('today')}</button></div><div class="small" id="fuelAge"></div>`)}
      ${f('diesel_price_eur_l', t('p_diesel_price'), inp('diesel_price_eur_l', 'number', 'step=".01" min="0.01" inputmode="decimal"'))}
      ${f('diesel_price_date', t('p_diesel_date'), inp('diesel_price_date', 'date'))}
      ${f('budget_ideal_eur', t('p_budget_ideal'), inp('budget_ideal_eur', 'number', 'step="100" min="1" inputmode="numeric"'))}
      ${f('budget_max_eur', t('p_budget_max'), inp('budget_max_eur', 'number', 'step="100" min="1" inputmode="numeric"'))}
    </div><p class="small" id="derived" style="margin:10px 0 0"></p></fieldset>
    <fieldset><legend>${t('insurance_purchase')}</legend><p class="small muted" style="margin:0 0 10px">${t('profile_hint')}</p><div class="fields">
      ${f('insurance_cover', t('p_cover'), sel('insurance_cover'))}${f('sf_class', 'SF-Klasse', sel('sf_class'))}${f('insurance_deductible_eur', t('p_deductible'), sel('insurance_deductible_eur'))}
      ${f('drivers_count', t('p_drivers'), inp('drivers_count', 'number', 'min="1" max="9" readonly'))}${f('driver_age', t('p_age'), inp('driver_age', 'number', 'min="17" max="99" readonly') + `<p class="hint"><a href="#/start?step=3">${t('from_drivers_step')}</a></p>`)}
      ${f('postal_code', t('p_postal'), inp('postal_code', 'text', 'inputmode="numeric" pattern="[0-9]{5}" maxlength="5"'))}${f('purchase_mode', t('p_purchase'), sel('purchase_mode'))}
      ${f('acquisition_mode', t('p_acquisition'), sel('acquisition_mode'))}${f('lease_rate_max_eur', t('p_lease_rate_max'), inp('lease_rate_max_eur', 'number', 'step="10" min="1" inputmode="numeric"'))}
    </div></fieldset>
    <fieldset><legend>${t('step_charging')}</legend><p class="small muted" style="margin:0 0 10px">${t('sl_charging')}</p><div class="fields">
      ${f('home_charging', t('p_home_charging'), sel('home_charging'))}${f('home_charging_pct', t('p_home_pct'), inp('home_charging_pct', 'number', 'min="0" max="100" step="5" inputmode="numeric"'))}
      ${f('electricity_home_eur_kwh', t('p_elec_home'), inp('electricity_home_eur_kwh', 'number', 'step=".01" min="0.01" inputmode="decimal"'))}${f('electricity_home_date', t('p_elec_home_date'), inp('electricity_home_date', 'date'))}
      ${f('electricity_public_eur_kwh', t('p_elec_public'), inp('electricity_public_eur_kwh', 'number', 'step=".01" min="0.01" inputmode="decimal"'))}${f('electricity_public_date', t('p_elec_public_date'), inp('electricity_public_date', 'date'))}
      ${f('wallbox_cost_eur', t('p_wallbox_cost'), inp('wallbox_cost_eur', 'number', 'step="50" min="0" inputmode="numeric"'))}
    </div></fieldset>
    <div class="row"><button class="btn" type="submit" id="saveParams">${t('save_params')}</button><button class="btn ghost" type="button" id="discardParams">${t('discard')}</button><span class="small" id="previewNote" role="status"></span></div></form>`;
}
function paramUi() {
  const km = +$('annual_km').value, y = +$('ownership_years').value, d = $('fuel_price_date').value;
  $('derived').textContent = km > 0 && y > 0 ? t('derived', { km: num(km * y, 0), m: y * 12 }) : '';
  const age = d ? Math.floor((Date.now() - new Date(d + 'T00:00')) / 864e5) : null;
  $('fuelAge').innerHTML = age == null ? '' : age > 30 ? `<span class="tag warn">⚠ ${t('fuel_age', { n: age })}</span>` : `<span class="muted">${t('fuel_age', { n: age })}</span>`;
  const isDirty = dirty(); $('saveParams').disabled = !isDirty; $('discardParams').disabled = !isDirty;
  $('previewNote').innerHTML = S.preview ? `<span class="tag warn">${t('preview_on')}</span>` : '';
}
async function preview() {
  const q = new URLSearchParams(); for (const k of CALC) { const v = $(k).value; if (v !== '') q.set(k, v); }
  const same = CALC.every(k => String(val(k) ?? '') === String(S.saved[k] ?? ''));
  let d;
  try { d = await get('/api/tco' + (same ? '' : '?' + q)); }
  catch (e) { const k = CALC.find(k => e.message.startsWith(k)); if (k) { $(k).setAttribute('aria-invalid', 'true'); if (k === 'budget_ideal_eur') $('budget_max_eur').setAttribute('aria-invalid', 'true'); } else toast(e.message, true); return; }
  CALC.forEach(k => $(k).removeAttribute('aria-invalid'));
  Object.assign(S, { p: d.parameters, units: d.listings, ranking: d.ranking, preview: d.preview, fuelStale: d.fuel_price_stale });
  renderShell(); paramUi();
}
function appearance() {
  const theme = store.get('theme', 'cluster'), mode = store.get('mode', 'auto');
  return `<div class="card"><h3>${t('appearance')}</h3><p class="small muted" style="margin-top:0">${t('appearance_hint')}</p>
    <div class="theme-grid">${THEMES.map(k => `<button type="button" data-theme-pick="${k}" aria-pressed="${k === theme}"><div class="sw-row">${THEME_SW[k].map(c => `<i style="background:${c}"></i>`).join('')}</div><b>${t('theme_' + k)}</b><div class="small muted">${t('theme_' + k + '_hint')}</div></button>`).join('')}</div>
    <div class="row" style="margin-top:12px"><span class="small">${t('mode')}:</span><div class="seg" role="group">${['auto', 'light', 'dark'].map(m => `<button type="button" data-mode-pick="${m}" aria-pressed="${m === mode}">${t('mode_' + m)}</button>`).join('')}</div>
      <span class="small" style="margin-left:12px">${t('language')}:</span><div class="seg" role="group">${Object.keys(i18n.LANGS).map(l => `<button type="button" data-lang="${l}" aria-pressed="${l === i18n.current()}">${l.toUpperCase()}</button>`).join('')}</div></div></div>`;
}
function account() {
  return `<div class="card"><h3>${t('account')} <span class="muted small">${esc(S.me.username)} · ${esc(t('role_' + S.me.role))}</span></h3>
    <form id="pwForm" class="stack"><div class="fields"><div class="field"><label for="pw_old">${t('pw_old')}</label><input id="pw_old" type="password" autocomplete="current-password" required></div>
      <div class="field"><label for="pw_new">${t('pw_new')}</label><input id="pw_new" type="password" autocomplete="new-password" minlength="8" required></div></div>
      <div><button class="btn ghost sm" type="submit">${t('pw_change')}</button></div></form>
    <h3 style="margin-top:16px">${t('agent_token')}</h3><p class="small muted" style="margin-top:0">${t('agent_token_hint')}</p>
    <div class="row"><button class="btn ghost sm" type="button" data-token>${S.me.has_token ? t('token_renew') : t('token_create')}</button></div><div id="tokenOut"></div></div>`;
}
function draw() {
  root.innerHTML = `<div class="section"><h2>${t('tab_settings')}</h2><p class="lead">${t('settings_lead')}</p>
    <div class="callout"><p>${t('setup_again_text')}</p><a class="btn ghost sm" href="#/start">${t('setup_again')}</a></div>
    <div class="grid" style="grid-template-columns:1fr"><div class="card">${form()}</div></div>
    <div class="grid" style="margin-top:16px">${appearance()}${account()}</div></div>`;
  paramUi();
}
function bind() {
  root.addEventListener('input', e => { const id = e.target.id;
    if (id.endsWith('_range')) $(id.replace('_range', '')).value = e.target.value;
    if (id === 'annual_km' || id === 'ownership_years') { $(id + '_range').value = $(id).value; }
    if (!KEYS.includes(id.replace('_range', ''))) return;
    paramUi(); if (CALC.includes(id.replace('_range', ''))) { clearTimeout(previewTimer); previewTimer = setTimeout(preview, 350); } });
  root.addEventListener('click', async e => {
    if (e.target.id === 'fuelToday') { $('fuel_price_date').value = new Date().toISOString().slice(0, 10); paramUi(); return; }
    if (e.target.id === 'discardParams') { await loadAll(); renderShell(); draw(); return; }
    const th = e.target.closest('[data-theme-pick]'); if (th) { applyTheme(th.dataset.themePick, store.get('mode', 'auto')); draw(); return; }
    const md = e.target.closest('[data-mode-pick]'); if (md) { applyTheme(store.get('theme', 'cluster'), md.dataset.modePick); draw(); return; }
    if (e.target.closest('[data-token]')) { try { const r = await post('/api/account/token', {}); $('tokenOut').innerHTML = `<p class="small">${t('token_shown_once')}</p><div class="token-box">${esc(r.token)}</div>`; S.me.has_token = true; } catch (err) { toast(err.message, true); } } });
  root.addEventListener('submit', async e => {
    e.preventDefault();
    if (e.target.id === 'pwForm') { try { await post('/api/account/password', { old: $('pw_old').value, new: $('pw_new').value }); toast(t('pw_changed')); e.target.reset(); } catch (err) { toast(err.message, true); } return; }
    const body = {}; KEYS.forEach(k => { $(k).removeAttribute('aria-invalid'); body[k] = k === 'insurance_deductible_eur' ? ($(k).value === '' ? null : Number($(k).value)) : val(k); });
    try { await post('/api/parameters', body); toast(t('saved')); await loadAll(); renderShell(); draw(); }
    catch (err) { const k = KEYS.find(k => (err.message || '').startsWith(k)); if (k) { $(k).setAttribute('aria-invalid', 'true'); $(k).focus(); } toast(t('not_saved', { m: err.message }), true); } });
}
export async function render(main) {
  if (!root || !main.contains(root)) { main.innerHTML = '<div data-page="settings"></div>'; root = main.firstElementChild; bind(); }
  draw();
}
