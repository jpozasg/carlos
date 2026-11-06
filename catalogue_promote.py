"""Part 6 of #106 (issue #144): moves the research that still belongs to one account into the shared catalogue and
merges duplicate generations, engines and variants. Generic rules, no ids:

- Promote every private variant with HSN and TSN, with its engine and generation (a variant without them stays private).
- Merge duplicates among the catalogue: generations with the same make, model and name; engines with the same code,
  fuel and kW and a displacement within 2 cm³; variants with the same HSN/TSN. The newest row (highest id, the newest
  research method) is kept and its empty fields are filled from the others; differing values are reported.
- Rows on a promoted level become shared, except those that belong to one account: insurance premiums and quotes,
  the owner's own observations, risks priced over one car's ownership window (< 100,000 km on the variant), rows whose
  notes speak of the listing, seller, photos or "this car", rows citing a listing or user-reported source.
- A row that moved with a merged level is archived when the kept level already has the same thing (job, component,
  part, metric, task, tax or tyre row), so nothing is counted twice; archived rows stay restorable.
- Sources on a promoted level, or cited by its shared rows, become shared (listing and user-reported ones never).

Dry run by default: works on a copy and prints the report; --apply backs up and changes the given database.
Usage: python catalogue_promote.py <cars.sqlite> [--apply] [--out <copy path>]"""
import json, sqlite3, sys, tempfile
from pathlib import Path
from migrate import backup

LEVELS = (('vehicle_id', 'vehicles'), ('engine_id', 'engines'), ('generation_id', 'generations'))
KNOW = ('maintenance_items', 'repair_risks', 'reliability_items', 'observations', 'tax_data', 'tyre_data', 'research_checks', 'insurance_data')
PRIVATE_SOURCES = ('listing', 'user_reported')
PRIVATE_METRICS = ('Current mileage', 'Current annual premium', 'Fuel price working assumption', 'Owner oil top-up', 'Owner measured average')
LISTING_WORDS = ('listing', 'seller', 'photo', 'this car')
SKIP_FIELDS = {'id', 'owner_id', 'notes'}
# when the kept level already has research of the same kind, the moved rows are the older parallel research of the same
# car and are archived: a whole table for schedules, risks, weak points, tax and tyres (the two accounts named the same
# jobs and faults differently, so matching them one by one would count them twice), except that a scheduled job or a
# replacement with a job code only gives way to the same job; per metric and per task otherwise
KEY = {'maintenance_items': lambda r: r['job'], 'repair_risks': lambda r: r['job'], 'reliability_items': lambda r: 'all',
       'tax_data': lambda r: 'all', 'tyre_data': lambda r: 'all', 'observations': lambda r: r['metric'],
       'research_checks': lambda r: r['task'], 'insurance_data': lambda r: 'typklassen'}


def private_reason(t, r, src_type):
    notes = (r['notes'] if 'notes' in r.keys() else '') or ''
    if t == 'insurance_data' and (r['annual_premium_eur'] is not None or r['premium_status'] in ('QUOTE', 'USER DATA')):
        return 'insurance premium or quote (account profile)'
    if t == 'observations' and (r['status'] == 'USER DATA' or r['metric'] in PRIVATE_METRICS or (r['metric'] or '').startswith('Comparable price')):
        return "the owner's own figure or a comparable price"
    if t == 'repair_risks' and r['vehicle_id'] and r['km_from'] is not None and r['km_to'] is not None and r['km_to'] - r['km_from'] < 100000:
        return "priced over one car's ownership window"
    if src_type in PRIVATE_SOURCES:
        return 'cites a listing or user-reported source'
    if any(w in notes.lower() for w in LISTING_WORDS):
        return 'notes speak of the listing, seller, photos or this car'
    return None


