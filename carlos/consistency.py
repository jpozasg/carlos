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
    if len(sa & sb) >= 2 and (sa <= sb or sb <= sa):
        return 'one name contains the other'
    ratio = difflib.SequenceMatcher(None, ' '.join(wa), ' '.join(wb)).ratio()
    return f'similar name {ratio:.2f}' if ratio >= 0.8 else None


def _overlap(a, b):
    """applies_from/applies_to windows (YYYY-MM, NULL = open) share at least one month."""
    return ((a.get('applies_to') is None or b.get('applies_from') is None or b['applies_from'] <= a['applies_to'])
            and (b.get('applies_to') is None or a.get('applies_from') is None or a['applies_from'] <= b['applies_to']))


def _carriers(c, n):
    """Catalogue variants (with the options of their generation) that carry a knowledge row `n` (its own level included)."""
    opts = {}
    for o in c.execute('SELECT id, generation_id FROM options WHERE generation_id IS NOT NULL'):
        opts.setdefault(o['generation_id'], []).append(o['id'])
    return [v for v in ({**v, 'option_ids': opts.get(v['generation_id'], [])} for v in db.variants(c, 'WHERE v.owner_id IS NULL'))
            if db.applies(n, v)]


# table -> (columns that must be equal, how two rows are "the same", what the 409 shows)
def _same_recall(a, b):
    return 'same recall code' if str(a.get('code') or '').strip().upper() == str(b.get('code') or '').strip().upper() else None


def _same_job(a, b):
    return 'same job' if a.get('job') and a.get('job') == b.get('job') else None


GUARDED = {'faults': (('part',), lambda a, b: same_fault(a.get('component'), b.get('component')), 'component'),
           'recalls': ((), _same_recall, 'code'),
           'maintenance_items': ((), _same_job, 'item'),
           'reliability_items': (('part', 'is_recall'), lambda a, b: same_fault(a.get('component'), b.get('component')), 'component')}
# a design defect must not be filed in both tables (#254): faults and non-recall reliability items are checked against each other
ALSO = {'faults': ('reliability_items',), 'reliability_items': ('faults',)}


def conflicts(c, table, n, row_id=None):
    """Existing rows of `table` that a new or changed row `n` would be costed together with (#221): the table's notion of
    "the same" (faults and reliability items: same part, similar name; recalls: same code; maintenance items: same job, global
    defaults excluded), overlapping windows, and at least one catalogue variant that carries both (its own level always
    counts). Faults and non-recall reliability items are also checked against each other (#254). Not a conflict: the row
    itself, a fixed_fault_id pair. Reads the connection's visible rows."""
    level = next((k for k in config.LEVEL_COLUMNS if n.get(k) is not None), None)
    if level is None:
        return []
    mine = _carriers(c, n)
    out = []
    for t in (table, *(ALSO.get(table, ()) if not n.get('is_recall') else ())):
        keys, same, label = GUARDED[t]
        own = t == table
        for x in db.rows(c, f'SELECT * FROM {t} WHERE archived=0' + ('' if own or t != 'reliability_items' else ' AND is_recall=0')):
            if own and x['id'] == row_id:
                continue
            if own and any(n.get(k) != x[k] for k in keys if k != 'is_recall') or own and 'is_recall' in keys and bool(n.get('is_recall')) != bool(x['is_recall']):
                continue
            if not own and n.get('part') != x.get('part'):
                continue
            if t == 'faults' and own and (n.get('fixed_fault_id') == x['id'] or row_id is not None and x.get('fixed_fault_id') == row_id):
                continue
            why = same(n, x)
            if not why or not _overlap(n, x):
                continue
            xl = next((k for k in config.LEVEL_COLUMNS if x.get(k) is not None), None)
            if xl is not None and ((xl == level and x[xl] == n[level] and own) or any(db.applies(x, v) for v in mine)):
                out.append({'id': x['id'], 'table': t, 'level': config.LEVELS[xl], 'level_id': x[xl], 'part': x.get('part'),
                            'component': x.get(label), 'applies_from': x.get('applies_from'), 'applies_to': x.get('applies_to'),
                            'frequency_band': x.get('frequency_band'), 'source_id': x.get('source_id'), 'notes': x.get('notes'), 'match': why})
    return out


