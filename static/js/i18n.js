// Languages: EN (default), ES, DE, PL. Strings live in /static/i18n/<lang>.json; fixed database codes are translated
// through the "codes" block of the same file; free text from the database is never translated.
export const LANGS = { en: 'en-GB', es: 'es-ES', de: 'de-DE', pl: 'pl-PL' };
let lang = 'en', dict = {}, en = {};
export const current = () => lang;
export const locale = () => LANGS[lang];
export async function load(l) {
  lang = LANGS[l] ? l : 'en';
  if (!Object.keys(en).length) en = await (await fetch('/static/i18n/en.json')).json();
  dict = lang === 'en' ? en : await (await fetch(`/static/i18n/${lang}.json`)).json();
  document.documentElement.lang = lang;
  try { localStorage.setItem('carlos.lang', lang); } catch (e) {}
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
