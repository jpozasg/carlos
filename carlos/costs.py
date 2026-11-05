"""Cost calculation per listing over the ownership period (README, "Calculation"). NULL means unknown, never 0."""
import datetime, re
from . import config
from .db import for_variant, latest, rows, scoped
from .ranking import QUALITY_POINTS, SEVERITY_POINTS, STATUS_POINTS


def occurrences(interval_km, interval_months, km, months, restarted=False):
    """How often a job falls due in the period, whichever comes first (km or months); 0 without an interval.
    Expected value (period ÷ interval) because a used car's position in its service cycle is unknown; whole intervals
    when the job was done at the start of ownership (`restarted`: certain repair, documented or claimed by the seller)."""
    if restarted:
        return max(km // interval_km if interval_km else 0, months // interval_months if interval_months else 0)
    return max(km / interval_km if interval_km else 0, months / interval_months if interval_months else 0)


def maintenance_plan(items, km, months, restarted=frozenset()):
    """Per-job view of the item schedule over the period (what maintenance_cost adds up): occurrences, price used,
    cost and DIY hours; cost None when a due job has no price."""
    plan = []
    for i in items:
        if not i['active'] or i['schedule'] != 'ITEM' or not (i['interval_km'] or i['interval_months']):
            continue
        n = occurrences(i['interval_km'], i['interval_months'], km, months, i['id'] in restarted)
        price = i['diy_parts_cost_eur'] if i['diy'] else i['reference_cost_eur']
        plan.append({'id': i['id'], 'item': i['item'], 'level': i.get('level'), 'interval_km': i['interval_km'],
                     'interval_months': i['interval_months'], 'diy': i['diy'], 'price_eur': price, 'occurrences': round(n, 3),
                     'restarted': i['id'] in restarted, 'cost_eur': None if (n and price is None) else round(n * (price or 0), 2),
                     'diy_hours': round(n * i['diy_hours'], 2) if i['diy'] and i['diy_hours'] else 0,
                     'status': i['status'], 'source_id': i['source_id'], 'notes': i['notes']})
    return plan


def risk_plan(risks, km_now, km_period):
    """Per-risk view of the expected repairs (what expected_repairs adds up): share of the km window driven in the
    period and expected cost."""
    out = []
    km_end = (km_now or 0) + km_period
    for r in risks:
        share = 0 if km_now is None else max(0, min(r['km_to'], km_end) - max(r['km_from'], km_now)) / (r['km_to'] - r['km_from'])
        priced = not (r['parts_eur'] is None and r['labor_eur'] is None)
        unit = (r['parts_eur'] or 0) + (0 if r['diy'] else (r['labor_eur'] or 0)) if priced else None
        out.append({**{k: r[k] for k in ('id', 'component', 'km_from', 'km_to', 'probability', 'parts_eur', 'labor_eur', 'diy',
                                          'diy_hours', 'status', 'evidence', 'source_id', 'notes')}, 'level': r.get('level'),
                    'price_eur': unit, 'share': round(share, 3),
                    'expected_eur': None if (share and unit is None) else round(share * r['probability'] * (unit or 0), 2)})
    return out


def maintenance_cost(items, km, months, restarted=frozenset()):
    """(cost, diy_hours) of scheduled maintenance over the period; (None, None) without data.
    Item schedules (schedule='ITEM') are costed one by one: DIY parts when the owner does the job (diy=1), otherwise the
    workshop reference; an item with an unknown price that falls due makes the total unknown (never 0). Without item
    rows the former service-package logic is used."""
    active = [i for i in items if i['active']]
    items_ = [i for i in active if i['schedule'] == 'ITEM' and (i['interval_km'] or i['interval_months'])]
    if not items_:
        return scheduled_maintenance([i for i in active if i['schedule'] == 'PACKAGE'], km, months), None
    total, hours = 0.0, 0.0
    for i in items_:
        n = occurrences(i['interval_km'], i['interval_months'], km, months, i['id'] in restarted)
        if not n:
            continue
        price = i['diy_parts_cost_eur'] if i['diy'] else i['reference_cost_eur']
        if price is None:
            return None, None
        total += n * price
        if i['diy'] and i['diy_hours']:
            hours += n * i['diy_hours']
    return total, hours


def expected_repairs(risks, km_now, km_period):
    """(expected cost, expected DIY hours) of repairs: each risk fails with `probability` somewhere in [km_from, km_to];
    the car is exposed to the share of that window it drives through. None without risks or without a mileage."""
    if not risks or km_now is None:
        return None, None
    km_end = km_now + km_period
    cost = hours = 0.0
    for r in risks:
        share = max(0, min(r['km_to'], km_end) - max(r['km_from'], km_now)) / (r['km_to'] - r['km_from'])
        if not share:
            continue
        if r['parts_eur'] is None and r['labor_eur'] is None:
            return None, None  # a risk without any price makes the expected repairs unknown (never 0)
        unit = (r['parts_eur'] or 0) + (0 if r['diy'] else (r['labor_eur'] or 0))
        cost += share * r['probability'] * unit
        if r['diy'] and r['diy_hours']:
            hours += share * r['probability'] * r['diy_hours']
    return cost, hours


def tyre_cost(t, km_period):
    """Wear cost of tyres over the period: km / life × (set price + fitting); None without complete tyre data."""
    if t is None or None in (t['price_per_tyre_eur'], t['life_km']):
        return None
    return km_period / t['life_km'] * (t['tyres_per_set'] * t['price_per_tyre_eur'] + (t['fitting_per_set_eur'] or 0))


def scheduled_maintenance(items, km, months):
    """Cost of periodic services (workshop reference price) over the period; None without data.
    Service n is the item with the largest interval dividing n*base_interval (e.g. 15k minor, 30k major)."""
    items = [i for i in items if i['interval_km'] and i['reference_cost_eur'] is not None]
    if not items:
        return None
    base = min(items, key=lambda i: i['interval_km'])
    events = max(km // base['interval_km'], months // base['interval_months'] if base['interval_months'] else 0)
    total = 0
    for n in range(1, events + 1):
        due = [i for i in items if (n * base['interval_km']) % i['interval_km'] == 0]
        total += max(due, key=lambda i: i['interval_km'])['reference_cost_eur']
    return total


def depreciation(u, vals):
    """(expected, pessimistic, optimistic). Candidate: price − resale. Reference: sale today − resale (opportunity cost)."""
    end = vals.get('resale_end')
    start = vals['sale_today']['expected_eur'] if u['is_reference'] and 'sale_today' in vals else (
        None if u['is_reference'] else u['price_eur'])
    if end is None or start is None:
        return None, None, None
    return (start - end['expected_eur'],
            start - end['low_eur'] if end['low_eur'] is not None else None,
            start - end['high_eur'] if end['high_eur'] is not None else None)


def age_years(first_registration, today):
    """Years since first registration ('YYYY', 'YYYY-MM' or 'YYYY-MM-DD'); None if unknown."""
    m = re.match(r'(\d{4})(?:-(\d{2}))?', first_registration or '')
    if not m:
        return None
    month = int(m[2]) if m[2] else 7  # shortcut: a year-only date is taken as mid-year
    return round(today.year - int(m[1]) + (today.month - month) / 12, 1)


def days_since(iso_date, today):
    try:
        return (today - datetime.date.fromisoformat(iso_date[:10])).days
    except (TypeError, ValueError):
        return None


def budget(p):
    """Purchase budget from the parameters (Settings): ideal and maximum asking price; None when not set."""
    return {'ideal': p.get('budget_ideal_eur'), 'max': p.get('budget_max_eur')}


def check_budget(p):
    """The ideal budget may not exceed the maximum."""
    if p.get('budget_ideal_eur') is not None and p.get('budget_max_eur') is not None and p['budget_ideal_eur'] > p['budget_max_eur']:
        raise ValueError('budget_ideal_eur must not be greater than budget_max_eur')


UNITS_SQL = '''SELECT l.*, v.generation_id, v.engine_id, v.trim, v.transmission, v.body_style, v.model_year,
  v.emissions_standard, v.co2_g_km, v.hsn, v.tsn, v.technical_status, v.notes vehicle_notes,
  g.make, g.model, g.name generation, g.start_year generation_start_year, g.end_year generation_end_year, g.facelift_year,
  e.code engine_code, e.family engine_family, e.description engine_description, e.fuel_type, e.displacement_cc, e.cylinders,
  e.power_kw, e.power_ps, e.aspiration, e.injection, e.timing_drive
FROM listings l JOIN vehicles v ON v.id=l.vehicle_id JOIN generations g ON g.id=v.generation_id JOIN engines e ON e.id=v.engine_id
ORDER BY l.is_reference DESC, l.id'''


class Knowledge:
    """Every knowledge table loaded once and resolved per variant (variant + engine + generation rows)."""

    def __init__(self, c):
        self.t = {t: scoped(c, t) for t in config.SCOPED_TABLES}

    def of(self, table, v):
        return for_variant(self.t[table], v)

    def consumption(self, v):
        prim = [o for o in self.of('observations', v) if o['metric'] == config.PRIMARY_CONSUMPTION and o['value_num'] is not None]
        return max(prim, key=lambda o: o['id']) if prim else None

    def insurance(self, v, is_reference):
        rows_ = self.of('insurance_data', v)
        if is_reference:
            user = [r for r in rows_ if r['premium_status'] == config.USER_PREMIUM and r['annual_premium_eur'] is not None]
            if user:
                return max(user, key=lambda r: r['id'])['annual_premium_eur']
        return latest(rows_, 'annual_premium_eur')

    def tax(self, v):
        return latest(self.of('tax_data', v), 'annual_tax_eur')

    def tyres(self, v):
        rows_ = self.of('tyre_data', v)
        return max(rows_, key=lambda r: r['id']) if rows_ else None  # the latest tyre row wins

    def reliability_points(self, v):
        """Severity points of the documented watch points (not proven defects); None without research."""
        rel = self.of('reliability_items', v)
        return sum(SEVERITY_POINTS.get(r['severity'], 0) for r in rel) if rel else None

    def reliability_detail(self, v):
        return [{'id': r['id'], 'component': r['component'], 'severity': r['severity'], 'points': SEVERITY_POINTS.get(r['severity'], 0),
                 'level': r['level'], 'source_id': r['source_id']} for r in self.of('reliability_items', v)]


def simplicity(u):
    """Mechanical simplicity 0–4 from engine and variant data; None while any of the four fields is unknown."""
    if None in (u['aspiration'], u['injection'], u['timing_drive'], u['transmission']):
        return None
    return ((u['aspiration'] == 'NATURALLY ASPIRATED') + (u['injection'] in ('PORT', 'CARBURETTOR'))
            + {'CHAIN': 1, 'GEAR': 1, 'BELT': 0.5}.get(u['timing_drive'], 0) + (u['transmission'].lower().startswith('manual')))


def evidence(rows_, sources):
    """Evidence quality of data rows (status and source quality), for the confidence criterion."""
    out = []
    for r in rows_:
        if r is None:
            continue
        q = sources.get(r.get('source_id'), {}).get('quality')
        out.append({'table': r.get('_table'), 'id': r['id'], 'status': r.get('status') or r.get('premium_status'),
                    'quality': q, 'points': round((STATUS_POINTS.get(r.get('status') or r.get('premium_status'), 0) + QUALITY_POINTS.get(q, 0.3)) / 2, 2)})
    return out


def tco_rows(c, p):
    years = p['ownership_years']; km = p['annual_km'] * years
    know = Knowledge(c)
    by_listing, vals, resets, insp, photos, prices = {}, {}, {}, {}, {}, {}
    for v in rows(c, 'SELECT * FROM valuations ORDER BY id'):  # the latest valuation of each kind wins
        vals.setdefault(v['listing_id'], {})[v['kind']] = v
    for r in c.execute('SELECT listing_id, maintenance_item_id FROM maintenance_resets'):
        resets.setdefault(r['listing_id'], set()).add(r['maintenance_item_id'])
    for uc in rows(c, 'SELECT * FROM unit_costs'):
        by_listing.setdefault(uc['listing_id'], []).append(uc)
    for r in c.execute('SELECT listing_id, status, count(*) n FROM inspection_items GROUP BY listing_id, status'):
        insp.setdefault(r['listing_id'], {})[r['status']] = r['n']
    for m in c.execute('SELECT listing_id, file_path FROM listing_media ORDER BY id'):  # the first upload is the cover
        photos.setdefault(m['listing_id'], []).append(m['file_path'])
    for r in c.execute('SELECT listing_id, captured_at, price_eur FROM listing_snapshots WHERE price_eur IS NOT NULL ORDER BY captured_at, id'):
        prices.setdefault(r['listing_id'], []).append({'date': r['captured_at'][:10], 'price_eur': r['price_eur']})
    today, limits = datetime.date.today(), budget(p)
    sources = {s['id']: s for s in rows(c, 'SELECT id, quality FROM sources')}
    units = rows(c, UNITS_SQL)
    ref = next((u for u in units if u['is_reference']), None)
    ref_sale = vals.get(ref['id'], {}).get('sale_today') if ref else None
    out = []
    for u in units:
        v = {'id': u['vehicle_id'], 'engine_id': u['engine_id'], 'generation_id': u['generation_id']}
        cons = know.consumption(v)
        u.update(consumption=cons['value_num'] if cons else None, consumption_sample=cons['sample_count'] if cons else None,
                 consumption_min=cons['min_value'] if cons else None, consumption_max=cons['max_value'] if cons else None,
                 consumption_metric=cons['metric'] if cons else None, consumption_source_id=cons['source_id'] if cons else None,
                 annual_insurance=know.insurance(v, u['is_reference']), annual_tax=know.tax(v))
        costs = by_listing.get(u['id'], [])
        unit_cost = {cat: sum((x['parts_eur'] or 0) + (x['labor_eur'] or 0) for x in costs if x['category'] == cat)
                     if any(x['category'] == cat for x in costs) else None for cat in config.UNIT_COST_CATEGORIES}
        dep, dep_pess, dep_opt = depreciation(u, vals.get(u['id'], {}))
        maint, maint_hours = maintenance_cost(know.of('maintenance_items', v), km, years * 12, frozenset(resets.get(u['id'], ())))
        risk, risk_hours = expected_repairs(know.of('repair_risks', v), u['mileage_km'], km)
        wear = tyre_cost(know.tyres(v), km)
        price_l = p.get('diesel_price_eur_l') if (u['fuel_type'] or '').lower() == 'diesel' else p['fuel_price_eur_l']
        # certain one-off costs of the listing plus the model's expected costs; the expected part unknown (no risk or
        # tyre research, an unpriced risk, no mileage) makes the whole component unknown, never a smaller number
        add = lambda certain, expected: None if expected is None else (certain or 0) + expected
        parts = {
            'fuel': u['consumption'] * km / 100 * price_l if u['consumption'] is not None and price_l else None,
            'insurance': u['annual_insurance'] * years if u['annual_insurance'] is not None else None,
            'tax': u['annual_tax'] * years if u['annual_tax'] is not None else None,
            'maintenance': add(unit_cost['maintenance'], maint),
            'repairs': add(unit_cost['repairs'], risk),
            'tyres': add(unit_cost['tyres'], wear),
            'purchase_sale': unit_cost['purchase_sale'], 'depreciation': dep,
        }
        known = [x for x in parts.values() if x is not None]
        subtotal = sum(known) if known else None  # unknown = NULL, never 0
        complete = len(known) == len(config.TCO_COMPONENTS)
        rest = subtotal - (parts['depreciation'] or 0) if subtotal is not None else None
        u.update(period_km=km, components=parts, inspection_counts=insp.get(u['id'], {}),
                 cover=(photos.get(u['id']) or [None])[0], photo_count=len(photos.get(u['id'], [])), known_cost_subtotal=subtotal,
                 known_cost_per_month=subtotal / (years * 12) if subtotal is not None else None,
                 known_cost_per_km=subtotal / km if subtotal is not None else None,
                 missing_components=[k for k in config.TCO_COMPONENTS if parts[k] is None], tco_complete=complete,
                 tco_pessimistic=rest + dep_pess if complete and dep_pess is not None else None,
                 tco_optimistic=rest + dep_opt if complete and dep_opt is not None else None,
                 diy_hours=(sum(x['diy_hours'] or 0 for x in costs) + (maint_hours or 0) + (risk_hours or 0)
                            if any(x['diy_hours'] is not None for x in costs) or maint_hours or risk_hours else None),
                 cost_detail={'repairs_certain': unit_cost['repairs'], 'repairs_expected': risk, 'tyre_wear': wear,
                              'maintenance_certain': unit_cost['maintenance'], 'maintenance_scheduled': maint,
                              'tyres_certain': unit_cost['tyres'], 'fuel_price_eur_l': price_l,
                              'maintenance_diy_hours': maint_hours, 'repairs_diy_hours': risk_hours},
                 initial_outlay=(u['price_eur'] - ref_sale['expected_eur'] if not u['is_reference'] and ref_sale
                                 and u['price_eur'] is not None else None))
        age = age_years(u['first_registration'], today)
        counts = u['inspection_counts']
        tagged = lambda table, rs: [{**r, '_table': table} for r in rs if r is not None]
        ins_rows = [r for r in know.of('insurance_data', v) if r['annual_premium_eur'] is not None]
        ev = evidence(tagged('observations', [cons]) + tagged('insurance_data', ins_rows[-1:]) +
                      tagged('tax_data', [r for r in know.of('tax_data', v) if r['annual_tax_eur'] is not None][-1:]) +
                      tagged('maintenance_items', [i for i in know.of('maintenance_items', v) if i['active'] and i['schedule'] == 'ITEM']) +
                      tagged('repair_risks', know.of('repair_risks', v)) + tagged('tyre_data', [know.tyres(v)]) +
                      tagged('valuations', [x for x in vals.get(u['id'], {}).values()]) + tagged('unit_costs', costs), sources)
        u['evidence'] = ev
        u['reliability_detail'] = know.reliability_detail(v)
        u['metrics'] = {
            'cost_month': u['known_cost_per_month'] if complete else None,
            'cash_now': None if u['is_reference'] or u['price_eur'] is None or unit_cost['purchase_sale'] is None else u['price_eur'] + unit_cost['purchase_sale'],
            'mileage': u['mileage_km'], 'age': age,
            'reliability': know.reliability_points(v),
            'inspection': counts.get('PROBLEM', 0) if counts.get('OK') or counts.get('PROBLEM') else None,
            'power': u['power_ps'], 'simplicity': simplicity(u),
            'confidence': round(sum(e['points'] for e in ev) / len(ev) * 100) if ev else None,
            # informative, not ranked (they are inside cost_month)
            'price': None if u['is_reference'] else u['price_eur'],
            'km_per_year': round(u['mileage_km'] / age) if u['mileage_km'] is not None and age else None,
            'consumption': u['consumption'], 'insurance': u['annual_insurance'], 'tax': u['annual_tax']}
        price = u['price_eur']
        u['budget_status'] = (None if u['is_reference'] or price is None else
                              'over_max' if limits['max'] is not None and price > limits['max'] else
                              'over_ideal' if limits['ideal'] is not None and price > limits['ideal'] else 'within')
        hist = prices.get(u['id'], [])
        u['price_history'] = hist
        u['price_change'] = ({'eur': hist[-1]['price_eur'] - hist[0]['price_eur'], 'since': hist[0]['date']}
                             if len(hist) > 1 and hist[-1]['price_eur'] != hist[0]['price_eur'] else None)
        since = days_since(u['last_checked'], today)
        u['stale'] = None if u['is_reference'] or since is None else since > config.STALE_LISTING_DAYS
        out.append(u)
    ref_row = next((r for r in out if r['is_reference']), None)
    for r in out:
        r['breakeven'] = breakeven(r, ref_row, vals, years * 12)
    for r in out:  # comparing partial subtotals would mislead: delta only between complete TCOs
        # switching also pays the reference's sale costs (deregistration) now, as keeping pays them at the end
        ref_tx = 0 if r['is_reference'] or not ref_row else ref_row['components']['purchase_sale'] or 0
        r['delta_vs_reference'] = (r['known_cost_subtotal'] + ref_tx - ref_row['known_cost_subtotal']
                                   if ref_row and r['tco_complete'] and ref_row['tco_complete'] else None)
    return out


def breakeven(u, ref, vals, months):
    """Cash view 'buy u' vs 'keep the reference'. Running costs are spread evenly per month (shortcut: repairs and
    tyres are period totals, not dated). Ready only when every input is known; otherwise lists what is missing."""
    def value(listing, kind):
        v = vals.get(listing['id'], {}).get(kind) if listing else None
        return v['expected_eur'] if v else None
    def need(listing, label):
        return [f'{label}: {k}' for k in config.RUNNING_COMPONENTS if listing['components'][k] is None]
    if ref is None:
        return {'ready': False, 'missing': ['reference car']}
    ref_tx = ref['components']['purchase_sale']
    missing = need(ref, 'reference') + ([] if ref_tx is not None else ['reference: purchase_sale'])
    ref_end = value(ref, 'resale_end')
    if ref_end is None:
        missing.append('reference: resale_end valuation')
    ref_monthly = sum(ref['components'][k] or 0 for k in config.RUNNING_COMPONENTS) / months
    if u['is_reference']:
        ok = not missing
        return {'ready': ok, 'missing': missing, 'monthly': round(ref_monthly, 2) if ok else None,
                'end_net': round(ref_monthly * months + ref_tx - ref_end, 2) if ok else None}
    sale_today = value(ref, 'sale_today')
    missing += need(u, 'car') + [m for m, ok in (('car: price', u['price_eur'] is not None),
                                                 ('car: purchase_sale', u['components']['purchase_sale'] is not None),
                                                 ('car: resale_end valuation', value(u, 'resale_end') is not None),
                                                 ('reference: sale_today valuation', sale_today is not None)) if not ok]
    if missing:
        return {'ready': False, 'missing': missing}
    monthly = sum(u['components'][k] for k in config.RUNNING_COMPONENTS) / months
    # the reference's transaction costs are paid now when switching, at the end when keeping it
    upfront = u['price_eur'] + u['components']['purchase_sale'] + ref_tx - sale_today
    saving = ref_monthly - monthly
    payback = 0 if upfront <= 0 else (upfront / saving if saving > 0 else None)
    switch_end = upfront + monthly * months - value(u, 'resale_end')
    keep_end = ref_monthly * months + ref_tx - ref_end
    return {'ready': True, 'missing': [], 'months': months, 'upfront': round(upfront, 2), 'monthly': round(monthly, 2),
            'ref_monthly': round(ref_monthly, 2), 'resale_end': value(u, 'resale_end'), 'ref_resale_end': ref_end,
            'ref_tx': ref_tx, 'payback_months': None if payback is None else round(payback, 1),
            'end_advantage': round(keep_end - switch_end, 2)}


def listing_detail(c, listing_id, p, ranked):
    """Everything about one listing: the ranked row plus its own rows and the resolved knowledge of its variant."""
    u = next((r for r in ranked if r['id'] == listing_id), None)
    if u is None:
        return None
    q = lambda sql: rows(c, sql, (listing_id,))
    v = {'id': u['vehicle_id'], 'engine_id': u['engine_id'], 'generation_id': u['generation_id']}
    know = Knowledge(c)
    u.update(valuations=q('SELECT * FROM valuations WHERE listing_id=? ORDER BY id'),
             unit_costs=q('SELECT * FROM unit_costs WHERE listing_id=? ORDER BY id'),
             maintenance_resets=q('SELECT * FROM maintenance_resets WHERE listing_id=? ORDER BY id'),
             inspection=q('SELECT * FROM inspection_items WHERE listing_id=? ORDER BY id'),
             events=q('SELECT * FROM listing_events WHERE listing_id=? ORDER BY event_date, id'),
             snapshots=q('SELECT * FROM listing_snapshots WHERE listing_id=? ORDER BY captured_at, id'),
             media=q('SELECT * FROM listing_media WHERE listing_id=? ORDER BY id'),
             reliability=know.of('reliability_items', v), maintenance=know.of('maintenance_items', v),
             insurance=know.of('insurance_data', v), tax=know.of('tax_data', v), observations=know.of('observations', v),
             tyres=know.of('tyre_data', v),
             engine_row=rows(c, 'SELECT * FROM engines WHERE id=?', (v['engine_id'],))[0],
             generation_row=rows(c, 'SELECT * FROM generations WHERE id=?', (v['generation_id'],))[0],
             sources=rows(c, 'SELECT * FROM sources WHERE vehicle_id=? OR engine_id=? OR generation_id=? '
                             'OR id IN (SELECT source_id FROM listing_events WHERE listing_id=?) OR id=? ORDER BY id',
                          (v['id'], v['engine_id'], v['generation_id'], listing_id, u['source_id'])))
    months = p['ownership_years'] * 12
    restarted = frozenset(r['maintenance_item_id'] for r in u['maintenance_resets'])
    u['maintenance_plan'] = maintenance_plan(u['maintenance'], u['period_km'], months, restarted)
    u['repair_risks'] = risk_plan(sorted(know.of('repair_risks', v), key=lambda r: (r['km_from'], r['id'])), u['mileage_km'], u['period_km'])
    # the dossier lists the sources these rows cite too (shared sources such as the HU fee have no vehicle)
    have = {s['id'] for s in u['sources']}
    cited = {x['source_id'] for x in u['maintenance_plan'] + u['repair_risks'] + u['tyres'] + u['insurance'] + u['tax']
             + u['observations'] if x['source_id'] and x['source_id'] not in have}
    if cited:
        u['sources'] += rows(c, f"SELECT * FROM sources WHERE id IN ({','.join('?' * len(cited))}) ORDER BY id", tuple(cited))
    return u
