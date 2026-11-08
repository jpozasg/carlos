"""Research staging (#253 phase P2, docs/design-two-agent-research.md sections 1.5, 2): the /api/agent writes of a RESEARCH_A,
RESEARCH_B or ARBITER run go to `research_findings` instead of the catalogue. A negative id in the API is a staged row of the
same run (-finding id); it may stand for a source, a level or a fault wherever the real id would. Nothing here writes to the
real tables except `dry_run`, which applies the findings inside a transaction it always rolls back, to grade the run.
Compare (P3) and merge (P4) are not here."""
import json, re, sqlite3, unicodedata
from . import config, consistency, research_units as ru
from .agent import ARCHIVABLE, AGENT_TABLES, DUPLICATE_GUARDED, Conflict, NotAllowed, NotFound, check_component_code, check_parents, clean_row, guard_duplicate, table_columns
from .auth import MODEL, OWNED, scope
from .db import connect, params

RUN = {'RESEARCH_A': 'A', 'RESEARCH_B': 'B', 'ARBITER': 'C'}
# real table -> finding kind (section 2.1); a PATCH of a real row is always kind 'patch', an insert of the three model tables is refused
KIND = {'sources': 'source', 'engine_families': 'level', 'gearbox_families': 'level', 'gearboxes': 'level', 'body_styles': 'level',
        'options': 'level', 'faults': 'fault', 'recalls': 'recall', 'maintenance_items': 'job', 'research_checks': 'check',
        'observations': 'observation', 'tyre_data': 'tyres', 'reliability_stats': 'stats', 'review_flags': 'flag'}
PATCHABLE = set(KIND) | {'generations', 'engines', 'vehicles', 'repair_risks'}  # never reliability_items (legacy), listing or insurance data
KIND_ORDER = ('source', 'level', 'patch', 'fault', 'recall', 'job', 'check', 'observation', 'tyres', 'stats', 'flag')
MODEL_LEVEL = {'generations': 'generation_id', 'engines': 'engine_id', 'vehicles': 'vehicle_id', 'gearboxes': 'gearbox_id',
               'engine_families': 'engine_family_id', 'gearbox_families': 'gearbox_family_id', 'body_styles': 'body_style_id',
               'options': 'option_id'}
# columns that may hold a staged id, and the table they point at (FKs are read from the schema; these have none declared)
EXTRA_REFS = {'source_id': 'sources', 'fixed_fault_id': 'faults'}


def norm(s):
    t = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode()
    return ' '.join(t.upper().split())


def key_of(kind, table, p, target_id=None):
    """The normalised identity of a finding (section 2.2); two runs' findings with one key are the same thing."""
    if kind == 'source':
        url = (p.get('url') or '').lower().split('#')[0].rstrip('/')
        return f'src:{url}' if url else f'src:title:{norm(p.get("title"))}'
    if kind == 'level':
        nat = {'gearboxes': norm(p.get('code')), 'body_styles': f'{p.get("generation_id")}:{norm(p.get("name"))}',
               'options': f'{norm(p.get("name"))}:{p.get("generation_id") or 0}'}.get(table, norm(p.get('name')))
        return f'lvl:{table}:{nat}'
    if kind == 'patch':
        return f'patch:{table}:{target_id}'
    if kind == 'fault':
        return f'fault:{p.get("part")}:{p.get("component_code")}'
    if kind == 'recall':
        return f'recall:{norm(p.get("code"))}'
    if kind == 'job':
        return f'job:{p["job"]}' if p.get('job') else 'item:' + ' '.join(consistency._words(p.get('item')))
    if kind == 'check':
        return f'check:{p.get("task")}'
    if kind == 'observation':
        return f'obs:{p.get("metric")}'
    if kind == 'tyres':
        return f'tyres:{p.get("tyre_type")}'
    if kind == 'stats':
        return f'stats:{p.get("kind")}:{p.get("age_from")}-{p.get("age_to")}:{p.get("report_year")}'
    return f'flag:{p.get("kind")}:{next((k for k in config.LEVEL_COLUMNS if p.get(k) is not None), None)}:' \
           f'{next((p[k] for k in config.LEVEL_COLUMNS if p.get(k) is not None), None)}'


def _refs(c, table, p):
    """{column: referenced table} for the columns of this row that point at another row (declared FKs plus EXTRA_REFS)."""
    refs = {fk['from']: fk['table'] for fk in c.execute(f'PRAGMA main.foreign_key_list({table})') if fk['table'] != 'users'}
    return {**{k: v for k, v in EXTRA_REFS.items() if k in table_columns(c, table)}, **refs}


def _level(p):
    """The (column, id) pair a row sits on, or (None, None)."""
    return next(((k, p[k]) for k in config.LEVEL_COLUMNS if p.get(k) is not None), (None, None))


def _staged(c, req, fid, table=None):
    row = c.execute('SELECT * FROM main.research_findings WHERE id=? AND request_id=? AND status=?', (fid, req['id'], 'STAGED')).fetchone()
    if row is None:
        raise ValueError(f'{-fid}: not a staged row of this run')
    if table and row['target_table'] != table:
        raise ValueError(f'{-fid}: a staged {row["target_table"]} row, not {table}')
    return row


