"""Ranking of the candidates (issue #46). Nine criteria that do not overlap: no metric appears in two of them.
Each criterion is min–max normalised among the candidates (best = 100) and combined with weights 0–5. The weights
come from a fixed questionnaire (answers → points per criterion) or are set by hand. Missing data lowers the
coverage of a car; it never scores 0. The formula and the objectivity rules are documented in docs/ranking.md."""
import json

# key: better direction, unit, how the value is obtained (for the explanation). Values live in row['metrics'].
CRITERIA = {
    'cost_month': {'better': 'lower', 'unit': 'eur_month', 'basis': 'Complete TCO over the period ÷ months: fuel, insurance, tax, maintenance, expected and certain repairs, tyres, purchase/sale costs and depreciation. Unknown while any component is missing.'},
    'cash_now': {'better': 'lower', 'unit': 'eur', 'basis': 'Asking price plus the purchase costs of this car (registration, plates, pre-purchase check).'},
    'mileage': {'better': 'lower', 'unit': 'km', 'basis': 'Odometer reading from the listing (the less favourable figure when the listing contradicts itself).'},
    'age': {'better': 'lower', 'unit': 'years', 'basis': 'Years since first registration.'},
    'reliability': {'better': 'lower', 'unit': 'points', 'basis': 'Severity points of the documented watch points of the variant, its engine and its generation: HIGH 3, HIGH IF APPLICABLE 1.5, MEDIUM 2, LOW-MEDIUM 1, LOW 0.5. Research must follow the protocol (same sources for every car) or this is biased by research depth.'},
    'inspection': {'better': 'lower', 'unit': 'problems', 'basis': 'Checklist items marked PROBLEM at a viewing; unknown until at least one item was checked.'},
    'power': {'better': 'higher', 'unit': 'ps', 'basis': 'Engine power in PS.'},
    'simplicity': {'better': 'higher', 'unit': 'points', 'basis': 'Mechanical simplicity from the engine and variant data: naturally aspirated +1, port injection +1, timing chain +1 (dry belt +0.5, wet belt 0), manual gearbox +1. Unknown while any of the four fields is unknown.'},
    'confidence': {'better': 'higher', 'unit': 'percent', 'basis': 'Average evidence quality of the rows behind the costs (consumption, insurance, tax, maintenance, risks, tyres, valuation): status VERIFIED/official/primary 1, ESTIMATED 0.5, else 0; source quality A 1, B 0.8, C 0.5, D 0.3, none 0.3.'},
}
SEVERITY_POINTS = {'HIGH': 3, 'HIGH IF APPLICABLE': 1.5, 'MEDIUM': 2, 'LOW-MEDIUM': 1, 'LOW': 0.5}
STATUS_POINTS = {'VERIFIED': 1, 'OFFICIAL FEE LEVEL': 1, 'PRIMARY': 1, 'USER DATA': 1, 'QUOTE': 1, 'ESTIMATED': 0.5}
QUALITY_POINTS = {'A': 1, 'B': 0.8, 'C': 0.5, 'D': 0.3, None: 0.3}
MAX_WEIGHT = 5

# The questionnaire (issue #13): everyday scenarios instead of "how important is X". Each answer adds points to one or
# more criteria; every criterion is fed by at least two questions so one answer never decides it. Per criterion the
# points are divided by the most that criterion could get from the questions answered (0–1), and the strongest
# preference is scaled to 5. Ids only here; the UI translates. Mapping and reasoning: docs/ranking.md.
QUESTIONS = [
    {'id': 'windfall', 'answers': {'cushion': {'cash_now': 2, 'reliability': 1}, 'car_fund': {'mileage': 1, 'age': 1},
                                   'invest': {'cost_month': 2}, 'treat': {'power': 1}}},
    {'id': 'no_start', 'answers': {'toolbox': {'simplicity': 2}, 'call': {'reliability': 1},
                                   'nightmare': {'reliability': 3, 'confidence': 1}, 'shrug': {}}},
    {'id': 'listing_eye', 'answers': {'price': {'cash_now': 2}, 'km_year': {'mileage': 2, 'age': 1},
                                      'history': {'confidence': 1, 'reliability': 1, 'inspection': 1}, 'engine': {'simplicity': 1, 'power': 1}}},
    {'id': 'twins', 'answers': {'cheaper': {'cash_now': 3}, 'fewer_km': {'mileage': 3},
                                'per_month': {'cost_month': 3}}},
    {'id': 'old_gem', 'answers': {'condition': {'inspection': 2}, 'if_cheap': {'cash_now': 1, 'age': 1},
                                  'no_old': {'age': 3}}},
    {'id': 'motorway', 'answers': {'surge': {'power': 3}, 'manage': {'power': 1}, 'patient': {'cost_month': 1}}},
    {'id': 'gadgets', 'answers': {'progress': {'power': 1}, 'breakable': {'simplicity': 3, 'reliability': 1},
                                  'indifferent': {}}},
    {'id': 'oil_stain', 'answers': {'walk': {'inspection': 3, 'reliability': 1}, 'haggle': {'inspection': 1, 'cash_now': 1},
                                    'workshop': {'inspection': 2, 'confidence': 1}, 'normal': {}}},
    {'id': 'friend_tip', 'answers': {'statistics': {'confidence': 2, 'reliability': 1}, 'trust': {}, 'see_one': {'inspection': 2}}},
    {'id': 'budget_shape', 'answers': {'monthly_tight': {'cost_month': 3}, 'savings_thin': {'cash_now': 3},
                                       'relaxed': {}}},
    {'id': 'five_years', 'answers': {'no_surprises': {'reliability': 2, 'mileage': 1, 'age': 1}, 'resell': {'cost_month': 2, 'mileage': 1},
                                     'used_up': {'cash_now': 1, 'cost_month': 1}, 'still_fun': {'power': 2}}},
    {'id': 'two_quotes', 'answers': {'cheaper_guess': {'cost_month': 2}, 'documented': {'confidence': 2, 'cost_month': 1},
                                     'dig_deeper': {'confidence': 1, 'inspection': 1}}},
]
NEUTRAL_WEIGHT = 3  # before any answer every criterion counts the same
_Q = {q['id']: q['answers'] for q in QUESTIONS}


