"""The research contract (issue #114, part of #106): what must be known about a generation, an engine, a variant and a
listing before it counts as researched, so "researched" is computed the same way for every car and does not depend on
which listing triggered the research. Each item is graded from the rows on its own level:
  MISSING  nothing acceptable (or only sources below the item's minimum quality, or checks older than the item),
  ACCEPTED present, but estimated or from a C/D source,
  VERIFIED a verified / official / primary row from an A/B source (a recorded check from an A/B source).
A level is researched without MISSING items and verified when every item is VERIFIED. The table of items is
documented in docs/cost-research-protocol.md (a test keeps both in step). Adding an item marks every level it applies to
incomplete at once; raising an item's `since` makes checks recorded against an older contract stop counting."""
import datetime, re
from . import config
from .db import rows
from .ranking import STATUS_POINTS

CONTRACT_VERSION = 10  # 10: fixed reliability sources per level replace rel.<PART>.<source>, rel.coverage, gen.baseline, var.gearbox; recalls and fault research stay (#357, #351); 9: rel.coverage, faults named by two sources (#343); 8: gen.recalls needs FOUND or NONE FOUND, N/A no longer counts (#333); 7: engine and family graded as one pool (#331); 6: Euro NCAP stars of the generation for the safety criterion (#169); 5: target design levels, faults, statistics baseline, ADAC/TÜV on the generation (#174); 2: jobs matched by code and needing both prices; lst.tax_covered (#106 part 4); 3: electric cars (#125); 4: EVDB consumption (#154)
GRADE = {'MISSING': 0, 'ACCEPTED': 0.5, 'VERIFIED': 1}
QUALITY_ORDER = 'ABCD'
LEVEL_COL = {'generation': 'generation_id', 'engine': 'engine_id', 'variant': 'vehicle_id', 'engine_family': 'engine_family_id',
             'gearbox': 'gearbox_id', 'gearbox_family': 'gearbox_family_id', 'body_style': 'body_style_id'}


def _job(*jobs):
    """Maintenance rows of one job by its code (#106 part 4): active, with an interval, the workshop price and, for a
    job any account may do itself (config.DIYABLE_JOBS), the DIY parts price too, since each account's choice picks one."""
    return lambda ctx: [r for r in ctx['rows']('maintenance_items') if r['active'] and r.get('job') in jobs
                        and (r['interval_km'] or r['interval_months']) and r['reference_cost_eur'] is not None
                        and (r['diy_parts_cost_eur'] is not None or r['job'] not in config.DIYABLE_JOBS)]


def _risks(ctx):
    """Priced faults (with a curve, or a band and a shape, #168) and old priced risks; one incomplete row makes the item
    missing (every fault gets a price and a probability)."""
    rs, fs = ctx['rows']('repair_risks'), ctx['rows']('faults')
    bad = any(r['parts_eur'] is None and r['labor_eur'] is None for r in rs + fs) or \
        any(not (f['curve_km'] or f['curve_age'] or f['frequency_band'] and f['shape']) for f in fs)
    return [] if bad else rs + fs


def _consumption(ctx):
    """The primary real-world consumption of the variant: one source per drivetrain (kWh for an electric car)."""
    if electric(ctx):  # a modelled figure per variant (EVDB, #154): no owner reports, so no sample size or range
        return [r for r in ctx['rows']('observations') if r['metric'] == config.PRIMARY_CONSUMPTION_EV and r['value_num'] is not None]
    return [r for r in ctx['rows']('observations') if r['metric'] == config.PRIMARY_CONSUMPTION and None not in
            (r['value_num'], r['sample_count'], r['min_value'], r['max_value'])]


def _tyres(ctx):
    return [r for r in ctx['rows']('tyre_data', 'generation') if None not in (r['size'], r['price_per_tyre_eur'], r['life_km'])]


def _tax(ctx):
    return [r for r in ctx['rows']('tax_data') if r['annual_tax_eur'] is not None
            and (ctx['sources'].get(r['source_id']) or {}).get('source_type') == config.TAX_OFFICIAL_SOURCE]


