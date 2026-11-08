"""Compares the two research runs of the pilot (issue #167): where each put the facts, and whether they agree.

  python pilot_compare.py <run a cars.sqlite> <run b cars.sqlite>   prints a Markdown report (read-only)

Agreement rules (owner decision for the pilot: "two runs agree, no tool errors"): a fault is matched across runs by
its part and a similar component name; it agrees when it sits on the same level, its frequency band is at most one
step apart and its workshop price within ±30 %. Also compared: maintenance jobs, recalls, research checks, review
flags, market models (resale rates), worker failures, and the pilot cars' cost per month, completeness and rank."""
import difflib
import sqlite3
import sys
from pathlib import Path

from carlos import auth, config, db

ACCOUNT = 4  # carlostester: the account the pilot requests and cars belong to (pilot.py REQUESTER)
BANDS = list(config.FREQUENCY_BANDS)  # ordered from the most to the least frequent
# Level keys that two independent runs write the same way. Free-text names (generation name, engine code) differ between runs,
# so levels are paired by what identifies the car: make and model, displacement and power, HSN/TSN.
LEVELS = (('vehicle_id', 'vehicles', ('hsn', 'tsn')), ('engine_id', 'engines', ('displacement_cc', 'power_kw')),
          ('engine_family_id', 'engine_families', ()), ('gearbox_id', 'gearboxes', ('type',)),
          ('gearbox_family_id', 'gearbox_families', ()), ('generation_id', 'generations', ('make', 'model')),
          ('body_style_id', 'body_styles', ()), ('option_id', 'options', ()))


def ro(path):
    c = sqlite3.connect(f'file:{Path(path).resolve()}?mode=ro', uri=True)
    c.row_factory = sqlite3.Row
    return c


def level(c, r):
    """'engine CHYB 55' — the level a row sits on, by its natural key, so both runs' ids can differ."""
    for col, table, key in LEVELS:
        if r[col] is not None:
            row = c.execute(f'SELECT * FROM {table} WHERE id=?', (r[col],)).fetchone()
            return f"{table.rstrip('s')} " + ' '.join(str(row[k]) for k in key) if row else f'{table} ?'
    return 'global'


def facts(c, table, where='archived=0'):
    return [{**dict(r), 'level': level(c, r)} for r in c.execute(f'SELECT * FROM {table} WHERE {where}')]


def match(a, b, key):
    """Pairs rows of two runs: same part, most similar name (ratio ≥ 0.6); the rest stays unmatched."""
    pairs, rest = [], list(b)
    for x in a:  # first the same component code on the same part and level (the schema's own identity of a fault), then the name
        code = x.get('component_code')
        y = next((y for y in rest if code and code != 'OTHER' and y.get('component_code') == code and x.get('part') == y.get('part')
                  and x.get('level') == y.get('level')), None)
        if y:
            pairs.append((x, y)); rest.remove(y)
    for x in (x for x in a if all(x is not p[0] for p in pairs)):
        # same part; a name ratio >= 0.6, or >= 0.35 when both sit on the same level (runs word one fault differently)
        best = max(((difflib.SequenceMatcher(None, key(x).lower(), key(y).lower()).ratio() + (0.25 if x.get('level') == y.get('level') else 0), y)
                    for y in rest if x.get('part') == y.get('part')), default=(0, None), key=lambda t: t[0])
        if best[0] >= 0.6:
            pairs.append((x, best[1])); rest.remove(best[1])
    return pairs, [x for x in a if all(x is not p[0] for p in pairs)], rest


def price(f):
    return None if f['parts_eur'] is None and f['labor_eur'] is None else (f['parts_eur'] or 0) + (f['labor_eur'] or 0)


def pct(n, d):
    return f'{100 * n / d:.0f} % ({n}/{d})' if d else 'n/a'


def costs(path):
    """The pilot account's cars as the app ranks them (cost per month, complete, score, rank)."""
    from carlos import server
    config.DB = Path(path).resolve()
    c = db.connect()
    auth.scope(c, ACCOUNT, curator=True)  # as the server does for an admin acting for the account
    out, _ = server.ranked_rows(c, db.params(c))
    c.close()
    return {u['id']: u for u in out}


