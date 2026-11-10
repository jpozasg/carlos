"""API, calculation and migration tests on a synthetic database (tests/fixture.py), never on real data.
Run: python -m unittest -v"""
import datetime, json, os, shutil, sqlite3, tempfile, threading, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock
import migrate
from carlos import auth, config, server, costs, ranking, research_units
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
        self.gaps = []   # the done gate's grading (#218) is stubbed: the fixture cars are not fully researched
        patcher = mock.patch.object(server.Handler, 'missing_items', lambda h, owner, lid: list(self.gaps))
        patcher.start(); self.addCleanup(patcher.stop)
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

    def test_migrate_cli_defaults_to_the_data_directory(self):
        """#158: `python migrate.py` without a path migrates CARLOS_DATA's database, never ./cars.sqlite at the repo root;
        --schema refuses a missing database instead of dumping an empty one."""
        import subprocess, sys
        root = Path(migrate.__file__).resolve().parent
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, 'CARLOS_DATA': d}
            r = subprocess.run([sys.executable, 'migrate.py'], cwd=root, env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((Path(d) / 'cars.sqlite').exists())
            self.assertFalse((root / 'cars.sqlite').exists())
            r = subprocess.run([sys.executable, 'migrate.py', '--schema', str(Path(d) / 'missing.sqlite')], cwd=root, env=env, capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertFalse((Path(d) / 'missing.sqlite').exists())

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

    def test_target_levels_174(self):
        """Target design step 1 (#174): families, gearboxes, body styles and options are catalogue levels; faults attach to
        exactly one level with a valid curve; a maintenance row without a level is a global default; an account sees a
        level's knowledge only through its own listings."""
        from carlos import db
        fam = self.agent('POST', 'engine_families', {'name': 'AM'})[1]['id']
        self.assertEqual(self.agent('PATCH', f'engines/{E_A}', {'family_id': fam})[0], 200)
        gf = self.agent('POST', 'gearbox_families', {'name': 'DX7'})[1]['id']
        gb = self.agent('POST', 'gearboxes', {'code': '0XX', 'family_id': gf, 'type': 'DCT', 'gears': 7})[1]['id']
        self.assertEqual(self.agent('POST', 'gearboxes', {'code': '0YY', 'type': 'ROBOT'})[0], 400)          # fixed code
        self.assertEqual(self.agent('PATCH', f'vehicles/{V_A}', {'gearbox_id': gb})[0], 200)
        self.sql_write('UPDATE reliability_items SET archived=1')   # the fixture's weak points would conflict (#254)
        fault = {'component': 'Timing chain', 'component_code': 'TIMING_CHAIN', 'part': 'ENGINE', 'consequence': 'ENGINE_DAMAGE', 'existence': 'REPORTED',
                 'curve_km': [[100000, 0.1], [200000, 0.4]], 'probability_basis': 'ESTIMATE', 'parts_eur': 400, 'labor_eur': 600,
                 'source_id': SRC_GUIDE}
        st, f = self.agent('POST', 'faults', {**fault, 'engine_family_id': fam})
        self.assertEqual(st, 201, f)
        self.assertEqual(self.agent('POST', 'faults', {**fault, 'engine_family_id': fam, 'gearbox_id': gb})[0], 400)  # two levels
        self.assertEqual(self.agent('POST', 'faults', {**fault, 'gearbox_id': gb, 'curve_km': [[200000, 0.4], [100000, 0.1]]})[0], 400)
        self.assertEqual(self.agent('POST', 'faults', {**fault, 'component': 'Gearbox whine', 'gearbox_id': gb, 'usage_multiplier': 1.5})[0], 400)  # needs a source
        self.assertEqual(self.agent('POST', 'maintenance_items', {'item': 'HU', 'job': 'HU', 'interval_months': 24, 'schedule': 'ITEM',
                                                                  'reference_cost_eur': 140, 'status': 'OFFICIAL FEE LEVEL',
                                                                  'source_id': SRC_GUIDE})[0], 201)  # global default
        uid, _ = self.second_account()
        c = db.connect()
        try:
            auth.scope(c, uid)
            seen = lambda t: c.execute(f'SELECT count(*) FROM {t}').fetchone()[0]
            self.assertEqual((seen('faults'), seen('engine_families'), seen('gearboxes')), (0, 0, 0))   # no listing, nothing seen
            self.assertEqual(c.execute("SELECT count(*) FROM maintenance_items WHERE item='HU' AND engine_id IS NULL AND generation_id IS NULL AND vehicle_id IS NULL").fetchone()[0], 1)
        finally:
            c.close()
        H = {'X-Carlos-Account': str(uid)}
        src = self.agent('POST', 'sources', {'title': 'Her listing', 'source_type': 'listing'}, headers=H)[1]
        st, _ = self.agent('POST', 'listings', {'vehicle_id': V_A, 'price_eur': 5000, 'source_id': src['id']}, headers=H)
        self.assertEqual(st, 201)
        c = db.connect()
        try:
            auth.scope(c, uid)
            self.assertEqual([r[0] for r in c.execute('SELECT id FROM faults')], [f['id']])        # through V_A → engine → family
            self.assertEqual(c.execute('SELECT count(*) FROM gearbox_families').fetchone()[0], 1)
            v = db.variants(c, 'WHERE v.id=?', (V_A,))[0]
            self.assertEqual((v['engine_family_id'], v['gearbox_family_id'], v['gearbox_type']), (fam, gf, 'DCT'))
            self.assertEqual(len(db.for_variant(db.scoped(c, 'faults'), v)), 1)
        finally:
            c.close()

    def test_review_flags_168(self):
        """#168: a flag lives on its level and is cleared only when two different workers resolve it with the same
        conclusion; a CONFIRMED review or a lone resolution keeps it open; it cannot be cleared by hand; every review is
        kept; the variant and every inheriting listing show it."""
        st, f = self.agent('POST', 'review_flags', {'engine_id': E_A, 'kind': 'SOURCES_DISAGREE', 'what': 'Chain life',
                                                    'why': 'ADAC and the guide disagree'})
        self.assertEqual(st, 201)
        rev = lambda w, o, con: self.agent('POST', 'flag_reviews', {'flag_id': f['id'], 'worker': w, 'outcome': o,
                                                                    'conclusion': con, 'finding': 'checked'})[0]
        status = lambda: next(x for x in self.req('GET', f'/api/vehicles/{V_A}')[1]['review_flags'] if x['id'] == f['id'])['status']
        self.assertEqual(rev('run 1', 'RESOLVED', 'guide outdated'), 201)
        self.assertEqual(rev('run 1', 'RESOLVED', 'guide outdated'), 400)                 # the same worker twice: not independent
        self.assertEqual(rev('run 2', 'CONFIRMED', 'guide outdated'), 201)
        self.assertEqual(rev('run 3', 'RESOLVED', 'ADAC outdated'), 201)                  # a different conclusion
        self.assertEqual(status(), 'OPEN')
        self.assertEqual(self.agent('PATCH', f"review_flags/{f['id']}", {'status': 'CLEARED'})[0], 400)
        a = self.req('GET', f'/api/listings/{CAR_A}')[1]
        self.assertEqual([x['id'] for x in a['review_flags']], [f['id']])                 # inherited by the listing
        self.assertEqual(len(a['review_flags'][0]['reviews']), 3)
        self.assertEqual(rev('run 4', 'RESOLVED', 'guide outdated'), 201)
        self.assertEqual(status(), 'CLEARED')
        # what the Models page shows for the new levels; reliability_stats is gone (#353): not writable
        self.agent('POST', 'faults', {'generation_id': G1, 'component': 'Trim', 'component_code': 'BODY_FITTINGS', 'part': 'CHASSIS', 'consequence': 'COSMETIC',
                                      'existence': 'CONFIRMED', 'frequency_band': 'rare', 'shape': 'RANDOM',
                                      'parts_eur': 50, 'source_id': SRC_GUIDE})
        v = self.req('GET', f'/api/vehicles/{V_A}')[1]
        self.assertEqual(([x['component'] for x in v['faults']], 'reliability_stats' in v, v['gearbox_family_name']), (['Trim'], False, None))
        self.assertNotEqual(self.agent('POST', 'reliability_stats', {'generation_id': G1, 'kind': 'TUEV', 'age_from': 6, 'age_to': 7,
                                                                     'value': 20, 'unit': '%', 'source_id': fx.SRC_HU})[0], 201)

    def test_fault_costs_174(self):
        """Step 2 (#174, method #168): a fault's expected cost is the conditional chance over the owner's km × its price; a
        documented fix switches to the fixed part's curve (or none); extended warranty pays its share; a band and shape
        give a curve continuing to the end limits; systemic needs a manufacturer trace, a forum source caps the band;
        the market model gives the end value; a level HU row overrides the global default; the listing's quote counts."""
        from carlos import costs
        curve = [[100000, 0.1], [200000, 0.4]]
        base = {'component': 'Chain', 'component_code': 'TIMING_CHAIN', 'part': 'ENGINE', 'consequence': 'ENGINE_DAMAGE', 'existence': 'CONFIRMED',
                'probability_basis': 'ESTIMATE', 'parts_eur': 400, 'labor_eur': 600, 'source_id': SRC_GUIDE, 'engine_id': E_A}
        f1 = self.agent('POST', 'faults', {**base, 'curve_km': curve})[1]['id']
        a = self.req('GET', f'/api/listings/{CAR_A}')[1]
        km, period = a['mileage_km'], a['period_km']
        plan = {x['id']: x for x in a['fault_plan']}
        self.assertEqual(plan[f1]['severity'], 'HIGH')                               # engine damage → HIGH, derived
        self.assertAlmostEqual(plan[f1]['expected_eur'], round(costs.conditional(curve, km, km + period, 300000) * 1000, 2), places=2)
        # extended warranty for the whole period pays half
        self.assertEqual(self.agent('PATCH', f'faults/{f1}', {'warranty_km': 900000, 'warranty_years': 40, 'warranty_share': 0.5})[0], 200)
        half = {x['id']: x for x in self.req('GET', f'/api/listings/{CAR_A}')[1]['fault_plan']}[f1]['expected_eur']
        self.assertAlmostEqual(half, plan[f1]['expected_eur'] / 2, delta=0.02)
        self.assertEqual(self.agent('PATCH', f'faults/{f1}', {'warranty_share': None, 'warranty_km': None, 'warranty_years': None})[0], 200)
        # documented fix at today's km without a fixed-part curve: no risk left; with one: that curve from the repair
        src = self.agent('POST', 'sources', {'title': 'Invoice', 'source_type': 'listing'})[1]['id']
        self.assertEqual(self.agent('POST', 'listing_history', {'listing_id': CAR_A, 'fault_id': f1, 'item': 'New chain', 'status': 'DONE',
                                                                'km': km, 'evidence': 'DOCUMENTED', 'source_id': src})[0], 201)
        fixed = lambda: {x['id']: x for x in self.req('GET', f'/api/listings/{CAR_A}')[1]['fault_plan']}[f1]
        self.assertEqual(fixed()['expected_eur'], 0)
        f2 = self.agent('POST', 'faults', {**base, 'component': 'Revised chain', 'distinct_of': [f1], 'notes': 'the fixed design after the repair', 'curve_km': [[200000, 0.05]]})[1]['id']
        self.assertEqual(self.agent('PATCH', f'faults/{f1}', {'fixed_fault_id': f2})[0], 200)
        self.assertAlmostEqual(fixed()['probability'], round(costs.conditional([[200000, 0.05]], 0, period, 300000), 4), places=4)
        # shapes: every shape gives a rising curve that reaches the end limit
        for shape in ('WEAR_KM', 'AGE', 'WINDOW', 'RANDOM'):
            km_c, age_c = costs.shape_curves({'frequency_band': 'common', 'shape': shape})
            pts = km_c or age_c
            self.assertEqual(pts[-1][0], 300000 if km_c else 20, shape)
            self.assertTrue(all(b[1] >= a_[1] for a_, b in zip(pts, pts[1:])), shape)
        self.assertEqual(self.agent('POST', 'faults', {**base, 'frequency_band': 'systemic', 'shape': 'WEAR_KM'})[0], 400)  # no trace
        forum = self.agent('POST', 'sources', {'title': 'Forum', 'quality': 'D', 'engine_id': E_A})[1]['id']
        self.assertEqual(self.agent('POST', 'faults', {**base, 'frequency_band': 'widespread', 'shape': 'WEAR_KM', 'source_id': forum})[0], 400)
        st, f3 = self.agent('POST', 'faults', {**base, 'component': 'Oil pump drive', 'component_code': 'ENGINE_INTERNALS', 'frequency_band': 'common', 'shape': 'RANDOM', 'source_id': forum})
        self.assertEqual(st, 201)
        self.assertGreater({x['id']: x for x in self.req('GET', f'/api/listings/{CAR_A}')[1]['fault_plan']}[f3['id']]['probability'], 0)
        # market model: depreciation = price − the end value at the owner's end age and km, less the private-sale discount
        m = {'generation_id': G1, 'engine_id': E_A, 'value_ref_eur': 6000, 'ref_age_years': 10, 'ref_km': 150000, 'rate_year': 0.08,
             'rate_10k_km': 0.02, 'band_counts': [5, 6, 7], 'sample_date': datetime.date.today().isoformat(), 'source_id': SRC_GUIDE}
        self.assertEqual(self.agent('POST', 'market_models', m)[0], 201)
        a = self.req('GET', f'/api/listings/{CAR_A}')[1]
        years = a['period_months'] / 12
        end = round(costs.market_value(m, a['metrics']['age'] + years, km + period) * (1 - config.PRIVATE_SALE_DISCOUNT), -1)
        self.assertAlmostEqual(a['components']['depreciation'], a['price_eur'] - end, places=2)
        # a global HU default is overridden by the generation's HU row; the listing's own quote is the insurance
        self.assertEqual(self.agent('POST', 'maintenance_items', {'item': 'HU (global)', 'job': 'HU', 'interval_months': 24, 'schedule': 'ITEM',
                                                                  'reference_cost_eur': 999, 'status': 'ESTIMATED', 'source_id': fx.SRC_HU})[0], 201)
        self.assertNotIn('HU (global)', [x['item'] for x in self.req('GET', f'/api/listings/{CAR_A}')[1]['maintenance_plan']])
        self.assertEqual(self.agent('POST', 'listing_quotes', {'listing_id': CAR_A, 'annual_premium_eur': 777, 'premium_status': 'QUOTE',
                                                               'quote_date': datetime.date.today().isoformat(), 'source_id': SRC_QUOTE})[0], 201)
        self.assertEqual(self.req('GET', f'/api/listings/{CAR_A}')[1]['annual_insurance'], 777)

    def test_scoped_rows_need_exactly_one_level(self):
        base = {'item': 'x', 'interval_km': 10000, 'schedule': 'ITEM', 'diy': 0, 'reference_cost_eur': 10, 'status': 'ESTIMATED', 'source_id': SRC_GUIDE}
        self.assertEqual(self.agent('POST', 'repair_risks', {'component': 'x', 'km_from': 0, 'km_to': 1, 'probability': 0.1,
                                                            'source_id': SRC_GUIDE})[0], 400)                    # no level
        self.assertEqual(self.agent('POST', 'maintenance_items', base)[0], 201)        # no level: a global default (#174)
        self.assertEqual(self.agent('POST', 'maintenance_items', {**base, 'vehicle_id': V_A, 'engine_id': E_A})[0], 400)  # two levels
        st, r = self.agent('POST', 'maintenance_items', {**base, 'engine_id': E_A})
        self.assertEqual(st, 201)
        # re-scoping a row from the variant to its engine in one PATCH
        st, _ = self.agent('PATCH', f'maintenance_items/{r["id"]}', {'engine_id': None, 'vehicle_id': V_A})
        self.assertEqual(st, 200)
        self.assertEqual(self.agent('PATCH', f'maintenance_items/{r["id"]}', {'vehicle_id': None})[0], 200)       # zero levels = global (#174)
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
        self.assertIsNone(a['metrics']['reliability'])                         # no source rating yet: not scored, never 0 (#356)
        self.assertEqual((a['reliability_sources']['present'], a['reliability_sources']['missing']), (0, ['ENGINE', 'HU', 'BREAKDOWNS']))
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
        self.assertEqual(electricity_price({'home_charging': 'none', 'electricity_public_eur_kwh': 0.5}), (0.5 * (1 + config.EV_CHARGING_LOSS), []))   # losses on every kWh (#154)
        self.assertAlmostEqual(electricity_price({'home_charging': 'socket', 'home_charging_pct': 100, 'electricity_home_eur_kwh': 0.4})[0], 0.44 * (1 + config.EV_CHARGING_LOSS))   # the socket's extra over a wallbox, once
        self.assertAlmostEqual(electricity_price({'home_charging': 'wallbox', 'home_charging_pct': 50, 'electricity_home_eur_kwh': 0.4,
                                                  'electricity_public_eur_kwh': 0.6})[0], 0.5 * (1 + config.EV_CHARGING_LOSS))

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
        self.assertAlmostEqual(u['components']['fuel'], 16.0 * 40000 / 100 * 0.40 * (1 + config.EV_CHARGING_LOSS))
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

    def test_new_car_150(self):
        """A new car (issue #150): registered today for tax, age 0, its schedule starts at 0 with the first HU at 36 months,
        and a reliability part whose every source check is N/A is unknown, never a clean record. Since #165 (second-hand
        only) a capture refuses a new car; the costing stays for listings captured before."""
        from carlos.costs import due, is_new
        from carlos import research
        from capture_listing import validate
        cap = {'url': 'https://x.example/1', 'platform': 'mobile.de', 'captured_at': '2026-11-06', 'vehicle_id': 1, 'mileage_km': 0, 'price_eur': 22990}
        with self.assertRaises(ValueError):
            validate(cap)  # a new car is not captured any more (#165)
        validate({**cap, 'mileage_km': 0, 'listing': {'first_registration': '2024-03'}})  # a registered car with 0 km is used
        with self.assertRaises(ValueError):
            validate({**cap, 'price_eur': 0})  # a price is never 0
        self.assertTrue(is_new({'first_registration': None, 'mileage_km': 0}))
        self.assertFalse(is_new({'first_registration': '2025-01', 'mileage_km': 10}))
        self.assertFalse(is_new({'first_registration': None, 'mileage_km': None}))  # unknown is not new
        hu = {'id': 9, 'job': 'HU', 'interval_km': None, 'interval_months': 24}
        self.assertEqual([due(hu, 0, m, frozenset(), True) for m in (24, 36, 48, 60)], [0, 1, 1, 2])
        self.assertEqual(due(hu, 0, 48, frozenset()), 2.0)  # a used car: the expected share
        oil = {'id': 8, 'job': 'OIL_SERVICE', 'interval_km': 15000, 'interval_months': 12}
        self.assertEqual(due(oil, 40000, 30, frozenset(), True), 2)  # whole intervals from 0
        e, v, l = self.ev_listing('Petrol', listing_id='NEW1', mileage_km=0, first_registration=None, price_eur=22990)
        self.agent('POST', 'tax_data', {'vehicle_id': v['id'], 'annual_tax_eur': 40, 'status': 'VERIFIED', 'source_id': SRC_GUIDE,
                                        'registered_from': '2025-01'})
        u = self.units()[l['id']]
        self.assertAlmostEqual(u['components']['tax'], 40 * u['period_months'] / 12)  # the window covers a car registered today
        self.assertEqual(u['metrics']['age'], 0)
        gap = 'listing field missing: first_registration'
        todo = lambda: next(x for x in self.req('GET', '/api/agent/todo')[1]['listings'] if x['listing_id'] == l['id'])['todo']
        self.assertNotIn(gap, todo())  # a new car has no registration yet (#162)
        self.agent('PATCH', f"listings/{l['id']}", {'mileage_km': 5000})
        self.assertIn(gap, todo())  # a used car without it still gets the item
        items = [{'id': f'rel.CHASSIS.{s}', 'grade': 'ACCEPTED', 'na_only': s != 'guide'} for s in ('adac', 'tuev', 'guide')]
        self.assertNotIn('CHASSIS', research.known_parts(items))
        self.assertEqual(research.too_new_parts(items), ['CHASSIS'])
        self.assertIn('CHASSIS', research.known_parts(items, {'CHASSIS'}))  # a documented weak point is evidence
        self.assertIn('CHASSIS', research.known_parts([{**i, 'na_only': False} for i in items]))

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
        import capture_listing  # second-hand purchases only (#165): a capture never writes a lease
        cap = {'url': 'https://x', 'platform': 'p', 'captured_at': '2026-11-05', 'vehicle_id': v['id'], 'price_eur': 9000}
        for lease in ({'lease_monthly_eur': 224}, {'lease_kind': 'abo'}, {'lease_includes': 'insurance'}):
            with self.assertRaises(ValueError):
                capture_listing.validate({**cap, 'listing': lease})
        capture_listing.validate({**cap, 'listing': {'first_registration': '2020-01'}})

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
        # an ad with both offers is bought, whatever acquisition_mode is stored: second-hand purchases only (#165)
        e, v, l3 = self.ev_listing('Petrol', listing_id='LS3', lease_kind='km', lease_monthly_eur=224, lease_term_months=48)
        self.req('POST', '/api/parameters', {'acquisition_mode': 'lease'})
        x = self.units()[l3['id']]
        self.assertEqual(x['offer'], 'purchase')
        self.assertIsNotNone(x['offers']['lease'])

    def test_electric_research_contract_125(self):
        e, v, l = self.ev_listing()
        todo = lambda: next(m for m in self.agent('GET', 'todo')[1]['models'] if m['vehicle_id'] == v['id'])['todo']
        ids = lambda: {x.split()[1] for x in todo() if ' missing: ' in x}
        self.assertTrue({'eng.identity_ev', 'eng.hv_battery', 'eng.drive_coolant', 'eng.reduction_gear_oil', 'var.consumption'} <= ids())
        self.assertFalse({'eng.identity', 'eng.oil', 'eng.spark_plugs', 'eng.timing_belt', 'eng.coolant'} & ids())
        self.agent('PATCH', f"engines/{e['id']}", {'ac_charge_kw': 22})
        self.agent('POST', 'observations', {'vehicle_id': v['id'], 'category': 'consumption', 'metric': config.PRIMARY_CONSUMPTION_EV,
                                            'value_num': 16.5, 'unit': 'kWh/100 km', 'status': 'ESTIMATED', 'source_id': SRC_GUIDE})  # EVDB: no sample (#154)
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

    def test_view_as_account_142(self):
        """An admin's browser session views any account through the carlos_view cookie (pages and photos); non-admins
        cannot; settings stay closed while viewing; the change log lists writer and account."""
        uid2, c2 = self.second_account()
        st, admin = self.login()
        mine = self.req('GET', '/api/tco', token=None, cookie=admin)[1]['listings']
        self.assertTrue(mine)
        self.assertEqual(self.req('GET', '/api/tco', token=None, cookie=f'{admin}; carlos_view={uid2}')[1]['listings'], [])
        self.assertEqual(self.req('GET', '/api/tco', token=None, cookie=f'{c2}; carlos_view=1')[1]['listings'], [])  # ignored for her
        self.assertEqual(self.req('POST', '/api/parameters', {'annual_km': 9000}, token=None, cookie=f'{admin}; carlos_view={uid2}')[0], 403)
        self.assertEqual(self.req('GET', '/api/admin/users', token=None, cookie=f'{admin}; carlos_view={uid2}')[0], 200)  # admin pages: own view
        self.assertEqual(len(self.req('GET', '/api/tco', token=None, cookie=f'{admin}; carlos_view=999')[1]['listings']), len(mine))  # stale cookie
        self.agent('PATCH', f'listings/{CAR_A}', {'notes': 'seen by the admin'}); self.agent('PATCH', f'listings/{CAR_A}', {'notes': 'seen twice'})
        ch = self.req('GET', '/api/admin/changes?limit=5', token=None, cookie=admin)[1]
        self.assertEqual((ch[0]['table_name'], ch[0]['writer']), ('listings', 'admin'))
        self.assertEqual(self.req('GET', f'/api/admin/changes?before={ch[0]["id"]}&limit=1', token=None, cookie=admin)[1][0]['id'], ch[1]['id'])
        self.assertEqual(self.req('GET', '/api/admin/changes', token=None, cookie=c2)[0], 401)

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
        got = [self.req('POST', '/api/worker/claim', {'worker': f'desk{i}'})[1]['request'] for i in range(5)]  # one worker each: a worker's new claim releases its previous one (#160)
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

    def test_done_gate_218(self):
        """A DONE report with contract items missing goes back to the queue (attempts + 1), the third time FAILED; a complete
        listing is DONE; a usage-limit release is not an attempt."""
        self.req('POST', '/api/requests', {'url': 'https://www.example.com/car/9'})
        self.sql_write("UPDATE research_requests SET unit=NULL")   # a legacy single-run request: the whole listing is graded
        done = lambda rid: self.req('POST', f'/api/worker/requests/{rid}', {'status': 'DONE', 'listing_id': CAR_A, 'result': 'ok'})[1]
        claim = lambda: self.req('POST', '/api/worker/claim', {'worker': 'w'})[1]['request']
        self.gaps[:] = ['gen.hu', 'var.tyres']
        r = claim()
        self.assertEqual((r['attempts'], r['missing']), (0, []))
        d = done(r['id'])
        self.assertEqual((d['status'], d['attempts'], d['listing_id'], d['worker']), ('QUEUED', 1, CAR_A, None))
        r = claim()
        self.assertEqual((r['attempts'], r['missing']), (1, ['gen.hu', 'var.tyres']))
        self.req('POST', f'/api/worker/requests/{r["id"]}', {'status': 'QUEUED', 'result': 'usage limit'})   # not an attempt
        r = claim(); self.assertEqual(r['attempts'], 1)
        self.assertEqual(done(r['id'])['status'], 'QUEUED')
        d = done(claim()['id'])
        self.assertEqual((d['status'], d['attempts']), ('FAILED', 3))
        self.assertIn('gen.hu, var.tyres', d['result'])
        self.req('POST', '/api/requests', {'url': 'https://www.example.com/car/10'})
        self.gaps[:] = []
        self.assertEqual(done(claim()['id'])['status'], 'DONE')

    def test_duplicate_fault_guard_221(self):
        """The same fault filed twice is refused (409) when one catalogue variant would carry both; distinct_of overrides it with a reason."""
        from carlos import consistency
        self.assertTrue(consistency.same_fault('Timing chain stretch', 'timing-chain stretch N47'))
        self.assertFalse(consistency.same_fault('Timing chain', 'Timing belt'))
        self.sql_write('UPDATE reliability_items SET archived=1')   # the fixture's weak points would conflict (#254)
        base = {'component': 'Timing chain stretch', 'component_code': 'TIMING_CHAIN', 'part': 'ENGINE', 'consequence': 'ENGINE_DAMAGE', 'existence': 'REPORTED',
                'curve_km': [[100000, 0.1], [200000, 0.4]], 'probability_basis': 'ESTIMATE', 'parts_eur': 400, 'labor_eur': 600,
                'source_id': SRC_GUIDE}
        st, first = self.agent('POST', 'faults', {**base, 'engine_id': E_A, 'notes': 'guide'})
        self.assertEqual(st, 201, first)
        # the generation reaches the same cars as the engine (through a variant): refused, with the existing row
        st, r = self.agent('POST', 'faults', {**base, 'component': 'timing chain stretching', 'generation_id': G1})
        self.assertEqual((st, [x['id'] for x in r['conflict']], r['conflict'][0]['level']), (409, [first['id']], 'engine'))
        # a different fault and another part are not conflicts; an open-ended row overlaps any window
        self.assertEqual(self.agent('POST', 'faults', {**base, 'component': 'Turbo failure', 'component_code': 'TURBO', 'generation_id': G1})[0], 201)
        self.assertEqual(self.agent('POST', 'faults', {**base, 'applies_from': '2000-01', 'applies_to': '2001-01', 'engine_id': E_A})[0], 409)
        self.assertEqual(self.agent('POST', 'faults', {**base, 'part': 'CHASSIS', 'component_code': 'BRAKES', 'generation_id': G1})[0], 201)
        # distinct_of: needs every conflicting id and a reason of its own; the decision is written into notes
        dup = {**base, 'generation_id': G1}
        self.assertEqual(self.agent('POST', 'faults', {**dup, 'distinct_of': [999], 'notes': 'x'})[0], 400)
        self.assertEqual(self.agent('POST', 'faults', {**dup, 'distinct_of': [first['id']]})[0], 400)           # no reason
        self.assertEqual(self.agent('POST', 'faults', {**dup, 'distinct_of': [first['id']], 'notes': 'guide'})[0], 400)  # copy of the other notes
        st, ok = self.agent('POST', 'faults', {**dup, 'distinct_of': [first['id']], 'notes': 'the tensioner, not the chain'})
        self.assertEqual(st, 201, ok)
        self.assertEqual(self.sql('SELECT notes FROM faults WHERE id=?', (ok['id'],))[0][0], f"Distinct from fault #{first['id']}: the tensioner, not the chain")
        # archiving is always allowed
        self.assertEqual(self.agent('PATCH', f"faults/{first['id']}", {'archived': 1})[0], 200)

    def test_fault_component_codes_221(self):
        """Phase 3: component_code is controlled and per part; same_fault gates on it; the schema lists it; the back-fill is a dry run first."""
        from carlos import config, consistency
        self.sql_write('UPDATE reliability_items SET archived=1')
        base = {'component': 'Timing chain stretch', 'part': 'ENGINE', 'consequence': 'ENGINE_DAMAGE', 'existence': 'REPORTED',
                'curve_km': [[100000, 0.1], [200000, 0.4]], 'probability_basis': 'ESTIMATE', 'parts_eur': 400, 'labor_eur': 600,
                'source_id': SRC_GUIDE, 'engine_id': E_A}
        st, r = self.agent('POST', 'faults', base)                                                      # required on insert, with the suggestion
        self.assertEqual(st, 400); self.assertIn('probably TIMING_CHAIN', r['error'])
        self.assertEqual(self.agent('POST', 'faults', {**base, 'component_code': 'NOPE'})[0], 400)       # unknown code
        self.assertEqual(self.agent('POST', 'faults', {**base, 'component_code': 'BRAKES'})[0], 400)     # another part's code
        self.assertEqual(self.agent('POST', 'faults', {**base, 'component_code': 'OTHER'})[0], 400)      # OTHER needs notes
        st, f = self.agent('POST', 'faults', {**base, 'component_code': 'OTHER', 'notes': 'a bespoke cover'})
        self.assertEqual(st, 201, f)
        self.assertEqual(self.agent('PATCH', f"faults/{f['id']}", {'component_code': 'CAM_PHASER'})[0], 200)
        self.assertEqual(self.agent('PATCH', f"faults/{f['id']}", {'component_code': 'BRAKES'})[0], 400)
        self.sql_write('UPDATE faults SET component_code=NULL WHERE id=?', (f['id'],))
        self.assertEqual(self.agent('PATCH', f"faults/{f['id']}", {'notes': 'legacy row, no code'})[0], 200)  # NULL tolerated on PATCH
        sch = self.agent('GET', 'schema')[1]
        self.assertEqual({p: len(v) for p, v in sch['fault_components'].items()}, {'ENGINE': 16, 'GEARBOX': 11, 'CHASSIS': 13, 'ELECTRICS': 11})
        self.assertEqual(sum(len(v) for v in config.FAULT_COMPONENTS.values()), 51)
        self.assertTrue(set(config.FAULT_COMPONENT_CODES) <= set(sch['fixed_codes']['faults.component_code']))
        row = lambda n, c=None: {'component': n, 'component_code': c}
        self.assertIsNone(consistency.same_fault(row('Timing chain', 'TIMING_CHAIN'), row('Timing belt', 'TIMING_BELT')))
        self.assertIsNone(consistency.same_fault(row('Water pump', 'COOLING'), row('Expansion tank crack', 'COOLING')))
        self.assertTrue(consistency.same_fault(row('Water pump leak', 'COOLING'), row('Water pump', 'COOLING')))
        self.assertTrue(consistency.same_fault(row('Timing chain stretch'), row('timing-chain stretch N47', 'OTHER')))   # no code: wording
        # back-fill: dry run proposes, --apply writes only NULL rows, OTHER/unmatched stay NULL
        pilot = ['Timing belt in oil bath (wet belt)', 'Timing chain / tensioner cold-start rattle', 'VANOS solenoid valves',
                 'Oil consumption at high mileage', 'Oil pump', 'Coolant module (water pump and thermostat housing)', 'Ignition coils',
                 'Turbocharger wear', 'Diesel particulate filter (DPF)', 'Throttle body / idle control', 'Hybrid battery (NiMH) module or pack replacement']
        want = ['TIMING_BELT', 'TIMING_CHAIN', 'CAM_PHASER', 'OIL_CONSUMPTION', 'ENGINE_INTERNALS', 'COOLING', 'IGNITION', 'TURBO', 'EMISSIONS',
                'ENGINE_MANAGEMENT', 'HV_BATTERY']
        faults = [{'id': i, 'part': 'ENGINE', 'component': n, 'component_code': None} for i, n in enumerate(pilot)]
        faults += [{'id': 90, 'part': 'ENGINE', 'component': 'ENGINE'}, {'id': 91, 'part': 'ENGINE', 'component': 'Oil pump', 'component_code': 'OTHER'}]
        done = []
        ok, left = consistency.backfill_codes(faults)
        self.assertEqual(([c for *_, c in ok], [i for i, *_ in left], done), (want, [90], []))
        consistency.backfill_codes(faults, lambda i, c: done.append((i, c)))
        self.assertEqual(done, [(i, c) for (i, _, _, c) in ok])

    def test_checklist_covers_faults_and_recalls_223(self):
        """A fault with an inspection_action and a recall row each get a checklist item (linked by fault_id / recall_id); until then
        lst.checklist is MISSING, afterwards met; a fault without an action is not required; the helper is idempotent."""
        from capture_listing import checklist_items
        grade = lambda: {i['id']: i['grade'] for i in self.units()[CAR_A]['research']}['lst.checklist']
        fault = {'component': 'Water pump seal', 'component_code': 'COOLING', 'part': 'ENGINE', 'consequence': 'COST', 'existence': 'REPORTED', 'engine_id': E_A,
                 'curve_km': [[100000, 0.1], [200000, 0.4]], 'probability_basis': 'ESTIMATE', 'parts_eur': 100, 'labor_eur': 100, 'source_id': SRC_GUIDE}
        st, f = self.agent('POST', 'faults', {**fault, 'inspection_action': 'Look for coolant traces at the water pump'})
        self.assertEqual(st, 201, f)
        self.assertEqual(self.agent('POST', 'faults', {**fault, 'component': 'Oil cooler leak', 'component_code': 'OIL_LEAK'})[0], 201)   # no action: no item
        st, rc = self.agent('POST', 'recalls', {'engine_id': E_A, 'code': 'R1', 'defect': 'Wiring harness', 'safety': 1, 'source_id': SRC_GUIDE})
        self.assertEqual(st, 201, rc)
        self.assertEqual(grade(), 'MISSING')
        d = self.req('GET', f'/api/listings/{CAR_A}')[1]
        todo = checklist_items(d, d['inspection'])
        links = [l for _, l in todo]
        self.assertIn({'fault_id': f['id']}, links)
        self.assertIn({'recall_id': rc['id']}, links)
        self.assertEqual(len([l for l in links if 'fault_id' in l]), 1)
        for text, link in todo:
            self.assertEqual(self.agent('POST', 'inspection_items', {'listing_id': CAR_A, 'item': text, 'status': 'PENDING', **link})[0], 201)
        self.assertNotEqual(grade(), 'MISSING')
        d = self.req('GET', f'/api/listings/{CAR_A}')[1]
        self.assertEqual(checklist_items(d, d['inspection']), [])   # idempotent

    def test_duplicate_detector_221(self):
        """The read-only detector lists faults a variant would carry twice, not distinct-marked ones, and sibling-engine lift candidates."""
        from carlos import consistency
        ins = "INSERT INTO faults (component, part, consequence, existence, source_id, {}, notes) VALUES (?, 'ENGINE', 'COST', 'REPORTED', ?, ?, ?)"
        self.sql_write(ins.format('engine_id'), ('Timing chain stretch', SRC_GUIDE, E_A, None))
        self.sql_write(ins.format('generation_id'), ('Timing chain stretching', SRC_GUIDE, G1, None))
        self.sql_write(ins.format('generation_id'), ('Turbo failure', SRC_GUIDE, G1, None))
        with sqlite3.connect(config.DB) as c:
            c.row_factory = sqlite3.Row
            pairs, lifts = consistency.duplicates(c)
            self.assertEqual(list(pairs), [(1, 2)])
            c.execute("UPDATE faults SET notes='Distinct from fault #1: tensioner' WHERE id=2")
            self.assertEqual(consistency.duplicates(c)[0], {})
            self.assertIn('Double counted: 0', consistency.duplicates_report(c))

    def test_duplicate_guard_recalls_and_jobs_221(self):
        """The 409 also covers a recall with the same code and a maintenance job with the same job code on levels one car carries."""
        rc = {'code': 'R1', 'defect': 'Wiring', 'safety': 1, 'source_id': SRC_GUIDE}
        self.assertEqual(self.agent('POST', 'recalls', {**rc, 'engine_id': E_A})[0], 201)
        st, r = self.agent('POST', 'recalls', {**rc, 'code': ' r1 ', 'generation_id': G1})
        self.assertEqual((st, r['conflict'][0]['level']), (409, 'engine'))
        self.assertEqual(self.agent('POST', 'recalls', {**rc, 'code': 'R2', 'generation_id': G1})[0], 201)
        job = {'item': 'Oil', 'job': 'COOLANT', 'interval_km': 10000, 'schedule': 'ITEM', 'diy': 0, 'reference_cost_eur': 10, 'status': 'ESTIMATED', 'source_id': SRC_GUIDE}
        self.assertEqual(self.agent('POST', 'maintenance_items', {**job, 'engine_id': E_A})[0], 201)
        st, r = self.agent('POST', 'maintenance_items', {**job, 'item': 'Coolant change', 'generation_id': G1})
        self.assertEqual(st, 409, r)
        self.assertEqual(self.agent('POST', 'maintenance_items', {**job, 'job': 'CABIN_FILTER', 'generation_id': G1})[0], 201)
        st, ok = self.agent('POST', 'maintenance_items', {**job, 'generation_id': G1, 'distinct_of': [r['conflict'][0]['id']], 'notes': 'gearbox oil'})
        self.assertEqual(st, 201, ok)

    def test_units_218(self):
        """A listing request is split into units stage by stage; a unit with nothing missing is SKIPPED, the server re-grades each
        unit, missing items re-queue it, and the parent is DONE when the stages are over."""
        patcher = mock.patch.object(research_units, 'FLOW', 'units')   # the legacy stages (the dual flow has its own tests)
        patcher.start(); self.addCleanup(patcher.stop)
        self.req('POST', '/api/requests', {'url': 'https://www.example.com/car/9'})
        claim = lambda: self.req('POST', '/api/worker/claim', {'worker': 'w'})[1]['request']
        finish = lambda r, **d: self.req('POST', f'/api/worker/requests/{r["id"]}', {'status': 'DONE', **d})[1]
        parts = lambda: {p['unit']: p['status'] for p in self.req('GET', '/api/requests')[1][0]['parts']}
        self.gaps[:] = ['var.tyres', 'gen.hu', 'lst.checklist']
        cap = claim()
        self.assertEqual(cap['unit'], 'CAPTURE')
        self.assertEqual(finish(cap, listing_id=CAR_A)['status'], 'WAITING')
        self.assertEqual(parts(), {'VARIANT': 'QUEUED'})                      # the next stages exist only when this one is closed
        v = claim()
        self.assertEqual((v['unit'], v['missing'], v['listing_id']), ('VARIANT', ['var.tyres'], CAR_A))
        self.gaps[:] = ['gen.hu', 'lst.checklist']
        self.assertEqual(finish(v)['status'], 'DONE')
        self.assertEqual(parts(), {'VARIANT': 'DONE', 'GENERATION': 'SKIPPED', 'GEN_MAINTENANCE': 'QUEUED', 'ENGINE': 'SKIPPED', 'GEARBOX': 'SKIPPED'})
        m = claim()
        self.assertEqual(m['unit'], 'GEN_MAINTENANCE')
        self.assertEqual(finish(m)['status'], 'QUEUED')                       # gen.hu still missing: another attempt
        m = claim(); self.assertEqual(m['attempts'], 1)
        self.gaps[:] = ['lst.checklist']
        self.assertEqual(finish(m)['status'], 'DONE')
        self.assertEqual(parts()['TAX'], 'SKIPPED')
        last = claim()
        self.assertEqual(last['unit'], 'LISTING')
        self.gaps[:] = []
        self.assertEqual(finish(last)['status'], 'DONE')
        top = self.req('GET', '/api/requests')[1][0]
        self.assertEqual((top['status'], top['listing_id']), ('DONE', CAR_A))
        self.assertEqual(self.req('GET', '/api/admin/requests')[1][0]['children'][0]['unit'], 'VARIANT')

    def test_insurance_unit_245(self):
        """INSURANCE is the last stage: SKIPPED without the account's consent, for a reference car or an incomplete profile;
        queued with consent and a complete profile; a failed quote never fails the car; consent is set only by the account itself."""
        from carlos import todo
        st, ck = self.login()
        self.assertEqual(self.req('POST', '/api/preferences', {'insurance_worker_quotes': 'yes'})[0], 403)           # a token cannot consent
        self.assertEqual(self.req('POST', '/api/preferences', {'insurance_worker_quotes': 'maybe'}, token=None, cookie=ck)[0], 400)
        claim = lambda: self.req('POST', '/api/worker/claim', {'worker': 'w'})[1]['request']
        run = lambda: [self.req('POST', f'/api/worker/requests/{c["id"]}', {'status': 'DONE', 'listing_id': CAR_A})[1] for c in [claim()]][0]
        parts = lambda: {p['unit']: p['status'] for p in self.req('GET', '/api/requests')[1][0]['parts']}
        def go():
            self.sql_write("UPDATE research_requests SET status='CANCELLED'")
            self.req('POST', '/api/requests', {'url': f'https://www.example.com/car/{go.n}'}); go.n += 1
            self.gaps[:] = ['lst.insurance']
            run()                                                              # capture done; only the quote is missing
        go.n = 20
        go()
        self.assertEqual(parts()['INSURANCE'], 'SKIPPED')                     # no consent
        self.assertIn('not enabled', [c for c in self.req('GET', '/api/admin/requests')[1][0]['children'] if c['unit'] == 'INSURANCE'][0]['result'])
        self.assertEqual(self.req('GET', '/api/requests')[1][0]['status'], 'DONE')
        # consent (own login) but no complete profile
        self.assertEqual(self.req('POST', '/api/preferences', {'insurance_worker_quotes': 'yes'}, token=None, cookie=ck)[0], 200)
        self.assertRegex(self.sql("SELECT preference_value FROM project_preferences WHERE preference_key='insurance_worker_quotes'")[0][0], r'^yes \d{4}-\d\d-\d\d$')
        go()
        self.assertEqual(parts()['INSURANCE'], 'SKIPPED')
        self.assertIn('profile incomplete', [c for c in self.req('GET', '/api/admin/requests')[1][0]['children'] if c['unit'] == 'INSURANCE'][0]['result'])
        # complete profile: the unit is queued; the agent's failure (blocked site) ends it without failing the car
        sets = ', '.join(f"{k}='x'" for k in todo.QUOTE_PARAMS if k != 'annual_km')
        self.sql_write(f"UPDATE project_parameters SET {sets}, annual_km=10000 WHERE owner_id=1")
        for k in todo.QUOTE_PREFS:
            self.sql_write("INSERT OR REPLACE INTO project_preferences (owner_id, preference_key, preference_value) VALUES (1, ?, 'x')", (k,))
        go()
        self.assertEqual(parts()['INSURANCE'], 'QUEUED')
        ins = claim()
        self.assertEqual(ins['unit'], 'INSURANCE')
        self.assertEqual(self.req('POST', f'/api/worker/requests/{ins["id"]}', {'status': 'FAILED', 'result': 'blocked by CHECK24'})[1]['status'], 'FAILED')
        top = self.req('GET', '/api/requests')[1][0]
        self.assertEqual(top['status'], 'DONE')
        self.assertIn('Insurance open', top['result'])
        # the reference car is never quoted (its premium is the owner's USER DATA)
        self.sql_write("UPDATE listings SET is_reference=1 WHERE id=?", (CAR_A,))
        go()
        self.assertEqual(parts()['INSURANCE'], 'SKIPPED')

    def test_duplicate_guard_reliability_254(self):
        """A recall filed on two levels, and a defect filed both as a fault and a reliability item, are refused (409)."""
        self.sql_write('UPDATE reliability_items SET archived=1')
        rel = {'component': 'Camshaft adjuster (EA211)', 'issue': 'x', 'severity': 'HIGH', 'part': 'ENGINE', 'is_recall': 1, 'frequency_status': 'PENDING',
               'inspection_action': 'dealer VIN check', 'source_id': SRC_GUIDE}
        self.assertEqual(self.agent('POST', 'reliability_items', {**rel, 'engine_id': E_A})[0], 201)
        st, r = self.agent('POST', 'reliability_items', {**rel, 'component': 'Camshaft adjuster (EA211): oil and fuel loss', 'generation_id': G1})
        self.assertEqual(st, 409, r)
        self.assertEqual(r['conflict'][0]['table'], 'reliability_items')
        self.assertEqual(self.agent('POST', 'reliability_items', {**rel, 'component': 'Parking brake', 'part': 'CHASSIS', 'is_recall': 0, 'generation_id': G1})[0], 201)
        fault = {'component': 'Parking brake cable', 'component_code': 'PARKING_BRAKE', 'part': 'CHASSIS', 'consequence': 'COST', 'existence': 'REPORTED', 'generation_id': G1,
                 'curve_km': [[100000, 0.1], [200000, 0.4]], 'probability_basis': 'ESTIMATE', 'parts_eur': 100, 'labor_eur': 100, 'source_id': SRC_GUIDE}
        st, r = self.agent('POST', 'faults', fault)
        self.assertEqual((st, r['conflict'][0]['table']), (409, 'reliability_items'))     # already a reliability item: one table only

    def test_parallel_claims_never_share_a_request_113(self):
        for i in range(3):
            self.req('POST', '/api/requests', {'url': f'https://www.example.com/car/{i}'})
        out = []
        threads = [threading.Thread(target=lambda i=i: out.append(self.req('POST', '/api/worker/claim', {'worker': f'w{i}'})[1]['request'])) for i in range(8)]
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

    def test_worker_restart_releases_its_request_160(self):
        """Issue #160: a worker runs one request at a time, so its new claim puts the request it still holds (an interrupted
        run) back in the queue and revokes that request's token; another worker's RUNNING request is untouched."""
        wt = self.req('POST', '/api/admin/workers', {'name': 'desk'})[1]['token']
        for i in range(3):
            self.req('POST', '/api/requests', {'url': f'https://www.example.com/car/16{i}'})
        a = self.req('POST', '/api/worker/claim', {}, token=wt)[1]['request']
        other = self.req('POST', '/api/worker/claim', {'worker': 'elsewhere'})[1]['request']
        again = self.req('POST', '/api/worker/claim', {}, token=wt)[1]['request']   # the restarted worker claims again
        self.assertEqual(again['id'], a['id'])           # oldest first: the released request comes straight back, with a new token
        self.assertIn('Released: worker desk', again['result'])
        self.assertEqual(self.req('GET', '/api/tco', token=a['request_token'])[0], 401)   # the interrupted run's token is dead
        self.assertEqual(self.req('GET', '/api/tco', token=again['request_token'])[0], 200)
        rows = dict(self.sql('SELECT id, status FROM research_requests WHERE id IN (?,?)', (a['id'], other['id'])))
        self.assertEqual(rows, {a['id']: 'RUNNING', other['id']: 'RUNNING'})
        self.assertEqual({x['name']: x for x in self.req('GET', '/api/admin/workers')[1]}['desk']['request_id'], a['id'])

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
        self.assertEqual(worker.outcome('CARLOS_RESULT done: faults complete'), {'status': 'DONE', 'result': 'faults complete'})  # a follow-up (#168)
        # the research runs on Haiku (owner, 2026-11-07): --model added after the claude executable unless given
        self.assertEqual(worker.command('claude -p', 'haiku'), ['claude', '--model', 'haiku', '-p'])
        self.assertEqual(worker.command('claude --chrome -p --', 'haiku')[:3], ['claude', '--model', 'haiku'])
        self.assertEqual(worker.command('claude --model opus -p', 'haiku'), ['claude', '--model', 'opus', '-p'])
        self.assertEqual(worker.command("sh -c 'x'", 'haiku'), ['sh', '-c', 'x'])

    def test_worker_usage_limit_206(self):
        import datetime, worker
        from capture_listing import Api
        logs = Path(self.tmp.name) / 'logs'
        self.req('POST', '/api/requests', {'url': 'https://www.example.com/car/206'})
        cmd = "sh -c 'echo You have hit your 5-hour limit · resets 4am; exit 1'"
        with self.assertRaises(worker.UsageLimit):
            worker.work_one(Api(self.base, TOKEN), 'test', cmd, logs, 30)
        r = self.req('GET', '/api/requests')[1][0]
        self.assertEqual((r['status'], r['worker']), ('QUEUED', None))          # released, not FAILED
        self.assertIn('Released', r['result'])
        self.assertEqual(worker.pause_seconds('x', fallback=5), 5)
        now = datetime.datetime(2026, 11, 7, 23, 0)
        self.assertEqual(worker.pause_seconds("resets 4am (Europe/Berlin)", now), 5 * 3600 + 60)
        self.assertEqual(worker.pause_seconds("resets 11:30pm", now), 30 * 60 + 60)

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
        self.assertFalse(any(t.startswith('variant var.gearbox missing') for t in mod[V_A]))           # manual gearbox: the generation's checks suffice
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

    def test_engine_family_one_pool_331(self):
        """Engine faults count for the engine and its family alike; no 'no engine family yet' hint."""
        fam = self.agent('POST', 'engine_families', {'name': 'AM'})[1]['id']
        self.assertEqual(self.agent('PATCH', f'engines/{E_A}', {'family_id': fam})[0], 200)
        self.sql_write('UPDATE reliability_items SET archived=1')
        self.sql_write('UPDATE repair_risks SET archived=1')
        self.sql_write('UPDATE faults SET archived=1')
        fault = {'component': 'Timing chain', 'component_code': 'TIMING_CHAIN', 'part': 'ENGINE', 'consequence': 'ENGINE_DAMAGE', 'existence': 'REPORTED',
                 'curve_km': [[100000, 0.1], [200000, 0.4]], 'probability_basis': 'ESTIMATE', 'parts_eur': 400, 'labor_eur': 600,
                 'source_id': SRC_GUIDE}
        todo = lambda: ' | '.join(next(m for m in self.agent('GET', 'todo')[1]['models'] if m['vehicle_id'] == V_A)['todo'])
        self.assertIn('eng.risks missing', todo())
        self.assertIn('fam.risks missing', todo())
        fid = self.agent('POST', 'faults', {**fault, 'engine_family_id': fam})[1]['id']
        self.assertNotIn('eng.risks missing', todo())
        self.assertNotIn('fam.risks missing', todo())
        self.assertNotIn('no engine family', todo())
        self.agent('PATCH', f'faults/{fid}', {'archived': 1})
        self.assertEqual(self.agent('POST', 'faults', {**fault, 'engine_id': E_A})[0], 201)
        self.assertNotIn('fam.risks missing', todo())
        self.assertNotIn('eng.risks missing', todo())

    def test_recalls_fallback_333(self):
        """An N/A recall check never satisfies gen.recalls; recall codes are KBA references or MAKE-YYYY-MM-COMPONENT."""
        gen = lambda: next(x for x in self.agent('GET', 'todo')[1]['catalogue']['generations'] if x['id'] == G1)
        self.sql_write("DELETE FROM research_checks WHERE task='gen.recalls'")
        chk = {'generation_id': G1, 'task': 'gen.recalls', 'source_id': SRC_GUIDE}
        self.assertEqual(self.agent('POST', 'research_checks', {**chk, 'result': 'N/A'})[0], 201)
        self.assertIn('gen.recalls', gen()['missing'])
        self.assertEqual(self.agent('POST', 'research_checks', {**chk, 'result': 'NONE FOUND'})[0], 201)
        self.assertNotIn('gen.recalls', gen()['missing'])
        rc = {'generation_id': G1, 'defect': 'Cam adjuster', 'source_id': SRC_GUIDE}
        self.assertEqual(self.agent('POST', 'recalls', {**rc, 'code': 'UNKNOWN-1'})[0], 400)
        self.assertEqual(self.agent('POST', 'recalls', {**rc, 'code': 'unknown recall'})[0], 400)
        self.assertEqual(self.agent('POST', 'recalls', {**rc, 'code': 'KBA-14729R'})[0], 201)
        self.assertEqual(self.agent('POST', 'recalls', {**rc, 'code': 'VW-2019-08-CAM_ADJUSTER'})[0], 201)

    def test_one_open_flag_per_level_and_kind_337(self):
        flag = {'engine_id': E_A, 'kind': 'SOURCES_DISAGREE', 'what': 'engine code A', 'why': 'sources differ'}
        st, a = self.agent('POST', 'review_flags', flag)
        self.assertEqual(st, 201, a)
        st, b = self.agent('POST', 'review_flags', {**flag, 'what': 'timing drive B'})
        self.assertEqual((st, b['id'], b.get('merged')), (200, a['id'], True))
        c = sqlite3.connect(config.DB)
        n, what = c.execute("SELECT COUNT(*), what FROM review_flags WHERE engine_id=? AND kind='SOURCES_DISAGREE'", (E_A,)).fetchone()
        c.close()
        self.assertEqual(n, 1)
        self.assertIn('engine code A', what); self.assertIn('timing drive B', what)
        st, o = self.agent('POST', 'review_flags', {**flag, 'kind': 'OTHER'})        # another kind: a new row
        self.assertEqual((st, o['id'] != a['id']), (201, True))
        self.sql_write("UPDATE review_flags SET status='CLEARED'")
        self.assertEqual(self.agent('POST', 'review_flags', flag)[0], 201)            # a cleared flag may repeat

    def test_rel_coverage_343(self):
        """A fault two sources name must be filed; a FOUND check without named_codes leaves rel.coverage missing."""
        todo = lambda: ' | '.join(next(m for m in self.agent('GET', 'todo')[1]['models'] if m['vehicle_id'] == V_A)['todo'])
        self.assertNotIn('rel.coverage', todo())                                     # only NONE FOUND checks: nothing named
        chk = {'generation_id': G1, 'result': 'FOUND', 'source_id': SRC_GUIDE}
        bad = {**chk, 'task': 'rel.CHASSIS.adac', 'named_codes': ['NOT_A_CODE']}
        self.assertEqual(self.agent('POST', 'research_checks', bad)[0], 400)
        self.assertEqual(self.agent('POST', 'research_checks', {**chk, 'task': 'gen.recalls', 'named_codes': ['BRAKES']})[0], 400)
        self.assertEqual(self.agent('POST', 'research_checks', {**chk, 'task': 'rel.CHASSIS.adac'})[0], 201)
        self.assertIn('checks without named_codes: rel.CHASSIS.adac', todo())
        self.sql_write("DELETE FROM research_checks WHERE task='rel.CHASSIS.adac' AND result='FOUND'")
        for src in ('adac', 'tuev'):
            self.assertEqual(self.agent('POST', 'research_checks', {**chk, 'task': f'rel.CHASSIS.{src}', 'named_codes': ['BRAKE_LINES']})[0], 201)
        self.assertIn('faults named by two sources but not filed: CHASSIS BRAKE_LINES', todo())
        self.sql_write('UPDATE faults SET archived=1')
        fault = {'component': 'Brake hose', 'component_code': 'BRAKE_LINES', 'part': 'CHASSIS', 'consequence': 'SAFETY', 'existence': 'REPORTED',
                 'curve_km': [[100000, 0.1], [200000, 0.4]], 'probability_basis': 'ESTIMATE', 'parts_eur': 100, 'labor_eur': 100,
                 'source_id': SRC_GUIDE, 'generation_id': G1}
        self.assertEqual(self.agent('POST', 'faults', fault)[0], 201)
        self.assertNotIn('rel.coverage', todo())

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
        a = self.units()[CAR_A]
        conf = a['metrics']['confidence']
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
    def test_filters_and_distance_169(self):
        """#169: filters leave out cars that fail them (or whose ad doesn't say); distance from the account's postcode."""
        from carlos import geo
        self.assertEqual(geo.km('97070', '97070'), 0.0)
        self.assertTrue(85 < geo.km('97070', '90402') < 100)          # Würzburg → Nürnberg ≈ 90 km straight line
        self.assertIsNone(geo.km('97070', '00000'))
        row = lambda **kw: {'id': 1, 'is_reference': 0, **kw}
        self.assertIsNone(ranking.failed_filter(row(seller_type='DEALER'), {'filter_seller': 'DEALER'}))
        self.assertEqual(ranking.failed_filter(row(seller_type=None), {'filter_seller': 'DEALER'}), 'seller')   # unknown never passes
        self.assertEqual(ranking.failed_filter(row(service_history='CLAIMED'), {'filter_service_history': 'YES'}), 'service_history')
        self.assertIsNone(ranking.failed_filter(row(service_history='CLAIMED'), {'filter_service_history': 'YES_OR_CLAIMED'}))
        today = datetime.date(2026, 11, 6)
        self.assertEqual(ranking.months_left('2027-05', today), 6)
        self.assertIsNone(ranking.failed_filter(row(), {}))                                                    # no filter set
        self.agent('PATCH', f'listings/{CAR_A}', {'postal_code': '90402', 'seller_type': 'PRIVATE', 'seller_rating': 4.5, 'seller_reviews': 12})
        self.req('POST', '/api/parameters', {'postal_code': '97070'})
        a = next(u for u in self.req('GET', '/api/tco')[1]['listings'] if u['id'] == CAR_A)
        self.assertTrue(85 < a['metrics']['distance'] < 100)
        self.req('POST', '/api/preferences', {'filter_seller': 'DEALER'})
        a = next(u for u in self.req('GET', '/api/tco')[1]['listings'] if u['id'] == CAR_A)
        self.assertEqual((a['excluded'], a['rank']), ('filter:seller', None))
        self.assertEqual(self.agent('PATCH', f'listings/{CAR_A}', {'seller_type': 'dealer'})[0], 400)          # fixed codes (schema)

    def test_rank_scoring(self):
        """#169: fixed curves; a car is scored only when complete; cost and power in percent against the current car;
        adding a car never changes the order of the others."""
        m = lambda **kw: {k: kw.get(k) for k in ranking.CRITERIA}
        car = lambda i, **kw: {'id': i, 'is_reference': 0, 'listing_status': 'UNDER REVIEW', 'research': [], 'metrics': m(**kw)}
        rows = [{'id': 1, 'is_reference': 1, 'listing_status': 'OWNED', 'research': [], 'metrics': m(cost_month=400, mileage=200000, power=100)},
                car(2, cost_month=400, mileage=100000, power=100), car(3, cost_month=360, mileage=50000, power=110),
                car(4, cost_month=300), car(5, cost_month=500, mileage=150000, power=90)]
        rows[4]['research'] = [{'id': 'gen.safety', 'grade': 'MISSING'}]
        w = {k: 0 for k in ranking.CRITERIA} | {'cost_month': 2, 'mileage': 1, 'power': 1}
        self.assertEqual(ranking.rank(rows, w), 4)
        r = {x['id']: x for x in rows}
        self.assertEqual(r[2]['score_parts'], {'cost_month': 60, 'mileage': 75, 'power': 60})   # at the anchor = 60
        self.assertEqual(r[2]['score'], round((2 * 60 + 75 + 60) / 4, 1))
        self.assertAlmostEqual(r[3]['score_parts']['cost_month'], 60 + 112 * __import__('math').log(400 / 360), delta=1)
        self.assertEqual(r[4]['not_scored'], {'criteria': ['mileage', 'power'], 'research': []})    # incomplete: no score
        self.assertEqual(r[5]['not_scored']['research'], ['gen.safety'])                            # research missing: no score
        self.assertEqual((r[1]['score'] is not None, r[1]['rank']), (True, None))                    # reference: scored, never ranked
        self.assertEqual([x['id'] for x in sorted(rows[1:], key=lambda x: x['rank'] or 9)][:2], [3, 2])
        before = {x['id']: x['score'] for x in rows}
        rows.append(car(6, cost_month=2000, mileage=20000, power=300))                              # a far more expensive car
        ranking.rank(rows, w)
        self.assertEqual({i: r[i]['score'] for i in (2, 3)}, {i: before[i] for i in (2, 3)})     # anchored on the current car: unchanged
        self.assertEqual(ranking.budget_score(3000, 6500, 8000), 100)
        self.assertEqual(ranking.budget_score(6500, 6500, 8000), 80)
        self.assertEqual(ranking.budget_score(8000, 6500, 8000), 0)
        self.assertLess(80 - ranking.budget_score(6875, 6500, 8000), ranking.budget_score(7250, 6500, 8000) - ranking.budget_score(7625, 6500, 8000))  # falls faster further above the ideal
        self.assertEqual(ranking.score_of('safety', {'safety': 5}, {}), 100)
        self.assertEqual(ranking.score_of('reliability', {'reliability': 80}, {}), 80)  # the source mean as is (#356)
        ref = {'is_reference': 1, 'listing_status': 'OWNED', 'research': [], 'metrics': {'cost_month': 300, 'mileage': 100000, 'age': 10, 'reliability': 27,
               'power': 90, 'safety': 4, 'budget': None, 'inspection': None, 'distance': None}}
        ranking.rank([ref], {k: 1 for k in ranking.CRITERIA}, {})
        self.assertIsNotNone(ref['score'])  # the owned car is scored without budget, inspection and distance (#321)
        cand = {'is_reference': 0, 'listing_status': 'UNDER REVIEW', 'research': [], 'metrics': {**ref['metrics'], 'budget': 5000, 'distance': 20}}
        ranking.rank([cand], {k: 1 for k in ranking.CRITERIA}, {'budget_ideal_eur': 6000, 'budget_max_eur': 8000})
        self.assertIsNotNone(cand['score'])  # not inspected yet: scored without the inspection criterion (#323)
        self.assertEqual(costs.safety_stars({'ncap_stars': 5, 'ncap_year': 2005, 'esp': 0}), 3)            # old regime and no ESP

    def test_questionnaire_weights(self):
        """#169: six tasks of six cars on a 3 × 3 grid; every criterion four times, every pair at least twice; simulated
        respondents get their favourite at 5 and their least important criterion at 1."""
        import itertools, random
        C, T = ranking._KEYS, ranking.TASKS
        self.assertEqual(set(C), set(ranking.CRITERIA))
        self.assertEqual(set(ranking.weights_from_answers({}).values()), {ranking.NEUTRAL_WEIGHT})   # no answers: neutral
        self.assertEqual((len(C), len(T), set(len(x['criteria']) for x in T)), (9, 6, {6}))
        self.assertEqual({k: sum(k in x['criteria'] for x in T) for k in C}, {k: 4 for k in C})
        pairs = [frozenset(p) for x in T for p in itertools.combinations(x['criteria'], 2)]
        self.assertEqual((len(set(pairs)), min(pairs.count(x) for x in set(pairs))), (36, 2))      # every pair at least twice
        self.assertEqual({k: sum(k in x['criteria'] for x in T[:ranking.EARLY_STOP_AFTER]) for k in C}, {k: 2 for k in C})   # the row tasks
        rnd, inverted = random.Random(169), 0
        for _ in range(300):                                     # simulated respondents with true priorities
            true = dict(zip(C, rnd.sample(range(9), 9)))
            ans = {x['id']: f"{max(x['criteria'], key=true.get)}>{min(x['criteria'], key=true.get)}" for x in T}
            w = ranking.weights_from_answers(ans)
            self.assertEqual((w[max(C, key=true.get)], w[min(C, key=true.get)]), (5, 1))
            inverted += sum(true[a] > true[b] and w[a] < w[b] for a, b in itertools.permutations(C, 2))
        self.assertLess(inverted / (300 * 72), 0.01)              # weights follow the true order (< 1 % of pairs inverted)
        self.assertEqual(ranking.weights_from_answers({'u1': f"{T[0]['criteria'][0]}>{T[0]['criteria'][1]}"})[T[0]['criteria'][2]], 3)   # middle once → neutral
        self.assertEqual(ranking.known_answers({'cash': 'tight', 'u1': f"{T[0]['criteria'][0]}>{T[0]['criteria'][1]}", 's1': 'power>mileage', 'r1': 'power>mileage'}),
                         {'u1': f"{T[0]['criteria'][0]}>{T[0]['criteria'][1]}"})   # s…, r…: retired
        with self.assertRaises(ValueError):
            ranking.check_answers({'u1': 'power>power'})
        st, d = self.req('GET', '/api/ranking')
        self.assertEqual((st, d['answered'], d['manual'], len(d['tasks'])), (200, False, False, 6))
        first, other = T[0]['criteria'][0], T[0]['criteria'][1]
        st, p = self.req('POST', '/api/parameters', {'ranking_answers': {'u1': f'{first}>{other}'}})
        self.assertEqual(st, 200)
        d = self.req('GET', '/api/ranking')[1]
        self.assertEqual((d['answered'], d['weights'][first], d['weights'][other], d['tally'][first]), (True, 5, 1, {'shown': 1, 'best': 1, 'worst': 0}))
        self.assertEqual(self.req('POST', '/api/parameters', {'ranking_answers': {'u1': 'age>cash_now'}})[0], 400)
        self.req('POST', '/api/parameters', {'ranking_weights': {first: 2}})
        d = self.req('GET', '/api/ranking')[1]
        self.assertEqual((d['manual'], d['weights'][first], d['derived_weights'][first]), (True, 2, 5))
        self.req('POST', '/api/parameters', {'ranking_weights': None})                 # back to the answers
        self.assertEqual(self.req('GET', '/api/ranking')[1]['manual'], False)

    def test_phase_windows_153(self):
        """Issue #153: a generation row with a first-registration window applies only to cars registered inside it."""
        w = costs.in_window
        self.assertTrue(w({}, '2011-06') and w({'applies_from': '2011-06'}, None))           # no window / unknown registration: kept
        self.assertTrue(w({'applies_from': '2010', 'applies_to': '2011-06'}, '2011-06'))
        self.assertFalse(w({'applies_from': '2011-07'}, '2011-06') or w({'applies_to': '2010-12'}, '2011-06'))
        self.assertTrue(w({'applies_to': '2011'}, '2011-06'))                                # coarser side compares years
        self.assertEqual(self.agent('POST', 'reliability_items', {'generation_id': G1, 'component': 'x', 'severity': 'LOW', 'part': 'CHASSIS',
                                                                  'source_id': SRC_GUIDE, 'applies_from': '2011-13'})[0], 400)
        names = lambda: {r['component'] for r in self.req('GET', f'/api/listings/{CAR_A}')[1]['reliability']}   # CAR_A: 2011-06
        for comp, lo, hi in (('Early rust', None, '2011-12'), ('Facelift wiring', '2012-01', None)):
            self.assertEqual(self.agent('POST', 'reliability_items', {'generation_id': G1, 'component': comp, 'severity': 'LOW', 'part': 'CHASSIS',
                                                                      'source_id': SRC_GUIDE, 'applies_from': lo, 'applies_to': hi})[0], 201)
        self.assertIn('Early rust', names())
        self.assertNotIn('Facelift wiring', names())

    def test_reliability_sources(self):
        """#356: reliability = mean of the slots present (Autoscore inverted, TUEV vs class average, ADAC band); a missing slot is
        coverage, never 0; EngineScope only with permission; ratings never change the cost."""
        def K(i, src, key, **kw):
            return {**dict(id=i, source_key=src, external_key=key, url=f'https://x.test/{key}', engine_id=None, generation_id=None), **kw}

        def R(i, src, key, **kw):
            return {**dict(id=i, source_key=src, external_key=key, edition='2026', value_num=None, value_text=None, band=None, class_average=None,
                           age_from=None, age_to=None, reg_year=None, url=f'https://x.test/{src}'), **kw}
        keys = [K(1, 'AUTOSCORE', 'n46', engine_id=1), K(2, 'TUEV_REPORT', 'Polo', generation_id=1),
                K(3, 'ADAC_PANNENSTATISTIK', 'Polo', generation_id=1), K(4, 'ENGINESCOPE', 'ea211', engine_id=1)]
        ratings = [R(1, 'AUTOSCORE', 'N46', value_num=4.0, value_text='CAUTION'), R(2, 'TUEV_REPORT', 'Polo', age_from=6, age_to=7, value_num=10.0, class_average=10.0),
                   R(3, 'TUEV_REPORT', 'Polo', age_from=10, age_to=11, value_num=5.0, class_average=10.0),
                   R(4, 'ADAC_PANNENSTATISTIK', 'Polo', reg_year=2014, band=2, value_num=3.1), R(5, 'ENGINESCOPE', 'ea211', value_num=90, value_text='BEST')]
        f = lambda *a, **kw: costs.reliability_sources(keys, ratings, *a, **kw)
        r = f(6.5, 2014)
        self.assertEqual((r['slots']['ENGINE']['points'], r['slots']['HU']['points'], r['slots']['BREAKDOWNS']['points']), (60, 50, 75))   # EngineScope ignored while NONE
        self.assertEqual((r['score'], r['coverage'], r['missing']), (61.7, 1.0, []))
        self.assertEqual(r['slots']['ENGINE']['sources'][0]['url'], 'https://x.test/AUTOSCORE')
        self.assertEqual(f(6.5, 2014, perm='SCORE')['slots']['ENGINE']['points'], 75)                  # (60 + 90) / 2
        r = f(15, 2005)                                                                                    # older than the oldest class: nearest; no ADAC year
        self.assertEqual((r['slots']['HU']['points'], r['slots']['HU']['sources'][0]['nearest_class'], r['slots']['BREAKDOWNS'], r['coverage']), (100, True, None, 2 / 3))
        r = f(1, None)                                                                                     # under 2 years: no TUEV class
        self.assertEqual((r['missing'], r['score']), (['HU', 'BREAKDOWNS'], 60))                           # one slot is enough
        self.assertIsNone(costs.reliability_sources([], [], 5, 2020)['score'])                            # none: not scored, not 0
        # on the listing: ratings fill the metric, and cost_month is the same with and without them
        base = self.units()[CAR_A]
        self.assertIsNone(base['metrics']['reliability'])
        self.assertEqual(self.agent('POST', 'source_keys', {'source_key': 'AUTOSCORE', 'engine_id': E_A, 'external_key': 'n46', 'url': 'https://autoscore.pro/engine/n46',
                                                            'source_id': SRC_GUIDE, 'checked_date': '2026-11-10'})[0], 201)
        self.assertEqual(self.agent('POST', 'source_ratings', {'source_key': 'AUTOSCORE', 'external_key': 'n46', 'edition': '2026-11-10', 'value_num': 4.5,
                                                               'value_text': 'AVOID', 'url': 'https://autoscore.pro/engine/n46', 'source_id': SRC_GUIDE,
                                                               'checked_date': '2026-11-10'})[0], 201)
        a = self.units()[CAR_A]
        self.assertEqual((a['metrics']['reliability'], a['reliability_sources']['present']), (55, 1))
        self.assertEqual(a['metrics']['cost_month'], base['metrics']['cost_month'])

    def test_archive_and_delete(self):
        """Issue #58: archived rows drop out of every read and calculation and can be restored; delete refuses while a
        row is referenced, removes a listing with its own rows, and is logged."""
        a = self.req('GET', f'/api/listings/{CAR_A}')[1]
        chain = next(r for r in a['reliability'] if r['component'] == 'Timing chain')
        self.assertEqual(self.agent('PATCH', f"reliability_items/{chain['id']}", {'archived': 1})[0], 200)
        a2 = self.req('GET', f'/api/listings/{CAR_A}')[1]
        self.assertNotIn(chain['id'], [r['id'] for r in a2['reliability']])
        self.assertEqual(self.agent('PATCH', f"reliability_items/{chain['id']}", {'archived': 0})[0], 200)   # restore
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
        self.assertEqual([u['rank'] for u in d['listings'] if u['rank']], [])   # research incomplete: not scored yet (#169)
        self.assertTrue(all(u['not_scored']['research'] for u in d['listings'] if u['listing_status'] != 'WITHDRAWN'))
        self.assertEqual(us['B2']['excluded'], 'over_max')                               # over the maximum: not ranked
        self.assertEqual(self.req('POST', '/api/parameters', {'ranking_weights': {'cash_now': 9}})[0], 400)
        self.assertEqual(self.req('POST', '/api/parameters', {'ranking_weights': {'price': 1}})[0], 400)   # old criterion
        self.assertEqual(self.req('POST', '/api/parameters', {'ranking_weights': {'cash_now': 5}})[0], 400)   # no longer a criterion
        st, p = self.req('POST', '/api/parameters', {'ranking_weights': {'budget': 5, 'power': 0}})
        self.assertEqual(st, 200)
        w = self.req('GET', '/api/tco')[1]['ranking']['weights']
        self.assertEqual((w['budget'], w['mileage']), (5, ranking.weights_from_answers({})['mileage']))
        self.assertEqual(self.req('POST', '/api/parameters', {'exclude_over_max': 2})[0], 400)
        self.req('POST', '/api/parameters', {'exclude_over_max': 0})
        us = {u['listing_id']: u for u in self.req('GET', '/api/tco')[1]['listings']}
        self.assertIsNone(us['B2']['excluded'])                                          # switched off: ranked like the rest
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
        self.assertEqual(s['scope_columns'], ['vehicle_id', 'engine_id', 'generation_id', 'gearbox_id', 'engine_family_id',
                                              'gearbox_family_id', 'body_style_id', 'option_id'])
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
        self.assertEqual(st['limit_bytes'], 1024 * 1024 ** 2)
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
        # the same generation (start year) and engine (specs, placeholder code) are reused, not created again (#293)
        self.assertEqual(self.agent('POST', 'generations', {'make': 'alpha', 'model': 'Hatch', 'name': 'Mk 1 (2008-2014)', 'start_year': 2008}, headers=H)[1],
                         {'table': 'generations', 'id': G1, 'existing': True})
        self.assertEqual(self.agent('POST', 'engines', {'code': 'UNKNOWN-1400-74', 'fuel_type': 'Petrol', 'displacement_cc': 1400, 'power_kw': 74}, headers=H)[1],
                         {'table': 'engines', 'id': E_A, 'existing': True})
        self.assertEqual(self.agent('POST', 'engines', {'code': 'ZZ99', 'fuel_type': 'Petrol', 'displacement_cc': 1400, 'power_kw': 74}, headers=H)[0], 201)  # another real code: a new engine
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

    def test_research_reset_194(self):
        """#167/#194: the reset empties the research, keeps one account's listings (variant cleared, still readable),
        deletes the other accounts' listings with their photo files, and a second run finds nothing to do."""
        import research_reset
        c = sqlite3.connect(config.DB)
        c.execute("INSERT INTO users (id, username, role) VALUES (2, 'other', 'user')")
        c.execute('UPDATE listings SET owner_id=2 WHERE id=?', (CAR_B,))
        (config.MEDIA_DIR / 'x').mkdir(parents=True, exist_ok=True); (config.MEDIA_DIR / 'x' / 'b.jpg').write_bytes(b'jpg')
        c.execute("INSERT INTO listing_media (listing_id, captured_at, file_path, mime, bytes, sha256) "
                  "VALUES (?, '2026-11-06', 'x/b.jpg', 'image/jpeg', 3, 'h')", (CAR_B,))
        c.commit(); c.close()
        self.assertTrue(research_reset.run(config.DB, apply=False, keep=1))   # dry run changes nothing
        self.assertEqual(self.req('GET', f'/api/listings/{CAR_A}')[1]['vehicle_id'], V_A)
        done = research_reset.run(config.DB, apply=True, keep=1)
        self.assertIn('vehicles: emptied', done)
        c = sqlite3.connect(config.DB)
        for t in ('vehicles', 'engines', 'generations', 'maintenance_items', 'reliability_items', 'research_checks'):
            self.assertEqual(c.execute(f'SELECT count(*) FROM {t}').fetchone()[0], 0, t)
        self.assertEqual(c.execute('SELECT count(*) FROM listings WHERE owner_id=2').fetchone()[0], 0)
        self.assertEqual(c.execute('SELECT count(*) FROM listings WHERE vehicle_id IS NOT NULL').fetchone()[0], 0)
        self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(), [])
        c.close()
        self.assertFalse((config.MEDIA_DIR / 'x' / 'b.jpg').exists())
        st, d = self.req('GET', f'/api/listings/{CAR_A}')   # a listing awaiting research stays readable
        self.assertEqual((st, d['vehicle_id'], d['research_levels']['variant']['state']), (200, None, 'incomplete'))
        self.assertEqual(self.req('GET', '/api/tco')[0], 200)
        self.assertEqual(research_reset.run(config.DB, apply=True, keep=1), {})   # idempotent
        # a listing awaiting research is queued by reference, not by an ad link (#194)
        self.assertEqual(self.req('POST', '/api/requests', {'url': f'carlos://listing/{CAR_A}'})[0], 201)
        self.assertEqual(self.req('POST', '/api/requests', {'url': 'carlos://listing/99999'})[0], 400)

    def test_pilot_compare_identical_runs(self):
        """#167 pilot: comparing a run with itself reports full agreement and no failures."""
        import pilot_compare
        c = sqlite3.connect(config.DB)
        c.execute("INSERT INTO faults (engine_id, component, part, consequence, existence, parts_eur, labor_eur, frequency_band, shape, source_id) "
                  "VALUES (?, 'Timing chain stretch', 'ENGINE', 'ENGINE_DAMAGE', 'CONFIRMED', 300, 500, 'common', 'WEAR_KM', ?)", (E_A, SRC_GUIDE))
        c.commit(); c.close()
        acct, pilot_compare.ACCOUNT = pilot_compare.ACCOUNT, 1
        try:
            out = pilot_compare.report(config.DB, config.DB)
        finally:
            pilot_compare.ACCOUNT = acct
        for line in ('- A: 1, B: 1, matched: 1', '- Same level: 100 % (1/1)', '- Band within one step: 100 % (1/1)',
                     '- Workshop price within ±30 %: 100 % (1/1)', '- A: none'):
            self.assertIn(line, out)

    def test_rating_sources_api(self):
        """source_keys / source_ratings (#354): per-source rules, EngineScope permission, archive instead of delete."""
        K = {'source_key': 'AUTOSCORE', 'engine_id': E_A, 'external_key': 'n46', 'url': 'https://autoscore.pro/engine/n46',
             'source_id': SRC_GUIDE, 'checked_date': '2026-11-10'}
        R = {'source_key': 'AUTOSCORE', 'external_key': 'n46', 'edition': '2026-11-10', 'value_num': 4.5, 'value_text': 'AVOID',
             'url': K['url'], 'source_id': SRC_GUIDE, 'checked_date': '2026-11-10'}
        self.assertEqual(self.agent('POST', 'source_keys', K)[0], 201)
        self.assertEqual(self.agent('POST', 'source_keys', {**K, 'external_key': 'x', 'engine_id': None, 'generation_id': G1})[0], 400)  # wrong level
        self.assertEqual(self.agent('POST', 'source_keys', {**K, 'fuel_type': 'Diesel'})[0], 400)    # fuel: GW-Info only
        self.assertEqual(self.agent('POST', 'source_keys', {**K, 'source_key': 'NOPE'})[0], 400)
        self.assertEqual(self.agent('POST', 'source_keys', {**K, 'source_id': None})[0], 400)
        st, r = self.agent('POST', 'source_ratings', R)
        self.assertEqual(st, 201)
        self.assertEqual(self.agent('POST', 'source_ratings', {**R, 'edition': '2027', 'value_num': 11})[0], 400)    # off the scale
        self.assertEqual(self.agent('POST', 'source_ratings', {**R, 'edition': '2027', 'value_text': None})[0], 400)  # required field
        self.assertEqual(self.agent('POST', 'source_ratings', {**R, 'source_key': 'ADAC_GWINFO'})[0], 400)          # keys only
        # EngineScope: link rows only until written permission
        E = {**R, 'source_key': 'ENGINESCOPE', 'external_key': 'vw-ea211-10', 'value_num': 86, 'value_text': 'BEST'}
        self.assertEqual(self.agent('POST', 'source_keys', {**K, 'source_key': 'ENGINESCOPE', 'external_key': 'vw-ea211-10'})[0], 201)
        self.assertEqual(self.agent('POST', 'source_ratings', E)[0], 403)
        with mock.patch.object(config, 'ENGINESCOPE_PERMISSION', 'SCORE'):
            self.assertEqual(self.agent('POST', 'source_ratings', {**E, 'value_text': 'AVOID'})[0], 400)            # band disagrees
            self.assertEqual(self.agent('POST', 'source_ratings', {**E, 'cost_min_eur': 200})[0], 403)
            self.assertEqual(self.agent('POST', 'source_ratings', E)[0], 201)
        # one live row per key and edition; a new edition replaces the old by archiving, never deleting
        self.assertGreaterEqual(self.agent('POST', 'source_ratings', R)[0], 400)
        self.assertEqual(self.agent('PATCH', f'source_ratings/{r["id"]}', {'archived': 1})[0], 200)
        self.assertEqual(self.agent('POST', 'source_ratings', R)[0], 201)
        self.assertEqual(self.agent('POST', 'source_keys', K, token='bad')[0], 401)


if __name__ == '__main__':
    unittest.main()