def _fields(*cols, status='status', code=False):
    """Identity fields of the level row: all filled (an engine code not 'unknown…'); graded by the row's status."""
    def cands(ctx):
        r = ctx['row']
        if any(r.get(c) in (None, '') for c in cols) or code and (r.get('code') or '').lower().startswith('unknown'):
            return []
        return [{'_grade': 'VERIFIED' if r.get(status) == 'VERIFIED' else 'ACCEPTED'}]
    return cands


def _source(key, ratings=True):
    """A live source_keys row of `key` on the level (status VERIFIED so the source's quality grades it), with a live rating
    for it when the source has ratings (#357). TUEV: a rating of the newest imported edition only (see Contract)."""
    def cands(ctx):
        return [{**k, 'status': 'VERIFIED'} for k in ctx['rows']('source_keys') if k['source_key'] == key
                and (not ratings or k['_ratings'])]
    return cands


def _gwinfo(ctx):
    """An ADAC_GWINFO key for the fuel of every catalogue variant of the generation (a key without a fuel covers all)."""
    keys = [k for k in ctx['rows']('source_keys') if k['source_key'] == 'ADAC_GWINFO']
    fuels = ctx['row'].get('_fuels') or set()
    ok = keys and all(any(k['fuel_type'] in (None, f) for k in keys) for f in fuels)
    return [{**k, 'status': 'VERIFIED'} for k in keys] if ok else []


def _is(col, *values):
    return lambda ctx: (ctx['row'].get(col) or '') in values


petrol = lambda ctx: (ctx['row'].get('fuel_type') or '').lower() in ('petrol', 'hybrid', 'plug-in hybrid')  # spark plugs
electric = lambda ctx: ctx['row'].get('fuel_type') == 'Electric'
combustion = lambda ctx: not electric(ctx)  # an engine with oil, filters, a timing drive (plug-in hybrids included)
diesel = lambda ctx: (ctx['row'].get('fuel_type') or '').lower() == 'diesel'
automatic = lambda ctx: bool(re.search(r'auto|dsg|cvt|dual.clutch|tiptronic', ctx['row'].get('transmission') or '', re.I))
always = lambda ctx: True
# which research_checks results satisfy an item that is a check, or the alternative to rows ('NONE FOUND' etc.)
FOUND_OR_NONE, NOT_APPLICABLE = ('FOUND', 'NONE FOUND', 'N/A'), ('N/A',)

