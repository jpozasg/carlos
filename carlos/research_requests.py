"""Research requests (issue #113): accounts queue listing URLs; the shared worker (admin token) claims the oldest,
researches it with docs/prompts/research-car.md writing as the requester (X-Carlos-Account) and finishes it.
Every query names main.research_requests and filters by owner itself: the table is not shadowed by auth.scope."""
import json, re, secrets
from .auth import digest
from . import research, research_units as ru
from .todo import quote_profile_gaps

MAX_ATTEMPTS = 3         # a listing still incomplete after this many DONE reports is FAILED with the missing items (#218)
MAX_OPEN = 5             # QUEUED + RUNNING per account: keeps one account from flooding the shared worker
WORKER_DOWN_SECONDS = 180  # a worker polls every 60 s: no heartbeat for three polls = down (issue #141)
CLAIM_TIMEOUT_HOURS = 3  # a RUNNING request older than this is taken to be abandoned (worker crashed) and can be claimed again
COLS = 'id, owner_id, url, note, status, requested_at, claimed_at, finished_at, worker, listing_id, result, requested_by, kind, flag_id, attempts, missing, parent_id, unit, level_id, shared_id, scope'


def clean_url(url):
    url = str(url or '').strip()
    if len(url) > 500 or not re.fullmatch(r'https?://[^\s/]+\.[^\s/]+(/\S*)?', url):
        raise ValueError('url: an http(s) link to the listing, at most 500 characters')
    return url


def _parts(c, parent_ids):
    out = {}
    for r in c.execute(f'SELECT {COLS} FROM main.research_requests WHERE parent_id IN ({",".join("?" * len(parent_ids))}) ORDER BY id',
                       parent_ids) if parent_ids else ():
        d = dict(r)
        d['missing'] = json.loads(d['missing']) if d['missing'] else []
        d['scope'] = json.loads(d['scope']) if d['scope'] else None
        d['detail'] = _detail(c, d)
        out.setdefault(d['parent_id'], []).append(d)
    return out


def _detail(c, d):
    """Progress line data of the two-agent units (#253 1.7); None for the other units."""
    from . import staging
    if d['unit'] in ('RESEARCH_A', 'RESEARCH_B'):
        staged = dict(c.execute('SELECT kind, count(*) FROM main.research_findings WHERE request_id=? GROUP BY kind', (d['id'],)).fetchall())
        last = c.execute('SELECT key, created_at FROM main.research_findings WHERE request_id=? ORDER BY id DESC LIMIT 1', (d['id'],)).fetchone()
        return {'staged': staged, 'last': ' '.join(last[0].split(':', 2)) if last else None, 'last_at': last[1] if last else None,
                'missing': d['missing']}
    if d['unit'] == 'ARBITER':
        ds = staging.dispute_rows(c, d['parent_id'])
        return {'disputes': len(ds), 'answered': sum(1 for m in ds if m['verdict'])}
    if d['unit'] == 'MERGE':
        ms = [json.loads(r[0]) for r in c.execute('SELECT merged FROM main.research_matches WHERE parent_id=? AND merged IS NOT NULL', (d['parent_id'],))]
        return {'agreement': staging.agreement(c, d['parent_id'])['agreement'], 'written': sum(len(m.get('ids') or []) for m in ms),
                'skipped': sum(1 for m in ms if m.get('skipped')),
                'flags': c.execute('SELECT count(*) FROM main.research_matches WHERE parent_id=? AND flag_id IS NOT NULL', (d['parent_id'],)).fetchone()[0]}
    return None


def _stages(c, parent_id):
    """The stages of a request: the legacy ones when it already has a legacy child, the dual ones when it has a dual child, else FLOW decides."""
    units = {r[0] for r in c.execute('SELECT unit FROM main.research_requests WHERE parent_id=?', (parent_id,))}
    if units & set(ru.LEGACY_UNITS):
        return ru.LEGACY_STAGES
    return ru.STAGES if units & {'RESEARCH_A', 'RESEARCH_B'} or ru.FLOW == 'dual' else ru.LEGACY_STAGES


def mine(c, uid):
    """The account's requests (parents only), each with `parts`: its units in stage order with status, attempts and missing items."""
    reqs = [dict(r) for r in c.execute(f'SELECT {COLS} FROM main.research_requests WHERE owner_id=? AND parent_id IS NULL ORDER BY id DESC', (uid,))]
    kids = _parts(c, [r['id'] for r in reqs])
    for r in reqs:
        order = {u: i for i, u in enumerate(sum(_stages(c, r['id']), ()))}
        r['parts'] = [{k: p[k] for k in ('unit', 'status', 'attempts', 'missing', 'shared_id', 'detail')} for p in
                      sorted(kids.get(r['id'], []), key=lambda p: order.get(p['unit'], 99))]
    return reqs


