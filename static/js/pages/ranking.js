// Ranking: the ranked list with the contribution of every criterion, the priorities the questionnaire read from the
// answers (and why), fine-tuning by hand, and the formula. #/ranking?quiz=1 runs the questionnaire in place.
import { S, refreshTco, go, current } from '../app.js';
import { post } from '../api.js';
import { t } from '../i18n.js';
import { esc, num, thumb, carLabel, toast } from '../ui.js';
import { quiz, profileHtml } from '../quiz.js';

let root, timer;
const CRIT = () => Object.keys(S.ranking.criteria);
// eight validated series colours (docs/frontend.md); a ninth criterion gets a neutral colour instead of an undefined, invisible --s9
const critColor = k => { const i = CRIT().indexOf(k); return i >= 0 && i < 8 ? `var(--s${i + 1})` : 'var(--text-3)'; };
async function save(body, msg) {
  try { await post('/api/parameters', body); await refreshTco(); toast(t(msg)); return true; } catch (e) { toast(t('not_saved', { m: e.message }), true); return false; }
}
function draw() {
  const R = S.ranking, cands = S.units.filter(u => u.rank).sort((a, b) => a.rank - b.rank);
  const sliders = CRIT().map(k => `<label for="w-${k}">${t('c_' + k)}</label><input id="w-${k}" type="range" min="0" max="5" step="1" value="${R.weights[k]}" data-weight="${k}"><output for="w-${k}">${R.weights[k]}</output>`).join('');
  const list = cands.map(u => { const ex = (u.explain || []).filter(x => x.contribution);
    const miss = (u.explain || []).filter(x => x.why_missing === 'no value for this car' && x.weight);
    return `<li><span class="rank-pos num">${u.rank}</span><div><a class="rank-car" href="#/listing/${u.id}">${thumb(u, 'sm')}<span>${carLabel(u)}</span></a>
      <div class="contrib" role="img" aria-label="${esc(ex.map(x => `${t('c_' + x.criterion)} ${num(x.contribution, 0)}%`).join(', '))}">${ex.map(x => `<i style="width:${x.contribution}%;background:${critColor(x.criterion)}" data-tip="${esc(t('c_' + x.criterion))}: ${num(x.score, 0)} × ${x.weight} → ${num(x.contribution, 0)}%"></i>`).join('')}</div>
      <div class="small muted">${t('coverage', { n: num(u.coverage * 100, 0) })}${miss.length ? ' · ' + t('missing_criteria', { l: miss.map(x => t('c_' + x.criterion)).join(', ') }) : ''}</div></div>
      <b class="score num${u.coverage < 0.5 ? ' provisional' : ''}" ${u.coverage < 0.5 ? `title="${esc(t('provisional_hint'))}"` : ''}>${num(u.score, 0)}${u.coverage < 0.5 ? '<small>?</small>' : ''}</b></li>`; }).join('');
  const thin = cands.some(u => u.coverage < 0.5);
  const state = !R.answered ? `<div class="callout"><p><b>${t(R.retired_answers ? 'prio_retired_title' : 'prio_none_title')}</b> ${t(R.retired_answers ? 'prio_retired_text' : 'prio_none_text')}</p><a class="btn" href="#/ranking?quiz=1">${t('quiz_start')}</a></div>`
    : R.manual ? `<div class="callout"><p>${t('prio_manual_text')}</p><button class="btn ghost sm" type="button" data-reset>${t('weights_reset')}</button></div>` : '';
  root.innerHTML = `<div class="section"><h2>${t('tab_ranking')}</h2><p class="lead">${t('ranking_lead')}</p>
    <div class="rank-layout">
      <div class="card"><h3>${t('rank_result')} <span class="muted small">${t('candidates_n', { n: R.candidates })}</span></h3>
        ${thin ? `<p class="note small">${t('provisional_note')}</p>` : ''}${cands.length ? `<ol class="rank-list">${list}</ol>` : `<p class="empty">${t('need_two')}</p>`}
        <div class="legend" style="margin-top:12px">${CRIT().map((k, i) => `<span><i class="sw" style="background:${critColor(k)}"></i>${t('c_' + k)}</span>`).join('')}</div></div>
      <div class="card prio"><h3>${t('prio_title')} ${R.manual ? `<span class="tag warn">${t('weights_manual')}</span>` : R.answered ? `<span class="tag good">${t('weights_from_answers')}</span>` : ''}</h3>
        ${state}<p class="small muted" style="margin-top:0">${t('prio_lead')}</p>${profileHtml(R)}
        <div class="row" style="margin-top:14px">${R.answered ? `<a class="btn ghost sm" href="#/ranking?quiz=1">${t('quiz_retake')}</a>` : ''}</div>
        <details class="tune"><summary>${t('tune_title')}</summary><p class="small muted">${t('weights_lead')}</p><div class="weights">${sliders}</div></details></div>
    </div>
    <details class="card formula"><summary><b>${t('formula_title')}</b></summary><p class="small">${esc(t('formula_text'))}</p>
      <div class="tablewrap"><table><thead><tr><th>${t('criterion')}</th><th>${t('better')}</th><th>${t('basis')}</th></tr></thead><tbody>${CRIT().map(k => `<tr><td><b>${t('c_' + k)}</b></td><td>${t('better_' + R.criteria[k].better)}</td><td class="small">${esc(t('cb_' + k))}</td></tr>`).join('')}</tbody></table></div>
      <p class="small muted">${t('quiz_method')}</p></details></div>`;
}
function runQuiz() {
  root.innerHTML = `<div class="section quiz-page"><h2>${t('quiz_title')}</h2><p class="lead">${t('quiz_lead')}</p><div id="qzHost"></div></div>`;
  quiz(root.querySelector('#qzHost'), { tasks: S.ranking.tasks, answers: S.ranking.answers, params: S.p,
    onCancel: () => go('ranking'),
    onDone: async answers => { if (await save({ ranking_answers: answers, ranking_weights: null }, 'answers_saved')) go('ranking'); } });
}
function bind() {
  root.addEventListener('input', e => { const k = e.target.dataset.weight; if (!k) return;
    e.target.nextElementSibling.textContent = e.target.value; clearTimeout(timer);
    const w = { ...S.ranking.weights, [k]: +e.target.value }; S.ranking.weights = w;
    timer = setTimeout(async () => { if (await save({ ranking_weights: w }, 'weights_saved')) { const open = root.querySelector('.tune')?.open; draw(); if (open) root.querySelector('.tune').open = true; } }, 500); });
  root.addEventListener('click', async e => { if (e.target.closest('[data-reset]') && await save({ ranking_weights: null }, 'weights_saved')) draw(); });
}
export async function render(main, r = current()) {
  if (!root || !main.contains(root)) { main.innerHTML = '<div data-page="ranking"></div>'; root = main.firstElementChild; bind(); }
  if (r.q.quiz) runQuiz(); else draw();
}
