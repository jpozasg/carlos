"""API, calculation and migration tests on a synthetic database (tests/fixture.py), never on real data.
Run: python -m unittest -v"""
import datetime, json, os, shutil, sqlite3, tempfile, threading, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
import migrate
from carlos import auth, config, server, costs, ranking
from tests import fixture as fx
from tests.fixture import REF, CAR_A, CAR_B, V_A, V_B, V_REF, V_B2, E_A, E_B, G1, G2, SRC_GUIDE, SRC_LISTING, SRC_QUOTE, SRC_TAX_OFFICIAL

TOKEN, PASSWORD = fx.TOKEN, fx.PASSWORD
REAL_DB = config.ROOT / 'data' / 'cars.sqlite'


class AppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.Handler.log_message = lambda *a: None
        cls.srv = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f'http://127.0.0.1:{cls.srv.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def setUp(self):  # fresh database per test: the server reads config.DB on every request
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        config.DATA_DIR, config.DB, config.MD_DIR, config.MEDIA_DIR = d, d / 'cars.sqlite', d / 'dossiers', d / 'media'
        fx.build(config.DB)
        auth.FAILS.clear()
        from carlos import agent as agent_mod; agent_mod._STORAGE.update(at=0.0, value=None)

    def tearDown(self):
        self.tmp.cleanup()

    def req(self, method, path, body=None, token=TOKEN, ctype='application/json', cookie=None, raw=None, headers=None):
        """Requests carry the admin's agent token unless told otherwise (token=None: anonymous; cookie: a session)."""
        headers = {'Content-Type': ctype, **(headers or {})}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        if cookie:
            headers['Cookie'] = f'{auth.COOKIE}={cookie}'
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        r = urllib.request.Request(self.base + path, data, headers, method=method)
        try:
            resp = urllib.request.urlopen(r); return resp.status, json.load(resp)
        except urllib.error.HTTPError as e:
            body = e.read()
            return e.code, json.loads(body) if body.startswith(b'{') else body

    def agent(self, method, path, body=None, token=TOKEN, headers=None, cookie=None):
        return self.req(method, '/api/agent/' + path, body, token, headers=headers, cookie=cookie)

    def ui(self, method, path, body=None, token=TOKEN, raw=None, ctype='application/json'):
        return self.req(method, '/api/ui/' + path, body, token, ctype, raw=raw)

    def login(self, username='admin', password=PASSWORD):
        r = urllib.request.Request(self.base + '/api/auth/login', json.dumps({'username': username, 'password': password}).encode(),
                                   {'Content-Type': 'application/json'}, method='POST')
        try:
            resp = urllib.request.urlopen(r)
        except urllib.error.HTTPError as e:
            return e.code, None
        cookie = resp.headers.get('Set-Cookie', '')
        return resp.status, cookie.split(';')[0].split('=', 1)[1]

    def upload(self, body, lid=CAR_A, q='', ctype='image/jpeg'):
        r = urllib.request.Request(f'{self.base}/api/agent/media/{lid}{q}', body,
                                   {'Content-Type': ctype, 'Authorization': f'Bearer {TOKEN}'}, method='POST')
        try:
            resp = urllib.request.urlopen(r); return resp.status, json.load(resp)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def units(self):
        return {u['id']: u for u in self.req('GET', '/api/tco')[1]['listings']}

    def sql(self, q, args=()):
        c = sqlite3.connect(config.DB)
        try:
            return c.execute(q, args).fetchall()
        finally:
            c.close()

    # --- database, schema, migrations ---
    def test_fixture_is_at_the_latest_schema_version(self):
        self.assertEqual(self.sql('PRAGMA user_version')[0][0], migrate.latest_version())
        self.assertEqual(migrate.run(config.DB), [])  # nothing pending on a fresh database
        self.assertEqual(self.sql('PRAGMA integrity_check')[0][0], 'ok')

    def test_schema_sql_matches_a_migrated_database(self):
        """schema.sql must be regenerated (python migrate.py --schema) after every migration."""
        reference = (config.ROOT / 'schema.sql').read_text(encoding='utf-8')
        out = Path(self.tmp.name) / 'schema_check.sql'
        migrate.dump_schema(config.DB, out)
        self.assertEqual(out.read_text(encoding='utf-8'), reference)

    @unittest.skipUnless(REAL_DB.exists(), 'no real database in data/')
    def test_real_database_migrates_cleanly(self):
        db = Path(self.tmp.name) / 'real.sqlite'
        shutil.copy(REAL_DB, db)
        migrate.run(db)
        c = sqlite3.connect(db)
        self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(), [])
        # at most one reference car per account (every account owns its data)
        self.assertEqual(c.execute('SELECT max(n) FROM (SELECT count(*) n FROM listings WHERE is_reference=1 GROUP BY owner_id)').fetchone()[0], 1)
        c.close()

    def test_failed_migration_rolls_back(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); (d / 'migrations').mkdir(); db = d / 'c.sqlite'
            fx.build(db)
            sqlite3.connect(db).execute('PRAGMA user_version=0').connection.commit()
            (d / 'migrations' / '001_bad.sql').write_text(
                "INSERT INTO sources(title) VALUES ('tmp-rollback');\n"
                "INSERT INTO tax_data(vehicle_id, annual_tax_eur) VALUES (999, 1);")  # violates the foreign key
            root, migrate.ROOT = migrate.ROOT, d
            try:
                with self.assertRaises(sqlite3.Error):
                    migrate.run(db)
            finally:
                migrate.ROOT = root
            c = sqlite3.connect(db)
            self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT count(*) FROM sources WHERE title='tmp-rollback'").fetchone()[0], 0)
            c.close()

    def test_backup_rotation(self):
        for _ in range(migrate.KEEP_BACKUPS + 2):
            migrate.backup(config.DB)
        self.assertEqual(len(list((config.DB.parent / 'backups').glob('cars_*.sqlite'))), migrate.KEEP_BACKUPS)

    # --- three levels: variant, engine, generation ---
    def test_knowledge_resolves_over_variant_engine_and_generation(self):
        d = self.req('GET', f'/api/listings/{CAR_B}')[1]
        self.assertEqual({(m['item'], m['level']) for m in d['maintenance']},
                         {('Engine oil and filter (DIY)', 'engine'), ('Timing belt with water pump (workshop)', 'engine'),
                          ('HU/AU inspection', 'generation')})
        self.assertEqual([r['component'] for r in d['repair_risks']], ['Turbocharger'])
        self.assertEqual(d['consumption'], 5.8)                               # engine-level consumption
        self.assertEqual(d['tyres'][0]['level'], 'generation')
        self.assertEqual((d['engine_row']['code'], d['generation_row']['name'], d['generation']), ('BC12T', 'Gen2', 'Gen2'))
        # the sibling variant on the same engine and generation inherits the same rows
        v = self.req('GET', f'/api/vehicles/{V_B2}')[1]
        self.assertEqual(len(v['maintenance_items']), 3)
        self.assertEqual(v['siblings'], {'same_engine': [V_B], 'same_generation': [V_B]})
        a = self.req('GET', f'/api/listings/{CAR_A}')[1]
        self.assertEqual({m['level'] for m in a['maintenance']}, {'engine', 'generation'})
        self.assertEqual({r['component'] for r in a['repair_risks']}, {'Water pump', 'Rear axle bushings'})
        self.assertIn(SRC_GUIDE, {s['id'] for s in a['sources']})           # engine-level source listed

    def test_scoped_rows_need_exactly_one_level(self):
        base = {'item': 'x', 'interval_km': 10000, 'schedule': 'ITEM', 'diy': 0, 'reference_cost_eur': 10, 'status': 'ESTIMATED', 'source_id': SRC_GUIDE}
        self.assertEqual(self.agent('POST', 'maintenance_items', base)[0], 400)                                  # no level
        self.assertEqual(self.agent('POST', 'maintenance_items', {**base, 'vehicle_id': V_A, 'engine_id': E_A})[0], 400)  # two levels
        st, r = self.agent('POST', 'maintenance_items', {**base, 'engine_id': E_A})
        self.assertEqual(st, 201)
        # re-scoping a row from the variant to its engine in one PATCH
        st, _ = self.agent('PATCH', f'maintenance_items/{r["id"]}', {'engine_id': None, 'vehicle_id': V_A})
        self.assertEqual(st, 200)
        self.assertEqual(self.agent('PATCH', f'maintenance_items/{r["id"]}', {'vehicle_id': None})[0], 400)       # CHECK: zero levels
        self.assertEqual(self.agent('POST', 'sources', {'title': 's', 'vehicle_id': V_A, 'generation_id': G1})[0], 400)
        self.assertEqual(self.agent('POST', 'sources', {'title': 's', 'generation_id': G1})[0], 201)
        self.assertEqual(self.agent('POST', 'engines', {'code': 'X', 'aspiration': 'JET'})[0], 400)              # fixed code
        self.assertEqual(self.agent('POST', 'engines', {'code': 'X', 'aspiration': 'TURBO', 'timing_drive': 'WET BELT'})[0], 201)
        self.assertEqual(self.agent('POST', 'vehicles', {'generation_id': 999, 'engine_id': E_A})[0], 400)          # FK

    def test_models_tree_and_variant_detail(self):
        t = self.req('GET', '/api/models')[1]
        self.assertEqual([m['make'] for m in t['makes']], ['Alpha', 'Beta'])
        beta = t['makes'][1]['models'][0]
        gen = beta['generations'][0]
        self.assertEqual((gen['name'], [e['code'] for e in gen['engines']]), ('Gen2', ['BC12T']))
        variants = gen['engines'][0]['variants']
        self.assertEqual([v['id'] for v in variants], [V_B, V_B2])
        self.assertEqual([l['id'] for l in variants[0]['listings']], [CAR_B])
        self.assertEqual(variants[0]['knowledge']['maintenance_items'], 3)
        alpha_gen = t['makes'][0]['models'][0]['generations'][0]
        self.assertEqual(sorted(e['code'] for e in alpha_gen['engines']), ['AM14', 'AM16'])
        v = self.req('GET', f'/api/vehicles/{V_REF}')[1]
        self.assertEqual((v['make'], v['engine_row']['code'], v['listings'][0]['is_reference']), ('Alpha', 'AM16', 1))
        self.assertEqual(self.req('GET', '/api/vehicles/999')[0], 404)
        self.assertEqual(len(self.req('GET', '/api/generations')[1]), 2)
        self.assertEqual(len(self.req('GET', '/api/engines')[1]), 3)

    # --- calculation ---
    def test_maintenance_schedule(self):
        small = {'interval_km': 15000, 'interval_months': 12, 'reference_cost_eur': 130}
        big = {'interval_km': 30000, 'interval_months': 24, 'reference_cost_eur': 270}
        wear = {'interval_km': None, 'interval_months': None, 'reference_cost_eur': 850}
        m = costs.scheduled_maintenance
        self.assertEqual(m([small, big, wear], 60000, 48), 800)
        self.assertEqual(m([small, big], 90000, 72), 1200)
        self.assertEqual(m([small, big], 20000, 48), 800)    # few km: the interval in months governs
        self.assertIsNone(m([wear], 60000, 48))

    def test_components_from_the_fixture(self):
        us = self.units()
        a, b, ref = us[CAR_A], us[CAR_B], us[REF]
        p = self.req('GET', '/api/parameters')[1]
        km = p['annual_km'] * p['ownership_years']
        self.assertAlmostEqual(a['components']['fuel'], 7.0 * km / 100 * p['fuel_price_eur_l'])
        self.assertEqual(a['components']['insurance'], 800 * 4)
        self.assertEqual(a['components']['tax'], 94 * 4)
        # maintenance (60,000 km, 48 months): oil 4×50, plugs 1×40, HU 2×163, pads 1×80 = 646
        self.assertAlmostEqual(a['components']['maintenance'], 646)
        self.assertAlmostEqual(a['diy_hours'], 4 * 1 + 0.5 + 1.5 + 0.4 * (60000 / 70000) * 2, places=2)
        # repairs: certain 500 + water pump 0.3 × 370 × (50000/60000 of its window) + bushings 0.4 × 60 (DIY parts) × 60000/70000
        self.assertAlmostEqual(a['components']['repairs'], 500 + 0.3 * 370 * 50000 / 60000 + 0.4 * 60 * 60000 / 70000, places=2)
        self.assertAlmostEqual(a['components']['tyres'], km / 45000 * (4 * 70 + 125))
        self.assertEqual(a['components']['purchase_sale'], 34 + 159)
        self.assertEqual(a['components']['depreciation'], 6000 - 4000)
        self.assertEqual((a['tco_pessimistic'] - a['known_cost_subtotal'], a['known_cost_subtotal'] - a['tco_optimistic']), (500, 500))
        self.assertTrue(a['tco_complete'] and b['tco_complete'] and ref['tco_complete'])
        self.assertEqual(ref['components']['insurance'], 900 * 4)              # USER DATA beats the quote for the reference
        self.assertEqual(ref['components']['depreciation'], 2500 - 1500)       # sale today − resale
        self.assertEqual(ref['consumption'], 8.2)                              # the same source for every car
        self.assertEqual(b['components']['repairs'], 0)                        # turbo window not reached: 0, not unknown
        self.assertAlmostEqual(a['delta_vs_reference'], a['known_cost_subtotal'] + (ref['components']['purchase_sale'] or 0) - ref['known_cost_subtotal'])
        self.assertEqual(a['initial_outlay'], 6000 - 2500)
        self.assertEqual(a['metrics']['reliability'], 33.5)                    # 36 − MEDIUM engine item 2 − LOW generation item 0.5
        self.assertEqual(b['metrics']['reliability'], 33)                      # 36 − HIGH engine item
        self.assertEqual(a['reliability_parts'], {'ENGINE': 7, 'GEARBOX': 9, 'CHASSIS': 8.5, 'ELECTRICS': 9})   # points left of 9
        self.assertNotIn('simplicity', a['metrics'])                           # removed from the ranking (issue #54)
        self.assertEqual(a['metrics']['cash_now'], 6000 + 34 + 159)
        self.assertIsNone(ref['metrics']['cash_now'])
        self.assertTrue(0 < a['metrics']['confidence'] <= 100)
        self.assertEqual({i['id']: i['grade'] for i in a['research']}['eng.risks'], 'ACCEPTED')   # estimated risks, C source
        self.assertEqual(b['metrics']['inspection'], 0)
        self.assertIsNone(a['metrics']['inspection'])                 # nothing checked yet

    def test_unknown_price_makes_the_component_unknown(self):
        self.agent('POST', 'repair_risks', {'vehicle_id': V_A, 'component': 'Mystery', 'km_from': 0, 'km_to': 300000,
                                            'probability': 0.5, 'status': 'ESTIMATED', 'source_id': SRC_GUIDE})
        self.assertEqual(self.agent('POST', 'repair_risks', {'vehicle_id': V_A, 'component': 'X', 'km_from': 0, 'km_to': 300000,
                                                             'probability': 0.5, 'source_id': SRC_GUIDE, 'parts_eur': 1})[0], 201)
        a = self.units()[CAR_A]
        self.assertIsNone(a['components']['repairs'])                      # certain 500 € does not hide the unknown part
        self.assertIn('repairs', a['missing_components'])
        self.assertFalse(a['tco_complete'])
        self.assertIsNone(a['delta_vs_reference'])                            # partial subtotals are not compared
        self.agent('PATCH', 'maintenance_items/1', {'diy_parts_cost_eur': None})
        self.assertIsNone(self.units()[CAR_A]['components']['maintenance'])

    def test_maintenance_resets(self):
        d = self.req('GET', f'/api/listings/{CAR_B}')[1]
        belt = next(m for m in d['maintenance'] if m['item'].startswith('Timing belt'))
        before = d['components']['maintenance']
        st, r = self.agent('POST', 'maintenance_resets', {'listing_id': CAR_B, 'maintenance_item_id': belt['id'], 'basis': 'SELLER CLAIM',
                                                          'source_id': SRC_LISTING, 'notes': 'Seller says the belt is new.'})
        self.assertEqual(st, 201)
        self.assertEqual(self.agent('POST', 'maintenance_resets', {'listing_id': CAR_B, 'maintenance_item_id': belt['id'], 'basis': 'DOCUMENTED', 'source_id': SRC_LISTING})[0], 400)  # unique
        self.assertEqual(self.agent('POST', 'maintenance_resets', {'listing_id': CAR_B, 'maintenance_item_id': belt['id'], 'basis': 'GUESS', 'source_id': SRC_LISTING})[0], 400)
        d = self.req('GET', f'/api/listings/{CAR_B}')[1]
        plan = next(x for x in d['maintenance_plan'] if x['id'] == belt['id'])
        self.assertTrue(plan['restarted'])
        self.assertEqual(plan['occurrences'], 0)                              # 60,000 km / 48 months < one whole interval
        self.assertAlmostEqual(d['components']['maintenance'], before - 48 / 72 * 600)   # months governed: 0.667 occurrences
        self.assertAlmostEqual(sum(x['cost_eur'] for x in d['maintenance_plan']), d['components']['maintenance'])
        self.assertAlmostEqual(sum(x['expected_eur'] for x in d['repair_risks']) + 0, d['cost_detail']['repairs_expected'])

    def test_certain_maintenance(self):
        """A scheduled job due at purchase is a certain maintenance cost: it adds to maintenance, never to repairs."""
        before = self.req('GET', f'/api/listings/{CAR_B}')[1]
        st, _ = self.agent('POST', 'unit_costs', {'listing_id': CAR_B, 'category': 'maintenance', 'item': 'Timing belt kit (due by age)',
                                                  'parts_eur': 200, 'labor_eur': 400, 'status': 'ESTIMATED', 'source_id': SRC_GUIDE})
        self.assertEqual(st, 201)
        d = self.req('GET', f'/api/listings/{CAR_B}')[1]
        self.assertAlmostEqual(d['components']['maintenance'], before['components']['maintenance'] + 600)
        self.assertEqual(d['components']['repairs'], before['components']['repairs'])
        self.assertEqual(d['cost_detail']['maintenance_certain'], 600)

    def test_diesel_price(self):
        st, e = self.agent('POST', 'engines', {'code': 'D15', 'fuel_type': 'Diesel', 'displacement_cc': 1500, 'power_ps': 105})
        st, v = self.agent('POST', 'vehicles', {'generation_id': G2, 'engine_id': e['id'], 'trim': 'City 1.5 D'})
        self.agent('POST', 'observations', {'vehicle_id': v['id'], 'category': 'consumption', 'metric': config.PRIMARY_CONSUMPTION,
                                            'value_num': 5.0, 'status': 'PRIMARY', 'source_id': SRC_GUIDE})
        st, l = self.agent('POST', 'listings', {'vehicle_id': v['id'], 'source_id': SRC_LISTING, 'listing_id': 'D1', 'price_eur': 5000, 'mileage_km': 50000})
        p = self.req('GET', '/api/parameters')[1]
        u = self.units()[l['id']]
        self.assertAlmostEqual(u['components']['fuel'], 5.0 * p['annual_km'] * p['ownership_years'] / 100 * p['diesel_price_eur_l'])
        self.assertEqual(u['cost_detail']['fuel_price_eur_l'], p['diesel_price_eur_l'])
        self.req('POST', '/api/parameters', {'diesel_price_eur_l': None})
        self.assertIsNone(self.units()[l['id']]['components']['fuel'])
        todo = {x['listing_id']: x['todo'] for x in self.agent('GET', 'todo')[1]['listings']}[l['id']]
        self.assertIn('diesel price missing (Settings: diesel_price_eur_l)', todo)

    def ev_listing(self, fuel='Electric', **listing):
        st, e = self.agent('POST', 'engines', {'code': 'EM1', 'fuel_type': fuel, 'power_ps': 136, 'battery_usable_kwh': 52})
        self.assertEqual(st, 201, e)
        st, v = self.agent('POST', 'vehicles', {'generation_id': G2, 'engine_id': e['id'], 'trim': 'City EV'})
        st, l = self.agent('POST', 'listings', {'vehicle_id': v['id'], 'source_id': SRC_LISTING, 'listing_id': 'EV1', 'price_eur': 12990,
                                                'mileage_km': 45000, 'first_registration': '2020-11', **listing})
        return e, v, l

    def test_electric_data_121(self):
        post = lambda b: self.req('POST', '/api/parameters', b)[0]
        self.assertEqual(post({'home_charging': 'garage'}), 400)
        self.assertEqual(post({'home_charging_pct': 120}), 400)
        self.assertEqual(post({'electricity_home_date': 'today'}), 400)
        self.assertEqual(self.agent('POST', 'engines', {'code': 'X', 'fuel_type': 'electric'})[0], 400)  # controlled code
        e, v, l = self.ev_listing()
        todo = lambda: {x['listing_id']: x['todo'] for x in self.agent('GET', 'todo')[1]['listings']}[l['id']]
        self.assertIn('charging answers missing for the energy cost (setup Charging step / Settings): home_charging', todo())
        self.assertTrue(any(x.startswith('battery state of health unknown') for x in todo()))
        self.assertEqual(post({'home_charging': 'wallbox', 'home_charging_pct': 80}), 200)
        self.assertIn('charging answers missing for the energy cost (setup Charging step / Settings): electricity_home_eur_kwh, '
                      'electricity_public_eur_kwh', todo())
        self.assertEqual(post({'electricity_home_eur_kwh': 0.37, 'electricity_public_eur_kwh': 0.52}), 200)
        self.assertEqual(self.agent('PATCH', f"listings/{l['id']}", {'battery_soh_claim': 94})[0], 200)
        self.assertFalse(any('charging answers' in x or 'battery state' in x for x in todo()))
        from carlos.costs import electricity_price
        self.assertEqual(electricity_price({'home_charging': 'none', 'electricity_public_eur_kwh': 0.5}), (0.5, []))
        self.assertAlmostEqual(electricity_price({'home_charging': 'socket', 'home_charging_pct': 100, 'electricity_home_eur_kwh': 0.4})[0], 0.44)
        self.assertAlmostEqual(electricity_price({'home_charging': 'wallbox', 'home_charging_pct': 50, 'electricity_home_eur_kwh': 0.4,
                                                  'electricity_public_eur_kwh': 0.6})[0], 0.5)

    def test_electric_costs_121(self):
        import datetime
        from carlos.costs import ev_tax_months
        self.req('POST', '/api/parameters', {'ownership_years': 4, 'annual_km': 10000, 'home_charging': 'wallbox_planned', 'home_charging_pct': 100,
                                             'electricity_home_eur_kwh': 0.40, 'wallbox_cost_eur': 1500})
        e, v, l = self.ev_listing()
        self.agent('POST', 'observations', {'vehicle_id': v['id'], 'category': 'consumption', 'metric': config.PRIMARY_CONSUMPTION_EV,
                                            'value_num': 16.0, 'unit': 'kWh/100 km', 'status': 'PRIMARY', 'source_id': SRC_GUIDE})
        self.agent('POST', 'unit_costs', {'listing_id': l['id'], 'category': 'purchase_sale', 'item': 'registration', 'parts_eur': 0,
                                          'labor_eur': 100, 'status': 'ESTIMATED', 'source_id': SRC_GUIDE})
        u = self.units()[l['id']]
        self.assertAlmostEqual(u['components']['fuel'], 16.0 * 40000 / 100 * 0.40)
        self.assertEqual(u['consumption_unit'], 'kWh/100 km')
        self.assertEqual(u['components']['tax'], 0)               # first registered 2020-11: exempt for the whole period, no row
        self.assertEqual(u['components']['purchase_sale'], 1600)  # registration + the planned wallbox
        self.assertEqual(u['metrics']['cash_now'], 12990 + 1600)
        self.req('POST', '/api/parameters', {'wallbox_cost_eur': None})
        self.assertIsNone(self.units()[l['id']]['components']['purchase_sale'])  # a needed cost unknown, never 0
        self.agent('PATCH', f"listings/{l['id']}", {'first_registration': '2018-05'})
        self.assertIsNone(self.units()[l['id']]['components']['tax'])  # taxable from 2028-05 and no tax row yet
        self.agent('POST', 'tax_data', {'vehicle_id': v['id'], 'annual_tax_eur': 48, 'status': 'VERIFIED', 'source_id': SRC_GUIDE})
        taxable = ev_tax_months('2018-05', datetime.date.today(), 48)
        self.assertAlmostEqual(self.units()[l['id']]['components']['tax'], 48 * taxable / 12)
        # the exemption: 10 years, never past 2035-12; later registrations not at all
        self.assertEqual(ev_tax_months('2030-06', datetime.date(2033, 1, 1), 60), 24)
        self.assertEqual(ev_tax_months('2031-01', datetime.date(2031, 1, 1), 12), 12)
        self.assertEqual(ev_tax_months('2020-11', datetime.date(2026, 11, 5), 48), 0)
        self.assertIsNone(ev_tax_months(None, datetime.date(2026, 11, 5), 48))
        e2, v2, l2 = self.ev_listing('Plug-in hybrid', listing_id='PH1')
        self.assertIsNone(self.units()[l2['id']]['components']['fuel'])  # plug-in hybrids: not supported yet

    def test_lease_data_127(self):
        post = lambda b: self.req('POST', '/api/parameters', b)[0]
        self.assertEqual(post({'acquisition_mode': 'rent'}), 400)
        self.assertEqual(post({'acquisition_mode': 'both', 'lease_rate_max_eur': 300}), 200)
        e, v, l = self.ev_listing('Petrol', listing_id='LS1', price_eur=None, lease_monthly_eur=224, lease_term_months=48)
        self.assertEqual(self.agent('PATCH', f"listings/{l['id']}", {'lease_kind': 'rent'})[0], 400)          # controlled code
        self.assertEqual(self.agent('PATCH', f"listings/{l['id']}", {'lease_includes': 'insurance, tax'})[0], 400)  # no spaces
        self.assertEqual(self.agent('PATCH', f"listings/{l['id']}", {'lease_includes': 'insurance,tax,gap'})[0], 200)
        todo = {x['listing_id']: x['todo'] for x in self.agent('GET', 'todo')[1]['listings']}[l['id']]
        self.assertIn('lease field not stated: lease_fees_eur (ask the dealer; null is never 0)', todo)
        self.assertIn('lease kind not recorded: km, residual or abo', todo)
        self.assertNotIn('listing field missing: price_eur', todo)  # a lease-only ad has no purchase price
        import capture_listing
        cap = {'url': 'https://x', 'platform': 'p', 'captured_at': '2026-11-05', 'vehicle_id': v['id']}
        for bad in ({'lease_monthly_eur': 0}, {'lease_term_months': 47.5}, {'lease_kind': 'rent'}, {'lease_includes': 'fuel'}):
            with self.assertRaises(ValueError):
                capture_listing.validate({**cap, 'listing': bad})
        capture_listing.validate({**cap, 'listing': {'lease_kind': 'abo', 'lease_monthly_eur': 299, 'lease_down_payment_eur': 0,
                                                     'lease_includes': 'insurance,tax,maintenance'}})

    def test_lease_costs_129(self):
        from carlos.costs import lease_costs
        running = lambda km, months: ({'fuel': 100.0, 'tax': 50.0, 'maintenance': 200.0, 'repairs': 300.0, 'tyres': 80.0},
                                      {'taxable': months, 'maint': None, 'maint_hours': None, 'risk': None, 'risk_hours': None,
                                       'wear': None, 'unpriced': [], 'km': km, 'months': months})
        u = {'lease_term_months': 48, 'lease_includes': 'insurance,tax', 'lease_km_per_year': 8000, 'lease_extra_km_eur': 0.1,
             'lease_fewer_km_eur': None, 'lease_fees_eur': 1000, 'lease_kind': 'km', 'lease_down_payment_eur': 0, 'lease_monthly_eur': 224}
        p = {'annual_km': 10000, 'ownership_years': 4}
        parts, det, ins = lease_costs(u, p, running, None, 0)
        self.assertEqual((parts['insurance'], parts['tax'], parts['maintenance']), (0, 0, 200))  # inside the rate: 0, never twice
        self.assertAlmostEqual(parts['purchase_sale'], 1000 + 8000 * 0.1)                      # fees + 8,000 extra km
        self.assertEqual(parts['depreciation'], 224 * 48)                                      # down payment + rate × term
        u2 = {**u, 'lease_includes': None}
        self.assertIsNone(lease_costs(u2, p, running, None, 0)[0]['insurance'])               # needs a Vollkasko quote
        self.assertEqual(lease_costs(u2, p, running, {'id': 1, 'annual_premium_eur': 600}, 0)[0]['insurance'], 2400)
        self.assertIsNone(lease_costs({**u, 'lease_kind': 'residual'}, p, running, None, 0)[0]['depreciation'])
        self.assertIsNone(lease_costs({**u, 'lease_extra_km_eur': None}, p, running, None, 0)[0]['purchase_sale'])
        self.assertEqual(lease_costs({**u, 'lease_km_per_year': 15000}, p, running, None, 0)[0]['purchase_sale'], 1000)  # no refund stated
        self.assertAlmostEqual(lease_costs({**u, 'lease_km_per_year': 15000, 'lease_fewer_km_eur': 0.05}, p, running, None, 0)[0]['purchase_sale'],
                               1000 - 20000 * 0.05)
        # through the API: a lease-only ad is costed as a lease; cash now, the rate cap and break-even by term
        self.req('POST', '/api/parameters', {'ownership_years': 4, 'annual_km': 10000, 'lease_rate_max_eur': 200})
        e, v, l = self.ev_listing('Petrol', listing_id='LS2', price_eur=None, lease_kind='km', lease_monthly_eur=224, lease_term_months=36,
                                  lease_km_per_year=10000, lease_down_payment_eur=500, lease_fees_eur=900, lease_includes='insurance')
        x = self.units()[l['id']]
        self.assertEqual(x['offer'], 'lease')
        self.assertEqual(x['components']['insurance'], 0)
        self.assertEqual(x['components']['depreciation'], 500 + 224 * 36)
        self.assertEqual(x['metrics']['cash_now'], 500 + 900)
        self.assertEqual(x['budget_status'], 'over_max')  # the rate is above the highest lease rate
        self.assertEqual(x['breakeven'], {'ready': False, 'missing': ['lease term differs from the ownership period']})
        self.assertIsNone(x['delta_vs_reference'])
        # an ad with both offers: bought unless the account leases or compares both
        e, v, l3 = self.ev_listing('Petrol', listing_id='LS3', lease_kind='km', lease_monthly_eur=224, lease_term_months=48)
        self.assertEqual(self.units()[l3['id']]['offer'], 'purchase')
        self.req('POST', '/api/parameters', {'acquisition_mode': 'lease'})
        x = self.units()[l3['id']]
        self.assertEqual((x['offer'], x['period_months']), ('lease', 48))
        self.assertIsNotNone(x['offers']['purchase'])

    def test_electric_research_contract_125(self):
        e, v, l = self.ev_listing()
        todo = lambda: next(m for m in self.agent('GET', 'todo')[1]['models'] if m['vehicle_id'] == v['id'])['todo']
        ids = lambda: {x.split()[1] for x in todo() if ' missing: ' in x}
        self.assertTrue({'eng.identity_ev', 'eng.hv_battery', 'eng.drive_coolant', 'eng.reduction_gear_oil', 'var.consumption'} <= ids())
        self.assertFalse({'eng.identity', 'eng.oil', 'eng.air_filter', 'eng.spark_plugs', 'eng.timing_belt', 'eng.coolant'} & ids())
        self.agent('PATCH', f"engines/{e['id']}", {'ac_charge_kw': 22})
        self.agent('POST', 'observations', {'vehicle_id': v['id'], 'category': 'consumption', 'metric': config.PRIMARY_CONSUMPTION_EV,
                                            'value_num': 16.5, 'unit': 'kWh/100 km', 'sample_count': 40, 'min_value': 12.1, 'max_value': 22.0,
                                            'status': 'PRIMARY', 'source_id': SRC_GUIDE})
        self.agent('POST', 'research_checks', {'engine_id': e['id'], 'task': 'eng.drive_coolant', 'result': 'NONE FOUND', 'source_id': SRC_GUIDE})
        self.assertFalse({'eng.identity_ev', 'var.consumption', 'eng.drive_coolant'} & ids())
        import capture_listing
        cap = {'url': 'https://x', 'platform': 'p', 'captured_at': '2026-11-05', 'vehicle_id': v['id'], 'listing': {'battery_soh_claim': 140}}
        with self.assertRaises(ValueError):
            capture_listing.validate(cap)

    def test_one_consumption_source_for_all_cars(self):
        self.sql_write('DELETE FROM observations WHERE vehicle_id=? AND metric=?', (V_REF, config.PRIMARY_CONSUMPTION))
        self.assertIsNone(self.units()[REF]['consumption'])                   # the owner's figure is a cross-check only
        self.agent('POST', 'observations', {'vehicle_id': V_REF, 'category': 'consumption', 'metric': config.PRIMARY_CONSUMPTION,
                                            'value_num': 8.0, 'status': 'PRIMARY', 'source_id': SRC_GUIDE})
        u = self.units()[REF]
        self.assertEqual((u['consumption'], u['consumption_metric']), (8.0, config.PRIMARY_CONSUMPTION))

    def sql_write(self, q, args=()):
        c = sqlite3.connect(config.DB); c.execute(q, args); c.commit(); c.close()

    def second_account(self):
        """A second, ordinary account (id 2), signed in: returns its session cookie (agent tokens are admin-only, #130)."""
        from carlos import db
        c = db.connect()
        try:
            uid = auth.create_user(c, 'maria', 'user'); tok = auth.new_token(c, uid)
            c.execute('UPDATE main.users SET password_hash=? WHERE id=?', (auth.hash_password('maria password'), uid)); c.commit()
        finally:
            c.close()
        self.assertEqual(self.req('GET', '/api/tco', token=tok)[0], 403)  # her old agent token no longer works
        st, cookie = self.login('maria', 'maria password')
        self.assertEqual(st, 200)
        self.assertEqual(self.req('POST', '/api/account/token', {}, token=None, cookie=cookie)[0], 403)
        return uid, cookie

    def test_account_prices_106(self):
        """Part 4 of #106: each account's DIY choice picks the DIY parts or the workshop price of a shared row; a missing
        price for that choice leaves the cost unknown and names the job in the to-do; tax rows have a registration window."""
        plan = lambda d, job: next(x for x in d['maintenance_plan'] if x['item'].startswith(job))
        base = self.req('GET', f'/api/listings/{CAR_A}')[1]
        self.assertEqual(plan(base, 'Spark plugs')['price_eur'], 40)                # no answer yet: the stored DIY flag
        # the admin does only oil and filters: spark plugs and brakes become workshop jobs without a workshop price
        self.assertEqual(self.req('POST', '/api/preferences', {'diy_jobs': 'oil and filters'})[0], 200)
        a = self.units()[CAR_A]
        self.assertIsNone(a['components']['maintenance'])                           # never the DIY price instead
        todo = {x['listing_id']: x['todo'] for x in self.agent('GET', 'todo')[1]['listings']}[CAR_A]
        self.assertIn("price missing for the account's DIY choice: Spark plugs (DIY) (workshop price)", todo)
        self.agent('PATCH', 'maintenance_items/2', {'reference_cost_eur': 140})
        self.agent('PATCH', 'maintenance_items/4', {'reference_cost_eur': 220})
        d = self.req('GET', f'/api/listings/{CAR_A}')[1]
        self.assertEqual((plan(d, 'Spark plugs')['price_eur'], plan(d, 'Spark plugs')['diy']), (140, 0))
        self.assertIsNotNone(d['components']['maintenance'])
        # a second account that does the plugs itself gets the DIY price from the same shared row
        uid2, t2 = self.second_account()
        H = {'X-Carlos-Account': str(uid2)}
        st, src = self.agent('POST', 'sources', {'title': 'Her listing', 'source_type': 'listing'}, headers=H)
        st, l = self.agent('POST', 'listings', {'vehicle_id': V_A, 'source_id': src['id'], 'platform': 'Test', 'listing_id': 'P1',
                                                'price_eur': 5000, 'mileage_km': 90000, 'first_registration': '2011-06'}, headers=H)
        self.assertEqual(self.req('POST', '/api/preferences', {'diy_jobs': 'oil and filters, spark plugs, brake pads and discs'}, token=None, cookie=t2)[0], 200)
        hers = self.req('GET', f'/api/listings/{l["id"]}', token=None, cookie=t2)[1]
        self.assertEqual((plan(hers, 'Spark plugs')['price_eur'], plan(hers, 'Spark plugs')['diy']), (40, 1))
        self.assertEqual(self.sql('SELECT diy, reference_cost_eur FROM maintenance_items WHERE id=2')[0], (1, 140))   # the row itself is unchanged
        # the contract wants both prices of a job an account may do itself, found by its job code
        eng = lambda: {x['id']: x for x in self.agent('GET', 'todo')[1]['catalogue']['engines']}[E_A]
        self.assertNotIn('eng.spark_plugs', eng()['missing'])
        self.agent('PATCH', 'maintenance_items/2', {'reference_cost_eur': None})
        self.assertIn('eng.spark_plugs', eng()['missing'])
        self.agent('PATCH', 'maintenance_items/2', {'reference_cost_eur': 140, 'job': None})
        self.assertIn('eng.spark_plugs', eng()['missing'])                            # no code, no match
        self.assertEqual(self.agent('PATCH', 'maintenance_items/2', {'job': 'PLUGS'})[0], 400)
        # tax: the row whose registration window covers the car's first registration (2011-06)
        self.agent('PATCH', 'tax_data/1', {'registered_from': '2012-01'})
        self.assertIsNone(self.units()[CAR_A]['annual_tax'])
        self.assertIn('lst.tax_covered', [i['id'] for i in self.units()[CAR_A]['research'] if i['grade'] == 'MISSING'])
        self.agent('POST', 'tax_data', {'vehicle_id': V_A, 'annual_tax_eur': 102, 'status': 'VERIFIED', 'registered_from': '2009-07',
                                        'registered_to': '2011-12', 'source_id': SRC_TAX_OFFICIAL})
        self.assertEqual(self.units()[CAR_A]['annual_tax'], 102)

    def test_research_requests_113(self):
        uid2, t2 = self.second_account()
        st, r = self.req('POST', '/api/requests', {'url': 'https://www.example.com/car/1', 'note': 'blue one'}, token=None, cookie=t2)
        self.assertEqual((st, r['status'], r['owner_id']), (201, 'QUEUED', uid2))
        for bad in ('ftp://example.com/x', 'not a link', 'https://' + 'a' * 500 + '.com', 'javascript:alert(1)'):
            self.assertEqual(self.req('POST', '/api/requests', {'url': bad}, token=None, cookie=t2)[0], 400, bad)
        self.assertEqual(self.req('POST', '/api/requests', {'url': 'https://www.example.com/car/1'}, token=None, cookie=t2)[0], 400)  # already open
        for i in range(2, 6):
            self.assertEqual(self.req('POST', '/api/requests', {'url': f'https://www.example.com/car/{i}'}, token=None, cookie=t2)[0], 201)
        self.assertEqual(self.req('POST', '/api/requests', {'url': 'https://www.example.com/car/9'}, token=None, cookie=t2)[0], 400)  # limit of open requests
        # each account sees only its own; the admin sees the whole queue with who asked
        self.assertEqual(self.req('GET', '/api/requests')[1], [])
        self.assertEqual(len(self.req('GET', '/api/requests', token=None, cookie=t2)[1]), 5)
        # an admin agent may queue for her (issue #139): recorded as requested_by, refused once her 5 open slots are full
        st, r = self.req('POST', '/api/requests', {'url': 'https://www.example.com/car/99'}, headers={'X-Carlos-Account': str(uid2)})
        self.assertEqual(st, 400, r)
        first = self.req('GET', '/api/requests', token=None, cookie=t2)[1][-1]
        self.assertIsNone(first['requested_by'])
        self.assertEqual({x['username'] for x in self.req('GET', '/api/admin/requests')[1]}, {'maria'})
        self.assertEqual(self.req('GET', '/api/admin/requests', token=None, cookie=t2)[0], 401)
        # cancel: own QUEUED only
        mine = self.req('GET', '/api/requests', token=None, cookie=t2)[1]
        self.assertEqual(self.req('PATCH', f'/api/requests/{mine[0]["id"]}', {'status': 'CANCELLED'})[0], 400)       # not the admin's
        self.assertEqual(self.req('PATCH', f'/api/requests/{mine[0]["id"]}', {'status': 'DONE'}, token=None, cookie=t2)[0], 400)
        self.assertEqual(self.req('PATCH', f'/api/requests/{mine[0]["id"]}', {'status': 'CANCELLED'}, token=None, cookie=t2)[0], 200)
        st, r = self.req('POST', '/api/requests', {'url': 'https://www.example.com/car/99'}, headers={'X-Carlos-Account': str(uid2)})
        self.assertEqual((st, r['owner_id'], r['requested_by']), (201, uid2, 1), r)  # 1 = the fixture's admin
        self.assertIn(r['id'], [x['id'] for x in self.req('GET', '/api/requests', token=None, cookie=t2)[1]])
        self.assertEqual(self.req('PATCH', f'/api/requests/{r["id"]}', {'status': 'CANCELLED'}, headers={'X-Carlos-Account': str(uid2)})[0], 200)
        self.assertEqual(self.req('POST', '/api/account/password', {'old': 'x', 'new': 'yyyyyyyyyy'}, headers={'X-Carlos-Account': str(uid2)})[0], 403)
        self.assertEqual(self.req('PATCH', f'/api/requests/{mine[0]["id"]}', {'status': 'CANCELLED'}, token=None, cookie=t2)[0], 400)  # no longer queued
        # the worker side is for admin tokens only
        self.assertEqual(self.req('POST', '/api/worker/claim', {'worker': 'x'}, token=None, cookie=t2)[0], 403)
        # claims hand out the oldest first, each request once, then nothing
        got = [self.req('POST', '/api/worker/claim', {'worker': 'desk'})[1]['request'] for _ in range(5)]
        self.assertEqual([g['url'][-1] for g in got[:4]], ['1', '2', '3', '4'])
        self.assertIsNone(got[4])
        self.assertEqual({g['status'] for g in got[:4]}, {'RUNNING'})
        self.assertEqual(self.req('POST', f'/api/worker/requests/{got[0]["id"]}', {'status': 'DONE'}, token=None, cookie=t2)[0], 403)
        # DONE needs a listing of the requester; the admin's car is refused
        self.assertEqual(self.req('POST', f'/api/worker/requests/{got[0]["id"]}', {'status': 'DONE', 'listing_id': CAR_A})[0], 400)
        H = {'X-Carlos-Account': str(uid2)}
        st, src = self.agent('POST', 'sources', {'title': 'Her listing', 'source_type': 'listing'}, headers=H)
        st, l = self.agent('POST', 'listings', {'vehicle_id': V_B, 'source_id': src['id'], 'platform': 'Test', 'listing_id': 'R1', 'price_eur': 4000}, headers=H)
        st, done = self.req('POST', f'/api/worker/requests/{got[0]["id"]}', {'status': 'DONE', 'listing_id': l['id'], 'result': 'ok'})
        self.assertEqual((st, done['status'], done['listing_id']), (200, 'DONE', l['id']))
        self.assertEqual(self.req('POST', f'/api/worker/requests/{got[0]["id"]}', {'status': 'FAILED'})[0], 400)  # already finished
        self.assertEqual(self.req('POST', f'/api/worker/requests/{got[1]["id"]}', {'status': 'FAILED', 'result': 'blocked'})[1]['status'], 'FAILED')
        # a RUNNING request abandoned past the timeout is handed out again
        self.sql_write("UPDATE research_requests SET claimed_at=datetime('now', '-4 hours') WHERE id=?", (got[2]['id'],))
        self.assertEqual(self.req('POST', '/api/worker/claim', {'worker': 'desk2'})[1]['request']['id'], got[2]['id'])

    def test_parallel_claims_never_share_a_request_113(self):
        for i in range(3):
            self.req('POST', '/api/requests', {'url': f'https://www.example.com/car/{i}'})
        out = []
        threads = [threading.Thread(target=lambda: out.append(self.req('POST', '/api/worker/claim', {'worker': 'w'})[1]['request'])) for _ in range(8)]
        [t.start() for t in threads]; [t.join() for t in threads]
        ids = [r['id'] for r in out if r]
        self.assertEqual((len(out), len(ids), len(set(ids))), (8, 3, 3))

    def test_registered_workers_141(self):
        """Issue #141: a worker token only heartbeats, claims and finishes; the claim hands out a per-request token that
        writes the catalogue and the requester's account only, and dies when the request ends."""
        st, w = self.req('POST', '/api/admin/workers', {'name': 'desk'})
        self.assertEqual(st, 201, w)
        wt = w['token']
        self.assertEqual(self.req('GET', '/api/tco', token=wt)[0], 403)                 # a worker token reads no data
        self.assertEqual(self.req('POST', '/api/worker/heartbeat', {'state': 'idle'}, token=wt)[0], 200)
        status = lambda: {x['name']: x for x in self.req('GET', '/api/admin/workers')[1]}['desk']
        self.assertEqual(status()['status'], 'idle')
        uid2, c2 = self.second_account()
        self.req('POST', '/api/requests', {'url': 'https://www.example.com/car/41'}, token=None, cookie=c2)
        req = self.req('POST', '/api/worker/claim', {}, token=wt)[1]['request']
        rt = req['request_token']
        self.assertEqual((req['owner_id'], req['worker']), (uid2, 'desk'))
        self.assertEqual((status()['status'], status()['request_id'], status()['username']), ('working', req['id'], 'maria'))
        # the request token: her account and the catalogue, nothing else
        self.assertEqual(self.req('GET', f'/api/listings/{CAR_A}', token=rt)[0], 404)
        self.assertEqual(self.agent('PATCH', f'listings/{CAR_A}', {'notes': 'x'}, token=rt)[0], 404)
        st, src = self.agent('POST', 'sources', {'title': 'Her listing', 'source_type': 'listing'}, token=rt)
        st, l = self.agent('POST', 'listings', {'vehicle_id': V_A, 'source_id': src['id'], 'platform': 'Test', 'listing_id': 'W1',
                                                'price_eur': 5000, 'mileage_km': 90000}, token=rt)
        self.assertEqual((st, self.sql('SELECT owner_id FROM listings WHERE id=?', (l['id'],))[0][0]), (201, uid2))
        st, g = self.agent('POST', 'generations', {'make': 'Zeta', 'model': 'Z', 'name': 'Z1'}, token=rt)
        self.assertEqual((st, self.sql('SELECT owner_id FROM generations WHERE id=?', (g['id'],))[0][0]), (201, None))   # catalogue
        for method, path, body, h in (('GET', '/api/admin/users', None, None), ('POST', '/api/parameters', {'annual_km': 1}, None),
                                      ('POST', '/api/worker/claim', {}, None), ('DELETE', f'/api/agent/listings/{l["id"]}', None, None),
                                      ('GET', '/api/tco', None, {'X-Carlos-Account': '1'})):
            self.assertEqual(self.req(method, path, body, token=rt, headers=h)[0], 403, path)
        self.assertEqual(self.req('POST', f'/api/worker/requests/{req["id"]}', {'status': 'DONE', 'listing_id': l['id']}, token=wt)[0], 200)
        self.assertEqual(self.req('GET', '/api/tco', token=rt)[0], 401)                 # dead once the request ended
        self.assertEqual(status()['state'], 'idle')
        # deactivate, reactivate, regenerate
        self.req('PATCH', f'/api/admin/workers/{w["id"]}', {'is_active': 0})
        self.assertEqual((status()['status'], self.req('POST', '/api/worker/claim', {}, token=wt)[0]), ('deactivated', 401))
        self.req('PATCH', f'/api/admin/workers/{w["id"]}', {'is_active': 1})
        new = self.req('POST', f'/api/admin/workers/{w["id"]}/token', {})[1]['token']
        self.assertEqual(self.req('POST', '/api/worker/heartbeat', {'state': 'idle'}, token=wt)[0], 401)
        self.assertEqual(self.req('POST', '/api/worker/heartbeat', {'state': 'error', 'error': 'site down'}, token=new)[0], 200)
        self.assertEqual((status()['status'], status()['last_error']), ('error', 'site down'))
        self.sql_write("UPDATE workers SET last_seen=datetime('now', '-1 hour')")
        self.assertEqual(status()['status'], 'down')
        self.assertEqual(self.req('GET', '/api/admin/workers', token=new)[0], 403)      # a worker is no admin
        # worker.py with a worker token hands the run only the per-request token, never its own or an account header
        import worker
        from capture_listing import Api
        self.req('POST', '/api/requests', {'url': 'https://www.example.com/car/42'}, token=None, cookie=c2)
        api, logs = Api(self.base, new), Path(self.tmp.name) / 'wlogs'
        api.worker = True
        worker.work_one(api, 'desk', "sh -c 'echo tok=$AGENT_TOKEN acct=${CARLOS_ACCOUNT:-none}; echo CARLOS_RESULT failed: test'", logs, 30)
        log = next(logs.glob('request-*.log')).read_text()
        self.assertIn('acct=none', log)
        self.assertNotIn(new, log)
        self.assertNotIn('tok= ', log)

    def test_admin_agent_token_reaches_every_account_143(self):
        """Issue #143: the admin agent token reads every account's rows and writes a row of another account as that account."""
        uid2, c2 = self.second_account()
        H = {'X-Carlos-Account': str(uid2)}
        st, src = self.agent('POST', 'sources', {'title': 'Her listing', 'source_type': 'listing'}, headers=H)
        st, l = self.agent('POST', 'listings', {'vehicle_id': V_A, 'source_id': src['id'], 'platform': 'Test', 'listing_id': 'A1',
                                                'price_eur': 5000, 'mileage_km': 90000}, headers=H)
        # no header: the row's own account is used
        self.assertEqual(self.agent('PATCH', f'listings/{l["id"]}', {'notes': 'checked by the admin agent'})[0], 200)
        self.assertEqual(self.sql('SELECT owner_id, notes FROM listings WHERE id=?', (l['id'],))[0], (uid2, 'checked by the admin agent'))
        hers = self.req('GET', f'/api/listings/{l["id"]}', token=None, cookie=c2)[1]
        self.assertEqual(hers['notes'], 'checked by the admin agent')
        st, ev = self.agent('POST', 'listing_events', {'listing_id': l['id'], 'event_date': '2026-11-06', 'kind': 'user_data', 'text': 'x'}, headers=H)
        self.assertEqual(self.agent('PATCH', f'listing_events/{ev["id"]}', {'text': 'y'})[0], 200)
        # every account's rows of one table, optionally one owner's
        mine_and_hers = {r['owner_id'] for r in self.req('GET', '/api/admin/data/listings')[1]}
        self.assertTrue({1, uid2} <= mine_and_hers)
        self.assertEqual({r['owner_id'] for r in self.req('GET', f'/api/admin/data/listings?owner_id={uid2}')[1]}, {uid2})
        self.assertNotIn('password_hash', self.req('GET', '/api/admin/data/users')[1][0])
        self.assertEqual(self.req('GET', '/api/admin/data/sessions')[0], 404)
        self.assertEqual(self.req('GET', '/api/admin/data/listings', token=None, cookie=c2)[0], 401)

    def test_worker_once_with_fake_claude_113(self):
        import worker
        from capture_listing import Api
        self.req('POST', '/api/requests', {'url': 'https://www.example.com/car/7'})
        logs = Path(self.tmp.name) / 'logs'
        # the fake agent proves it got the requester's account in its environment, then reports the admin's car
        cmd = f"sh -c 'echo account=$CARLOS_ACCOUNT; echo CARLOS_RESULT listing_id={CAR_A}'"
        self.assertTrue(worker.work_one(Api(self.base, TOKEN), 'test', cmd, logs, 30))
        r = self.req('GET', '/api/requests')[1][0]
        self.assertEqual((r['status'], r['listing_id'], r['worker']), ('DONE', CAR_A, 'test'))
        self.assertIn('account=1', (logs / f'request-{r["id"]}.log').read_text())
        self.assertFalse(worker.work_one(Api(self.base, TOKEN), 'test', cmd, logs, 30))   # queue empty
        self.req('POST', '/api/requests', {'url': 'https://www.example.com/car/8'})
        worker.work_one(Api(self.base, TOKEN), 'test', "sh -c 'echo CARLOS_RESULT failed: page blocked'", logs, 30)
        self.assertEqual([x['result'] for x in self.req('GET', '/api/requests')[1]][0], 'page blocked')
        self.assertEqual(worker.outcome('noise\nCARLOS_RESULT listing_id=12\n')['listing_id'], 12)
        self.assertEqual(worker.outcome('crashed')['status'], 'FAILED')
        # the research runs on Sonnet (owner, 2026-11-06): --model added after the claude executable unless given
        self.assertEqual(worker.command('claude -p', 'sonnet'), ['claude', '--model', 'sonnet', '-p'])
        self.assertEqual(worker.command('claude --chrome -p --', 'sonnet')[:3], ['claude', '--model', 'sonnet'])
        self.assertEqual(worker.command('claude --model opus -p', 'sonnet'), ['claude', '--model', 'opus', '-p'])
        self.assertEqual(worker.command("sh -c 'x'", 'sonnet'), ['sh', '-c', 'x'])

    def test_insurance_quotes(self):
        quote = {'vehicle_id': V_A, 'premium_status': 'QUOTE', 'annual_premium_eur': 850, 'premium_min_eur': 700,
                 'insurer': 'Test Insurer', 'tariff': 'Basic', 'quote_date': fx.TODAY, 'source_id': SRC_QUOTE,
                 'quote_profile': {'cover': 'Teilkasko', 'deductible_eur': 150}}
        self.assertEqual(self.agent('POST', 'insurance_data', quote)[0], 201)
        self.assertEqual(self.units()[CAR_A]['annual_insurance'], 850)        # the latest quote wins
        self.assertEqual(self.agent('POST', 'insurance_data', {**quote, 'quote_profile': 'x'})[0], 400)
        self.assertEqual(self.agent('POST', 'insurance_data', {**quote, 'quote_date': '03.11.2026'})[0], 400)
        self.assertEqual(self.agent('POST', 'insurance_data', {'vehicle_id': V_A, 'liability_typklasse': 17, 'source_id': SRC_QUOTE})[0], 201)
        self.assertEqual(self.units()[CAR_A]['annual_insurance'], 850)        # a Typklasse-only row is not a premium
        self.assertEqual(self.agent('POST', 'insurance_data', {**quote, 'vehicle_id': V_REF, 'annual_premium_eur': 500})[0], 201)
        self.assertEqual(self.units()[REF]['annual_insurance'], 900)          # the reference keeps what the user pays

    def test_data_bugs_107(self):
        # a source of another account cannot be cited, also where source_id has no declared foreign key
        self.sql_write("INSERT INTO users (id, username, role) VALUES (2, 'other', 'user')")
        self.sql_write("INSERT INTO sources (id, owner_id, title) VALUES (99, 2, 'Not yours')")
        row = {'vehicle_id': V_A, 'item': 'x', 'schedule': 'ITEM', 'source_id': 99}
        self.assertEqual(self.agent('POST', 'maintenance_items', row)[0], 400)
        self.assertEqual(self.agent('POST', 'maintenance_items', {**row, 'source_id': SRC_GUIDE})[0], 201)
        # a newer estimate does not hide a verified tax row
        self.agent('POST', 'tax_data', {'vehicle_id': V_A, 'annual_tax_eur': 120, 'status': 'ESTIMATED', 'source_id': SRC_GUIDE})
        self.assertEqual(self.units()[CAR_A]['annual_tax'], 94)
        # the reference car's insurance is the premium the owner pays (USER DATA), not the newer quote, in the cost and
        # in the research contract (#114 replaced the row evidence)
        ref = self.units()[REF]
        self.assertEqual(ref['annual_insurance'], 900)
        self.assertEqual({i['id']: i['grade'] for i in ref['research']}['lst.insurance'], 'VERIFIED')

    def test_todo(self):
        d = self.agent('GET', 'todo')[1]
        lst = {x['listing_id']: x['todo'] for x in d['listings']}
        mod = {x['vehicle_id']: x['todo'] for x in d['models']}
        self.assertIn('no verdict', lst[CAR_A])
        self.assertNotIn('no verdict', lst[REF])
        self.assertIn('no listing capture (listing_snapshots)', lst[CAR_B])
        self.assertTrue(any(t.startswith('not checked for over') for t in lst[CAR_B]))
        self.assertIn('variant var.tax missing: annual tax from the BMF Kfz-Steuer-Rechner', mod[V_B])   # an estimate is not the calculator
        self.assertIn('variant var.identity missing: HSN/TSN, gearbox, body, emissions class, CO2', mod[V_B2])
        self.assertIn('variant var.gearbox missing: automatic gearbox weak points checked for this variant', mod[V_B2])
        self.assertFalse(any('var.gearbox' in t for t in mod[V_A]))           # manual gearbox: the generation's checks suffice
        self.assertIn('generation gen.recalls missing: recall search (KBA / manufacturer)', mod[V_A])
        self.assertEqual({x['vehicle_id']: x['state'] for x in d['models']}[V_A], 'incomplete')
        self.assertEqual(set(d['catalogue']), {'generations', 'engines', 'variants'})
        e_a = {x['id']: x for x in d['catalogue']['engines']}[E_A]
        self.assertIn('eng.coolant', e_a['missing'])
        self.assertIn('eng.oil', e_a['accepted'])                               # a DIY price from a C source
        self.assertNotIn('items', e_a)
        # an expired quote is the listing's own research item
        self.agent('PATCH', 'insurance_data/1', {'quote_date': '2026-01-01'})
        self.assertIn(f'listing lst.insurance missing: an insurance quote younger than {config.QUOTE_MAX_AGE_DAYS} days',
                      {x['listing_id']: x['todo'] for x in self.agent('GET', 'todo')[1]['listings']}[CAR_A])
        self.agent('PATCH', f'listings/{CAR_A}', {'verdict': 'Strong candidate'})
        self.assertNotIn('no verdict', {x['listing_id']: x['todo'] for x in self.agent('GET', 'todo')[1]['listings']}[CAR_A])
        self.agent('PATCH', f'listings/{CAR_B}', {'listing_status': 'WITHDRAWN'})
        self.assertNotIn(CAR_B, {x['listing_id'] for x in self.agent('GET', 'todo')[1]['listings']})

    def test_research_contract(self):
        from unittest import mock
        from carlos import research
        lvl = lambda: {x['id']: x for x in self.agent('GET', 'todo')[1]['catalogue']['engines']}[E_A]
        # a check that consulted a source and found nothing satisfies an item (a C source: ACCEPTED, not VERIFIED)
        st, _ = self.agent('POST', 'research_checks', {'engine_id': E_A, 'task': 'eng.coolant', 'result': 'NONE FOUND', 'source_id': SRC_GUIDE})
        self.assertEqual(st, 201)
        self.assertIn('eng.coolant', lvl()['accepted'])
        bad = {'engine_id': E_A, 'task': 'eng.nonsense', 'result': 'FOUND', 'source_id': SRC_GUIDE}
        self.assertEqual(self.agent('POST', 'research_checks', bad)[0], 400)
        self.assertEqual(self.agent('POST', 'research_checks', {**bad, 'task': 'eng.coolant', 'result': 'MAYBE'})[0], 400)
        # raising an item's `since` makes checks recorded against the older contract stop counting
        bumped = [i[:-1] + (research.CONTRACT_VERSION + 1,) if i[0] == 'eng.coolant' else i for i in research.ITEMS]
        with mock.patch.object(research, 'ITEMS', bumped):
            self.assertIn('eng.coolant', lvl()['missing'])
        # a part without its required source checks is unknown: reliability unknown, never full points or 0
        a = self.units()[CAR_A]
        self.assertEqual(a['metrics']['reliability'], 33.5)
        conf = a['metrics']['confidence']
        self.assertEqual(conf, research.confidence(a['research']))
        c = sqlite3.connect(config.DB)
        check = c.execute('SELECT id FROM research_checks WHERE generation_id=? AND task=?', (G1, 'rel.CHASSIS.adac')).fetchone()[0]
        c.close()
        self.assertEqual(self.agent('PATCH', f'research_checks/{check}', {'archived': 1})[0], 200)
        a = self.units()[CAR_A]
        self.assertIsNone(a['metrics']['reliability'])
        self.assertIsNone(a['reliability_parts']['CHASSIS'])
        self.assertEqual(a['reliability_parts']['ENGINE'], 7)
        self.assertLess(a['metrics']['confidence'], conf)                       # one required item fewer done
        # every contract item is documented in the protocol, so code and docs stay in step
        doc = (config.ROOT / 'docs' / 'cost-research-protocol.md').read_text()
        self.assertEqual([i[0] for i in research.ITEMS if not i[0].startswith('rel.') and f'`{i[0]}`' not in doc], [])
        self.assertIn('`rel.<PART>.<source>`', doc)
        # the schema publishes the contract
        sch = self.agent('GET', 'schema')[1]
        self.assertEqual(sch['research_contract']['version'], research.CONTRACT_VERSION)
        self.assertIn('rel.ENGINE.engine_specific', {i['id'] for i in sch['research_contract']['items']})
        # the models API and the dossier carry the state per level
        self.assertIn(self.req('GET', f'/api/vehicles/{V_A}')[1]['research']['engine']['state'], ('incomplete', 'researched', 'verified'))
        self.assertIn('listing', self.req('GET', f'/api/listings/{CAR_A}')[1]['research_levels'])

    def test_price_history_and_todo_mismatch(self):
        u = self.units()[CAR_A]
        self.assertEqual([h['price_eur'] for h in u['price_history']], [6200, 6000])
        self.assertEqual(u['price_change'], {'eur': -200, 'since': '2026-10-01'})
        self.assertIsNone(self.units()[REF]['price_change'])
        self.agent('PATCH', f'listings/{CAR_A}', {'price_eur': 6150})
        todo = {x['listing_id']: x['todo'] for x in self.agent('GET', 'todo')[1]['listings']}[CAR_A]
        self.assertTrue(any(t.startswith('listing price_eur (6150) differs from the latest capture (6000)') for t in todo))

    def test_breakeven(self):
        us = self.units()
        a, ref = us[CAR_A], us[REF]
        be = a['breakeven']
        self.assertTrue(be['ready'])
        self.assertEqual(be['upfront'], 6000 + (34 + 159) + 7.5 - 2500)
        self.assertAlmostEqual(be['monthly'], sum(a['components'][k] for k in config.RUNNING_COMPONENTS) / 48, places=2)
        self.assertAlmostEqual(be['ref_monthly'], sum(ref['components'][k] for k in config.RUNNING_COMPONENTS) / 48, places=2)
        self.assertAlmostEqual(be['payback_months'], round(be['upfront'] / (be['ref_monthly'] - be['monthly']), 1))
        keep_end = be['ref_monthly'] * 48 + 7.5 - 1500
        switch_end = be['upfront'] + be['monthly'] * 48 - 4000
        self.assertAlmostEqual(be['end_advantage'], keep_end - switch_end, delta=0.5)   # rounded parts
        if a['delta_vs_reference'] is not None:                       # the two views tell the same story
            self.assertAlmostEqual(be['end_advantage'], -a['delta_vs_reference'], delta=1)
        self.assertTrue(ref['breakeven']['ready'])
        st, l = self.agent('POST', 'listings', {'vehicle_id': V_B2, 'source_id': SRC_LISTING, 'listing_id': 'BE1', 'price_eur': 5000})
        be = self.units()[l['id']]['breakeven']
        self.assertFalse(be['ready'])
        self.assertNotIn('car: fuel', be['missing'])                          # engine-level consumption is inherited
        for k in ('car: insurance', 'car: tax', 'car: repairs', 'car: purchase_sale', 'car: resale_end valuation'):
            self.assertIn(k, be['missing'])

    def test_age_years(self):
        today = datetime.date(2026, 11, 2)
        self.assertEqual(costs.age_years('2008-06', today), 18.4)
        self.assertEqual(costs.age_years('2008', today), 18.3)
        self.assertIsNone(costs.age_years(None, today))

    # --- ranking ---
    def test_rank_scoring(self):
        m = lambda **kw: {k: kw.get(k) for k in ranking.CRITERIA}
        rows = [{'id': 1, 'is_reference': 1, 'listing_status': 'OWNED', 'metrics': m(cash_now=None, mileage=200000)},
                {'id': 2, 'is_reference': 0, 'listing_status': 'UNDER REVIEW', 'metrics': m(cash_now=5000, mileage=100000, power=90)},
                {'id': 3, 'is_reference': 0, 'listing_status': 'UNDER REVIEW', 'metrics': m(cash_now=7000, mileage=50000, power=120)},
                {'id': 4, 'is_reference': 0, 'listing_status': 'UNDER REVIEW', 'metrics': m(cash_now=6000, confidence=70)},
                {'id': 5, 'is_reference': 0, 'listing_status': 'WITHDRAWN', 'metrics': m(cash_now=1, mileage=1)}]
        w = {k: 0 for k in ranking.CRITERIA} | {'cash_now': 2, 'mileage': 1, 'power': 1, 'confidence': 3}
        self.assertEqual(ranking.rank(rows, w), 3)                 # reference and withdrawn are not candidates
        r = {x['id']: x for x in rows}
        self.assertEqual(r[2]['score_parts'], {'cash_now': 100, 'mileage': 0, 'power': 0})
        self.assertEqual(r[2]['score'], 50.0)
        self.assertEqual(r[4]['coverage'], round(2 / 7, 2))        # missing data lowers coverage, it never scores 0
        self.assertTrue(r[5]['score'] is None and r[5]['rank'] is None)                        # withdrawn: not scored
        self.assertEqual((r[1]['score'], r[1]['rank']), (0.0, None))   # reference (issue #72): scored with the candidates' bounds, clamped (200,000 km is worse than every candidate), never ranked
        self.assertEqual(ranking.rank(rows, w), 3)                                             # and it does not change the candidates
        ex = {e['criterion']: e for e in r[4]['explain']}
        self.assertEqual((ex['cash_now']['score'], ex['cash_now']['contribution'], ex['cash_now']['bounds']), (50, 50.0, {'min': 5000, 'max': 7000, 'n': 3}))
        self.assertEqual(ex['confidence']['why_missing'], 'fewer than two cars with a value')
        self.assertEqual(ex['mileage']['why_missing'], 'no value for this car')
        self.assertEqual(ex['age']['why_missing'], 'weight 0')

    def test_questionnaire_weights(self):
        C, T = ranking.CRITERIA, ranking.TASKS
        self.assertEqual(set(ranking.weights_from_answers({}).values()), {ranking.NEUTRAL_WEIGHT})   # no answers: neutral
        seen = {k: sum(k in x['criteria'] for x in T) for k in C}
        self.assertEqual((len(C), len(T), set(len(x['criteria']) for x in T)), (8, 8, {4}))
        self.assertEqual(set(seen.values()), {4})                         # every criterion in exactly four tasks
        pairs = [frozenset(p) for x in T for p in __import__('itertools').combinations(x['criteria'], 2)]
        self.assertEqual((len(pairs), len(set(pairs)), set(pairs.count(x) for x in set(pairs))), (48, 28, {1, 2, 3}))   # every pair meets at least once
        always = {x['id']: f"power>{[k for k in x['criteria'] if k != 'power'][0]}" if 'power' in x['criteria'] else None for x in T}
        w = ranking.weights_from_answers({k: v for k, v in always.items() if v})
        self.assertEqual(w['power'], 5)                                   # picked first every time it was shown
        never = {x['id']: f"{x['criteria'][1] if x['criteria'][0] == 'power' else x['criteria'][0]}>power" for x in T if 'power' in x['criteria']}
        self.assertEqual(ranking.weights_from_answers(never)['power'], 1)  # picked last every time: floor 1
        self.assertEqual(ranking.weights_from_answers({'r1': 'cost_month>power'})['mileage'], 3)   # middle once → neutral
        self.assertEqual(ranking.known_answers({'cash': 'tight', 'r1': 'power>mileage', 'r2': 'power>age', 'q1': 'power>mileage', 't1': 'power>age'}), {'r1': 'power>mileage'})   # t…, q…: retired
        with self.assertRaises(ValueError):
            ranking.check_answers({'r1': 'power>power'})
        st, d = self.req('GET', '/api/ranking')
        self.assertEqual((st, d['answered'], d['manual'], len(d['tasks'])), (200, False, False, 8))
        st, p = self.req('POST', '/api/parameters', {'ranking_answers': {'r1': 'power>cost_month'}})
        self.assertEqual(st, 200)
        d = self.req('GET', '/api/ranking')[1]
        self.assertEqual((d['answered'], d['weights']['power'], d['weights']['cost_month'], d['weights']['age'], d['tally']['power']),
                         (True, 5, 1, 3, {'shown': 1, 'best': 1, 'worst': 0}))
        self.assertEqual(self.req('POST', '/api/parameters', {'ranking_answers': {'r1': 'age>cash_now'}})[0], 400)
        self.req('POST', '/api/parameters', {'ranking_weights': {'power': 2}})
        d = self.req('GET', '/api/ranking')[1]
        self.assertEqual((d['manual'], d['weights']['power'], d['derived_weights']['power']), (True, 2, 5))
        self.req('POST', '/api/parameters', {'ranking_weights': None})                 # back to the answers
        self.assertEqual(self.req('GET', '/api/ranking')[1]['manual'], False)

    def test_reliability_parts(self):
        """Issue #54: each part starts at 9 and loses its 3 worst points (higher is better); a recall drops out once its check is OK; no part = unknown."""
        rows = [dict(id=i, component=f'c{i}', severity=sev, part=part, is_recall=rec, source_id=1)
                for i, (sev, part, rec) in enumerate([('HIGH', 'ENGINE', 0), ('MEDIUM', 'ENGINE', 0), ('MEDIUM', 'ENGINE', 0),
                                                      ('LOW', 'ENGINE', 0), ('HIGH IF APPLICABLE', 'ELECTRICS', 1), ('LOW', 'CHASSIS', 0)], 1)]
        total, parts, det = costs.reliability(rows, {})
        self.assertEqual((parts, total), ({'ENGINE': 2, 'GEARBOX': 9, 'CHASSIS': 8.5, 'ELECTRICS': 7.5}, 27))   # the 4th engine point is not counted
        self.assertFalse(next(d for d in det if d['id'] == 4)['counted'])
        total, parts, det = costs.reliability(rows, {5: 'OK'})                     # recall checked: done
        self.assertEqual((parts['ELECTRICS'], total, next(d for d in det if d['id'] == 5)['excluded']), (9, 28.5, 'recall_checked'))
        self.assertEqual(costs.reliability(rows, {5: 'PROBLEM'})[0], 27)           # still open: counts
        self.assertIsNone(costs.reliability(rows + [dict(id=9, component='x', severity='LOW', part=None, is_recall=0, source_id=1)], {})[0])
        self.assertEqual(costs.reliability([], {})[0], 36)                     # every source checked, nothing found: clean (#114)
        self.assertEqual(costs.reliability([], {}, known={'ENGINE'})[:2], (None, {'ENGINE': 9, 'GEARBOX': None, 'CHASSIS': None, 'ELECTRICS': None}))
        # API: part is required; a recall gets its own linked check, which decides whether it counts and stays out of inspection
        self.assertEqual(self.agent('POST', 'reliability_items', {'engine_id': E_A, 'component': 'Injector', 'severity': 'LOW', 'source_id': SRC_GUIDE})[0], 400)
        self.assertEqual(self.agent('POST', 'reliability_items', {'engine_id': E_A, 'component': 'Injector', 'severity': 'LOW', 'part': 'MOTOR', 'source_id': SRC_GUIDE})[0], 400)
        st, r = self.agent('POST', 'reliability_items', {'generation_id': G1, 'component': 'Airbag recall', 'severity': 'HIGH IF APPLICABLE', 'part': 'ELECTRICS',
                                                         'is_recall': 1, 'source_id': SRC_GUIDE, 'inspection_action': 'Dealer check by VIN'})
        self.assertEqual(st, 201)
        before = self.req('GET', f'/api/listings/{CAR_A}')[1]['metrics']['reliability'] + 1.5   # the new recall already costs its points (no check yet)
        st, i = self.agent('POST', 'inspection_items', {'listing_id': CAR_A, 'item': 'Recall: airbag', 'status': 'PENDING', 'reliability_item_id': r['id']})
        self.assertEqual(st, 201)
        self.assertEqual(self.req('GET', f'/api/listings/{CAR_A}')[1]['metrics']['reliability'], before - 1.5)   # pending: counts
        before -= 1.5
        self.assertEqual(self.ui('PATCH', f"inspection_items/{i['id']}", {'status': 'PROBLEM'})[0], 200)
        a = self.req('GET', f'/api/listings/{CAR_A}')[1]
        self.assertEqual((a['metrics']['reliability'], a['metrics']['inspection']), (before, None))   # open recall counts in reliability only; inspection still unchecked
        self.ui('PATCH', f"inspection_items/{i['id']}", {'status': 'OK'})
        self.assertEqual(self.req('GET', f'/api/listings/{CAR_A}')[1]['metrics']['reliability'], before + 1.5)

    def test_archive_and_delete(self):
        """Issue #58: archived rows drop out of every read and calculation and can be restored; delete refuses while a
        row is referenced, removes a listing with its own rows, and is logged."""
        a = self.req('GET', f'/api/listings/{CAR_A}')[1]
        chain = next(r for r in a['reliability'] if r['component'] == 'Timing chain')
        self.assertEqual(self.agent('PATCH', f"reliability_items/{chain['id']}", {'archived': 1})[0], 200)
        a2 = self.req('GET', f'/api/listings/{CAR_A}')[1]
        self.assertNotIn(chain['id'], [r['id'] for r in a2['reliability']])
        self.assertEqual(a2['metrics']['reliability'], a['metrics']['reliability'] + 2)          # the MEDIUM point no longer costs
        self.assertEqual(self.agent('PATCH', f"reliability_items/{chain['id']}", {'archived': 0})[0], 200)   # restore
        self.assertEqual(self.req('GET', f'/api/listings/{CAR_A}')[1]['metrics']['reliability'], a['metrics']['reliability'])
        self.assertEqual(self.agent('PATCH', f"reliability_items/{chain['id']}", {'archived': 2})[0], 400)
        st, r = self.agent('DELETE', f"vehicles/{V_A}")
        self.assertEqual(st, 400); self.assertIn('listings.vehicle_id', r['error'])            # still used by a listing
        self.assertEqual(self.agent('DELETE', 'listings')[0], 405)
        self.assertEqual(self.agent('DELETE', 'listings/99999')[0], 404)
        n_children = self.sql('SELECT count(*) FROM inspection_items WHERE listing_id=?', (CAR_A,))[0][0]
        st, r = self.agent('DELETE', f'listings/{CAR_A}')
        self.assertEqual((st, r['deleted'], r['removed_children']['inspection_items']), (200, True, n_children))
        self.assertEqual(self.sql('SELECT count(*) FROM listings WHERE id=?', (CAR_A,))[0][0], 0)
        self.assertEqual(self.sql("SELECT action FROM change_log WHERE table_name='listings' AND row_id=? ORDER BY id DESC LIMIT 1", (CAR_A,))[0][0], 'delete')
        self.assertEqual(self.req('GET', f'/api/listings/{CAR_A}')[0], 404)

    def test_owner_decision(self):
        ls = self.req('GET', '/api/tco')[1]['listings']
        cand = next(u for u in ls if not u['is_reference'] and u['listing_status'] != 'WITHDRAWN'); ref = next(u for u in ls if u['is_reference'])
        st, _ = self.req('POST', f"/api/ui/decision/{cand['id']}", {'decision': 'reject', 'reason': 'too far away'})
        self.assertEqual(st, 201)
        d = self.req('GET', f"/api/listings/{cand['id']}")[1]
        self.assertEqual((d['listing_status'], d['verdict']), ('WITHDRAWN', 'Rejected by the owner: too far away'))
        self.assertTrue(any(e['kind'] == 'decision' for e in d['events']))
        self.req('POST', f"/api/ui/decision/{cand['id']}", {'decision': 'reset'})
        d = self.req('GET', f"/api/listings/{cand['id']}")[1]
        self.assertEqual((d['listing_status'], d['verdict']), ('UNDER REVIEW', None))
        self.assertEqual(self.req('POST', f"/api/ui/decision/{ref['id']}", {'decision': 'shortlist'})[0], 400)
        self.assertEqual(self.req('POST', f"/api/ui/decision/{cand['id']}", {'decision': 'maybe'})[0], 400)

    def test_account_todo(self):
        d = self.req('GET', '/api/todo')[1]
        self.assertTrue(any(x.startswith('setup not finished') for x in d['account']))
        self.assertTrue(any('insurance_holder_birth_date' in x for x in d['account']))
        self.req('POST', '/api/preferences', {'onboarding_done': '2026-11-05', 'insurance_holder_birth_date': '1990-01-01'})
        d = self.req('GET', '/api/todo')[1]
        self.assertFalse(any(x.startswith('setup not finished') for x in d['account']))
        self.assertFalse(any('insurance_holder_birth_date' in x for x in d['account']))

    def test_preferences_upsert(self):
        st, d = self.req('POST', '/api/preferences', {'search_radius': '100', 'diy_jobs': 'oil and filters, brakes'})
        self.assertEqual(st, 200)
        self.assertEqual({r['preference_key']: r['preference_value'] for r in d}['search_radius'], '100')
        st, d = self.req('POST', '/api/preferences', {'search_radius': '50', 'diy_jobs': None})
        prefs = {r['preference_key']: r['preference_value'] for r in d}
        self.assertEqual((prefs['search_radius'], 'diy_jobs' in prefs), ('50', False))
        self.assertEqual(self.req('POST', '/api/preferences', {'Bad Key': 'x'})[0], 400)
        self.assertEqual(self.req('POST', '/api/preferences', ['x'])[0], 400)

    def test_budget_ranking_api_and_weights(self):
        st, l = self.agent('POST', 'listings', {'vehicle_id': V_B2, 'source_id': SRC_LISTING, 'platform': 'Test', 'listing_id': 'B2',
                                                'price_eur': 9000, 'first_registration': '2016-03'})
        st, d = self.req('GET', '/api/tco')
        us = {u['listing_id']: u for u in d['listings']}
        self.assertEqual((us['A1']['budget_status'], us['B1']['budget_status'], us['B2']['budget_status']), ('within', 'over_ideal', 'over_max'))
        self.assertIsNone(us[None]['budget_status'])
        self.assertEqual(d['ranking']['candidates'], 3)
        self.assertEqual(sorted(u['rank'] for u in d['listings'] if u['rank']), [1, 2, 3])
        self.assertEqual(self.req('POST', '/api/parameters', {'ranking_weights': {'cash_now': 9}})[0], 400)
        self.assertEqual(self.req('POST', '/api/parameters', {'ranking_weights': {'price': 1}})[0], 400)   # old criterion
        st, p = self.req('POST', '/api/parameters', {'ranking_weights': {'cash_now': 5, 'power': 0}})
        self.assertEqual(st, 200)
        w = self.req('GET', '/api/tco')[1]['ranking']['weights']
        self.assertEqual((w['cash_now'], w['mileage']), (5, ranking.weights_from_answers({})['mileage']))
        self.assertEqual(self.req('POST', '/api/parameters', {'budget_ideal_eur': 9000, 'budget_max_eur': 8000})[0], 400)
        self.assertEqual(self.req('GET', '/api/tco?budget_ideal_eur=9000')[0], 400)   # preview validated too

    def test_parameter_preview_does_not_save(self):
        st, d = self.req('GET', '/api/tco?annual_km=30000&ownership_years=2')
        self.assertTrue(d['preview'])
        self.assertEqual(d['parameters']['annual_km'], 30000)
        a = next(u for u in d['listings'] if u['id'] == CAR_A)
        self.assertAlmostEqual(a['components']['insurance'], 800 * 2)
        self.assertEqual(self.req('GET', '/api/parameters')[1]['annual_km'], 15000)
        self.assertEqual(self.req('GET', '/api/tco?annual_km=abc')[0], 400)

    def test_parameter_validation(self):
        post = lambda b, ct='application/json': self.req('POST', '/api/parameters', b, ctype=ct)[0]
        self.assertEqual(post({'annual_km': 0}), 400)
        self.assertEqual(post({'ownership_years': None}), 400)
        self.assertEqual(post({'annual_km': 1.5}), 400)
        self.assertEqual(post({'fuel_price_date': 'yesterday'}), 400)
        self.assertEqual(post({'fuel_price_eur_l': float('inf')}), 400)
        self.assertEqual(post({'annual_km': 1}, 'text/plain'), 415)
        st, p = self.req('POST', '/api/parameters', {'annual_km': 12000, 'sf_class': '  ', 'driver_age': None})
        self.assertEqual(st, 200)
        self.assertEqual((p['annual_km'], p['sf_class'], p['driver_age']), (12000, None, None))
        self.assertTrue(self.req('GET', '/api/tco')[1]['fuel_price_stale'] is False)
        self.req('POST', '/api/parameters', {'fuel_price_date': '2026-01-01'})
        self.assertTrue(self.req('GET', '/api/tco')[1]['fuel_price_stale'])

    # --- agent API ---
    def test_agent_auth_and_schema(self):
        self.assertEqual(self.req('POST', '/api/agent/listing_events', {'listing_id': 1}, token=None)[0], 401)
        self.assertEqual(self.req('GET', '/api/agent/schema', token='bad')[0], 401)
        st, s = self.agent('GET', 'schema')
        self.assertEqual(st, 200)
        self.assertIn('engines', s['writable_tables'])
        self.assertEqual(s['scope_columns'], ['vehicle_id', 'engine_id', 'generation_id'])
        self.assertEqual(s['code_formats']['listing_events.kind'], '[a-z][a-z_]*')
        self.assertIn('WET BELT', s['fixed_codes']['engines.timing_drive'])
        self.assertEqual(self.agent('POST', 'listing_events', {'listing_id': CAR_A, 'event_date': '2026-11-03', 'kind': 'Decision', 'text': 'x'})[0], 400)
        self.assertEqual(self.agent('PATCH', f'listings/{CAR_A}', {'listing_status': 'retirado'})[0], 400)
        self.assertEqual(self.agent('PATCH', f'listings/{CAR_A}', {'listing_status': 'WITHDRAWN'})[0], 200)

    def test_agent_validation(self):
        v = {'listing_id': CAR_A, 'kind': 'resale_end', 'expected_eur': 3000, 'status': 'ESTIMATED'}
        self.assertEqual(self.agent('POST', 'valuations', v)[0], 400)                                        # no source
        self.assertEqual(self.agent('POST', 'valuations', {**v, 'source_id': SRC_GUIDE, 'expected_eur': ''})[0], 400)  # '' → NULL → NOT NULL
        self.assertEqual(self.agent('POST', 'valuations', {**v, 'source_id': SRC_GUIDE, 'kind': 'other'})[0], 400)    # CHECK
        self.assertEqual(self.agent('POST', 'valuations', {**v, 'source_id': 999})[0], 400)                   # FK
        self.assertEqual(self.agent('POST', 'valuations', {**v, 'source_id': SRC_GUIDE, 'hack': 1})[0], 400)  # column
        self.assertEqual(self.agent('POST', 'sources', {'title': 't', 'quality': 'A/B'})[0], 400)
        self.assertEqual(self.agent('POST', 'change_log', {'table_name': 'x'})[0], 404)
        self.assertEqual(self.agent('PATCH', 'listings/999', {'verdict': 'x'})[0], 404)
        self.assertEqual(self.agent('PATCH', f'listings/{CAR_A}', {'source_id': None})[0], 400)
        self.assertEqual(self.agent('POST', 'repair_risks', {'vehicle_id': V_A, 'component': 'X', 'km_from': 10, 'km_to': 5, 'probability': 0.1, 'parts_eur': 1, 'source_id': SRC_GUIDE})[0], 400)

    def test_agent_write_logs_and_regenerates_markdown(self):
        st, r = self.agent('PATCH', f'listings/{CAR_A}', {'verdict': 'Strong candidate, inspection pending'})
        self.assertEqual((st, r), (200, {'table': 'listings', 'id': CAR_A}))
        old, new = self.sql("SELECT old_json, new_json FROM change_log WHERE table_name='listings' ORDER BY id DESC LIMIT 1")[0]
        self.assertEqual(json.loads(new), {'verdict': 'Strong candidate, inspection pending'})
        self.assertIsNone(json.loads(old)['verdict'])
        md = (config.MD_DIR / '1' / 'Alpha-Hatch-Test-A1.md').read_text()
        self.assertIn('Strong candidate, inspection pending', md)
        self.assertIn('BC12T', (config.MD_DIR / '1' / 'Beta-City-Test-B1.md').read_text())
        self.assertTrue((config.MD_DIR / '1' / 'Alpha-Hatch-OWNED-u1.md').exists())
        self.agent('PATCH', f'listings/{CAR_A}', {'verdict': 'x'})
        self.assertNotIn('inspection pending', (config.MD_DIR / '1' / 'Alpha-Hatch-Test-A1.md').read_text())
        self.assertEqual(self.agent('POST', 'export-md')[0], 200)

    def test_dossiers_follow_saved_parameters(self):
        md = lambda: (config.MD_DIR / '1' / 'Alpha-Hatch-Test-A1.md').read_text()
        self.agent('POST', 'export-md')
        self.assertIn('4 years, 60,000 km', md())
        self.req('GET', '/api/tco?ownership_years=2')
        self.assertIn('4 years, 60,000 km', md())                              # a preview changes nothing
        self.req('POST', '/api/parameters', {'ownership_years': 2})
        self.assertIn('2 years, 30,000 km', md())

    def test_archive_snapshot_and_photos(self):
        st, new = self.agent('POST', 'listings', {'vehicle_id': V_B2, 'source_id': SRC_LISTING, 'platform': 'Test', 'listing_id': 'T1', 'price_eur': 7000})
        self.assertEqual(st, 201)
        L = new['id']
        self.assertEqual((self.units()[L]['cover'], self.units()[L]['photo_count']), (None, 0))
        snap = {'listing_id': L, 'captured_at': '2026-11-02T14:00', 'source_id': SRC_LISTING, 'title': 'Beta City Plus',
                'price_eur': 6450, 'description': 'Line 1\nLine 2', 'attributes_json': {'Getriebe': 'Automatik', 'HU': '11/2028'}}
        st, r = self.agent('POST', 'listing_snapshots', snap)
        self.assertEqual(st, 201)
        self.assertEqual(self.agent('POST', 'listing_snapshots', {**snap, 'attributes_json': '[1]'})[0], 400)  # not an object
        self.assertEqual(self.agent('POST', 'listing_snapshots', {**snap, 'source_id': None})[0], 400)
        jpg = b'\xff\xd8\xff\xe0' + b'x' * 100
        st, m = self.upload(jpg, L, q=f'?url=https://img.example/1.jpg&snapshot_id={r["id"]}')
        self.assertEqual((st, m['created']), (201, True))
        self.assertEqual(self.upload(jpg, L)[1]['created'], False)                 # deduplicated by sha256
        self.assertEqual(self.upload(b'GIF89a', L)[0], 400)                         # type not allowed
        self.assertEqual(self.upload(jpg, L, ctype='application/json')[0], 415)
        self.assertEqual(self.upload(jpg, lid=999)[0], 404)
        self.assertEqual(self.upload(b'\xff\xd8\xff' + b'x' * config.MAX_IMAGE_BYTES, L)[0], 400)
        budget, config.STORAGE_BUDGET = config.STORAGE_BUDGET, 0
        try:
            self.assertEqual(self.upload(jpg + b'more', L)[0], 507)                 # quota
        finally:
            config.STORAGE_BUDGET = budget
        d = self.req('GET', f'/api/listings/{L}')[1]
        self.assertEqual(len(d['media']), 1)
        self.assertEqual((d['cover'], d['photo_count']), (d['media'][0]['file_path'], 1))
        r = urllib.request.Request(f"{self.base}/media/{d['media'][0]['file_path']}", headers={'Authorization': f'Bearer {TOKEN}'})
        self.assertEqual(urllib.request.urlopen(r).read(), jpg)
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(f"{self.base}/media/{d['media'][0]['file_path']}")   # login required
        md = (config.MD_DIR / '1' / 'Beta-City-Test-T1.md').read_text()
        self.assertIn('> Line 2', md)
        self.assertIn('| Getriebe | Automatik |', md)
        self.assertIn(f'../../media/{L}/', md)
        self.assertEqual(len(list((config.MEDIA_DIR / str(L)).iterdir())), 1)  # no orphan files

    def test_storage_and_health(self):
        st = self.req('GET', '/api/storage')[1]
        self.assertEqual(st['limit_bytes'], 500 * 1024 ** 2)
        self.assertLess(st['total_bytes'], st['limit_bytes'])
        h = self.req('GET', '/api/health')[1]
        self.assertEqual((h['integrity'], h['listings']), ('ok', 3))
        self.assertEqual(h['schema_version'], migrate.latest_version())

    def test_listing_detail_and_static(self):
        st, d = self.req('GET', f'/api/listings/{CAR_A}')
        self.assertEqual(st, 200)
        self.assertEqual(len(d['inspection']), 2)
        self.assertEqual([e['kind'] for e in d['events']], ['found'])
        self.assertEqual(len(d['snapshots']), 2)
        self.assertEqual(self.req('GET', '/api/listings/999')[0], 404)
        self.assertEqual(self.req('GET', '/api/nothing')[0], 404)
        self.assertEqual(urllib.request.urlopen(self.base + '/').status, 200)
        self.assertEqual(urllib.request.urlopen(self.base + '/login').status, 200)
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(self.base + '/static/../app.py')

    # --- viewing mode ---
    def test_viewing_mode(self):
        self.assertEqual(self.ui('GET', 'check')[0], 200)
        self.assertEqual(self.ui('GET', 'check', token=None)[0], 401)
        st, r = self.ui('PATCH', 'inspection_items/1', {'status': 'OK', 'notes': 'Quiet cold start', 'item': 'hacked'})
        self.assertEqual(st, 200)
        item, status, notes, date = self.sql('SELECT item, status, notes, checked_date FROM inspection_items WHERE id=1')[0]
        self.assertEqual((status, notes, date), ('OK', 'Quiet cold start', datetime.date.today().isoformat()))
        self.assertNotEqual(item, 'hacked')                                    # only status and notes are writable
        self.assertEqual(self.ui('PATCH', 'inspection_items/1', {'status': 'MAYBE'})[0], 400)
        self.assertEqual(self.ui('PATCH', 'inspection_items/1', {'status': 'PENDING'})[0], 200)   # reset: no checked date
        self.assertEqual(self.sql('SELECT status, checked_date FROM inspection_items WHERE id=1')[0], ('PENDING', None))
        self.ui('PATCH', 'inspection_items/1', {'status': 'OK'})                                   # back to the state the test continues with
        st, r = self.ui('POST', 'listing_events', {'listing_id': CAR_A, 'text': 'Small dent on the rear door.'})
        self.assertEqual(st, 201)
        kind, src = self.sql('SELECT kind, source_id FROM listing_events WHERE id=?', (r['id'],))[0]
        self.assertEqual(kind, 'viewing')
        self.assertEqual(self.sql('SELECT source_type FROM sources WHERE id=?', (src,))[0][0], 'user_reported')
        self.assertEqual(self.ui('POST', 'inspection_items', {'listing_id': CAR_A, 'item': 'Check the spare wheel'})[0], 201)
        self.assertEqual(self.ui('POST', f'media/{CAR_A}', raw=b'\xff\xd8\xff\xe0' + b'v' * 50, ctype='image/jpeg')[0], 201)
        self.assertEqual(self.ui('POST', 'listings', {'price_eur': 1})[0], 404)   # the PIN cannot write anything else
        self.assertEqual(self.req('PATCH', f'/api/agent/listings/{CAR_A}', {'verdict': 'x'}, token='123456')[0], 401)
        self.assertEqual(self.units()[CAR_A]['metrics']['inspection'], 0)

    # --- accounts ---
    def test_login_session_logout_and_lockout(self):
        self.assertEqual(self.req('GET', '/api/tco', token=None)[0], 401)
        self.assertEqual(self.req('GET', '/api/auth/me', token=None)[0], 401)
        self.assertEqual(self.login(password='wrong')[0], 401)
        st, cookie = self.login()
        self.assertEqual(st, 200)
        st, me = self.req('GET', '/api/auth/me', token=None, cookie=cookie)
        self.assertEqual((st, me['username'], me['role']), (200, 'admin', 'admin'))
        self.assertEqual(self.req('GET', '/api/tco', token=None, cookie=cookie)[0], 200)
        self.assertEqual(self.req('GET', '/api/tco', token=None, cookie='forged')[0], 401)
        self.assertEqual(self.req('POST', '/api/auth/logout', {}, token=None, cookie=cookie)[0], 200)
        self.assertEqual(self.req('GET', '/api/tco', token=None, cookie=cookie)[0], 401)
        for _ in range(auth.LOGIN_MAX_FAILS):
            self.login(password='wrong')
        self.assertEqual(self.login()[0], 429)                                # this client is locked, even with the right password
        self.assertEqual(self.sql('SELECT count(*) FROM sessions')[0][0], 0)
        self.assertEqual(len(auth.FAILS), 1)                                  # keyed by client, not by the names tried
        auth.FAILS['127.0.0.1'].update(until=0.0, last=0.0)                   # the lock expired long ago: purged on the next call
        self.assertEqual(self.login()[0], 200)
        self.assertNotIn('127.0.0.1', auth.FAILS)

    def test_json_body_size_is_capped(self):
        r = urllib.request.Request(self.base + '/api/auth/login', b'{}', {'Content-Type': 'application/json', 'Content-Length': str(server.MAX_JSON_BYTES + 1)}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(r)
        self.assertEqual(cm.exception.code, 400)

    def test_password_change_and_agent_token(self):
        st, cookie = self.login()
        self.assertEqual(self.req('POST', '/api/account/password', {'old': 'nope', 'new': 'another password'}, token=None, cookie=cookie)[0], 401)
        self.assertEqual(self.req('POST', '/api/account/password', {'old': PASSWORD, 'new': 'short'}, token=None, cookie=cookie)[0], 400)
        self.assertEqual(self.req('POST', '/api/account/password', {'old': PASSWORD, 'new': 'another password'}, token=None, cookie=cookie)[0], 200)
        self.assertEqual(self.login()[0], 401)
        self.assertEqual(self.login(password='another password')[0], 200)
        st, t = self.req('POST', '/api/account/token', {}, token=None, cookie=cookie)
        self.assertEqual(st, 201)
        self.assertEqual(self.agent('GET', 'schema')[0], 401)                 # the old token is dead
        self.assertEqual(self.agent('GET', 'schema', token=t['token'])[0], 200)

    def test_invites_admin_and_account_isolation(self):
        st, cookie = self.login()
        st, u = self.req('POST', '/api/admin/users', {'username': 'maria'}, token=None, cookie=cookie)
        self.assertEqual((st, u['username']), (201, 'maria'))
        self.assertEqual(self.req('POST', '/api/admin/users', {'username': 'x y'}, token=None, cookie=cookie)[0], 400)
        self.assertEqual(self.req('POST', '/api/admin/users', {'username': 'maria'}, token=None, cookie=cookie)[0], 400)   # unique
        raw = u['invite'].rsplit('/', 1)[1]
        self.assertEqual(self.req('GET', f'/api/auth/invite/{raw}', token=None)[1]['username'], 'maria')
        self.assertEqual(self.req('POST', f'/api/auth/invite/{raw}', {'password': 'short'}, token=None)[0], 400)
        st, me = self.req('POST', f'/api/auth/invite/{raw}', {'password': 'marias password'}, token=None)
        self.assertEqual((st, me['username']), (201, 'maria'))
        self.assertEqual(self.req('GET', f'/api/auth/invite/{raw}', token=None)[0], 404)   # one-time
        st, c2 = self.login('maria', 'marias password')
        self.assertEqual(st, 200)
        self.assertEqual(self.req('GET', '/api/admin/users', token=None, cookie=c2)[0], 401)   # not an admin
        self.assertEqual(len(self.req('GET', '/api/admin/users', token=None, cookie=cookie)[1]), 2)
        # maria sees nothing of the admin's data and cannot touch it
        self.assertEqual(self.req('POST', '/api/account/token', {}, token=None, cookie=c2)[0], 403)   # agent tokens: admins only (#130)
        t2 = c2
        self.assertEqual(self.req('GET', '/api/tco', token=None, cookie=t2)[1]['listings'], [])
        self.assertEqual(self.req('GET', '/api/models', token=None, cookie=t2)[1]['makes'], [])
        self.assertEqual(self.req('GET', f'/api/listings/{CAR_A}', token=None, cookie=t2)[0], 404)
        self.assertEqual(self.req('GET', f'/api/vehicles/{V_A}', token=None, cookie=t2)[0], 404)
        self.assertEqual(self.agent('PATCH', f'listings/{CAR_A}', {'verdict': 'mine now'}, token=None, cookie=t2)[0], 403)  # listings: the worker's
        self.assertEqual(self.agent('POST', 'listing_events', {'listing_id': CAR_A, 'event_date': '2026-11-04', 'kind': 'found', 'text': 'x'}, token=None, cookie=t2)[0], 400)
        self.assertEqual(self.agent('POST', 'sources', {'title': 's', 'owner_id': 1}, token=None, cookie=t2)[0], 400)
        st, m = self.upload(b'\xff\xd8\xff\xe0' + b'p' * 20)
        self.assertEqual(self.req('GET', '/media/' + self.req('GET', f'/api/listings/{CAR_A}')[1]['media'][0]['file_path'], token=None, cookie=t2)[0], 404)
        # research and listings are written by the shared worker only (issue #109): her own token gets 403
        for table, row in (('generations', {'make': 'Gamma', 'model': 'Van', 'name': 'I'}), ('engines', {'code': 'GV20'}),
                           ('vehicles', {'generation_id': G1, 'engine_id': E_A}), ('maintenance_items', {'engine_id': E_A, 'item': 'x', 'schedule': 'ITEM', 'source_id': SRC_GUIDE}),
                           ('listings', {'vehicle_id': V_A, 'source_id': SRC_LISTING, 'listing_id': 'steal'}), ('sources', {'title': 's', 'engine_id': E_A})):
            self.assertEqual(self.agent('POST', table, row, token=None, cookie=t2)[0], 403, table)
        self.assertEqual(self.agent('POST', 'sources', {'title': 'Her own note'}, token=None, cookie=t2)[0], 201)   # a level-free source of her own
        # acting for an account needs an admin token, and covers reads and agent writes only
        H = {'X-Carlos-Account': '2'}
        self.assertEqual(self.req('GET', '/api/tco', token=None, cookie=t2, headers={'X-Carlos-Account': '1'})[0], 403)
        self.assertEqual(self.req('POST', '/api/parameters', {'annual_km': 1}, headers=H)[0], 403)
        self.assertEqual(self.req('GET', '/api/tco', headers={'X-Carlos-Account': '99'})[0], 400)
        # the worker (admin acting for maria) resolves a known HSN/TSN to the catalogue variant and links it to her
        st, r = self.agent('POST', 'vehicles', {'generation_id': G1, 'engine_id': E_A, 'hsn': '1111', 'tsn': 'aaa'}, headers=H)
        self.assertEqual((st, r), (200, {'table': 'vehicles', 'id': V_A, 'existing': True}))
        st, va = self.req('GET', f'/api/vehicles/{V_A}', token=None, cookie=t2)
        self.assertEqual(st, 200)
        self.assertTrue(va['maintenance_items'] and va['reliability_items'])                         # shared research
        self.assertEqual([r['premium_status'] for r in va['insurance_data']], [])                    # not the admin's quote
        self.assertNotIn(SRC_LISTING, [x['id'] for x in va['sources']])
        self.assertEqual([l['id'] for l in va['listings']], [])                                       # not the admin's car
        # ... and writes her listing: it belongs to her, links its variant, and the change log names the worker
        st, src = self.agent('POST', 'sources', {'title': 'Her listing', 'source_type': 'listing'}, headers=H)
        st, l = self.agent('POST', 'listings', {'vehicle_id': V_B, 'source_id': src['id'], 'platform': 'Test', 'listing_id': 'M1', 'price_eur': 4000}, headers=H)
        self.assertEqual(st, 201)
        self.assertEqual(self.sql('SELECT owner_id FROM listings WHERE id=?', (l['id'],))[0][0], 2)
        self.assertEqual(self.sql('SELECT user_id FROM change_log ORDER BY id DESC LIMIT 1')[0][0], 1)
        self.assertEqual(self.sql('SELECT count(*) FROM catalogue_links WHERE owner_id=2 AND vehicle_id=?', (V_B,))[0][0], 1)
        mine = self.req('GET', '/api/tco', token=None, cookie=t2)[1]['listings']
        self.assertEqual([(x['make'], x['annual_insurance']) for x in mine], [('Beta', None)])        # the admin's quote stays his
        self.assertNotIn(l['id'], self.units())
        self.assertEqual(self.req('GET', f'/api/listings/{l["id"]}')[0], 404)
        # a correction to the shared engine reaches her dossier too
        self.assertEqual(self.agent('PATCH', f'engines/{E_B}', {'code': 'BC12X'})[0], 200)
        self.assertIn('BC12X', ''.join(f.read_text() for f in (config.MD_DIR / '2').glob('*.md')))
        self.assertEqual(self.req('POST', '/api/parameters', {'annual_km': 9000}, token=None, cookie=t2)[1]['annual_km'], 9000)
        self.assertEqual(self.req('GET', '/api/parameters')[1]['annual_km'], 15000)
        self.assertTrue((config.MD_DIR / '1' / 'Alpha-Hatch-Test-A1.md').exists())
        # deactivation ends the sessions and the token
        self.assertEqual(self.req('PATCH', '/api/admin/users/2', {'is_active': 0}, token=None, cookie=cookie)[1]['is_active'], 0)
        self.assertEqual(self.req('GET', '/api/tco', token=None, cookie=c2)[0], 401)
        self.assertEqual(self.req('GET', '/api/tco', token=None, cookie=t2)[0], 401)
        self.assertEqual(self.req('PATCH', '/api/admin/users/1', {'is_active': 0}, token=None, cookie=cookie)[0], 400)
        self.assertEqual(self.req('PATCH', '/api/admin/users/1', {'role': 'user'}, token=None, cookie=cookie)[0], 400)   # no self-demotion
        self.assertEqual(self.req('POST', '/api/admin/users/2/invite', {}, token=None, cookie=cookie)[0], 201)

    def test_bootstrap_prints_invite_and_sets_admin_token(self):
        self.sql_write('UPDATE users SET password_hash=NULL, api_token_hash=NULL')
        env, config.ENV = config.ENV, Path(self.tmp.name) / '.env'
        try:
            os.environ['AGENT_TOKEN'] = 'env-token'
            import io, contextlib
            out = io.StringIO()
            c = sqlite3.connect(config.DB); c.row_factory = sqlite3.Row
            with contextlib.redirect_stdout(out):
                server.bootstrap(c)
            c.close()
        finally:
            config.ENV = env; os.environ.pop('AGENT_TOKEN', None)
        self.assertEqual(self.agent('GET', 'schema', token='env-token')[0], 200)
        raw = out.getvalue().strip().rsplit('/', 1)[1]
        self.assertEqual(self.req('GET', f'/api/auth/invite/{raw}', token=None)[1]['username'], 'admin')

    def test_load_secret_fills_template(self):
        env, config.ENV = config.ENV, Path(self.tmp.name) / '.env'
        try:
            shutil.copy(config.ROOT / '.env.example', config.ENV)
            os.environ.pop('UI_PIN', None)
            self.assertEqual(server.load_secret('UI_PIN', lambda: '424242'), '424242')
            text = config.ENV.read_text()
            self.assertEqual(text.count('UI_PIN='), 1)                         # filled in place, not duplicated
            self.assertIn('UI_PIN=424242', text)
            self.assertIn('# AGENT_TOKEN', text)                              # comments kept
            self.assertEqual(server.load_secret('UI_PIN', lambda: 'other'), '424242')   # stable on restart
            self.assertEqual(oct(os.stat(config.ENV).st_mode & 0o777), '0o600')
        finally:
            config.ENV = env


if __name__ == '__main__':
    unittest.main()