def create(c, uid, data, by=None):
    """by: the admin who queued it for the account (issue #139); None when the account asked itself."""
    raw = str(data.get('url') or '').strip()
    m = re.fullmatch(r'carlos://listing/(\d+)', raw)  # re-research a listing the account has (no ad, or offline; #194)
    if m and not c.execute('SELECT 1 FROM main.listings WHERE id=? AND owner_id=?', (int(m[1]), uid)).fetchone():
        raise ValueError(f'{raw}: no such listing in this account')
    url, note = raw if m else clean_url(raw), (str(data.get('note') or '').strip()[:1000] or None)
    with c:
        open_urls = [r[0] for r in c.execute("SELECT url FROM main.research_requests WHERE owner_id=? AND parent_id IS NULL "
                                             "AND status IN ('QUEUED','RUNNING','WAITING')", (uid,))]
        if url in open_urls:
            raise ValueError('This link is already waiting to be researched')
        if len(open_urls) >= MAX_OPEN:
            raise ValueError(f'At most {MAX_OPEN} requests can wait at a time; cancel one or wait until the worker finishes one')
        rid = c.execute("INSERT INTO main.research_requests (owner_id, url, note, requested_by, unit) VALUES (?,?,?,?,'CAPTURE')",
                        (uid, url, note, by)).lastrowid
    return rid


def follow_up(c, flag_id, task):
    """Queues a follow-up research request (#168) for a review flag: an admin's request (the catalogue is shared), its
    URL names the flag; the worker reviews the flagged level and records a flag review. One open request per flag."""
    if c.execute("SELECT 1 FROM main.research_requests WHERE flag_id=? AND status IN ('QUEUED','RUNNING')", (flag_id,)).fetchone():
        return None
    admin = c.execute("SELECT min(id) FROM main.users WHERE role='admin' AND is_active=1").fetchone()[0]
    return c.execute("INSERT INTO main.research_requests (owner_id, url, note, kind, flag_id) VALUES (?,?,?,'FOLLOW_UP',?)",
                     (admin, f'carlos://follow-up/flag/{flag_id}', task[:1000], flag_id)).lastrowid


def cancel(c, uid, rid):
    """Cancels one of the account's requests that has not started: QUEUED, or a unit-split one WAITING between stages
    (its queued and waiting units are cancelled with it; a unit already running finishes and the request stays cancelled)."""
    with c:
        n = c.execute("UPDATE main.research_requests SET status='CANCELLED', finished_at=datetime('now') "
                      "WHERE id=? AND owner_id=? AND parent_id IS NULL AND (status='QUEUED' OR status='WAITING' AND unit IS NOT NULL)",
                      (rid, uid)).rowcount
        if not n:
            raise ValueError('Only your own requests still waiting in the queue can be cancelled')
        kids = [r[0] for r in c.execute("SELECT id FROM main.research_requests WHERE parent_id=? AND status IN ('QUEUED','WAITING')", (rid,))]
        for k in kids:
            c.execute("UPDATE main.research_requests SET status='CANCELLED', finished_at=datetime('now') WHERE id=?", (k,))
        for k in kids:
            release_shared(c, _blocker(c, k))


def everything(c):
    """The whole queue with who asked (admins)."""
    out = [dict(r) for r in c.execute(f'SELECT {", ".join("r." + x.strip() for x in COLS.split(","))}, u.username '
                                      'FROM main.research_requests r JOIN main.users u ON u.id=r.owner_id WHERE r.parent_id IS NULL '
                                      'ORDER BY r.id DESC LIMIT 500')]
    kids = _parts(c, [r['id'] for r in out])
    for r in out:
        r['children'] = kids.get(r['id'], [])
    return out