def report(pa, pb):
    a, b = ro(pa), ro(pb)
    lines = ['# Pilot comparison', '', f'Run A: `{pa}`  ', f'Run B: `{pb}`', '']
    fa, fb = facts(a, 'faults'), facts(b, 'faults')
    pairs, only_a, only_b = match(fa, fb, lambda f: f['component'])
    placed = sum(x['level'] == y['level'] for x, y in pairs)
    bands = [(x, y) for x, y in pairs if x['frequency_band'] in BANDS and y['frequency_band'] in BANDS]
    near = sum(abs(BANDS.index(x['frequency_band']) - BANDS.index(y['frequency_band'])) <= 1 for x, y in bands)
    priced = [(price(x), price(y)) for x, y in pairs if price(x) and price(y)]
    close = sum(abs(p - q) / max(p, q) <= 0.30 for p, q in priced)
    lines += ['## Faults', f'- A: {len(fa)}, B: {len(fb)}, matched: {len(pairs)}',
              f'- Same level: {pct(placed, len(pairs))}', f'- Band within one step: {pct(near, len(bands))}',
              f'- Workshop price within ±30 %: {pct(close, len(priced))}', '',
              '| Part | Component (A / B) | Level (A / B) | Band | Shape | Price € |', '|---|---|---|---|---|---|']
    for x, y in pairs:
        flag = '' if x['level'] == y['level'] else ' ⚠'
        lines.append(f"| {x['part']} | {x['component']} / {y['component']} | {x['level']} / {y['level']}{flag} | "
                     f"{x['frequency_band']} / {y['frequency_band']} | {x['shape']} / {y['shape']} | {price(x)} / {price(y)} |")
    for name, rows in (('Only in A', only_a), ('Only in B', only_b)):
        if rows:
            lines += ['', f'**{name}:** ' + '; '.join(f"{f['component']} ({f['part']}, {f['level']}, {f['frequency_band']})" for f in rows)]
    ma, mb = facts(a, 'maintenance_items', 'archived=0 AND active=1'), facts(b, 'maintenance_items', 'archived=0 AND active=1')
    ka = {(m['level'], m['job'] or m['item']): m for m in ma}
    kb = {(m['level'], m['job'] or m['item']): m for m in mb}
    same = [k for k in ka if k in kb]
    lines += ['', '## Maintenance', f'- A: {len(ma)}, B: {len(mb)}, same job on the same level: {len(same)}',
              f"- Same interval (km and months): {pct(sum(ka[k]['interval_km'] == kb[k]['interval_km'] and ka[k]['interval_months'] == kb[k]['interval_months'] for k in same), len(same))}",
              f'- Only in A: {sorted(str(k) for k in ka.keys() - kb.keys())}', f'- Only in B: {sorted(str(k) for k in kb.keys() - ka.keys())}']
    ra = {r['code'] for r in facts(a, 'recalls')}; rb = {r['code'] for r in facts(b, 'recalls')}
    lines += ['', '## Recalls', f'- Both: {sorted(ra & rb)}', f'- Only A: {sorted(ra - rb)}', f'- Only B: {sorted(rb - ra)}']
    ca = {(r['level'], r['task']): r['result'] for r in facts(a, 'research_checks')}
    cb = {(r['level'], r['task']): r['result'] for r in facts(b, 'research_checks')}
    both = ca.keys() & cb.keys()
    lines += ['', '## Research checks', f'- A: {len(ca)}, B: {len(cb)}, same task on the same level: {len(both)}',
              f'- Same result: {pct(sum(ca[k] == cb[k] for k in both), len(both))}']
    fl = lambda c: [f"{r['kind']} on {level(c, r)} ({r['status']})" for r in c.execute('SELECT * FROM review_flags')]
    lines += ['', '## Review flags', f'- A: {fl(a) or "none"}', f'- B: {fl(b) or "none"}', '', '## Resale (market models)']
    for run, c in (('A', a), ('B', b)):
        lines += [f"- {run} {m['level']}: {m['rate_year']} %/year, {m['rate_10k_km']} %/10,000 km, bands {m['band_counts']}"
                  for m in facts(c, 'market_models')]
    fails = lambda c: [f"#{r['id']} {r['unit'] or ''} {r['status']} after {r['attempts']} attempts: {(r['result'] or '')[:120]!r}" for r in c.execute(
        "SELECT * FROM research_requests WHERE id>=16 AND (status='FAILED' OR attempts>0) ORDER BY id")]
    lines += ['', '## Worker failures and retries (units that FAILED or needed more than one run)', f'- A: {fails(a) or "none"}', f'- B: {fails(b) or "none"}']
    urls = lambda c: {r['url']: r['id'] for r in c.execute('SELECT id, url FROM listings WHERE owner_id=?', (ACCOUNT,)) if r['url']}
    ia, ib = urls(a), urls(b)
    a.close(); b.close()
    ua, ub = costs(pa), costs(pb)
    lines += ['', '## Pilot cars (account 4)', '| Car | € / month A / B | Complete | Missing A / B | Rank A / B |', '|---|---|---|---|---|']
    f = lambda v: '—' if v is None else f'{v:.0f}'
    miss = lambda u: ','.join(i['id'] for i in u.get('research', []) if i['grade'] == 'MISSING') or 'none'
    for url in sorted(ia.keys() & ib.keys()):
        x, y = ua.get(ia[url]), ub.get(ib[url])
        if x and y:
            lines.append(f"| {x.get('title') or url[-20:]} | {f(x['known_cost_per_month'])} / {f(y['known_cost_per_month'])} | "
                         f"{x['tco_complete']} / {y['tco_complete']} | {miss(x)} / {miss(y)} | {x.get('rank')} / {y.get('rank')} |")
    return '\n'.join(lines)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    print(report(sys.argv[1], sys.argv[2]))
