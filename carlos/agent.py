"""The agent's write API: validation against the real schema, change log, photo storage, quota."""
import hashlib, json, math, os, re, time
from pathlib import Path
from . import config, research
from .auth import SOURCE_TABLES, _KNOW, _LISTING_CHILDREN, ARCHIVABLE, MODEL, OWNED

# Format of controlled codes written by the agent (English: upper-case statuses, snake_case kinds).
CODE_FORMATS = {('listings', 'listing_status'): r'[A-Z][A-Z /-]*', ('listing_events', 'kind'): r'[a-z][a-z_]*',
                ('vehicles', 'technical_status'): r'[A-Z][A-Z /-]*', ('generations', 'status'): r'[A-Z][A-Z /-]*',
                ('engines', 'status'): r'[A-Z][A-Z /-]*',
                # KBA reference ('KBA-14729R') or '<MAKE>-<YYYY-MM>-<COMPONENT_CODE>'; never 'UNKNOWN-...' or prose (#333)
                ('recalls', 'code'): r'\s*(?!(?i:unknown))[A-Za-z0-9][A-Za-z0-9_./-]*\s*',
                ('reliability_items', 'severity'): r'[A-Z][A-Z /-]*', ('reliability_items', 'frequency_status'): r'[A-Z][A-Z /-]*',
                ('insurance_data', 'premium_status'): r'[A-Z][A-Z /-]*', ('repair_risks', 'status'): r'[A-Z][A-Z /-]*',
                ('tyre_data', 'status'): r'[A-Z][A-Z /-]*', ('tyre_data', 'tyre_type'): r'[A-Z][A-Z /-]*',
                **{(t, col): r'\d{4}(-(0[1-9]|1[0-2]))?' for t in config.WINDOWED_TABLES for col in ('applies_from', 'applies_to')},
                ('listings', 'build_date'): r'\d{4}(-(0[1-9]|1[0-2]))?', ('faults', 'usage_flags'): r'[A-Z_]+(,[A-Z_]+)*',
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
               'listings.lease_kind': config.LEASE_KINDS, 'gearboxes.type': config.GEARBOX_TYPES,
               'faults.part': config.RELIABILITY_PARTS, 'faults.consequence': config.FAULT_CONSEQUENCES,
               'faults.existence': ['CONFIRMED', 'REPORTED'], 'faults.frequency_band': list(config.FREQUENCY_BANDS),
               'faults.shape': config.FAULT_SHAPES, 'faults.component_code': config.FAULT_COMPONENT_CODES,
               'review_flags.kind': ['STATS_MISMATCH', 'SOURCES_DISAGREE', 'FIX_UNCERTAIN', 'OTHER'],
               'review_flags.status': ['OPEN', 'CLEARED'], 'flag_reviews.outcome': ['CONFIRMED', 'RESOLVED'], 'faults.probability_basis': ['STATISTIC', 'EXPERT', 'ESTIMATE'],
               'recalls.part': config.RELIABILITY_PARTS,
               'maintenance_items.kind': ['JOB', 'WEAR'], 'listing_history.status': ['DONE', 'PRESENT', 'OPEN', 'NOT AFFECTED'],
               'listing_history.evidence': ['DOCUMENTED', 'SELLER CLAIM', 'OBSERVED', 'VIN CHECK'],
               'listing_history.category': ['maintenance', 'repairs'], 'listing_history.job': config.JOBS}
# Tables the agent may write. Those in the second set require source_id on insert.
AGENT_TABLES = {'generations', 'engines', 'vehicles', 'listings', 'sources', 'observations', 'insurance_data', 'tax_data',
                'maintenance_items', 'reliability_items', 'valuations', 'unit_costs', 'inspection_items', 'listing_events',
                'listing_snapshots', 'repair_risks', 'tyre_data', 'maintenance_resets', 'research_checks',
                # target design (#174): levels, knowledge, listing facts
                'engine_families', 'gearbox_families', 'gearboxes', 'body_styles', 'options', 'faults', 'recalls',
                'market_models', 'listing_history', 'listing_quotes', 'listing_options',
                'review_flags', 'flag_reviews', 'source_keys', 'source_ratings'}
