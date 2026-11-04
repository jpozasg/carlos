"""Helpers for research agents: write cost data through the local agent API the same way for every car.

Protocol: docs/cost-research-protocol.md. Usage from a script (standard library only):

    import sys; sys.path.insert(0, '/path/to/carlos')
    from agent_tools import *
    s = src(vehicle_id=V, title='...', url='...', source_type='parts_prices', quality='D', supports='...', limitations='...')
    item(V, 'Engine oil and filter (DIY)', 15000, 12, True, 60.0, None, 0.75, s, 'ESTIMATED', '...')

Every helper writes through the API (never SQLite directly), so the change log and dossiers stay consistent.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from capture_listing import Api, load_token  # noqa: E402

API_BASE = os.environ.get('CAR_API', 'http://127.0.0.1:8000')
api = Api(API_BASE, load_token())
DAY = datetime.date.today().isoformat()
PRIMARY_CONSUMPTION = 'Autokostencheck average'

# Shared conventions (the same for every car so totals stay comparable). Regional figures: adjust them to the
# account's region from an official fee table and register that table as a shared source with the title prefix used here.
TYRE_LIFE_KM = 45000          # all-season tyre tests: tread life ~35–68k km, typical ~45k km
TYRE_FITTING_EUR = 125.0      # fitting + balancing per set incl. disposal (typical German range 90–160 €)
HU_FEE_EUR = 163.0            # HU incl. AU, typical German inspection fee 2026 (source: shared source 'HU/AU price')
PURCHASE_SALE_DEFAULTS = (    # (item, amount, shared source title prefix, note)
    ('Re-registration with new plates (Umschreibung)', 34.00, 'Registration fees', 'Registration office fee + KBA fee + seals; a fee, not parts.'),
    ('Number plates (pair)', 35.00, 'Number plates', 'Plate maker next to the office; online plates are cheaper (DIY order).'),
    ('Pre-purchase check (motoring club, members)', 159.00, 'Pre-purchase check', 'Recommended before buying; cheaper inspection-organisation checks exist (~79 €).'),
)


# ---------------------------------------------------------------- basic API calls
def get(path):
    return api.call('GET', path)


def post(table, row):
    return api.call('POST', f'/api/agent/{table}', row)['id']


def patch(table, rid, row):
    return api.call('PATCH', f'/api/agent/{table}/{rid}', row)


def src(**row):
    """Register a source (quality A–D, URL, supports, limitations). Returns its id."""
    return post('sources', {'accessed_date': DAY, **row})


def shared_source(title_prefix):
    """Id of the newest shared source whose title starts with title_prefix (fees, HU, tyres, depreciation, ...)."""
    rows = [s for s in get('/api/sources') if (s.get('title') or '').startswith(title_prefix)]
    if not rows:
        raise LookupError(f'no shared source titled {title_prefix!r}')
    return max(rows, key=lambda s: s['id'])['id']


def listing(listing_id):
    return get(f'/api/listings/{listing_id}')


def log(listing_id, kind, text, source_id=None):
    """Listing log entry (kinds: found, verification, correction, price, decision, user_data, warning, ...)."""
    return post('listing_events', {'listing_id': listing_id, 'event_date': DAY, 'kind': kind, 'text': text, 'source_id': source_id})


# ---------------------------------------------------------------- data levels (issue #44)
LEVEL_COLUMNS = {'variant': 'vehicle_id', 'engine': 'engine_id', 'generation': 'generation_id'}


def scope(v, level='variant'):
    """The column that attaches a knowledge row to a level. `v` is the variant id (vehicles.id); with level 'engine'
    or 'generation' the row is attached to that variant's engine or generation, so every variant sharing it
    inherits the row. Pass an explicit id with level_id=... in the helpers when you have it."""
    if level == 'variant':
        return {'vehicle_id': v}
    var = get(f'/api/vehicles/{v}')
    return {LEVEL_COLUMNS[level]: var[LEVEL_COLUMNS[level]]}


def variant(v):
    """The variant with its engine, generation, resolved knowledge rows (each with `level`) and listings."""
    return get(f'/api/vehicles/{v}')


def engine(**row):
    """Register an engine (code, description, fuel_type, displacement_cc, power_kw/ps, aspiration, injection, timing_drive)."""
    return post('engines', row)


def generation(**row):
    """Register a model generation (make, model, name, start_year, end_year, facelift_year, status)."""
    return post('generations', row)


# ---------------------------------------------------------------- model data
def consumption(v, value, n, lo, hi, source_id, notes='', level='variant'):
    """Primary real-world consumption (autokostencheck.de average of the exact HSN/TSN variant)."""
    return post('observations', {**scope(v, level), 'category': 'consumption', 'metric': PRIMARY_CONSUMPTION, 'value_num': value,
                                 'unit': 'l/100 km', 'sample_count': n, 'min_value': lo, 'max_value': hi, 'status': 'PRIMARY',
                                 'evidence_quality': 'C', 'observed_date': DAY, 'source_id': source_id,
                                 'notes': ('Primary consumption figure (same source for all cars, user decision 2026-11-03). ' + notes).strip()})


def reliability(v, component, issue, evidence, severity, source_id, inspection_action, frequency_status='PENDING', level='variant'):
    """Known weak point; inspection_action becomes a checklist item for every listing of the model. Engine faults go
    on the engine (level='engine'), body/chassis faults on the generation, variant-only quirks on the variant."""
    return post('reliability_items', {**scope(v, level), 'component': component, 'issue': issue, 'evidence': evidence,
                                      'severity': severity, 'frequency_status': frequency_status, 'source_id': source_id,
                                      'inspection_action': inspection_action})


def checklist_from_reliability(listing_id):
    """Add missing checklist items from the model's reliability_items (capture_listing does this only at capture time)."""
    u = listing(listing_id)
    have = {i['item'] for i in u.get('inspection', [])}
    added = 0
    for r in u.get('reliability', []):
        text = r.get('inspection_action')
        if text and text not in have:
            post('inspection_items', {'listing_id': listing_id, 'item': text, 'status': 'PENDING',
                                      'notes': f"From reliability item: {r.get('component')}"})
            have.add(text)
            added += 1
    return added


