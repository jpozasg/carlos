// The ranking questionnaire (issues #19, #54, #64): eight best–worst tasks. Each task shows four cars of the same model that are
// equal except for one advantage each; the person taps the car they would buy first, then the one they would buy
// last. Numbers are concrete and follow the account's budget and period. Used by the Ranking page and the setup
// wizard; the scoring lives in carlos/ranking.py (TASKS, tally, weights_from_answers).
import { t } from './i18n.js';
import { esc, euro, num } from './ui.js';

const shuffle = a => { a = [...a]; for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };

// [ordinary value, advantage] per criterion; only the advantage differs between the cars of a task
export function attributes(p = {}) {
  const y = new Date().getFullYear(), price = Math.max(2000, Math.round((p.budget_ideal_eur || 8000) / 100) * 100);
  return {
    cost_month: [euro(330) + t('per_month'), euro(290) + t('per_month')], cash_now: [euro(price), euro(price - 1500)],
    mileage: [num(150000, 0) + ' km', num(100000, 0) + ' km'], age: [String(y - 13), String(y - 9)], power: ['75 PS', '115 PS'],
    reliability: [t('bw_rel_base'), t('bw_rel_adv')], inspection: [t('bw_insp_base'), t('bw_insp_adv')],
    confidence: [t('bw_conf_base'), t('bw_conf_adv')],
  };
}

// tasks: [{id, criteria: [4 keys]}] from the API; answers: {taskId: 'best>worst'}
export function quiz(el, { tasks, answers = {}, params = {}, onDone, onCancel, doneLabel }) {
  const ans = { ...answers }, A = attributes(params), years = params.ownership_years || 4;
  const order = shuffle(tasks).map(x => ({ ...x, cars: shuffle(x.criteria) }));  // cars[n] = the criterion car n is better on
  let i = Math.max(0, order.findIndex(x => !ans[x.id])), pick = null, advance;
  const draw = focus => {
    const x = order[i], [best, worst] = (ans[x.id] || '').split('>'), last = i === order.length - 1, done = !!ans[x.id];
    const phase = done ? 'done' : pick ? 'worst' : 'best';
    const badge = k => k === best || k === pick ? t('bw_first') : k === worst ? t('bw_last') : done ? t('bw_second') : '';
    el.innerHTML = `<div class="qz" data-qz>
      <div class="qz-top"><span class="qz-count num">${t('quiz_progress', { i: i + 1, n: order.length })}</span>
        <div class="qz-bar" role="progressbar" aria-valuemin="0" aria-valuemax="${order.length}" aria-valuenow="${order.filter(o => ans[o.id]).length}" aria-label="${esc(t('quiz_progress_aria'))}"><i style="width:${order.filter(o => ans[o.id]).length / order.length * 100}%"></i></div>
        ${onCancel ? `<button class="linkbtn" type="button" data-qz-cancel>${t('quiz_cancel')}</button>` : ''}</div>
      <p class="bw-frame small muted">${t('bw_frame')}</p>
      <h3 class="qz-title" aria-live="polite">${t('bw_ask_' + phase)}</h3>
      <div class="bw" role="group" aria-label="${esc(t('bw_cars'))}">${x.cars.map((k, n) => { const b = badge(k);
        return `<button type="button" class="bw-car${k === best || k === pick ? ' first' : k === worst ? ' last' : ''}" data-car="${k}" aria-pressed="${!!b}">
          <span class="bw-h"><b>${t('car_letter', { l: 'ABCD'[n] })}</b>${b ? `<span class="bw-badge">${b}</span>` : `<span class="k num" aria-hidden="true">${n + 1}</span>`}</span>
          ${x.criteria.map(c => `<span class="bw-row${c === k ? ' adv' : ''}"><small>${esc(t('bw_row_' + c))}</small><span>${esc(A[c][c === k ? 1 : 0])}</span></span>`).join('')}</button>`; }).join('')}</div>
      <p class="small muted bw-note">${x.criteria.includes('cost_month') ? esc(t('bw_month_note', { v: euro(40 * 12 * years), y: years })) + ' ' : ''}${t('bw_equal')}</p>
      <div class="qz-nav"><button class="btn ghost" type="button" data-qz-back ${i ? '' : 'disabled'}>${t('back')}</button>
        <button class="linkbtn" type="button" data-qz-skip>${t('bw_skip')}</button><span class="spacer"></span>
        <button class="btn" type="button" data-qz-next ${done ? '' : 'disabled'}>${last ? esc(doneLabel || t('quiz_finish')) : t('next')}</button></div></div>`;
    if (focus) el.querySelector(phase === 'worst' ? '.bw-car:not(.first)' : '.bw-car')?.focus({ preventScroll: true });
  };
  const go = d => { clearTimeout(advance); pick = null; i += d; if (i >= order.length) { i = order.length - 1; onDone(ans); return; } draw(true); };
  const choose = k => {
    const x = order[i];
    if (ans[x.id] || k === pick) { delete ans[x.id]; pick = null; draw(true); return; }  // tapping again starts the task over
    if (!pick) { pick = k; draw(true); return; }
    ans[x.id] = `${pick}>${k}`; pick = null; draw(false);
    if (i < order.length - 1) advance = setTimeout(() => go(1), 650);  // a moment to see the full order before moving on
  };
  el.onclick = e => {
    const car = e.target.closest('[data-car]'); if (car) { choose(car.dataset.car); return; }
    if (e.target.closest('[data-qz-next]')) go(1);
    else if (e.target.closest('[data-qz-back]') && i) go(-1);
    else if (e.target.closest('[data-qz-skip]')) { delete ans[order[i].id]; go(1); }
    else if (e.target.closest('[data-qz-cancel]')) onCancel();
  };
  const onKey = e => { if (!el.isConnected || !el.querySelector('[data-qz]')) { document.removeEventListener('keydown', onKey); return; }
    if (e.altKey || e.ctrlKey || e.metaKey || e.target.matches?.('input,textarea,select')) return;
    if (e.key === 'Enter' && ans[order[i].id] && !e.target.closest?.('button')) { e.preventDefault(); go(1); return; }
    const car = el.querySelectorAll('.bw-car')[+e.key - 1]; if (car) { e.preventDefault(); choose(car.dataset.car); } };
  document.addEventListener('keydown', onKey);
  draw(false);
}