def _check_refs(c, req, table, p):
    """Negative ids must be staged rows of this run in the right table; the real ones go through check_parents."""
    refs = _refs(c, table, p)
    for col, v in p.items():
        if isinstance(v, int) and not isinstance(v, bool) and v < 0:
            if col not in refs:
                raise ValueError(f'{col}={v}: only references to staged rows may be negative')
            _staged(c, req, -v, refs[col])
    check_parents(c, table, {k: v for k, v in p.items() if not (isinstance(v, int) and not isinstance(v, bool) and v < 0)})


def write(c, req, table, row_id, data):
    """Stages an insert (row_id None), a PATCH of a staged row (row_id < 0) or a PATCH of a real row (row_id > 0) of the run `req`
    (a research_requests row). Returns {'table', 'id': -<finding id>, 'staged': True}. Raises NotAllowed-like errors as the
    server maps them: NotAllowed (403), ValueError (400), NotFound (404), Conflict (409)."""
    if table not in PATCHABLE or table not in AGENT_TABLES:
        raise NotAllowed(f'{table} is not part of a research run (staging takes sources, levels, faults, recalls, jobs, checks, '
                              f'observations, tyres, statistics, flags and patches of real rows)')
    data = dict(data)
    distinct = data.pop('distinct_of', None)
    old = None
    if row_id is not None and row_id < 0:
        old = _staged(c, req, -row_id, table)
        op, target, kind = old['op'], old['target_id'], old['kind']
        data = {**json.loads(old['payload']), **data}
    elif row_id is not None:
        op, target, kind = 'patch', row_id, 'patch'
        if c.execute(f'SELECT 1 FROM {table}_all WHERE id=?' if table in ARCHIVABLE else f'SELECT 1 FROM {table} WHERE id=?', (row_id,)).fetchone() is None:
            raise NotFound(f'{table} id={row_id} does not exist')
        prev = c.execute('SELECT * FROM main.research_findings WHERE request_id=? AND key=? AND status=?',
                         (req['id'], key_of('patch', table, {}, row_id), 'STAGED')).fetchone()
        if prev:  # later PATCHes of the same real row merge into one finding
            old, data = prev, {**json.loads(prev['payload']), **data}
    else:
        if table not in KIND or table in ('generations', 'engines', 'vehicles'):
            raise NotAllowed(f'{table}: the capture created the shell rows; stage a PATCH of the real row instead')
        op, target, kind = 'insert', None, KIND[table]
    p = clean_row(c, table, data, insert=op == 'insert')
    if table == 'faults':  # component_code (#221 phase 3): required on a new fault, in the part's vocabulary
        check_component_code(c, p, target if op == 'patch' else None)
    if op == 'insert':  # the INSERT would fail at the merge: refuse it now
        cols = {r['name']: r for r in c.execute(f'PRAGMA main.table_info({table})')}
        lacking = [n for n, r in cols.items() if r['notnull'] and r['dflt_value'] is None and not r['pk'] and n != 'owner_id' and p.get(n) is None]
        if lacking:
            raise ValueError(f'{table}: required column(s) missing: {", ".join(lacking)}')
    _check_refs(c, req, table, p)
    if op == 'patch':
        base = c.execute(f'SELECT * FROM {table}_all WHERE id=?' if table in ARCHIVABLE else f'SELECT * FROM {table} WHERE id=?', (target,)).fetchone()
        col, lid = (MODEL_LEVEL[table], target) if table in MODEL_LEVEL else _level({**dict(base), **p})
    else:
        col, lid = _level(p)
    if req['scope'] and col and lid is not None and lid > 0 and [col, lid] not in json.loads(req['scope']):
        raise NotAllowed(f'{col}={lid} is already researched or outside this run (scope: {req["scope"]}); it is read-only context')
    if col and lid is not None and lid < 0:
        _staged(c, req, -lid, {v: k for k, v in MODEL_LEVEL.items()}.get(col))
    key = key_of(kind, table, p, target)
    if req['unit'] == 'ARBITER' and kind != 'source' and key not in disputed_keys(c, req['parent_id']):
        raise NotAllowed(f'{key} is not under dispute: the arbiter stages only corrected findings for the disputes it was given')
    mine = old['id'] if old else None
    # within-run duplicates: unique kinds by key (a source answers with the existing id); faults by component (the #221 wording, staged ids)
    same = c.execute('SELECT id FROM main.research_findings WHERE request_id=? AND key=? AND status=? AND id IS NOT ?',
                     (req['id'], key, 'STAGED', mine)).fetchone() if kind not in ('fault', 'check', 'flag') else None
    if same and kind == 'source' and old is None:
        return {'table': table, 'id': -same[0], 'staged': True, 'existing': True}
    if same:
        raise Conflict({'error': f'{table}: this run already staged {key} as {-same[0]}. PATCH -{same[0]} instead of filing it twice'})
    if kind == 'fault':
        _fault_conflicts(c, req, p, mine, distinct)
    if kind in ('fault', 'recall', 'job') and op == 'insert' and lid is not None and lid > 0:  # real rows: the #221 guard, unchanged
        guard_duplicate(c, table, dict(p), None, [d for d in distinct or [] if d > 0] or None)
    stored = json.dumps({**p, **({'distinct_of': distinct} if distinct else {})}, ensure_ascii=False)
    lvl = config.LEVELS.get(col) if col else None
    if old:
        c.execute('UPDATE main.research_findings SET payload=?, key=?, level=?, level_id=?, part=?, updated_at=datetime(\'now\') WHERE id=?',
                  (stored, key, lvl, lid, p.get('part'), old['id']))
        fid = old['id']
    else:
        fid = c.execute('INSERT INTO main.research_findings (request_id, parent_id, run, kind, op, target_table, target_id, key, level, level_id, '
                        'part, component_code, payload) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (req['id'], req['parent_id'] or req['id'], RUN[req['unit']], kind, op, table, target, key, lvl, lid, p.get('part'),
                         p.get('component_code'), stored)).lastrowid
    c.commit()
    return {'table': table, 'id': -fid, 'staged': True}


