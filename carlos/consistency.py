"""Statistics vs faults (owner, 2026-11-06, #168): for every generation with TÜV/ADAC figures, compare what the official
statistics say about the model at an age class (its figure ÷ the class average in the same report) with what our faults
predict for it (the yearly chance of any of its faults at that age ÷ the catalogue average for that age class). When one
says clearly more trouble and the other clearly less, the generation gets a STATS_MISMATCH review flag and a follow-up
research request is queued for a worker. Nothing is scaled automatically. Reads the main tables (the whole catalogue)."""
import difflib, json, re, unicodedata
from . import config, db
from .costs import curve_at, shape_curves
from .research_requests import follow_up


def yearly_chance(faults, age):
    """Chance per year that one of the faults happens to a car of this age at typical mileage (sum over the faults of
    the curve's rise over that year; age curves by years, km curves at TYPICAL_KM_PER_YEAR)."""
    total, km = 0.0, config.TYPICAL_KM_PER_YEAR
    for f in faults:
        km_c, age_c = shape_curves(f)
        if age_c:
            total += curve_at(age_c, age + 1, config.CURVE_END_YEARS) - curve_at(age_c, age, config.CURVE_END_YEARS)
        elif km_c:
            total += curve_at(km_c, (age + 1) * km, config.CURVE_END_KM) - curve_at(km_c, age * km, config.CURVE_END_KM)
    return total


def generation_faults(c, gid):
    """The faults a generation's cars carry: its own, its body styles' and options', and those of its variants, engines,
    engine families, gearboxes and gearbox families (every level that reaches its cars)."""
    q = '''SELECT f.* FROM main.faults f WHERE f.archived=0 AND (f.generation_id=:g
        OR f.vehicle_id IN (SELECT id FROM main.vehicles WHERE generation_id=:g)
        OR f.engine_id IN (SELECT engine_id FROM main.vehicles WHERE generation_id=:g)
        OR f.engine_family_id IN (SELECT e.family_id FROM main.vehicles v JOIN main.engines e ON e.id=v.engine_id WHERE v.generation_id=:g)
        OR f.gearbox_id IN (SELECT gearbox_id FROM main.vehicles WHERE generation_id=:g)
        OR f.gearbox_family_id IN (SELECT gb.family_id FROM main.vehicles v JOIN main.gearboxes gb ON gb.id=v.gearbox_id WHERE v.generation_id=:g)
        OR f.body_style_id IN (SELECT id FROM main.body_styles WHERE generation_id=:g)
        OR f.option_id IN (SELECT id FROM main.options WHERE generation_id=:g))'''
    return [dict(r) for r in c.execute(q, {'g': gid})]


def check(c):
    """Flags generations whose statistics and faults disagree clearly (both ways) and queues a follow-up for each new flag.
    Returns the new flags' ids."""
    stats = [dict(r) for r in c.execute('SELECT * FROM main.reliability_stats WHERE archived=0 AND class_average IS NOT NULL')]
    if not stats:
        return []
    faults = {gid: generation_faults(c, gid) for gid in {s['generation_id'] for s in stats}}
    by_age = {}
    for s in stats:
        age = (s['age_from'] + s['age_to']) / 2
        by_age.setdefault((s['age_from'], s['age_to']), []).append((s, yearly_chance(faults[s['generation_id']], age)))
    new, r = [], config.STATS_MISMATCH_RATIO
    with c:
        for cls, entries in by_age.items():
            mean = sum(p for _, p in entries) / len(entries)
            for s, p in entries:
                stat_ratio, fault_ratio = s['value'] / s['class_average'], (p / mean if mean else None)
                if fault_ratio is None or not (stat_ratio >= r and fault_ratio <= 1 / r or stat_ratio <= 1 / r and fault_ratio >= r):
                    continue
                if c.execute("SELECT 1 FROM main.review_flags WHERE generation_id=? AND kind='STATS_MISMATCH' AND status='OPEN'",
                             (s['generation_id'],)).fetchone():
                    continue
                more = stat_ratio >= r
                what = (f"{s['kind']} {s['age_from']}–{s['age_to']} years: {s['value']:g} {s['unit']} vs class average "
                        f"{s['class_average']:g} ({stat_ratio:.1f}×); our faults predict {fault_ratio:.1f}× the catalogue average")
                why = ('the statistics show clearly more trouble than our faults explain: look for missing faults'
                       if more else 'our faults predict clearly more trouble than the statistics show: look for overstated faults')
                fid = c.execute("INSERT INTO main.review_flags (generation_id, kind, what, why, created_by) VALUES (?,?,?,?,?)",
                                (s['generation_id'], 'STATS_MISMATCH', what, why, 'consistency check')).lastrowid
                follow_up(c, fid, f'Review flag {fid} (generation {s["generation_id"]}): {why}. {what}.')
                new.append(fid)
    return new