# (id, level, title, rows → candidates or None for a pure check, results accepted from research_checks, min quality,
#  applies, since). Item ids are the research_checks.task values.
ITEMS = [
    ('gen.identity', 'generation', 'make, model, name, start and end year of the whole production run', _fields('start_year', 'end_year'), (), None, always, 1),
    ('gen.facelift', 'generation', 'facelift year (check N/A when there was none)', _fields('facelift_year'), NOT_APPLICABLE, None, always, 1),
    ('gen.hu', 'generation', 'HU/AU every 24 months with the official fee', _job('HU'), (), None, always, 2),
    ('gen.brake_fluid', 'generation', 'brake fluid interval and workshop price', _job('BRAKE_FLUID'), (), None, always, 2),
    ('gen.brakes', 'generation', 'brake pads and discs: interval, DIY parts and workshop price', _job('BRAKES_FRONT', 'BRAKES_REAR'), (), None, always, 2),
    ('gen.recalls', 'generation', 'recall search (KBA / manufacturer)', None, ('FOUND', 'NONE FOUND'), 'C', always, 1),  # N/A records an unreachable source but never satisfies the item (#333)  # C: KBA pages are often unreachable; the recall row asks for a dealer VIN check anyway (#303)
    ('gen.risks', 'generation', 'body/chassis repair risks, each priced (or a check: none found)', _risks, ('NONE FOUND',), None, always, 1),
    ('eng.identity', 'engine', 'code, fuel, displacement, power, aspiration, injection, timing drive', _fields(
        'code', 'fuel_type', 'displacement_cc', 'power_ps', 'aspiration', 'injection', 'timing_drive', code=True), (), None, combustion, 1),
    ('eng.identity_ev', 'engine', 'electric: code, fuel, power, usable battery kWh, AC charging kW', _fields(
        'code', 'fuel_type', 'power_ps', 'battery_usable_kwh', 'ac_charge_kw', code=True), (), None, electric, 3),
    ('eng.hv_battery', 'engine', 'electric: battery warranty (years / km / % health) and the battery risk checked', None, FOUND_OR_NONE, 'B', electric, 3),
    ('eng.drive_coolant', 'engine', 'electric: battery/motor coolant interval and workshop price (or a check: lifetime fill)', _job('DRIVE_COOLANT'), ('NONE FOUND',), None, electric, 3),
    ('eng.reduction_gear_oil', 'engine', 'electric: reduction gear oil interval and workshop price (or a check: none scheduled)', _job('REDUCTION_GEAR_OIL'), ('NONE FOUND',), None, electric, 3),
    ('eng.oil', 'engine', 'oil and filter service: interval, DIY parts and workshop price', _job('OIL_SERVICE'), (), None, combustion, 2),
    ('eng.spark_plugs', 'engine', 'spark plugs: interval, DIY parts and workshop price', _job('SPARK_PLUGS'), (), None, petrol, 2),
    ('eng.timing_belt', 'engine', 'timing belt: interval, DIY parts and workshop price', _job('TIMING_DRIVE'), (), None,
     lambda ctx: combustion(ctx) and not _is('timing_drive', 'CHAIN', 'GEAR')(ctx), 2),
    ('eng.timing_chain', 'engine', 'timing chain/gear: a job or a check that none is scheduled', _job('TIMING_DRIVE'), ('NONE FOUND',), None,
     _is('timing_drive', 'CHAIN', 'GEAR'), 2),
    ('eng.coolant', 'engine', 'coolant: interval, DIY parts and workshop price (or a check: lifetime fill)', _job('COOLANT'), ('NONE FOUND',), None, combustion, 2),
    ('eng.risks', 'engine', 'engine repair risks, each priced (or a check: none found)', _risks, ('NONE FOUND',), None, always, 1),
    ('var.identity', 'variant', 'HSN/TSN, gearbox, body, emissions class, CO2', _fields(
        'hsn', 'tsn', 'transmission', 'body_style', 'emissions_standard', 'co2_g_km', status='technical_status'), (), None, always, 1),
    ('var.consumption', 'variant', f'{config.PRIMARY_CONSUMPTION} with sample size, min and max (electric: {config.PRIMARY_CONSUMPTION_EV}, kWh/100 km of the exact variant and battery)',
     _consumption, ('NONE FOUND',), 'C', always, 1),  # no reported average on the exact variant page: stays unknown, goes to the to-do (#303)
    ('var.tyres', 'variant', 'all-season tyres: size, price, tread life (variant or generation)', _tyres, (), None, always, 1),
    ('var.tax', 'variant', 'annual tax from the BMF Kfz-Steuer-Rechner', _tax, (), 'A', always, 1),
    # target design (#174): the new levels
    ('var.gearbox_level', 'variant', 'the variant names its gearbox (code, type)', _fields('gearbox_id'), (), None, always, 5),
    ('fam.risks', 'engine_family', 'engine family faults, each priced with a probability (or a check: none found)', _risks, ('NONE FOUND',), None, always, 5),
    ('gbx.identity', 'gearbox', 'gearbox code and type', _fields('code', 'type'), (), None, always, 5),
    ('gbx.service', 'gearbox', 'gearbox oil service: interval and workshop price (or a check: none scheduled)', _job('GEARBOX_OIL'), ('NONE FOUND',), None, always, 5),
    ('gbx.clutch', 'gearbox', 'clutch: typical life, DIY parts and workshop price (or a check: none)', _job('CLUTCH'), ('NONE FOUND',), None,
     _is('type', 'MANUAL', 'DCT'), 5),
    ('gbx.risks', 'gearbox', 'gearbox faults, each priced with a probability (or a check: none found)', _risks, ('NONE FOUND',), None, always, 5),
    ('gen.safety', 'generation', 'Euro NCAP stars and test year (or a check: N/A, never tested)', _fields('ncap_stars', 'ncap_year'), NOT_APPLICABLE, 'B', always, 6),
    ('bdy.risks', 'body_style', 'body style faults and maintenance (convertible roof …) or a check: none found', _risks, ('NONE FOUND',), None, always, 5),
]
# fixed reliability sources (#351, #357): a source_keys row (and its rating where the source has ratings) or an N/A check
# saying why the source does not cover the level; recalls (gen.recalls) and fault research (*.risks) stay
ITEMS += [
    ('rel.autoscore', 'engine', 'Autoscore engine key with its rating (or a check: N/A, not listed)', _source('AUTOSCORE'), NOT_APPLICABLE, 'C', combustion, 10),
    ('rel.enginescope', 'engine', 'EngineScope engine key, link only (or a check: N/A, not listed)', _source('ENGINESCOPE', ratings=False), NOT_APPLICABLE, 'C', combustion, 10),
    ('rel.adac_gwinfo', 'generation', 'ADAC Gebrauchtwagen-Info PDF for the fuel of every variant (or a check: N/A, no report found)', _gwinfo, NOT_APPLICABLE, 'B', always, 10),
    ('rel.adac', 'generation', 'ADAC Pannenstatistik key with at least one rating (or a check: N/A, too new or too few registrations)', _source('ADAC_PANNENSTATISTIK'), NOT_APPLICABLE, 'B', always, 10),
    ('rel.tuev', 'generation', 'TÜV-Report key with a rating of the newest imported edition (or a check: N/A, not in the report)', _source('TUEV_REPORT'), NOT_APPLICABLE, 'B', always, 10),
]
ITEM = {i[0]: i for i in ITEMS}
TASKS = set(ITEM)


