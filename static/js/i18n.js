// Languages: EN (default), ES, DE, PL. Strings live in /static/i18n/<lang>.json; fixed database codes are translated
// through the "codes" block of the same file; free text from the database is never translated.
export const LANGS = { en: 'en-GB', es: 'es-ES', de: 'de-DE', pl: 'pl-PL' };
let lang = 'en', dict = {}, en = {};
export const current = () => lang;
export const locale = () => LANGS[lang];
const getJson = async l => { const r = await fetch(`/static/i18n/${l}.json`); if (!r.ok) throw new Error(`${l}.json ${r.status}`); return r.json(); };
// a failing English file throws (app.js shows the error card); a failing other language falls back to English, unsaved
export async function load(l) {
  const want = LANGS[l] ? l : 'en';
  if (!Object.keys(en).length) en = await getJson('en');
  let ok = true;
  dict = want === 'en' ? en : await getJson(want).catch(() => { ok = false; return en; });
  lang = ok ? want : 'en';
  document.documentElement.lang = lang;
  if (ok) try { localStorage.setItem('carlos.lang', lang); } catch (e) {}
}
export function initialLang() {
  try { const v = localStorage.getItem('carlos.lang'); if (LANGS[v]) return v; } catch (e) {}
  const nav = (navigator.language || 'en').slice(0, 2);
  return LANGS[nav] ? nav : 'en';
}
export function t(key, vars = {}) {
  let v = dict[key] ?? en[key] ?? key;
  if (typeof v === 'object' && v !== null) {  // plural forms {one, few?, other}; "few" is the Polish 2–4 form
    const n = vars.n, i = Math.abs(Math.trunc(Number(n)));
    const few = v.few && i % 10 >= 2 && i % 10 <= 4 && (i % 100 < 12 || i % 100 > 14) && Number.isInteger(Number(n));
    v = n === 1 ? v.one : few ? v.few : v.other;
  }
  return String(v).replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? '');
}
// fixed codes (statuses, event kinds, component keys, levels) → translated label; free text passes through
export const tv = v => v == null ? v : ((dict.codes || {})[v] ?? (en.codes || {})[v] ?? v);
export const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
export const comp = k => cap(tv(k));
