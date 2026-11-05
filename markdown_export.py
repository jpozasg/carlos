"""Generates one Markdown dossier per listing from SQLite. The .md files are read-only: they are overwritten."""
import json, os, re

MARKER = '<!-- GENERATED from the database: do not edit by hand -->'


def val(x, unit='', nd=2):
    if x is None:
        return 'Pending'
    if isinstance(x, (int, float)) and not isinstance(x, bool) and unit:  # with a unit: thousands separator
        x = float(x)
    if isinstance(x, float):
        x = f'{x:,.{nd}f}'.removesuffix('.00')
    return f'{x} {unit}'.strip()


def cell(x):
    return val(x).replace('|', '\\|').replace('\n', ' ') if not isinstance(x, str) else (x.replace('|', '\\|').replace('\n', ' ') or '—')


def table(rows, cols):
    """cols: [(header, key)]"""
    if not rows:
        return '_No data recorded._\n'
    out = ['| ' + ' | '.join(h for h, _ in cols) + ' |', '|' + '---|' * len(cols)]
    out += ['| ' + ' | '.join(cell(r.get(k)) for _, k in cols) + ' |' for r in rows]
    return '\n'.join(out) + '\n'


def filename(u):
    part = lambda s: re.sub(r'[^A-Za-z0-9]+', '', s or '') or 'X'
    return f"{part(u['make'])}-{part(u['model'])}-{part(u['platform'])}-{part(u['listing_id']) if u['listing_id'] else 'u' + str(u['id'])}.md"


