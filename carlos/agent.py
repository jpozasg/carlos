"""The agent's write API: validation against the real schema, change log, photo storage, quota."""
import hashlib, json, math, os, re, time
from pathlib import Path
from . import config, research
from .auth import _KNOW, _LISTING_CHILDREN, ARCHIVABLE, MODEL, OWNED

# Format of controlled codes written by the agent (English: upper-case statuses, snake_case kinds).
CODE_FORMATS = {('listings', 'listing_status'): r'[A-Z][A-Z /-]*', ('listing_events', 'kind'): r'[a-z][a-z_]*',
                ('vehicles', 'technical_status'): r'[A-Z][A-Z /-]*', ('generations', 'status'): r'[A-Z][A-Z /-]*',
                ('engines', 'status'): r'[A-Z][A-Z /-]*',
                ('reliability_items', 'severity'): r'[A-Z][A-Z /-]*', ('reliability_items', 'frequency_status'): r'[A-Z][A-Z /-]*',
                ('insurance_data', 'premium_status'): r'[A-Z][A-Z /-]*', ('repair_risks', 'status'): r'[A-Z][A-Z /-]*',
                ('tyre_data', 'status'): r'[A-Z][A-Z /-]*', ('tyre_data', 'tyre_type'): r'[A-Z][A-Z /-]*',
                # what a lease rate includes (#127): a comma list without spaces, e.g. 'insurance,tax,gap'
                ('listings', 'lease_includes'): '({0})(,({0}))*'.format('|'.join(config.LEASE_INCLUDES))}
FIXED_CODES = {'valuations.kind': ['sale_today', 'resale_end'], 'unit_costs.category': config.UNIT_COST_CATEGORIES,
               'inspection_items.status': ['PENDING', 'OK', 'PROBLEM', 'N/A'],
               'engines.aspiration': ['NATURALLY ASPIRATED', 'TURBO', 'SUPERCHARGED'],
               'engines.injection': ['PORT', 'DIRECT', 'DUAL', 'CARBURETTOR'],
               'engines.timing_drive': ['CHAIN', 'BELT', 'WET BELT', 'GEAR'], 'engines.fuel_type': config.FUEL_TYPES,
               'maintenance_resets.basis': ['CERTAIN REPAIR', 'SELLER CLAIM', 'DOCUMENTED'],
               'reliability_items.part': config.RELIABILITY_PARTS,
               'maintenance_items.job': config.JOBS, 'repair_risks.job': config.JOBS, 'research_checks.result': ['FOUND', 'NONE FOUND', 'N/A'],
               'listings.lease_kind': config.LEASE_KINDS}
# Tables the agent may write. Those in the second set require source_id on insert.
AGENT_TABLES = {'generations', 'engines', 'vehicles', 'listings', 'sources', 'observations', 'insurance_data', 'tax_data',
                'maintenance_items', 'reliability_items', 'valuations', 'unit_costs', 'inspection_items', 'listing_events',
                'listing_snapshots', 'repair_risks', 'tyre_data', 'maintenance_resets', 'research_checks'}
SOURCE_REQUIRED = {'listings', 'observations', 'insurance_data', 'tax_data', 'maintenance_items',
                   'reliability_items', 'valuations', 'unit_costs', 'listing_snapshots', 'repair_risks', 'tyre_data',
                   'maintenance_resets', 'research_checks'}
JSON_COLUMNS = (('listing_snapshots', 'attributes_json'), ('insurance_data', 'quote_profile'))
RULES = ('null = unknown (never 0); archive outdated rows with PATCH archived=1 (listings: listing_status WITHDRAWN); DELETE only after the owner confirmed it; source quality A–D; free text '
         'in English; knowledge rows attach to exactly one level: vehicle_id (variant), engine_id or generation_id; see AGENTS.md')


class UnsupportedMediaType(Exception):
    pass


class NotFound(Exception):
    pass


class NotAllowed(Exception):
    pass


class QuotaExceeded(Exception):
    pass


def table_columns(c, table):
    return {r['name']: (r['type'].upper(), bool(r['notnull'])) for r in c.execute(f'PRAGMA main.table_info({table})')
            if r['name'] != 'owner_id'}


