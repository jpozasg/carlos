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

ACCOUNT = 5
BANDS = list(config.FREQUENCY_BANDS)  # ordered from the most to the least frequent
LEVELS = (('vehicle_id', 'vehicles', ('hsn', 'tsn', 'engine_id')), ('engine_id', 'engines', ('code', 'power_kw')),
          ('engine_family_id', 'engine_families', ('name',)), ('gearbox_id', 'gearboxes', ('code',)),
          ('gearbox_family_id', 'gearbox_families', ('name',)), ('generation_id', 'generations', ('make', 'model', 'name')),
          ('body_style_id', 'body_styles', ('generation_id', 'name')), ('option_id', 'options', ('name',)))


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
    for x in a:
        best = max(((difflib.SequenceMatcher(None, key(x).lower(), key(y).lower()).ratio(), y) for y in rest
                    if x.get('part') == y.get('part')), default=(0, None), key=lambda t: t[0])
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
    fails = lambda c: [f"#{r['id']} {r['result'][:120]!r}" for r in c.execute(
        "SELECT * FROM research_requests WHERE status='FAILED' AND note LIKE 'Pilot run%'")]
    lines += ['', '## Worker failures', f'- A: {fails(a) or "none"}', f'- B: {fails(b) or "none"}']
    a.close(); b.close()
    ua, ub = costs(pa), costs(pb)
    from pilot import CARS
    pilot = sorted(i for i in CARS if i in ua and i in ub)
    lines += ['', '## Pilot cars (account 5)', '| Listing | Car | € / month A / B | Complete | Score A / B | Rank A / B |',
              '|---|---|---|---|---|---|']
    for i in pilot:
        x, y = ua[i], ub[i]
        f = lambda v: '—' if v is None else f'{v:.0f}'
        lines.append(f"| {i} | {CARS[i]} | {f(x['known_cost_per_month'])} / {f(y['known_cost_per_month'])} | "
                     f"{x['tco_complete']} / {y['tco_complete']} | {f(x.get('score'))} / {f(y.get('score'))} | {x.get('rank')} / {y.get('rank')} |")
    return '\n'.join(lines)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    print(report(sys.argv[1], sys.argv[2]))
