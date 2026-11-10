// Sources: every source of the account, grouped by what it belongs to, with a text filter.
import { S } from '../app.js';
import { t } from '../i18n.js';
import { esc, empty, qTag, lvlTag, safeUrl, modelsHref } from '../ui.js';

// The five fixed reliability sources behind the score (plan #351 section 1): name, quality, level, terms, link pattern.
const REL_SOURCES = [
  ['Autoscore', 'C', 'engine', 'src_terms_own_use', 'https://autoscore.pro/engine/<slug>'],
  ['EngineScope', 'C', 'engine', 'src_terms_link_only', 'https://enginescope.gr/engine/<slug>/'],
  ['TÜV-Report', 'B', 'generation', 'src_terms_own_use', 'https://www.tuev-verband.de/pressemitteilungen/tuev-report-<year>'],
  ['ADAC Pannenstatistik', 'B', 'generation', 'src_terms_free', 'https://www.adac.de/rund-ums-fahrzeug/unfall-schaden-panne/adac-pannenstatistik/'],
  ['ADAC Gebrauchtwagen-Info', 'B', 'generation', 'src_terms_free', 'https://assets.adac.de/Autodatenbank/GWInfo/gwNNNN-<make>-<model>-<years>-bericht.pdf'],
];
const relBlock = () => `<div class="card" style="margin-bottom:16px"><h3>${t('src_rel_block')}</h3><p class="small muted">${t('src_rel_lead')}</p><div class="tablewrap"><table><thead><tr><th>${t('source')}</th><th>${t('quality')}</th><th>${t('level')}</th><th>${t('src_rel_terms')}</th><th>${t('src_rel_pattern')}</th></tr></thead><tbody>${REL_SOURCES.map(([n, q, l, terms, url]) =>
  `<tr><td><b>${esc(n)}</b></td><td>${qTag(q, t('quality_hint', { q }))}</td><td>${lvlTag(l)}</td><td class="small">${t(terms)}</td><td class="small"><a href="${safeUrl(url.replace(/<.*$/, ''))}" target="_blank" rel="noopener">${esc(url)}</a></td></tr>`).join('')}</tbody></table></div><p class="small muted">${t('src_to_recheck')}</p></div>`;
let root, q = '';
function draw() {
  const names = {}, hrefs = {};
  for (const u of S.units) { names['v' + u.vehicle_id] = `${u.make} ${u.model} ${u.trim ?? ''}`; hrefs['v' + u.vehicle_id] = '#/models/' + u.vehicle_id;
    names['e' + u.engine_id] = `${t('engine')} ${u.engine_code}`; hrefs['e' + u.engine_id] = modelsHref({ engine: u.engine_code });
    names['g' + u.generation_id] = `${u.make} ${u.model} · ${u.generation}`; hrefs['g' + u.generation_id] = modelsHref({ make: u.make, model: u.model }); }
  const key = s => s.vehicle_id ? 'v' + s.vehicle_id : s.engine_id ? 'e' + s.engine_id : s.generation_id ? 'g' + s.generation_id : '';
  const name = s => names[key(s)] ?? (s.vehicle_id ? t('variant') + ' #' + s.vehicle_id : s.engine_id ? t('engine') + ' #' + s.engine_id : s.generation_id ? t('generation') + ' #' + s.generation_id : t('general'));
  const lvl = s => s.vehicle_id ? 'variant' : s.engine_id ? 'engine' : s.generation_id ? 'generation' : 'shared';
  const match = s => !q || [s.title, s.url, s.supports, s.limitations, s.source_type].join(' ').toLowerCase().includes(q);
  const groups = {}; for (const s of S.sources.filter(match)) (groups[name(s)] ??= []).push(s);
  const html = Object.entries(groups).map(([g, ss]) => `<div class="card" style="margin-bottom:16px"><h3>${hrefs[key(ss[0])] ? `<a href="${hrefs[key(ss[0])]}">${esc(g)}</a>` : esc(g)} ${lvlTag(lvl(ss[0]))} <span class="muted small">${ss.length}</span></h3>${ss.map(s => `<div class="src"><div class="src-title">${qTag(s.quality, t('quality_hint', { q: s.quality ?? t('unrated') }))}<span>${esc(s.title)}</span></div>
      ${s.url ? `<a href="${safeUrl(s.url)}" target="_blank" rel="noopener">${esc(s.url)}</a>` : `<span class="small muted">${t('no_url')}</span>`}
      ${s.supports ? `<p><b>${t('supports')}:</b> ${esc(s.supports)}</p>` : ''}${s.limitations ? `<p><b>${t('limitations')}:</b> ${esc(s.limitations)}</p>` : ''}
      <p class="muted small">${esc(s.source_type ?? '')}${s.accessed_date ? ' · ' + t('accessed', { d: esc(s.accessed_date) }) : ''} · id ${s.id}</p></div>`).join('')}</div>`).join('');
  root.querySelector('#srcList').innerHTML = html || empty(t('no_match'));
}
export async function render(main) {
  if (!root || !main.contains(root)) {
    main.innerHTML = `<div data-page="sources"><div class="section"><h2>${t('sources_title')}</h2><p class="lead">${t('sources_lead')}</p>
      ${relBlock()}
      <input class="search" type="search" placeholder="${t('filter_sources')}" aria-label="${t('filter_sources')}"><div id="srcList"></div></div></div>`;
    root = main.firstElementChild; root.querySelector('.search').addEventListener('input', e => { q = e.target.value.toLowerCase(); draw(); });
  }
  draw();
}