SOURCE_REQUIRED = {'source_keys', 'source_ratings', 'listings', 'observations', 'insurance_data', 'tax_data', 'maintenance_items',
                   'reliability_items', 'valuations', 'unit_costs', 'listing_snapshots', 'repair_risks', 'tyre_data',
                   'maintenance_resets', 'research_checks', 'faults', 'recalls', 'market_models', 'listing_quotes'}
JSON_COLUMNS = (('listing_snapshots', 'attributes_json'), ('insurance_data', 'quote_profile'), ('listing_quotes', 'quote_profile'),
                ('faults', 'curve_km'), ('faults', 'curve_age'), ('research_checks', 'named_codes'), ('market_models', 'band_counts'), ('market_models', 'sample_json'))
RULES = ('null = unknown (never 0); archive outdated rows with PATCH archived=1 (listings: listing_status WITHDRAWN); DELETE only after the owner confirmed it; source quality A–D; free text '
         'in English; knowledge rows attach to exactly one level (vehicle_id, engine_id, generation_id, gearbox_id, engine_family_id, '
         'gearbox_family_id, body_style_id or option_id; a maintenance row without one is a global default); see AGENTS.md')


class UnsupportedMediaType(Exception):
    pass


class NotFound(Exception):
    pass


class NotAllowed(Exception):
    pass


class Conflict(Exception):
    """409: the row would duplicate an existing one (#221); `payload` is the JSON answer."""
    def __init__(self, payload):
        super().__init__(payload['error']); self.payload = payload


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


def curve_points(raw):
    """A fault's cumulative probability curve (#174): JSON [[x, share], …] with x (km or years) rising and the share
    0–1 never falling. Returns the points; ValueError otherwise."""
    pts = json.loads(raw) if isinstance(raw, str) else raw
    ok = isinstance(pts, list) and pts and all(isinstance(p, list) and len(p) == 2 and all(isinstance(v, (int, float)) for v in p) for p in pts)
    if not ok or any(not 0 <= p[1] <= 1 or p[0] < 0 for p in pts) or \
            any(b[0] <= a[0] or b[1] < a[1] for a, b in zip(pts, pts[1:])):
        raise ValueError('a curve is [[x, share], …]: x (km or years) rising, share between 0 and 1 and never falling')
    return pts


def clear_if_agreed(c, flag_id):
    """A flag is cleared only when two independent reviews (different workers or runs) resolve it with the same conclusion
    (owner, 2026-11-06, #168); a CONFIRMED review or a lone resolution keeps it open."""
    rows_ = c.execute("SELECT conclusion, count(DISTINCT worker) FROM main.flag_reviews WHERE flag_id=? AND outcome='RESOLVED' "
                      "GROUP BY conclusion", (flag_id,)).fetchall()
    if any(n >= 2 for _, n in rows_):
        c.execute("UPDATE main.review_flags SET status='CLEARED', cleared_at=datetime('now') WHERE id=? AND status='OPEN'", (flag_id,))


def fault_checks(c, out):
    """The fault probability method (#168): valid curves; a band fills its central range; 'systemic' needs a manufacturer
    trace; a fault whose source is a forum (quality D) is never above 'common'."""
    for col in ('curve_km', 'curve_age'):
        if out.get(col) is not None:
            curve_points(out[col])
    band = out.get('frequency_band')
    if band in config.FREQUENCY_BANDS:
        _, lo, hi = config.FREQUENCY_BANDS[band]
        out.setdefault('share_low', lo)
        out.setdefault('share_high', hi)
        if band == 'systemic' and not out.get('manufacturer_trace'):
            raise ValueError("frequency_band 'systemic' needs manufacturer_trace (extended warranty, Kulanz, TPI or class action)")
        bands = list(config.FREQUENCY_BANDS)
        if out.get('source_id') is not None and bands.index(band) < bands.index(config.FORUM_MAX_BAND):
            q = c.execute('SELECT quality FROM sources WHERE id=?', (out['source_id'],)).fetchone()
            if q and q[0] == 'D':
                raise ValueError(f"a forum-only fault (source quality D) is never above '{config.FORUM_MAX_BAND}'")
    # a "fixed from" / build window needs an A/B source; otherwise the fault stays, marked uncertain (#168)
    if (out.get('applies_from') or out.get('applies_to')) and out.get('source_id') is not None:
        q = c.execute('SELECT quality FROM sources WHERE id=?', (out['source_id'],)).fetchone()
        if not q or q[0] not in ('A', 'B'):
            out['window_uncertain'] = 1


