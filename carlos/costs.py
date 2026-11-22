"""Cost calculation per listing over the ownership period (README, "Calculation"). NULL means unknown, never 0."""
import datetime, json, re
from . import config
from . import geo, research
from .db import for_variant, rows, scoped
from .ranking import SEVERITY_POINTS, STATUS_POINTS, curve as ranking_curve


def occurrences(interval_km, interval_months, km, months, restarted=False):
    """How often a job falls due in the period, whichever comes first (km or months); 0 without an interval.
    Expected value (period ÷ interval) because a used car's position in its service cycle is unknown; whole intervals
    when the job was done at the start of ownership (`restarted`: certain repair, documented or claimed by the seller)."""
    if restarted:
        return max(km // interval_km if interval_km else 0, months // interval_months if interval_months else 0)
    return max(km / interval_km if interval_km else 0, months / interval_months if interval_months else 0)


def due(i, km, months, restarted):
    """Occurrences of one job over the period (whole intervals when the job was restarted at the start of ownership)."""
    return occurrences(i['interval_km'], i['interval_months'], km, months, i['id'] in restarted)


def maintenance_plan(items, km, months, restarted=frozenset()):
    """Per-job view of the item schedule over the period (what maintenance_cost adds up): occurrences, price used,
    cost and DIY hours; cost None when a due job has no price."""
    plan = []
    for i in items:
        if not i['active'] or i['schedule'] != 'ITEM' or not (i['interval_km'] or i['interval_months']):
            continue
        n = due(i, km, months, restarted)
        price = i['diy_parts_cost_eur'] if i['diy'] else i['reference_cost_eur']
        plan.append({'id': i['id'], 'item': i['item'], 'level': i.get('level'), 'applies_from': i.get('applies_from'), 'applies_to': i.get('applies_to'), 'interval_km': i['interval_km'],
                     'interval_months': i['interval_months'], 'diy': i['diy'], 'price_eur': price, 'occurrences': round(n, 3),
                     'restarted': i['id'] in restarted, 'cost_eur': None if (n and price is None) else round(n * (price or 0), 2),
                     'diy_hours': round(n * i['diy_hours'], 2) if i['diy'] and i['diy_hours'] else 0,
                     'status': i['status'], 'source_id': i['source_id'], 'notes': i['notes']})
    return plan


def maintenance_cost(items, km, months, restarted=frozenset()):
    """(cost, diy_hours) of scheduled maintenance over the period; (None, None) without data.
    Item schedules (schedule='ITEM') are costed one by one: DIY parts when the owner does the job (diy=1), otherwise the
    workshop reference; an item with an unknown price that falls due makes the total unknown (never 0)."""
    items_ = [i for i in items if i['active'] and i['schedule'] == 'ITEM' and (i['interval_km'] or i['interval_months'])]
    if not items_:
        return None, None
    total, hours = 0.0, 0.0
    for i in items_:
        n = due(i, km, months, restarted)
        if not n:
            continue
        price = i['diy_parts_cost_eur'] if i['diy'] else i['reference_cost_eur']
        if price is None:
            return None, None
        total += n * price
        if i['diy'] and i['diy_hours']:
            hours += n * i['diy_hours']
    return total, hours


def tyre_cost(t, km_period):
    """Wear cost of tyres over the period: km / life × (set price + fitting); None without complete tyre data."""
    if t is None or None in (t['price_per_tyre_eur'], t['life_km']):
        return None
    return km_period / t['life_km'] * (t['tyres_per_set'] * t['price_per_tyre_eur'] + (t['fitting_per_set_eur'] or 0))


def curve_at(points, x, end):
    """Cumulative share failed at x on a curve [[x, share], …] (#174): linear between the points, from (0, 0); beyond the
    last point it continues with the last segment's slope up to `end` (CURVE_END_KM / _YEARS), never above 1: no zero
    risk just because the source stopped counting (#168)."""
    prev = (0, 0.0)
    for px, ps in points:
        if x <= px:
            return prev[1] + (ps - prev[1]) * (x - prev[0]) / (px - prev[0]) if px > prev[0] else ps
        prev = (px, ps)
    a = points[-2] if len(points) > 1 else (0, 0.0)
    slope = (prev[1] - a[1]) / (prev[0] - a[0]) if prev[0] > a[0] else 0
    return min(1.0, prev[1] + slope * (min(x, end) - prev[0]))


def conditional(points, start, end, limit):
    """Chance the fault happens between start and end given it has not happened by start: (F(end) − F(start)) / (1 − F(start))."""
    fa, fb = curve_at(points, max(start, 0), limit), curve_at(points, max(end, 0), limit)
    return 0.0 if fa >= 1 else max(0.0, (fb - fa) / (1 - fa))


def shape_curves(f):
    """(km curve, age curve) of a fault (#168): its own stated points, else one of the four shapes scaled to its band's
    central share s by BAND_REFERENCE_KM / _YEARS, continuing to CURVE_END_KM / _YEARS. WEAR_KM rises with km (s·(km/ref)²),
    AGE with years, WINDOW reaches s by window_km then only a residual 10 % of s more by CURVE_END_KM, RANDOM is steady
    (1 − (1 − s)^(km/ref)). None without curve and band."""
    km = json.loads(f['curve_km']) if f.get('curve_km') else None
    age = json.loads(f['curve_age']) if f.get('curve_age') else None
    if km or age or f.get('frequency_band') not in config.FREQUENCY_BANDS or not f.get('shape'):
        return km, age
    s, R, Y, E = config.FREQUENCY_BANDS[f['frequency_band']][0], config.BAND_REFERENCE_KM, config.BAND_REFERENCE_YEARS, config.CURVE_END_KM
    cap = lambda v: round(min(0.95, v), 6)
    if f['shape'] == 'WEAR_KM':
        return [[x, cap(s * (x / R) ** 2)] for x in (50_000, 100_000, 150_000, R, E)], None
    if f['shape'] == 'AGE':
        return None, [[y, cap(s * (y / Y) ** 2)] for y in (5, 10, Y, config.CURVE_END_YEARS)]
    if f['shape'] == 'WINDOW':
        w = f.get('window_km') or 100_000
        return [[w, cap(s)], [E, cap(s * 1.1)]], None
    return [[x, cap(1 - (1 - s) ** (x / R))] for x in (100_000, R, E)], None  # RANDOM


def amount(x):
    """Parts plus labour of a cost row or a fault (its workshop price); None when it has neither figure (a pending price, never 0)."""
    return None if x['parts_eur'] is None and x['labor_eur'] is None else (x['parts_eur'] or 0) + (x['labor_eur'] or 0)


def fault_severity(f):
    """Derived, never chosen (owner, 2026-11-06, #168): HIGH when it can destroy the engine or gearbox or costs ≥ SEVERITY_HIGH_EUR, or
    strands the car / is a safety risk and costs ≥ SEVERITY_MEDIUM_EUR (cheaper: LOW-MEDIUM, #285); MEDIUM from SEVERITY_MEDIUM_EUR
    or when the car is unusable until fixed; LOW below that while the car still drives."""
    price = amount(f) or 0
    if f['consequence'] == 'ENGINE_DAMAGE' or price >= config.SEVERITY_HIGH_EUR:
        return 'HIGH'
    if f['consequence'] in ('STRANDS', 'SAFETY'):  # #285: a cheap stranding or safety fault (a coil, bulbs, tie-rod ends) must not empty a part
        return 'HIGH' if price >= config.SEVERITY_MEDIUM_EUR else 'LOW-MEDIUM'
    return 'MEDIUM' if f['consequence'] == 'UNUSABLE' or price >= config.SEVERITY_MEDIUM_EUR else 'LOW'


def fault_weight(f):
    """Share of its severity points a fault scores (#287): a fault that hits few cars is not a flaw of the model. The band's
    central share against the 'common' one, at most 1 (rare 0.125, occasional 0.42); no band = 1."""
    b = config.FREQUENCY_BANDS.get(f.get('frequency_band'))
    return 1 if not b else round(min(1, b[0] / config.FREQUENCY_BANDS['common'][0]), 3)


def fault_plan(faults, km_now, km_period, age_now, months, heavy=False, done=None, annual_km=None, by_id=None):
    """Per-fault expected repair cost over the period (#174, #168): the chance it fails during the owner's km and years
    (the larger of the km and age chances, never both) given it has not failed yet, × its price. A sourced usage
    multiplier applies when the account's usage is heavy (short trips). After a documented fix (history DONE at km) the
    car follows the fixed part's curve from there (fixed_fault_id), or none. Extended warranty cover reduces the cost of
    the share that falls while it applies. p or price None = unknown."""
    done, by_id = done or {}, by_id or {}
    out = []
    for f in faults:
        fixed, d = f['id'] in done, done.get(f['id'])  # a documented fix; its km may be unknown (None)
        g = by_id.get(f.get('fixed_fault_id')) if fixed else f  # the curve the car follows now
        k0 = None if km_now is None or fixed and d is None else km_now - (d or 0)  # a fix at an unknown km: the fixed part's km is unknown
        p = 0.0 if g is None else None
        cover = 0.0
        if g is not None:
            km_c, age_c = shape_curves(g)
            ps = []
            if km_c and k0 is not None:
                ps.append(('km', conditional(km_c, k0, k0 + km_period, config.CURVE_END_KM)))
            if age_c and age_now is not None and not fixed:
                ps.append(('age', conditional(age_c, age_now, age_now + months / 12, config.CURVE_END_YEARS)))
            if ps:
                axis, p = max(ps, key=lambda t: t[1])
                if heavy and g.get('usage_multiplier') and 'SHORT_TRIPS' in (g.get('usage_flags') or ''):
                    p = min(1.0, p * g['usage_multiplier'])
                # warranty: the share of p inside the cover (km and years from first registration, years as km at the
                # owner's annual km) is paid by the manufacturer for warranty_share of the price
                # (cover needs a stated limit; an unknown age gives no cover for the years limit, never "brand new")
                if f.get('warranty_share') and km_now is not None and axis == 'km':
                    yrs = f.get('warranty_years')
                    by_years = float('inf') if not yrs else None if age_now is None else km_now + max(0, yrs - age_now) * (annual_km or 0)
                    limit = None if by_years is None else min(f['warranty_km'] or float('inf'), by_years)
                    if limit is not None and km_now < limit < float('inf'):
                        cover = conditional(km_c, k0, min(k0 + km_period, k0 + limit - km_now), config.CURVE_END_KM) * f['warranty_share']
        price = amount(f)
        out.append({**{k: f.get(k) for k in ('id', 'component', 'part', 'issue', 'consequence', 'existence', 'probability_basis',
                                              'frequency_band', 'shape', 'inspection_action', 'applies_from', 'applies_to',
                                              'window_uncertain', 'source_id', 'notes')},
                    'level': f.get('level'), 'severity': fault_severity(f), 'price_eur': price, 'repaired_at_km': d, 'fixed': fixed,
                    'probability': None if p is None else round(p, 4), 'warranty_cover': round(cover, 4),
                    'expected_eur': None if p is None or (p and price is None) else round(max(0.0, p - cover) * (price or 0), 2)})
    return out


def market_value(m, age, km):
    """Value of the model at an age and mileage from its market model (#166): the value at the reference point, less the
    share lost per year and per 10,000 km."""
    return m['value_ref_eur'] * (1 - m['rate_year']) ** (age - m['ref_age_years']) * (1 - m['rate_10k_km']) ** ((km - m['ref_km']) / 10000)


def market_model(models, u, today):
    """The usable market model of a listing's model: same generation and engine, same gearbox when the model names one,
    at least MARKET_MIN_PER_BAND cars in each of the three bands, sampled within MARKET_MAX_AGE_DAYS; None otherwise."""
    for m in sorted(models, key=lambda m: -m['id']):
        if m['generation_id'] == u['generation_id'] and m['engine_id'] == u['engine_id'] and m['gearbox_id'] in (None, u.get('gearbox_id')):
            counts = json.loads(m['band_counts'])
            age = days_since(m['sample_date'], today)
            if len(counts) == 3 and min(counts) >= config.MARKET_MIN_PER_BAND and age is not None and age <= config.MARKET_MAX_AGE_DAYS:
                return m
    return None


def resale_at(end, years, electric=False):
    """A stored resale_end is the value at its own `horizon_years`. For another ownership period it moves along the rule of
    thumb's yearly loss (config.RESALE_YEARLY_LOSS; the one-off private-sale discount inside the stored value stays), so a
    longer horizon is not flattered (#388). An electric car's expected value follows the low case, as the rule stores it.
    No horizon stored: taken as given."""
    h = end.get('horizon_years')
    if not h or h == years:
        return end
    loss = config.RESALE_YEARLY_LOSS
    rate = {'expected': loss['low' if electric else 'expected'], 'low': loss['low'], 'high': loss['high']}
    return {**end, **{f'{k}_eur': None if end[f'{k}_eur'] is None else round(end[f'{k}_eur'] * (1 - r) ** (years - h), 2) for k, r in rate.items()},
            'horizon_years': years, 'rescaled_from_years': h}


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


UNITS_SQL = '''SELECT l.*, v.generation_id, v.engine_id, v.gearbox_id, v.body_style_id, e.family_id engine_family_id,
  gb.family_id gearbox_family_id, gb.code gearbox_code, gb.type gearbox_type, v.trim, v.transmission, v.body_style, v.model_year,
  v.emissions_standard, v.co2_g_km, v.hsn, v.tsn, v.technical_status, v.notes vehicle_notes,
  g.make, g.model, g.name generation, g.start_year generation_start_year, g.end_year generation_end_year, g.facelift_year,
  g.ncap_stars, g.ncap_year, v.esp,
  e.code engine_code, e.family engine_family, e.description engine_description, e.fuel_type, e.displacement_cc, e.cylinders,
  e.power_kw, e.power_ps, e.aspiration, e.injection, e.timing_drive, e.battery_usable_kwh, e.ac_charge_kw, e.dc_charge_kw
FROM listings l LEFT JOIN vehicles v ON v.id=l.vehicle_id LEFT JOIN generations g ON g.id=v.generation_id
LEFT JOIN engines e ON e.id=v.engine_id
LEFT JOIN gearboxes gb ON gb.id=v.gearbox_id
ORDER BY l.is_reference DESC, l.id'''


def levels_of(u, options=frozenset()):
    """The level ids a listing's knowledge resolves through (db.applies): variant, engine and its family, gearbox and
    its family, generation, body style, and the options present on the listing (#174)."""
    return {'id': u['vehicle_id'], 'engine_id': u['engine_id'], 'generation_id': u['generation_id'], 'gearbox_id': u.get('gearbox_id'),
            'engine_family_id': u.get('engine_family_id'), 'gearbox_family_id': u.get('gearbox_family_id'),
            'body_style_id': u.get('body_style_id'), 'option_ids': frozenset(options)}


def listing_facts(c):
    """Per listing: its history records, options present and insurance quotes (#174)."""
    hist, opts, quotes = {}, {}, {}
    for h in rows(c, 'SELECT * FROM listing_history ORDER BY id'):
        hist.setdefault(h['listing_id'], []).append(h)
    for lid, oid in c.execute('SELECT listing_id, option_id FROM listing_options'):
        opts.setdefault(lid, set()).add(oid)
    for q in rows(c, 'SELECT * FROM listing_quotes ORDER BY id'):
        quotes.setdefault(q['listing_id'], []).append(q)
    return hist, opts, quotes


def history_effects(h, m_rows):
    """What a listing's history changes (#174): scheduled jobs DONE restart (by item or job code), faults DONE restart their
    km curve at that mileage (None when the history does not say where), PRESENT items are certain costs by category (None
    when one has no figure yet), recalls get their per-car status."""
    done_jobs = {x['job'] for x in h if x['status'] == 'DONE' and x['job']}
    restarted = {x['maintenance_item_id'] for x in h if x['status'] == 'DONE' and x['maintenance_item_id']} | \
        {m['id'] for m in m_rows if m.get('job') in done_jobs}
    faults_done = {x['fault_id']: x['km'] for x in h if x['status'] == 'DONE' and x['fault_id']}
    present = {}
    for x in h:
        if x['status'] == 'PRESENT':
            a, cat = amount(x), x['category']
            present[cat] = None if a is None or cat in present and present[cat] is None else present.get(cat, 0) + a
    recalls = {x['recall_id']: x['status'] for x in h if x['recall_id']}
    return restarted, faults_done, present, recalls


def quote_for(qs, is_reference):
    """The listing's insurance quote behind the cost: the reference car's own premium (USER DATA), else the newest by quote date
    (a later entry of an older quote never replaces a fresher one), then by id. An expired quote is still used (owner decides)."""
    user = [q for q in qs if q['premium_status'] == config.USER_PREMIUM] if is_reference else []
    return max(user or qs, key=lambda q: (q.get('quote_date') or '', q['id']), default=None)


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


def most_specific(rows_):
    """The newest row of the most specific level: the exact variant's figure before the engine's, that before any wider level
    (AGENTS.md: the HSN/TSN variant is primary), so a later generation row from a re-run never replaces it."""
    return min(rows_, key=lambda r: ({'variant': 0, 'engine': 1}.get(r['level'], 2), -r['id']), default=None)


class Knowledge:
    """Every knowledge table loaded once and resolved per variant (variant + engine + generation rows)."""

    def __init__(self, c):
        self.t = {t: scoped(c, t) for t in config.SCOPED_TABLES}
        self.jobs = diy_choice(c)
        self.faults_by_id = {f['id']: f for f in self.t['faults']}  # a fix's curve (fixed_fault_id) may sit on another level
        mix = c.execute("SELECT preference_value FROM project_preferences WHERE preference_key='driving_mix'").fetchone()
        self.heavy = bool(mix) and mix[0] in config.HEAVY_USE_MIX  # short trips: heavy-use intervals and sourced multipliers

    def of(self, table, v, reg=None):
        """The variant's rows; maintenance items with a job code carry this account's DIY choice (#106 part 4);
        with `reg` (a listing's first registration) rows whose window excludes the car are left out (#153)."""
        rs = for_variant(self.t[table], v)
        if table in config.WINDOWED_TABLES:
            rs = [r for r in rs if in_window(r, reg)]
        if table == 'maintenance_items':
            # a global default (no level) is overridden by a level row with the same job (#174); heavy use takes the
            # manufacturer's heavy-use interval where one is given
            jobs = {r['job'] for r in rs if r['level'] != 'shared' and r.get('job')}
            rs = [r for r in rs if not (r['level'] == 'shared' and r.get('job') in jobs)]
            if self.heavy:
                rs = [{**r, 'interval_km': r.get('interval_km_heavy') or r['interval_km'],
                       'interval_months': r.get('interval_months_heavy') or r['interval_months']} for r in rs]
        if self.jobs is None or table != 'maintenance_items':
            return rs
        return [{**r, 'diy': int(r['job'] in self.jobs), 'diy_as_stored': r['diy']} if r.get('job') else r for r in rs]

    def consumption(self, v, fuel_type=None):
        """The primary consumption row: one real-world source per drivetrain (l/100 km, or kWh/100 km for an electric car)."""
        metric = config.PRIMARY_CONSUMPTION_EV if fuel_type == 'Electric' else config.PRIMARY_CONSUMPTION
        prim = [o for o in self.of('observations', v) if o['metric'] == metric and o['value_num'] is not None]
        return most_specific(prim)

    def insurance(self, v, is_reference):
        """The premium row behind the cost (and its evidence, #107): the reference car's own premium, else the newest."""
        rows_ = [r for r in self.of('insurance_data', v) if r['annual_premium_eur'] is not None]
        user = [r for r in rows_ if r['premium_status'] == config.USER_PREMIUM] if is_reference else []
        return max(user or rows_, key=lambda r: r['id'], default=None)

    def tax(self, v, first_registration=None):
        """The tax row behind the cost: among the rows whose registration window covers the car's first registration (no
        window = any car), verified or official rows before estimates, then the newest (#107)."""
        fr = (first_registration or '')[:7]
        covers = lambda r: (r.get('registered_from') is None or fr and fr >= r['registered_from'][:7]) and \
            (r.get('registered_to') is None or fr and fr <= r['registered_to'][:7])
        rows_ = [r for r in self.of('tax_data', v) if r['annual_tax_eur'] is not None and covers(r)]
        return max(rows_, key=lambda r: (STATUS_POINTS.get(r['status'], 0) == 1, r['id']), default=None)

    def tyres(self, v):
        return most_specific(self.of('tyre_data', v))



SOURCE_NAMES = {'AUTOSCORE': 'Autoscore', 'ENGINESCOPE': 'EngineScope', 'TUEV_REPORT': 'TÜV-Report', 'ADAC_PANNENSTATISTIK': 'ADAC Pannenstatistik'}


def reliability_sources(keys, ratings, age, reg_year, perm=None):
    """Reliability from the fixed external sources (#351, #356), 0-100, higher is better. Slots: ENGINE (Autoscore, with
    EngineScope averaged in once config.ENGINESCOPE_PERMISSION allows its score), HU (TÜV defect share against the class
    average), BREAKDOWNS (ADAC band). Score = mean of the slots present; a missing source is coverage, never 0; fewer than
    config.RELIABILITY_MIN_SLOTS slots = None. Nothing here enters a TCO component. `keys`/`ratings`: live source_keys and
    source_ratings rows of the car's engine and generation. Returns {score, coverage, slots, explain}."""
    perm = config.ENGINESCOPE_PERMISSION if perm is None else perm
    slots = {s: [] for s in config.RATING_SLOTS}
    for src, rule in config.RATING_SOURCES.items():
        if not rule['slot'] or src == 'ENGINESCOPE' and perm == 'NONE':
            continue
        key = min((k for k in keys if k['source_key'] == src), key=lambda k: k['id'], default=None)
        if key is None:
            continue
        rs = [r for r in ratings if r['source_key'] == src and r['external_key'].upper() == key['external_key'].upper() and r['value_num'] is not None]
        if src == 'TUEV_REPORT':  # the age class holding the car; older than the oldest class: the nearest (oldest) one; under 2: none
            oldest = max((r['age_to'] for r in rs), default=0)
            rs = [r for r in rs if age is not None and age >= 2 and r['age_from'] <= age and (int(age) <= r['age_to'] or r['age_to'] == oldest)]
        elif src == 'ADAC_PANNENSTATISTIK':
            rs = [r for r in rs if reg_year and r['reg_year'] == reg_year]
        r = max(rs, key=lambda r: (r['edition'], r['id']), default=None)
        if r is None:
            continue
        if src == 'TUEV_REPORT':
            p = ranking_curve([(0.5, 100), (1, 50), (2, 0)], r['value_num'] / r['class_average'])
        elif src == 'ADAC_PANNENSTATISTIK':
            p = {1: 100, 2: 75, 3: 50, 4: 25, 5: 0}[r['band']]
        elif src == 'AUTOSCORE':
            p = 100 - 10 * r['value_num']  # Autoscore: higher risk is worse
        else:
            p = r['value_num']
        slots[rule['slot']].append({'source_key': src, 'source': SOURCE_NAMES[src], 'value': r['value_num'], 'value_text': r['value_text'],
                                    'band': r['band'], 'class_average': r['class_average'], 'reg_year': r['reg_year'], 'edition': r['edition'],
                                    'age_class': [r['age_from'], r['age_to']] if src == 'TUEV_REPORT' else None,
                                    'nearest_class': src == 'TUEV_REPORT' and int(age) > r['age_to'],
                                    'points': round(p, 1), 'url': r['url'] or key['url']})
    slot_out = {s: {'points': round(sum(x['points'] for x in v) / len(v), 1), 'sources': v} if v else None for s, v in slots.items()}
    present = [x['points'] for x in slot_out.values() if x]
    return {'score': round(sum(present) / len(present), 1) if len(present) >= config.RELIABILITY_MIN_SLOTS else None,
            'coverage': len(present) / len(slot_out), 'present': len(present), 'of': len(slot_out), 'slots': slot_out,
            'missing': [s for s, x in slot_out.items() if not x]}


def source_rows(c, engine_id, generation_id):
    """Live source_keys of an engine and generation, with the source_ratings that belong to them (#358), for the UI."""
    keys = rows(c, 'SELECT * FROM source_keys WHERE archived=0 AND (engine_id=? OR generation_id=?) ORDER BY id', (engine_id, generation_id))
    have = {(k['source_key'], k['external_key'].upper()) for k in keys}
    rats = [r for r in rows(c, 'SELECT * FROM source_ratings WHERE archived=0 ORDER BY id') if (r['source_key'], r['external_key'].upper()) in have]
    return keys, rats


def safety_stars(u):
    """Euro NCAP stars adjusted for the test regime (#169): a rating from before the stricter 2009 overall rating counts
    one star less; a car without ESP loses another; None when the generation's rating is unknown."""
    s = u.get('ncap_stars')
    if s is None:
        return None
    s -= 1 if (u.get('ncap_year') or 2009) < config.NCAP_REGIME_YEAR else 0
    return max(0, s - (1 if u.get('esp') == 0 else 0))


def cash_now(u, parts):
    """Paid now: the price and purchase costs; None when unknown."""
    if u['is_reference'] or parts['purchase_sale'] is None or u['price_eur'] is None:
        return None
    return u['price_eur'] + parts['purchase_sale']


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
    check_texts = {}  # listing -> check texts on its list (a fault with the same action text is covered by it, #223)
    for r in c.execute('SELECT listing_id, reliability_item_id, fault_id, recall_id, item, status FROM inspection_items'):
        check_texts.setdefault(r['listing_id'], set()).add(r['item'].strip())
        key = r['reliability_item_id'] or (f"F{r['fault_id']}" if r['fault_id'] else f"R{r['recall_id']}" if r['recall_id'] else None)
        if key is None:
            continue
        checks.setdefault(r['listing_id'], {})[key] = r['status']
        if r['recall_id'] or r['reliability_item_id'] in recall_ids:
            recall_checks.setdefault(r['listing_id'], {}).setdefault(r['status'], 0)
            recall_checks[r['listing_id']][r['status']] += 1
    for m in c.execute('SELECT listing_id, file_path FROM listing_media ORDER BY id'):  # the first upload is the cover
        photos.setdefault(m['listing_id'], []).append(m['file_path'])
    for r in c.execute('SELECT listing_id, captured_at, price_eur FROM listing_snapshots WHERE price_eur IS NOT NULL ORDER BY captured_at, id'):
        prices.setdefault(r['listing_id'], []).append({'date': r['captured_at'][:10], 'price_eur': r['price_eur']})
    today, limits = datetime.date.today(), budget(p)
    history, opts, quotes = listing_facts(c)
    markets = rows(c, 'SELECT * FROM market_models')
    contract = research.Contract(c, know)
    src_keys, src_ratings = rows(c, 'SELECT * FROM source_keys'), rows(c, 'SELECT * FROM source_ratings')
    captured = {r[0] for r in c.execute('SELECT DISTINCT listing_id FROM listing_snapshots')}
    units = rows(c, UNITS_SQL)
    ref = next((u for u in units if u['is_reference']), None)
    ref_sale = vals.get(ref['id'], {}).get('sale_today') if ref else None
    out = []
    for u in units:
        v = levels_of(u, opts.get(u['id'], ()))
        reg = u['first_registration']
        # build-date windows (#174): the build date when the listing shows it, else the registration, flagged
        win = u.get('build_date') or reg
        u['build_date_unknown'] = not u.get('build_date')
        quote = quote_for(quotes.get(u['id'], []), u['is_reference'])
        cons, ins_row, tax_row = know.consumption(v, u['fuel_type']), quote or know.insurance(v, u['is_reference']), know.tax(v, reg)
        electric = u['fuel_type'] == 'Electric'
        annual_tax = (tax_row or {}).get('annual_tax_eur')
        u.update(consumption=cons['value_num'] if cons else None, consumption_unit=cons['unit'] if cons else None,
                 consumption_sample=cons['sample_count'] if cons else None,
                 consumption_min=cons['min_value'] if cons else None, consumption_max=cons['max_value'] if cons else None,
                 consumption_metric=cons['metric'] if cons else None, consumption_source_id=cons['source_id'] if cons else None)
        costs = by_listing.get(u['id'], [])
        unit_cost = {cat: sum(amount(x) or 0 for x in costs if x['category'] == cat)
                     if any(x['category'] == cat for x in costs) else None for cat in config.UNIT_COST_CATEGORIES}
        no_figure = {x['category'] for x in costs if amount(x) is None}  # a certain cost still without a price: its component is unknown
        m_rows = know.of('maintenance_items', v, win)
        f_rows, rc_rows = know.of('faults', v, win), know.of('recalls', v, win)
        h_restart, faults_done, present, recall_status = history_effects(history.get(u["id"], []), m_rows)
        restarted = frozenset(resets.get(u['id'], ())) | h_restart
        for cat, eur in present.items():  # a PRESENT history item is a certain cost (#174)
            if eur is None:
                no_figure.add(cat)
            else:
                unit_cost[cat] = (unit_cost[cat] or 0) + eur
        certain_eur = lambda cat: None if cat in no_figure else unit_cost[cat]
        age_now = age_years(u['first_registration'], today)
        # energy price: diesel, petrol (full hybrids too), electricity for an electric car; a plug-in hybrid's mix of both
        # is not supported yet, so its fuel stays unknown (owner decision 2026-11-05)
        price_l = None if u['fuel_type'] in ('Electric', 'Plug-in hybrid') else \
            p.get('diesel_price_eur_l') if (u['fuel_type'] or '').lower() == 'diesel' else p['fuel_price_eur_l']
        price_kwh = electricity_price(p)[0] if electric else None
        energy = price_kwh if electric else price_l
        # a planned wallbox is a cost of choosing an electric car (purchase side, paid now); unknown cost = unknown component
        wallbox = (p.get('wallbox_cost_eur') if p.get('home_charging') == 'wallbox_planned' else 0) if electric and not u['is_reference'] else 0
        # certain one-off costs of the listing plus the model's expected costs; the expected part unknown (no fault or
        # tyre research, an unpriced fault, no mileage) makes the whole component unknown, never a smaller number
        add = lambda cat, expected: None if expected is None or cat in no_figure else (unit_cost[cat] or 0) + expected
        need = lambda x: f"{x.get('item') or x['component']} ({'DIY parts' if x['diy'] else 'workshop'} price)"

        def running(km_, months_):
            """The running components over km_ and months_ (the ownership period)."""
            # an electric car's tax only for the months after its exemption: fully exempt = a known 0 by law, no row needed
            taxable = ev_tax_months(reg, today, months_) if electric else months_
            maint, maint_hours = maintenance_cost(m_rows, km_, months_, restarted)
            fp = fault_plan(f_rows, u['mileage_km'], km_, age_now, months_, know.heavy, faults_done, p['annual_km'], know.faults_by_id)
            # faults (#174): any unknown chance or price makes the repairs unknown; no fault research = unknown
            risk = None if not f_rows or any(x['expected_eur'] is None for x in fp) else sum(x['expected_eur'] for x in fp)
            wear = tyre_cost(know.tyres(v), km_)
            if wear is not None and unit_cost['tyres']:  # a set bought now is the first of the expected wear, never on top of it (#388)
                wear = max(0.0, wear - unit_cost['tyres'])
            # the jobs whose price for this account's DIY choice is missing, named for the to-do
            unpriced = ([need(x) for x in maintenance_plan(m_rows, km_, months_, restarted) if x['cost_eur'] is None] if maint is None else []) + \
                ([f"{x['component']} (fault: chance or price)" for x in fp if x['expected_eur'] is None] if risk is None else [])
            return {'fuel': u['consumption'] * km_ / 100 * energy if u['consumption'] is not None and energy is not None else None,
                    'tax': None if taxable is None else 0.0 if taxable == 0 else annual_tax * taxable / 12 if annual_tax is not None else None,
                    'maintenance': add('maintenance', maint), 'repairs': add('repairs', risk), 'tyres': add('tyres', wear)}, \
                {'taxable': taxable, 'maint': maint, 'maint_hours': maint_hours, 'risk': risk,
                 'wear': wear, 'unpriced': unpriced, 'km': km_, 'months': years * 12 if months_ is None else months_, 'faults': fp}

        run, det = running(km, years * 12)
        u['fault_plan'], u['restarted_items'] = det['faults'], sorted(restarted)
        if 'resale_end' in vals.get(u['id'], {}):  # the stored end value belongs to its own horizon (#388)
            vals[u['id']]['resale_end'] = resale_at(vals[u['id']]['resale_end'], years, electric)
        # resale from the model's market sample (#166): end value at the owner's end age and km, less the private-sale
        # discount; it replaces the listing's own valuation when the sample is usable
        mm = market_model(markets, u, today) if age_now is not None and u['mileage_km'] is not None else None
        u['market_model_id'] = mm['id'] if mm else None
        if mm:
            sale = lambda a, k: round(market_value(mm, a, k) * (1 - config.PRIVATE_SALE_DISCOUNT), -1)
            lv = vals.setdefault(u['id'], {})
            lv['resale_end'] = {'expected_eur': sale(age_now + years, u['mileage_km'] + km), 'low_eur': None, 'high_eur': None,
                                'source': 'market', 'market_model_id': mm['id']}
            if u['is_reference'] and 'sale_today' not in lv:
                lv['sale_today'] = {'expected_eur': sale(age_now, u['mileage_km']), 'low_eur': None, 'high_eur': None, 'source': 'market'}
        annual_ins = (ins_row or {}).get('annual_premium_eur')
        dep, dep_pess, dep_opt = depreciation(u, vals.get(u['id'], {}))
        parts = {'fuel': run['fuel'], 'insurance': annual_ins * years if annual_ins is not None else None, 'tax': run['tax'],
                 'maintenance': run['maintenance'], 'repairs': run['repairs'], 'tyres': run['tyres'],
                 'purchase_sale': None if unit_cost['purchase_sale'] is None or 'purchase_sale' in no_figure or wallbox is None
                 else unit_cost['purchase_sale'] + wallbox,
                 'depreciation': dep}
        taxable = det['taxable']
        months, km_o = det['months'], det['km']
        u['unpriced'] = det['unpriced']
        u.update(tax_exempt_months=months - taxable if electric and taxable is not None else None,
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
                 diy_hours=(sum(x['diy_hours'] or 0 for x in costs) + (det['maint_hours'] or 0)
                            if any(x['diy_hours'] is not None for x in costs) or det['maint_hours'] else None),
                 cost_detail={'repairs_certain': certain_eur('repairs'), 'repairs_expected': det['risk'], 'tyre_wear': det['wear'],
                              'maintenance_certain': certain_eur('maintenance'), 'maintenance_scheduled': det['maint'],
                              'tyres_certain': certain_eur('tyres'), 'fuel_price_eur_l': price_l, 'electricity_eur_kwh': price_kwh,
                              'resale_rescaled_from_years': (vals.get(u['id'], {}).get('resale_end') or {}).get('rescaled_from_years'),
                              'wallbox_eur': wallbox or None,
                              'maintenance_diy_hours': det['maint_hours']},
                 initial_outlay=(u['price_eur'] - ref_sale['expected_eur'] if not u['is_reference'] and ref_sale
                                 and u['price_eur'] is not None else None))
        age = age_now
        counts = u['inspection_counts']
        items = contract.resolved(v['id'])
        rel_rows = know.of('reliability_items', v, win)
        rel_checks = dict(checks.get(u['id'], {}))
        rel_rows = rel_rows + [{'id': f"F{f['id']}", 'component': f['component'], 'severity': fault_severity(f), 'part': f['part'], 'weight': fault_weight(f),
                                'is_recall': False, 'inspection_action': (f.get('inspection_action') or '').strip(), 'level': f['level'], 'source_id': f['source_id']} for f in f_rows] + \
            [{'id': f"R{r['id']}", 'component': r['code'] + ': ' + r['defect'], 'severity': 'HIGH IF APPLICABLE',
              'part': r['part'], 'is_recall': True, 'level': r['level'], 'source_id': r['source_id']} for r in rc_rows]
        for rid, st in recall_status.items():  # done or not affected (VIN check): the recall stops counting
            if st in ('DONE', 'NOT AFFECTED'):
                rel_checks[f'R{rid}'] = 'OK'
        items += research.listing_items(u, {'insurance': know.of('insurance_data', v) + quotes.get(u['id'], []), 'tax': {'exempt': True} if electric and taxable == 0 else tax_row, 'valuations': vals.get(u['id'], {}), 'unit_costs': costs,
                                            # a recall always needs its check; any other weak point only when it has an action (#223)
                                            'weak_points': {r['id'] for r in rel_rows if r.get('is_recall') or (r.get('inspection_action') or '').strip()} | {'VIN'},
                                            'checked': set(rel_checks) | ({'VIN'} if config.VIN_RECALL_CHECK in check_texts.get(u['id'], ()) else set()) | {r['id'] for r in rel_rows if not r.get('is_recall') and
                                                         (r.get('inspection_action') or '').strip() in check_texts.get(u['id'], ())},
                                            'captured': u['id'] in captured}, today)
        u['research'] = items
        reg_year = int(u['first_registration'][:4]) if u['first_registration'] else None
        u['reliability_sources'] = rel = reliability_sources(
            [k for k in src_keys if k['engine_id'] == u['engine_id'] or k['generation_id'] == u['generation_id']], src_ratings,
            age if u['first_registration'] else None, reg_year)
        rc = recall_checks.get(u['id'], {})
        insp_ok, insp_problem = counts.get('OK', 0) - rc.get('OK', 0), counts.get('PROBLEM', 0) - rc.get('PROBLEM', 0)
        u['metrics'] = {
            'cost_month': u['known_cost_per_month'] if complete else None,
            'cash_now': cash_now(u, parts),
            'mileage': u['mileage_km'], 'age': age,
            'reliability': rel['score'],
            'inspection': insp_problem if insp_ok or insp_problem else None,
            'power': u['power_ps'],
            # ranking inputs (#169): the purchase price for the budget curve,
            # Euro NCAP adjusted for the test regime, the distance to view (per account, on the listing)
            'budget': None if u['is_reference'] else u['price_eur'],
            'safety': safety_stars(u),
            'distance': 0 if u['is_reference'] else u.get('distance_km') if u.get('distance_km') is not None else geo.km(p.get('postal_code'), u.get('postal_code')),
            'confidence': research.confidence(items),  # the contract's grades (issue #114), not the number of rows
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
                                   if ref_row and r['tco_complete'] and ref_row['tco_complete']
                                   else None)
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
    first, resale = u['price_eur'], value(u, 'resale_end')
    monthly = sum(u['components'][k] for k in config.RUNNING_COMPONENTS) / months
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
    v = levels_of(u, [r['option_id'] for r in q('SELECT option_id FROM listing_options WHERE listing_id=?')])
    know = Knowledge(c)
    reg = u.get('build_date') or u['first_registration']  # as in the ranking
    u.update(valuations=q('SELECT * FROM valuations WHERE listing_id=? ORDER BY id'),
             unit_costs=q('SELECT * FROM unit_costs WHERE listing_id=? ORDER BY id'),
             maintenance_resets=q('SELECT * FROM maintenance_resets WHERE listing_id=? ORDER BY id'),
             history=q('SELECT * FROM listing_history WHERE listing_id=? ORDER BY id'),
             quotes=q('SELECT * FROM listing_quotes WHERE listing_id=? ORDER BY id'), quote_max_age_days=config.QUOTE_MAX_AGE_DAYS,
             recalls=know.of('recalls', v, reg), review_flags=know.of('review_flags', v),
             inspection=q('SELECT * FROM inspection_items WHERE listing_id=? ORDER BY id'),
             events=q('SELECT * FROM listing_events WHERE listing_id=? ORDER BY event_date, id'),
             snapshots=q('SELECT * FROM listing_snapshots WHERE listing_id=? ORDER BY captured_at, id'),
             media=q('SELECT * FROM listing_media WHERE listing_id=? ORDER BY id'),
             reliability=know.of('reliability_items', v, reg), maintenance=know.of('maintenance_items', v, reg),
             insurance=know.of('insurance_data', v), tax=know.of('tax_data', v), observations=know.of('observations', v),
             tyres=know.of('tyre_data', v),
             # a listing awaiting research has no variant, engine or generation yet (#194)
             engine_row=next(iter(rows(c, 'SELECT * FROM engines WHERE id=?', (v['engine_id'],))), None),
             generation_row=next(iter(rows(c, 'SELECT * FROM generations WHERE id=?', (v['generation_id'],))), None),
             sources=rows(c, 'SELECT * FROM sources WHERE vehicle_id=? OR engine_id=? OR generation_id=? '
                             'OR id IN (SELECT source_id FROM listing_events WHERE listing_id=?) OR id=? ORDER BY id',
                          (v['id'], v['engine_id'], v['generation_id'], listing_id, u['source_id'])))
    u['research_levels'] = research.levels(u['research'])
    u['rating_keys'], u['ratings'] = source_rows(c, v['engine_id'], v['generation_id'])
    from .models import with_reviews
    u['review_flags'] = with_reviews(c, u['review_flags'])  # problems flagged on any of its levels (#168)
    months = p['ownership_years'] * 12
    restarted = frozenset(u.get('restarted_items') or ())
    u['maintenance_plan'] = maintenance_plan(u['maintenance'], u['period_km'], months, restarted)
    # the dossier lists the sources these rows cite too (shared sources such as the HU fee have no vehicle)
    have = {s['id'] for s in u['sources']}
    cited = {x['source_id'] for x in u['maintenance_plan'] + u['tyres'] + u['insurance'] + u['tax']
             + u.get('fault_plan', []) + u['recalls'] + u['quotes'] + u['valuations'] + u['unit_costs']
             + u['observations'] if x['source_id'] and x['source_id'] not in have}
    if cited:
        u['sources'] += rows(c, f"SELECT * FROM sources WHERE id IN ({','.join('?' * len(cited))}) ORDER BY id", tuple(cited))
    return u