def known_answers(answers):
    """Only answers to current questions (answers to retired questions are ignored, never an error when read)."""
    return {k: v for k, v in (answers or {}).items() if k in _Q and v in _Q[k]}


def profile_from_answers(answers):
    """Per criterion: points earned and the most attainable from the questions answered."""
    answers = known_answers(answers)
    got, best = {k: 0 for k in CRITERIA}, {k: 0 for k in CRITERIA}
    for qid, a in answers.items():
        for k, pts in _Q[qid][a].items():
            got[k] += pts
        for k in CRITERIA:
            best[k] += max(opt.get(k, 0) for opt in _Q[qid].values())
    return got, best


def weights_from_answers(answers):
    """Weights 0–5: share of the attainable points per criterion, scaled so the strongest preference gets 5."""
    got, best = profile_from_answers(answers)
    if not any(best.values()):
        return {k: NEUTRAL_WEIGHT for k in CRITERIA}
    share = {k: got[k] / best[k] if best[k] else 0 for k in CRITERIA}
    top = max(share.values())
    return {k: round(MAX_WEIGHT * share[k] / top) if top else 0 for k in CRITERIA}


def check_answers(answers):
    if not isinstance(answers, dict):
        raise ValueError('answers must be an object question → answer')
    for k, v in answers.items():
        if k not in _Q or v not in _Q[k]:
            raise ValueError(f'unknown question or answer: {k}={v}')
    return answers


def ranking_state(p):
    """Answers, weights and whether the weights were edited by hand (differ from the answers' weights)."""
    try:
        answers = known_answers(json.loads(p.get('ranking_answers') or '{}'))
    except (ValueError, AttributeError):
        answers = {}
    derived = weights_from_answers(answers)
    try:
        saved = json.loads(p.get('ranking_weights') or 'null')
    except ValueError:
        saved = None
    weights = {k: saved.get(k, derived[k]) for k in CRITERIA} if isinstance(saved, dict) else derived
    return {'answers': answers, 'answered': bool(answers), 'weights': weights,
            'derived_weights': derived, 'manual': weights != derived}


def weights_from(p):
    return ranking_state(p)['weights']


def rank(rows, weights):
    """Weighted 0–100 score among candidates with a per-criterion explanation. Returns the number of candidates."""
    cands = [r for r in rows if not r['is_reference'] and r['listing_status'] != 'WITHDRAWN']
    norm, bounds = {r['id']: {} for r in cands}, {}
    for k, spec in CRITERIA.items():
        vals = [r['metrics'][k] for r in cands if r['metrics'][k] is not None]
        if not weights.get(k) or len(vals) < 2:
            continue
        lo, hi = min(vals), max(vals)
        bounds[k] = {'min': lo, 'max': hi, 'n': len(vals)}
        for r in cands:
            v = r['metrics'][k]
            if v is not None:
                norm[r['id']][k] = 1.0 if hi == lo else ((hi - v) if spec['better'] == 'lower' else (v - lo)) / (hi - lo)
    total_w = sum(w for w in weights.values() if w > 0)
    for r in rows:
        n = norm.get(r['id'], {})
        known_w = sum(weights[k] for k in n)
        score = round(sum(weights[k] * v for k, v in n.items()) / known_w * 100, 1) if known_w else None
        r.update(score_parts={k: round(v * 100) for k, v in n.items()}, score=score,
                 coverage=round(known_w / total_w, 2) if r['id'] in norm and total_w else None, rank=None,
                 explain=[{'criterion': k, 'value': r['metrics'][k], 'unit': CRITERIA[k]['unit'], 'better': CRITERIA[k]['better'],
                           'weight': weights[k], 'score': round(n[k] * 100) if k in n else None,
                           'contribution': round(weights[k] * n[k] / known_w * 100, 1) if k in n and known_w else None,
                           'bounds': bounds.get(k),
                           'why_missing': None if k in n else ('weight 0' if not weights[k] else 'no value for this car' if r['metrics'][k] is None else 'fewer than two cars with a value')}
                          for k in CRITERIA] if r['id'] in norm else [])
    for i, r in enumerate(sorted((r for r in rows if r['score'] is not None), key=lambda r: -r['score']), 1):
        r['rank'] = i
    return len(cands)