def check_component_code(c, data, row_id):
    """A fault's component_code (#221 phase 3): required on insert, NULL tolerated on PATCH; it must belong to the (merged) part,
    and OTHER needs notes. The 400 names the suggested code."""
    old = c.execute('SELECT * FROM faults_all WHERE id=?', (row_id,)).fetchone() if row_id is not None else None
    row = {**(dict(old) if old else {}), **data}
    code, part = row.get('component_code'), row.get('part')
    codes = [k for k, _, _ in config.FAULT_COMPONENTS.get(part, ())]
    if code is None and row_id is None or code is not None and code not in codes:
        hint = config.suggest_component(part, row.get('component'))
        raise ValueError(f"component_code: {'required' if code is None else repr(code) + ' is not a ' + str(part) + ' code'}; "
                         f"for {row.get('component')!r} ({part}) " + (f'probably {hint}; ' if hint else '') + f'codes: {", ".join(codes)} '
                         '(GET /api/agent/schema, fault_components)')
    if code == 'OTHER' and not str(row.get('notes') or '').strip():
        raise ValueError('component_code OTHER needs notes saying what the component is')


def rating_checks(c, table, out, row_id):
    """source_keys / source_ratings (#354): the source's rules from config.RATING_SOURCES. A PATCH is checked on the row as
    it will be; archiving alone is never refused."""
    if set(out) <= {'archived'}:
        return
    old = dict(c.execute(f'SELECT * FROM {table}_all WHERE id=?', (row_id,)).fetchone() or {}) if row_id else {}
    row = {**old, **out}
    rule = config.RATING_SOURCES.get(row.get('source_key'))
    if rule is None:
        raise ValueError(f"source_key must be one of {sorted(config.RATING_SOURCES)}")
    if table == 'source_keys':
        level = 'engine' if row.get('engine_id') is not None else 'generation'
        if level != rule['level']:
            raise ValueError(f"{row['source_key']} keys attach to a {rule['level']} (engine_id or generation_id)")
        if row.get('fuel_type') is not None and not rule.get('fuel'):
            raise ValueError('fuel_type is for ADAC_GWINFO keys only')
        return
    if not rule['required']:
        raise ValueError(f"{row['source_key']} has no ratings (a source_keys link only)")
    if row['source_key'] == 'ENGINESCOPE':
        perm = config.ENGINESCOPE_PERMISSION
        costs = row.get('cost_min_eur') is not None or row.get('cost_max_eur') is not None
        if perm not in ('SCORE', 'SCORE_AND_COSTS') or costs and perm != 'SCORE_AND_COSTS':
            raise NotAllowed('ENGINESCOPE: no written permission to store its '
                             + ('scores' if perm == 'NONE' else 'costs') + ' (terms section 6): a source_keys link only')
    missing = [k for k in rule['required'] if row.get(k) is None]
    if missing:
        raise ValueError(f"{row['source_key']} ratings need {', '.join(missing)}")
    lo, hi = rule.get('scale', (0, None))
    if row.get('value_num') is not None and (row['value_num'] < lo or hi is not None and row['value_num'] > hi):
        raise ValueError(f"value_num must be within {lo}-{hi} for {row['source_key']}")
    if 'bands' in rule:
        band = next(b for floor, b in config.ENGINESCOPE_BANDS if row['value_num'] >= floor)
        if str(row['value_text']).strip().upper() != band:
            raise ValueError(f"value_text must be the band of the score: {row['value_num']} is {band}")


