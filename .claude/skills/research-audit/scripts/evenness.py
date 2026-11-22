#!/usr/bin/env python3
"""Evenness yardstick for Carlos research: one row per car (listing), one column per metric, outliers marked '*',
then the defects with row ids. Read-only: the database is opened with mode=ro and nothing is written.
Usage: python evenness.py [path/to/cars.sqlite] [--all]   (default $CARLOS_DATA/cars.sqlite, else data/cars.sqlite)
No personal data is printed: only listing ids, make/model/generation names, table names and row ids."""
import datetime, os, re, sqlite3, statistics, sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), *['..'] * 4))
try:  # the repo's own values when run inside it; the fallback keeps the script usable on its own
    sys.path.insert(0, ROOT)
    from carlos.config import DIYABLE_JOBS, QUOTE_MAX_AGE_DAYS
except Exception:  # shortcut: hard-coded copies of config.DIYABLE_JOBS and QUOTE_MAX_AGE_DAYS, refresh when they change
    DIYABLE_JOBS = {'OIL_SERVICE', 'AIR_FILTER', 'CABIN_FILTER', 'FUEL_FILTER', 'SPARK_PLUGS', 'BRAKES_FRONT', 'BRAKES_REAR',
                    'BATTERY', 'BULBS', 'WIPERS', 'COOLANT', 'TIMING_DRIVE', 'CLUTCH'}
    QUOTE_MAX_AGE_DAYS = 60

# the levels a listing inherits from (carlos.config.LEVEL_COLUMNS without gearbox_family_id, retired by #295, and option_id)
LEVELS = ['vehicle_id', 'gearbox_id', 'engine_id', 'engine_family_id', 'generation_id', 'body_style_id']
# job -> the contract check that may stand in for it ('NONE FOUND'), see carlos/research.py ITEMS
TASK_OF_JOB = {'COOLANT': 'eng.coolant', 'OIL_SERVICE': 'eng.oil', 'SPARK_PLUGS': 'eng.spark_plugs', 'GEARBOX_OIL': 'gbx.service',
               'CLUTCH': 'gbx.clutch', 'BRAKE_FLUID': 'gen.brake_fluid', 'HU': 'gen.hu', 'TIMING_DRIVE': 'eng.timing_chain',
               'DRIVE_COOLANT': 'eng.drive_coolant', 'REDUCTION_GEAR_OIL': 'eng.reduction_gear_oil'}
VERIFIED_STATUS = {'VERIFIED', 'OFFICIAL FEE LEVEL', 'PRIMARY', 'QUOTE', 'DOCUMENTED'}
STOP = {'the', 'a', 'an', 'of', 'and', 'with', 'due', 'kit', 'by', 'age', 'in', 'to', 'for', 'new', 'replacement'}


def connect(path):
    # shortcut: mode=ro URI, no immutable flag. Carlos uses the default rollback journal; a WAL database would get -shm/-wal files created next to it
    # as_uri() percent-encodes the path (a '?', '#' or '%' in a directory name would otherwise open another file)
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)


def q(c, sql, *args):
    c.row_factory = sqlite3.Row
    return [dict(r) for r in c.execute(sql, args)]


