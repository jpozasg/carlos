// Carlos front end: shell, router, shared state. Pages live in ./pages/*.js; every theme runs this same code.
import { get, post } from './api.js';
import * as i18n from './i18n.js';
import { t } from './i18n.js';
import { $, esc, num, store, toast, yrs } from './ui.js';

export const S = { me: null, p: null, saved: null, preview: false, units: [], components: [], ranking: null, budget: null,
  fuelStale: null, storage: null, todo: { listings: [], models: [] }, sources: [], models: null };
export const THEMES = ['friendly', 'garage', 'cluster', 'retro', 'olive', 'terminal', 'kawaii', 'circuit', 'arcade'];
const PAGES = {
  compare: () => import('./pages/compare.js'), ranking: () => import('./pages/ranking.js'), listing: () => import('./pages/dossier.js'),
  models: () => import('./pages/models.js'), sources: () => import('./pages/sources.js'), settings: () => import('./pages/settings.js'),
  admin: () => import('./pages/admin.js') };
const NAV = ['compare', 'ranking', 'models', 'sources', 'settings'];

export function applyTheme(theme = store.get('theme', 'friendly'), mode = store.get('mode', 'auto')) {
  if (!THEMES.includes(theme)) theme = 'friendly';
  const root = document.documentElement;
  root.dataset.theme = theme;
  if (mode === 'auto') root.removeAttribute('data-mode'); else root.dataset.mode = mode;
  root.classList.toggle('os-dark', matchMedia('(prefers-color-scheme: dark)').matches);
  store.set('theme', theme); store.set('mode', mode);
  document.querySelector('meta[name=theme-color]')?.setAttribute('content', getComputedStyle(root).getPropertyValue('--bg').trim() || '#fff');
}
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => applyTheme());

export async function setLang(l) { await i18n.load(l); renderShell(); route(); }

export async function loadAll() {
  const [me, p, tco, st, td, ss] = await Promise.all([get('/api/auth/me'), get('/api/parameters'), get('/api/tco'), get('/api/storage'), get('/api/todo'), get('/api/sources')]);
  Object.assign(S, { me, p, saved: p, preview: false, units: tco.listings, components: tco.components, ranking: tco.ranking, budget: tco.budget,
    fuelStale: tco.fuel_price_stale, storage: st, todo: td, sources: ss, models: null });
}
export async function refreshTco(query = '') {
  const d = await get('/api/tco' + query);
  Object.assign(S, { p: d.parameters, units: d.listings, ranking: d.ranking, budget: d.budget, fuelStale: d.fuel_price_stale, preview: d.preview });
  return d;
}

export function renderShell() {
  document.title = t('app_title');
  const p = S.p, st = S.storage;
  const chips = p ? `<a class="chip${S.fuelStale || S.preview ? ' warn' : ''}" href="#/settings" title="${esc(S.fuelStale ? t('fuel_stale') : t('edit_params'))}">${S.preview ? '✎ ' : S.fuelStale ? '⚠ ' : ''}${num(p.annual_km, 0)} ${t('per_year_short')} · ${yrs(p.ownership_years)} · ${num(p.fuel_price_eur_l, 2)} €/l</a>
    <span class="chip${st && st.total_bytes / st.limit_bytes >= .9 ? ' bad' : st && st.total_bytes / st.limit_bytes >= .8 ? ' warn' : ''}" title="${esc(t('storage_hint'))}">${st ? `${num(st.total_bytes / 1048576, 1)} / ${num(st.limit_bytes / 1048576, 0)} MB` : ''}</span>` : '';
  const langs = `<div class="seg" role="group" aria-label="${esc(t('language'))}">${Object.keys(i18n.LANGS).map(l => `<button type="button" data-lang="${l}" lang="${l}" aria-pressed="${l === i18n.current()}">${l.toUpperCase()}</button>`).join('')}</div>`;
  $('hdr').innerHTML = `<div class="bar"><a class="brand" href="#/compare" aria-label="${esc(t('app_title'))}"><svg viewBox="0 0 64 64" aria-hidden="true"><use href="/static/brand/mark.svg#mark"/></svg><span><b>Carlos</b><small>${esc(t('tagline'))}</small></span></a>${chips}${langs}
    ${S.me ? `<a class="chip" href="#/settings" title="${esc(t('account'))}">👤 ${esc(S.me.username)}</a><button class="chip" type="button" data-logout>${t('logout')}</button>` : ''}</div>
    <nav class="main" aria-label="${esc(t('sections'))}">${[...NAV, ...(S.me?.role === 'admin' ? ['admin'] : [])].map(k => `<a href="#/${k}" data-nav="${k}">${t('tab_' + k)}</a>`).join('')}</nav>`;
  $('footer').innerHTML = esc(t('footer'));
}

export function current() {
  const h = location.hash.replace(/^#\/?/, '');
  const [path, qs] = h.split('?');
  const [page, id] = path.split('/');
  return { page: page || 'compare', id: id ? +id : null, q: Object.fromEntries(new URLSearchParams(qs || '')) };
}
export function go(path) { location.hash = '#/' + path; }

let busy = null;
export async function route() {
  const r = current();
  const key = PAGES[r.page] ? r.page : 'compare';
  document.querySelectorAll('[data-nav]').forEach(a => a.setAttribute('aria-current', a.dataset.nav === (key === 'listing' ? 'compare' : key) ? 'page' : 'false'));
  const main = $('main');
  const token = busy = {};
  try {
    const mod = await PAGES[key]();
    if (busy !== token) return;
    await mod.render(main, r);
  } catch (e) {
    main.innerHTML = `<div class="card err"><b>${t('load_failed')}</b><p class="small">${esc(e.message)}</p><button class="btn ghost" type="button" onclick="location.reload()">${t('retry')}</button></div>`;
  }
  if (!r.q.keep) scrollTo({ top: 0 });
}

document.addEventListener('click', async e => {
  const l = e.target.closest('[data-lang]'); if (l) { await setLang(l.dataset.lang); return; }
  if (e.target.closest('[data-logout]')) { await post('/api/auth/logout', {}); location.href = '/login'; }
});
const tip = $('tip');
document.addEventListener('mousemove', e => { const s = e.target.closest('[data-tip]'); if (!s) { tip.style.opacity = 0; return; }
  tip.textContent = s.dataset.tip; tip.style.opacity = 1; const w = tip.offsetWidth; tip.style.left = Math.min(e.clientX + 12, innerWidth - w - 8) + 'px'; tip.style.top = (e.clientY + 14) + 'px'; });
window.addEventListener('hashchange', route);

(async () => {
  applyTheme();
  await i18n.load(i18n.initialLang());
  try { await loadAll(); } catch (e) { $('main').innerHTML = `<div class="card err"><b>${t('load_failed')}</b><p class="small">${esc(e.message)}</p></div>`; }
  renderShell();
  if (!location.hash) location.replace('#/compare');
  route();
})();
