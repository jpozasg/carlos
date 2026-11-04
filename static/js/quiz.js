// The ranking questionnaire: one everyday scenario per screen, no points shown while answering (issue #13), and the
// profile that explains afterwards which answers produced which weight. Used by the Ranking page and the setup wizard.
import { t } from './i18n.js';
import { esc } from './ui.js';

// questions: [{id, answers: {code: {criterion: points}}}] from the API; answers: {id: code}
export function quiz(el, { questions, answers = {}, onDone, onCancel, doneLabel }) {
  const ans = { ...answers };
  let i = Math.max(0, questions.findIndex(q => !ans[q.id]));
  if (i < 0 || !questions[i]) i = 0;
  const draw = (focusOpt) => {
    const q = questions[i], codes = Object.keys(q.answers), last = i === questions.length - 1;
    el.innerHTML = `<div class="qz" data-qz>
      <div class="qz-top"><span class="qz-count num">${t('quiz_progress', { i: i + 1, n: questions.length })}</span>
        <div class="qz-bar" role="progressbar" aria-valuemin="0" aria-valuemax="${questions.length}" aria-valuenow="${Object.keys(ans).length}" aria-label="${esc(t('quiz_progress_aria'))}"><i style="width:${Object.keys(ans).filter(k => questions.some(x => x.id === k)).length / questions.length * 100}%"></i></div>
        ${onCancel ? `<button class="linkbtn" type="button" data-qz-cancel>${t('quiz_cancel')}</button>` : ''}</div>
      <fieldset class="qz-q"><legend class="qz-title">${esc(t('q_' + q.id))}</legend>
        <div class="qz-opts">${codes.map((a, n) => `<label class="qz-opt"><input type="radio" name="qz-${q.id}" value="${a}" ${ans[q.id] === a ? 'checked' : ''}><span class="k num" aria-hidden="true">${n + 1}</span><span>${esc(t('a_' + q.id + '_' + a))}</span></label>`).join('')}</div></fieldset>
      <div class="qz-nav"><button class="btn ghost" type="button" data-qz-back ${i ? '' : 'disabled'}>${t('back')}</button><span class="qz-hint small muted">${t('quiz_keys')}</span>
        <button class="btn" type="button" data-qz-next ${ans[q.id] ? '' : 'disabled'}>${last ? esc(doneLabel || t('quiz_finish')) : t('next')}</button></div></div>`;
    if (focusOpt) (el.querySelector('.qz-opt input:checked') || el.querySelector('.qz-opt input'))?.focus({ preventScroll: true });
  };
  const next = () => { if (i < questions.length - 1) { i++; draw(true); } else onDone(ans); };
  let advance;
  el.onchange = e => { const r = e.target.closest('.qz-opt input'); if (!r) return;
    ans[questions[i].id] = r.value; el.querySelector('[data-qz-next]').disabled = false;
    clearTimeout(advance); if (i < questions.length - 1) advance = setTimeout(next, 280); };  // short pause shows the choice before moving on
  el.onclick = e => {
    if (e.target.closest('[data-qz-next]')) { clearTimeout(advance); next(); }
    else if (e.target.closest('[data-qz-back]') && i) { clearTimeout(advance); i--; draw(true); }
    else if (e.target.closest('[data-qz-cancel]')) onCancel();
  };
  // number keys pick an answer wherever the focus is, unless the person is typing; the listener ends with the quiz
  const onKey = e => { if (!el.isConnected || !el.querySelector('[data-qz]')) { document.removeEventListener('keydown', onKey); return; }
    const n = +e.key; if (!n || e.altKey || e.ctrlKey || e.metaKey || e.target.matches?.('input:not([type=radio]),textarea,select')) return;
    const opt = el.querySelectorAll('.qz-opt input')[n - 1]; if (opt) { opt.checked = true; opt.focus({ preventScroll: true }); opt.dispatchEvent(new Event('change', { bubbles: true })); } };
  document.addEventListener('keydown', onKey);
  el.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.matches('.qz-opt input') && ans[questions[i].id]) { e.preventDefault(); clearTimeout(advance); next(); } });
  draw(true);
}

// Which answers fed each criterion: [{criterion, weight, because: [answer text]}], strongest first.
export function profile(R, answers = R.answers || {}) {
  return Object.keys(R.criteria).map(k => ({ criterion: k, weight: R.weights[k],
    because: R.questions.filter(q => answers[q.id] && q.answers[answers[q.id]]?.[k]).map(q => t('a_' + q.id + '_' + answers[q.id])) }))
    .sort((a, b) => b.weight - a.weight || b.because.length - a.because.length);
}

export function profileHtml(R, { explain = true } = {}) {
  const rows = profile(R);
  return `<ol class="prof">${rows.map(r => `<li class="${r.weight ? '' : 'zero'}"><div class="prof-h"><b>${esc(t('c_' + r.criterion))}</b><span class="prof-w num" aria-label="${esc(t('weight_of', { w: r.weight }))}">${r.weight}<small>/5</small></span></div>
    <div class="prof-bar" aria-hidden="true">${[1, 2, 3, 4, 5].map(n => `<i class="${n <= r.weight ? 'on' : ''}"></i>`).join('')}</div>
    ${explain ? `<p class="prof-why small">${r.because.length ? `${t('because_you')} ${r.because.map(b => `<q>${esc(b)}</q>`).join(' · ')}` : `<span class="muted">${R.answered ? t('because_none') : esc(t('cb_' + r.criterion))}</span>`}</p>` : ''}</li>`).join('')}</ol>`;
}