def claim(c, worker, worker_id=None):
    """Takes the oldest QUEUED request (or an abandoned RUNNING one) for `worker`, atomically; None when idle.
    The request gets a fresh per-request token (issue #141), returned once as `request_token`."""
    worker = str(worker or 'worker').strip()[:60]
    raw = secrets.token_urlsafe(32)
    c.isolation_level = None  # manual transaction: BEGIN IMMEDIATE takes the write lock before reading, so two workers never get the same row
    try:
        c.execute('BEGIN IMMEDIATE')
        # a worker runs one request at a time: one it still holds was interrupted (e.g. restarted), so queue it again (#160)
        c.execute("UPDATE main.research_requests SET status='QUEUED', claimed_at=NULL, worker=NULL, request_token_hash=NULL, "
                  "result=COALESCE(result || char(10), '') || ? WHERE status='RUNNING' AND worker=?",
                  (f'Released: worker {worker} claimed a new request; the previous run was interrupted', worker))
        row = c.execute(f"SELECT id FROM main.research_requests WHERE status='QUEUED' OR status='RUNNING' AND claimed_at < "
                        f"datetime('now', '-{CLAIM_TIMEOUT_HOURS} hours') ORDER BY coalesce(parent_id, id), id LIMIT 1").fetchone()
        if row:
            c.execute("UPDATE main.research_requests SET status='RUNNING', claimed_at=datetime('now'), worker=?, request_token_hash=? "
                      "WHERE id=?", (worker, digest(raw), row[0]))
            if worker_id is not None:
                c.execute("UPDATE main.workers SET state='working', request_id=?, last_seen=datetime('now') WHERE id=?", (row[0], worker_id))
        c.execute('COMMIT')
    except BaseException:
        c.execute('ROLLBACK'); raise
    finally:
        c.isolation_level = ''
    if not row:
        return None
    r = dict(c.execute(f'SELECT {COLS} FROM main.research_requests WHERE id=?', (row[0],)).fetchone())
    r['missing'] = json.loads(r['missing']) if r['missing'] else []
    r['scope'] = json.loads(r['scope']) if r['scope'] else None
    return {**r, 'request_token': raw}


def _row(c, rid):
    return dict(c.execute(f'SELECT {COLS} FROM main.research_requests WHERE id=?', (rid,)).fetchone())


def _unit_ids(ids, unit):
    if unit in ru.ITEM_UNIT:  # both research runs own the same items
        return [i for i in ids if i in ru.RESEARCH_ITEMS]
    return [i for i in ids if ru.UNIT_OF.get(i) == unit]