def clean_row(c, table, data, insert, row_id=None):
    """Validates an agent row against the real schema: known columns, types, '' → NULL, source required, one level."""
    if not isinstance(data, dict) or not data:
        raise ValueError('Expected a non-empty JSON object')
    if 'owner_id' in data:
        raise ValueError('owner_id is set from the account, not by the client')
    cols = table_columns(c, table)
    out = {}
    for tbl, col in JSON_COLUMNS:
        if table == tbl and isinstance(data.get(col), (dict, list)):
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
    if table == 'research_checks' and out.get('named_codes'):
        task = out.get('task') or ''
        part = task.split('.')[1] if task.startswith('rel.') else None
        valid = [k for k, _, _ in config.FAULT_COMPONENTS.get(part, ())]
        bad = [x for x in json.loads(out['named_codes']) if x not in valid]
        if part is None or bad:
            raise ValueError(f"named_codes {bad or ''} must be fault_components codes of the part of a rel.<PART>.<source> task: {valid} (GET /api/agent/schema)")
    if insert and table == 'research_checks' and out.get('contract_version') is None:
        out['contract_version'] = research.CONTRACT_VERSION
    if insert and table == 'reliability_items' and out.get('part') is None:
        raise ValueError(f"reliability_items requires part: one of {config.RELIABILITY_PARTS} (docs/cost-research-protocol.md, step 2)")
    levels = sum(out.get(k) is not None for k in config.LEVEL_COLUMNS)
    if insert and table in config.SCOPED_TABLES and (levels > 1 or levels == 0 and table not in config.GLOBAL_LEVEL_TABLES):
        raise ValueError(f'{table} must attach to exactly one level: {", ".join(config.LEVEL_COLUMNS)}'
                         + (' (none = a global default)' if table in config.GLOBAL_LEVEL_TABLES else ''))
    if insert and table == 'sources' and levels > 1:
        raise ValueError(f'sources attach to at most one level: {", ".join(config.LEVEL_COLUMNS)} (none = shared)')
    if table == 'faults':
        fault_checks(c, out)
    if table in SOURCE_TABLES:
        rating_checks(c, table, out, row_id)
    return out


ADMIN_TABLES = set(MODEL) | set(_KNOW) | {'listings', 'flag_reviews', *SOURCE_TABLES}  # research and listings: the shared worker (admin) only (#109)


def check_writable(c, table, row_id, data):
    """A non-admin agent token writes only its own listing rows and level-free sources; research belongs to the shared
    catalogue, written by admins (issue #109). The UI's own writes (viewing, checklist, decisions) do not pass here."""
    level = any(data.get(k) is not None for k in config.LEVEL_COLUMNS) if isinstance(data, dict) else False
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
    """A catalogue variant with the same HSN/TSN (and engine, when given: one HSN/TSN can cover several engine codes,
    #174) is reused instead of duplicated; the account gets a link to it."""
    if not isinstance(data, dict) or not data.get('hsn') or not data.get('tsn'):
        return None
    row = c.execute('SELECT min(id) FROM main.vehicles WHERE owner_id IS NULL AND upper(trim(hsn))=upper(trim(?)) '
                    'AND upper(trim(tsn))=upper(trim(?)) AND (? IS NULL OR engine_id=?)',
                    (str(data['hsn']), str(data['tsn']), data.get('engine_id'), data.get('engine_id'))).fetchone()
    if row[0] is not None:
        with c:
            link(c, owner_id, row[0])
    return row[0]


