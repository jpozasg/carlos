import { t, tv, locale } from './i18n.js';
export const $ = id => document.getElementById(id);
export const esc = s => s == null ? '' : String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
export const safeUrl = u => /^https?:\/\//i.test(u || '') ? esc(u) : '#';
export const euro = n => n == null ? '—' : new Intl.NumberFormat(locale(), { style: 'currency', currency: 'EUR', maximumFractionDigits: 0, useGrouping: 'always' }).format(n);
export const num = (n, d = 2) => n == null ? '—' : new Intl.NumberFormat(locale(), { maximumFractionDigits: d, useGrouping: 'always' }).format(n);
// a score exists only when the car is complete (#169); otherwise what is missing
export const scoreTxt = u => num(u.score, 0);
export const notScoredTxt = u => u.excluded === 'over_max' ? t('excluded_over_max') : (u.excluded || '').startsWith('filter:') ? t('excluded_filter', { f: t('flt_' + u.excluded.slice(7)) }) : !u.not_scored ? t('not_ranked')
  : [u.not_scored.criteria.length ? t('ns_criteria', { l: u.not_scored.criteria.map(k => t('c_' + k)).join(', ') }) : '',
     u.not_scored.research.length ? t('ns_research', { n: u.not_scored.research.length }) : ''].filter(Boolean).join(' · ') || t('not_ranked');