def promote(c):
    c.row_factory = sqlite3.Row
    rep = {'promoted': {}, 'merged': [], 'conflicts': [], 'not_merged': [], 'private': {}, 'archived': {}, 'sources': {},
           'private_variants': [], 'possible_duplicates': []}
    log = []

    def upd(t, rid, **f):
        old = dict(c.execute(f'SELECT {", ".join(f)} FROM {t} WHERE id=?', (rid,)).fetchone())
        c.execute(f'UPDATE {t} SET {", ".join(k + "=?" for k in f)} WHERE id=?', (*f.values(), rid))
        log.append((t, rid, 'update', json.dumps(old), json.dumps(f)))

    owner = {t: {r['id']: r['owner_id'] for r in c.execute(f'SELECT id, owner_id FROM {t}')} for _, t in LEVELS}
    # the account each knowledge row belonged to, through its level, before anything moves
    origin = {t: {r['id']: dict(r) for r in c.execute(f'SELECT * FROM {t}')} for t in KNOW}
    level_of = lambda r: next((col, r[col]) for col, _ in LEVELS if r[col] is not None)
    tab = dict(LEVELS)
    row_owner = lambda r: owner[tab[level_of(r)[0]]][level_of(r)[1]]

    # 1. what becomes catalogue
    cat = {t: {i for i, o in owner[t].items() if o is None} for _, t in LEVELS}
    for v in c.execute('SELECT * FROM vehicles WHERE owner_id IS NOT NULL'):
        if (v['hsn'] or '').strip() and (v['tsn'] or '').strip():
            cat['vehicles'].add(v['id']); cat['engines'].add(v['engine_id']); cat['generations'].add(v['generation_id'])
        else:
            rep['private_variants'].append(v['id'])

    # 2. duplicates among the catalogue: keep the newest, fill its gaps, repoint every reference, delete the rest
    fks = [(t, fk[3], fk[2]) for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
           for fk in c.execute(f'PRAGMA foreign_key_list({t})') if fk[2] in tab.values()]
    keys = {'generations': lambda r: (r['make'], r['model'], r['name']),
            'engines': lambda r: ((r['code'] or '').strip().upper(), r['fuel_type'], r['power_kw']),
            'vehicles': lambda r: ((r['hsn'] or '').strip().upper(), (r['tsn'] or '').strip().upper())}
    moved = {t: set() for t in KNOW}
    col_of = {t: col for col, t in LEVELS}

    def merge(t, keep, d):
        """Fills keep's gaps from d, reports differing values, moves every reference from d to keep, removes d."""
        keep = dict(c.execute(f'SELECT * FROM {t} WHERE id=?', (keep,)).fetchone())
        d = dict(c.execute(f'SELECT * FROM {t} WHERE id=?', (d,)).fetchone())
        fill = {k: v for k, v in d.items() if k not in SKIP_FIELDS and keep.get(k) is None and v is not None}
        for k, v in d.items():
            if k not in SKIP_FIELDS and k not in fill and keep.get(k) is not None and v is not None and v != keep[k]:
                rep['conflicts'].append(f'{t} {keep["id"]} (kept) vs {d["id"]}: {k} {keep[k]!r} vs {v!r}')
        if fill:
            upd(t, keep['id'], **fill)
        for kt in KNOW:
            moved[kt] |= {r[0] for r in c.execute(f'SELECT id FROM {kt} WHERE {col_of[t]}=?', (d['id'],))}
        for ft, col, target in fks:
            if target == t:
                for (rid,) in c.execute(f'SELECT id FROM {ft} WHERE {col}=?', (d['id'],)).fetchall():
                    upd(ft, rid, **{col: keep['id']})
        c.execute(f'DELETE FROM {t} WHERE id=?', (d['id'],)); log.append((t, d['id'], 'delete', json.dumps(d), json.dumps({'merged_into': keep['id']})))
        cat[t].discard(d['id'])
        rep['merged'].append(f"{t} {d['id']} (account {d['owner_id'] or 'catalogue'}) into {keep['id']}")

    for t in ('generations', 'engines', 'vehicles'):
        groups = {}
        for r in c.execute(f'SELECT * FROM {t} ORDER BY id DESC'):
            if r['id'] in cat[t]:
                groups.setdefault(keys[t](r), []).append(dict(r))
        for rows in groups.values():
            keep, rest = rows[0], rows[1:]
            for d in rest:
                if t == 'engines' and abs((keep['displacement_cc'] or 0) - (d['displacement_cc'] or 0)) > 2:
                    rep['not_merged'].append(f"engines {keep['id']} and {d['id']}: same code and kW, displacement {keep['displacement_cc']} vs {d['displacement_cc']}")
                    continue
                if t == 'vehicles':  # one HSN/TSN is one type: its engine and generation are the same too
                    k, dd = c.execute('SELECT engine_id, generation_id FROM vehicles WHERE id IN (?,?) ORDER BY id=?', (keep['id'], d['id'], d['id'])).fetchall()
                    for i, lt in ((0, 'engines'), (1, 'generations')):
                        if k[i] != dd[i]:
                            if c.execute('SELECT count(*) FROM vehicles WHERE ' + col_of[lt] + '=? AND id<>?', (dd[i], d['id'])).fetchone()[0]:
                                rep['not_merged'].append(f"{lt} {dd[i]} kept apart from {k[i]}: used by other variants too (same HSN/TSN as variant {keep['id']})")
                            else:
                                merge(lt, k[i], dd[i])
                merge(t, keep['id'], d['id'])
        for i in cat[t]:
            if c.execute(f'SELECT owner_id FROM {t} WHERE id=?', (i,)).fetchone()[0] is not None:
                upd(t, i, owner_id=None); rep['promoted'][t] = rep['promoted'].get(t, 0) + 1

    # 3. rows on catalogue levels: shared unless they belong to one account
    src_type = {r['id']: r['source_type'] for r in c.execute('SELECT id, source_type FROM sources')}
    for t in KNOW:
        for r in c.execute(f'SELECT * FROM {t} WHERE owner_id IS NULL').fetchall():
            col, lid = level_of(r)
            o = row_owner(origin[t][r['id']])
            if lid not in cat[tab[col]] or o is None:
                continue  # still on a private level, or already shared research
            why = private_reason(t, r, src_type.get(r['source_id']))
            if why:
                upd(t, r['id'], owner_id=o); rep['private'][why] = rep['private'].get(why, 0) + 1

    # 4. a row that moved with a merged level and duplicates what the kept level has is archived
    for t in KNOW:
        for r in c.execute(f'SELECT * FROM {t} WHERE archived=0').fetchall():
            if r['id'] not in moved[t] or t == 'insurance_data' and r['owner_id'] is not None or t == 'observations' and r['owner_id'] is not None:
                continue
            col, lid = level_of(r)
            scope = [(col, lid)]
            if col == 'vehicle_id':
                v = c.execute('SELECT engine_id, generation_id FROM vehicles WHERE id=?', (lid,)).fetchone()
                scope += [('engine_id', v[0]), ('generation_id', v[1])]
            where = ' OR '.join(f'{k}=?' for k, _ in scope)
            same = [x for x in c.execute(f'SELECT * FROM {t} WHERE archived=0 AND ({where})', [i for _, i in scope])
                    if x['id'] not in moved[t] and (KEY[t](r) is None or KEY[t](x) == KEY[t](r)) and (x['owner_id'] is None or x['owner_id'] == r['owner_id'])]
            if same:
                upd(t, r['id'], archived=1); rep['archived'][t] = rep['archived'].get(t, 0) + 1
                if t == 'maintenance_items':  # a listing's reset follows its job to the kept row with the same job code
                    to = next((x['id'] for x in same if r['job'] and x['job'] == r['job']), None)
                    for (rid,) in c.execute('SELECT id FROM maintenance_resets WHERE maintenance_item_id=?', (r['id'],)).fetchall():
                        if to:
                            upd('maintenance_resets', rid, maintenance_item_id=to)
                        else:
                            rep['not_merged'].append(f"maintenance reset {rid}: job {r['item']!r} has no job code match on the kept level, so the reset now points to an archived row")

    # 5. sources: shared when on a catalogue level or cited by its shared rows (never listing or user-reported ones)
    for s in c.execute('SELECT * FROM sources WHERE owner_id IS NOT NULL').fetchall():
        if s['source_type'] in PRIVATE_SOURCES:
            continue
        lvl = next(((col, s[col]) for col, _ in LEVELS if s[col] is not None), None)
        if lvl:
            if lvl[1] in cat[tab[lvl[0]]]:
                upd('sources', s['id'], owner_id=None); rep['sources']['on a catalogue level'] = rep['sources'].get('on a catalogue level', 0) + 1
            continue
        citers = {level_of(r) for t in KNOW for r in c.execute(f'SELECT * FROM {t} WHERE source_id=? AND owner_id IS NULL', (s['id'],))
                  if level_of(r)[1] in cat[tab[level_of(r)[0]]]}
        if citers:
            if len(citers) == 1:  # attached to its only level, so only accounts seeing that level see it
                (col, lid), = citers
                upd('sources', s['id'], owner_id=None, **{col: lid}); key = 'cited by one shared level (attached to it)'
            else:  # shortcut: cited from several levels stays level-free, so every account can see it; split it if that matters
                upd('sources', s['id'], owner_id=None); key = 'cited by several shared levels (global)'
            rep['sources'][key] = rep['sources'].get(key, 0) + 1

    # 6. every account with a listing on a catalogue variant keeps seeing it
    for o, v in c.execute('SELECT DISTINCT owner_id, vehicle_id FROM listings').fetchall():
        if v in cat['vehicles'] and not c.execute('SELECT 1 FROM catalogue_links WHERE owner_id=? AND vehicle_id=?', (o, v)).fetchone():
            c.execute('INSERT INTO catalogue_links (owner_id, vehicle_id) VALUES (?,?)', (o, v))
    c.execute('DELETE FROM catalogue_links WHERE id NOT IN (SELECT min(id) FROM catalogue_links GROUP BY owner_id, vehicle_id, engine_id, generation_id)')

    # 7. same make and model with overlapping years: possibly one generation under two names, for the owner to decide
    gens = [dict(r) for r in c.execute('SELECT * FROM generations WHERE owner_id IS NULL ORDER BY make, model, id')]
    for i, a in enumerate(gens):
        for b in gens[i + 1:]:
            if (a['make'], a['model']) == (b['make'], b['model']) and (a['start_year'] or 0) <= (b['end_year'] or 9999) and (b['start_year'] or 0) <= (a['end_year'] or 9999):
                rep['possible_duplicates'].append(f"generations {a['id']} {a['name']!r} and {b['id']} {b['name']!r} ({a['make']} {a['model']})")
    c.executemany('INSERT INTO change_log (table_name, row_id, action, old_json, new_json) VALUES (?,?,?,?,?)', log)
    rep['changes'] = len(log)
    return rep


def run(db, apply=False, out=None):
    db = Path(db)
    if apply:
        backup(db); target = db
    else:
        target = Path(out or Path(tempfile.gettempdir()) / 'carlos-promote-dry-run.sqlite')
        src, dst = sqlite3.connect(db), sqlite3.connect(target)
        src.backup(dst); dst.close(); src.close()
    c = sqlite3.connect(target)
    c.execute('PRAGMA foreign_keys=OFF')
    try:
        rep = promote(c)
        bad = c.execute('PRAGMA foreign_key_check').fetchall()
        if bad:
            raise RuntimeError(f'foreign key violations, nothing changed: {bad[:5]}')
        c.commit()
        assert c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    except Exception:
        c.rollback(); raise
    finally:
        c.close()
    rep['database'] = str(target)
    return rep


if __name__ == '__main__':
    args = sys.argv[1:]
    if not args or args[0].startswith('--'):
        raise SystemExit(__doc__)
    out = args[args.index('--out') + 1] if '--out' in args else None
    print(json.dumps(run(args[0], '--apply' in args, out), indent=1, ensure_ascii=False))
