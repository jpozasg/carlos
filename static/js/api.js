// Fetch wrapper. Every call is the same for every theme; a 401 sends the browser to the login page.
export async function get(url) {
  const r = await fetch(url);
  if (r.status === 401) { location.href = '/login'; await new Promise(() => {}); }
  if (!r.ok) throw Error('HTTP ' + r.status + ' · ' + url);
  return r.json();
}
export async function send(method, url, body, ctype = 'application/json') {
  const r = await fetch(url, { method, headers: { 'Content-Type': ctype }, body: ctype === 'application/json' && body != null ? JSON.stringify(body) : body });
  const j = await r.json().catch(() => ({}));
  if (r.status === 401 && !url.startsWith('/api/account/password')) { location.href = '/login'; await new Promise(() => {}); }
  if (!r.ok) throw Error(j.error || 'HTTP ' + r.status);
  return j;
}
export const post = (url, body) => send('POST', url, body);
export const patch = (url, body) => send('PATCH', url, body);