def check_parents(c, table, data):
    """Every referenced parent row must exist for this owner (the views hide other accounts' rows)."""
    for fk in c.execute(f'PRAGMA main.foreign_key_list({table})'):
        ref_table, col = fk['table'], fk['from']
        if ref_table != 'users' and data.get(col) is not None:
            if c.execute(f'SELECT 1 FROM {ref_table} WHERE id=?', (data[col],)).fetchone() is None:
                raise ValueError(f'{col}={data[col]}: no such {ref_table} row in this account')
    # source_id has no declared foreign key on some tables (#107): check it the same way
    if data.get('source_id') is not None and not any(fk['from'] == 'source_id' for fk in c.execute(f'PRAGMA main.foreign_key_list({table})')):
        if c.execute('SELECT 1 FROM sources WHERE id=?', (data['source_id'],)).fetchone() is None:
            raise ValueError(f"source_id={data['source_id']}: no such sources row in this account")


def clean_row(c, table, data, insert):
    """Validates an agent row against the real schema: known columns, types, '' → NULL, source required, one level."""
    if not isinstance(data, dict) or not data:
        raise ValueError('Expected a non-empty JSON object')
    if 'owner_id' in data:
        raise ValueError('owner_id is set from the account, not by the client')
    cols = table_columns(c, table)
    out = {}
    for tbl, col in JSON_COLUMNS:
        if table == tbl and isinstance(data.get(col), dict):
            data = {**data, col: json.dumps(data[col], ensure_ascii=False)}
    for k, v in data.items():
        if k == 'id' or k not in cols:
            raise ValueError(f'Column not allowed in {table}: {k}')
        typ = cols[k][0]
        if isinstance(v, str) and v.strip() == '':
            v = None
        if v is not None:
            if typ in ('INTEGER', 'REAL'):
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                    raise ValueError(f'{k} must be a finite number (use null when unknown, never 0)')
                if typ == 'INTEGER' and not float(v).is_integer():
                    raise ValueError(f'{k} must be an integer')
            elif not isinstance(v, str):
                raise ValueError(f'{k} must be text')
        out[k] = v
    for (tbl, col), pattern in CODE_FORMATS.items():
        if tbl == table and out.get(col) is not None and not re.fullmatch(pattern, out[col]):
            raise ValueError(f'{col} must be an English code matching {pattern} (see AGENTS.md, controlled codes)')
    for key, allowed in FIXED_CODES.items():
        tbl, col = key.split('.')
        if tbl == table and out.get(col) is not None and out[col] not in allowed:
            raise ValueError(f'{col} must be one of {allowed}')
    if table == 'sources' and out.get('quality') is not None and out['quality'] not in ('A', 'B', 'C', 'D'):
        raise ValueError('quality must be a single letter A, B, C or D')
    if insert and table in SOURCE_REQUIRED and out.get('source_id') is None:
        raise ValueError(f'{table} requires source_id (register the source in sources first)')
    if not insert and table in SOURCE_REQUIRED and 'source_id' in out and out['source_id'] is None:
        raise ValueError('Cannot remove the source of a data point')
    if table == 'research_checks' and 'task' in out and out['task'] not in research.TASKS:
        raise ValueError(f"task must be a research contract item: {sorted(research.TASKS)} (docs/cost-research-protocol.md)")
    if insert and table == 'research_checks' and out.get('contract_version') is None:
        out['contract_version'] = research.CONTRACT_VERSION
    if insert and table == 'reliability_items' and out.get('part') is None:
        raise ValueError(f"reliability_items requires part: one of {config.RELIABILITY_PARTS} (docs/cost-research-protocol.md, step 2)")
    if insert and table in config.SCOPED_TABLES and sum(out.get(k) is not None for k in config.SCOPE_COLUMNS) != 1:
        raise ValueError(f'{table} must attach to exactly one level: vehicle_id (variant), engine_id or generation_id')
    if insert and table == 'sources' and sum(out.get(k) is not None for k in config.SCOPE_COLUMNS) > 1:
        raise ValueError('sources attach to at most one level: vehicle_id, engine_id or generation_id (none = shared)')
    return out


ADMIN_TABLES = set(MODEL) | set(_KNOW) | {'listings'}  # research and listings: the shared worker (admin) only (#109)


