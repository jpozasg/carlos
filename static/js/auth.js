// Sign-in and invite page (/login, /invite/<token>). A module, so it uses the app's i18n files: the same four languages,
// remembered per browser. Every request is caught: a proxy error page or no answer shows a message, never a silent failure.
import { load, initialLang, t } from './i18n.js';
import { busy } from './ui.js';

const $ = id => document.getElementById(id);
const inv = location.pathname.match(/^\/invite\/([\w-]+)$/), f = $('f'), e = $('e');
const NAMES = { en: 'English', es: 'Español', de: 'Deutsch', pl: 'Polski' };

// [status, body]: status 0 when the network fails, body {} when the answer is not JSON (a proxy's 502 page)
async function j(m, u, b) {
  let r;
  try { r = await fetch(u, { method: m, headers: { 'Content-Type': 'application/json' }, body: b ? JSON.stringify(b) : null }); }
  catch (err) { return [0, {}]; }
  return [r.status, await r.json().catch(() => ({}))];
}
// the server's own messages are English: known answers get the page's translated text; any other 4xx keeps the server's
// message; a 5xx, no answer or a non-JSON page (the proxy's 502) gets the unreachable text
const failText = (s, d = {}) => s === 401 ? t('auth_wrong') : s === 429 ? t('auth_locked') : s === 404 ? t('auth_invite_gone')
  : d.error && s >= 400 && s < 500 ? d.error : t('auth_unreachable');

function paint() {
  document.title = t('auth_title');
  $('t').textContent = inv ? t('auth_set_password') : t('auth_sign_in');
  $('tg').textContent = t('tagline');
  $('ul').textContent = t('auth_username');
  $('pl').textContent = inv ? t('auth_new_password') : t('auth_password');
  $('p2l').textContent = t('auth_repeat_password');
  $('b').textContent = inv ? t('auth_save_sign_in') : t('auth_sign_in');
  $('lg').textContent = t('language');
  $('f-src').textContent = t('source_code'); $('f-priv').textContent = t('footer_privacy'); $('f-imp').textContent = t('footer_imprint');
}
async function setLang(l) { await load(l); $('lang').value = l; paint(); }
$('lang').innerHTML = Object.entries(NAMES).map(([c, n]) => `<option value="${c}">${n}</option>`).join('');
$('lang').onchange = () => setLang($('lang').value);

if (inv) { $('u').readOnly = true; $('p').autocomplete = 'new-password'; $('p').minLength = 8; $('p2').required = true; $('p2f').hidden = false; }

(async () => {
  await setLang(initialLang()).catch(() => {});  // no language file: the English text in the page stays, and the invite check still runs
  if (!inv) return;
  const [s, d] = await j('GET', '/api/auth/invite/' + inv[1]);
  if (s === 200) $('u').value = d.username;
  else { e.textContent = failText(s, d); f.querySelectorAll('input,button').forEach(x => x.disabled = true); }
})();

f.onsubmit = ev => {
  ev.preventDefault(); e.textContent = '';
  if (inv && $('p').value !== $('p2').value) {  // checked here, before the request: a typo would otherwise lock the person out until a new link
    $('p2').setAttribute('aria-invalid', 'true'); $('p2').setAttribute('aria-describedby', 'e'); e.textContent = t('auth_mismatch'); $('p2').focus(); return;
  }
  $('p2').removeAttribute('aria-invalid'); $('p2').removeAttribute('aria-describedby');
  busy(ev.submitter || $('b'), async () => {
    const [s, d] = inv ? await j('POST', '/api/auth/invite/' + inv[1], { password: $('p').value })
      : await j('POST', '/api/auth/login', { username: $('u').value, password: $('p').value });
    if (s > 0 && s < 300) location.href = '/'; else e.textContent = failText(s, d);
  });
};
