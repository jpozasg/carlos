"""Research requests (issue #113): accounts queue listing URLs; the shared worker (admin token) claims the oldest,
researches it with docs/prompts/research-car.md writing as the requester (X-Carlos-Account) and finishes it.
Every query names main.research_requests and filters by owner itself: the table is not shadowed by auth.scope."""
import re, secrets
from .auth import digest

MAX_OPEN = 5             # QUEUED + RUNNING per account: keeps one account from flooding the shared worker
WORKER_DOWN_SECONDS = 180  # a worker polls every 60 s: no heartbeat for three polls = down (issue #141)
CLAIM_TIMEOUT_HOURS = 3  # a RUNNING request older than this is taken to be abandoned (worker crashed) and can be claimed again
COLS = 'id, owner_id, url, note, status, requested_at, claimed_at, finished_at, worker, listing_id, result, requested_by'


def clean_url(url):
    url = str(url or '').strip()
    if len(url) > 500 or not re.fullmatch(r'https?://[^\s/]+\.[^\s/]+(/\S*)?', url):
        raise ValueError('url: an http(s) link to the listing, at most 500 characters')
    return url


def mine(c, uid):
    return [dict(r) for r in c.execute(f'SELECT {COLS} FROM main.research_requests WHERE owner_id=? ORDER BY id DESC', (uid,))]


def create(c, uid, data, by=None):
    """by: the admin who queued it for the account (issue #139); None when the account asked itself."""
    url, note = clean_url(data.get('url')), (str(data.get('note') or '').strip()[:1000] or None)
    with c:
        open_urls = [r[0] for r in c.execute("SELECT url FROM main.research_requests WHERE owner_id=? AND status IN ('QUEUED','RUNNING')", (uid,))]
        if url in open_urls:
            raise ValueError('This link is already waiting to be researched')
        if len(open_urls) >= MAX_OPEN:
            raise ValueError(f'At most {MAX_OPEN} requests can wait at a time; cancel one or wait until the worker finishes one')
        rid = c.execute('INSERT INTO main.research_requests (owner_id, url, note, requested_by) VALUES (?,?,?,?)', (uid, url, note, by)).lastrowid
    return rid


def cancel(c, uid, rid):
    with c:
        n = c.execute("UPDATE main.research_requests SET status='CANCELLED', finished_at=datetime('now') "
                      "WHERE id=? AND owner_id=? AND status='QUEUED'", (rid, uid)).rowcount
    if not n:
        raise ValueError('Only your own requests still waiting in the queue can be cancelled')


def everything(c):
    """The whole queue with who asked (admins)."""
    return [dict(r) for r in c.execute(f'SELECT {", ".join("r." + x.strip() for x in COLS.split(","))}, u.username '
                                       'FROM main.research_requests r JOIN main.users u ON u.id=r.owner_id ORDER BY r.id DESC LIMIT 500')]


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
                        f"datetime('now', '-{CLAIM_TIMEOUT_HOURS} hours') ORDER BY id LIMIT 1").fetchone()
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
    return {**dict(c.execute(f'SELECT {COLS} FROM main.research_requests WHERE id=?', (row[0],)).fetchone()), 'request_token': raw} if row else None


def finish(c, rid, data):
    status, result = data.get('status'), (str(data.get('result') or '').strip()[-4000:] or None)
    if status not in ('DONE', 'FAILED'):
        raise ValueError('status: DONE or FAILED')
    req = c.execute("SELECT owner_id, status FROM main.research_requests WHERE id=?", (rid,)).fetchone()
    if req is None or req['status'] != 'RUNNING':
        raise ValueError('Only a RUNNING request can be finished')
    lid = data.get('listing_id')
    if status == 'DONE':  # the listing must exist and belong to the account that asked
        own = c.execute('SELECT owner_id FROM main.listings WHERE id=?', (lid if isinstance(lid, int) else -1,)).fetchone()
        if own is None or own[0] != req['owner_id']:
            raise ValueError("listing_id: DONE needs the id of the listing written into the requester's account")
    with c:
        c.execute("UPDATE main.research_requests SET status=?, listing_id=?, result=?, finished_at=datetime('now'), "
                  "request_token_hash=NULL WHERE id=?", (status, lid if status == 'DONE' else None, result, rid))  # the request token dies
        c.execute("UPDATE main.workers SET state='idle', request_id=NULL WHERE request_id=?", (rid,))
    return dict(c.execute(f'SELECT {COLS} FROM main.research_requests WHERE id=?', (rid,)).fetchone())


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
                       f"w.last_seen >= datetime('now', '-{WORKER_DOWN_SECONDS} seconds') AS up, r.url, r.listing_id, u.username "
                       'FROM main.workers w LEFT JOIN main.research_requests r ON r.id=w.request_id '
                       'LEFT JOIN main.users u ON u.id=r.owner_id ORDER BY w.name'):
        d = dict(w)
        d['status'] = 'deactivated' if not d['is_active'] else (d['state'] or 'idle') if d.pop('up') else 'down'
        out.append(d)
    return out