def resolve_level(c, table, data):
    """An existing shared generation or engine instead of a duplicate (#293), so its research is reused: a generation of the
    same make and model with the same start year or the same name; an engine of the same fuel, displacement and power (±1 kW or
    ±1 PS) whose code is the same or a placeholder ('UNKNOWN-…') on either side. None when nothing matches or a fact is missing."""
    if not isinstance(data, dict):
        return None
    if table == 'generations' and data.get('make') and data.get('model'):
        r = c.execute('SELECT min(id) FROM main.generations WHERE owner_id IS NULL AND upper(trim(make))=upper(trim(?)) AND upper(trim(model))=upper(trim(?)) '
                      'AND (start_year IS NOT NULL AND start_year=? OR upper(trim(name))=upper(trim(?)))',
                      (data['make'], data['model'], data.get('start_year'), data.get('name') or '')).fetchone()
        return r[0]
    if table == 'engines' and data.get('code') and data.get('fuel_type') and data.get('displacement_cc') and (data.get('power_kw') or data.get('power_ps')):
        r = c.execute("SELECT min(id) FROM main.engines WHERE owner_id IS NULL AND fuel_type=? AND displacement_cc=? "
                      "AND (abs(coalesce(power_kw, -99) - coalesce(?, -1)) <= 1 OR abs(coalesce(power_ps, -99) - coalesce(?, -1)) <= 1) "
                      "AND (upper(trim(code))=upper(trim(?)) OR upper(code) LIKE 'UNKNOWN-%' OR upper(?) LIKE 'UNKNOWN-%')",
                      (data['fuel_type'], data['displacement_cc'], data.get('power_kw'), data.get('power_ps'), data['code'], data['code'])).fetchone()
        return r[0]
    return None


def link(c, owner_id, vehicle_id):
    """The account sees this catalogue variant (with its engine and generation) from now on."""
    c.execute('INSERT INTO main.catalogue_links (owner_id, vehicle_id) SELECT ?, id FROM main.vehicles WHERE id=? AND owner_id IS NULL '
              'AND NOT EXISTS (SELECT 1 FROM main.catalogue_links WHERE owner_id=? AND vehicle_id=?)', (owner_id, vehicle_id, owner_id, vehicle_id))


# a listing reaches every level through its variant (engine → family, gearbox → family, body style) and its options
_LISTING_LEVELS = ('SELECT DISTINCT l.owner_id FROM main.listings l JOIN main.vehicles v ON v.id=l.vehicle_id '
                   'JOIN main.engines e ON e.id=v.engine_id LEFT JOIN main.gearboxes gb ON gb.id=v.gearbox_id '
                   'WHERE v.id=:vehicle_id OR v.engine_id=:engine_id OR v.generation_id=:generation_id OR v.gearbox_id=:gearbox_id '
                   'OR e.family_id=:engine_family_id OR gb.family_id=:gearbox_family_id OR v.body_style_id=:body_style_id '
                   'OR l.id IN (SELECT listing_id FROM main.listing_options WHERE option_id=:option_id)')
_MODEL_LEVEL = {'vehicles': 'vehicle_id', 'engines': 'engine_id', 'generations': 'generation_id', 'gearboxes': 'gearbox_id',
                'engine_families': 'engine_family_id', 'gearbox_families': 'gearbox_family_id', 'body_styles': 'body_style_id',
                'options': 'option_id'}


def linked_accounts(c, table, row_id):
    """Accounts with a listing on the level this row belongs to (their dossiers show it)."""
    lv = dict.fromkeys(config.LEVEL_COLUMNS)
    if table in MODEL:
        lv[_MODEL_LEVEL[table]] = row_id
    elif table in _KNOW or table == 'sources':
        r = c.execute(f'SELECT * FROM main.{table} WHERE id=?', (row_id,)).fetchone()
        lv.update({k: r[k] for k in r.keys() if k in lv} if r else {})
    else:
        return []
    return [o for (o,) in c.execute(_LISTING_LEVELS, lv)]


DUPLICATE_GUARDED = ('faults', 'recalls', 'maintenance_items', 'reliability_items')  # the same row filed twice on levels one car carries (#221)
GUARD_KEYS = (*config.LEVEL_COLUMNS, 'part', 'component', 'component_code', 'code', 'job', 'applies_from', 'applies_to', 'archived')