def _fault_conflicts(c, req, p, mine, distinct):
    """Two staged faults of one run on the same part with the same component are one fault unless distinct_of names the earlier one."""
    found = [r for r in c.execute("SELECT id, payload FROM main.research_findings WHERE request_id=? AND kind='fault' AND status='STAGED' AND id IS NOT ?",
                                  (req['id'], mine))
             if json.loads(r['payload']).get('part') == p.get('part')
             and consistency.same_fault(json.loads(r['payload']).get('component'), p.get('component'))]
    ids = [-r['id'] for r in found]
    if not ids:
        return
    if distinct is None:
        raise Conflict({'error': f"faults: a similar fault is already staged by this run: {ids[0]}. PATCH {ids[0]}, or resend with distinct_of={ids} "
                                 f"and the reason in notes", 'conflict': ids})
    if not set(ids) <= set(distinct) or not str(p.get('notes') or '').strip():
        raise ValueError(f'distinct_of must list every similar staged fault {ids} and notes must say why this one is different')


def findings(c, request_id, status='STAGED'):
    return [dict(r) for r in c.execute('SELECT * FROM main.research_findings WHERE request_id=? AND status=? '
                                       'ORDER BY id', (request_id, status))]


# ---------------------------------------------------------------------------------------------- apply and dry grade
def apply(conn, rows, insert, update):
    """Applies findings in the order sources, levels, patches, knowledge rows, mapping staged ids to the ids the writer returns.
    `insert(table, payload) -> id` and `update(table, id, payload)` do the writing: raw SQL for the dry grade, agent_write for the merge (P4).
    Returns {finding id: real id}."""
    ids = {}
    sub = lambda t, p: {k: (ids[-v] if isinstance(v, int) and not isinstance(v, bool) and v < 0 and k in _refs(conn, t, p) else v)
                        for k, v in p.items()}
    for kind in KIND_ORDER:
        for f in (r for r in rows if r['kind'] == kind):
            p = sub(f['target_table'], {k: v for k, v in json.loads(f['payload']).items() if k != 'distinct_of'})
            if f['op'] == 'patch':
                update(f['target_table'], f['target_id'], p); ids[f['id']] = f['target_id']
            else:
                ids[f['id']] = insert(f['target_table'], p)
    return ids


def _raw_writer(conn, owner_id):
    def insert(table, p):
        catalogue = table in MODEL or table == 'sources' and any(p.get(k) is not None for k in config.LEVEL_COLUMNS)
        if table in OWNED:
            p = {**p, 'owner_id': None if catalogue else owner_id}
        return conn.execute(f'INSERT INTO main.{table} ({",".join(p)}) VALUES ({",".join("?" * len(p))})', list(p.values())).lastrowid

    def update(table, rid, p):
        conn.execute(f'UPDATE main.{table} SET {",".join(f"{k}=?" for k in p)} WHERE id=?', [*p.values(), rid])
    return insert, update


def dry_run(req, fn):
    """fn(connection) on the real catalogue with this run's findings applied on top, as the requester's account (curator view).
    The transaction is always rolled back: the real tables never change. Holds the write lock while it runs (a busy timeout
    covers concurrent writers)."""
    s = connect()
    try:
        scope(s, req['owner_id'], curator=True)
        rows = findings(s, req['id'])
        apply(s, rows, *_raw_writer(s, req['owner_id']))
        return fn(s)
    finally:
        s.rollback()
        s.close()


def missing(req, grade):
    """The research contract items still MISSING for the run's listing with its findings applied (docs section 1.5). `grade(conn, listing_id)`
    returns the MISSING ids (the server's ranked_rows grading). Only the research units' items count; lst.* items never do."""
    return sorted(set(dry_run(req, lambda s: grade(s, req['listing_id']))) & set(ru.RESEARCH_ITEMS))


def stage_view(c, req, grade):
    """GET /api/agent/stage: this run's findings (staged ids negative) and what is still missing. Never another run's."""
    rows = findings(c, req['id'])
    counts = {}
    for r in rows:
        counts[r['kind']] = counts.get(r['kind'], 0) + 1
    return {'request_id': req['id'], 'run': RUN[req['unit']], 'scope': json.loads(req['scope']) if req['scope'] else None,
            'counts': counts,
            'findings': [{'id': -r['id'], 'kind': r['kind'], 'op': r['op'], 'table': r['target_table'], 'target_id': r['target_id'],
                          'key': r['key'], 'level': r['level'], 'level_id': r['level_id'], 'payload': json.loads(r['payload'])} for r in rows],
            'missing': missing(req, grade)}