def finish(c, rid, data, missing=None, staged=None):
    """Finishes a RUNNING request. `missing(owner_id, listing_id)` -> ids of the contract items still MISSING (the server's own
    grading, #218): the agent's DONE/FAILED is only a hint. A unit-split request (unit set) is graded for its unit's items only
    and advances the parent; a legacy one (unit NULL) is graded as a whole. Missing items re-queue it, FAILED after MAX_ATTEMPTS.
    The two-agent units (#253) have their own gates: a research run is graded on its staged rows (`staged(request) -> ids`) and closes
    DONE with gaps after RESEARCH_MAX_ATTEMPTS; the ARBITER on unanswered disputes (DONE after 2 attempts); the MERGE on the real rows
    (one attempt, FAILED with the items still missing)."""
    status, result = data.get('status'), (str(data.get('result') or '').strip()[-4000:] or None)
    if status not in ('DONE', 'FAILED', 'QUEUED'):
        raise ValueError('status: DONE, FAILED or QUEUED (release)')
    req = c.execute("SELECT id, owner_id, status, unit, parent_id, listing_id, attempts, kind, missing, scope FROM main.research_requests WHERE id=?", (rid,)).fetchone()
    if req is None or req['status'] != 'RUNNING':
        raise ValueError('Only a RUNNING request can be finished')
    if status == 'QUEUED':  # the run could not work (usage limit, API error): back in the queue, not a failure (#206)
        with c:
            c.execute("UPDATE main.research_requests SET status='QUEUED', claimed_at=NULL, worker=NULL, request_token_hash=NULL, "
                      "result=COALESCE(result || char(10), '') || ? WHERE id=?", (result or 'Released by the worker', rid))
            c.execute("UPDATE main.workers SET state='idle', request_id=NULL WHERE request_id=?", (rid,))
        return _row(c, rid)
    lid = data.get('listing_id')
    follow_up = req['kind'] == 'FOLLOW_UP'
    unit = req['unit']
    capture = unit == 'CAPTURE'
    if unit and not capture:
        lid = req['listing_id']  # a unit works on the listing its parent captured, whatever the agent says
    elif status == 'DONE' and not follow_up:  # the listing must exist and belong to the account that asked
        own = c.execute('SELECT owner_id FROM main.listings WHERE id=?', (lid if isinstance(lid, int) else -1,)).fetchone()
        if own is None or own[0] != req['owner_id']:
            raise ValueError("listing_id: DONE needs the id of the listing written into the requester's account")
    ids = None  # contract items still missing (None: nothing to grade)
    max_attempts, last_status = MAX_ATTEMPTS, 'FAILED'
    if unit in ('RESEARCH_A', 'RESEARCH_B'):  # graded on the run's staged rows, its own items only
        own = set(json.loads(req['missing'] or '[]'))
        ids = [i for i in (staged(dict(req)) if staged else sorted(own)) if i in own]
        max_attempts, last_status = ru.RESEARCH_MAX_ATTEMPTS, 'DONE'
    elif unit == 'ARBITER':
        from . import staging
        ids = staging.unanswered(c, req['parent_id'])
        max_attempts, last_status = 2, 'DONE'  # disputes without a verdict stay UNRESOLVED (flags at merge)
    elif unit == 'MERGE':
        own = set(json.loads(req['missing'] or '[]'))
        ids = [i for i in (missing(req['owner_id'], lid) if missing else sorted(own)) if i in own]
        max_attempts = 1
    elif not follow_up and unit and not capture:
        ids = _unit_ids(missing(req['owner_id'], lid) if missing else sorted(ru.UNIT_OF), unit)  # no grader: fail closed
        if unit == 'INSURANCE' and status == 'FAILED':
            ids = None  # a blocked comparison site or withdrawn consent: no retry loop against an anti-bot wall
    elif not follow_up and capture:
        if status == 'DONE':
            ids = _unit_ids(missing(req['owner_id'], lid), 'CAPTURE') if missing else []
            if not c.execute('SELECT vehicle_id FROM main.listings WHERE id=?', (lid,)).fetchone()[0]:
                ids = ids + ['listing.variant']  # captured but no variant attached: the units cannot start
    elif not follow_up and status == 'DONE' and missing:
        ids = [i for i in missing(req['owner_id'], lid) if i != 'lst.insurance']  # a legacy whole-listing run never quotes
    if ids:
        n = req['attempts'] + 1
        again = n < max_attempts
        what = 'disputes without a verdict' if unit == 'ARBITER' else 'contract items missing'
        note = f'Attempt {n}/{max_attempts}: {len(ids)} {what}: {", ".join(map(str, ids))}'
        if not again and last_status == 'DONE':
            note = f'Closed with {len(ids)} {what}: {", ".join(map(str, ids))}'
        elif not again and unit == 'MERGE':
            note = f'Still missing after merge: {", ".join(ids)}'
        with c:
            c.execute("UPDATE main.research_requests SET status=?, listing_id=?, attempts=?, missing=?, result=?, request_token_hash=NULL, "
                      "claimed_at=CASE WHEN ? THEN NULL ELSE claimed_at END, worker=CASE WHEN ? THEN NULL ELSE worker END, "
                      "finished_at=CASE WHEN ? THEN NULL ELSE datetime('now') END WHERE id=?",
                      ('QUEUED' if again else last_status, lid if isinstance(lid, int) else req['listing_id'], n, json.dumps(ids),
                       (result + '\n' if result else '') + note, again, again, again, rid))
            c.execute("UPDATE main.workers SET state='idle', request_id=NULL WHERE request_id=?", (rid,))
        if not again:
            _closed(c, rid, missing)
        return _row(c, rid)
    blocked = unit == 'INSURANCE' and status == 'FAILED'  # reported blocked or consent withdrawn: final, not graded
    done = status == 'DONE' or bool(unit and not capture and not blocked)  # a unit with nothing missing is done, whatever the agent said
    with c:
        c.execute("UPDATE main.research_requests SET status=?, listing_id=?, result=?, finished_at=datetime('now'), "
                  "request_token_hash=NULL WHERE id=?",
                  ('DONE' if done else 'FAILED', lid if (done or unit) and isinstance(lid, int) else None, result, rid))
        c.execute("UPDATE main.workers SET state='idle', request_id=NULL WHERE request_id=?", (rid,))
    _closed(c, rid, missing)
    return _row(c, rid)


def _blocker(c, rid):
    """The unit other requests wait on when `rid` closes: a MERGE releases through its parent's RESEARCH_A (#253), any other unit is its own."""
    r = _row(c, rid)
    if r['unit'] != 'MERGE':
        return rid
    a = c.execute("SELECT id FROM main.research_requests WHERE parent_id=? AND unit='RESEARCH_A'", (r['parent_id'],)).fetchone()
    return a[0] if a else rid