def check_writable(c, table, row_id, data):
    """A non-admin agent token writes only its own listing rows and level-free sources; research belongs to the shared
    catalogue, written by admins (issue #109). The UI's own writes (viewing, checklist, decisions) do not pass here."""
    level = any(data.get(k) is not None for k in config.SCOPE_COLUMNS) if isinstance(data, dict) else False
    shared = row_id is not None and table == 'sources' and \
        (c.execute('SELECT owner_id FROM sources WHERE id=?', (row_id,)).fetchone() or [0])[0] is None
    if table in ADMIN_TABLES or (table == 'sources' and (level or shared)):
        raise NotAllowed(f'{table}: research and listings are written by the shared research worker (an admin token); '
                         'request the research instead (AGENTS.md)')


def row_owner(c, table, row_id, data):
    """The account a row belongs to (issue #143): its own owner_id, or its listing's; None for catalogue rows and new rows
    that name no listing."""
    if row_id is not None and (table in OWNED or table in _KNOW):
        r = c.execute(f'SELECT owner_id FROM main.{table} WHERE id=?', (row_id,)).fetchone()
        return r[0] if r else None
    if row_id is not None and table in _LISTING_CHILDREN:
        r = c.execute(f'SELECT l.owner_id FROM main.{table} x JOIN main.listings l ON l.id=x.listing_id WHERE x.id=?', (row_id,)).fetchone()
        return r[0] if r else None
    lid = data.get('listing_id') if isinstance(data, dict) and table in _LISTING_CHILDREN else None
    r = c.execute('SELECT owner_id FROM main.listings WHERE id=?', (lid,)).fetchone() if isinstance(lid, int) else None
    return r[0] if r else None


def resolve_variant(c, data, owner_id):
    """A catalogue variant with the same HSN/TSN is reused instead of duplicated; the account gets a link to it."""
    if not isinstance(data, dict) or not data.get('hsn') or not data.get('tsn'):
        return None
    row = c.execute('SELECT min(id) FROM main.vehicles WHERE owner_id IS NULL AND upper(trim(hsn))=upper(trim(?)) '
                    'AND upper(trim(tsn))=upper(trim(?))', (str(data['hsn']), str(data['tsn']))).fetchone()
    if row[0] is not None:
        with c:
            link(c, owner_id, row[0])
    return row[0]


def link(c, owner_id, vehicle_id):
    """The account sees this catalogue variant (with its engine and generation) from now on."""
    c.execute('INSERT INTO main.catalogue_links (owner_id, vehicle_id) SELECT ?, id FROM main.vehicles WHERE id=? AND owner_id IS NULL '
              'AND NOT EXISTS (SELECT 1 FROM main.catalogue_links WHERE owner_id=? AND vehicle_id=?)', (owner_id, vehicle_id, owner_id, vehicle_id))


def linked_accounts(c, table, row_id):
    """Accounts with a listing on the level this row belongs to (their dossiers show it)."""
    if table in MODEL:
        lv = {{'vehicles': 'vehicle_id', 'engines': 'engine_id', 'generations': 'generation_id'}[table]: row_id}
    elif table in _KNOW or table == 'sources':
        r = c.execute(f'SELECT vehicle_id, engine_id, generation_id FROM main.{table} WHERE id=?', (row_id,)).fetchone()
        lv = dict(r) if r else {}
    else:
        return []
    return [o for (o,) in c.execute('SELECT DISTINCT l.owner_id FROM main.listings l JOIN main.vehicles v ON v.id=l.vehicle_id '
                                    'WHERE v.id=? OR v.engine_id=? OR v.generation_id=?',
                                    (lv.get('vehicle_id'), lv.get('engine_id'), lv.get('generation_id')))]


