"""Ranking of the candidates (issues #46, #54; redesigned in #169, docs/target-design.md §6). Each criterion has a FIXED
score curve (0–100), so a car's points never depend on which other cars are in the list (min–max reshuffled the order
when one car was added); cost per month and power are scored in percent against an anchor (the current car, else the
candidates' median), which may shift every shown score by the same amount but never changes the order. A car is scored
only when every weighted criterion has a value and its research is complete; the reference car is scored the same way.
The maximum budget excludes cars (switchable). Weights 0–5 come from the questionnaire or are set by hand."""
import json, math

# key: better direction, unit, how the value is obtained (for the explanation). Values live in row['metrics'].
CRITERIA = {
    'cost_month': {'better': 'lower', 'unit': 'eur_month', 'basis': 'Complete TCO over the period ÷ months: fuel, insurance, tax, maintenance, expected and certain repairs, tyres, purchase/sale costs and depreciation. Scored in percent against the current car\'s cost per month (else the median of the candidates): points = 60 − 112·ln(cost ÷ anchor), 0–100 (≈ +10.7 points per 10 % cheaper).'},
    'budget': {'better': 'lower', 'unit': 'eur', 'basis': 'Asking price against your budget: 100 points up to 55 % of the ideal budget, slowly down to 80 at the ideal, then falling faster and faster to 0 at the maximum; above the maximum the car is not ranked (switchable).'},
    'mileage': {'better': 'lower', 'unit': 'km', 'basis': 'Odometer reading: ≤ 50,000 km = 100 points, 150,000 km = 50, ≥ 250,000 km = 0.'},
    'age': {'better': 'lower', 'unit': 'years', 'basis': 'Years since first registration: ≤ 3 years = 100 points, 10 = 50, ≥ 20 = 0.'},
    'reliability': {'better': 'higher', 'unit': 'points', 'basis': 'One value, 0-100: the mean of the slots with a published figure - engine (Autoscore, risk inverted; EngineScope when permitted), HU defects (TÜV-Report against the class average) and breakdowns (ADAC band). A missing slot lowers coverage, never the score; unknown without any slot.'},
    'inspection': {'better': 'lower', 'unit': 'problems', 'basis': 'Checklist items marked PROBLEM at a viewing: none = 100 points, each problem −25; unknown until at least one item was checked.'},
    'power': {'better': 'higher', 'unit': 'ps', 'basis': 'Engine power in percent against the current car (else the median of the candidates): points = 60 + 112·ln(PS ÷ anchor), 0–100.'},
    'safety': {'better': 'higher', 'unit': 'stars', 'basis': 'Euro NCAP stars of the generation; a rating from before the stricter 2009 test counts one star less, no ESP one star less: 5 = 100 points, 4 = 70, 3 = 40, 2 = 25, 1 = 10, 0 = 0.'},
    'distance': {'better': 'lower', 'unit': 'km', 'basis': 'Distance from your postcode to the car: ≤ 25 km = 100 points, 100 km = 50, ≥ 200 km = 0.'},
}
SEVERITY_POINTS = {'HIGH': 3, 'HIGH IF APPLICABLE': 1.5, 'MEDIUM': 2, 'LOW-MEDIUM': 1, 'LOW': 0.5}
STATUS_POINTS = {'VERIFIED': 1, 'OFFICIAL FEE LEVEL': 1, 'PRIMARY': 1, 'USER DATA': 1, 'QUOTE': 1, 'ESTIMATED': 0.5}
MAX_WEIGHT = 5

