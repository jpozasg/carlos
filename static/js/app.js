// Carlos front end: shell, router, shared state. Pages live in ./pages/*.js; every theme runs this same code.
import { get, post } from './api.js';
import * as i18n from './i18n.js';
import { t } from './i18n.js';
import { $, esc, num, store, toast, yrs } from './ui.js';

export const S = { accounts: [], me: null, p: null, saved: null, preview: false, units: [], components: [], ranking: null, budget: null,
  fuelStale: null, storage: null, todo: { listings: [], models: [] }, sources: [], models: null, prefs: {} };
const PAGES = {
  compare: () => import('./pages/compare.js'), ranking: () => import('./pages/ranking.js'), listing: () => import('./pages/dossier.js'),
  models: () => import('./pages/models.js'), sources: () => import('./pages/sources.js'), settings: () => import('./pages/settings.js'),
  admin: () => import('./pages/admin.js'), start: () => import('./pages/start.js') };
const NAV = ['compare', 'ranking', 'models', 'sources', 'settings'];
// "view as account" (issue #142): the admin's session sends this cookie, so every page and photo shows that account
export const viewing = () => +(document.cookie.match(/(?:^|; )carlos_view=(\d+)/) || [])[1] || null;
function setView(id) {
  document.cookie = id ? `carlos_view=${id}; path=/; SameSite=Strict` : 'carlos_view=; path=/; max-age=0; SameSite=Strict';
  location.hash = '#/compare'; location.reload();
}

export function applyTheme(mode = store.get('mode', 'auto')) {  // one theme (issue #181): only light/dark/auto is chosen
  const root = document.documentElement;
  root.dataset.theme = 'cluster';
  if (mode === 'auto') root.removeAttribute('data-mode'); else root.dataset.mode = mode;
  root.classList.toggle('os-dark', matchMedia('(prefers-color-scheme: dark)').matches);
  store.set('mode', mode);
  document.querySelector('meta[name=theme-color]')?.setAttribute('content', getComputedStyle(root).getPropertyValue('--bg').trim() || '#fff');
}
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => applyTheme());

export async function setLang(l) { await i18n.load(l); renderShell(); route(); }

export async function loadAll() {
  const [me, p, tco, st, td, ss, pr] = await Promise.all([get('/api/auth/me'), get('/api/parameters'), get('/api/tco'), get('/api/storage'), get('/api/todo'), get('/api/sources'), get('/api/preferences')]);
  Object.assign(S, { me, p, saved: p, preview: false, units: tco.listings, components: tco.components, ranking: tco.ranking, budget: tco.budget,
    fuelStale: tco.fuel_price_stale, storage: st, todo: td, sources: ss, models: null,
    prefs: Object.fromEntries(pr.map(x => [x.preference_key, x.preference_value])) });
  if (me.role === 'admin') S.accounts = await get('/api/admin/users');
}
export async function refreshTco(query = '') {
  const d = await get('/api/tco' + query);
  Object.assign(S, { p: d.parameters, units: d.listings, ranking: d.ranking, budget: d.budget, fuelStale: d.fuel_price_stale, preview: d.preview });
  return d;
}