def agent_write(c, table, row_id, data, user_id, admin=False, actor=None):
    """Inserts (row_id None) or updates a row of this account in one transaction and records it in change_log.
    Admin inserts of generations, engines, variants and level sources go to the shared catalogue (owner_id NULL);
    knowledge rows follow their level, except an account's own premium or USER DATA figure, which stays private.
    `actor` is who wrote it (the admin acting for the account), for the change log."""
    data = clean_row(c, table, data, insert=row_id is None)
    check_parents(c, table, data)
    with c:
        if row_id is None:
            if table in OWNED:
                catalogue = admin and (table in MODEL or table == 'sources' and any(data.get(k) is not None for k in config.SCOPE_COLUMNS))
                data['owner_id'] = None if catalogue else user_id
            elif table in _KNOW and ('USER DATA' in (data.get('status'), data.get('premium_status')) or data.get('annual_premium_eur') is not None):
                data['owner_id'] = user_id
            cur = c.execute(f'INSERT INTO main.{table} ({",".join(data)}) VALUES ({",".join("?" * len(data))})', list(data.values()))
            row_id, old = cur.lastrowid, None
        else:
            view = f'{table}_all' if table in ARCHIVABLE else table  # archived rows can be restored (PATCH archived=0)
            old = c.execute(f'SELECT * FROM {view} WHERE id=?', (row_id,)).fetchone()  # the owner's view: others' rows are "not found"
            if old is None:
                raise NotFound(f'{table} id={row_id} does not exist')
            c.execute(f'UPDATE main.{table} SET {",".join(f"{k}=?" for k in data)} WHERE id=?', [*data.values(), row_id])
            old = json.dumps(dict(old), ensure_ascii=False)
        if table == 'listings' and data.get('vehicle_id') is not None:
            link(c, user_id, data['vehicle_id'])
        c.execute('INSERT INTO main.change_log (table_name,row_id,action,old_json,new_json,user_id) VALUES (?,?,?,?,?,?)',
                  (table, row_id, 'update' if old else 'insert', old, json.dumps(data, ensure_ascii=False), actor or user_id))
    return row_id


# A listing is deleted together with its own rows, children first (photos before captures, resets before costs).
LISTING_CHILDREN_DELETE_ORDER = ('maintenance_resets', 'inspection_items', 'unit_costs', 'valuations', 'listing_events',
                                 'listing_media', 'listing_snapshots')