def _closed(c, rid, missing):
    """A unit-split request reached DONE or FAILED: wake the requests waiting for it, then let its parent go on."""
    r = _row(c, rid)
    if not r['unit']:
        return
    if r['parent_id'] is None:  # the CAPTURE parent: failed ends the request, done opens the first stage
        if r['status'] == 'FAILED':
            return
        with c:
            c.execute("UPDATE main.research_requests SET status='WAITING' WHERE id=?", (rid,))
        advance(c, rid, missing)
        return
    if r['unit'] not in ru.DUAL_UNITS:
        release_shared(c, rid, missing)
    elif r['unit'] == 'MERGE' or c.execute('SELECT status FROM main.research_requests WHERE id=?', (r['parent_id'],)).fetchone()[0] != 'WAITING':
        release_shared(c, _blocker(c, rid), missing)  # the research is open until its MERGE closes (or the request was cancelled)
    advance(c, r['parent_id'], missing)


def _scope(c, listing_id, ids):
    """[[level column, id]] of the levels the missing research items are graded on for the listing's variant (docs 1.2): a missing
    family or gearbox counts as its fallback level. Levels without missing items are not in the scope."""
    v = c.execute('SELECT v.id, v.generation_id, v.engine_id, v.gearbox_id, v.body_style_id, e.family_id engine_family, g.family_id gearbox_family '
                  'FROM main.listings l JOIN main.vehicles v ON v.id=l.vehicle_id JOIN main.engines e ON e.id=v.engine_id '
                  'LEFT JOIN main.gearboxes g ON g.id=v.gearbox_id WHERE l.id=?', (listing_id,)).fetchone()
    if v is None:
        return []
    gearbox = ['gearbox_id', v['gearbox_id']] if v['gearbox_id'] else ['vehicle_id', v['id']]
    level = {'generation': ['generation_id', v['generation_id']], 'engine': ['engine_id', v['engine_id']],
             'engine_family': ['engine_family_id', v['engine_family']] if v['engine_family'] else ['engine_id', v['engine_id']],
             'gearbox': gearbox, 'gearbox_family': ['gearbox_family_id', v['gearbox_family']] if v['gearbox_family'] else gearbox,
             'variant': ['vehicle_id', v['id']], 'body_style': ['body_style_id', v['body_style_id']] if v['body_style_id'] else ['vehicle_id', v['id']]}
    out = []
    for i in ids:
        lv = level.get(research.ITEM[i][1] if i in research.ITEM else None)
        if lv and lv not in out:
            out.append(lv)
    return out


def _overlap(c, parent_id, scope):
    """The RESEARCH_A id of another request whose open research (from its RESEARCH_A until its MERGE closes) shares a level with
    `scope`; a waiting one counts only when it is the older request, so two waiters never wait for each other."""
    mine = {tuple(x) for x in scope}
    for a in c.execute("SELECT a.id, a.scope FROM main.research_requests a JOIN main.research_requests p ON p.id=a.parent_id "
                       "WHERE a.unit='RESEARCH_A' AND a.parent_id<>? AND a.scope IS NOT NULL AND a.status NOT IN ('CANCELLED','SKIPPED','FAILED') "
                       "AND (a.status<>'WAITING' OR a.parent_id<?) AND p.status NOT IN ('CANCELLED','FAILED','DONE') AND NOT EXISTS "
                       "(SELECT 1 FROM main.research_requests m WHERE m.parent_id=a.parent_id AND m.unit='MERGE' "
                       "AND m.status IN ('DONE','SKIPPED','FAILED','CANCELLED')) ORDER BY a.id", (parent_id, parent_id)):
        if mine & {tuple(x) for x in json.loads(a['scope'])}:
            return a['id']
    return None