def grade_rows(cands, sources, min_q):
    """Best grade of the candidate rows (a candidate may carry its own '_grade', e.g. identity fields)."""
    best = 'MISSING'
    for r in cands:
        g = r.get('_grade')
        if g is None:
            q = (sources.get(r.get('source_id')) or {}).get('quality')
            if min_q and (q is None or QUALITY_ORDER.find(q) > QUALITY_ORDER.find(min_q)):
                continue
            ok = 'result' in r or STATUS_POINTS.get(r.get('status') or r.get('premium_status')) == 1
            g = 'VERIFIED' if ok and q in ('A', 'B') else 'ACCEPTED'
        if GRADE[g] > GRADE[best]:
            best = g
    return best


def evaluate(level, row, rows, sources):
    """Grades of the items of one level. `rows(table, *extra_levels)` returns the knowledge rows on this level."""
    ctx = {'row': row, 'rows': rows, 'sources': sources, 'hints': {}}
    out = []
    for iid, lvl, title, cands, results, min_q, applies, since in ITEMS:
        if lvl != level or not applies(ctx):
            continue
        found = list(cands(ctx)) if cands else []
        found += [r for r in rows('research_checks') if r['task'] == iid and r['result'] in results and r['contract_version'] >= since]
        out.append({'id': iid, 'level': lvl, 'title': title, 'grade': grade_rows(found, sources, min_q),
                    **({'hint': ctx['hints'][iid]} if iid in ctx['hints'] else {})})
    return out


def state(items):
    return 'verified' if all(i['grade'] == 'VERIFIED' for i in items) else \
        'researched' if all(i['grade'] != 'MISSING' for i in items) else 'incomplete'


def summary(items):
    return {'state': state(items), 'missing': [i['id'] for i in items if i['grade'] == 'MISSING'],
            'accepted': [i['id'] for i in items if i['grade'] == 'ACCEPTED'], 'items': items}