def deactivate_packages(v, listing_id):
    """Old service packages stay as history but stop counting once an item schedule exists."""
    for m in listing(listing_id)['maintenance']:
        if m['schedule'] == 'PACKAGE' and m['active']:
            patch('maintenance_items', m['id'], {'active': 0})


def item(v, name, km, months, diy, parts, workshop, hours, source_id, status, notes, level='variant'):
    """Maintenance item: DIY → parts price + hours; workshop → total job price in `workshop`.
    Engine jobs (oil, plugs, timing drive, coolant) belong on the engine; brakes, HU, wipers on the generation."""
    return post('maintenance_items', {**scope(v, level), 'item': name, 'interval_km': km, 'interval_months': months,
                                      'schedule': 'ITEM', 'diy': 1 if diy else 0, 'diy_parts_cost_eur': parts,
                                      'reference_cost_eur': workshop, 'diy_hours': hours, 'labor_included': 0 if diy else 1,
                                      'status': status, 'source_id': source_id, 'notes': notes, 'active': 1})


def hu(v, level='generation'):
    return item(v, 'HU/AU inspection', None, 24, False, None, HU_FEE_EUR, None, shared_source('HU/AU price'),
                'OFFICIAL FEE LEVEL', 'Every 24 months; 2 inspections in a 4-year period. Timing depends on the HU date of the car.', level)


def risk(v, component, km_from, km_to, probability, parts, labor, diy, hours, source_id, evidence, notes='', level='variant'):
    """Expected repair: probability of failure somewhere in [km_from, km_to]. Every risk needs a price: estimate one when
    none is found (user decision 2026-11-03) and say how in `notes`."""
    if parts is None and labor is None:
        raise ValueError(f'{component}: every risk needs a price; estimate one and say how in notes')
    return post('repair_risks', {**scope(v, level), 'component': component, 'km_from': km_from, 'km_to': km_to,
                                 'probability': probability, 'parts_eur': parts, 'labor_eur': labor, 'diy': 1 if diy else 0,
                                 'diy_hours': hours, 'status': 'ESTIMATED', 'evidence': evidence, 'source_id': source_id, 'notes': notes})