def references(c, table, row_id):
    """Rows of any table that point at main.<table>(id): declared foreign keys, plus source_id for sources."""
    out = []
    for (t,) in c.execute("SELECT name FROM main.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        cols = {fk['from'] for fk in c.execute(f'PRAGMA main.foreign_key_list({t})') if fk['table'] == table}
        if table == 'sources' and t != 'sources':
            cols |= {r['name'] for r in c.execute(f'PRAGMA main.table_info({t})') if r['name'] == 'source_id'}
        for col in cols:
            n = c.execute(f'SELECT count(*) FROM main.{t} WHERE {col}=?', (row_id,)).fetchone()[0]
            if n:
                out.append(f'{t}.{col} ({n})')
    return out


def agent_delete(c, table, row_id, user_id):
    """Deletes a row of this account (issue #58) and records it in change_log. Agents call this only after the owner
    confirmed it in the session (AGENTS.md); archiving (PATCH archived=1) is the default for outdated rows.
    A listing goes together with its own rows and photo files; any other row is refused while something references it."""
    view = f'{table}_all' if table in ARCHIVABLE else table
    old = c.execute(f'SELECT * FROM {view} WHERE id=?', (row_id,)).fetchone()  # the owner's view: others' rows are "not found"
    if old is None:
        raise NotFound(f'{table} id={row_id} does not exist')
    files, removed = [], {}
    with c:
        if table == 'listings':
            files = [r['file_path'] for r in c.execute('SELECT file_path FROM main.listing_media WHERE listing_id=?', (row_id,))]
            for child in LISTING_CHILDREN_DELETE_ORDER:
                removed[child] = c.execute(f'DELETE FROM main.{child} WHERE listing_id=?', (row_id,)).rowcount
        refs = references(c, table, row_id)
        if refs:
            raise ValueError(f'{table} id={row_id} is still referenced by {", ".join(refs)}: delete or re-point those first')
        c.execute(f'DELETE FROM main.{table} WHERE id=?', (row_id,))
        c.execute('INSERT INTO main.change_log (table_name,row_id,action,old_json,new_json,user_id) VALUES (?,?,?,?,?,?)',
                  (table, row_id, 'delete', json.dumps(dict(old), ensure_ascii=False),
                   json.dumps({'deleted': True, 'removed_children': {k: v for k, v in removed.items() if v}}), user_id))
    for f in files:  # after the commit: a failed delete keeps its photos
        path = config.MEDIA_DIR / f
        path.unlink(missing_ok=True)
        if path.parent != config.MEDIA_DIR and path.parent.is_dir() and not any(path.parent.iterdir()):
            path.parent.rmdir()
    return removed


_STORAGE = {'at': 0.0, 'value': None}


def storage_usage(max_age=60):
    """Bytes used by the installation (code and data directories), grouped by top-level folder or file.
    Cached for `max_age` seconds: the directory walk grows with the photo archive and git history."""
    if _STORAGE['value'] is not None and time.time() - _STORAGE['at'] < max_age:
        return _STORAGE['value']
    usage = {}
    seen = set()
    for base in (config.ROOT, config.DATA_DIR):
        for dirpath, _, files in os.walk(base):
            if dirpath in seen:
                continue
            seen.add(dirpath)
            try:
                top = Path(dirpath).relative_to(base).parts[:1]
            except ValueError:
                top = ()
            for f in files:
                key = top[0] if top else f
                try:
                    usage[key] = usage.get(key, 0) + os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
    _STORAGE.update(at=time.time(), value={'total_bytes': sum(usage.values()), 'limit_bytes': config.STORAGE_LIMIT,
                                           'budget_bytes': config.STORAGE_BUDGET, 'by_item': dict(sorted(usage.items(), key=lambda kv: -kv[1]))})
    return _STORAGE['value']


def save_media(c, listing_id, body, query):
    """Stores a listing photo in media/<listing>/<sha256>.<ext>; deduplicates and respects the quota."""
    if not body:
        raise ValueError('Empty body: send the image bytes')
    if len(body) > config.MAX_IMAGE_BYTES:
        raise ValueError(f'Image is {len(body)} bytes; maximum {config.MAX_IMAGE_BYTES}. Download a smaller version (~1024 px)')
    kind = next((v for magic, v in config.IMAGE_TYPES.items() if body.startswith(magic)), None)
    if kind is None or (kind[1] == 'webp' and body[8:12] != b'WEBP'):
        raise ValueError('Only JPEG, PNG or WebP are accepted')
    if c.execute('SELECT 1 FROM listings WHERE id=?', (listing_id,)).fetchone() is None:
        raise NotFound(f'listings id={listing_id} does not exist')
    digest = hashlib.sha256(body).hexdigest()
    dup = c.execute('SELECT id FROM listing_media WHERE listing_id=? AND sha256=?', (listing_id, digest)).fetchone()
    if dup:
        return dup['id'], False
    if storage_usage(max_age=0)['total_bytes'] + len(body) > config.STORAGE_BUDGET:
        raise QuotaExceeded('Storage budget exhausted (450 of 500 MB); free space before archiving more photos')
    snapshot = query.get('snapshot_id', [None])[0]
    if snapshot and c.execute('SELECT 1 FROM listing_snapshots WHERE id=? AND listing_id=?', (int(snapshot), listing_id)).fetchone() is None:
        raise ValueError(f'snapshot_id={snapshot} is not a capture of listing {listing_id}')
    rel = f'{listing_id}/{digest}.{kind[1]}'
    path = config.MEDIA_DIR / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    try:
        with c:
            cur = c.execute('INSERT INTO main.listing_media (listing_id, snapshot_id, original_url, file_path, mime, bytes, sha256) '
                            'VALUES (?,?,?,?,?,?,?)', (listing_id, int(snapshot) if snapshot else None,
                                                      query.get('url', [None])[0], rel, kind[0], len(body), digest))
            c.execute('INSERT INTO main.change_log (table_name,row_id,action,new_json) VALUES (?,?,?,?)',
                      ('listing_media', cur.lastrowid, 'insert', json.dumps({'file_path': rel, 'bytes': len(body)})))
    except Exception:
        # without a DB row the file would be orphaned; but if a concurrent upload already registered it, keep it
        if c.execute('SELECT 1 FROM listing_media WHERE file_path=?', (rel,)).fetchone() is None:
            path.unlink(missing_ok=True)
        raise
    return cur.lastrowid, True
