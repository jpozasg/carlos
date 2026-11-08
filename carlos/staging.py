"""Research staging (#253 phase P2, docs/design-two-agent-research.md sections 1.5, 2): the /api/agent writes of a RESEARCH_A,
RESEARCH_B or ARBITER run go to `research_findings` instead of the catalogue. A negative id in the API is a staged row of the
same run (-finding id); it may stand for a source, a level or a fault wherever the real id would. Nothing here writes to the
real tables except `dry_run`, which applies the findings inside a transaction it always rolls back, to grade the run.
Compare (P3) and merge (P4) are not here."""
import json, re, unicodedata
from . import config, consistency, research_units as ru
from .agent import ARCHIVABLE, AGENT_TABLES, Conflict, NotAllowed, NotFound, check_component_code, check_parents, clean_row, guard_duplicate, table_columns
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