def tyres(v, size, price_per_tyre, source_id, notes, life_km=TYRE_LIFE_KM, fitting=TYRE_FITTING_EUR, level='variant'):
    return post('tyre_data', {**scope(v, level), 'tyre_type': 'ALL-SEASON', 'size': size, 'price_per_tyre_eur': price_per_tyre,
                              'tyres_per_set': 4, 'life_km': life_km, 'fitting_per_set_eur': fitting, 'status': 'ESTIMATED',
                              'source_id': source_id, 'notes': notes})


# ---------------------------------------------------------------- listing data
def certain(listing_id, category, name, parts, labor, hours, source_id, notes):
    """One-off cost that will happen for this car (e.g. timing belt due by age): category repairs/tyres/purchase_sale."""
    return post('unit_costs', {'listing_id': listing_id, 'category': category, 'item': name, 'parts_eur': parts,
                               'labor_eur': labor, 'diy_hours': hours, 'status': 'ESTIMATED', 'source_id': source_id, 'notes': notes})


def restart(listing_id, maintenance_item_id, basis, source_id, unit_cost_id=None, notes=None):
    """A scheduled job done at the start of ownership (basis CERTAIN REPAIR, SELLER CLAIM or DOCUMENTED): the schedule
    restarts for this listing, so only whole intervals after it count instead of the expected share."""
    return post('maintenance_resets', {'listing_id': listing_id, 'maintenance_item_id': maintenance_item_id, 'basis': basis,
                                       'unit_cost_id': unit_cost_id, 'source_id': source_id, 'notes': notes})


def purchase_sale_defaults(listing_id):
    """Registration, plates and pre-purchase check: the same three items for every car for sale."""
    have = {c['item'] for c in listing(listing_id).get('unit_costs', []) if c['category'] == 'purchase_sale'}
    for name, amount, prefix, note in PURCHASE_SALE_DEFAULTS:
        if name not in have:
            post('unit_costs', {'listing_id': listing_id, 'category': 'purchase_sale', 'item': name, 'parts_eur': amount,
                                'labor_eur': None, 'status': 'ESTIMATED', 'source_id': shared_source(prefix), 'notes': note})


def resale_rule_of_thumb(listing_id, years=None):
    """resale_end from the asking price: expected 6 %/year + 10 % private-sale discount; low 10 %/year + 20 %;
    high 3 %/year + 5 %. Replace with a comparable-listings valuation when one exists."""
    u = listing(listing_id)
    price = u['price_eur']
    years = years or get('/api/listings')['parameters']['ownership_years']
    r = lambda rate, disc: round(price * (1 - rate) ** years * (1 - disc), -1)
    return post('valuations', {'listing_id': listing_id, 'kind': 'resale_end', 'horizon_years': years,
                               'low_eur': r(0.10, 0.20), 'expected_eur': r(0.06, 0.10), 'high_eur': r(0.03, 0.05),
                               'status': 'ESTIMATED', 'valued_date': DAY, 'source_id': shared_source('Allianz'),
                               'notes': f'Rule-of-thumb estimate from the asking price {price:.0f} €: expected 6%/year and 10% '
                                        'private-sale discount; low 10%/year and 20%; high 3%/year and 5%. Not model-specific; '
                                        'refine with comparable listings.'})


def todo(listing_id=None, vehicle_id=None):
    """Open to-do items for one listing and/or one model (all when no id is given)."""
    t = get('/api/agent/todo')
    rows = [r for r in t['listings'] if listing_id in (None, r['listing_id'])] if vehicle_id is None or listing_id else []
    rows += [r for r in t['models'] if vehicle_id in (None, r['vehicle_id'])] if listing_id is None or vehicle_id else []
    return [r for r in rows if r['todo']]