def _release_pair(c, w, xr, missing):
    """A research pair waiting on another request's RESEARCH_A (#253): recompute what is still missing for its own listing. Nothing:
    both runs DONE. Otherwise both QUEUED, or still WAITING for another open research that overlaps."""
    ids = _unit_ids(missing(w['owner_id'], w['listing_id']), 'RESEARCH_A') if missing else None
    scope = _scope(c, w['listing_id'], ids) if ids else json.loads(w['scope'] or '[]')
    other = _overlap(c, w['parent_id'], scope) if ids is None or ids else None
    with c:
        if ids is not None and not ids:
            c.execute("UPDATE main.research_requests SET status='DONE', shared_id=NULL, missing='[]', result=?, finished_at=datetime('now') "
                      "WHERE parent_id=? AND unit IN ('RESEARCH_A','RESEARCH_B') AND status='WAITING'",
                      (f'Researched by request #{xr["parent_id"] or xr["id"]}', w['parent_id']))
        else:
            c.execute("UPDATE main.research_requests SET status=?, shared_id=?, missing=COALESCE(?, missing), scope=? "
                      "WHERE parent_id=? AND unit IN ('RESEARCH_A','RESEARCH_B') AND status='WAITING'",
                      ('WAITING' if other else 'QUEUED', other, json.dumps(ids) if ids is not None else None, json.dumps(scope), w['parent_id']))
    if ids is not None and not ids:
        advance(c, w['parent_id'], missing)


def release_shared(c, x, missing=None):
    """Requests WAITING for unit x (another request's identical open unit): when x is done they re-check what is still
    missing for their own listing (nothing: done by x); when x failed they fail; when x was cancelled or left gaps the first one
    runs and the rest wait for that one (the open-unit index allows one open unit per level).
    A research pair (#253) waits on the other request's RESEARCH_A and is released by that request's MERGE (see _release_pair);
    a failed merge does not fail the waiters."""
    xr = _row(c, x)
    waiting = [dict(w) for w in c.execute("SELECT id, owner_id, listing_id, unit, parent_id, scope FROM main.research_requests "
                                          "WHERE shared_id=? AND status='WAITING' ORDER BY id", (x,))]
    first = None
    for w in waiting:
        if w['unit'] == 'RESEARCH_A':
            _release_pair(c, w, xr, missing)
        if w['unit'] in ('RESEARCH_A', 'RESEARCH_B'):
            continue  # RESEARCH_B is handled with its RESEARCH_A
        ids = _unit_ids(missing(w['owner_id'], w['listing_id']), w['unit']) if missing and xr['status'] == 'DONE' else None
        with c:
            if xr['status'] == 'DONE' and ids is not None and not ids:
                c.execute("UPDATE main.research_requests SET status='DONE', result=?, finished_at=datetime('now'), missing='[]' WHERE id=?",
                          (f'Researched by request #{x}', w['id']))
            elif xr['status'] == 'FAILED':
                c.execute("UPDATE main.research_requests SET status='FAILED', result=?, finished_at=datetime('now') WHERE id=?",
                          (f'Blocked: request #{x} failed', w['id']))
            elif first is None:
                first = w['id']
                c.execute("UPDATE main.research_requests SET status='QUEUED', shared_id=NULL, missing=? WHERE id=?",
                          (json.dumps(ids or []), w['id']))
            else:
                c.execute("UPDATE main.research_requests SET shared_id=? WHERE id=?", (first, w['id']))
        if missing and (xr['status'] != 'DONE' or ids is not None and not ids or xr['status'] == 'FAILED') and w['id'] != first:
            advance(c, w['parent_id'], missing)


def _insurance_skip(c, parent):
    """Why the INSURANCE unit does not run for this request (None: it runs). Order: reference car (its premium is the owner's
    USER DATA), the account's consent (Settings, preference insurance_worker_quotes), a complete insurance profile."""
    if c.execute('SELECT is_reference FROM main.listings WHERE id=?', (parent['listing_id'],)).fetchone()[0]:
        return "Reference car: the premium is the owner's USER DATA"
    prefs = {r[0]: r[1] for r in c.execute('SELECT preference_key, preference_value FROM main.project_preferences WHERE owner_id=?', (parent['owner_id'],))}
    if not prefs.get('insurance_worker_quotes'):
        return 'Insurance quotes not enabled for this account (Settings)'
    row = c.execute('SELECT * FROM main.project_parameters WHERE owner_id=?', (parent['owner_id'],)).fetchone()
    gaps = quote_profile_gaps(dict(row) if row else {}, prefs)
    return f"Insurance profile incomplete: {', '.join(gaps)}" if gaps else None


def _unit_row(c, p, u, st, ids, result=None, scope=None, shared=None):
    return c.execute("INSERT INTO main.research_requests (owner_id, url, note, requested_by, kind, listing_id, parent_id, unit, shared_id, status, "
                     "missing, scope, result, finished_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (p['owner_id'], p['url'], p['note'], p['requested_by'], p['kind'], p['listing_id'], p['id'], u, shared, st, json.dumps(ids),
                      json.dumps(scope) if scope is not None else None, result, None)).lastrowid


