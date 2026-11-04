// Admin: accounts (create with an invite link, re-invite, deactivate, role).
import { S } from '../app.js';
import { get, post, patch } from '../api.js';
import { t } from '../i18n.js';
import { $, esc, toast, empty } from '../ui.js';

let root, users = [], lastInvite = null;
function draw() {
  const rows = users.map(u => `<tr><td><b>${esc(u.username)}</b>${u.id === S.me.id ? ` <span class="tag ref">${t('you')}</span>` : ''}</td><td>${esc(t('role_' + u.role))}</td>
    <td>${u.is_active ? `<span class="tag good">${t('active')}</span>` : `<span class="tag">${t('inactive')}</span>`}${u.has_password ? '' : ` <span class="tag warn">${t('no_password')}</span>`}</td><td class="small">${esc(u.created_at)}</td>
    <td class="row"><button class="btn ghost sm" type="button" data-invite="${u.id}">${t('invite_link')}</button>
      ${u.id !== S.me.id ? `<button class="btn ghost sm" type="button" data-active="${u.id}" data-to="${u.is_active ? 0 : 1}">${u.is_active ? t('deactivate') : t('activate')}</button><button class="btn ghost sm" type="button" data-role="${u.id}" data-to="${u.role === 'admin' ? 'user' : 'admin'}">${u.role === 'admin' ? t('make_user') : t('make_admin')}</button>` : ''}</td></tr>`).join('');
  root.innerHTML = `<div class="section"><h2>${t('tab_admin')}</h2><p class="lead">${t('admin_lead')}</p>
    <div class="card" style="margin-bottom:16px"><h3>${t('new_user')}</h3><form id="newUser" class="row"><div class="field"><label for="nu_name">${t('username')}</label><input id="nu_name" pattern="[\\w.-]{2,40}" required></div>
      <div class="field"><label for="nu_role">${t('role')}</label><select id="nu_role" class="inline"><option value="user">${t('role_user')}</option><option value="admin">${t('role_admin')}</option></select></div><button class="btn" type="submit" style="align-self:flex-end">${t('create_invite')}</button></form>
      ${lastInvite ? `<p class="small" style="margin:12px 0 4px">${t('invite_created', { u: esc(lastInvite.username) })}</p><div class="token-box">${esc(lastInvite.invite)}</div>` : ''}</div>
    <div class="tablewrap"><table><thead><tr><th>${t('username')}</th><th>${t('role')}</th><th>${t('status')}</th><th>${t('created')}</th><th></th></tr></thead><tbody>${rows || `<tr><td colspan="5">${empty('')}</td></tr>`}</tbody></table></div></div>`;
}
async function reload() { users = await get('/api/admin/users'); draw(); }
function bind() {
  root.addEventListener('submit', async e => { e.preventDefault();
    try { const r = await post('/api/admin/users', { username: $('nu_name').value.trim(), role: $('nu_role').value }); lastInvite = r; await reload(); } catch (err) { toast(err.message, true); } });
  root.addEventListener('click', async e => {
    const inv = e.target.closest('[data-invite]'); if (inv) { try { const r = await post(`/api/admin/users/${inv.dataset.invite}/invite`, {}); lastInvite = { username: users.find(u => u.id === +inv.dataset.invite)?.username, invite: r.invite }; draw(); } catch (err) { toast(err.message, true); } return; }
    const ac = e.target.closest('[data-active]'); if (ac) { try { await patch(`/api/admin/users/${ac.dataset.active}`, { is_active: +ac.dataset.to }); await reload(); } catch (err) { toast(err.message, true); } return; }
    const ro = e.target.closest('[data-role]'); if (ro) { try { await patch(`/api/admin/users/${ro.dataset.role}`, { role: ro.dataset.to }); await reload(); } catch (err) { toast(err.message, true); } } });
}
export async function render(main) {
  if (S.me?.role !== 'admin') { main.innerHTML = `<div class="card err">${t('admin_only')}</div>`; return; }
  if (!root || !main.contains(root)) { main.innerHTML = '<div data-page="admin"></div>'; root = main.firstElementChild; bind(); }
  await reload();
}