# ---------------------------------------------------------------------------------------------- compare (P3, sections 3.1-3.3)
import difflib
BANDS = tuple(config.FREQUENCY_BANDS)  # systemic ... rare
BAD_CONSEQUENCE = ('ENGINE_DAMAGE', 'STRANDS', 'SAFETY')
COMPARED = ('fault', 'recall', 'job', 'check', 'observation', 'tyres', 'stats', 'patch', 'level')  # flags and sources are never compared
DISPUTE_ORDER = ('patch', 'level', 'recall', 'fault', 'job')  # then the rest; faults by price


def _payload(f):
    return {k: v for k, v in json.loads(f['payload']).items() if k != 'distinct_of'}


def _ref(c, f):
    """A level or a staged id as something comparable across runs: staged rows by their key, real ones by id."""
    lid = f['level_id']
    if lid is not None and lid < 0:
        lid = c.execute('SELECT key FROM main.research_findings WHERE id=?', (-lid,)).fetchone()[0]
    return [f['level'], lid]


def _price(p):
    return None if p.get('parts_eur') is None and p.get('labor_eur') is None else (p.get('parts_eur') or 0) + (p.get('labor_eur') or 0)


def _differs(rule, a, b):
    if a is None or b is None:
        return a is not b
    if rule == 'eq':
        return norm(a) != norm(b) if isinstance(a, str) or isinstance(b, str) else a != b
    if rule[0] == 'rel':
        return abs(a - b) > rule[1] * max(abs(a), abs(b))
    return abs(BANDS.index(a) - BANDS.index(b)) > rule[1] if a in BANDS and b in BANDS else a != b


def _diffs(c, fa, fb):
    pa, pb = _payload(fa), _payload(fb)
    out = []
    if fa['kind'] in ('patch', 'level'):  # identity: every field both set (staged ids compared by key); notes and sources are not facts
        res = lambda k, v: _ref(c, {'level': k, 'level_id': v})[1] if k.endswith('_id') and isinstance(v, int) and v < 0 else v
        for k in sorted(set(pa) & set(pb) - {'notes', 'source_id', 'usage_source_id'}):
            if pa[k] is not None and pb[k] is not None and _differs('eq', res(k, pa[k]), res(k, pb[k])):
                out.append({'field': k, 'a': pa[k], 'b': pb[k]})
        return out
    for field, rule in config.STAGE_TOLERANCE[fa['kind']].items():
        a, b = (_ref(c, fa), _ref(c, fb)) if field == 'level' else \
               (_price(pa), _price(pb)) if field == 'price' else (pa.get(field), pb.get(field))
        if _differs(rule, a, b):
            out.append({'field': field, 'a': a, 'b': b})
    if fa['kind'] == 'fault' and not consistency.same_fault(pa, pb):  # paired by component code only: the wording differs
        out.append({'field': 'component', 'a': pa.get('component'), 'b': pb.get('component')})
    return out


def _material(kind, outcome, pa, pb, diffs):
    """Section 3.3. pa/pb: the payloads of the sides present."""
    if outcome == 'AGREED':
        return 0
    one = outcome != 'DISPUTED'
    p = pa or pb
    names = {d['field'] for d in diffs}
    if kind in ('patch', 'level'):
        return int(not one)
    if kind == 'fault':
        if one:
            return int(p.get('frequency_band') in BANDS[:3] or (_price(p) or 0) >= config.STAGE_MATERIAL_EUR
                       or p.get('consequence') in BAD_CONSEQUENCE)
        return int(bool(names & {'level', 'frequency_band', 'component'})
                   or 'price' in names and max(_price(pa) or 0, _price(pb) or 0) >= config.STAGE_MATERIAL_EUR)
    if kind == 'recall':
        return int(one)
    if kind == 'job':
        return int(bool(p.get('job')) and p.get('kind') != 'WEAR') if one else int(bool(names & {'interval_km', 'interval_months'}))
    return int(kind in ('observation', 'tyres', 'stats') and not one)


def _fault_pairs(A, B):
    """Greedy pairing inside (part, component_code): same_fault first, then the best text ratio; a lone fault on each side always
    pairs. NULL and OTHER codes pair only by same_fault."""
    pairs, ga, gb = [], {}, {}
    for g, rows in ((ga, A), (gb, B)):
        for f in rows:
            g.setdefault((f['part'], f['component_code']), []).append(f)
    for grp, ra in ga.items():
        cands = []
        for i, x in enumerate(ra):
            for j, y in enumerate(gb.get(grp, [])):
                px, py = _payload(x), _payload(y)
                same = bool(consistency.same_fault(px, py))
                if same or grp[1] not in (None, 'OTHER'):
                    cands.append((same, difflib.SequenceMatcher(None, norm(px.get('component')), norm(py.get('component'))).ratio(), i, j))
        ua, ub = set(), set()
        for _, _, i, j in sorted(cands, key=lambda t: (-t[0], -t[1], t[2], t[3])):
            if i not in ua and j not in ub:
                ua.add(i); ub.add(j); pairs.append((ra[i], gb[grp][j]))
    return pairs


_RESULT_RANK = {'FOUND': 2, 'NONE FOUND': 1, 'N/A': 0}