class Contract:
    """Grades per level and resolved per variant, from Knowledge's rows (loaded once)."""

    def __init__(self, c, know):
        self.sources = {r['id']: r for r in rows(c, 'SELECT id, quality, source_type FROM sources')}
        self.rows = {t: {r['id']: r for r in rows(c, f'SELECT * FROM {t}')}
                     for t in ('vehicles', 'engines', 'generations', 'gearboxes', 'engine_families', 'gearbox_families', 'body_styles')}
        self.index = {}
        # live source_keys with the ratings behind them (#357); the TÜV counts only the newest imported edition
        ratings = rows(c, 'SELECT * FROM source_ratings WHERE archived = 0')
        newest = max((r['edition'] for r in ratings if r['source_key'] == 'TUEV_REPORT'), default=None)
        keys = rows(c, 'SELECT * FROM source_keys WHERE archived = 0')
        for k in keys:
            k['_ratings'] = [r for r in ratings if r['source_key'] == k['source_key'] and r['external_key'].upper() == k['external_key'].upper()
                             and (k['source_key'] != 'TUEV_REPORT' or r['edition'] == newest)]
        for table, rs in {**know.t, 'source_keys': keys}.items():
            for r in rs:
                for col in config.LEVEL_COLUMNS:
                    if r.get(col) is not None:
                        self.index.setdefault((col, r[col]), {}).setdefault(table, []).append(r)
        self.cache = {}

    def _rows(self, keys, extra=None):
        """rows(table, *levels): the rows of `table` on `keys`, plus on the named extra levels (e.g. a variant's tyres
        may sit on its generation)."""
        def rows(table, *levels):
            ks = list(keys) + [extra[l] for l in levels if extra and l in extra]
            return [r for k in ks for r in self.index.get(k, {}).get(table, [])]
        return rows

    def level(self, level, row):
        """Grades of one level from its own rows only (stable whichever listing triggered the research)."""
        key = (level, row['id'])
        if level == 'variant':  # the variant's drivetrain decides which consumption source counts
            row = {**row, 'fuel_type': self.rows['engines'][row['engine_id']]['fuel_type']}
        if level == 'generation':  # fuels of the catalogue variants: one GW-Info report per fuel (#357)
            row = {**row, '_fuels': {self.rows['engines'][v['engine_id']]['fuel_type'] for v in self.rows['vehicles'].values()
                                     if v['generation_id'] == row['id']}}
        if key not in self.cache:
            eng = self.rows['engines'].get(row.get('engine_id')) or {}
            extra = {'generation': ('generation_id', row.get('generation_id')), 'engine': ('engine_id', row.get('engine_id')),
                     'engine_family': ('engine_family_id', eng.get('family_id')), 'gearbox': ('gearbox_id', row.get('gearbox_id'))} if level == 'variant' else None
            self.cache[key] = evaluate(level, row, self._rows([(LEVEL_COL[level], row['id'])], extra), self.sources)
        return self.cache[key]

    def resolved(self, vehicle_id):
        """A variant with every level above it: generation, engine and its family, gearbox and its family, body style
        (#174). Engine and family items are graded on the union of the engine's and its family's rows; a gearbox item on the
        variant when it names no gearbox. An item missing on its level but present one level lower (e.g. an engine job
        stored on the variant, an ADAC check stored on the engine) counts as ACCEPTED at most, with a hint to move it up."""
        if vehicle_id is None:  # a listing awaiting (re-)research has no variant yet (#194): nothing is researched
            return [{'id': 'var.identity', 'level': 'variant', 'title': 'Variant (awaiting research)', 'grade': 'MISSING',
                     'hint': 'the listing has no variant yet: queue it for research'}]
        v = self.rows['vehicles'][vehicle_id]
        engine, generation = self.rows['engines'][v['engine_id']], self.rows['generations'][v['generation_id']]
        gearbox = self.rows['gearboxes'].get(v.get('gearbox_id'))
        efam = self.rows['engine_families'].get(engine.get('family_id'))
        body = self.rows['body_styles'].get(v.get('body_style_id'))
        out = []
        lower = {'generation': [('vehicle_id', v['id']), ('engine_id', v['engine_id'])], 'engine': [('vehicle_id', v['id'])], 'variant': []}
        # (level, row, the keys its items are graded on): a missing gearbox falls back to the level below
        # engine and family are one evidence pool for engine faults: the cost is the same on either level (#331)
        pool = [('engine_id', engine['id'])] + ([('engine_family_id', efam['id'])] if efam else [])
        plan = [('generation', generation, None), ('engine', engine, None),
                ('engine_family', efam or engine, None),
                ('gearbox', gearbox or {**v, 'code': None, 'type': None}, None if gearbox else [('vehicle_id', v['id'])]),
                ('variant', v, None)] + ([('body_style', body, None)] if body else [])
        for level, row, keys in plan:
            if keys is not None:  # graded on the fallback level's rows
                for i in evaluate(level, row, self._rows(keys), self.sources):
                    out.append({**i, 'hint': f'no {level.replace("_", " ")} yet: graded on the level below'})
                continue
            below = None
            graded = evaluate(level, row, self._rows(pool), self.sources) if level in ('engine', 'engine_family') else self.level(level, row)
            for i in graded:
                if i['grade'] == 'MISSING' and lower.get(level):
                    below = below or {x['id']: x['grade'] for x in evaluate(level, row, self._rows(lower[level]), self.sources)}
                    if below.get(i['id'], 'MISSING') != 'MISSING':
                        i = {**i, 'grade': 'ACCEPTED', 'hint': f'found on a lower level: move it to the {level}'}
                out.append(i)
        return out