// Per criterion: weight and the plain count behind it, strongest first.
export function profileHtml(R, { explain = true } = {}) {
  const rows = Object.keys(R.criteria).map(k => ({ k, w: R.weights[k], x: R.tally?.[k] || { shown: 0, best: 0, worst: 0 } }))
    .sort((a, b) => b.w - a.w || b.x.best - a.x.best);
  const top = rows.filter(r => r.w >= 4).slice(0, 3).map(r => t('c_' + r.k));
  const head = R.answered && top.length ? `<p class="prof-head">${esc(t('prof_head', { l: top.join(', ') }))}</p>` : '';
  return `${head}<ol class="prof">${rows.map(({ k, w, x }) => `<li class="${w ? '' : 'zero'}"><div class="prof-h"><b>${esc(t('c_' + k))}</b><span class="prof-w num" aria-label="${esc(t('weight_of', { w }))}">${w}<small>/5</small></span></div>
    <div class="prof-bar" aria-hidden="true">${[1, 2, 3, 4, 5].map(n => `<i class="${n <= w ? 'on' : ''}"></i>`).join('')}</div>
    ${explain ? `<p class="prof-why small">${x.shown ? esc(t('tally_line', { s: x.shown, b: x.best, w: x.worst })) : `<span class="muted">${R.answered ? t('tally_none') : esc(t('cb_' + k))}</span>`}</p>` : ''}</li>`).join('')}</ol>`;
}
