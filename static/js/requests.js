// Research requests (issue #113): an account pastes a listing link; the shared worker researches it and adds the car.
// Shown at the top of Compare; the admins' whole queue is on the Accounts page (pages/admin.js).
import { get, post, patch } from './api.js';
import { t, tv } from './i18n.js';
import { esc, safeUrl, store, toast } from './ui.js';

let REQS = [];
const TAG = { QUEUED: 'warn', RUNNING: 'warn', WAITING: 'warn', DONE: 'good', SKIPPED: 'good', FAILED: 'bad', CANCELLED: '' };
export const statusTag = s => `<span class="tag ${TAG[s] ?? ''}">${esc(tv(s))}</span>`;

// Parts of a request (#218 phase 2): the stages after reading the ad. Missing `parts`/`children` (old server) = no part view.
const ORDER = ['CAPTURE', 'VARIANT', 'GENERATION', 'GEN_MAINTENANCE', 'ENGINE', 'GEARBOX', 'TAX', 'LISTING'];
// user-facing state: SKIPPED counts as done; icon + text, never colour alone
const UST = { DONE: 'done', SKIPPED: 'done', RUNNING: 'doing', WAITING: 'waiting', QUEUED: 'pending', FAILED: 'failed', CANCELLED: 'pending' };
const ICON = { done: '✓', doing: '▶', waiting: '…', pending: '○', failed: '✕' };
export function partList(r, parts) {
  if (!Array.isArray(parts) || !parts.length) return [];
  const cap = { unit: 'CAPTURE', status: r.status === 'FAILED' ? 'FAILED' : 'DONE', attempts: r.attempts, missing: [] };  // the parent row is the capture; reaching the stages means it is done
  return [cap, ...parts].sort((a, b) => ORDER.indexOf(a.unit) - ORDER.indexOf(b.unit));
}
export function partsHtml(r, parts, admin = false) {
  const L = partList(r, parts); if (!L.length) return '';
  const done = L.filter(p => UST[p.status] === 'done').length;
  const li = p => { const st = UST[p.status] ?? 'pending', n = (p.missing || []).length;
    let x = admin ? tv(p.status) : t('rps_' + st);
    if (admin && p.status === 'DONE' && p.shared_id) x = t('rp_done_by', { n: p.shared_id });
    if (admin && p.status === 'WAITING' && p.shared_id) x = t('rp_waits_for', { n: p.shared_id });
    return `<li class="rp ${st}"><span aria-hidden="true">${ICON[st]}</span> ${esc(t('rp_' + p.unit))}: <b>${esc(x)}</b>`
      + `${st === 'failed' && n ? ` <span class="small muted">(${t('rp_missing', { n })})</span>` : ''}`
      + `${admin ? ` <span class="small muted">${[p.worker, p.attempts ? t('rp_attempt', { n: p.attempts }) : ''].filter(Boolean).map(esc).join(' · ')}</span>` : ''}`
      + `${admin && n ? `<details class="small"><summary>${t('rp_items')} (${n})</summary>${p.missing.map(esc).join(', ')}</details>` : ''}`
      + `${admin && p.result ? `<div class="small muted">${esc(String(p.result).split('\n')[0])}</div>` : ''}</li>`; };
  return `<div class="rparts"><div class="small muted">${t('rp_summary', { n: done, m: L.length })}</div><ul>${L.map(li).join('')}</ul></div>`;
}
export async function loadRequests() { try { REQS = await get('/api/requests'); } catch { REQS = []; } }

export function requestsPanel() {
  const open = store.get('reqsOpen', false);  // collapsed by default, remembered per browser (issue #180)
  const list = REQS.slice(0, 10).map(r => `<li><a href="${safeUrl(r.url)}" target="_blank" rel="noopener">${esc(r.url)}</a> ${statusTag(r.status)}
    <span class="small muted">${esc(r.requested_at)}</span>${r.status === 'QUEUED' ? ` <button class="btn ghost sm" type="button" data-reqcancel="${r.id}">${t('req_cancel')}</button>` : ''}
    ${r.listing_id ? ` <a class="btn ghost sm" href="#/listing/${r.listing_id}">${t('req_open_car')}</a>` : ''}${partsHtml(r, r.parts)}${r.status === 'FAILED' && r.result ? `<div class="small muted">${esc(r.result.split('\n')[0])}</div>` : ''}</li>`).join('');
  return `<details class="card reqs"${open ? ' open' : ''}><summary><b>${t('req_title')}</b></summary><p class="small muted">${t('req_lead')}</p>
    <form class="row" data-reqform><div class="field"><label for="req_url">${t('req_url')}</label><input id="req_url" type="url" required maxlength="500" placeholder="https://"></div>
      <div class="field"><label for="req_note">${t('req_note')}</label><input id="req_note" maxlength="1000"></div><button class="btn" type="submit" style="align-self:end">${t('req_send')}</button></form>
    ${list ? `<ul class="reqlist">${list}</ul>` : ''}</details>`;
}

// delegated on the page root; redraw() repaints the page after the list changed
export function bindRequests(root, redraw) {
  root.addEventListener('toggle', e => { if (e.target.matches?.('details.reqs')) store.set('reqsOpen', e.target.open); }, true);  // toggle doesn't bubble
  root.addEventListener('submit', async e => { const f = e.target.closest('[data-reqform]'); if (!f) return; e.preventDefault();
    try { await post('/api/requests', { url: f.querySelector('#req_url').value.trim(), note: f.querySelector('#req_note').value.trim() }); toast(t('req_sent')); await loadRequests(); redraw(); }
    catch (err) { toast(err.message, true); } });
  root.addEventListener('click', async e => { const b = e.target.closest('[data-reqcancel]'); if (!b) return;
    try { await patch(`/api/requests/${b.dataset.reqcancel}`, { status: 'CANCELLED' }); await loadRequests(); redraw(); } catch (err) { toast(err.message, true); } });
}