def listing_items(u, rows, today):
    """The account's own part of the research for one listing (private): insurance, valuation, purchase costs, checklist,
    capture and photos. `rows` has the listing's insurance rows (its own), valuations, unit costs, checklist links, captures."""
    items = []
    def add(iid, title, ok):
        items.append({'id': iid, 'level': 'listing', 'title': title, 'grade': 'VERIFIED' if ok is True else ok or 'MISSING'})
    ins = [r for r in rows['insurance'] if r['annual_premium_eur'] is not None]  # premiums are private rows (#109)
    if u['is_reference']:
        add('lst.insurance', 'the premium the owner pays (USER DATA)', any(r['premium_status'] == config.USER_PREMIUM for r in ins))
    else:
        fresh = [r for r in ins if r['premium_status'] == 'QUOTE' and _age(r['quote_date'], today) is not None
                 and _age(r['quote_date'], today) <= config.QUOTE_MAX_AGE_DAYS]
        add('lst.insurance', f'an insurance quote younger than {config.QUOTE_MAX_AGE_DAYS} days', bool(fresh))
    add('lst.tax_covered', "a tax row whose registration window covers this car's first registration", rows['tax'] is not None)
    add('lst.valuation', 'resale value at the end of the period', 'resale_end' in rows['valuations'])
    if not u['is_reference']:
        add('lst.purchase_sale', 'purchase costs of this car', any(x['category'] == 'purchase_sale' for x in rows['unit_costs']))
        add('lst.checklist', 'a checklist item for every recall and every weak point with an inspection action', rows['weak_points'] <= rows['checked'])
        add('lst.capture', 'listing captured', rows['captured'])
        add('lst.photos', 'photos archived', bool(u['photo_count']))
    return items


def _age(iso_date, today):
    try:
        return (today - datetime.date.fromisoformat(iso_date[:10])).days
    except (TypeError, ValueError):
        return None


def published():
    """The contract as data, for GET /api/agent/schema."""
    return {'version': CONTRACT_VERSION, 'grades': GRADE, 'check_results': ['FOUND', 'NONE FOUND', 'N/A'],
            'items': [{'id': i[0], 'level': i[1], 'title': i[2], 'check_results': list(i[4]), 'min_quality': i[5], 'since': i[7],
                       'kind': 'check' if i[3] is None else 'rows' + (' or check' if i[4] else '')} for i in ITEMS]}


def levels(items):
    """Summary per level (generation, engine, variant, listing) of resolved items, for the UI."""
    return {lvl: summary([i for i in items if i['level'] == lvl]) for lvl in ('generation', 'engine_family', 'engine', 'gearbox_family', 'gearbox', 'body_style', 'variant', 'listing')
            if any(i['level'] == lvl for i in items)}


def confidence(items):
    """Mean grade of the applicable items (VERIFIED 1, ACCEPTED 0.5, MISSING 0) as a percentage; None without items."""
    return round(sum(GRADE[i['grade']] for i in items) / len(items) * 100) if items else None