def render(u, p):
    claims = {1: 'yes', 0: 'no', None: 'Pending'}
    lines = [MARKER, '',
             f"# {u['make']} {u['model']} {u['trim'] or ''} — {'REFERENCE (own car)' if u['is_reference'] else 'listing ' + (u['listing_id'] or str(u['id']))}",
             '', f"- **Status:** {val(u['listing_status'])}", f"- **Verdict:** {val(u['verdict'])}",
             f"- **Last checked:** {val(u['last_checked'])}", f"- **URL:** {u['url'] or '—'}", '',
             '## 1. Listing data', '',
             'Price and claims come from the listing/seller: an asking price, not a transaction; claims are not an inspection.', '',
             table([{'c': c, 'v': v} for c, v in [
                 ('Platform', u['platform']), ('Asking price', val(u['price_eur'], '€')), ('Mileage', val(u['mileage_km'], 'km')),
                 ('First registration', u['first_registration']), ('Seller', u['seller']), ('Location', u['location']),
                 ('Accident-free (claimed)', claims.get(u['accident_free_claim'])), ('Owners (claimed)', u['owners_claim']),
                 ('HU (claimed)', u['hu_claim']), ('Service history (claimed)', u['service_history_claim']),
                 ('Equipment', u['equipment']), ('Notes', u['notes'])]], [('Field', 'c'), ('Value', 'v')]),
             '## 2. Model and generation', '',
             f"- **Generation:** {val(u['generation'])}, on sale {val(u['generation_start_year'])}–{val(u['generation_end_year'])}; facelift {val(u['facelift_year'])}",
             f"- **Engine:** {val(u['engine_code'])} {u['engine_description'] or ''} · {val(u['displacement_cc'], 'cm³')} · {val(u['power_ps'], 'PS')} · {val(u['transmission'])}",
             f"- **Fuel / emissions:** {val(u['fuel_type'])} · {val(u['emissions_standard'])} · {val(u['co2_g_km'], 'g CO₂/km', 0)}",
             f"- **HSN/TSN:** {val(u['hsn'])} / {val(u['tsn'])}",
             f"- **Technical status:** {val(u['technical_status'])}", f"- **Model notes:** {val(u['vehicle_notes'])}", '',
             '## 3. Model observations (consumption, market, insurance, tax)', '',
             table(u['observations'], [('Category', 'category'), ('Metric', 'metric'), ('Value', 'value_num'), ('Text', 'value_text'), ('Unit', 'unit'),
                                       ('n', 'sample_count'), ('Min', 'min_value'), ('Max', 'max_value'), ('Status', 'status'),
                                       ('Quality', 'evidence_quality'), ('Source', 'source_id'), ('Notes', 'notes')]),
             '## 3A. Model insurance and tax', '', 'A Typklasse is not a premium.', '',
             table(u['insurance'], [('HSN', 'hsn'), ('TSN', 'tsn'), ('Year', 'year'), ('TK Haftpflicht', 'liability_typklasse'),
                                    ('TK Teilkasko', 'partial_typklasse'), ('TK Vollkasko', 'comprehensive_typklasse'),
                                    ('Annual premium €', 'annual_premium_eur'), ('Premium status', 'premium_status'),
                                    ('Source', 'source_id'), ('Notes', 'notes')]),
             table(u['tax'], [('Kfz-Steuer €/year', 'annual_tax_eur'), ('Status', 'status'), ('Basis', 'basis'),
                              ('Source', 'source_id'), ('Notes', 'notes')]),
             '## 4. Model maintenance (references)', '',
             table(u['maintenance'], [('Item', 'item'), ('Interval km', 'interval_km'), ('Months', 'interval_months'),
                                      ('Workshop ref. €', 'reference_cost_eur'), ('DIY parts €', 'diy_parts_cost_eur'),
                                      ('Status', 'status'), ('Notes', 'notes')]),
             '## 5. Model reliability', '',
             table(u['reliability'], [('Part', 'part'), ('Recall', 'is_recall'), ('Component', 'component'), ('Issue', 'issue'), ('Evidence', 'evidence'),
                                      ('Severity', 'severity'), ('Frequency', 'frequency_status'), ('Source', 'source_id'),
                                      ('Inspection action', 'inspection_action')]),
             '## 6. Inspection of this car', '',
             table(u['inspection'], [('Check', 'item'), ('Status', 'status'), ('Date', 'checked_date'), ('Notes', 'notes')]),
             '## 7. Valuations (sale/resale)', '',
             table(u['valuations'], [('Kind', 'kind'), ('Horizon (years)', 'horizon_years'), ('Low €', 'low_eur'),
                                     ('Expected €', 'expected_eur'), ('High €', 'high_eur'), ('Status', 'status'),
                                     ('Date', 'valued_date'), ('Source', 'source_id'), ('Notes', 'notes')]),
             '## 8. Car-specific costs', '',
             table(u['unit_costs'], [('Category', 'category'), ('Item', 'item'), ('Parts €', 'parts_eur'),
                                     ('Labour €', 'labor_eur'), ('DIY hours', 'diy_hours'), ('Status', 'status'),
                                     ('Source', 'source_id'), ('Notes', 'notes')]),
             f"## 9. Period costs ({p['ownership_years']} years, {val(u['period_km'], 'km')}, petrol {val(p['fuel_price_eur_l'], '€/l')})", '',
             f"**{'Complete TCO' if u['tco_complete'] else 'Partial subtotal — NOT a complete TCO'}.** "
             f"Pending: {', '.join(u['missing_components']) or 'nothing'}.", '',
             table([{'c': k, 'v': val(v, '€')} for k, v in u['components'].items()] +
                   [{'c': '**Known subtotal**', 'v': val(u['known_cost_subtotal'], '€')},
                    {'c': '€/month', 'v': val(u['known_cost_per_month'], '€')},
                    {'c': 'DIY hours (not monetised)', 'v': val(u['diy_hours'], 'h')},
                    {'c': 'Initial outlay (price − reference sale)', 'v': val(u['initial_outlay'], '€')},
                    {'c': 'Difference vs reference', 'v': val(u['delta_vs_reference'], '€')}], [('Component', 'c'), ('Amount', 'v')]),
             '## 9B. Ranking and checks', '',
             table([{'c': c, 'v': v} for c, v in [
                 ('Age', val(u['metrics']['age'], 'years', 1)), ('Km per year', val(u['metrics']['km_per_year'], 'km')),
                 ('Budget', u['budget_status'] or ('n/a (reference)' if u['is_reference'] else 'Pending')),
                 ('Not checked for over 14 days', None if u['stale'] is None else ('yes' if u['stale'] else 'no')),
                 ('Reliability (points, 3 worst per part, lower is better)', u['metrics']['reliability']),
                 ('Reliability by part', ', '.join(f"{k.lower()} {v:g}" for k, v in (u.get('reliability_parts') or {}).items()) or None),
                 ('Data confidence (%)', u['metrics']['confidence']),
                 ('Ranking score (0–100)', 'not ranked (reference)' if u['is_reference'] else u.get('score')),
                 ('Price history', ' → '.join(f"{x['date']} {val(x['price_eur'], '€')}" for x in u['price_history']) or None),
                 ('Rank', u.get('rank')), ('Data coverage', None if u.get('coverage') is None else f"{u['coverage']:.0%}"),
                 ('Criterion scores', ', '.join(f'{k} {v}' for k, v in (u.get('score_parts') or {}).items()) or None)]],
                   [('Check', 'c'), ('Value', 'v')]),
             '## 9A. Listing archive (captures)', '',
             'Copy of the listing kept even after it is no longer available. Each capture is independent; content is verbatim.', '',
             *([f"### Capture {s['captured_at']} (source {s['source_id']})\n\n"
               f"- **Title:** {val(s['title'])} · **Price:** {val(s['price_eur'], '€')} · **Km:** {val(s['mileage_km'], 'km')}\n\n"
               + (table([{'k': k, 'v': v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)}
                         for k, v in json.loads(s['attributes_json']).items()], [('Feature', 'k'), ('Value', 'v')])
                  if s['attributes_json'] else '')
               + '\n' + ('\n'.join('> ' + line for line in s['description'].splitlines()) if s['description'] else '_No description._') + '\n'
               for s in u['snapshots']] or ['_No captures._\n']),
             ' '.join(f"![photo {m['id']}](../../media/{m['file_path']})" for m in u['media']) or '_No archived photos._', '',
             '## 10. Log', '',
             table(u['events'], [('Date', 'event_date'), ('Kind', 'kind'), ('Text', 'text'), ('Source', 'source_id')]),
             '## 11. Sources', '',
             table(u['sources'], [('id', 'id'), ('Title', 'title'), ('URL', 'url'), ('Quality', 'quality'), ('Date', 'accessed_date'),
                                  ('Supports', 'supports'), ('Limitations', 'limitations')])]
    return '\n'.join(lines)


def export_all(c, out_dir, p, detail):
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for (lid,) in c.execute('SELECT id FROM listings ORDER BY id').fetchall():
        u = detail(c, lid, p)
        f = out_dir / filename(u)
        tmp = f.with_suffix('.md.tmp'); tmp.write_text(render(u, p), encoding='utf-8'); os.replace(tmp, f)  # never a half-written file
        written.append(f)
    for f in out_dir.glob('*.md'):  # delete only generated dossiers that no longer match a listing
        if f not in written and f.read_text(encoding='utf-8').startswith('<!-- GENERATED from'):
            f.unlink()
    return written
