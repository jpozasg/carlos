"""An account's own data: the JSON export a person downloads from Settings, and the erasure an admin confirms with the
account's username (writes the export into the data directory first). Rows are chosen by owner: owner_id, or the
listing, research request or request of the account. Shared catalogue rows (owner_id NULL) are never touched."""
import datetime, json, os, shutil
from .agent import NotFound

# Tables that are not the account's data: sign-in secrets, the operator's own records and the worker registrations
EXCLUDED = ('users', 'sessions', 'invites', 'change_log', 'workers')
# A row that is not the account's but points at one of its rows keeps the row and loses the link (who queued it, who wrote it)
NULLABLE_LINKS = {('change_log', 'user_id'), ('change_log', 'request_id'), ('invites', 'created_by'), ('research_requests', 'requested_by'),
                  ('workers', 'request_id')}
ERASED = '{"erased": true}'  # new_json is NOT NULL: the change log keeps the row and its shape, not the values
VIA = {'listing_id': 'listings', 'request_id': 'research_requests', 'parent_id': 'research_requests'}  # owned through a parent row


def _tables(c):
    return [r[0] for r in c.execute("SELECT name FROM main.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def account_tables(c):
    """(table, WHERE clause with one parameter: the account id) for every table that holds the account's rows. Rows owned
    through a parent (a listing's, a request's) come first: their parent is still there when the WHERE clause reads it."""
    owned, via = [], []
    for t in _tables(c):
        if t in EXCLUDED:
            continue
        cols = [r[1] for r in c.execute(f'PRAGMA main.table_info({t})')]
        if 'owner_id' in cols:
            owned.append((t, 'owner_id=?'))
        elif col := next((k for k in VIA if k in cols), None):
            via.append((t, f'{col} IN (SELECT id FROM main.{VIA[col]} WHERE owner_id=?)'))
    return via + owned


def export(c, uid):
    """Every row of the account as one JSON-ready dict. Hashes (sign-in and request tokens) are left out; photos are
    listed by file name only, the image files stay in the data directory."""
    user = c.execute('SELECT id, username, role, created_at FROM main.users WHERE id=?', (uid,)).fetchone()
    if user is None:
        raise NotFound('No such account')
    tables = {}
    for t, where in account_tables(c):
        cur = c.execute(f'SELECT * FROM main.{t} WHERE {where} ORDER BY rowid', (uid,))
        names = [d[0] for d in cur.description]
        tables[t] = [{k: v for k, v in zip(names, r) if not k.endswith('_hash')} for r in cur]
    return {'account': dict(zip(('id', 'username', 'role', 'created_at'), user)),
            'exported_at': datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None).isoformat(sep=' '),
            'note': 'Your own rows. Passwords and tokens are not included; photos appear by file name only.',
            'tables': tables}


def erase(c, uid, typed, admin_id, data_dir, media_dir, md_dir):
    """Deletes one account after the export is written to DATA_DIR/exports. Refuses the admin's own account, a wrong
    username, and any row of another account that would be left pointing at a deleted row (nothing is changed then)."""
    user = c.execute('SELECT id, username FROM main.users WHERE id=?', (uid,)).fetchone()
    if user is None:
        raise NotFound('No such account')
    if uid == admin_id:
        raise ValueError('You cannot erase your own account')
    if str(typed or '') != user[1]:
        raise ValueError("Type the account's username exactly to confirm the erasure")
    doc = export(c, uid)
    folder = data_dir / 'exports'
    folder.mkdir(parents=True, exist_ok=True)
    name = f'account-{uid}-{datetime.datetime.now():%Y%m%d-%H%M%S}.json'
    fd = os.open(folder / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # private: the export holds the account's data
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, default=str)
    lids = [r[0] for r in c.execute('SELECT id FROM main.listings WHERE owner_id=?', (uid,))]
    deleted = {}
    with c:  # one transaction; deferred foreign keys: the order of the deletes does not matter, the check at the end does
        c.execute('PRAGMA defer_foreign_keys=ON')
        c.execute('BEGIN')  # explicit: an implicit BEGIN after the pragma would switch the deferral off again
        for t, where in account_tables(c):  # the change log keeps its rows; the values of the account's rows go
            c.execute(f'UPDATE main.change_log SET old_json=NULL, new_json=? WHERE table_name=? AND row_id IN (SELECT id FROM main.{t} WHERE {where})', (ERASED, t, uid))
        c.execute('UPDATE main.change_log SET old_json=NULL, new_json=? WHERE user_id=? OR request_id IN '
                  '(SELECT id FROM main.research_requests WHERE owner_id=?)', (ERASED, uid, uid))
        for t, where in account_tables(c):
            deleted[t] = c.execute(f'DELETE FROM main.{t} WHERE {where}', (uid,)).rowcount
        deleted['sessions'] = c.execute('DELETE FROM main.sessions WHERE user_id=?', (uid,)).rowcount
        deleted['invites'] = c.execute('DELETE FROM main.invites WHERE user_id=?', (uid,)).rowcount
        c.execute('DELETE FROM main.users WHERE id=?', (uid,))
        for table, rowid, _parent, fkid in c.execute('PRAGMA main.foreign_key_check').fetchall():
            col = next(r[3] for r in c.execute(f'PRAGMA main.foreign_key_list({table})') if r[0] == fkid)
            if (table, col) not in NULLABLE_LINKS:
                raise ValueError(f'{table}.{col} of another row still points at this account: erase refused, nothing changed')
            c.execute(f'UPDATE main.{table} SET {col}=NULL WHERE rowid=?', (rowid,))
    for lid in lids:  # the photos of the account's cars, then its dossiers (the database no longer names them)
        shutil.rmtree(media_dir / str(lid), ignore_errors=True)
    shutil.rmtree(md_dir / str(uid), ignore_errors=True)
    return {'id': uid, 'username': user[1], 'export': f'exports/{name}', 'deleted': {t: n for t, n in deleted.items() if n}}
