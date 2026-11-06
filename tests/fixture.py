"""Synthetic test database: built from schema.sql with invented cars, so the tests never touch real data and carry no
personal data. Ids below are stable and used by the tests. The models are shared catalogue rows (owner_id NULL, issue
#109); listings, listing sources, quotes and the owner's figures belong to the admin."""
import datetime, json, sqlite3
import migrate
from carlos import auth

TODAY = datetime.date.today().isoformat()
# listings
REF, CAR_A, CAR_B = 1, 2, 3
# vehicles (variants)
V_A, V_B, V_REF, V_B2 = 1, 2, 3, 4
# engines / generations
E_A, E_B, E_REF = 1, 2, 3
G1, G2 = 1, 2
# sources
SRC_LISTING, SRC_USER, SRC_HU, SRC_TAX_OFFICIAL, SRC_QUOTE, SRC_GUIDE = 1, 2, 3, 4, 5, 6

ADMIN, PASSWORD, TOKEN = 1, 'correct horse battery', 'test-token'

ROWS = {
    'users': [dict(id=ADMIN, username='admin', role='admin', password_hash=auth.hash_password(PASSWORD), api_token_hash=auth.digest(TOKEN))],
    'project_parameters': [dict(id=1, owner_id=ADMIN, annual_km=15000, ownership_years=4, fuel_price_eur_l=1.80, fuel_price_date=TODAY,
                                diesel_price_eur_l=1.70, diesel_price_date=TODAY, budget_ideal_eur=6500, budget_max_eur=8000,
                                postal_code=None, drivers_count=1, driver_age=30, sf_class='SF 5', insurance_cover='Teilkasko',
                                insurance_deductible_eur=150, purchase_mode='cash', currency='EUR', ranking_weights=None)],
    'project_preferences': [dict(preference_key='preferred_transmission', preference_value='Manual', unit='text', status='USER_SETTING', notes='Test preference.')],
    'generations': [
        dict(id=G1, make='Alpha', model='Hatch', name='Mk1', start_year=2008, end_year=2014, facelift_year=2011, status='VERIFIED'),
        dict(id=G2, make='Beta', model='City', name='Gen2', start_year=2012, end_year=2018, facelift_year=None, status='PARTIAL'),
    ],
    'engines': [
        dict(id=E_A, code='AM14', description='1.4 petrol, naturally aspirated, port injection, timing chain', fuel_type='Petrol',
             displacement_cc=1400, cylinders=4, power_kw=74, power_ps=100, aspiration='NATURALLY ASPIRATED', injection='PORT', timing_drive='CHAIN', status='VERIFIED'),
        dict(id=E_B, code='BC12T', description='1.2 turbo petrol, direct injection, timing belt', fuel_type='Petrol',
             displacement_cc=1200, cylinders=3, power_kw=66, power_ps=90, aspiration='TURBO', injection='DIRECT', timing_drive='BELT', status='VERIFIED'),
        dict(id=E_REF, code='AM16', description='1.6 petrol, naturally aspirated', fuel_type='Petrol',
             displacement_cc=1600, cylinders=4, power_kw=85, power_ps=115, aspiration='NATURALLY ASPIRATED', injection=None, timing_drive='CHAIN', status='PARTIAL'),
    ],
    'sources': [
        dict(id=SRC_LISTING, owner_id=ADMIN, title='Test listing source', url='https://example.test/listing', source_type='listing', quality='A', accessed_date=TODAY),
        dict(id=SRC_USER, owner_id=ADMIN, title='User-provided data', source_type='user_reported', accessed_date=TODAY, supports='Facts about the own car', limitations='User statements'),
        dict(id=SRC_HU, title='HU/AU price 2026', url='https://example.test/hu', source_type='fees', quality='B', accessed_date=TODAY),
        dict(id=SRC_TAX_OFFICIAL, title='BMF Kfz-Steuer-Rechner', url='https://example.test/tax', source_type='tax_official_calculator', quality='A', accessed_date=TODAY),
        dict(id=SRC_QUOTE, owner_id=ADMIN, title='Comparison quote', url='https://example.test/quote', source_type='insurance_quote', quality='B', accessed_date=TODAY),
        dict(id=SRC_GUIDE, engine_id=E_A, title='Engine guide AM14', url='https://example.test/am14', source_type='buying_guide', quality='C', accessed_date=TODAY),
    ],
    'vehicles': [
        dict(id=V_A, generation_id=G1, engine_id=E_A, trim='Hatch 1.4 Comfort', transmission='Manual', body_style='Hatchback, 5 doors', emissions_standard='Euro 5', co2_g_km=140, hsn='1111', tsn='AAA', technical_status='VERIFIED'),
        dict(id=V_B, generation_id=G2, engine_id=E_B, trim='City 1.2 Turbo', transmission='Manual', body_style='Hatchback, 5 doors', emissions_standard='Euro 6', co2_g_km=105, hsn='2222', tsn='BBB', technical_status='VERIFIED'),
        dict(id=V_REF, generation_id=G1, engine_id=E_REF, trim='Hatch 1.6 Sport', transmission='Manual', body_style='Hatchback, 3 doors', emissions_standard='Euro 4', co2_g_km=165, hsn='1111', tsn='AAC', technical_status='PARTIAL'),
        dict(id=V_B2, generation_id=G2, engine_id=E_B, trim='City 1.2 Turbo Plus', transmission='Automatic', body_style='Hatchback, 5 doors', emissions_standard='Euro 6', co2_g_km=108, hsn=None, tsn=None, technical_status='PENDING'),
    ],
    'listings': [
        dict(id=REF, vehicle_id=V_REF, source_id=SRC_USER, platform='OWNED', mileage_km=180000, first_registration='2009-05',
             listing_status='OWNED', is_reference=1, last_checked=TODAY),
        dict(id=CAR_A, vehicle_id=V_A, source_id=SRC_LISTING, platform='Test', listing_id='A1', url='https://example.test/a1',
             price_eur=6000, mileage_km=90000, first_registration='2011-06', seller='Dealer A', location='Testville',
             listing_status='UNDER REVIEW', is_reference=0, last_checked=TODAY, accident_free_claim=1, owners_claim=2),
        dict(id=CAR_B, vehicle_id=V_B, source_id=SRC_LISTING, platform='Test', listing_id='B1', url='https://example.test/b1',
             price_eur=7500, mileage_km=60000, first_registration='2015-03', listing_status='UNDER REVIEW', is_reference=0,
             last_checked='2026-01-01', verdict='Good candidate'),
    ],
    'observations': [
        dict(vehicle_id=V_A, category='consumption', metric='Autokostencheck average', value_num=7.0, unit='l/100 km', sample_count=120, min_value=5.5, max_value=9.0, status='PRIMARY', evidence_quality='C', observed_date=TODAY, source_id=SRC_GUIDE),
        dict(engine_id=E_B, category='consumption', metric='Autokostencheck average', value_num=5.8, unit='l/100 km', sample_count=80, min_value=4.6, max_value=7.4, status='PRIMARY', evidence_quality='C', observed_date=TODAY, source_id=SRC_GUIDE),
        dict(vehicle_id=V_REF, category='consumption', metric='Autokostencheck average', value_num=8.2, unit='l/100 km', sample_count=300, min_value=6.5, max_value=10.5, status='PRIMARY', evidence_quality='C', observed_date=TODAY, source_id=SRC_GUIDE),
        dict(vehicle_id=V_REF, category='consumption', metric='Owner measured average', value_num=8.6, unit='l/100 km', status='USER DATA', observed_date=TODAY, source_id=SRC_USER, owner_id=ADMIN),
    ],
    'insurance_data': [
        dict(vehicle_id=V_A, hsn='1111', tsn='AAA', annual_premium_eur=800, premium_min_eur=700, premium_status='QUOTE', quote_date=TODAY, source_id=SRC_QUOTE, owner_id=ADMIN,
             quote_profile=json.dumps({'cover': 'Teilkasko', 'deductible_eur': 150})),
        dict(vehicle_id=V_B, hsn='2222', tsn='BBB', annual_premium_eur=700, premium_status='QUOTE', quote_date=TODAY, source_id=SRC_QUOTE, owner_id=ADMIN),
        dict(vehicle_id=V_REF, annual_premium_eur=900, premium_status='USER DATA', source_id=SRC_USER, owner_id=ADMIN),
        dict(vehicle_id=V_REF, annual_premium_eur=950, premium_status='QUOTE', quote_date=TODAY, source_id=SRC_QUOTE, owner_id=ADMIN),
    ],
    'tax_data': [
        dict(vehicle_id=V_A, annual_tax_eur=94, status='VERIFIED', basis='1400 cc, 140 g/km', source_id=SRC_TAX_OFFICIAL),
        dict(vehicle_id=V_B, annual_tax_eur=60, status='ESTIMATED', basis='1200 cc, 105 g/km', source_id=SRC_GUIDE),
        dict(vehicle_id=V_REF, annual_tax_eur=108, status='VERIFIED', basis='1600 cc, Euro 4', source_id=SRC_TAX_OFFICIAL),
    ],
    'maintenance_items': [
        dict(id=1, job='OIL_SERVICE', engine_id=E_A, item='Engine oil and filter (DIY)', interval_km=15000, interval_months=12, schedule='ITEM', diy=1, diy_parts_cost_eur=50, reference_cost_eur=120, diy_hours=1, status='VERIFIED', source_id=SRC_GUIDE),
        dict(id=2, job='SPARK_PLUGS', engine_id=E_A, item='Spark plugs (DIY)', interval_km=60000, interval_months=48, schedule='ITEM', diy=1, diy_parts_cost_eur=40, diy_hours=0.5, status='VERIFIED', source_id=SRC_GUIDE),
        dict(id=3, job='HU', generation_id=G1, item='HU/AU inspection', interval_months=24, schedule='ITEM', diy=0, reference_cost_eur=163, status='OFFICIAL FEE LEVEL', source_id=SRC_HU),
        dict(id=4, job='BRAKES_FRONT', generation_id=G1, item='Front brake pads (DIY)', interval_km=60000, schedule='ITEM', diy=1, diy_parts_cost_eur=80, diy_hours=1.5, status='ESTIMATED', source_id=SRC_GUIDE),
        dict(id=5, job='OIL_SERVICE', engine_id=E_B, item='Engine oil and filter (DIY)', interval_km=15000, interval_months=12, schedule='ITEM', diy=1, diy_parts_cost_eur=55, diy_hours=1, status='VERIFIED', source_id=SRC_GUIDE),
        dict(id=6, job='TIMING_DRIVE', engine_id=E_B, item='Timing belt with water pump (workshop)', interval_km=120000, interval_months=72, schedule='ITEM', diy=0, reference_cost_eur=600, status='VERIFIED', source_id=SRC_GUIDE),
        dict(id=7, job='HU', generation_id=G2, item='HU/AU inspection', interval_months=24, schedule='ITEM', diy=0, reference_cost_eur=163, status='OFFICIAL FEE LEVEL', source_id=SRC_HU),
        dict(id=8, job='OIL_SERVICE', engine_id=E_REF, item='Engine oil and filter (DIY)', interval_km=15000, interval_months=12, schedule='ITEM', diy=1, diy_parts_cost_eur=60, diy_hours=1, status='VERIFIED', source_id=SRC_GUIDE),
        dict(id=9, engine_id=E_A, item='Minor service', interval_km=15000, interval_months=12, schedule='PACKAGE', reference_cost_eur=130, status='ADAC REFERENCE', active=0, source_id=SRC_GUIDE),
    ],
    'repair_risks': [
        dict(id=1, engine_id=E_A, component='Water pump', km_from=100000, km_to=160000, probability=0.3, parts_eur=120, labor_eur=250, status='ESTIMATED', evidence='Typical life', source_id=SRC_GUIDE),
        dict(id=2, engine_id=E_B, component='Turbocharger', km_from=120000, km_to=200000, probability=0.2, parts_eur=900, labor_eur=400, status='ESTIMATED', evidence='Forum reports', source_id=SRC_GUIDE),
        dict(id=3, generation_id=G1, component='Rear axle bushings', km_from=80000, km_to=150000, probability=0.4, parts_eur=60, labor_eur=150, diy=1, diy_hours=2, status='ESTIMATED', evidence='Common wear item', source_id=SRC_GUIDE),
        dict(id=4, engine_id=E_REF, component='Timing chain', km_from=150000, km_to=250000, probability=0.5, parts_eur=400, labor_eur=700, status='ESTIMATED', evidence='Known weakness', source_id=SRC_GUIDE),
    ],
    'tyre_data': [
        dict(generation_id=G1, tyre_type='ALL-SEASON', size='185/65 R15', price_per_tyre_eur=70, tyres_per_set=4, life_km=45000, fitting_per_set_eur=125, status='ESTIMATED', source_id=SRC_GUIDE),
        dict(generation_id=G2, tyre_type='ALL-SEASON', size='185/60 R15', price_per_tyre_eur=75, tyres_per_set=4, life_km=45000, fitting_per_set_eur=125, status='ESTIMATED', source_id=SRC_GUIDE),
    ],
    'reliability_items': [
        dict(engine_id=E_A, component='Timing chain', part='ENGINE', issue='Rattle on cold start', evidence='Owner reports', severity='MEDIUM', frequency_status='DOCUMENTED FOR ENGINE', source_id=SRC_GUIDE, inspection_action='Cold start: listen for chain rattle for 5 s'),
        dict(generation_id=G1, component='Body', part='CHASSIS', issue='Rust at the tailgate seam', evidence='TÜV report', severity='LOW', frequency_status='DOCUMENTED FOR MODEL', source_id=SRC_GUIDE, inspection_action='Check the tailgate seam for rust'),
        dict(engine_id=E_B, component='Timing belt', part='ENGINE', issue='Belt degrades early', evidence='Recall', severity='HIGH', frequency_status='DOCUMENTED FOR ENGINE', source_id=SRC_GUIDE, inspection_action='Ask for the timing belt invoice'),
    ],
    # the contract's reliability source checks (issue #114): every part of every engine and generation, so reliability
    # is known; a test removes some to see a part become unknown
    'research_checks': [dict({col: lvl}, task=f'rel.{part}.{src}', result='NONE FOUND', contract_version=1, checked_date=TODAY,
                             source_id=SRC_HU if src in ('adac', 'tuev') else SRC_GUIDE)
                        for col, lvl, parts in [('engine_id', e, ['ENGINE']) for e in (E_A, E_B, E_REF)] +
                        [('generation_id', g, ['GEARBOX', 'CHASSIS', 'ELECTRICS']) for g in (G1, G2)]
                        for part in parts for src in ('adac', 'tuev', 'guide') + (('engine_specific',) if part == 'ENGINE' else ())] +
                       # contract 5 (#174): the gearbox-specific source, graded on the variant while it names no gearbox
                       [dict(vehicle_id=v, task='rel.GEARBOX.gearbox_specific', result='NONE FOUND', contract_version=5, checked_date=TODAY,
                             source_id=SRC_GUIDE) for v in (V_A, V_B, V_REF, V_B2)],
    'valuations': [
        dict(listing_id=REF, kind='sale_today', expected_eur=2500, status='ESTIMATED', valued_date=TODAY, source_id=SRC_GUIDE),
        dict(listing_id=REF, kind='resale_end', horizon_years=4, expected_eur=1500, status='ESTIMATED', valued_date=TODAY, source_id=SRC_GUIDE),
        dict(listing_id=CAR_A, kind='resale_end', horizon_years=4, low_eur=3500, expected_eur=4000, high_eur=4500, status='ESTIMATED', valued_date=TODAY, source_id=SRC_GUIDE),
        dict(listing_id=CAR_B, kind='resale_end', horizon_years=4, expected_eur=5500, status='ESTIMATED', valued_date=TODAY, source_id=SRC_GUIDE),
    ],
    'unit_costs': [
        dict(listing_id=REF, category='purchase_sale', item='Deregistration', parts_eur=7.5, status='ESTIMATED', source_id=SRC_HU),
        dict(listing_id=CAR_A, category='purchase_sale', item='Re-registration', parts_eur=34, status='ESTIMATED', source_id=SRC_HU),
        dict(listing_id=CAR_A, category='purchase_sale', item='Pre-purchase check', parts_eur=159, status='ESTIMATED', source_id=SRC_HU),
        dict(listing_id=CAR_A, category='repairs', item='Timing chain tensioner due', parts_eur=200, labor_eur=300, status='ESTIMATED', source_id=SRC_GUIDE),
        dict(listing_id=CAR_B, category='purchase_sale', item='Re-registration', parts_eur=34, status='ESTIMATED', source_id=SRC_HU),
    ],
    'inspection_items': [
        dict(id=1, listing_id=CAR_A, item='Cold start: listen for chain rattle for 5 s', status='PENDING'),
        dict(id=2, listing_id=CAR_A, item='Check the tailgate seam for rust', status='PENDING'),
        dict(id=3, listing_id=CAR_B, item='Ask for the timing belt invoice', status='OK', checked_date=TODAY),
    ],
    'listing_events': [
        dict(listing_id=CAR_A, event_date=TODAY, kind='found', text='Listing captured for the test fixture.', source_id=SRC_LISTING),
        dict(listing_id=REF, event_date=TODAY, kind='user_data', text='Own car registered as the reference.', source_id=SRC_USER),
    ],
    'listing_snapshots': [
        dict(listing_id=CAR_A, captured_at='2026-10-01T10:00', source_id=SRC_LISTING, title='Alpha Hatch 1.4', price_eur=6200, mileage_km=90000,
             description='Erste Hand.\nScheckheftgepflegt.', attributes_json=json.dumps({'Getriebe': 'Schaltgetriebe', 'HU': '05/2027'})),
        dict(listing_id=CAR_A, captured_at='2026-10-20T10:00', source_id=SRC_LISTING, title='Alpha Hatch 1.4', price_eur=6000, mileage_km=90000,
             description='Erste Hand.', attributes_json=json.dumps({'Getriebe': 'Schaltgetriebe'})),
    ],
}


def build(path):
    """Creates the fixture database at `path` (schema.sql baseline + the rows above)."""
    migrate.create(path)
    c = sqlite3.connect(path)
    c.execute('PRAGMA foreign_keys=ON')
    with c:
        for table, rows in ROWS.items():
            for r in rows:
                c.execute(f'INSERT INTO {table} ({",".join(r)}) VALUES ({",".join("?" * len(r))})', list(r.values()))
    assert not c.execute('PRAGMA foreign_key_check').fetchall()
    c.close()
    return path