def _dual_stage(c, p, first, ids, missing):
    """Creates the units of one stage of the two-agent flow (#253, docs 1.2). True when something now has to run."""
    from . import staging
    pid = p['id']
    if first == 'RESEARCH_A':
        rids = _unit_ids(ids, 'RESEARCH_A')
        if not rids:  # nothing to research: the whole research block is skipped
            with c:
                for u in ('RESEARCH_A', 'RESEARCH_B', 'ARBITER', 'MERGE'):
                    _unit_row(c, p, u, 'SKIPPED', [], 'Already researched')
            return False
        scope = _scope(c, p['listing_id'], rids)
        other = _overlap(c, pid, scope)
        with c:
            [_unit_row(c, p, u, 'WAITING' if other else 'QUEUED', rids, scope=scope, shared=other) for u in ('RESEARCH_A', 'RESEARCH_B')]
        return True
    if first == 'ARBITER':
        agr = staging.compare(c, pid)
        disputes = [m['id'] for m in staging.dispute_rows(c, pid)]
        text = (f"No material disagreement (agreement {round(agr['agreement'] * 100)} %)" if agr['agreement'] is not None
                else 'Nothing staged by the research runs')
        with c:
            _unit_row(c, p, 'ARBITER', 'QUEUED' if disputes else 'SKIPPED', disputes, None if disputes else text)
        return bool(disputes)
    # MERGE: always after a research that staged something, also when a run closed with gaps
    staged = c.execute('SELECT 1 FROM main.research_matches WHERE parent_id=?', (pid,)).fetchone()
    with c:
        mid = _unit_row(c, p, 'MERGE', 'QUEUED' if staged else 'SKIPPED', _unit_ids(ids, 'RESEARCH_A'), None if staged else 'Nothing staged')
    if not staged:  # the research is closed without a merge: release the requests waiting for it
        release_shared(c, _blocker(c, mid), missing)
    return bool(staged)


def advance(c, parent_id, missing):
    """Creates the next stage of a unit-split request when its units are closed (#218): one child per unit with contract items
    still MISSING (QUEUED, or WAITING for an identical open unit of another request); a unit with nothing missing is SKIPPED
    ("already existed"). When the stages are over the parent is DONE (every unit DONE or SKIPPED) or FAILED."""
    p = _row(c, parent_id)
    if p['unit'] != 'CAPTURE' or p['status'] != 'WAITING':
        return
    kids = [dict(k) for k in c.execute("SELECT * FROM main.research_requests WHERE parent_id=?", (parent_id,))]
    if any(k['status'] in ('QUEUED', 'RUNNING', 'WAITING') for k in kids):
        return
    ids = missing(p['owner_id'], p['listing_id'])
    v = c.execute('SELECT v.id, v.generation_id, v.engine_id, v.gearbox_id FROM main.listings l JOIN main.vehicles v ON v.id=l.vehicle_id '
                  'WHERE l.id=?', (p['listing_id'],)).fetchone()
    have = {k['unit'] for k in kids}
    for stage in _stages(c, parent_id):
        todo = [u for u in stage if u not in have]
        if not todo:
            continue
        if set(stage) <= set(ru.DUAL_UNITS):
            if _dual_stage(c, p, stage[0], ids, missing):
                return
            have |= set(r[0] for r in c.execute('SELECT unit FROM main.research_requests WHERE parent_id=?', (parent_id,)))
            continue
        opened = False
        with c:
            for u in todo:
                uids = _unit_ids(ids, u)
                level = v[ru.LEVEL_COLUMN[u]] if v and u in ru.LEVEL_COLUMN else None
                other = c.execute("SELECT id FROM main.research_requests WHERE unit=? AND level_id=? AND parent_id IS NOT NULL AND parent_id<>? "
                                  "AND status IN ('QUEUED','RUNNING')", (u, level, parent_id)).fetchone() if uids and level is not None else None
                why = _insurance_skip(c, p) if u == 'INSURANCE' and uids else None
                st = 'SKIPPED' if not uids or why else 'WAITING' if other else 'QUEUED'
                c.execute("INSERT INTO main.research_requests (owner_id, url, note, requested_by, kind, listing_id, parent_id, unit, level_id, "
                          "shared_id, status, missing, result, finished_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (p['owner_id'], p['url'], p['note'], p['requested_by'], p['kind'], p['listing_id'], parent_id, u,
                           level if uids else None, other[0] if other else None, st, json.dumps(uids),
                           why or ('Already researched' if st == 'SKIPPED' else None), None))
                opened = opened or st != 'SKIPPED'
        if opened:
            return
    kids = [dict(k) for k in c.execute("SELECT unit, status, missing FROM main.research_requests WHERE parent_id=?", (parent_id,))]
    failed = [k for k in kids if k['status'] not in ('DONE', 'SKIPPED') and k['unit'] != 'INSURANCE']  # a blocked quote never fails a car
    ins = next((k for k in c.execute("SELECT status, result FROM main.research_requests WHERE parent_id=? AND unit='INSURANCE'", (parent_id,))), None)
    open_ins = ' Insurance open: ' + (ins['result'] or ins['status'].lower()) if ins and ins['status'] != 'DONE' else ''
    text = (('Done.' + open_ins) if not failed else
            'Units failed: ' + '; '.join(f"{k['unit']} ({k['status'].lower()}: {', '.join(map(str, json.loads(k['missing'] or '[]')))})" for k in failed))
    with c:
        c.execute("UPDATE main.research_requests SET status=?, result=?, finished_at=datetime('now') WHERE id=?",
                  ('DONE' if not failed else 'FAILED', text, parent_id))


