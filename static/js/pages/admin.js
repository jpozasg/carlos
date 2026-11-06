// Admin (issue #142): research workers (status, token), accounts (invite link, re-invite, deactivate, role), the research
// queue and the change log. Viewing any account is the header switcher (app.js).
import { S } from '../app.js';
import { get, post, patch } from '../api.js';
import { t } from '../i18n.js';
import { $, esc, toast, empty, safeUrl } from '../ui.js';
import { statusTag } from '../requests.js';

let root, users = [], reqs = [], lastInvite = null, workers = [], lastToken = null, changes = [];
const WS = { idle: '', working: 'good', error: 'bad', down: 'bad', deactivated: '' };
const uname = id => esc(users.find(u => u.id === id)?.username ?? (id == null ? '—' : '#' + id));
function workersHtml() {
  const rows = workers.map(w => `<tr><td><b>${esc(w.name)}</b></td><td><span class="tag ${WS[w.status] ?? ''}">${esc(t('ws_' + w.status))}</span></td>
    <td class="small">${esc(w.last_seen ?? '—')}</td>
    <td class="small">${w.url ? `<a href="${safeUrl(w.url)}" target="_blank" rel="noopener">${esc(w.url)}</a><div class="muted">${esc(w.username ?? '')}${w.listing_id ? ` · #${w.listing_id}` : ''}</div>` : '—'}</td>
    <td class="small">${w.last_error ? `${esc(w.last_error)}<div class="muted">${esc(w.last_error_at ?? '')}</div>` : '—'}</td>
    <td class="row"><button class="btn ghost sm" type="button" data-wtoken="${w.id}">${t('worker_regen')}</button><button class="btn ghost sm" type="button" data-wactive="${w.id}" data-to="${w.is_active ? 0 : 1}">${w.is_active ? t('deactivate') : t('activate')}</button></td></tr>`).join('');
  return `<h3>${t('workers')}</h3><p class="small muted">${t('workers_lead')}</p>
    <form id="newWorker" class="row" style="margin-bottom:12px"><div class="field"><label for="nw_name">${t('worker_name')}</label><input id="nw_name" pattern="[\\w.-]{2,40}" required></div><button class="btn" type="submit" style="align-self:flex-end">${t('worker_create')}</button></form>
    ${lastToken ? `<p class="small" style="margin:0 0 4px">${t('worker_token_hint', { n: esc(lastToken.name) })}</p><div class="token-box" style="margin-bottom:12px">${esc(lastToken.token)}</div>` : ''}
    <div class="tablewrap"><table><thead><tr><th>${t('worker_name')}</th><th>${t('status')}</th><th>${t('worker_last_seen')}</th><th>${t('worker_job')}</th><th>${t('worker_error')}</th><th></th></tr></thead><tbody>${rows || `<tr><td colspan="6">${empty('')}</td></tr>`}</tbody></table></div>`;
}
function changesHtml() {
  return `<h3 style="margin-top:24px">${t('changes')}</h3><p class="small muted">${t('changes_lead')}</p>
    <div class="tablewrap"><table><thead><tr><th>${t('ch_when')}</th><th>${t('ch_writer')}</th><th>${t('ch_account')}</th><th>${t('ch_table')}</th><th>${t('ch_action')}</th></tr></thead><tbody>${changes.map(x => `<tr><td class="small">${esc(x.changed_at)}</td><td>${esc(x.writer ?? '—')}</td><td>${esc(x.account ?? '—')}</td><td class="small">${esc(x.table_name)} #${x.row_id}</td><td class="small">${esc(x.action)}</td></tr>`).join('') || `<tr><td colspan="5">${empty('')}</td></tr>`}</tbody></table></div>
    ${changes.length && changes.length % 50 === 0 ? `<button class="btn ghost sm" type="button" data-older style="margin-top:8px">${t('ch_older')}</button>` : ''}`;
}
function draw() {
  const rows = users.map(u => `<tr><td><b>${esc(u.username)}</b>${u.id === S.me.id ? ` <span class="tag ref">${t('you')}</span>` : ''}</td><td>${esc(t('role_' + u.role))}</td>
    <td>${u.is_active ? `<span class="tag good">${t('active')}</span>` : `<span class="tag">${t('inactive')}</span>`}${u.has_password ? '' : ` <span class="tag warn">${t('no_password')}</span>`}</td><td class="small">${esc(u.created_at)}</td>
    <td class="row"><button class="btn ghost sm" type="button" data-invite="${u.id}">${t('invite_link')}</button>
      ${u.id !== S.me.id ? `<button class="btn ghost sm" type="button" data-active="${u.id}" data-to="${u.is_active ? 0 : 1}">${u.is_active ? t('deactivate') : t('activate')}</button><button class="btn ghost sm" type="button" data-role="${u.id}" data-to="${u.role === 'admin' ? 'user' : 'admin'}">${u.role === 'admin' ? t('make_user') : t('make_admin')}</button>` : ''}</td></tr>`).join('');
  root.innerHTML = `<div class="section"><h2>${t('tab_admin')}</h2><p class="lead">${t('admin_lead')}</p>
    <div class="card" style="margin-bottom:16px">${workersHtml()}</div>
    <div class="card" style="margin-bottom:16px"><h3>${t('new_user')}</h3><form id="newUser" class="row"><div class="field"><label for="nu_name">${t('username')}</label><input id="nu_name" pattern="[\\w.-]{2,40}" required></div>
      <div class="field"><label for="nu_role">${t('role')}</label><select id="nu_role" class="inline"><option value="user">${t('role_user')}</option><option value="admin">${t('role_admin')}</option></select></div><button class="btn" type="submit" style="align-self:flex-end">${t('create_invite')}</button></form>
      ${lastInvite ? `<p class="small" style="margin:12px 0 4px">${t('invite_created', { u: esc(lastInvite.username) })}</p><div class="token-box">${esc(lastInvite.invite)}</div>` : ''}</div>
    <div class="tablewrap"><table><thead><tr><th>${t('username')}</th><th>${t('role')}</th><th>${t('status')}</th><th>${t('created')}</th><th></th></tr></thead><tbody>${rows || `<tr><td colspan="5">${empty('')}</td></tr>`}</tbody></table></div>
    <h3 style="margin-top:24px">${t('req_queue')}</h3><p class="small muted">${t('req_queue_lead')}</p>
    <div class="tablewrap"><table><thead><tr><th>${t('req_requested')}</th><th>${t('username')}</th><th>${t('req_url')}</th><th>${t('status')}</th><th>${t('req_result')}</th></tr></thead><tbody>${reqs.map(r => `<tr><td class="small">${esc(r.requested_at)}</td><td>${esc(r.username)}</td>
      <td class="small"><a href="${safeUrl(r.url)}" target="_blank" rel="noopener">${esc(r.url)}</a>${r.note ? `<div class="muted">${esc(r.note)}</div>` : ''}</td><td>${statusTag(r.status)}${r.worker ? `<div class="small muted">${esc(r.worker)} · ${esc(r.claimed_at ?? '')}</div>` : ''}${r.requested_by ? `<div class="small muted">${t('req_by', { u: uname(r.requested_by) })}</div>` : ''}</td>
      <td class="small">${r.listing_id ? `#${r.listing_id} ` : ''}${esc((r.result || '').split('\n')[0])}</td></tr>`).join('') || `<tr><td colspan="5">${empty('')}</td></tr>`}</tbody></table></div>${changesHtml()}</div>`;
}
async function reload() { [users, reqs, workers, changes] = await Promise.all([get('/api/admin/users'), get('/api/admin/requests'), get('/api/admin/workers'), get('/api/admin/changes?limit=50')]); draw(); }
function bind() {
  root.addEventListener('submit', async e => { e.preventDefault();
    if (e.target.id === 'newWorker') { try { const name = $('nw_name').value.trim(); const r = await post('/api/admin/workers', { name }); lastToken = { name, token: r.token }; await reload(); } catch (err) { toast(err.message, true); } return; }
    try { const r = await post('/api/admin/users', { username: $('nu_name').value.trim(), role: $('nu_role').value }); lastInvite = r; await reload(); } catch (err) { toast(err.message, true); } });
  root.addEventListener('click', async e => {
    const wt = e.target.closest('[data-wtoken]'); if (wt) { try { const r = await post(`/api/admin/workers/${wt.dataset.wtoken}/token`, {}); lastToken = { name: workers.find(w => w.id === +wt.dataset.wtoken)?.name, token: r.token }; draw(); } catch (err) { toast(err.message, true); } return; }
    const wa = e.target.closest('[data-wactive]'); if (wa) { try { await patch(`/api/admin/workers/${wa.dataset.wactive}`, { is_active: +wa.dataset.to }); await reload(); } catch (err) { toast(err.message, true); } return; }
    if (e.target.closest('[data-older]')) { try { changes = changes.concat(await get(`/api/admin/changes?limit=50&before=${changes[changes.length - 1].id}`)); draw(); } catch (err) { toast(err.message, true); } return; }
    const inv = e.target.closest('[data-invite]'); if (inv) { try { const r = await post(`/api/admin/users/${inv.dataset.invite}/invite`, {}); lastInvite = { username: users.find(u => u.id === +inv.dataset.invite)?.username, invite: r.invite }; draw(); } catch (err) { toast(err.message, true); } return; }
    const ac = e.target.closest('[data-active]'); if (ac) { try { await patch(`/api/admin/users/${ac.dataset.active}`, { is_active: +ac.dataset.to }); await reload(); } catch (err) { toast(err.message, true); } return; }
    const ro = e.target.closest('[data-role]'); if (ro) { try { await patch(`/api/admin/users/${ro.dataset.role}`, { role: ro.dataset.to }); await reload(); } catch (err) { toast(err.message, true); } } });
}
export async function render(main) {
  if (S.me?.role !== 'admin') { main.innerHTML = `<div class="card err">${t('admin_only')}</div>`; return; }
  if (!root || !main.contains(root)) { main.innerHTML = '<div data-page="admin"></div>'; root = main.firstElementChild; bind(); }
  await reload();
}