const viewedName = () => { const v = viewing(); return v && v !== S.me?.id ? S.accounts.find(u => u.id === v)?.username : null; };
export function renderShell() {
  document.title = t('app_title');
  document.querySelector('[data-i18n-skip]').textContent = t('skip_content');
  document.querySelectorAll('[data-aria]').forEach(b => b.setAttribute('aria-label', t(b.dataset.aria)));
  const p = S.p, st = S.storage;
  const chips = p ? `<a class="chip${S.fuelStale || S.preview ? ' warn' : ''}" href="#/settings" title="${esc(S.fuelStale ? t('fuel_stale') : t('edit_params'))}">${S.preview ? '✎ ' : S.fuelStale ? '⚠ ' : ''}${num(p.annual_km, 0)} ${t('per_year_short')} · ${yrs(p.ownership_years)} · ${num(p.fuel_price_eur_l, 2)} €/l</a>
    <span class="chip chip-store${st && st.total_bytes / st.limit_bytes >= .9 ? ' bad' : st && st.total_bytes / st.limit_bytes >= .8 ? ' warn' : ''}" title="${esc(t('storage_hint'))}">${st ? `${num(st.total_bytes / 1048576, 1)} / ${num(st.limit_bytes / 1048576, 0)} MB` : ''}</span>` : '';
  const langs = `<div class="seg" role="group" aria-label="${esc(t('language'))}">${Object.keys(i18n.LANGS).map(l => `<button type="button" data-lang="${l}" lang="${l}" aria-pressed="${l === i18n.current()}">${l.toUpperCase()}</button>`).join('')}</div>`;
  $('hdr').innerHTML = `<div class="bar"><a class="brand" href="#/compare" aria-label="${esc(t('app_title'))}"><svg viewBox="0 0 64 64" aria-hidden="true"><use href="/static/brand/mark.svg#mark"/></svg><span><b>Carlos</b><small>${esc(t('tagline'))}</small></span></a>${chips}${langs}
    ${S.me?.role === 'admin' ? `<select class="chip" data-viewas aria-label="${esc(t('view_as'))}" title="${esc(t('view_as'))}"><option value="">${esc(t('view_as_me'))}</option>${S.accounts.filter(u => u.is_active && u.id !== S.me.id).map(u => `<option value="${u.id}"${u.id === viewing() ? ' selected' : ''}>${esc(t('view_as'))}: ${esc(u.username)}</option>`).join('')}</select>` : ''}
    ${S.me ? `<a class="chip" href="#/settings" title="${esc(t('account'))}">👤 ${esc(S.me.username)}</a><button class="chip" type="button" data-logout>${t('logout')}</button>` : ''}</div>
    ${viewedName() ? `<div class="callout viewas" role="status"><p>${t('viewing_as', { u: `<b>${esc(viewedName())}</b>` })}</p><button class="btn sm" type="button" data-viewas-exit>${t('viewing_exit')}</button></div>` : ''}
    <nav class="main" aria-label="${esc(t('sections'))}">${[...NAV, ...(S.me?.role === 'admin' ? ['admin'] : [])].map(k => `<a href="#/${k}" data-nav="${k}">${t('tab_' + k)}</a>`).join('')}</nav>`;
  $('footer').innerHTML = esc(t('footer')) + ' · ' + t('osm_credit');  // ODbL attribution for the bundled postcode points (#169)
  setHeaderHeight();
}
function setHeaderHeight() {  // the compare control bar sticks right below the (sticky) header
  const h = document.querySelector('header.top');
  document.documentElement.style.setProperty('--hdr', (getComputedStyle(h).position === 'sticky' ? h.offsetHeight : 0) + 'px');
}
window.addEventListener('resize', setHeaderHeight);

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
  if (!r.q.keep) { scrollTo({ top: 0 }); main.focus({ preventScroll: true }); }  // screen readers and keyboard start at the new page
}

document.addEventListener('click', async e => {
  if (e.target.closest('[data-i18n-skip]')) { e.preventDefault(); $('main').focus(); return; }  // a #main href would break the hash router
  const l = e.target.closest('[data-lang]'); if (l) { await setLang(l.dataset.lang); return; }
  if (e.target.closest('[data-viewas-exit]')) { setView(null); return; }
  if (e.target.closest('[data-logout]')) { document.cookie = 'carlos_view=; path=/; max-age=0; SameSite=Strict'; await post('/api/auth/logout', {}); location.href = '/login'; }
});
const tip = $('tip');
document.addEventListener('mousemove', e => { const s = e.target.closest('[data-tip]'); if (!s) { tip.style.opacity = 0; return; }
  tip.textContent = s.dataset.tip; tip.style.opacity = 1; const w = tip.offsetWidth; tip.style.left = Math.min(e.clientX + 12, innerWidth - w - 8) + 'px'; tip.style.top = (e.clientY + 14) + 'px'; });
// a tap (touch screens have no hover) or click on a [data-tip] element shows its tooltip under it
document.addEventListener('click', e => { const s = e.target.closest('[data-tip]'); if (!s) return;
  tip.textContent = s.dataset.tip; tip.style.opacity = 1; const r = s.getBoundingClientRect(), w = tip.offsetWidth;
  tip.style.left = Math.max(8, Math.min(r.left, innerWidth - w - 8)) + 'px'; tip.style.top = (r.bottom + 6) + 'px'; });
// keyboard: Enter or Space on a focused tip icon shows the tooltip like a tap; Escape or blur hides it
document.addEventListener('keydown', e => { if (e.key === 'Escape') tip.style.opacity = 0; else if ((e.key === 'Enter' || e.key === ' ') && e.target.matches?.('[data-tip][tabindex]')) { e.preventDefault(); e.target.click(); } });
document.addEventListener('focusout', e => { if (e.target.matches?.('[data-tip]')) tip.style.opacity = 0; });
window.addEventListener('scroll', () => { tip.style.opacity = 0; }, { passive: true });
window.addEventListener('hashchange', route);
document.addEventListener('change', e => { const v = e.target.closest('[data-viewas]'); if (v) setView(+v.value || null); });

(async () => {
  applyTheme();
  await i18n.load(i18n.initialLang());
  try { await loadAll(); } catch (e) { $('main').innerHTML = `<div class="card err"><b>${t('load_failed')}</b><p class="small">${esc(e.message)}</p></div>`; }
  renderShell();
  // first run: the setup wizard until it was finished or put off (preference onboarding_done)
  if (S.me && !viewing() && !S.prefs.onboarding_done && (!location.hash || location.hash === '#/compare')) location.replace('#/start');
  else if (!location.hash) location.replace('#/compare');
  route();
})();