def has(c, table):
    return bool(q(c, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", table))


def words(text):
    return {w for w in re.findall(r'[a-z]{4,}', (text or '').lower()) if w not in STOP}


def in_window(r, reg):
    """carlos.costs.in_window: a row with a first-registration window (applies_from/to on faults and the like, registered_from/to
    on tax_data, 'YYYY' or 'YYYY-MM') applies to a car registered inside it; an unknown registration keeps the row."""
    if not reg:
        return True
    lo = r.get('applies_from') or r.get('registered_from')
    hi = r.get('applies_to') or r.get('registered_to')
    n = lambda w: min(len(w), len(reg))
    return (not lo or lo[:n(lo)] <= reg[:n(lo)]) and (not hi or reg[:n(hi)] <= hi[:n(hi)])


class Car:
    """One listing with the rows it inherits (archived rows, other accounts' private rows and rows whose build window
    excludes the car left out). The listing must have a variant."""
    def __init__(s, c, L):
        s.c, s.L = c, L
        v = q(c, 'SELECT * FROM vehicles WHERE id=?', L['vehicle_id'])[0]
        e = (q(c, 'SELECT * FROM engines WHERE id=?', v['engine_id']) or [{}])[0]
        g = (q(c, 'SELECT * FROM generations WHERE id=?', v['generation_id']) or [{}])[0]
        s.ids = {'vehicle_id': v['id'], 'gearbox_id': v.get('gearbox_id'), 'engine_id': v['engine_id'],
                 'engine_family_id': e.get('family_id'), 'generation_id': v['generation_id'], 'body_style_id': v.get('body_style_id')}
        s.label = 'L%d %s %s %s%s' % (L['id'], g.get('make', '?'), g.get('model', '?'), g.get('name') or '', ' (ref)' if L['is_reference'] else '')
        s.cache = {}

    def rows(s, table):
        if table not in s.cache:
            out = []
            if has(s.c, table):
                cols = {r[1] for r in s.c.execute('PRAGMA table_info(%s)' % table)}  # table is a literal from this file
                for lev, i in s.ids.items():
                    if i is not None and lev in cols:
                        w = ' AND archived=0' if 'archived' in cols else ''
                        o = ' AND (owner_id IS NULL OR owner_id=%d)' % int(s.L['owner_id'] or 0) if 'owner_id' in cols else ''
                        out += [dict(r, _level=lev[:-3]) for r in q(s.c, 'SELECT * FROM %s WHERE %s=?%s%s' % (table, lev, w, o), i)]
            s.cache[table] = [r for r in out if in_window(r, s.L['first_registration'])]
        return s.cache[table]

    def own(s, table):  # rows tied to the listing itself
        if (table, 'own') not in s.cache:
            ok = has(s.c, table)
            s.cache[(table, 'own')] = q(s.c, 'SELECT * FROM %s WHERE listing_id=?%s' % (table, ' AND archived=0' if table != 'listing_events' else ''), s.L['id']) if ok else []
        return s.cache[(table, 'own')]


def mid_share(f):
    return None if f.get('share_low') is None or f.get('share_high') is None else (f['share_low'] + f['share_high']) / 2


def metrics(car, today):
    """(numeric metrics, defects) for one car. Defects are (code, table, row id, text)."""
    d, m = [], {}
    faults, items = car.rows('faults'), car.rows('maintenance_items')
    items = [i for i in items if i.get('active', 1)]
    eng = [f for f in faults if f['_level'] in ('engine', 'engine_family')]
    m['faults'], m['engine_faults'] = len(faults), len(eng)
    # expected cost = (parts + labour) x the middle of the share range; curve-only faults have no share and count as 0 here
    m['exp_fault_eur'] = round(sum(((f['parts_eur'] or 0) + (f['labor_eur'] or 0)) * mid_share(f) for f in faults if mid_share(f) is not None))
    m['fault_prob_null'] = sum(1 for f in faults if not f['probability_basis'])
    m['jobs'] = len({i['job'] for i in items if i.get('job')})
    prices = items + car.rows('tyre_data') + car.rows('tax_data')
    est = sum(1 for r in prices if r.get('status') == 'ESTIMATED')
    m['estimated_pct'] = round(100 * est / len(prices)) if prices else None
    m['verified_pct'] = round(100 * sum(1 for r in prices if r.get('status') in VERIFIED_STATUS) / len(prices)) if prices else None
    keys = {(k['source_key'], k['external_key']) for k in car.rows('source_keys')}
    rated = {(r['source_key'], r['external_key']) for r in q(car.c, 'SELECT source_key, external_key FROM source_ratings WHERE archived=0')} \
        if has(car.c, 'source_ratings') else set()
    m['rel_slots_of_3'] = sum(1 for k in ('AUTOSCORE', 'TUEV_REPORT', 'ADAC_PANNENSTATISTIK')
                              if any(sk == k and (sk, ek) in rated for sk, ek in keys))
    checks = car.rows('research_checks')
    m['rel_checks'] = sum(1 for k in checks if (k['task'] or '').startswith('rel.'))
    m['recalls'] = len(car.rows('recalls'))
    free_recall = [i for i in car.own('inspection_items') if re.search(r'recall|rückruf', i['item'] or '', re.I) and not i.get('recall_id')]
    m['recall_items_unlinked'] = len(free_recall)
    for r in free_recall:
        d.append(('RECALL_UNLINKED', 'inspection_items', r['id'], 'free-text recall item without recall_id'))
    # NULL vs zero
    for t, cols in {'faults': ('parts_eur', 'labor_eur', 'diy_parts_eur', 'diy_hours'),
                    'maintenance_items': ('reference_cost_eur', 'diy_parts_cost_eur', 'diy_hours'),
                    'tyre_data': ('price_per_tyre_eur',)}.items():
        for r in car.rows(t):
            for col in cols:
                if r.get(col) == 0:
                    d.append(('ZERO_NOT_NULL', t, r['id'], '%s = 0 (unknown must be NULL; zero needs a note)' % col))
    for r in car.own('unit_costs'):
        for col in ('parts_eur', 'labor_eur', 'diy_hours'):
            if r.get(col) == 0:
                d.append(('ZERO_NOT_NULL', 'unit_costs', r['id'], '%s = 0' % col))
    # DIY / workshop pairs
    for r in items:
        if r.get('job') in DIYABLE_JOBS and (r['reference_cost_eur'] is None) != (r['diy_parts_cost_eur'] is None):
            d.append(('DIY_PAIR', 'maintenance_items', r['id'], '%s has only one of workshop price / DIY parts price' % r['job']))
    # status vs evidence on every price row: ESTIMATED needs its derivation, VERIFIED / OFFICIAL FEE LEVEL an A/B source
    for t, rs in (('maintenance_items', items), ('tyre_data', car.rows('tyre_data')), ('tax_data', car.rows('tax_data'))):
        for r in rs:
            if r['status'] == 'ESTIMATED' and not (r.get('notes') or r.get('basis') or '').strip():
                d.append(('ESTIMATED_NO_NOTE', t, r['id'], 'ESTIMATED without a derivation in notes'))
            if r['status'] in ('VERIFIED', 'OFFICIAL FEE LEVEL') and r.get('source_id') is not None:
                qv = q(car.c, 'SELECT quality FROM sources WHERE id=?', r['source_id'])
                if qv and qv[0]['quality'] not in ('A', 'B'):
                    d.append(('VERIFIED_LOW_QUALITY', t, r['id'], '%s on a %s source' % (r['status'], qv[0]['quality'])))
    for f in faults:
        if not f['probability_basis']:
            d.append(('FAULT_NO_BASIS', 'faults', f['id'], 'probability_basis NULL'))
        if not (f.get('quote') or '').strip():
            d.append(('FAULT_NO_QUOTE', 'faults', f['id'], 'quote empty'))
        if f['parts_eur'] is None and f['labor_eur'] is None:
            d.append(('FAULT_UNPRICED', 'faults', f['id'], 'no price (every fault gets one, estimated if need be)'))
    # stale quotes (insurance_data of the variant, listing_quotes of the listing)
    for t, rs in (('insurance_data', car.rows('insurance_data')), ('listing_quotes', car.own('listing_quotes'))):
        for r in rs:
            if r['premium_status'] == 'QUOTE' and r['quote_date']:
                try:
                    age = (today - datetime.date.fromisoformat(str(r['quote_date'])[:10])).days
                except ValueError:
                    d.append(('STALE_QUOTE', t, r['id'], 'quote_date %r is not a date' % r['quote_date']))
                    continue
                if age > QUOTE_MAX_AGE_DAYS:
                    d.append(('STALE_QUOTE', t, r['id'], 'quote is %d days old (limit %d)' % (age, QUOTE_MAX_AGE_DAYS)))
    # checks: NONE FOUND and "source does not list / cover it" N/A need the URL or the search in notes; an N/A that says an item
    # does not apply (gen.facelift) needs a reason; a NONE FOUND on a *.risks item must not contradict rows on that level
    risk_tasks = {'eng.risks': 'engine', 'fam.risks': 'engine_family', 'gen.risks': 'generation', 'gbx.risks': 'gearbox', 'bdy.risks': 'body_style'}
    for k in checks:
        notes = k['notes'] or ''
        source_claim = k['result'] == 'NONE FOUND' or k['task'].startswith('rel.') or k['task'] in ('gen.recalls', 'gen.safety')
        if k['result'] in ('NONE FOUND', 'N/A') and source_claim and not re.search(r'https?://|\bsite:|\bsearch(ed)?\b', notes, re.I):
            d.append(('CHECK_NO_EVIDENCE', 'research_checks', k['id'], '%s %s: notes hold neither a URL nor the search' % (k['task'], k['result'])))
        elif k['result'] == 'N/A' and not source_claim and len(notes.strip()) < 10:
            d.append(('CHECK_NO_EVIDENCE', 'research_checks', k['id'], '%s N/A: no reason in notes' % k['task']))
        if k['result'] == 'NONE FOUND' and k['task'] in risk_tasks and any(f['_level'] == risk_tasks[k['task']] for f in faults):
            d.append(('NONE_FOUND_CONTRADICTED', 'research_checks', k['id'], '%s NONE FOUND but faults exist on that level' % k['task']))
    # duplicates across levels
    seen = defaultdict(list)
    for i in items:
        if i.get('job'):
            seen[i['job']].append(i)
    for job, rs in seen.items():
        if len({r['_level'] for r in rs}) > 1:
            d.append(('DUPLICATE_LEVELS', 'maintenance_items', rs[0]['id'], '%s on several levels: ids %s' % (job, ','.join(str(r['id']) for r in rs))))
    fseen = defaultdict(list)
    for f in faults:
        if not (f.get('notes') or '').startswith('Distinct from fault'):  # distinct_of: the API wrote that prefix (agent.guard_duplicate)
            fseen[f['component_code'] or (f['component'] or '').lower()].append(f)
    for code, fs in fseen.items():
        if len({f['_level'] for f in fs}) > 1:
            d.append(('DUPLICATE_LEVELS', 'faults', fs[0]['id'], 'fault %s on several levels: ids %s' % (code, ','.join(str(f['id']) for f in fs))))
    # certain costs vs active faults / schedule restarts
    resets = {r['unit_cost_id'] for r in car.own('maintenance_resets')}
    for u in car.own('unit_costs'):
        if u['category'] == 'maintenance' and u['id'] not in resets:
            d.append(('CERTAIN_NO_RESTART', 'unit_costs', u['id'], 'certain maintenance cost without a maintenance_resets row (schedule counted twice)'))
        if u['category'] in ('repairs', 'maintenance'):
            for f in faults:
                if len(words(u['item']) & words(f['component'])) >= 2:
                    d.append(('DOUBLE_COUNT', 'unit_costs', u['id'], 'certain cost overlaps active fault id %d (%s)' % (f['id'], f['_level'])))
    m['_jobs'] = {i['job'] for i in items if i.get('job')}
    m['_none_found'] = {k['task'] for k in checks if k['result'] == 'NONE FOUND'}
    return m, d


def outliers(table, cols):
    """Cells to mark: value more than 2x or less than half the median of the other cars (needs 3 cars)."""
    out = set()
    if len(table) < 3:
        return out
    for col in cols:
        vals = [m[col] for m in table.values() if m.get(col) is not None]
        if len(vals) < 3:
            continue
        med = statistics.median(vals)
        for lid, m in table.items():
            v = m.get(col)
            if v is not None and ((med == 0 and v > 0) or (med and (v > 2 * med or v < med / 2))):
                out.add((lid, col))
    return out


def main(argv):
    args = [a for a in argv if not a.startswith('--')]
    path = args[0] if args else os.path.join(os.environ.get('CARLOS_DATA', os.path.join(ROOT, 'data')), 'cars.sqlite')
    if not os.path.exists(path):
        sys.exit('no database at %s' % path)
    c = connect(path)
    today = datetime.date.today()
    where = '' if '--all' in argv else " WHERE COALESCE(listing_status, '')<>'WITHDRAWN'"
    table, defects, cars = {}, [], []
    for L in q(c, 'SELECT * FROM listings%s ORDER BY id' % where):
        if L['vehicle_id'] is None or not q(c, 'SELECT 1 FROM vehicles WHERE id=?', L['vehicle_id']):  # vehicle_id is nullable (#167)
            defects.append(('L%d' % L['id'], 'NO_VARIANT', 'listings', L['id'], 'listing has no variant: not researched, left out of the table'))
        else:
            cars.append(Car(c, L))
    for car in cars:
        m, d = metrics(car, today)
        table[car.label], defects = m, defects + [(car.label,) + x for x in d]
    cols = ['faults', 'engine_faults', 'exp_fault_eur', 'fault_prob_null', 'jobs', 'estimated_pct', 'verified_pct', 'rel_slots_of_3',
            'rel_checks', 'recalls', 'recall_items_unlinked']
    odd = outliers(table, cols)
    w = max([len(k) for k in table] + [4])
    print('Evenness: %d cars, database %s (read-only). * = more than 2x / less than half the median of the cars.' % (len(table), os.path.basename(path)))
    print('car'.ljust(w), *[c_.rjust(len(c_) + 1) for c_ in cols])
    for lid, m in table.items():
        print(lid.ljust(w), *[('%s%s' % ('-' if m[c_] is None else m[c_], '*' if (lid, c_) in odd else '')).rjust(len(c_) + 1) for c_ in cols])
    # jobs on some cars only
    alljobs = set().union(*[m['_jobs'] for m in table.values()]) if table else set()
    for job in sorted(alljobs):
        miss = [k for k, m in table.items() if job not in m['_jobs']]
        if miss and len(miss) < len(table):
            nf = [k for k in miss if TASK_OF_JOB.get(job) in table[k]['_none_found']]
            defects.append(('catalogue', 'JOB_UNEVEN', 'maintenance_items', '-', '%s researched on %d car(s), missing on %s (NONE FOUND check on: %s)'
                            % (job, len(table) - len(miss), ', '.join(m_.split(' ')[0] for m_ in miss), ', '.join(n.split(' ')[0] for n in nf) or 'none')))
    # source grades by domain
    dom = defaultdict(lambda: defaultdict(list))
    for s in q(c, 'SELECT id, url, quality FROM sources WHERE url IS NOT NULL AND owner_id IS NULL'):  # shared research sources only
        dom[(urlparse(s['url']).netloc or '?').lower().replace('www.', '')][s['quality'] or 'NULL'].append(s['id'])
    print('\nSource grades by domain, shared sources only (a domain with two grades is listed as a defect):')
    for k in sorted(dom):
        print('  %-34s %s' % (k, ' '.join('%s:%d' % (g, len(v)) for g, v in sorted(dom[k].items()))))
        if len(dom[k]) > 1:
            defects.append(('catalogue', 'GRADE_MISMATCH', 'sources', '-', '%s graded %s (ids %s)' % (k, '/'.join(sorted(dom[k])), ','.join(str(i) for v in dom[k].values() for i in v[:3]))))
    print('\nDefects (%d):' % len(defects))
    for x in sorted(defects, key=lambda x: (x[1], x[0])):
        print('  [%s] %s %s id=%s: %s' % x)
    c.close()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