# The questionnaire (issues #19, #54, #64; shortened in #169): best–worst tasks of SIX cars of the same model, equal in
# everything except one advantage each; the person picks the car they would buy first and the one they would buy last.
# The nine criteria sit on a 3 × 3 grid; each task leaves out one row or one column (AG(2,3)), so six tasks show every
# criterion four times and every pair of criteria together at least twice. The three row tasks come first: when their
# answers are already consistent (no criterion picked both first and last) the questionnaire may stop after three
# screens; a final screen shows the weights to confirm or adjust. New task ids (u…) retire earlier answers.
# Score per criterion: (times first − times last) ÷ times answered, −1…+1, mapped to 1–5; never answered = neutral.
# Simulated in tests: the true favourite always gets 5 and the least important 1.
_KEYS = ['cost_month', 'budget', 'mileage', 'age', 'reliability', 'inspection', 'power', 'safety', 'distance']
TASKS = ([{'id': f'u{r + 1}', 'criteria': [_KEYS[i] for i in range(9) if i // 3 != r]} for r in range(3)]
         + [{'id': f'u{c + 4}', 'criteria': [_KEYS[i] for i in range(9) if i % 3 != c]} for c in range(3)])
EARLY_STOP_AFTER = 3  # the row tasks
NEUTRAL_WEIGHT = 3  # a criterion never answered counts the same as any other
MIN_DERIVED = 1  # answers never remove a criterion entirely (simulation: zeros came from noise); by hand 0 is allowed
_T = {x['id']: x['criteria'] for x in TASKS}


def parse_answer(task_id, answer):
    """'best>worst' (criterion keys of that task) → (best, worst), or None when invalid."""
    crit = _T.get(task_id)
    if not crit or not isinstance(answer, str) or answer.count('>') != 1:
        return None
    best, worst = answer.split('>')
    return (best, worst) if best in crit and worst in crit and best != worst else None


def known_answers(answers):
    """Only valid answers to current tasks (answers to retired questionnaires are ignored, never an error when read)."""
    return {k: v for k, v in (answers or {}).items() if isinstance(answers, dict) and parse_answer(k, v)}


def tally(answers):
    """Per criterion: tasks answered that showed it, times picked first, times picked last."""
    out = {k: {'shown': 0, 'best': 0, 'worst': 0} for k in _KEYS}
    for tid, a in known_answers(answers).items():
        best, worst = parse_answer(tid, a)
        for k in _T[tid]:
            out[k]['shown'] += 1
        out[best]['best'] += 1
        out[worst]['worst'] += 1
    return out


def weights_from_answers(answers):
    """Weight 1–5 per criterion: (first − last) ÷ shown, from −1 to +1, mapped linearly (half up) to 0–5, floor 1."""
    w = {k: max(MIN_DERIVED, int(MAX_WEIGHT * ((x['best'] - x['worst']) / x['shown'] + 1) / 2 + 0.5)) if x['shown'] else NEUTRAL_WEIGHT
         for k, x in tally(answers).items()}
    return {k: w.get(k, NEUTRAL_WEIGHT) for k in CRITERIA}


def check_answers(answers):
    if not isinstance(answers, dict):
        raise ValueError('answers must be an object task → "best>worst"')
    for k, v in answers.items():
        if not parse_answer(k, v):
            raise ValueError(f'unknown task or answer: {k}={v} (expected "best>worst" with criteria of that task)')
    return answers


def ranking_state(p):
    """Answers, weights and whether the weights were edited by hand (differ from the answers' weights)."""
    try:
        stored = json.loads(p.get('ranking_answers') or '{}')
    except ValueError:
        stored = {}
    answers = known_answers(stored)
    derived = weights_from_answers(answers)
    try:
        saved = json.loads(p.get('ranking_weights') or 'null')
    except ValueError:
        saved = None
    weights = {k: saved.get(k, derived[k]) for k in CRITERIA} if isinstance(saved, dict) else derived
    return {'answers': answers, 'answered': bool(answers), 'weights': weights, 'tally': tally(answers),
            'derived_weights': derived, 'manual': weights != derived,
            'retired_answers': bool(stored) and not answers}  # answers from an earlier questionnaire: ask again


def weights_from(p):
    return ranking_state(p)['weights']


def curve(points, v):
    """Piecewise-linear score through (value, points) pairs, flat beyond both ends."""
    if v <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if v <= x1:
            return y0 + (y1 - y0) * (v - x0) / (x1 - x0)
    return points[-1][1]


def log_score(v, anchor, sign):
    """Percent against an anchor (#169): 60 at the anchor, ±112 points per natural-log unit (≈ 10.7 per 10 %), 0–100."""
    return min(100.0, max(0.0, 60 + sign * 112 * math.log(v / anchor))) if v and anchor and v > 0 and anchor > 0 else None


def budget_score(price, ideal, top):
    """100 up to 55 % of the ideal, slowly down to 80 at the ideal, then a quadratic (accelerating) fall to 0 at the
    maximum (or at 1.5 × the ideal without one); above the maximum 0 (excluded from the ranking unless switched off)."""
    if price is None or not ideal:
        return None
    if price <= ideal:
        return curve([(0.55 * ideal, 100), (ideal, 80)], price)
    top = top if top and top > ideal else 1.5 * ideal
    return max(0.0, 80 * (1 - ((price - ideal) / (top - ideal)) ** 2))


SAFETY_POINTS = {0: 0, 1: 10, 2: 25, 3: 40, 4: 70, 5: 100}
REFERENCE_SKIPS = ('budget', 'inspection', 'distance')  # criteria that do not apply to the owned reference car


def median(vals):
    vals = sorted(vals)
    n = len(vals)
    return (vals[n // 2] + vals[(n - 1) // 2]) / 2 if vals else None


def score_of(k, m, ctx):
    """Points 0–100 of criterion k for metrics m, or None when the car has no value for it."""
    v = m.get(k)
    if k == 'cost_month':
        return log_score(v, ctx['cost_anchor'], -1)
    if k == 'power':
        return log_score(v, ctx['power_anchor'], +1)
    if k == 'budget':
        return budget_score(v, ctx['ideal'], ctx['max'])
    if k == 'reliability':
        return None if v is None else v  # already 0-100: the mean of the source slots (#356)
    if v is None:
        return None
    if k == 'mileage':
        return curve([(50_000, 100), (150_000, 50), (250_000, 0)], v)
    if k == 'age':
        return curve([(3, 100), (10, 50), (20, 0)], v)
    if k == 'inspection':
        return max(0.0, 100 - 25 * v)
    if k == 'safety':
        return SAFETY_POINTS.get(int(v), 0)
    if k == 'distance':
        return curve([(25, 100), (100, 50), (200, 0)], v)
    return None


FILTERS = {  # preference key → (allowed values, test on the listing row); unknown (NULL) never passes
    'filter_seller': (('DEALER', 'PRIVATE'), lambda r, v: r.get('seller_type') == v),
    'filter_warranty': (('1',), lambda r, v: r.get('warranty') == 1),
    'filter_service_history': (('YES', 'YES_OR_CLAIMED'), lambda r, v: r.get('service_history') == 'YES' or v == 'YES_OR_CLAIMED' and r.get('service_history') == 'CLAIMED'),
    'filter_accident_free': (('YES', 'YES_OR_CLAIMED'), lambda r, v: r.get('accident_free') == 'YES' or v == 'YES_OR_CLAIMED' and r.get('accident_free') == 'CLAIMED'),
    'filter_hu_months': (None, lambda r, v: months_left(r.get('hu_until')) is not None and months_left(r['hu_until']) >= int(v)),
}


def months_left(yyyy_mm, today=None):
    """Whole months from this month to the HU month ('YYYY-MM'); None when unknown."""
    import datetime
    if not yyyy_mm:
        return None
    t = today or datetime.date.today()
    y, m = map(int, yyyy_mm.split('-'))
    return (y - t.year) * 12 + m - t.month


def failed_filter(r, p):
    """The first filter this listing fails, or None."""
    for k, (allowed, ok) in FILTERS.items():
        v = p.get(k)
        if v not in (None, '') and (allowed is None or v in allowed) and not ok(r, v):
            return k[len('filter_'):]
    return None


def rank(rows, weights, p=None):
    """Fixed-curve 0–100 score with a per-criterion explanation; returns the number of ranking candidates. A car without a
    value for a weighted criterion, or with research still missing, is 'not scored yet' and says what is missing."""
    p = p or {}
    cands = [r for r in rows if not r['is_reference'] and r['listing_status'] != 'WITHDRAWN']
    ref = next((r for r in rows if r['is_reference']), None)
    anchor = lambda k: (ref['metrics'].get(k) if ref and ref['metrics'].get(k)
                        else median([r['metrics'][k] for r in cands if r['metrics'].get(k)]))
    ctx = {'cost_anchor': anchor('cost_month'), 'power_anchor': anchor('power'),
           'ideal': p.get('budget_ideal_eur'), 'max': p.get('budget_max_eur')}
    exclude = p.get('exclude_over_max') != 0  # NULL (never set) = exclude
    all_used = {k: w for k, w in weights.items() if k in CRITERIA and w and w > 0}
    for r in rows:
        m = r['metrics']
        research_left = [i['id'] for i in (r.get('research') or []) if i.get('grade') == 'MISSING']
        parts = {k: score_of(k, m, ctx) for k in CRITERIA}
        used = {k: w for k, w in all_used.items() if not (r['is_reference'] and k in REFERENCE_SKIPS)  # an owned car has no asking price, no viewing and no trip (#321)
                and not (k == 'inspection' and m.get('inspection') is None)}  # not inspected yet: scored without it, rescored after the viewing (#323)
        total_w = sum(used.values())
        missing = [k for k in used if parts[k] is None]
        excluded = None if r['is_reference'] else 'over_max' if exclude and r.get('budget_status') == 'over_max' else (
            'filter:' + failed_filter(r, p) if failed_filter(r, p) else None)
        scored = bool(total_w) and not missing and not research_left and r['listing_status'] != 'WITHDRAWN'
        score = round(sum(used[k] * parts[k] for k in used) / total_w, 1) if scored else None
        r.update(score=score, rank=None, excluded=excluded,
                 score_parts={k: round(parts[k]) for k in used if parts[k] is not None},
                 not_scored=None if scored else {'criteria': missing, 'research': research_left},
                 explain=[{'criterion': k, 'value': m.get(k), 'unit': CRITERIA[k]['unit'], 'better': CRITERIA[k]['better'],
                           'weight': weights.get(k, 0), 'score': None if parts[k] is None else round(parts[k]),
                           'contribution': round(used[k] * parts[k] / total_w, 1) if score is not None and k in used else None,
                           'anchor': ctx['cost_anchor'] if k == 'cost_month' else ctx['power_anchor'] if k == 'power' else None,
                           'why_missing': None if parts[k] is not None else ('weight 0' if k not in used else 'no value for this car')}
                          for k in CRITERIA])
    ranked = sorted((r for r in cands if r['score'] is not None and not r['excluded']), key=lambda r: -r['score'])
    for i, r in enumerate(ranked, 1):
        r['rank'] = i
    return len(cands)