# --- the same fault filed twice (#221) ---
_STOP = {'the', 'a', 'an', 'of', 'and', 'with', 'on', 'in', 'at', 'to', 'for'}


def _words(text):
    t = unicodedata.normalize('NFKD', str(text or '')).encode('ascii', 'ignore').decode().lower()
    out = []
    for w in re.findall(r'[a-z0-9]+', t):
        if w in _STOP or re.search(r'\d', w):  # a word with a digit is an engine/gearbox code: the level already names it
            continue
        out.append(w[:-1] if len(w) > 3 and w.endswith('s') else w)
    return out


def same_fault(a, b):
    """Whether two component names describe one fault: equal after normalising, word overlap >= 0.6 or text similarity >= 0.8.
    Returns the reason (a short string) or None. shortcut: wording only, until component codes exist (#221 phase 3)."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return None
    if wa == wb:
        return 'same name'
    sa, sb = set(wa), set(wb)
    if len(sa & sb) / len(sa | sb) >= 0.6:
        return 'similar words'
    ratio = difflib.SequenceMatcher(None, ' '.join(wa), ' '.join(wb)).ratio()
    return f'similar name {ratio:.2f}' if ratio >= 0.8 else None


def _overlap(a, b):
    """applies_from/applies_to windows (YYYY-MM, NULL = open) share at least one month."""
    return ((a.get('applies_to') is None or b.get('applies_from') is None or b['applies_from'] <= a['applies_to'])
            and (b.get('applies_to') is None or a.get('applies_from') is None or a['applies_from'] <= b['applies_to']))


def fault_conflicts(c, n, row_id=None):
    """Existing faults that a new or changed fault `n` would be costed together with (#221): same part, a name that
    reads as the same fault, windows that overlap, and at least one catalogue variant that carries both (its own level
    always counts). Not a conflict: the row itself, a fixed_fault_id pair. Reads the connection's visible faults."""
    level = next((k for k in config.LEVEL_COLUMNS if n.get(k) is not None), None)
    variants = [v for v in db.variants(c, 'WHERE v.owner_id IS NULL')]
    opts = {}
    for o in c.execute('SELECT id, generation_id FROM options WHERE generation_id IS NOT NULL'):
        opts.setdefault(o['generation_id'], []).append(o['id'])
    mine = [v for v in ({**v, 'option_ids': opts.get(v['generation_id'], [])} for v in variants) if db.applies(n, v)]
    out = []
    for x in db.rows(c, 'SELECT * FROM faults WHERE archived=0 AND part=?', (n.get('part'),)):
        if x['id'] == row_id or n.get('fixed_fault_id') == x['id'] or x.get('fixed_fault_id') == row_id and row_id is not None:
            continue
        why = same_fault(n.get('component'), x['component'])
        if not why or not _overlap(n, x):
            continue
        xl = next(k for k in config.LEVEL_COLUMNS if x.get(k) is not None)
        if (xl == level and x[xl] == n[level]) or any(db.applies(x, v) for v in mine):
            out.append({'id': x['id'], 'level': config.LEVELS[xl], 'level_id': x[xl], 'part': x['part'], 'component': x['component'],
                        'applies_from': x['applies_from'], 'applies_to': x['applies_to'], 'frequency_band': x['frequency_band'],
                        'source_id': x['source_id'], 'notes': x['notes'], 'match': why})
    return out
