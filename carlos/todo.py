"""What the agent should research next: per listing, per variant (resolved over variant, engine and generation) and per
catalogue level on its own, all from the research contract (carlos/research.py, issue #114)."""
import datetime
from . import config, research
from .costs import Knowledge, days_since, electricity_price, is_new
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
        # the price this account's DIY choice needs is missing: never the other price instead (#106 part 4)
        t += [f'price missing for the account\'s DIY choice: {x}' for x in u.get('unpriced', [])]
        if (u['fuel_type'] or '').lower() == 'diesel' and not p.get('diesel_price_eur_l'):
            t.append('diesel price missing (Settings: diesel_price_eur_l)')
        if u['fuel_type'] == 'Electric':  # electric cars (#121)
            miss = electricity_price(p)[1]
            if miss:
                t.append('charging answers missing for the energy cost (setup Charging step / Settings): ' + ', '.join(miss))
            if not u['is_reference'] and u.get('battery_soh_claim') is None:
                t.append('battery state of health unknown: ask the seller for a SoH certificate (method, date, km)')
        if u['fuel_type'] == 'Plug-in hybrid':
            t.append('plug-in hybrid: energy cost not supported yet, fuel stays unknown (owner decision 2026-11-05)')
        if u['is_reference'] and (u['id'], 'sale_today') not in vals:
            t.append('valuation missing: sale_today')
        lease = not u['is_reference'] and u.get('lease_monthly_eur') is not None  # a lease offer (#127)
        if lease:
            t += [f'lease field not stated: {f} (ask the dealer; null is never 0)' for f in
                  ('lease_term_months', 'lease_km_per_year', 'lease_down_payment_eur', 'lease_fees_eur') if u.get(f) is None]
            if u.get('lease_kind') is None:
                t.append('lease kind not recorded: km, residual or abo')
            elif u['lease_kind'] == 'residual':
                t.append('residual-value leasing: recorded, not costed (owner decision 2026-11-05)')
            # a lease rate rarely includes insurance; lessors require fully comprehensive cover (#129)
            if u.get('offer') == 'lease' and u['components']['insurance'] is None:
                t.append('lease without insurance in the rate: get a Vollkasko quote ("geleast", docs/browser-tasks.md)')
        for field in ('first_registration', 'mileage_km') + (() if u['is_reference'] else (() if lease else ('price_eur',)) + ('url',)):
            if u[field] is None and not (field == 'first_registration' and is_new(u)):  # a new car has none yet (#162)
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
        # the contract's listing items that no line above covers (an expired quote, a weak point without a checklist item)
        t += [f"listing {i['id']} missing: {i['title']}" for i in u['research']
              if i['id'] in ('lst.insurance', 'lst.checklist') and i['grade'] == 'MISSING']
        listings.append({'listing_id': u['id'], 'name': f"{u['make']} {u['model']} {u['listing_id'] or '(reference)'}", 'todo': t})
    know = Knowledge(c)
    contract = research.Contract(c, know)
    level = contract.rows
    models = []
    for v in variants(c):
        items = contract.resolved(v['id'])
        t = [f"{i['level']} {i['id']} missing: {i['title']}" for i in items if i['grade'] == 'MISSING']
        t += [f"{i['level']} {i['id']}: {i['hint']}" for i in items if i.get('hint')]
        loose = [r['id'] for r in know.of('reliability_items', v) if r.get('part') is None]
        if loose:
            t.append(f"reliability items without a part (reliability_items.part), reliability unknown: ids {loose}")
        models.append({'vehicle_id': v['id'], 'engine_id': v['engine_id'], 'generation_id': v['generation_id'],
                       'name': variant_name(v), 'state': research.state(items), 'todo': t})
    # each catalogue level on its own rows only, so "researched" does not depend on the listing that triggered it
    labels = (('generations', 'generations', 'generation', lambda r: f"{r['make']} {r['model']} {r['name']}"),
              ('engines', 'engines', 'engine', lambda r: r['code']),
              ('variants', 'vehicles', 'variant', lambda r: r['trim'] or f"#{r['id']}"))
    catalogue = {name: [{'id': r['id'], 'name': label(r), **without_items(research.summary(contract.level(lvl, r)))}
                        for r in level[table].values()] for name, table, lvl, label in labels}
    return {'account': account_todo(c, p, today), 'listings': listings, 'models': models, 'catalogue': catalogue}


def without_items(summary):
    return {k: v for k, v in summary.items() if k != 'items'}


# What a comparison-site quote needs from the account (docs/browser-tasks.md, setup wizard Drivers/Insurance steps).
QUOTE_PARAMS = ('postal_code', 'sf_class', 'insurance_cover', 'insurance_deductible_eur', 'annual_km')
QUOTE_PREFS = ('insurance_holder_gender', 'insurance_holder_birth_date', 'insurance_holder_licence_date', 'insurance_holder_occupation',
               'insurance_holder_marital', 'insurance_claims_3y', 'insurance_usage', 'insurance_parking', 'insurance_start_date')


def account_todo(c, p, today):
    """Gaps of the account itself: setup, ranking answers, fuel price, the profile an insurance quote needs."""
    prefs = {r[0]: r[1] for r in c.execute('SELECT preference_key, preference_value FROM project_preferences')}
    t = []
    if not prefs.get('onboarding_done'):
        t.append('setup not finished (the user runs it at #/start)')
    if not (p.get('ranking_answers') or '').strip('{} ') and not p.get('ranking_weights'):
        t.append('ranking choices not made (Ranking page): every criterion weighs the same')
    age = days_since(p.get('fuel_price_date'), today)
    if age is None or age > config.STALE_FUEL_PRICE_DAYS:
        t.append(f'fuel price older than {config.STALE_FUEL_PRICE_DAYS} days or undated (Settings)')
    if c.execute("SELECT 1 FROM listings l JOIN vehicles v ON v.id=l.vehicle_id JOIN engines e ON e.id=v.engine_id "
                 "WHERE e.fuel_type='Electric' AND l.listing_status!='WITHDRAWN'").fetchone():
        for k in ('electricity_home', 'electricity_public'):
            age = days_since(p.get(k + '_date'), today)
            if p.get(k + '_eur_kwh') is not None and (age is None or age > config.STALE_FUEL_PRICE_DAYS):
                t.append(f'{k.replace("_", " ")} price older than {config.STALE_FUEL_PRICE_DAYS} days or undated (Settings)')
    missing = [k for k in QUOTE_PARAMS if p.get(k) in (None, '')] + [k for k in QUOTE_PREFS if not prefs.get(k)]
    if missing:
        t.append('insurance profile incomplete for quotes (ask the user or the setup Drivers/Insurance steps): ' + ', '.join(missing))
    return t
