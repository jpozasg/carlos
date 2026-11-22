// Ranking: the ranked list with the contribution of every criterion, the priorities the questionnaire read from the
// answers (and why), fine-tuning by hand, and the formula. #/ranking?quiz=1 runs the questionnaire in place.
import { S, refreshTco, go, current } from '../app.js';
import { post } from '../api.js';
import { t, locale } from '../i18n.js';
import { esc, num, thumb, carLabel, toast, critColor as colorOf, notScoredTxt } from '../ui.js';
import { quiz, profileHtml } from '../quiz.js';

let root, timer, base = null;  // base: the saved weights before the current run of slider moves
const CRIT = () => Object.keys(S.ranking.criteria);
const critColor = k => colorOf(k, CRIT());
async function save(body, msg) {
  try { await post('/api/parameters', body); await refreshTco(); toast(t(msg)); return true; } catch (e) { toast(t('not_saved', { m: e.message }), true); return false; }
}
// one sentence per car: the two criteria with the highest weight, and how many criteria have data for this car
function whyTxt(u) {
  const ex = u.explain || [], n = ex.filter(x => x.score != null).length, m = CRIT().length;
  const top = ex.filter(x => x.weight > 0).sort((a, b) => b.weight - a.weight).slice(0, 2).map(x => t('c_' + x.criterion));
  return top.length ? t('rank_why', { top: new Intl.ListFormat(locale(), { style: 'long', type: 'conjunction' }).format(top), n, m }) : t('rank_cov', { n, m });
}
function results() {
  const R = S.ranking, cands = S.units.filter(u => u.rank).sort((a, b) => a.rank - b.rank);
  // the owner's car is scored the same way (issue #72) and listed at its score, without a rank
  const ref = S.units.find(u => u.is_reference && u.score != null);
  const rows = ref ? [...cands.filter(u => u.score >= ref.score), ref, ...cands.filter(u => u.score < ref.score)] : cands;
  const list = rows.map(u => { const ex = (u.explain || []).filter(x => x.contribution);
    return `<li${u.is_reference ? ' class="is-ref"' : ''}><span class="rank-pos num">${u.is_reference ? '–' : u.rank}</span><div><a class="rank-car" href="#/listing/${u.id}">${thumb(u, 'sm')}<span>${carLabel(u)}${u.is_reference ? ` <span class="tag ref">${t('your_car')}</span>` : ''}</span></a>
      <div class="contrib" role="img" aria-label="${esc(ex.map(x => `${t('c_' + x.criterion)} ${num(x.contribution, 0)}%`).join(', '))}">${ex.map(x => `<i data-style="width:${x.contribution}%;background:${critColor(x.criterion)}" data-tip="${esc(t('c_' + x.criterion))}: ${num(x.score, 0)} × ${x.weight} → ${num(x.contribution, 0)}%"></i>`).join('')}</div>
      <p class="why small muted">${esc(whyTxt(u))}</p>
      </div>
      <b class="score num">${num(u.score, 0)}</b></li>`; }).join('');
  const unscored = S.units.filter(u => !u.is_reference && u.listing_status !== 'WITHDRAWN' && (u.score == null || u.excluded));
  const thin = unscored.length > 0;
  return `<h3>${t('rank_result')} <span class="muted small">${t('candidates_n', { n: R.candidates })}</span></h3>
        ${thin ? `<details class="note small"><summary>${t('ns_title', { n: unscored.length })}</summary><ul>${unscored.map(u => `<li><a href="#/listing/${u.id}">${carLabel(u)}</a>: ${esc(notScoredTxt(u))}</li>`).join('')}</ul></details>` : ''}${cands.length ? `<ol class="rank-list">${list}</ol>` : `<p class="empty">${t('need_two')}</p>`}
        <div class="legend mt12">${CRIT().map((k, i) => `<span><i class="sw" data-style="background:${critColor(k)}"></i>${t('c_' + k)}</span>`).join('')}</div>`;
}
function prioHead() {
  const R = S.ranking;
  const state = !R.answered ? `<div class="callout"><p><b>${t(R.retired_answers ? 'prio_retired_title' : 'prio_none_title')}</b> ${t(R.retired_answers ? 'prio_retired_text' : 'prio_none_text')}</p><a class="btn" href="#/ranking?quiz=1">${t('quiz_start')}</a></div>`
    : R.manual ? `<div class="callout"><p>${t('prio_manual_text')}</p><button class="btn ghost sm" type="button" data-reset>${t('weights_reset')}</button></div>` : '';
  return `<h3>${t('prio_title')} ${R.manual ? `<span class="tag warn">${t('weights_manual')}</span>` : R.answered ? `<span class="tag good">${t('weights_from_answers')}</span>` : ''}</h3>
        ${state}<p class="small muted mt0">${t('prio_lead')}</p>${profileHtml(R)}
        <div class="row mt14">${R.answered ? `<a class="btn ghost sm" href="#/ranking?quiz=1">${t('quiz_retake')}</a>` : ''}</div>`;
}
function draw() {
  const R = S.ranking;
  const sliders = CRIT().map(k => `<label for="w-${k}">${t('c_' + k)}</label><input id="w-${k}" type="range" min="0" max="5" step="1" value="${R.weights[k]}" data-weight="${k}"><output for="w-${k}">${R.weights[k]}</output>`).join('');
  root.innerHTML = `<div class="section"><h2>${t('tab_ranking')}</h2><p class="lead">${t('ranking_lead')}</p>
    <div class="rank-layout">
      <div class="card rank-result">${results()}</div>
      <div class="card prio"><div class="prio-head">${prioHead()}</div>
        <details class="tune"><summary>${t('tune_title')}</summary><p class="small muted">${t('weights_lead')}</p><div class="weights">${sliders}</div><p class="small wmsg" role="status"></p></details></div>
    </div>
    <details class="card formula"><summary><b>${t('formula_title')}</b></summary><p class="small">${esc(t('formula_text'))}</p>
      <div class="tablewrap"><table><thead><tr><th>${t('criterion')}</th><th>${t('better')}</th><th>${t('basis')}</th></tr></thead><tbody>${CRIT().map(k => `<tr><td><b>${t('c_' + k)}</b></td><td>${t('better_' + R.criteria[k].better)}</td><td class="small">${esc(t('cb_' + k))}</td></tr>`).join('')}</tbody></table></div>
      <p class="small">${t('rel_ranking_note')}</p><p class="small muted">${t('quiz_method')}</p></details></div>`;
}
// after a saved weight change: the list and the priority head change, the sliders stay mounted (no lost focus or drag)
function update() { if (!root.querySelector('.rank-result')) return;  // the user left the page meanwhile
  root.querySelector('.rank-result').innerHTML = results(); root.querySelector('.prio-head').innerHTML = prioHead(); }
