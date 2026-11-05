"""Ranking of the candidates (issues #46, #54). Eight criteria that do not overlap: no metric appears in two of them.
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
    'reliability': {'better': 'higher', 'unit': 'points', 'basis': 'Known weak points of the variant, its engine and its generation in four parts (engine incl. intake, cooling, turbo and injection; gearbox and clutch; chassis, brakes and body; electrics). Severity points HIGH 3, MEDIUM 2, HIGH IF APPLICABLE 1.5, LOW-MEDIUM 1, LOW 0.5; each part starts at 9 and loses the points of its 3 worst weak points (score out of 36, higher is better), so more documentation never makes a car look worse. A recall counts until its checklist item for this car is OK or N/A. Unknown while a weak point has no part.'},
    'inspection': {'better': 'lower', 'unit': 'problems', 'basis': 'Checklist items marked PROBLEM at a viewing; unknown until at least one item was checked.'},
    'power': {'better': 'higher', 'unit': 'ps', 'basis': 'Engine power in PS.'},
    'confidence': {'better': 'higher', 'unit': 'percent', 'basis': 'How much of the research contract is done for this car: every required item of its generation, engine, variant and listing scores VERIFIED 1 (verified or official data from an A/B source), ACCEPTED 0.5 (estimated or a C/D source), MISSING 0; the mean as a percentage (docs/cost-research-protocol.md).'},
}
SEVERITY_POINTS = {'HIGH': 3, 'HIGH IF APPLICABLE': 1.5, 'MEDIUM': 2, 'LOW-MEDIUM': 1, 'LOW': 0.5}
STATUS_POINTS = {'VERIFIED': 1, 'OFFICIAL FEE LEVEL': 1, 'PRIMARY': 1, 'USER DATA': 1, 'QUOTE': 1, 'ESTIMATED': 0.5}
MAX_WEIGHT = 5

# The questionnaire (issues #19, #54, #64): eight best–worst tasks. Each shows four cars of the same model, equal in
# everything except one advantage each; the person picks the car they would buy first and the one they would buy last.
# Criterion i is the point with the binary digits of i in the affine space AG(3,2); each task is a plane
# {x : n·x = b}. The four normals n = 1, 2, 3, 4 give four parallel classes (two complementary planes each): every
# criterion appears in exactly four tasks and every pair of criteria meets at least once (12 pairs once, 12 twice,
# 4 three times; the full 14-task design meets every pair three times but was too long for the owner).
# New task ids (r…) retire earlier answers. Score per criterion: (times first − times last) ÷ times answered, −1…+1,
# mapped to 1–5; never answered = neutral. Reasoning: docs/ranking.md.
_KEYS = list(CRITERIA)
TASKS = [{'id': f'r{2 * i + b + 1}', 'criteria': [_KEYS[x] for x in range(8) if bin(n & x).count('1') % 2 == b]}
         for i, n in enumerate((1, 2, 3, 4)) for b in (0, 1)]
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
    out = {k: {'shown': 0, 'best': 0, 'worst': 0} for k in CRITERIA}
    for tid, a in known_answers(answers).items():
        best, worst = parse_answer(tid, a)
        for k in _T[tid]:
            out[k]['shown'] += 1
        out[best]['best'] += 1
        out[worst]['worst'] += 1
    return out


def weights_from_answers(answers):
    """Weight 1–5 per criterion: (first − last) ÷ shown, from −1 to +1, mapped linearly (half up) to 0–5, floor 1."""
    return {k: max(MIN_DERIVED, int(MAX_WEIGHT * ((x['best'] - x['worst']) / x['shown'] + 1) / 2 + 0.5)) if x['shown'] else NEUTRAL_WEIGHT
            for k, x in tally(answers).items()}


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


def rank(rows, weights):
    """Weighted 0–100 score among candidates with a per-criterion explanation. Returns the number of candidates."""
    cands = [r for r in rows if not r['is_reference'] and r['listing_status'] != 'WITHDRAWN']
    refs = [r for r in rows if r['is_reference']]  # scored for reference (issue #72): same bounds, no rank
    norm, bounds = {r['id']: {} for r in cands + refs}, {}
    for k, spec in CRITERIA.items():
        vals = [r['metrics'][k] for r in cands if r['metrics'][k] is not None]
        if not weights.get(k) or len(vals) < 2:
            continue
        lo, hi = min(vals), max(vals)
        bounds[k] = {'min': lo, 'max': hi, 'n': len(vals)}
        for r in cands + refs:  # bounds come from the candidates only; the reference is clamped to them
            v = r['metrics'][k]
            if v is not None:
                s = 1.0 if hi == lo else ((hi - v) if spec['better'] == 'lower' else (v - lo)) / (hi - lo)
                norm[r['id']][k] = min(1.0, max(0.0, s))
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
    for i, r in enumerate(sorted((r for r in rows if r['score'] is not None and not r['is_reference']), key=lambda r: -r['score']), 1):
        r['rank'] = i
    return len(cands)
