"""Cost calculation per listing over the ownership period (README, "Calculation"). NULL means unknown, never 0."""
import datetime, re
from . import config
from . import research
from .db import for_variant, rows, scoped
from .ranking import SEVERITY_POINTS, STATUS_POINTS


def occurrences(interval_km, interval_months, km, months, restarted=False):
    """How often a job falls due in the period, whichever comes first (km or months); 0 without an interval.
    Expected value (period ÷ interval) because a used car's position in its service cycle is unknown; whole intervals
    when the job was done at the start of ownership (`restarted`: certain repair, documented or claimed by the seller)."""
    if restarted:
        return max(km // interval_km if interval_km else 0, months // interval_months if interval_months else 0)
    return max(km / interval_km if interval_km else 0, months / interval_months if interval_months else 0)


def is_new(u):
    """A new car (issue #150): never registered and only delivery kilometres."""
    return not u.get('first_registration') and u.get('mileage_km') is not None and u['mileage_km'] < config.NEW_CAR_MAX_KM


def due(i, km, months, restarted, new=False):
    """Occurrences of one job: a new car's schedule starts at 0 (whole intervals), and its first HU is at 36 months."""
    if new and i.get('job') == 'HU' and i['interval_months']:
        return 0 if months < config.NEW_CAR_FIRST_HU_MONTHS else 1 + (months - config.NEW_CAR_FIRST_HU_MONTHS) // i['interval_months']
    return occurrences(i['interval_km'], i['interval_months'], km, months, new or i['id'] in restarted)


def maintenance_plan(items, km, months, restarted=frozenset(), new=False):
    """Per-job view of the item schedule over the period (what maintenance_cost adds up): occurrences, price used,
    cost and DIY hours; cost None when a due job has no price."""
    plan = []
    for i in items:
        if not i['active'] or i['schedule'] != 'ITEM' or not (i['interval_km'] or i['interval_months']):
            continue
        n = due(i, km, months, restarted, new)
        price = i['diy_parts_cost_eur'] if i['diy'] else i['reference_cost_eur']
        plan.append({'id': i['id'], 'item': i['item'], 'level': i.get('level'), 'applies_from': i.get('applies_from'), 'applies_to': i.get('applies_to'), 'interval_km': i['interval_km'],
                     'interval_months': i['interval_months'], 'diy': i['diy'], 'price_eur': price, 'occurrences': round(n, 3),
                     'restarted': i['id'] in restarted, 'cost_eur': None if (n and price is None) else round(n * (price or 0), 2),
                     'diy_hours': round(n * i['diy_hours'], 2) if i['diy'] and i['diy_hours'] else 0,
                     'status': i['status'], 'source_id': i['source_id'], 'notes': i['notes']})
    return plan


def risk_price(r):
    """Price of one failure: DIY parts, or parts plus workshop labour; None without a price. When the account's DIY
    choice differs from how the row was priced (`diy_as_stored`), the price that choice needs (parts for DIY, labour
    for the workshop) must be there: never the other price instead (#106 part 4)."""
    if r['parts_eur'] is None and r['labor_eur'] is None:
        return None
    if r.get('diy_as_stored', r['diy']) != r['diy'] and (r['parts_eur'] if r['diy'] else r['labor_eur']) is None:
        return None
    return (r['parts_eur'] or 0) + (0 if r['diy'] else (r['labor_eur'] or 0))


def risk_plan(risks, km_now, km_period):
    """Per-risk view of the expected repairs (what expected_repairs adds up): share of the km window driven in the
    period and expected cost."""
    out = []
    km_end = (km_now or 0) + km_period
    for r in risks:
        share = 0 if km_now is None else max(0, min(r['km_to'], km_end) - max(r['km_from'], km_now)) / (r['km_to'] - r['km_from'])
        unit = risk_price(r)
        out.append({**{k: r[k] for k in ('id', 'component', 'km_from', 'km_to', 'probability', 'parts_eur', 'labor_eur', 'diy',
                                          'diy_hours', 'status', 'evidence', 'source_id', 'notes')}, 'level': r.get('level'),
                    'applies_from': r.get('applies_from'), 'applies_to': r.get('applies_to'),
                    'price_eur': unit, 'share': round(share, 3),
                    'expected_eur': None if (share and unit is None) else round(share * r['probability'] * (unit or 0), 2)})
    return out


def maintenance_cost(items, km, months, restarted=frozenset(), new=False):
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
        n = due(i, km, months, restarted, new)
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
        unit = risk_price(r)
        if unit is None:
            return None, None  # a risk without the price it needs makes the expected repairs unknown (never 0)
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


SOCKET_EXTRA_LOSS = 0.10  # ADAC: charging losses 13–24 % at a household socket vs 6–10 % at a wallbox (docs/cost-research-protocol.md)


def electricity_price(p):
    """€ per kWh an electric car pays (#121): the home and public prices weighted by the share charged at home, a household
    socket's extra loss on the home part, all of it raised by the wallbox-level charging loss (#154). Returns (price, missing parameters); a price only weighted 0 is not needed."""
    hc = p.get('home_charging')
    if hc is None:
        return None, ['home_charging']
    share = 0 if hc == 'none' else (p.get('home_charging_pct') if p.get('home_charging_pct') is not None else None)
    if share is None:
        return None, ['home_charging_pct']
    s = share / 100
    need = [k for k, w in (('electricity_home_eur_kwh', s), ('electricity_public_eur_kwh', 1 - s)) if w and p.get(k) is None]
    if need:
        return None, need
    home = s * p['electricity_home_eur_kwh'] * (1 + (SOCKET_EXTRA_LOSS if hc == 'socket' else 0)) if s else 0
    # € per kWh in the battery: the consumption source excludes charging losses (#154)
    return (home + ((1 - s) * p['electricity_public_eur_kwh'] if s < 1 else 0)) * (1 + config.EV_CHARGING_LOSS), []


def ev_tax_months(first_registration, today, months):
    """Months of the period (from today) in which an electric car pays Kfz-Steuer: first registered by 2030-12-31 it is
    exempt for 10 years, until 2035-12-31 at the latest (§ 3d KraftStG, 8. KraftStÄndG); None without a first
    registration. The exemption passes to the next owner."""
    try:
        y, m = (int(x) for x in str(first_registration)[:7].split('-'))
    except (TypeError, ValueError):
        return None
    start = today.year * 12 + today.month - 1
    if (y, m) > config.EV_TAX_EXEMPT_REGISTERED_BY:
        free_until = start  # registered later: no exemption
    else:
        ey, em = config.EV_TAX_EXEMPT_UNTIL
        free_until = min(y * 12 + m - 1 + 120, ey * 12 + em)  # first taxable month index
    return max(0, start + months - max(start, free_until))


def check_budget(p):
    """The ideal budget may not exceed the maximum."""
    if p.get('budget_ideal_eur') is not None and p.get('budget_max_eur') is not None and p['budget_ideal_eur'] > p['budget_max_eur']:
        raise ValueError('budget_ideal_eur must not be greater than budget_max_eur')


UNITS_SQL = '''SELECT l.*, v.generation_id, v.engine_id, v.gearbox_id, v.trim, v.transmission, v.body_style, v.model_year,
  v.emissions_standard, v.co2_g_km, v.hsn, v.tsn, v.technical_status, v.notes vehicle_notes,
  g.make, g.model, g.name generation, g.start_year generation_start_year, g.end_year generation_end_year, g.facelift_year,
  e.code engine_code, e.family engine_family, e.description engine_description, e.fuel_type, e.displacement_cc, e.cylinders,
  e.power_kw, e.power_ps, e.aspiration, e.injection, e.timing_drive, e.battery_usable_kwh, e.ac_charge_kw, e.dc_charge_kw,
  x.code gearbox_code, x.type gearbox_type, x.gears gearbox_gears
FROM listings l JOIN vehicles v ON v.id=l.vehicle_id JOIN generations g ON g.id=v.generation_id JOIN engines e ON e.id=v.engine_id
  LEFT JOIN gearboxes x ON x.id=v.gearbox_id
ORDER BY l.is_reference DESC, l.id'''


def diy_choice(c):
    """The job codes this account does itself (preference diy_jobs, config.DIY_JOBS); None when it never answered, so
    every row keeps its stored diy flag."""
    v = c.execute("SELECT preference_value FROM project_preferences WHERE preference_key='diy_jobs'").fetchone()
    if v is None or v[0] is None:
        return None
    return {j for name in v[0].split(',') for j in config.DIY_JOBS.get(name.strip(), ())}


def in_window(r, reg):
    """A row with a first-registration window (issue #153) applies to a car registered inside it; compared at the precision
    of the coarser side ('2015' vs '2014-08' compares years). An unknown registration keeps the row: never dropped by guess."""
    if not reg:
        return True
    lo, hi = r.get('applies_from'), r.get('applies_to')
    n = lambda w: min(len(w), len(reg))
    return (not lo or lo[:n(lo)] <= reg[:n(lo)]) and (not hi or reg[:n(hi)] <= hi[:n(hi)])


class Knowledge:
    """Every knowledge table loaded once and resolved per variant (variant + engine + generation rows)."""

    def __init__(self, c):
        self.t = {t: scoped(c, t) for t in config.SCOPED_TABLES}
        self.jobs = diy_choice(c)

    def of(self, table, v, reg=None):
        """The variant's rows; maintenance items and risks with a job code carry this account's DIY choice (#106 part 4);
        with `reg` (a listing's first registration) rows whose window excludes the car are left out (#153)."""
        rs = for_variant(self.t[table], v)
        if table in config.WINDOWED_TABLES:
            rs = [r for r in rs if in_window(r, reg)]
        if self.jobs is None or table not in ('maintenance_items', 'repair_risks'):
            return rs
        return [{**r, 'diy': int(r['job'] in self.jobs), 'diy_as_stored': r['diy']} if r.get('job') else r for r in rs]

    def consumption(self, v, fuel_type=None):
        """The primary consumption row: one real-world source per drivetrain (l/100 km, or kWh/100 km for an electric car)."""
        metric = config.PRIMARY_CONSUMPTION_EV if fuel_type == 'Electric' else config.PRIMARY_CONSUMPTION
        prim = [o for o in self.of('observations', v) if o['metric'] == metric and o['value_num'] is not None]
        return max(prim, key=lambda o: o['id']) if prim else None

    def insurance(self, v, is_reference):
        """The premium row behind the cost (and its evidence, #107): the reference car's own premium, else the newest."""
        rows_ = [r for r in self.of('insurance_data', v) if r['annual_premium_eur'] is not None]
        user = [r for r in rows_ if r['premium_status'] == config.USER_PREMIUM] if is_reference else []
        return max(user or rows_, key=lambda r: r['id'], default=None)

    def insurance_vollkasko(self, v):
        """The newest fully comprehensive quote (a lease needs one, #129): quote_profile names Vollkasko."""
        rows_ = [r for r in self.of('insurance_data', v) if r['annual_premium_eur'] is not None
                 and 'vollkasko' in (r.get('quote_profile') or '').lower()]
        return max(rows_, key=lambda r: r['id'], default=None)

    def tax(self, v, first_registration=None):
        """The tax row behind the cost: among the rows whose registration window covers the car's first registration (no
        window = any car), verified or official rows before estimates, then the newest (#107)."""
        fr = (first_registration or '')[:7]
        covers = lambda r: (r.get('registered_from') is None or fr and fr >= r['registered_from'][:7]) and \
            (r.get('registered_to') is None or fr and fr <= r['registered_to'][:7])
        rows_ = [r for r in self.of('tax_data', v) if r['annual_tax_eur'] is not None and covers(r)]
        return max(rows_, key=lambda r: (STATUS_POINTS.get(r['status'], 0) == 1, r['id']), default=None)

    def tyres(self, v):
        rows_ = self.of('tyre_data', v)
        return max(rows_, key=lambda r: r['id']) if rows_ else None  # the latest tyre row wins



def reliability(rel_rows, checks, known=frozenset(config.RELIABILITY_PARTS)):
    """Reliability of one listing (issue #54), higher is better: each part starts at config.RELIABILITY_PART_MAX and
    loses the severity points of its config.RELIABILITY_TOP worst documented weak points; the score is the sum of the
    parts (max 36). A recall drops out when its checklist item for this listing
    (`checks`: reliability_item_id → status) is OK or N/A. Returns (total, per-part points left, detail with the points each weak point costs); total None
    while any row has no part (unclassified rows are never guessed into a part). A part outside `known`
    (its required source checks are missing, issue #114) is None, and so is the total: never full points by default."""
    detail = []
    for r in sorted(rel_rows, key=lambda r: r['id']):
        check = checks.get(r['id'])
        detail.append({'id': r['id'], 'component': r['component'], 'severity': r['severity'], 'part': r.get('part'),
                       'is_recall': bool(r.get('is_recall')), 'check': check, 'level': r.get('level'), 'source_id': r['source_id'],
                       'points': SEVERITY_POINTS.get(r['severity'], 0), 'counted': False,
                       'excluded': 'recall_checked' if r.get('is_recall') and check in ('OK', 'N/A') else None})
    parts = {}
    for part in config.RELIABILITY_PARTS:
        top = sorted((d for d in detail if d['part'] == part and not d['excluded']), key=lambda d: -d['points'])[:config.RELIABILITY_TOP]
        for d in top:
            d['counted'] = True
        parts[part] = config.RELIABILITY_PART_MAX - sum(d['points'] for d in top) if part in known else None
    # with the source checks recorded, a part without weak points is clean (9), not unresearched (issue #114)
    total = None if any(d['part'] is None for d in detail) or None in parts.values() else sum(parts.values())
    return total, parts, detail


def offer_summary(parts, months):
    """Cost per month of one way to get the car (purchase or lease), for the dossier and the 'compare both' choice."""
    known = [x for x in parts.values() if x is not None]
    complete = len(known) == len(config.TCO_COMPONENTS)
    return {'cost_month': sum(known) / months if known and months else None, 'complete': complete and bool(months),
            'missing': [k for k in config.TCO_COMPONENTS if parts[k] is None], 'months': months}


def lease_costs(u, p, running, vollkasko, wallbox):
    """The eight components of a lease offer over its term (#129): running costs over the term's km, 0 for what the rate
    includes (never counted twice), insurance from a Vollkasko quote (lessors require it), lease fees + extra km (− the
    fewer-km refund when stated) in place of purchase costs, down payment + rate × term in place of depreciation.
    Residual-value leasing is not costed; return damages are not predicted. Returns (parts, detail, annual insurance)."""
    term = u['lease_term_months']
    inc = set((u.get('lease_includes') or '').split(','))
    km = p['annual_km'] * term / 12 if term else None
    run, det = running(km, term) if term else ({k: None for k in config.RUNNING_COMPONENTS}, None)
    det = det or {'taxable': None, 'maint': None, 'maint_hours': None, 'risk': None, 'risk_hours': None, 'wear': None,
                  'unpriced': [], 'km': km, 'months': p['ownership_years'] * 12}
    annual_ins = 0.0 if 'insurance' in inc else (vollkasko or {}).get('annual_premium_eur')
    allowance = u['lease_km_per_year'] * term / 12 if term and u.get('lease_km_per_year') else None
    over = None if allowance is None or km is None else km - allowance
    if over is None:
        km_cost = None
    elif over > 0:  # extra km at the stated rate; not stated = unknown
        km_cost = over * u['lease_extra_km_eur'] if u.get('lease_extra_km_eur') is not None else None
    else:  # fewer km: a refund only when the rate is stated (over ≤ 0, so this is ≤ 0)
        km_cost = over * (u.get('lease_fewer_km_eur') or 0)
    parts = {'fuel': run['fuel'],
             'insurance': None if annual_ins is None or not term else annual_ins * term / 12,
             **{k: 0.0 if k in inc else run[k] for k in ('tax', 'maintenance', 'repairs', 'tyres')},
             'purchase_sale': None if u.get('lease_fees_eur') is None or km_cost is None or wallbox is None else u['lease_fees_eur'] + km_cost + wallbox,
             'depreciation': None if u.get('lease_kind') == 'residual' or u.get('lease_down_payment_eur') is None or not term
             else u['lease_down_payment_eur'] + u['lease_monthly_eur'] * term}
    det['lease'] = {'term_months': term, 'km_allowance': allowance, 'km_over': over, 'km_cost': km_cost, 'includes': sorted(inc - {''}),
                    'vollkasko_quote_id': (vollkasko or {}).get('id'), 'insurance_included': 'insurance' in inc}
    return parts, det, annual_ins


def cash_now(u, parts):
    """Paid now: the price and purchase costs, or for a lease the down payment and fees (#129); None when unknown."""
    if u['is_reference'] or parts['purchase_sale'] is None:
        return None
    first = u['price_eur'] if u.get('offer', 'purchase') == 'purchase' else u.get('lease_down_payment_eur')
    return None if first is None else first + parts['purchase_sale']


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
    # checklist items linked to a weak point: a recall's check decides whether it counts in reliability, and recall
    # checks stay out of the inspection criterion so an open recall is not counted twice
    recall_ids = {r['id'] for r in know.t['reliability_items'] if r.get('is_recall')}
    checks, recall_checks = {}, {}
    for r in c.execute('SELECT listing_id, reliability_item_id, status FROM inspection_items WHERE reliability_item_id IS NOT NULL'):
        checks.setdefault(r['listing_id'], {})[r['reliability_item_id']] = r['status']
        if r['reliability_item_id'] in recall_ids:
            recall_checks.setdefault(r['listing_id'], {}).setdefault(r['status'], 0)
            recall_checks[r['listing_id']][r['status']] += 1
    for m in c.execute('SELECT listing_id, file_path FROM listing_media ORDER BY id'):  # the first upload is the cover
        photos.setdefault(m['listing_id'], []).append(m['file_path'])
    for r in c.execute('SELECT listing_id, captured_at, price_eur FROM listing_snapshots WHERE price_eur IS NOT NULL ORDER BY captured_at, id'):
        prices.setdefault(r['listing_id'], []).append({'date': r['captured_at'][:10], 'price_eur': r['price_eur']})
    today, limits = datetime.date.today(), budget(p)
    contract = research.Contract(c, know)
    captured = {r[0] for r in c.execute('SELECT DISTINCT listing_id FROM listing_snapshots')}
    units = rows(c, UNITS_SQL)
    ref = next((u for u in units if u['is_reference']), None)
    ref_sale = vals.get(ref['id'], {}).get('sale_today') if ref else None
    out = []
    for u in units:
        v = {'id': u['vehicle_id'], 'engine_id': u['engine_id'], 'generation_id': u['generation_id'], 'gearbox_id': u['gearbox_id']}
        # a new car is registered when bought: today stands in for its first registration (tax window, EV exemption)
        new = is_new(u)
        reg = u['first_registration'] or (today.isoformat()[:7] if new else None)
        cons, ins_row, tax_row = know.consumption(v, u['fuel_type']), know.insurance(v, u['is_reference']), know.tax(v, reg)
        electric = u['fuel_type'] == 'Electric'
        annual_tax = (tax_row or {}).get('annual_tax_eur')
        u.update(consumption=cons['value_num'] if cons else None, consumption_unit=cons['unit'] if cons else None,
                 consumption_sample=cons['sample_count'] if cons else None,
                 consumption_min=cons['min_value'] if cons else None, consumption_max=cons['max_value'] if cons else None,
                 consumption_metric=cons['metric'] if cons else None, consumption_source_id=cons['source_id'] if cons else None)
        costs = by_listing.get(u['id'], [])
        unit_cost = {cat: sum((x['parts_eur'] or 0) + (x['labor_eur'] or 0) for x in costs if x['category'] == cat)
                     if any(x['category'] == cat for x in costs) else None for cat in config.UNIT_COST_CATEGORIES}
        m_rows, r_rows, restarted = know.of('maintenance_items', v, reg), know.of('repair_risks', v, reg), frozenset(resets.get(u['id'], ()))
        # energy price: diesel, petrol (full hybrids too), electricity for an electric car; a plug-in hybrid's mix of both
        # is not supported yet, so its fuel stays unknown (owner decision 2026-11-05)
        price_l = None if u['fuel_type'] in ('Electric', 'Plug-in hybrid') else \
            p.get('diesel_price_eur_l') if (u['fuel_type'] or '').lower() == 'diesel' else p['fuel_price_eur_l']
        price_kwh = electricity_price(p)[0] if electric else None
        energy = price_kwh if electric else price_l
        # a planned wallbox is a cost of choosing an electric car (purchase side, paid now); unknown cost = unknown component
        wallbox = (p.get('wallbox_cost_eur') if p.get('home_charging') == 'wallbox_planned' else 0) if electric and not u['is_reference'] else 0
        # certain one-off costs of the listing plus the model's expected costs; the expected part unknown (no risk or
        # tyre research, an unpriced risk, no mileage) makes the whole component unknown, never a smaller number
        add = lambda certain, expected: None if expected is None else (certain or 0) + expected
        need = lambda x: f"{x.get('item') or x['component']} ({'DIY parts' if x['diy'] else 'workshop'} price)"

        def running(km_, months_):
            """The running components over km_ and months_ (the ownership period, or a lease's term)."""
            # an electric car's tax only for the months after its exemption: fully exempt = a known 0 by law, no row needed
            taxable = ev_tax_months(reg, today, months_) if electric else months_
            maint, maint_hours = maintenance_cost(m_rows, km_, months_, restarted, new)
            risk, risk_hours = expected_repairs(r_rows, u['mileage_km'], km_)
            wear = tyre_cost(know.tyres(v), km_)
            # the jobs whose price for this account's DIY choice is missing, named for the to-do
            unpriced = ([need(x) for x in maintenance_plan(m_rows, km_, months_, restarted, new) if x['cost_eur'] is None] if maint is None else []) + \
                ([need(x) for x in risk_plan(r_rows, u['mileage_km'], km_) if x['expected_eur'] is None] if risk is None and u['mileage_km'] is not None else [])
            return {'fuel': u['consumption'] * km_ / 100 * energy if u['consumption'] is not None and energy else None,
                    'tax': None if taxable is None else 0.0 if taxable == 0 else annual_tax * taxable / 12 if annual_tax is not None else None,
                    'maintenance': add(unit_cost['maintenance'], maint), 'repairs': add(unit_cost['repairs'], risk),
                    'tyres': add(unit_cost['tyres'], wear)}, \
                {'taxable': taxable, 'maint': maint, 'maint_hours': maint_hours, 'risk': risk, 'risk_hours': risk_hours,
                 'wear': wear, 'unpriced': unpriced, 'km': km_, 'months': years * 12 if months_ is None else months_}

        run, det = running(km, years * 12)
        annual_ins = (ins_row or {}).get('annual_premium_eur')
        dep, dep_pess, dep_opt = depreciation(u, vals.get(u['id'], {}))
        parts = {'fuel': run['fuel'], 'insurance': annual_ins * years if annual_ins is not None else None, 'tax': run['tax'],
                 'maintenance': run['maintenance'], 'repairs': run['repairs'], 'tyres': run['tyres'],
                 'purchase_sale': None if unit_cost['purchase_sale'] is None or wallbox is None else unit_cost['purchase_sale'] + wallbox,
                 'depreciation': dep}
        taxable = det['taxable']
        offers = {'purchase': offer_summary(parts, years * 12) if u['price_eur'] is not None or u['is_reference'] else None, 'lease': None}
        u['offer'] = 'purchase'
        if not u['is_reference'] and u.get('lease_monthly_eur') is not None:  # a lease offer (#129)
            l_parts, l_det, l_ins = lease_costs(u, p, running, know.insurance_vollkasko(v), wallbox)
            offers['lease'] = offer_summary(l_parts, u['lease_term_months'])
            mode, buy = p.get('acquisition_mode') or 'buy', offers['purchase']
            # compare both: the cheaper complete way; a lease-only ad is always costed as a lease
            if buy is None or mode == 'lease' or mode == 'both' and offers['lease']['complete'] and (
                    not buy['complete'] or offers['lease']['cost_month'] < buy['cost_month']):
                u['offer'], parts, det, annual_ins = 'lease', l_parts, l_det, l_ins
                dep_pess = dep_opt = parts['depreciation']  # the payments are fixed: no resale range
        u['offers'] = offers
        months, km_o = det['months'], det['km']
        u['unpriced'] = det['unpriced']
        u.update(tax_exempt_months=months - taxable if electric and taxable is not None and u['offer'] == 'purchase' else None,
                 annual_insurance=annual_ins, annual_tax=parts['tax'] * 12 / months if parts['tax'] is not None else annual_tax)
        known = [x for x in parts.values() if x is not None]
        subtotal = sum(known) if known else None  # unknown = NULL, never 0
        complete = len(known) == len(config.TCO_COMPONENTS)
        rest = subtotal - (parts['depreciation'] or 0) if subtotal is not None else None
        u.update(period_km=km_o, period_months=months, components=parts, inspection_counts=insp.get(u['id'], {}),
                 cover=(photos.get(u['id']) or [None])[0], photo_count=len(photos.get(u['id'], [])), known_cost_subtotal=subtotal,
                 known_cost_per_month=subtotal / months if subtotal is not None else None,
                 known_cost_per_km=subtotal / km_o if subtotal is not None and km_o else None,
                 missing_components=[k for k in config.TCO_COMPONENTS if parts[k] is None], tco_complete=complete,
                 tco_pessimistic=rest + dep_pess if complete and dep_pess is not None else None,
                 tco_optimistic=rest + dep_opt if complete and dep_opt is not None else None,
                 diy_hours=(sum(x['diy_hours'] or 0 for x in costs) + (det['maint_hours'] or 0) + (det['risk_hours'] or 0)
                            if any(x['diy_hours'] is not None for x in costs) or det['maint_hours'] or det['risk_hours'] else None),
                 cost_detail={'repairs_certain': unit_cost['repairs'], 'repairs_expected': det['risk'], 'tyre_wear': det['wear'],
                              'maintenance_certain': unit_cost['maintenance'], 'maintenance_scheduled': det['maint'],
                              'tyres_certain': unit_cost['tyres'], 'fuel_price_eur_l': price_l, 'electricity_eur_kwh': price_kwh,
                              'wallbox_eur': wallbox or None,
                              'maintenance_diy_hours': det['maint_hours'], 'repairs_diy_hours': det['risk_hours'],
                              **({'lease': det['lease']} if u['offer'] == 'lease' else {})},
                 initial_outlay=(u['price_eur'] - ref_sale['expected_eur'] if not u['is_reference'] and ref_sale
                                 and u['price_eur'] is not None and u['offer'] == 'purchase' else None))
        age = 0.0 if new else age_years(u['first_registration'], today)
        counts = u['inspection_counts']
        items = contract.resolved(v['id'])
        rel_rows = know.of('reliability_items', v, reg)
        items += research.listing_items(u, {'insurance': know.of('insurance_data', v), 'tax': {'exempt': True} if electric and taxable == 0 else tax_row, 'valuations': vals.get(u['id'], {}), 'unit_costs': costs,
                                            'weak_points': {r['id'] for r in rel_rows}, 'checked': set(checks.get(u['id'], {})),
                                            'captured': u['id'] in captured}, today)
        u['research'] = items
        evidence = {r['part'] for r in rel_rows if r.get('part')}
        rel_total, rel_parts, u['reliability_detail'] = reliability(rel_rows, checks.get(u['id'], {}), research.known_parts(items, evidence))
        u['reliability_too_new'] = research.too_new_parts(items, evidence)
        u['reliability_parts'] = rel_parts
        rc = recall_checks.get(u['id'], {})
        insp_ok, insp_problem = counts.get('OK', 0) - rc.get('OK', 0), counts.get('PROBLEM', 0) - rc.get('PROBLEM', 0)
        u['metrics'] = {
            'cost_month': u['known_cost_per_month'] if complete else None,
            'cash_now': cash_now(u, parts),
            'mileage': u['mileage_km'], 'age': age,
            'reliability': rel_total,
            'inspection': insp_problem if insp_ok or insp_problem else None,
            'power': u['power_ps'],
            'confidence': research.confidence(items),  # the contract's grades (issue #114), not the number of rows
            # informative, not ranked (they are inside cost_month)
            'price': None if u['is_reference'] else u['price_eur'],
            'km_per_year': round(u['mileage_km'] / age) if u['mileage_km'] is not None and age else None,
            'consumption': u['consumption'], 'insurance': u['annual_insurance'], 'tax': u['annual_tax']}
        # the budget is what is paid now: the price, or for a lease the down payment and fees; and the lease rate's own cap
        price = u['price_eur'] if u['offer'] == 'purchase' else u['metrics']['cash_now']
        rate_over = u['offer'] == 'lease' and p.get('lease_rate_max_eur') is not None and u['lease_monthly_eur'] > p['lease_rate_max_eur']
        u['budget_status'] = (None if u['is_reference'] or price is None and not rate_over else
                              'over_max' if rate_over or limits['max'] is not None and price > limits['max'] else
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
                                   if ref_row and r['tco_complete'] and ref_row['tco_complete']
                                   and r['period_months'] == years * 12 else None)  # a lease of another term: not comparable
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
    if u.get('offer') == 'lease':  # a lease (#129): no resale; the down payment now, the rate every month
        if u['lease_term_months'] != months:
            return {'ready': False, 'missing': ['lease term differs from the ownership period']}
        missing += need(u, 'car') + [m for m, ok in (('car: lease down payment', u['lease_down_payment_eur'] is not None),
                                                     ('car: lease fees', u['components']['purchase_sale'] is not None),
                                                     ('reference: sale_today valuation', sale_today is not None)) if not ok]
        if missing:
            return {'ready': False, 'missing': missing}
        first, extra_month, resale = u['lease_down_payment_eur'], u['lease_monthly_eur'], 0
    else:
        missing += need(u, 'car') + [m for m, ok in (('car: price', u['price_eur'] is not None),
                                                 ('car: purchase_sale', u['components']['purchase_sale'] is not None),
                                                 ('car: resale_end valuation', value(u, 'resale_end') is not None),
                                                     ('reference: sale_today valuation', sale_today is not None)) if not ok]
        if missing:
            return {'ready': False, 'missing': missing}
        first, extra_month, resale = u['price_eur'], 0, value(u, 'resale_end')
    monthly = sum(u['components'][k] for k in config.RUNNING_COMPONENTS) / months + extra_month
    # the reference's transaction costs are paid now when switching, at the end when keeping it
    upfront = first + u['components']['purchase_sale'] + ref_tx - sale_today
    saving = ref_monthly - monthly
    payback = 0 if upfront <= 0 else (upfront / saving if saving > 0 else None)
    switch_end = upfront + monthly * months - resale
    keep_end = ref_monthly * months + ref_tx - ref_end
    return {'ready': True, 'missing': [], 'months': months, 'upfront': round(upfront, 2), 'monthly': round(monthly, 2),
            'ref_monthly': round(ref_monthly, 2), 'resale_end': resale, 'ref_resale_end': ref_end,
            'ref_tx': ref_tx, 'payback_months': None if payback is None else round(payback, 1),
            'end_advantage': round(keep_end - switch_end, 2)}


def listing_detail(c, listing_id, p, ranked):
    """Everything about one listing: the ranked row plus its own rows and the resolved knowledge of its variant."""
    u = next((r for r in ranked if r['id'] == listing_id), None)
    if u is None:
        return None
    q = lambda sql: rows(c, sql, (listing_id,))
    v = {'id': u['vehicle_id'], 'engine_id': u['engine_id'], 'generation_id': u['generation_id'], 'gearbox_id': u['gearbox_id']}
    know = Knowledge(c)
    reg = u['first_registration'] or (datetime.date.today().isoformat()[:7] if is_new(u) else None)  # as in the ranking
    u.update(valuations=q('SELECT * FROM valuations WHERE listing_id=? ORDER BY id'),
             unit_costs=q('SELECT * FROM unit_costs WHERE listing_id=? ORDER BY id'),
             maintenance_resets=q('SELECT * FROM maintenance_resets WHERE listing_id=? ORDER BY id'),
             inspection=q('SELECT * FROM inspection_items WHERE listing_id=? ORDER BY id'),
             events=q('SELECT * FROM listing_events WHERE listing_id=? ORDER BY event_date, id'),
             snapshots=q('SELECT * FROM listing_snapshots WHERE listing_id=? ORDER BY captured_at, id'),
             media=q('SELECT * FROM listing_media WHERE listing_id=? ORDER BY id'),
             reliability=know.of('reliability_items', v, reg), maintenance=know.of('maintenance_items', v, reg),
             insurance=know.of('insurance_data', v), tax=know.of('tax_data', v), observations=know.of('observations', v),
             tyres=know.of('tyre_data', v),
             engine_row=rows(c, 'SELECT * FROM engines WHERE id=?', (v['engine_id'],))[0],
             generation_row=rows(c, 'SELECT * FROM generations WHERE id=?', (v['generation_id'],))[0],
             gearbox_row=(rows(c, 'SELECT * FROM gearboxes WHERE id=?', (v['gearbox_id'],)) or [None])[0],
             sources=rows(c, 'SELECT * FROM sources WHERE vehicle_id=? OR engine_id=? OR generation_id=? OR gearbox_id=? '
                             'OR id IN (SELECT source_id FROM listing_events WHERE listing_id=?) OR id=? ORDER BY id',
                          (v['id'], v['engine_id'], v['generation_id'], v['gearbox_id'], listing_id, u['source_id'])))
    u['research_levels'] = research.levels(u['research'])
    months = p['ownership_years'] * 12
    restarted = frozenset(r['maintenance_item_id'] for r in u['maintenance_resets'])
    u['maintenance_plan'] = maintenance_plan(u['maintenance'], u['period_km'], months, restarted, is_new(u))
    u['repair_risks'] = risk_plan(sorted(know.of('repair_risks', v, reg), key=lambda r: (r['km_from'], r['id'])), u['mileage_km'], u['period_km'])
    # the dossier lists the sources these rows cite too (shared sources such as the HU fee have no vehicle)
    have = {s['id'] for s in u['sources']}
    cited = {x['source_id'] for x in u['maintenance_plan'] + u['repair_risks'] + u['tyres'] + u['insurance'] + u['tax']
             + u['observations'] if x['source_id'] and x['source_id'] not in have}
    if cited:
        u['sources'] += rows(c, f"SELECT * FROM sources WHERE id IN ({','.join('?' * len(cited))}) ORDER BY id", tuple(cited))
    return u