def fault_conflicts(c, n, row_id=None):
    return conflicts(c, 'faults', n, row_id)


def _distinct(x, y):
    """One row's notes say it is a different fault from the other (the #221 `distinct_of` decision)."""
    return any((a['notes'] or '').startswith('Distinct from fault') and f"#{b['id']}" in a['notes'] for a, b in ((x, y), (y, x)))


def duplicates(c):
    """Read-only (#221): (double_counted, lift_candidates). double_counted: pairs of faults a catalogue variant would carry
    together that read as one fault (same part, similar name, overlapping window), minus fixed_fault_id links and rows
    marked distinct; each with the variants it hits. lift_candidates: the same fault on two engines of one engine family or two
    gearboxes of one gearbox family (never on one car, so not double counted: maybe one row on the family)."""
    faults = db.rows(c, 'SELECT * FROM faults WHERE archived=0')
    opts = {}
    for o in c.execute('SELECT id, generation_id FROM options WHERE generation_id IS NOT NULL'):
        opts.setdefault(o['generation_id'], []).append(o['id'])
    pairs = {}
    for v in db.variants(c, 'WHERE v.owner_id IS NULL'):
        v = {**v, 'option_ids': opts.get(v['generation_id'], [])}
        here = db.for_variant(faults, v)
        for i, x in enumerate(here):
            for y in here[i + 1:]:
                if (x['part'] == y['part'] and x['id'] != y['id'] and same_fault(x['component'], y['component']) and _overlap(x, y)
                        and x.get('fixed_fault_id') != y['id'] and y.get('fixed_fault_id') != x['id'] and not _distinct(x, y)):
                    pairs.setdefault((min(x['id'], y['id']), max(x['id'], y['id'])), []).append(db.variant_name(v))
    lifts = []
    for col, table in (('engine_id', 'engines'), ('gearbox_id', 'gearboxes')):
        fam = {r['id']: r['family_id'] for r in c.execute(f'SELECT id, family_id FROM {table}') if r['family_id']}
        on = [f for f in faults if f.get(col) in fam]
        for i, x in enumerate(on):
            for y in on[i + 1:]:
                if (fam[x[col]] == fam[y[col]] and x[col] != y[col] and x['part'] == y['part'] and same_fault(x['component'], y['component'])):
                    lifts.append((x['id'], y['id'], f'{table[:-1]} family {fam[x[col]]}'))
    return pairs, lifts


def duplicates_report(c):
    pairs, lifts = duplicates(c)
    by_id = {f['id']: f for f in db.rows(c, 'SELECT * FROM faults')}
    out = [f'# Fault duplicates (#221)', '', f'## Double counted: {len(pairs)}', '']
    for (a, b), names in sorted(pairs.items()):
        x, y = by_id[a], by_id[b]
        keeper = min((x, y), key=lambda f: (f['existence'] != 'CONFIRMED', f['id']))
        out.append(f"- #{a} '{x['component']}' ({config.LEVELS[next(k for k in config.LEVEL_COLUMNS if x.get(k) is not None)]}) and "
                   f"#{b} '{y['component']}' ({config.LEVELS[next(k for k in config.LEVEL_COLUMNS if y.get(k) is not None)]}): "
                   f"{len(names)} variants, e.g. {names[0]}; suggested keeper #{keeper['id']}")
    out += ['', f'## Lift candidates (same fault in sibling engines or gearboxes): {len(lifts)}', '']
    out += [f"- #{a} and #{b} ({why})" for a, b, why in lifts]
    return '\n'.join(out) + '\n'


if __name__ == '__main__':  # python -m carlos.consistency --duplicates [db]
    import sqlite3, sys
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if '--duplicates' not in sys.argv:
        raise SystemExit('usage: python -m carlos.consistency --duplicates [database]')
    con = sqlite3.connect(f'file:{args[0] if args else config.DB}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    print(duplicates_report(con))
