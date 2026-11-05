"""Research requests (issue #113): accounts queue listing URLs; the shared worker (admin token) claims the oldest,
researches it with docs/prompts/research-car.md writing as the requester (X-Carlos-Account) and finishes it.
Every query names main.research_requests and filters by owner itself: the table is not shadowed by auth.scope."""
import re

MAX_OPEN = 5             # QUEUED + RUNNING per account: keeps one account from flooding the shared worker
CLAIM_TIMEOUT_HOURS = 3  # a RUNNING request older than this is taken to be abandoned (worker crashed) and can be claimed again
COLS = 'id, owner_id, url, note, status, requested_at, claimed_at, finished_at, worker, listing_id, result'


def clean_url(url):
    url = str(url or '').strip()
    if len(url) > 500 or not re.fullmatch(r'https?://[^\s/]+\.[^\s/]+(/\S*)?', url):
        raise ValueError('url: an http(s) link to the listing, at most 500 characters')
    return url


def mine(c, uid):
    return [dict(r) for r in c.execute(f'SELECT {COLS} FROM main.research_requests WHERE owner_id=? ORDER BY id DESC', (uid,))]


def create(c, uid, data):
    url, note = clean_url(data.get('url')), (str(data.get('note') or '').strip()[:1000] or None)
    with c:
        open_urls = [r[0] for r in c.execute("SELECT url FROM main.research_requests WHERE owner_id=? AND status IN ('QUEUED','RUNNING')", (uid,))]
        if url in open_urls:
            raise ValueError('This link is already waiting to be researched')
        if len(open_urls) >= MAX_OPEN:
            raise ValueError(f'At most {MAX_OPEN} requests can wait at a time; cancel one or wait until the worker finishes one')
        rid = c.execute('INSERT INTO main.research_requests (owner_id, url, note) VALUES (?,?,?)', (uid, url, note)).lastrowid
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


def claim(c, worker):
    """Takes the oldest QUEUED request (or an abandoned RUNNING one) for `worker`, atomically; None when idle."""
    worker = str(worker or 'worker').strip()[:60]
    c.isolation_level = None  # manual transaction: BEGIN IMMEDIATE takes the write lock before reading, so two workers never get the same row
    try:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute(f"SELECT id FROM main.research_requests WHERE status='QUEUED' OR status='RUNNING' AND claimed_at < "
                        f"datetime('now', '-{CLAIM_TIMEOUT_HOURS} hours') ORDER BY id LIMIT 1").fetchone()
        if row:
            c.execute("UPDATE main.research_requests SET status='RUNNING', claimed_at=datetime('now'), worker=? WHERE id=?", (worker, row[0]))
        c.execute('COMMIT')
    except BaseException:
        c.execute('ROLLBACK'); raise
    finally:
        c.isolation_level = ''
    return dict(c.execute(f'SELECT {COLS} FROM main.research_requests WHERE id=?', (row[0],)).fetchone()) if row else None


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
        c.execute("UPDATE main.research_requests SET status=?, listing_id=?, result=?, finished_at=datetime('now') WHERE id=?",
                  (status, lid if status == 'DONE' else None, result, rid))
    return dict(c.execute(f'SELECT {COLS} FROM main.research_requests WHERE id=?', (rid,)).fetchone())