// saved 500 ms after the last move; a failed save puts the server's weights back on the sliders with a message
async function sendWeights() {
  const sent = S.ranking.weights, from = base; base = null;
  try { await post('/api/parameters', { ranking_weights: sent }); }
  catch (e) {
    S.ranking.weights = from;
    for (const k of Object.keys(from)) { const el = root.querySelector(`[data-weight="${k}"]`); if (el) { el.value = from[k]; el.nextElementSibling.textContent = from[k]; } }
    const m = t('not_saved', { m: e.message }); if (root.querySelector('.wmsg')) root.querySelector('.wmsg').textContent = m; toast(m, true); return; }
  if (root.querySelector('.wmsg')) root.querySelector('.wmsg').textContent = ''; toast(t('weights_saved')); await refreshTco(); update();
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
    base = base || S.ranking.weights;  // the weights the server holds: restored if the save fails
    S.ranking.weights = { ...S.ranking.weights, [k]: +e.target.value };
    timer = setTimeout(sendWeights, 500); });
  root.addEventListener('click', async e => { if (e.target.closest('[data-reset]') && await save({ ranking_weights: null }, 'weights_saved')) draw(); });
}
export async function render(main, r = current()) {
  if (!root || !main.contains(root)) { main.innerHTML = '<div data-page="ranking"></div>'; root = main.firstElementChild; bind(); }
  if (r.q.quiz) runQuiz(); else draw();
}
