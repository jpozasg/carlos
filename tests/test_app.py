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

    def req(self, method, path, body=None, token=TOKEN, ctype='application/json', cookie=None, raw=None):
        """Requests carry the admin's agent token unless told otherwise (token=None: anonymous; cookie: a session)."""
        headers = {'Content-Type': ctype}
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

    def agent(self, method, path, body=None, token=TOKEN):
        return self.req(method, '/api/agent/' + path, body, token)

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
        self.assertTrue(any(e['table'] == 'repair_risks' for e in a['evidence']))
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

    def test_one_consumption_source_for_all_cars(self):
        self.sql_write('DELETE FROM observations WHERE vehicle_id=? AND metric=?', (V_REF, config.PRIMARY_CONSUMPTION))
        self.assertIsNone(self.units()[REF]['consumption'])                   # the owner's figure is a cross-check only
        self.agent('POST', 'observations', {'vehicle_id': V_REF, 'category': 'consumption', 'metric': config.PRIMARY_CONSUMPTION,
                                            'value_num': 8.0, 'status': 'PRIMARY', 'source_id': SRC_GUIDE})
        u = self.units()[REF]
        self.assertEqual((u['consumption'], u['consumption_metric']), (8.0, config.PRIMARY_CONSUMPTION))

    def sql_write(self, q, args=()):
        c = sqlite3.connect(config.DB); c.execute(q, args); c.commit(); c.close()

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
        # the reference car's insurance evidence is the premium the cost uses (USER DATA), not the newer quote
        ev = [e for e in self.units()[REF]['evidence'] if e['table'] == 'insurance_data']
        self.assertEqual([e['status'] for e in ev], ['USER DATA'])

    def test_todo(self):
        d = self.agent('GET', 'todo')[1]
        lst = {x['listing_id']: x['todo'] for x in d['listings']}
        mod = {x['vehicle_id']: x['todo'] for x in d['models']}
        self.assertIn('no verdict', lst[CAR_A])
        self.assertNotIn('no verdict', lst[REF])
        self.assertIn('no listing capture (listing_snapshots)', lst[CAR_B])
        self.assertTrue(any(t.startswith('not checked for over') for t in lst[CAR_B]))
        self.assertIn('tax not from the BMF Kfz-Steuer-Rechner', mod[V_B])
        self.assertIn('annual tax missing', mod[V_B2])
        self.assertIn('HSN/TSN missing (vehicles.hsn, vehicles.tsn)', mod[V_B2])
        self.assertEqual(mod[V_A], [f'no weak points researched for part {x} (the same four sources as for every car)' for x in ('GEARBOX', 'ELECTRICS')])
        old = {'vehicle_id': V_A, 'premium_status': 'QUOTE', 'annual_premium_eur': 800, 'quote_date': '2026-01-01', 'source_id': SRC_QUOTE}
        self.agent('POST', 'insurance_data', old)
        self.assertIn(f'insurance quote older than {config.QUOTE_MAX_AGE_DAYS} days: request a new quote',
                      {x['vehicle_id']: x['todo'] for x in self.agent('GET', 'todo')[1]['models']}[V_A])
        self.agent('PATCH', f'listings/{CAR_A}', {'verdict': 'Strong candidate'})
        self.assertNotIn('no verdict', {x['listing_id']: x['todo'] for x in self.agent('GET', 'todo')[1]['listings']}[CAR_A])
        self.agent('PATCH', f'listings/{CAR_B}', {'listing_status': 'WITHDRAWN'})
        self.assertNotIn(CAR_B, {x['listing_id'] for x in self.agent('GET', 'todo')[1]['listings']})

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
        self.assertEqual(costs.reliability([], {})[0], None)
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
        t2 = self.req('POST', '/api/account/token', {}, token=None, cookie=c2)[1]['token']
        self.assertEqual(self.req('GET', '/api/tco', token=t2)[1]['listings'], [])
        self.assertEqual(self.req('GET', '/api/models', token=t2)[1]['makes'], [])
        self.assertEqual(self.req('GET', f'/api/listings/{CAR_A}', token=t2)[0], 404)
        self.assertEqual(self.req('GET', f'/api/vehicles/{V_A}', token=t2)[0], 404)
        self.assertEqual(self.agent('PATCH', f'listings/{CAR_A}', {'verdict': 'mine now'}, token=t2)[0], 404)
        self.assertEqual(self.agent('POST', 'listing_events', {'listing_id': CAR_A, 'event_date': '2026-11-04', 'kind': 'found', 'text': 'x'}, token=t2)[0], 400)
        self.assertEqual(self.agent('POST', 'maintenance_items', {'engine_id': E_A, 'item': 'x', 'schedule': 'ITEM', 'source_id': SRC_GUIDE}, token=t2)[0], 400)
        self.assertEqual(self.agent('POST', 'vehicles', {'generation_id': G1, 'engine_id': E_A}, token=t2)[0], 400)
        self.assertEqual(self.agent('POST', 'listings', {'vehicle_id': V_A, 'source_id': SRC_LISTING, 'listing_id': 'steal'}, token=t2)[0], 400)
        self.assertEqual(self.agent('POST', 'sources', {'title': 's', 'owner_id': 1}, token=t2)[0], 400)
        st, m = self.upload(b'\xff\xd8\xff\xe0' + b'p' * 20)
        self.assertEqual(self.req('GET', '/media/' + self.req('GET', f'/api/listings/{CAR_A}')[1]['media'][0]['file_path'], token=t2)[0], 404)
        # maria builds her own data; the admin does not see it, and both have their own parameters and dossiers
        st, g = self.agent('POST', 'generations', {'make': 'Gamma', 'model': 'Van', 'name': 'I'}, token=t2)
        st, e = self.agent('POST', 'engines', {'code': 'GV20'}, token=t2)
        st, v = self.agent('POST', 'vehicles', {'generation_id': g['id'], 'engine_id': e['id']}, token=t2)
        st, src = self.agent('POST', 'sources', {'title': 'Her listing'}, token=t2)
        st, l = self.agent('POST', 'listings', {'vehicle_id': v['id'], 'source_id': src['id'], 'listing_id': 'M1', 'price_eur': 4000}, token=t2)
        self.assertEqual(st, 201)
        self.assertEqual([x['make'] for x in self.req('GET', '/api/tco', token=t2)[1]['listings']], ['Gamma'])
        self.assertNotIn(l['id'], self.units())
        self.assertEqual(self.req('GET', f'/api/listings/{l["id"]}')[0], 404)
        self.assertEqual(self.req('POST', '/api/parameters', {'annual_km': 9000}, token=t2)[1]['annual_km'], 9000)
        self.assertEqual(self.req('GET', '/api/parameters')[1]['annual_km'], 15000)
        self.assertTrue((config.MD_DIR / '2' / 'Gamma-Van-X-M1.md').exists())
        self.assertTrue((config.MD_DIR / '1' / 'Alpha-Hatch-Test-A1.md').exists())
        self.assertEqual(self.sql('SELECT user_id FROM change_log ORDER BY id DESC LIMIT 1')[0][0], 2)
        # deactivation ends the sessions and the token
        self.assertEqual(self.req('PATCH', '/api/admin/users/2', {'is_active': 0}, token=None, cookie=cookie)[1]['is_active'], 0)
        self.assertEqual(self.req('GET', '/api/tco', token=None, cookie=c2)[0], 401)
        self.assertEqual(self.req('GET', '/api/tco', token=t2)[0], 401)
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
