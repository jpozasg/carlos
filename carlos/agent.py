"""The agent's write API: validation against the real schema, change log, photo storage, quota."""
import hashlib, json, math, os, re, time
from pathlib import Path
from . import config
from .auth import OWNED

# Format of controlled codes written by the agent (English: upper-case statuses, snake_case kinds).
CODE_FORMATS = {('listings', 'listing_status'): r'[A-Z][A-Z /-]*', ('listing_events', 'kind'): r'[a-z][a-z_]*',
                ('vehicles', 'technical_status'): r'[A-Z][A-Z /-]*', ('generations', 'status'): r'[A-Z][A-Z /-]*',
                ('engines', 'status'): r'[A-Z][A-Z /-]*',
                ('reliability_items', 'severity'): r'[A-Z][A-Z /-]*', ('reliability_items', 'frequency_status'): r'[A-Z][A-Z /-]*',
                ('insurance_data', 'premium_status'): r'[A-Z][A-Z /-]*', ('repair_risks', 'status'): r'[A-Z][A-Z /-]*',
                ('tyre_data', 'status'): r'[A-Z][A-Z /-]*', ('tyre_data', 'tyre_type'): r'[A-Z][A-Z /-]*'}
FIXED_CODES = {'valuations.kind': ['sale_today', 'resale_end'], 'unit_costs.category': config.UNIT_COST_CATEGORIES,
               'inspection_items.status': ['PENDING', 'OK', 'PROBLEM', 'N/A'],
               'engines.aspiration': ['NATURALLY ASPIRATED', 'TURBO', 'SUPERCHARGED'],
               'engines.injection': ['PORT', 'DIRECT', 'DUAL', 'CARBURETTOR'],
               'engines.timing_drive': ['CHAIN', 'BELT', 'WET BELT', 'GEAR'],
               'maintenance_resets.basis': ['CERTAIN REPAIR', 'SELLER CLAIM', 'DOCUMENTED']}
# Tables the agent may write. Those in the second set require source_id on insert.
AGENT_TABLES = {'generations', 'engines', 'vehicles', 'listings', 'sources', 'observations', 'insurance_data', 'tax_data',
                'maintenance_items', 'reliability_items', 'valuations', 'unit_costs', 'inspection_items', 'listing_events',
                'listing_snapshots', 'repair_risks', 'tyre_data', 'maintenance_resets'}
SOURCE_REQUIRED = {'listings', 'observations', 'insurance_data', 'tax_data', 'maintenance_items',
                   'reliability_items', 'valuations', 'unit_costs', 'listing_snapshots', 'repair_risks', 'tyre_data',
                   'maintenance_resets'}
JSON_COLUMNS = (('listing_snapshots', 'attributes_json'), ('insurance_data', 'quote_profile'))
RULES = ('null = unknown (never 0); no DELETE: archive with PATCH (e.g. listing_status); source quality A–D; free text '
         'in English; knowledge rows attach to exactly one level: vehicle_id (variant), engine_id or generation_id; see AGENTS.md')


class UnsupportedMediaType(Exception):
    pass


class NotFound(Exception):
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
    if insert and table in config.SCOPED_TABLES and sum(out.get(k) is not None for k in config.SCOPE_COLUMNS) != 1:
        raise ValueError(f'{table} must attach to exactly one level: vehicle_id (variant), engine_id or generation_id')
    if insert and table == 'sources' and sum(out.get(k) is not None for k in config.SCOPE_COLUMNS) > 1:
        raise ValueError('sources attach to at most one level: vehicle_id, engine_id or generation_id (none = shared)')
    return out


def agent_write(c, table, row_id, data, user_id):
    """Inserts (row_id None) or updates a row of this account in one transaction and records it in change_log."""
    data = clean_row(c, table, data, insert=row_id is None)
    check_parents(c, table, data)
    with c:
        if row_id is None:
            if table in OWNED:
                data['owner_id'] = user_id
            cur = c.execute(f'INSERT INTO main.{table} ({",".join(data)}) VALUES ({",".join("?" * len(data))})', list(data.values()))
            row_id, old = cur.lastrowid, None
        else:
            old = c.execute(f'SELECT * FROM {table} WHERE id=?', (row_id,)).fetchone()  # the owner's view: others' rows are "not found"
            if old is None:
                raise NotFound(f'{table} id={row_id} does not exist')
            c.execute(f'UPDATE main.{table} SET {",".join(f"{k}=?" for k in data)} WHERE id=?', [*data.values(), row_id])
            old = json.dumps(dict(old), ensure_ascii=False)
        c.execute('INSERT INTO main.change_log (table_name,row_id,action,old_json,new_json,user_id) VALUES (?,?,?,?,?,?)',
                  (table, row_id, 'update' if old else 'insert', old, json.dumps(data, ensure_ascii=False), user_id))
    return row_id


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