def _pairs(c, A, B):
    """[(finding of run A or None, finding of run B or None, match key)] over the compared kinds."""
    out = []
    for kind in COMPARED:
        ra, rb = [f for f in A if f['kind'] == kind], [f for f in B if f['kind'] == kind]
        if kind == 'fault':
            prs = _fault_pairs(ra, rb)
            done = {f['id'] for pr in prs for f in pr}
            name = lambda f: f"{f['key']}:{norm(_payload(f).get('component'))}"
            out += [(a, b, name(a)) for a, b in prs]
            out += [(f if f in ra else None, f if f in rb else None, name(f)) for f in ra + rb if f['id'] not in done]
            continue
        ga, gb = {}, {}
        for g, rows in ((ga, ra), (gb, rb)):
            for f in rows:  # checks: one per task and level, the best result stands for the run
                k = f['key'] if kind != 'check' else f"{f['key']}@{_ref(c, f)}"
                if k not in g or kind == 'check' and _RESULT_RANK[_payload(f)['result']] > _RESULT_RANK[_payload(g[k])['result']]:
                    g[k] = f
        out += [(ga.get(k), gb.get(k), k) for k in sorted(set(ga) | set(gb))]
    return out


def compare(c, parent_id):
    """Pairs run A's and run B's STAGED findings of one parent and writes one research_matches row per pair or one-sided finding.
    Idempotent: a parent with matches is left alone. Returns agreement(c, parent_id)."""
    if not c.execute('SELECT 1 FROM main.research_matches WHERE parent_id=?', (parent_id,)).fetchone():
        rows = [dict(r) for r in c.execute("SELECT * FROM main.research_findings WHERE parent_id=? AND status='STAGED' AND run IN ('A','B') "
                                           "ORDER BY id", (parent_id,))]
        for a, b, key in _pairs(c, [r for r in rows if r['run'] == 'A'], [r for r in rows if r['run'] == 'B']):
            kind, pa, pb = (a or b)['kind'], a and _payload(a), b and _payload(b)
            if a and b:
                diffs = _diffs(c, a, b) if kind != 'check' else \
                    [{'field': 'result', 'a': pa['result'], 'b': pb['result']}] if pa['result'] != pb['result'] else []
            else:
                diffs = []
            outcome = ('DISPUTED' if diffs else 'AGREED') if a and b else 'ONLY_A' if a else 'ONLY_B'
            c.execute('INSERT INTO main.research_matches (parent_id, kind, key, a_id, b_id, outcome, diffs, material) VALUES (?,?,?,?,?,?,?,?)',
                      (parent_id, kind, key, a and a['id'], b and b['id'], outcome, json.dumps(diffs) if diffs else None,
                       0 if kind == 'check' else _material(kind, outcome, pa, pb, diffs)))
        c.commit()
    return agreement(c, parent_id)


def agreement(c, parent_id):
    """AGREED / all matches, overall and per kind (section 3.2), plus the number of material disputes."""
    per, tot = {}, {'agreed': 0, 'total': 0}
    for kind, outcome, n in c.execute('SELECT kind, outcome, count(*) FROM main.research_matches WHERE parent_id=? GROUP BY kind, outcome', (parent_id,)):
        for d in (per.setdefault(kind, {'agreed': 0, 'total': 0}), tot):
            d['total'] += n; d['agreed'] += n if outcome == 'AGREED' else 0
    share = lambda d: round(d['agreed'] / d['total'], 4) if d['total'] else None
    return {'agreement': share(tot), 'matches': tot['total'], 'per_kind': {k: {**d, 'agreement': share(d)} for k, d in per.items()},
            'material': c.execute('SELECT count(*) FROM main.research_matches WHERE parent_id=? AND material=1', (parent_id,)).fetchone()[0]}


# ---------------------------------------------------------------------------------------------- arbiter interface (3.4)
VERDICTS = ('A', 'B', 'BOTH', 'NEITHER', 'OWN')


def dispute_rows(c, parent_id):
    """The material matches the arbiter may answer: at most MAX_DISPUTES, identity first, then recalls, faults by price, jobs, the rest."""
    def order(m):
        prices = [_price(json.loads(m[s])) or 0 for s in ('a_payload', 'b_payload') if m[s]]
        return (DISPUTE_ORDER.index(m['kind']) if m['kind'] in DISPUTE_ORDER else len(DISPUTE_ORDER), -max(prices, default=0), m['id'])
    rows = [dict(r) for r in c.execute(
        'SELECT m.*, fa.payload a_payload, fb.payload b_payload FROM main.research_matches m LEFT JOIN main.research_findings fa ON fa.id=m.a_id '
        'LEFT JOIN main.research_findings fb ON fb.id=m.b_id WHERE m.parent_id=? AND m.material=1 ORDER BY m.id', (parent_id,))]
    return sorted(rows, key=order)[:config.MAX_DISPUTES]


def _question(m, diffs):
    f = {d['field'] for d in diffs}
    if m['outcome'] != 'DISPUTED':
        return {'fault': 'Is this fault real for this car, and is its band and price right?', 'recall': 'Is this recall real and does it apply to this car?',
                'job': 'Does this maintenance job apply to this car, and at what interval?'}.get(m['kind'], 'Is this finding right for this car?')
    if m['kind'] in ('patch', 'level'):
        return f'Which value is right for {", ".join(sorted(f))}?'
    qs = [q for k, q in (('level', 'Which level does the evidence name?'), ('frequency_band', 'Which frequency band does the evidence support?'),
                         ('component', 'Do the two entries describe the same fault?'), ('price', 'Which repair price is right?'),
                         ('interval_km', 'Which interval is right?'), ('interval_months', 'Which interval is right?')) if k in f]
    return ' '.join(dict.fromkeys(qs)) or f'Which value is right for {", ".join(sorted(f))}?'


