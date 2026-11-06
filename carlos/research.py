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

CONTRACT_VERSION = 5  # 2: jobs matched by code and needing both prices; lst.tax_covered (#106 part 4); 3: electric cars (#125); 4: EVDB consumption (#154); 5: gearbox level (#164)
GRADE = {'MISSING': 0, 'ACCEPTED': 0.5, 'VERIFIED': 1}
QUALITY_ORDER = 'ABCD'
LEVEL_COL = {'generation': 'generation_id', 'engine': 'engine_id', 'gearbox': 'gearbox_id', 'variant': 'vehicle_id'}
LEVEL_ORDER = ('generation', 'engine', 'gearbox', 'variant', 'listing')
REL_SOURCES = {'adac': 'B', 'tuev': 'B', 'guide': 'C', 'engine_specific': 'C'}  # the same sources for every car, minimum quality


def _job(*jobs):
    """Maintenance rows of one job by its code (#106 part 4): active, with an interval, the workshop price and, for a
    job any account may do itself (config.DIYABLE_JOBS), the DIY parts price too, since each account's choice picks one."""
    return lambda ctx: [r for r in ctx['rows']('maintenance_items') if r['active'] and r.get('job') in jobs
                        and (r['interval_km'] or r['interval_months']) and r['reference_cost_eur'] is not None
                        and (r['diy_parts_cost_eur'] is not None or r['job'] not in config.DIYABLE_JOBS)]


def _risks(ctx):
    """Priced weak-point risks; one unpriced risk makes the item missing (every risk gets a price, AGENTS.md)."""
    rs = ctx['rows']('repair_risks')
    return [] if any(r['parts_eur'] is None and r['labor_eur'] is None for r in rs) else rs


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


def _is(col, *values):
    return lambda ctx: (ctx['row'].get(col) or '') in values


