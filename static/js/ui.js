import { t, tv, locale } from './i18n.js';
export const $ = id => document.getElementById(id);
export const esc = s => s == null ? '' : String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
export const safeUrl = u => /^https?:\/\//i.test(u || '') ? esc(u) : '#';
export const euro = n => n == null ? '—' : new Intl.NumberFormat(locale(), { style: 'currency', currency: 'EUR', maximumFractionDigits: 0, useGrouping: 'always' }).format(n);
export const num = (n, d = 2) => n == null ? '—' : new Intl.NumberFormat(locale(), { maximumFractionDigits: d, useGrouping: 'always' }).format(n);
export const PEND = () => `<span class="pending">${t('pending')}</span>`;
export const eP = n => n == null ? PEND() : euro(n);
export const yrs = n => `${num(n, 1)} ${t('years', { n })}`;
export const store = {
  get(k, d) { try { const v = localStorage.getItem('carlos.' + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('carlos.' + k, JSON.stringify(v)); } catch (e) {} },
};
export function toast(msg, bad) {
  const el = $('toast'); el.textContent = msg; el.className = 'show' + (bad ? ' bad' : '');
  clearTimeout(el._h); el._h = setTimeout(() => el.className = bad ? 'bad' : '', 3500);
}
export const empty = x => `<p class="empty">${x}</p>`;
export const facts = pairs => `<dl class="facts">${pairs.map(([k, v]) => `<dt>${k}</dt><dd>${v ?? PEND()}</dd>`).join('')}</dl>`;
export const media = fp => '/media/' + esc(fp);
export const CAR_SVG = '<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 40v-8l6-12a4 4 0 0 1 3.6-2.2h28.8A4 4 0 0 1 50 20l6 12v8a3 3 0 0 1-3 3H11a3 3 0 0 1-3-3Z"/><path d="M12 32h40"/><circle cx="19" cy="43" r="5"/><circle cx="45" cy="43" r="5"/></svg>';
export const thumb = (u, cls = '') => u.cover ? `<img class="thumb ${cls}" src="${media(u.cover)}" alt="" loading="lazy">` : `<span class="thumb ${cls}" aria-hidden="true"></span>`;
export const unitName = u => `${esc(u.make)} ${esc(u.model)}`;
// every car, model or engine name links somewhere: a listing to its dossier, a variant to its model page, a model or
// engine to the models tree filtered to it
export const modelsHref = f => '#/models?' + new URLSearchParams(Object.entries(f).filter(([, v]) => v)).toString();
export const carLink = (u, html = carLabel(u)) => `<a class="carlink" href="#/listing/${u.id}">${html}</a>`;
// short, unambiguous car name: model, engine size and first-registration year
export const carShort = u => `${esc(u.model)}${u.displacement_cc ? ' ' + (u.displacement_cc / 1000).toFixed(1) : ''}${u.first_registration ? ' · ' + esc(String(u.first_registration).slice(0, 4)) : ''}`;
export const carLabel = u => `${esc(u.make)} ${carShort(u)}`;
export const unitSub = u => u.is_reference ? t('your_car') : `${esc(u.platform ?? '')}${u.listing_id ? ' ' + esc(u.listing_id) : ''}`;
export const sevTag = s => !s ? PEND() : `<span class="tag ${/HIGH/.test(s) ? 'bad' : /MEDIUM/.test(s) ? 'warn' : 'good'}">${esc(tv(s))}</span>`;
export const lvlTag = l => l ? `<span class="tag lvl lvl-${esc(l)}" title="${esc(t('level_hint'))}"><i class="dot"></i>${esc(tv(l))}</span>` : '';
export const qTag = (q, title = '') => { const ql = /^[ABCD]$/.test(q ?? '') ? q : 'X'; return `<span class="q ${ql}" title="${esc(title)}">${esc(q ?? '–')}</span>`; };
export function statusTags(u) {
  const b = u.budget_status, tags = [];
  if (b === 'over_max') tags.push(`<span class="tag bad">⚠ ${t('over_max')}</span>`);
  else if (b === 'over_ideal') tags.push(`<span class="tag warn">${t('over_ideal')}</span>`);
  if (u.price_change) { const d = u.price_change.eur; tags.push(`<span class="tag ${d < 0 ? 'good' : 'warn'}" title="${esc(t('price_change_title', { d: u.price_change.since }))}">${d < 0 ? '▼' : '▲'} ${euro(Math.abs(d))} ${t('since_date', { d: esc(u.price_change.since) })}</span>`); }
  if (u.stale) tags.push(`<span class="tag warn">⏱ ${t('stale', { n: 14 })}</span>`);
  if (u.listing_status === 'WITHDRAWN') tags.push(`<span class="tag">${esc(tv('WITHDRAWN'))}</span>`);
  return tags;
}
export function gaps(items) {
  if (!items || !items.length) return `<p class="small" style="margin:10px 0 0"><span class="tag good">✓ ${t('no_gaps')}</span></p>`;
  return `<details style="margin-top:10px"><summary class="small" style="cursor:pointer"><span class="tag warn">${t('gaps', { n: items.length })}</span></summary>
    <ul class="small" lang="en" style="margin:6px 0 0;padding-left:18px">${items.map(x => `<li>${esc(x)}</li>`).join('')}</ul><p class="small muted" style="margin:4px 0 0">${t('gaps_note')}</p></details>`;
}
export function intervalTxt(km, mo) { const a = []; if (km) a.push(num(km, 0) + ' km'); if (mo) a.push(num(mo, 0) + ' ' + t('months_short')); return a.join(' ' + t('or_word') + ' ') || '—'; }