def _side(c, fid):
    if fid is None:
        return None
    f = dict(c.execute('SELECT * FROM main.research_findings WHERE id=?', (fid,)).fetchone())
    p = _payload(f)
    sid, src = p.get('source_id'), None
    if sid is not None:  # a staged source is another finding of the same run; a real one is a sources row
        row = c.execute('SELECT payload FROM main.research_findings WHERE id=?', (-sid,)).fetchone() if sid < 0 else \
              c.execute('SELECT title, url, quality, supports FROM sources WHERE id=?', (sid,)).fetchone()
        src = None if row is None else json.loads(row[0]) if sid < 0 else dict(row)
    return {'payload': p, 'level': _ref(c, f), 'source_id': sid,
            'sources': [{k: src.get(k) for k in ('title', 'url', 'quality', 'supports')}] if src else []}


def disputes_view(c, req):
    """GET /api/agent/disputes (ARBITER token): the disputes of its parent; 'a' is run 1, 'b' run 2."""
    if req['unit'] != 'ARBITER':
        raise NotAllowed('Only the ARBITER run reads the disputes')
    out = []
    for m in dispute_rows(c, req['parent_id']):
        diffs = json.loads(m['diffs']) if m['diffs'] else []
        out.append({'id': m['id'], 'kind': m['kind'], 'key': m['key'], 'outcome': m['outcome'], 'question': _question(m, diffs), 'diffs': diffs,
                    'a': _side(c, m['a_id']), 'b': _side(c, m['b_id']), 'verdict': m['verdict'], 'reason': m['verdict_reason']})
    return {'parent_id': req['parent_id'], 'disputes': out, 'answered': sum(1 for d in out if d['verdict']), 'open': [d['id'] for d in out if not d['verdict']]}


def answer_dispute(c, req, match_id, body):
    """PATCH /api/agent/disputes/<id> {"verdict", "reason", "source_id"?, "finding"?}. A/B need that side, BOTH both sides, OWN a
    "finding": -<id> staged by this run on the disputed key. May be answered again until the merge."""
    if req['unit'] != 'ARBITER':
        raise NotAllowed('Only the ARBITER run answers disputes')
    m = next((d for d in dispute_rows(c, req['parent_id']) if d['id'] == match_id), None)
    if m is None:
        raise NotFound(f'dispute {match_id} does not exist for this request')
    v, reason = body.get('verdict'), str(body.get('reason') or '').strip()
    if v not in VERDICTS or not reason:
        raise ValueError(f'verdict must be one of {", ".join(VERDICTS)} and reason must say why')
    if v in ('A', 'B') and not m[v.lower() + '_id'] or v == 'BOTH' and not (m['a_id'] and m['b_id']):
        raise ValueError(f'verdict {v}: that side did not stage this finding')
    own, src = None, body.get('source_id')
    if src is not None:
        if not isinstance(src, int) or src >= 0 and not c.execute('SELECT 1 FROM sources WHERE id=?', (src,)).fetchone():
            raise ValueError('source_id must be a staged source of this run (negative) or an existing source')
        if src < 0:
            _staged(c, req, -src, 'sources')
    if v == 'OWN':
        fid = body.get('finding')
        if not isinstance(fid, int) or fid >= 0:
            raise ValueError('verdict OWN needs "finding": -<id> of a corrected finding staged by this run')
        own = _staged(c, req, -fid)
        if own['key'] not in {r[0] for i in (m['a_id'], m['b_id']) if i for r in c.execute('SELECT key FROM main.research_findings WHERE id=?', (i,))}:
            raise ValueError(f'finding {fid} is on {own["key"]}, not on the disputed key')
    elif body.get('finding') is not None:
        raise ValueError('"finding" belongs to verdict OWN only')
    c.execute('UPDATE main.research_matches SET verdict=?, verdict_id=?, verdict_reason=?, verdict_source_id=? WHERE id=?',
              (v, own['id'] if own else None, reason, src, match_id))
    c.commit()
    return {'id': match_id, 'verdict': v}


def unanswered(c, parent_id):
    """Dispute ids without a verdict: the arbiter's done gate (re-queue while any remain)."""
    return [m['id'] for m in dispute_rows(c, parent_id) if not m['verdict']]


def disputed_keys(c, parent_id):
    """The finding keys an ARBITER run may stage (for OWN verdicts); sources are always allowed."""
    return {r[0] for m in dispute_rows(c, parent_id) for r in c.execute('SELECT key FROM main.research_findings WHERE id IN (?,?)', (m['a_id'], m['b_id']))}


# ---------------------------------------------------------------------------------------------------- merge (P4, section 3.5)
_BAND_ORDER = ('rare', 'occasional', 'common', 'widespread', 'systemic')  # ascending: higher index = worse
NOTE_AGREED, NOTE_ONE = 'Second independent run agreed (sources: %s).', 'Found by one of two independent runs.'


class _Skip(Exception):
    pass


def _quality(c, fs, p):
    sid = p.get('source_id')
    if sid is None:
        return 9
    q = fs[-sid]['p'].get('quality') if sid < 0 and -sid in fs else (c.execute('SELECT quality FROM sources WHERE id=?', (sid,)).fetchone() or [None])[0]
    return 'ABCD'.index(q) if q in tuple('ABCD') else 9


