// Sources: every source of the account, grouped by what it belongs to, with a text filter.
import { S } from '../app.js';
import { t } from '../i18n.js';
import { esc, empty, qTag, lvlTag, safeUrl } from '../ui.js';

let root, q = '';
function draw() {
  const names = {}; for (const u of S.units) names['v' + u.vehicle_id] = `${u.make} ${u.model} ${u.trim ?? ''}`;
  const name = s => s.vehicle_id ? (names['v' + s.vehicle_id] ?? t('variant') + ' #' + s.vehicle_id) : s.engine_id ? t('engine') + ' #' + s.engine_id : s.generation_id ? t('generation') + ' #' + s.generation_id : t('general');
  const lvl = s => s.vehicle_id ? 'variant' : s.engine_id ? 'engine' : s.generation_id ? 'generation' : 'shared';
  const match = s => !q || [s.title, s.url, s.supports, s.limitations, s.source_type].join(' ').toLowerCase().includes(q);
  const groups = {}; for (const s of S.sources.filter(match)) (groups[name(s)] ??= []).push(s);
  const html = Object.entries(groups).map(([g, ss]) => `<div class="card" style="margin-bottom:16px"><h3>${esc(g)} ${lvlTag(lvl(ss[0]))} <span class="muted small">${ss.length}</span></h3>${ss.map(s => `<div class="src"><div class="src-title">${qTag(s.quality, t('quality_hint', { q: s.quality ?? t('unrated') }))}<span>${esc(s.title)}</span></div>
      ${s.url ? `<a href="${safeUrl(s.url)}" target="_blank" rel="noopener">${esc(s.url)}</a>` : `<span class="small muted">${t('no_url')}</span>`}
      ${s.supports ? `<p><b>${t('supports')}:</b> ${esc(s.supports)}</p>` : ''}${s.limitations ? `<p><b>${t('limitations')}:</b> ${esc(s.limitations)}</p>` : ''}
      <p class="muted small">${esc(s.source_type ?? '')}${s.accessed_date ? ' · ' + t('accessed', { d: esc(s.accessed_date) }) : ''} · id ${s.id}</p></div>`).join('')}</div>`).join('');
  root.querySelector('#srcList').innerHTML = html || empty(t('no_match'));
}
export async function render(main) {
  if (!root || !main.contains(root)) {
    main.innerHTML = `<div data-page="sources"><div class="section"><h2>${t('sources_title')}</h2><p class="lead">${t('sources_lead')}</p>
      <input class="search" type="search" placeholder="${t('filter_sources')}" aria-label="${t('filter_sources')}"><div id="srcList"></div></div></div>`;
    root = main.firstElementChild; root.querySelector('.search').addEventListener('input', e => { q = e.target.value.toLowerCase(); draw(); });
  }
  draw();
}