def guard_duplicate(c, table, data, row_id, distinct):
    """409 when a fault, recall or maintenance job would be costed twice (#221). `distinct_of` (the conflicting ids) plus a reason in `notes` overrides it;
    the server prefixes the notes so the decision stays visible in the log."""
    if row_id is not None:
        if not any(k in data for k in GUARD_KEYS) or data.get('archived') == 1:
            return
        old = c.execute(f'SELECT * FROM {table}_all WHERE id=?', (row_id,)).fetchone()
        merged = {**(dict(old) if old else {}), **data}
        if any(k in data for k in config.LEVEL_COLUMNS):  # a re-scope replaces the level
            merged = {**merged, **{k: data.get(k) for k in config.LEVEL_COLUMNS}}
    else:
        merged = data
    from . import consistency
    found = consistency.conflicts(c, table, merged, row_id)
    if not found:
        return
    ids = [f['id'] for f in found]
    if distinct is None:
        first = found[0]
        raise Conflict({'error': f"{table}: a similar row already applies to cars of this level: "
                                 f"{first['table']} #{first['id']} '{first['component']}' ({first['level']} {first['level_id']}). PATCH it (add evidence in notes, "
                                 f"re-scope it with one PATCH), or resend with distinct_of={ids} and the reason in notes",
                        'conflict': found})
    if not isinstance(distinct, list) or not set(ids) <= set(distinct):
        raise ValueError(f'distinct_of must list every conflicting fault id: {ids}')
    reason = str(data.get('notes') or '').strip()
    if not reason or any(reason == (f['notes'] or '').strip() for f in found):
        raise ValueError('distinct_of needs notes saying why this is a different fault (not a copy of the other row\'s notes)')
    data['notes'] = f"Distinct from {table[:-1].replace('_', ' ')} {', '.join('#%d' % i for i in ids)}: {reason}"


def open_flag(c, data):
    """Id of the OPEN review flag of the same kind on the same level as `data`, or None (one open flag per level and kind, #337)."""
    cols = [k for k in config.LEVEL_COLUMNS if isinstance(data, dict) and data.get(k) is not None]
    if len(cols) != 1 or not data.get('kind'):
        return None
    r = c.execute(f"SELECT id FROM main.review_flags WHERE {cols[0]}=? AND kind=? AND status='OPEN' ORDER BY id LIMIT 1", (data[cols[0]], data['kind'])).fetchone()
    return r[0] if r else None


def agent_write(c, table, row_id, data, user_id, admin=False, actor=None):
    """Inserts (row_id None) or updates a row of this account in one transaction and records it in change_log.
    Admin inserts of generations, engines, variants and level sources go to the shared catalogue (owner_id NULL);
    knowledge rows follow their level, except an account's own premium or USER DATA figure, which stays private.
    `actor` is who wrote it (the admin acting for the account), for the change log."""
    if table == 'review_flags' and row_id is None and (fid := open_flag(c, data)):  # a second flag of the kind joins the open one
        old = c.execute('SELECT what, why FROM main.review_flags WHERE id=?', (fid,)).fetchone()
        new = {k: '; '.join(dict.fromkeys([old[k], str(data.get(k) or '')]))[:1500] for k in ('what', 'why')}
        with c:
            c.execute('UPDATE main.review_flags SET what=?, why=? WHERE id=?', (new['what'], new['why'], fid))
            c.execute('INSERT INTO main.change_log (table_name,row_id,action,old_json,new_json,user_id) VALUES (?,?,?,?,?,?)',
                      ('review_flags', fid, 'update', json.dumps(dict(old)), json.dumps(new), actor or user_id))
        return fid
    distinct = data.pop('distinct_of', None) if table in DUPLICATE_GUARDED and isinstance(data, dict) else None
    data = clean_row(c, table, data, insert=row_id is None, row_id=row_id)
    check_parents(c, table, data)
    if table == 'faults':
        check_component_code(c, data, row_id)
    if table in DUPLICATE_GUARDED:
        guard_duplicate(c, table, data, row_id, distinct)
    with c:
        if row_id is None:
            if table in OWNED:
                catalogue = admin and (table in MODEL or table == 'sources' and any(data.get(k) is not None for k in config.LEVEL_COLUMNS))
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
        if table == 'flag_reviews':
            clear_if_agreed(c, c.execute('SELECT flag_id FROM main.flag_reviews WHERE id=?', (row_id,)).fetchone()[0])
        if table == 'review_flags' and data.get('status') == 'CLEARED':
            raise ValueError('a flag is cleared only by two independent reviews reaching the same conclusion (flag_reviews)')
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
        raise QuotaExceeded('Storage budget exhausted (900 of 1024 MB); free space before archiving more photos')
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