def _figure(kind, p):
    """Higher = less favourable to the buyer (section 3.5): higher band and price for faults, shorter interval and dearer job for jobs."""
    if kind == 'fault':
        return (_BAND_ORDER.index(p['frequency_band']) if p.get('frequency_band') in _BAND_ORDER else -1, (p.get('parts_eur') or 0) + (p.get('labor_eur') or 0))
    if kind == 'job':
        return (-(p.get('interval_km') or 1e12), -(p.get('interval_months') or 1e12), p.get('reference_cost_eur') or 0)
    return ()


def _pick(c, fs, a, b):
    """Of two paired findings: the less favourable figure; on a tie (or a kind without figures) the better source quality, then A."""
    fa, fb = _figure(a['kind'], a['p']), _figure(a['kind'], b['p'])
    if fa != fb:
        return a if fa > fb else b
    return b if _quality(c, fs, b['p']) < _quality(c, fs, a['p']) else a


def _urls(c, fs, *found):
    out = []
    for f in found:
        sid = f['p'].get('source_id')
        if sid is None:
            continue
        u = fs[-sid]['p'].get('url') if sid < 0 and -sid in fs else (c.execute('SELECT url FROM sources WHERE id=?', (sid,)).fetchone() or [None])[0]
        if u and u not in out:
            out.append(u)
    return ', '.join(out) or 'none cited'


def _plan(c, fs, m):
    """([(finding, note, distinct_of_the_first)], skip reason, needs a flag) for one match."""
    a, b = fs.get(m['a_id']), fs.get(m['b_id'])
    sides, v, kind = [x for x in (a, b) if x], m['verdict'], m['kind']
    if kind in ('check', 'flag'):  # unions: every distinct one is written
        return [(x, None, False) for x in sides], None, False
    if v == 'NEITHER':
        return [], f'rejected by the arbiter: {m["verdict_reason"]}', False
    if v in ('A', 'B', 'OWN'):
        f = {'A': a, 'B': b, 'OWN': fs.get(m['verdict_id'])}[v]
        return ([(f, None, False)], None, False) if f else ([], f'verdict {v} names a finding that does not exist', False)
    if v == 'BOTH':
        return [(x, m['verdict_reason'] if i else None, bool(i)) for i, x in enumerate(sides)], None, False
    unresolved = bool(m['material'])
    if unresolved and kind in ('patch', 'level') and m['outcome'] != 'AGREED':
        return [], 'identity dispute not settled by the arbiter; left unwritten', True
    if len(sides) == 1:
        return [(sides[0], NOTE_ONE, False)], None, unresolved
    agreed = m['outcome'] == 'AGREED'
    return [(_pick(c, fs, a, b), NOTE_AGREED % _urls(c, fs, a, b) if agreed else None, False)], None, unresolved and not agreed


def _summary(m):
    diffs = json.loads(m['diffs'] or '[]')
    if diffs:
        r1, r2 = (', '.join(f'{d["field"]} {d[s]}' for d in diffs) for s in 'ab')
    else:
        r1, r2 = ('found it', 'did not find it') if m['a_id'] else ('did not find it', 'found it')
    return f'{m["kind"]} {m["key"]}: run 1 {r1}; run 2 {r2}'


