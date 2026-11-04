"""What the agent should research next, per listing and per variant (resolved over variant, engine and generation)."""
import datetime
from . import config
from .costs import Knowledge, days_since
from .db import rows, variant_name, variants


def todo(c, p, ranked):
    today = datetime.date.today()
    snaps = {r[0] for r in c.execute('SELECT DISTINCT listing_id FROM listing_snapshots')}
    vals = {(r[0], r[1]) for r in c.execute('SELECT listing_id, kind FROM valuations')}
    listings = []
    for u in ranked:
        if u['listing_status'] == 'WITHDRAWN':
            continue
        t = [f'cost component missing: {k}' for k in u['missing_components']]
        if (u['fuel_type'] or '').lower() == 'diesel' and not p.get('diesel_price_eur_l'):
            t.append('diesel price missing (Settings: diesel_price_eur_l)')
        if u['is_reference'] and (u['id'], 'sale_today') not in vals:
            t.append('valuation missing: sale_today')
        for field in ('first_registration', 'mileage_km') + (() if u['is_reference'] else ('price_eur', 'url')):
            if u[field] is None:
                t.append(f'listing field missing: {field}')
        if not u['is_reference']:
            if u['id'] not in snaps:
                t.append('no listing capture (listing_snapshots)')
            if not u['photo_count']:
                t.append('no archived photos')
            hist = u['price_history']
            if hist and u['price_eur'] is not None and hist[-1]['price_eur'] != u['price_eur']:
                t.append(f"listing price_eur ({u['price_eur']:g}) differs from the latest capture ({hist[-1]['price_eur']:g}): update it")
            if u['stale']:
                t.append(f'not checked for over {config.STALE_LISTING_DAYS} days: re-check availability and price')
            if not u['inspection_counts']:
                t.append('no inspection checklist')
            if u['verdict'] is None:
                t.append('no verdict')
        listings.append({'listing_id': u['id'], 'name': f"{u['make']} {u['model']} {u['listing_id'] or '(reference)'}", 'todo': t})
    know = Knowledge(c)
    sources = {r['id']: r for r in rows(c, 'SELECT id, source_type FROM sources')}
    models = []
    for v in variants(c):
        t = [f'generation field missing: {f}' for f, col in (('start_year', 'generation_start_year'), ('end_year', 'generation_end_year'),
                                                            ('facelift_year', 'facelift_year')) if v[col] is None]
        t += [f'engine field missing: {f}' for f, col in (('power_ps', 'power_ps'), ('timing_drive', 'timing_drive'),
                                                         ('aspiration', 'aspiration'), ('injection', 'injection')) if v[col] is None]
        if v['transmission'] is None:
            t.append('variant field missing: transmission')
        if (v['engine_code'] or '').startswith('unknown'):
            t.append('engine code missing (engines.code)')
        if v['hsn'] is None or v['tsn'] is None:
            t.append('HSN/TSN missing (vehicles.hsn, vehicles.tsn)')
        if know.consumption(v) is None:
            t.append(f'real-world consumption missing ({config.PRIMARY_CONSUMPTION})')
        if not know.of('repair_risks', v):
            t.append('repair risks missing (repair_risks)')
        tyres = know.tyres(v)
        if tyres is None or tyres['price_per_tyre_eur'] is None or tyres['life_km'] is None:
            t.append('tyre data missing (tyre_data)')
        maint = know.of('maintenance_items', v)
        if not any(m['active'] and (m['item'] or '').startswith('HU') for m in maint):
            t.append('HU/AU inspection missing from the maintenance schedule')
        if not any(m['interval_km'] is not None for m in maint):
            t.append('maintenance schedule missing')
        tax_rows = [r for r in know.of('tax_data', v) if r['annual_tax_eur'] is not None]
        if not tax_rows:
            t.append('annual tax missing')
        else:
            tx = max(tax_rows, key=lambda r: r['id'])
            if (sources.get(tx['source_id']) or {}).get('source_type') != config.TAX_OFFICIAL_SOURCE:
                t.append('tax not from the BMF Kfz-Steuer-Rechner')
        ins = [r for r in know.of('insurance_data', v) if r['annual_premium_eur'] is not None]
        if not ins:
            t.append('insurance premium missing (a Typklasse is not a premium)')
        quotes = [r for r in ins if r['premium_status'] == 'QUOTE']
        if quotes:
            q = max(quotes, key=lambda r: r['id'])
            age = days_since(q['quote_date'], today)
            if age is None:
                t.append('insurance quote without quote_date')
            elif age > config.QUOTE_MAX_AGE_DAYS:
                t.append(f'insurance quote older than {config.QUOTE_MAX_AGE_DAYS} days: request a new quote')
        if not know.of('reliability_items', v):
            t.append('reliability research missing')
        models.append({'vehicle_id': v['id'], 'engine_id': v['engine_id'], 'generation_id': v['generation_id'],
                       'name': variant_name(v), 'todo': t})
    return {'listings': listings, 'models': models}
