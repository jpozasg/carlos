// Ranking: the questionnaire that derives the weights, the weights themselves (editable), the ranked list with the
// contribution of every criterion, and the explanation of the formula.
import { S, refreshTco } from '../app.js';
import { post } from '../api.js';
import { t } from '../i18n.js';
import { esc, num, thumb, carLabel, toast, PEND } from '../ui.js';

let root, timer;
const CRIT = () => Object.keys(S.ranking.criteria);
async function save(body, msg) {
  try { await post('/api/parameters', body); await refreshTco(); toast(t(msg)); draw(); } catch (e) { toast(t('not_saved', { m: e.message }), true); }
}
function draw() {
  const R = S.ranking, cands = S.units.filter(u => u.rank).sort((a, b) => a.rank - b.rank);
  const quiz = R.questions.map(q => `<div class="q-item"><div class="q-title">${esc(t('q_' + q.id))}</div><div class="opts">${Object.keys(q.answers).map(a => `<label><input type="radio" name="q-${q.id}" value="${a}" ${R.answers[q.id] === a ? 'checked' : ''} data-answer="${q.id}"><span>${esc(t('a_' + q.id + '_' + a))}<span class="small muted"> · ${Object.entries(q.answers[a]).map(([k, v]) => `${t('c_' + k)} +${v}`).join(', ') || t('a_nothing')}</span></span></label>`).join('')}</div></div>`).join('');
  const sliders = CRIT().map(k => `<label for="w-${k}">${t('c_' + k)}<span class="small muted" style="display:block">${t('cb_' + k)}</span></label><input id="w-${k}" type="range" min="0" max="5" step="1" value="${R.weights[k]}" data-weight="${k}"><output for="w-${k}">${R.weights[k]}</output>`).join('');
  const list = cands.map(u => { const ex = (u.explain || []).filter(x => x.contribution);
    return `<li><span class="rank-pos">${u.rank}</span><div><a href="#/listing/${u.id}" style="font-weight:600;text-decoration:none">${thumb(u, 'sm')} ${carLabel(u)}</a>
      <div class="contrib" title="${ex.map(x => `${t('c_' + x.criterion)} ${num(x.contribution, 0)}%`).join(' · ')}">${ex.map(x => `<i style="width:${x.contribution}%;background:var(--s${CRIT().indexOf(x.criterion) + 1})" data-tip="${esc(t('c_' + x.criterion))}: ${num(x.score, 0)} × ${x.weight} → ${num(x.contribution, 0)}%"></i>`).join('')}</div>
      <div class="small muted">${t('coverage', { n: num(u.coverage * 100, 0) })}${u.explain?.some(x => x.why_missing === 'no value for this car' && x.weight) ? ' · ' + t('missing_criteria', { l: u.explain.filter(x => x.why_missing === 'no value for this car' && x.weight).map(x => t('c_' + x.criterion)).join(', ') }) : ''}</div></div>
      <b class="score">${num(u.score, 0)}</b></li>`; }).join('');
  root.innerHTML = `<div class="section"><h2>${t('tab_ranking')}</h2><p class="lead">${t('ranking_lead')}</p>
    <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(320px,1fr))">
      <div class="card"><h3>${t('rank_result')} <span class="muted small">${t('candidates_n', { n: R.candidates })}</span></h3>
        ${cands.length ? `<ol class="rank-list">${list}</ol>` : `<p class="empty">${t('need_two')}</p>`}
        <div class="legend" style="margin-top:12px">${CRIT().map((k, i) => `<span><i class="sw" style="background:var(--s${i + 1})"></i>${t('c_' + k)}</span>`).join('')}</div></div>
      <div class="card"><h3>${t('quiz_title')}</h3><p class="small muted" style="margin-top:0">${t('quiz_lead')}</p><div class="quiz">${quiz}</div></div>
      <div class="card"><h3>${t('weights')} ${R.manual ? `<span class="tag warn">${t('weights_manual')}</span>` : `<span class="tag good">${t('weights_from_answers')}</span>`}</h3>
        <p class="small muted" style="margin-top:0">${t('weights_lead')}</p><div class="weights">${sliders}</div>
        ${R.manual ? `<button class="btn ghost sm" type="button" data-reset style="margin-top:10px">${t('weights_reset')}</button>` : ''}</div>
      <div class="card span2"><h3>${t('formula_title')}</h3><p class="small">${esc(t('formula_text'))}</p>
        <div class="tablewrap"><table><thead><tr><th>${t('criterion')}</th><th>${t('better')}</th><th>${t('basis')}</th></tr></thead><tbody>${CRIT().map(k => `<tr><td><b>${t('c_' + k)}</b></td><td>${t('better_' + R.criteria[k].better)}</td><td class="small">${esc(t('cb_' + k))}</td></tr>`).join('')}</tbody></table></div></div>
    </div></div>`;
}
function bind() {
  root.addEventListener('change', e => {
    const a = e.target.closest('[data-answer]'); if (a) { const answers = { ...S.ranking.answers, [a.dataset.answer]: a.value }; save({ ranking_answers: answers, ranking_weights: null }, 'answers_saved'); } });
  root.addEventListener('input', e => { const k = e.target.dataset.weight; if (!k) return;
    e.target.nextElementSibling.textContent = e.target.value; clearTimeout(timer);
    const w = { ...S.ranking.weights, [k]: +e.target.value }; S.ranking.weights = w; timer = setTimeout(() => save({ ranking_weights: w }, 'weights_saved'), 500); });
  root.addEventListener('click', e => { if (e.target.closest('[data-reset]')) save({ ranking_weights: null }, 'weights_saved'); });
}
export async function render(main) {
  if (!root || !main.contains(root)) { main.innerHTML = '<div data-page="ranking"></div>'; root = main.firstElementChild; bind(); }
  draw();
}