def merge(c, parent_id, owner_id, actor=None):
    """Writes the agreed and arbitrated findings of a listing request through agent_write (validation, change_log, catalogue ownership,
    the #221 duplicate guard). Idempotent: matches already merged are left alone. Returns the report; `accounts` are the accounts whose
    dossiers changed. consistency.check runs once at the end, not after every fault."""
    from .agent import agent_write, linked_accounts
    ms = [dict(r) for r in c.execute('SELECT * FROM main.research_matches WHERE parent_id=? ORDER BY id', (parent_id,))]
    if not ms:
        raise ValueError(f'request {parent_id}: nothing to merge, the two runs were not compared')
    fs = {r['id']: {**dict(r), 'p': json.loads(r['payload'])} for r in c.execute('SELECT * FROM main.research_findings WHERE parent_id=?', (parent_id,))}
    ids = {i: f['merged_id'] for i, f in fs.items() if f['status'] == 'MERGED' and f['merged_id']}
    skipped_f, redirect, touched, orphans, seen = set(), {}, [], [], set()
    report = {'parent_id': parent_id, 'counts': {}, 'written': 0, 'skipped': [], 'flags': [], 'orphans': orphans}
    for m in ms:
        report['counts'][m['outcome']] = report['counts'].get(m['outcome'], 0) + 1
    lv = c.execute('SELECT l.vehicle_id FROM main.listings l JOIN main.research_requests r ON r.listing_id=l.id WHERE r.id=?', (parent_id,)).fetchone()

    def write(table, rid, p):
        out = agent_write(c, table, rid, p, owner_id, True, actor, check=False)
        touched.append((table, out))
        return out

    def real(fid):
        """The real id a staged reference stands for: written already, a source or level created on first use, or unavailable."""
        if fid not in ids:
            f = fs.get(fid)
            if f is None or fid in skipped_f or f['kind'] not in ('source', 'level'):
                raise _Skip(f'it points at staged row {-fid}, which was not written')
            ids[fid] = create(f, None)
            c.execute("UPDATE main.research_findings SET status='MERGED', merged_id=?, updated_at=datetime('now') WHERE id=?", (ids[fid], fid))
        return ids[fid]

    def subst(table, p):
        refs = _refs(c, table, p)
        p = {k: real(-v) if isinstance(v, int) and not isinstance(v, bool) and v < 0 and k in refs else v for k, v in p.items() if k != 'distinct_of'}
        return {k: redirect.get((k, v), v) if k in config.LEVEL_COLUMNS else v for k, v in p.items()}

    def create(f, note, distinct=None):
        """Writes one finding (get-or-create for sources and levels) and returns the real id."""
        table, p = f['target_table'], dict(f['p'])
        if note:
            p['notes'] = f'{p["notes"]} {note}' if p.get('notes') else note
        p = subst(table, p)
        if f['kind'] in ('source', 'level'):
            want = key_of(f['kind'], table, p)
            hit = next((x['id'] for x in c.execute(f'SELECT * FROM {table}') if key_of(f['kind'], table, dict(x)) == want), None)
            return hit or write(table, None, p)
        if f['op'] == 'patch':
            try:
                write(table, f['target_id'], p)
            except sqlite3.IntegrityError:  # the shell engine's natural key is already in the catalogue: relink instead
                base = {**dict(c.execute(f'SELECT * FROM {table} WHERE id=?', (f['target_id'],)).fetchone()), **p}
                same = c.execute('SELECT id FROM engines WHERE owner_id IS NULL AND code=? AND power_kw=? AND id!=?',
                                 (base.get('code'), base.get('power_kw'), f['target_id'])).fetchone() if table == 'engines' else None
                if same is None:
                    raise
                for (vid,) in c.execute('SELECT id FROM vehicles WHERE engine_id=?', (f['target_id'],)).fetchall():
                    write('vehicles', vid, {'engine_id': same[0]})
                redirect[('engine_id', f['target_id'])] = same[0]
                orphans.append({'engine_id': f['target_id'], 'relinked_to': same[0]})
                return same[0]
            return f['target_id']
        mapped = [ids[-d] for d in f['p'].get('distinct_of') or [] if ids.get(-d)] + list(distinct or [])
        if mapped and table in DUPLICATE_GUARDED:
            p['distinct_of'] = mapped
        return write(table, None, p)

    def flag(m):
        f = fs.get(m['a_id']) or fs.get(m['b_id'])
        col = next((k for k, name in config.LEVELS.items() if f['level'] == name), None) if f['kind'] != 'level' else None
        lid = (f['level_id'] if f['level_id'] is None or f['level_id'] > 0 else ids.get(-f['level_id'])) if col else None
        if lid is None:  # a staged level that was not written: the flag goes on the listing's variant
            col, lid = 'vehicle_id', lv[0]
        return write('review_flags', None, {col: lid, 'kind': 'SOURCES_DISAGREE', 'what': _summary(m), 'created_by': f'merge of request #{parent_id}',
                                            'why': f'Two independent research runs disagree and the arbiter did not settle it (request #{parent_id})'})

    for m in sorted(ms, key=lambda m: (KIND_ORDER.index(m['kind']), m['id'])):
        if m['merged']:
            continue
        written, reason, needs_flag = [], None, False
        try:
            plan, reason, needs_flag = _plan(c, fs, m)
            for f, note, after_first in plan:
                try:
                    if f['kind'] in ('check', 'flag'):
                        sig = (f['target_table'], json.dumps(subst(f['target_table'], f['p']), sort_keys=True))
                        if sig in seen:
                            continue
                        seen.add(sig)
                    ids[f['id']] = create(f, note, [ids[w['id']] for w in written] if after_first else None)
                    written.append(f)
                except Conflict as e:  # never forced: the row exists, the run should have extended it
                    hit = (e.payload.get('conflict') or [{}])[0]
                    reason = f'exists as {hit["table"]} #{hit["id"]}' if hit.get('id') else str(e)
                except (_Skip, ValueError, sqlite3.Error) as e:
                    reason = f'not written: {e}'
        except _Skip as e:
            reason = f'not written: {e}'
        skipped_f |= {s for s in (m['a_id'], m['b_id'], m['verdict_id']) if s in fs and s not in {w['id'] for w in written}}
        report['written'] += len(written)
        for w in written:
            c.execute("UPDATE main.research_findings SET status='MERGED', merged_id=?, updated_at=datetime('now') WHERE id=?", (ids[w['id']], w['id']))
        for s in skipped_f & {m['a_id'], m['b_id'], m['verdict_id']}:
            c.execute("UPDATE main.research_findings SET status='SKIPPED', updated_at=datetime('now') WHERE id=? AND status='STAGED'", (s,))
        flag_id = flag(m) if needs_flag else None
        report['flags'] += [flag_id] if flag_id else []
        res = {'ids': [ids[w['id']] for w in written], **({'skipped' if not written else 'note': reason} if reason else {})}
        c.execute('UPDATE main.research_matches SET merged=?, flag_id=? WHERE id=?', (json.dumps(res), flag_id, m['id']))
        c.commit()
        if not written and reason:
            report['skipped'].append({'match': m['id'], 'key': m['key'], 'reason': reason})
    consistency.check(c)
    report['accounts'] = sorted({o for t, i in touched for o in linked_accounts(c, t, i)})
    return report