# --- registered workers (issue #141) ---
WORKER_COLS = 'id, name, is_active, created_at, last_seen, state, request_id, last_error, last_error_at'


def request_by_token(c, token):
    """The RUNNING request a per-request token belongs to, while it is not abandoned; None otherwise."""
    return c.execute(f"SELECT * FROM main.research_requests WHERE request_token_hash=? AND status='RUNNING' "
                     f"AND claimed_at >= datetime('now', '-{CLAIM_TIMEOUT_HOURS} hours')", (digest(token or ''),)).fetchone()


def worker_by_token(c, token):
    return c.execute('SELECT * FROM main.workers WHERE token_hash=? AND is_active=1', (digest(token or ''),)).fetchone()


def new_worker(c, name):
    name = str(name or '').strip()
    if not re.fullmatch(r'[\w.-]{2,40}', name):
        raise ValueError('name: 2–40 letters, digits, dots, dashes or underscores')
    raw = secrets.token_urlsafe(32)
    with c:
        wid = c.execute('INSERT INTO main.workers (name, token_hash) VALUES (?,?)', (name, digest(raw))).lastrowid
    return wid, raw


def new_worker_token(c, wid):
    """A new token for the worker; the old one stops working at once. Shown once."""
    raw = secrets.token_urlsafe(32)
    with c:
        if not c.execute('UPDATE main.workers SET token_hash=? WHERE id=?', (digest(raw), wid)).rowcount:
            raise ValueError('No such worker')
    return raw


def set_worker_active(c, wid, active):
    if active not in (0, 1):
        raise ValueError('is_active: 0 or 1')
    with c:
        if not c.execute('UPDATE main.workers SET is_active=? WHERE id=?', (active, wid)).rowcount:
            raise ValueError('No such worker')


def heartbeat(c, wid, data):
    state, error = data.get('state', 'idle'), (str(data.get('error') or '').strip()[-2000:] or None)
    if state not in ('idle', 'working', 'error'):
        raise ValueError('state: idle, working or error')
    with c:
        c.execute("UPDATE main.workers SET last_seen=datetime('now'), state=? WHERE id=?", (state, wid))
        if error:
            c.execute("UPDATE main.workers SET last_error=?, last_error_at=datetime('now') WHERE id=?", (error, wid))


def workers(c):
    """Every worker with `status`: down (no heartbeat for WORKER_DOWN_SECONDS, or deactivated), else its reported state;
    and the request it is on (link, account, listing)."""
    out = []
    for w in c.execute(f"SELECT {', '.join('w.' + x.strip() for x in WORKER_COLS.split(','))}, "
                       f"w.last_seen >= datetime('now', '-{WORKER_DOWN_SECONDS} seconds') AS up, r.url, r.listing_id, r.unit, r.parent_id, u.username "
                       'FROM main.workers w LEFT JOIN main.research_requests r ON r.id=w.request_id '
                       'LEFT JOIN main.users u ON u.id=r.owner_id ORDER BY w.name'):
        d = dict(w)
        d['status'] = 'deactivated' if not d['is_active'] else (d['state'] or 'idle') if d.pop('up') else 'down'
        out.append(d)
    return out