petrol = lambda ctx: (ctx['row'].get('fuel_type') or '').lower() in ('petrol', 'hybrid', 'plug-in hybrid')  # spark plugs
electric = lambda ctx: ctx['row'].get('fuel_type') == 'Electric'
combustion = lambda ctx: not electric(ctx)  # an engine with oil, filters, a timing drive (plug-in hybrids included)
diesel = lambda ctx: (ctx['row'].get('fuel_type') or '').lower() == 'diesel'
oil_change_gearbox = lambda ctx: ctx['row'].get('type') in ('DCT', 'AT', 'CVT')  # a manual's oil is usually a lifetime fill
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
    ('gen.battery', 'generation', 'battery: life, DIY parts and workshop price', _job('BATTERY'), (), None, always, 2),
    ('gen.wipers', 'generation', 'wiper blades: interval, DIY parts and workshop price', _job('WIPERS'), (), None, always, 2),
    ('gen.cabin_filter', 'generation', 'cabin (pollen) filter: interval, DIY parts and workshop price', _job('CABIN_FILTER'), (), None, always, 2),
    ('gen.recalls', 'generation', 'recall search (KBA / manufacturer)', None, FOUND_OR_NONE, 'B', always, 1),
    ('gen.risks', 'generation', 'body/chassis repair risks, each priced (or a check: none found)', _risks, ('NONE FOUND',), None, always, 1),
    ('eng.identity', 'engine', 'code, fuel, displacement, power, aspiration, injection, timing drive', _fields(
        'code', 'fuel_type', 'displacement_cc', 'power_ps', 'aspiration', 'injection', 'timing_drive', code=True), (), None, combustion, 1),
    ('eng.identity_ev', 'engine', 'electric: code, fuel, power, usable battery kWh, AC charging kW', _fields(
        'code', 'fuel_type', 'power_ps', 'battery_usable_kwh', 'ac_charge_kw', code=True), (), None, electric, 3),
    ('eng.hv_battery', 'engine', 'electric: battery warranty (years / km / % health) and the battery risk checked', None, FOUND_OR_NONE, 'B', electric, 3),
    ('eng.drive_coolant', 'engine', 'electric: battery/motor coolant interval and workshop price (or a check: lifetime fill)', _job('DRIVE_COOLANT'), ('NONE FOUND',), None, electric, 3),
    ('eng.reduction_gear_oil', 'engine', 'electric: reduction gear oil interval and workshop price (or a check: none scheduled)', _job('REDUCTION_GEAR_OIL'), ('NONE FOUND',), None, electric, 3),
    ('eng.oil', 'engine', 'oil and filter service: interval, DIY parts and workshop price', _job('OIL_SERVICE'), (), None, combustion, 2),
    ('eng.air_filter', 'engine', 'air filter: interval, DIY parts and workshop price', _job('AIR_FILTER'), (), None, combustion, 2),
    ('eng.spark_plugs', 'engine', 'spark plugs: interval, DIY parts and workshop price', _job('SPARK_PLUGS'), (), None, petrol, 2),
    ('eng.fuel_filter', 'engine', 'fuel filter: interval, DIY parts and workshop price', _job('FUEL_FILTER'), (), None, diesel, 2),
    ('eng.timing_belt', 'engine', 'timing belt: interval, DIY parts and workshop price', _job('TIMING_DRIVE'), (), None,
     lambda ctx: combustion(ctx) and not _is('timing_drive', 'CHAIN', 'GEAR')(ctx), 2),
    ('eng.timing_chain', 'engine', 'timing chain/gear: a job or a check that none is scheduled', _job('TIMING_DRIVE'), ('NONE FOUND',), None,
     _is('timing_drive', 'CHAIN', 'GEAR'), 2),
    ('eng.coolant', 'engine', 'coolant: interval, DIY parts and workshop price (or a check: lifetime fill)', _job('COOLANT'), ('NONE FOUND',), None, combustion, 2),
    ('eng.risks', 'engine', 'engine repair risks, each priced (or a check: none found)', _risks, ('NONE FOUND',), None, always, 1),
    ('var.identity', 'variant', 'HSN/TSN, gearbox, body, emissions class, CO2', _fields(
        'hsn', 'tsn', 'transmission', 'body_style', 'emissions_standard', 'co2_g_km', status='technical_status'), (), None, always, 1),
    ('var.consumption', 'variant', f'{config.PRIMARY_CONSUMPTION} with sample size, min and max (electric: {config.PRIMARY_CONSUMPTION_EV}, kWh/100 km of the exact variant and battery)',
     _consumption, (), 'C', always, 1),
    ('var.tyres', 'variant', 'all-season tyres: size, price, tread life (variant or generation)', _tyres, (), None, always, 1),
    ('var.tax', 'variant', 'annual tax from the BMF Kfz-Steuer-Rechner', _tax, (), 'A', always, 1),
    ('gbx.identity', 'gearbox', 'gearbox code, type and number of gears', _fields('code', 'type', 'gears'), (), None, always, 5),
    ('gbx.oil', 'gearbox', 'DCT / automatic / CVT oil service: interval and workshop price (or a check: lifetime fill)',
     _job('GEARBOX_OIL'), ('NONE FOUND',), None, oil_change_gearbox, 5),
    ('gbx.risks', 'gearbox', 'gearbox repair risks, each priced (or a check: none found)', _risks, ('NONE FOUND',), None, always, 5),
]
# weak points: the same sources per part (docs/cost-research-protocol.md, step 2), each on the level the part belongs to
# (issue #164): ENGINE on the engine (with an engine-specific source), GEARBOX on the gearbox (its faults follow the
# gearbox type, not the model), CHASSIS and ELECTRICS on the generation
REL_LEVEL = {'ENGINE': 'engine', 'GEARBOX': 'gearbox', 'CHASSIS': 'generation', 'ELECTRICS': 'generation'}
for _part in config.RELIABILITY_PARTS:
    for _src, _q in REL_SOURCES.items():
        if _src != 'engine_specific' or _part == 'ENGINE':
            ITEMS.append((f'rel.{_part}.{_src}', REL_LEVEL[_part], f'{_part.lower()} weak points: {_src.replace("_", "-")} source checked',
                          None, FOUND_OR_NONE, _q, always, 5 if _part == 'GEARBOX' else 1))
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
    ctx = {'row': row, 'rows': rows, 'sources': sources}
    out = []
    for iid, lvl, title, cands, results, min_q, applies, since in ITEMS:
        if lvl != level or not applies(ctx):
            continue
        found = list(cands(ctx)) if cands else []
        found += [r for r in rows('research_checks') if r['task'] == iid and r['result'] in results and r['contract_version'] >= since]
        # na_only: every result is N/A (the source does not cover this model yet, e.g. too new for ADAC/TÜV statistics)
        out.append({'id': iid, 'level': lvl, 'title': title, 'grade': grade_rows(found, sources, min_q),
                    'na_only': bool(found) and all(x.get('result') == 'N/A' for x in found)})
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
        self.rows = {t: {r['id']: r for r in rows(c, f'SELECT * FROM {t}')} for t in ('vehicles', 'engines', 'gearboxes', 'generations')}
        self.index = {}
        for table, rs in know.t.items():
            for r in rs:
                for col in config.SCOPE_COLUMNS:
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
        if key not in self.cache:
            extra = {'generation': ('generation_id', row.get('generation_id'))} if level == 'variant' else None
            self.cache[key] = evaluate(level, row, self._rows([(LEVEL_COL[level], row['id'])], extra), self.sources)
        return self.cache[key]

    def resolved(self, vehicle_id):
        """A variant with its engine and generation. An item missing on its level but present one level lower (e.g. an
        engine job stored on the variant) counts as ACCEPTED at most, with a hint to move the row up."""
        v = self.rows['vehicles'][vehicle_id]
        engine, generation = self.rows['engines'][v['engine_id']], self.rows['generations'][v['generation_id']]
        # a variant without a gearbox yet (#164) still owes the gearbox research: its items are graded on an empty row
        gearbox = self.rows['gearboxes'].get(v.get('gearbox_id')) or {'id': None}
        out = []
        # only the variant counts as "too low": an engine row is the engine's research, not the generation's
        lower = {'generation': [('vehicle_id', v['id'])], 'engine': [('vehicle_id', v['id'])],
                 'gearbox': [('vehicle_id', v['id'])], 'variant': []}
        for level, row in (('generation', generation), ('engine', engine), ('gearbox', gearbox), ('variant', v)):
            below = None
            for i in self.level(level, row):
                if i['grade'] == 'MISSING' and lower[level]:
                    below = below or {x['id']: x['grade'] for x in evaluate(level, row, self._rows(lower[level]), self.sources)}
                    if below.get(i['id'], 'MISSING') != 'MISSING':
                        i = {**i, 'grade': 'ACCEPTED', 'hint': f'found on a lower level: move it to the {level}'}
                out.append(i)
        return out