// eight validated series colours (docs/frontend.md) by the criterion's position; a ninth gets a neutral colour, never an undefined --s9
export const critColor = (k, keys) => { const i = keys.indexOf(k); return i >= 0 && i < 9 ? `var(--s${i + 1})` : 'var(--text-3)'; };
export const PEND = () => `<span class="pending">${t('pending')}</span>`;
export const eP = n => n == null ? PEND() : euro(n);
// totals reduce to {sum, missing, n}: a row without a figure is counted as missing, never added as 0 (docs/frontend.md)
export const sumKnown = (rows, pick) => rows.reduce((a, r) => { const v = pick(r); if (v == null) a.missing++; else { a.sum += v; a.n++; } return a; }, { sum: 0, missing: 0, n: 0 });
// a reduced total as text: the amount, then "+n pending" while any row is unknown; nothing known at all = pending
export const totalP = r => !r.n ? PEND() : r.missing ? `${euro(r.sum)} <span class="tag warn">+${t('pendings', { n: r.missing })}</span>` : euro(r.sum);
// known cost per month always wears the partial marker (text) unless the car's TCO is complete; suffix = e.g. "/month"
export const perMonth = (u, suffix = '') => u.known_cost_per_month == null ? PEND() : euro(u.known_cost_per_month) + suffix + (u.tco_complete ? '' : ` <span class="tag warn">${t('partial_short')}</span>`);
// a share or probability (0-1) as a percentage; null stays pending, never "0 %"
export const pct = (v, d = 0) => v == null ? PEND() : `${num(v * 100, d)}\u00a0%`;
// parts + labour as one price: both unknown = pending, one unknown = the known part with the partial marker (never a complete price)
export const partsLaborP = (a, b) => a == null && b == null ? PEND() : euro((a || 0) + (b || 0)) + (a == null || b == null ? ` <span class="tag warn">${t('partial_short')}</span>` : '');
// "a–b" where one end may be open; both unknown = pending (never "—–—")
export const rangeTxt = (a, b, d = 0) => a == null && b == null ? PEND() : `${a == null ? '…' : num(a, d)}–${b == null ? '…' : num(b, d)}`;
// consumption with its unit as the data gives it (no invented unit) and the spread of the source (min-max, sample size) when known
export const consumptionTxt = u => u.consumption == null ? PEND() : `${num(u.consumption)}\u00a0${u.consumption_unit ? esc(u.consumption_unit) : PEND()}`;
export const consumptionSpread = u => [u.consumption_min != null && u.consumption_max != null ? rangeTxt(u.consumption_min, u.consumption_max, 2) : null, u.consumption_sample != null ? `n=${num(u.consumption_sample, 0)}` : null].filter(Boolean).join(' · ');
export const yrs = n => `${num(n, 1)} ${t('years', { n })}`;
export const store = {
  get(k, d) { try { const v = localStorage.getItem('carlos.' + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('carlos.' + k, JSON.stringify(v)); } catch (e) {} },
};
// an error stays until the reader closes it (role=alert, a close button); a success goes after 3.5 s
export function toast(msg, bad) {
  const el = $('toast'); clearTimeout(el._h);
  el.setAttribute('role', bad ? 'alert' : 'status'); el.textContent = msg; el.className = 'show' + (bad ? ' bad' : '');
  if (!bad) { el._h = setTimeout(() => el.classList.remove('show'), 3500); return; }
  const x = document.createElement('button'); x.type = 'button'; x.className = 'toast-x'; x.textContent = '×';
  x.setAttribute('aria-label', t('dismiss')); x.addEventListener('click', () => el.classList.remove('show')); el.append(x);
}
// a request-sending control: disabled and aria-busy while `work` runs, restored in finally so a double submit is impossible
export async function busy(btn, work) {
  const label = btn.textContent; btn.disabled = true; btn.setAttribute('aria-busy', 'true'); btn.textContent = t('saving');
  try { return await work(); }
  finally { if (btn.isConnected) { btn.disabled = false; btn.removeAttribute('aria-busy'); btn.textContent = label; } }
}
// an ISO date (YYYY-MM-DD) as the reader's locale writes it
export const fmtDate = iso => /^\d{4}-\d\d-\d\d/.test(iso || '') ? new Intl.DateTimeFormat(locale(), { dateStyle: 'medium' }).format(new Date(iso.slice(0, 10) + 'T12:00:00')) : '';
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
export const lvlTag = (l, r) => (l ? `<span class="tag lvl lvl-${esc(l)}" title="${esc(t('level_hint'))}"><i class="dot"></i>${esc(tv(l))}</span>` : '')
  + (r && (r.applies_from || r.applies_to) ? ` <span class="tag" title="${esc(t('window_hint'))}">${esc(r.applies_from || '…')}–${esc(r.applies_to || '…')}</span>` : '');  // first-registration window (#153)
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
// the research contract per level (issue #114): state, what is missing and what is only estimated; item titles are
// English agent texts (lang="en"), like the to-do
const RS = { verified: 'good', researched: '', incomplete: 'warn' };
export function researchLevels(levels) {
  const rows = Object.entries(levels || {}).map(([lvl, x]) => {
    const open = x.items.filter(i => i.grade !== 'VERIFIED');
    return `<li>${lvlTag(lvl)} <span class="tag ${RS[x.state]}">${t('rs_' + x.state)}</span>${x.missing.length ? ` <span class="small">${t('rs_missing', { n: x.missing.length })}</span>` : ''}${x.accepted.length ? ` <span class="small muted">· ${t('rs_accepted', { n: x.accepted.length })}</span>` : ''}
      ${open.length ? `<details class="small"><summary style="cursor:pointer">${open.length}</summary><ul lang="en" style="margin:4px 0 0;padding-left:18px">${open.map(i => `<li>${i.grade === 'MISSING' ? '✗' : '½'} <code>${esc(i.id)}</code> ${esc(i.title)}${i.hint ? ` <span class="tag warn">${t('rs_move')}</span>` : ''}</li>`).join('')}</ul></details>` : ''}</li>`; }).join('');
  return rows ? `<ul class="rs-levels">${rows}</ul>` : '';
}
export function gaps(items) {
  if (!items || !items.length) return `<p class="small" style="margin:10px 0 0"><span class="tag good">✓ ${t('no_gaps')}</span></p>`;
  return `<details style="margin-top:10px"><summary class="small" style="cursor:pointer"><span class="tag warn">${t('gaps', { n: items.length })}</span></summary>
    <ul class="small" lang="en" style="margin:6px 0 0;padding-left:18px">${items.map(x => `<li>${esc(x)}</li>`).join('')}</ul><p class="small muted" style="margin:4px 0 0">${t('gaps_note')}</p></details>`;
}
export function intervalTxt(km, mo) { const a = []; if (km) a.push(num(km, 0) + ' km'); if (mo) a.push(num(mo, 0) + ' ' + t('months_short')); return a.join(' ' + t('or_word') + ' ') || '—'; }

// review flags of a level (#168): what, why and every review (worker, date, outcome, finding); a flag clears only when
// two independent reviews reach the same conclusion, so an open one stays visible here and in every inheriting dossier
export function flagsCard(flags) {
  if (!flags || !flags.length) return '';
  const open = f => f.status === 'OPEN';
  return `<div class="card span2"><h3>${t('flags_title')} <span class="muted small">${flags.filter(open).length}</span></h3><p class="small muted" style="margin-top:0">${t('flags_lead')}</p>
    <ul class="check">${flags.map(f => `<li><span class="ico ${open(f) ? 'pend' : 'ok'}" aria-hidden="true">${open(f) ? '!' : '✓'}</span><div><b>${esc(f.what)}</b> <span class="tag ${open(f) ? 'warn' : 'good'}">${esc(tv(f.status))}</span> <span class="tag">${esc(tv(f.kind))}</span> ${lvlTag(f.level)}
      <div class="small muted">${esc(f.why)}</div>${(f.reviews || []).length ? `<ul class="small" style="margin:4px 0 0;padding-left:18px">${f.reviews.map(r => `<li>${esc(r.review_date)} · ${esc(r.worker)} · <b>${esc(tv(r.outcome))}</b>: ${esc(r.conclusion)} — ${esc(r.finding)}</li>`).join('')}</ul>` : `<div class="small muted">${t('flag_no_reviews')}</div>`}</div></li>`).join('')}</ul></div>`;
}
// a fault's probability as the sources put it: a frequency band with its shape, or a sourced curve (#168)
export const faultProb = f => f.frequency_band ? `${esc(tv(f.frequency_band))}${f.shape ? ' · ' + esc(tv(f.shape)) : ''}` : (f.curve_km || f.curve_age ? t('f_curve') : '—');