def known_parts(items, evidence=frozenset()):
    """Reliability parts whose required source checks are all present (owner decision: otherwise the part is unknown).
    A part whose long-term statistics (the ADAC and TÜV checks) are both N/A (the model is too new for them) is unknown
    too, never a clean record, unless a weak point was documented for it (`evidence`: parts with reliability rows; a
    buying guide finding nothing about a brand-new model is no track record; issue #150)."""
    known = set()
    for p in config.RELIABILITY_PARTS:
        its = [i for i in items if i['id'].startswith(f'rel.{p}.')]
        stats = [i for i in its if i['id'] in (f'rel.{p}.adac', f'rel.{p}.tuev')]
        if all(i['grade'] != 'MISSING' for i in its) and (p in evidence or not stats or not all(i.get('na_only') for i in stats)):
            known.add(p)
    return known


def too_new_parts(items, evidence=frozenset()):
    """The parts unknown only because no source covers the model yet (shown as such in the dossier)."""
    return [p for p in config.RELIABILITY_PARTS if p not in known_parts(items, evidence)
            and p in known_parts([{**i, 'na_only': False} for i in items], evidence)]


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
        add('lst.checklist', 'a checklist item for every weak point', rows['weak_points'] <= rows['checked'])
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
    """Summary per level (generation, engine, gearbox, variant, listing) of resolved items, for the UI."""
    return {lvl: summary([i for i in items if i['level'] == lvl]) for lvl in LEVEL_ORDER
            if any(i['level'] == lvl for i in items)}


def confidence(items):
    """Mean grade of the applicable items (VERIFIED 1, ACCEPTED 0.5, MISSING 0) as a percentage; None without items."""
    return round(sum(GRADE[i['grade']] for i in items) / len(items) * 100) if items else None
