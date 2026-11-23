"""API, calculation and migration tests on a synthetic database (tests/fixture.py), never on real data.
Run: python -m unittest -v"""
import datetime, json, math, os, re, shutil, sqlite3, tempfile, threading, time, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock
import migrate
from carlos import auth, config, server, costs, ranking, research_units
from tests import fixture as fx
from tests.fixture import REF, CAR_A, CAR_B, V_A, V_B, V_REF, V_B2, E_A, E_B, G1, G2, SRC_GUIDE, SRC_LISTING, SRC_QUOTE, SRC_TAX_OFFICIAL

TOKEN, PASSWORD = fx.TOKEN, fx.PASSWORD
REAL_DB = config.ROOT / 'data' / 'cars.sqlite'


def dossier_path(name):
    """A dossier file of account 1: <make>-<model>-<platform>-<listing id>-<row id>.md (the row id makes every name unique)."""
    return next((config.MD_DIR / '1').glob(name + '-*.md'), config.MD_DIR / '1' / (name + '.md'))


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
        fx.build(config.DB, repair_faults=True)
        auth.FAILS.clear(); auth.MINUTE.update(start=0.0, fails=0)
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
        self.assertEqual([r['component'] for r in d['fault_plan']], ['Turbocharger'])
        self.assertEqual(d['consumption'], 5.8)                               # engine-level consumption
        self.assertEqual(d['tyres'][0]['level'], 'generation')
        self.assertEqual((d['engine_row']['code'], d['generation_row']['name'], d['generation']), ('BC12T', 'Gen2', 'Gen2'))
        # the sibling variant on the same engine and generation inherits the same rows
        v = self.req('GET', f'/api/vehicles/{V_B2}')[1]
        self.assertEqual(len(v['maintenance_items']), 3)
        self.assertEqual(v['siblings'], {'same_engine': [V_B], 'same_generation': [V_B]})
        a = self.req('GET', f'/api/listings/{CAR_A}')[1]
        self.assertEqual({m['level'] for m in a['maintenance']}, {'engine', 'generation'})
        self.assertEqual({r['component'] for r in a['fault_plan']}, {'Water pump', 'Rear axle bushings'})
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
        self.sql_write('UPDATE faults SET archived=1')   # the fixture's priced repairs would conflict with the faults filed here
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

    def test_retired_tables_are_read_only_397(self):
        """reliability_items, repair_risks, review_flags and flag_reviews (retired with #351) take no new rows and no edits through the
        agent API (403) and stay out of the writable tables; a legacy row can still be archived, restored or (owner-confirmed) deleted,
        and the old rows can still be read."""
        for t in ('reliability_items', 'repair_risks', 'review_flags', 'flag_reviews'):
            self.assertEqual(self.agent('POST', t, {'component': 'x'})[0], 403, t)
            self.assertEqual(self.agent('PATCH', f'{t}/1', {'component': 'y'})[0], 403, t)
            self.assertEqual(self.agent('PATCH', f'{t}/1', {'archived': 1, 'component': 'y'})[0], 403, t)
            self.assertNotIn(t, self.agent('GET', 'schema')[1]['writable_tables'])
            self.assertEqual(self.req('GET', f'/api/admin/data/{t}')[0], 200, t)
        self.assertTrue(self.req('GET', '/api/admin/data/reliability_items')[1])      # the fixture's old rows are still there
        rid = self.req('GET', '/api/admin/data/reliability_items')[1][0]['id']
        self.assertEqual(self.agent('PATCH', f'reliability_items/{rid}', {'archived': 1})[0], 200)   # archive
        self.assertEqual(self.agent('PATCH', f'reliability_items/{rid}', {'archived': 0})[0], 200)   # restore
        self.assertEqual(self.agent('PATCH', 'repair_risks/999', {'archived': 1})[0], 404)
        st, r = self.agent('DELETE', f'reliability_items/{rid}')
        self.assertEqual(st, 200, r)
        self.assertEqual(self.sql('SELECT count(*) FROM reliability_items WHERE id=?', (rid,)), [(0,)])

    def test_models_page_faults_and_no_reliability_stats(self):
        # what the Models page shows for the new levels; reliability_stats is gone (#353): not writable
        self.sql_write('UPDATE faults SET archived=1')   # the fixture's priced repairs would conflict with the faults filed here
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
        # documented fix at today's km without a fixed-part curve: the part is new from today, so its own curve restarts at 0
        # (the chance over the period, not zero, owner rule 2026-11-22); with a fixed-part curve: that curve from the repair
        src = self.agent('POST', 'sources', {'title': 'Invoice', 'source_type': 'listing'})[1]['id']
        self.assertEqual(self.agent('POST', 'listing_history', {'listing_id': CAR_A, 'fault_id': f1, 'item': 'New chain', 'status': 'DONE',
                                                                'km': km, 'evidence': 'DOCUMENTED', 'source_id': src})[0], 201)
        fixed = lambda: {x['id']: x for x in self.req('GET', f'/api/listings/{CAR_A}')[1]['fault_plan']}[f1]
        self.assertAlmostEqual(fixed()['expected_eur'], round(costs.conditional(curve, 0, period, config.CURVE_END_KM) * 1000, 2), places=2)
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

    def test_owner_chance_on_one_car_379(self):
        """#379 (owner decision 2026-11-22): after a DONE restart a fault follows its own curve from the DONE km (or the fixed
        part's curve), unless the owner gives this car its own chance for the period; that chance applies to this car only, is validated, logged as
        user data, and the shared fault row and the other cars keep their figures. The BMW case: a chain replaced, due again."""
        f1 = self.agent('POST', 'faults', {'component': 'Chain', 'component_code': 'ENGINE_INTERNALS', 'part': 'ENGINE', 'consequence': 'ENGINE_DAMAGE',
                                           'existence': 'CONFIRMED', 'probability_basis': 'ESTIMATE', 'parts_eur': 400, 'labor_eur': 600,
                                           'source_id': SRC_GUIDE, 'generation_id': G1, 'curve_km': [[100000, 0.1], [200000, 0.4]]})[1]['id']
        plan = lambda lid: {x['id']: x for x in self.req('GET', f'/api/listings/{lid}')[1]['fault_plan']}[f1]
        before_ref, shared = plan(REF), self.sql('SELECT * FROM faults WHERE id=?', (f1,))
        src = self.agent('POST', 'sources', {'title': 'Invoice', 'source_type': 'listing'})[1]['id']
        hist = self.agent('POST', 'listing_history', {'listing_id': CAR_A, 'fault_id': f1, 'item': 'New chain', 'status': 'DONE', 'km': 80000,
                                                      'evidence': 'DOCUMENTED', 'source_id': src})
        self.assertEqual(hist[0], 201)
        hA = hist[1]['id']
        a0 = self.req('GET', f'/api/listings/{CAR_A}')[1]   # the fix restarts its own curve at 80,000 km (owner rule 2026-11-22)
        own_curve = round(costs.conditional([[100000, 0.1], [200000, 0.4]], a0['mileage_km'] - 80000, a0['mileage_km'] - 80000 + a0['period_km'],
                                            config.CURVE_END_KM) * 1000, 2)
        self.assertEqual((plan(CAR_A)['expected_eur'], plan(CAR_A)['owner_chance']), (own_curve, None))
        st, adm = self.login()
        chance = lambda row, body, ck=adm: self.req('PATCH', f'/api/ui/listing_history/{row}', body, token=None, cookie=ck)
        self.assertEqual(chance(hA, {'owner_probability': 0.3, 'owner_reason': 'Chain stretched after 61,500 km; owner expects a repeat'})[0], 200)
        p = plan(CAR_A)
        self.assertAlmostEqual(p['expected_eur'], 300.0, places=2)                              # 0.3 x (400 + 600)
        self.assertEqual((p['probability'], p['owner_chance']['source'], p['owner_chance']['reason'][:12]), (0.3, 'user_data', 'Chain stretc'))
        self.assertEqual(plan(REF), before_ref)                          # the same fault on another car is unchanged
        self.assertEqual(self.sql('SELECT * FROM faults WHERE id=?', (f1,)), shared)   # the shared row is unchanged
        self.assertEqual(self.sql("SELECT kind FROM listing_events WHERE listing_id=? ORDER BY id DESC LIMIT 1", (CAR_A,))[0][0], 'user_data')
        for bad in ({'owner_probability': 1.5, 'owner_reason': 'x'}, {'owner_probability': -0.1, 'owner_reason': 'x'},
                    {'owner_probability': '0.3', 'owner_reason': 'x'}, {'owner_probability': True, 'owner_reason': 'x'},
                    {'owner_probability': 0.3}, {'owner_probability': 0.3, 'owner_reason': '  '},
                    {'owner_probability': 0.3, 'owner_reason': 'x', 'status': 'OPEN'}, {'owner_reason': 'x'}, {}):
            self.assertEqual(chance(hA, bad)[0], 400, bad)
        self.assertEqual(chance(hA, {'owner_probability': 0.3, 'owner_reason': 'x'}, ck='nope')[0], 401)
        uid2, c2 = self.second_account()
        self.assertEqual(chance(hA, {'owner_probability': 0.9, 'owner_reason': 'x'}, ck=c2)[0], 404)   # another account's row
        self.assertAlmostEqual(plan(CAR_A)['expected_eur'], 300.0, places=2)                    # refusals changed nothing
        hopen = self.agent('POST', 'listing_history', {'listing_id': CAR_A, 'fault_id': f1, 'item': 'Chain rattle', 'status': 'OPEN', 'evidence': 'OBSERVED'})
        self.assertEqual(hopen[0], 201)
        self.assertEqual(chance(hopen[1]['id'], {'owner_probability': 0.3, 'owner_reason': 'x'})[0], 400)   # only a DONE repair
        self.assertEqual(chance(hA, {'owner_probability': None})[0], 200)                       # null clears it: unknown, not zero
        self.assertEqual((plan(CAR_A)['expected_eur'], plan(CAR_A)['owner_chance']), (own_curve, None))

    def test_scoped_rows_need_exactly_one_level(self):
        base = {'item': 'x', 'interval_km': 10000, 'schedule': 'ITEM', 'diy': 0, 'reference_cost_eur': 10, 'status': 'ESTIMATED', 'source_id': SRC_GUIDE}
        self.assertEqual(self.agent('POST', 'faults', {'component': 'x', 'component_code': 'COOLING', 'part': 'ENGINE', 'consequence': 'COST', 'existence': 'REPORTED',
                                                       'curve_km': [[0, 0], [1, 0.1]], 'parts_eur': 1, 'source_id': SRC_GUIDE})[0], 400)  # no level
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
        self.assertAlmostEqual(a['diy_hours'], 4 * 1 + 0.5 + 1.5, places=2)
        # repairs: certain 500 + faults (90,000 to 150,000 km): water pump 0.3 × 50/60 of its curve × 370; bushings F(150,000) = 0.4,
        # F(90,000) = 0.4 × 10/70, so the chance (0.4 − 0.4 × 10/70) / (1 − 0.4 × 10/70) × 210
        f0 = 0.4 * 10 / 70
        self.assertAlmostEqual(a['components']['repairs'], 500 + 0.3 * 50 / 60 * 370 + (0.4 - f0) / (1 - f0) * 210, places=2)
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
        fault = {'vehicle_id': V_A, 'component_code': 'FUEL_SYSTEM', 'part': 'ENGINE', 'consequence': 'COST', 'existence': 'REPORTED',
                 'curve_km': [[0, 0], [300000, 0.5]], 'probability_basis': 'ESTIMATE', 'source_id': SRC_GUIDE}
        self.assertEqual(self.agent('POST', 'faults', {**fault, 'component': 'Mystery'})[0], 201)              # no price yet
        self.assertEqual(self.agent('POST', 'faults', {**fault, 'component': 'X', 'component_code': 'IGNITION', 'parts_eur': 1})[0], 201)
        a = self.units()[CAR_A]
        self.assertIsNone(a['components']['repairs'])                      # certain 500 € does not hide the unknown part
        self.assertIn('repairs', a['missing_components'])
        self.assertFalse(a['tco_complete'])
        self.assertIsNone(a['delta_vs_reference'])                            # partial subtotals are not compared
        self.agent('PATCH', 'maintenance_items/1', {'diy_parts_cost_eur': None})
        self.assertIsNone(self.units()[CAR_A]['components']['maintenance'])

    def tco_at(self, years):
        return {u['id']: u for u in self.req('GET', f'/api/tco?ownership_years={years}')[1]['listings']}

    def test_resale_follows_the_ownership_period_388(self):
        """C1: a stored resale_end is the value at its own horizon_years; another ownership period moves it along the linear
        resale rule (owner decision 2026-11-23: 495 € a year of age and 0.051 € a km driven; at the fixture's 15,000 km a
        year that is 1,260 € a year of ownership; low 1.5×, high 0.5× the rule; floored at 0), so a longer horizon is not
        flattered: CAR_A at 8 years cost 330.14 a month (was 297.61 with the 6 %/year rule)."""
        per_year = 495 + 0.051 * 15000
        floor = lambda v: max(0, v)
        month = {}
        for y in (4, 6, 8):
            us = self.tco_at(y)
            a, b, ref = us[CAR_A], us[CAR_B], us[REF]
            d = y - 4
            exp, low, high = floor(4000 - per_year * d * 0.90), floor(3500 - 1.5 * per_year * d * 0.80), floor(4500 - 0.5 * per_year * d * 0.95)
            self.assertAlmostEqual(a['components']['depreciation'], 6000 - exp, places=1)
            self.assertAlmostEqual(a['tco_pessimistic'] - a['known_cost_subtotal'], exp - low, places=1)
            self.assertAlmostEqual(a['known_cost_subtotal'] - a['tco_optimistic'], high - exp, places=1)
            self.assertAlmostEqual(b['components']['depreciation'], 7500 - floor(5500 - per_year * d * 0.90), places=1)
            self.assertAlmostEqual(ref['components']['depreciation'], 2500 - floor(1500 - per_year * d * 0.90), places=1)   # sale today stays
            self.assertEqual(a['cost_detail']['resale_rescaled_from_years'], None if y == 4 else 4)
            be = a['breakeven']                                                   # the cash view prices the same end value
            self.assertAlmostEqual(be['resale_end'], exp, places=1)
            self.assertAlmostEqual(be['end_advantage'], -a['delta_vs_reference'], delta=1)
            month[y] = a['known_cost_per_month']
        self.assertAlmostEqual(month[4], 316.33, places=2)
        self.assertAlmostEqual(month[6], 329.25, delta=0.05)
        self.assertAlmostEqual(month[8], 330.14, delta=0.05)
        # a row without a horizon is taken as given; an electric car's expected value is the low case (1.5× the rule, 20 %)
        self.sql_write('UPDATE valuations SET horizon_years=NULL WHERE listing_id=?', (CAR_A,))
        self.assertAlmostEqual(self.tco_at(8)[CAR_A]['components']['depreciation'], 2000, places=1)
        e, v, l = self.ev_listing(price_eur=10000)
        self.agent('POST', 'valuations', {'listing_id': l['id'], 'kind': 'resale_end', 'horizon_years': 4, 'expected_eur': 4000,
                                          'status': 'ESTIMATED', 'source_id': SRC_GUIDE})
        self.assertAlmostEqual(self.tco_at(6)[l['id']]['components']['depreciation'], 10000 - (4000 - 1.5 * per_year * 2 * 0.80), places=1)

    def test_certain_tyres_are_part_of_the_wear_388(self):
        """C2: the set bought now is the first 45,000 km of the expected wear (60,000 km, 405 € a set: 540), never on top."""
        base = self.units()[CAR_A]['components']['tyres']
        self.assertAlmostEqual(base, 540)
        add = lambda eur: self.agent('POST', 'unit_costs', {'listing_id': CAR_A, 'category': 'tyres', 'item': 'Tyres at purchase',
                                                            'parts_eur': eur, 'status': 'ESTIMATED', 'source_id': SRC_GUIDE})[0]
        self.assertEqual(add(405), 201)
        a = self.units()[CAR_A]
        self.assertAlmostEqual(a['components']['tyres'], 540)
        self.assertAlmostEqual(a['cost_detail']['tyres_certain'] + a['cost_detail']['tyre_wear'], 540)   # 405 + the rest, 135
        self.assertAlmostEqual(self.tco_at(1)[CAR_A]['components']['tyres'], 405)      # a short stay still pays the set
        self.assertEqual(add(100), 201)                                                # more than one set's price is not capped
        self.assertAlmostEqual(self.units()[CAR_A]['components']['tyres'], 540)        # 505 certain, wear 540: the larger
        self.assertAlmostEqual(self.tco_at(8)[CAR_A]['components']['tyres'], 1080)     # 120,000 km: 2.67 sets
        self.sql_write('DELETE FROM tyre_data')                                        # no tyre data: unknown, not the certain part
        self.assertIsNone(self.units()[CAR_A]['components']['tyres'])

    def test_most_specific_level_wins_for_consumption_and_tyres_388(self):
        """C5: the exact variant's figure beats a newer engine or generation row; within one level the newest wins."""
        obs = lambda **k: self.agent('POST', 'observations', {'category': 'consumption', 'metric': config.PRIMARY_CONSUMPTION,
                                                              'status': 'PRIMARY', 'source_id': SRC_GUIDE, **k})[0]
        self.assertEqual(obs(engine_id=E_A, value_num=6.0, unit='l/100 km'), 201)       # newer than the variant's 7.0
        self.assertEqual(obs(generation_id=G2, value_num=6.5, unit='l/100 km'), 201)    # newer than CAR_B's engine row 5.8
        us = self.units()
        self.assertEqual((us[CAR_A]['consumption'], us[CAR_B]['consumption']), (7.0, 5.8))
        self.assertEqual(obs(vehicle_id=V_A, value_num=7.4, unit='l/100 km'), 201)
        self.assertEqual(self.units()[CAR_A]['consumption'], 7.4)                       # same level: the newest
        tyre = lambda price, **k: self.agent('POST', 'tyre_data', {'tyre_type': 'ALL-SEASON', 'size': '195/55 R16', 'price_per_tyre_eur': price,
                                                                   'tyres_per_set': 4, 'life_km': 45000, 'fitting_per_set_eur': 0,
                                                                   'status': 'ESTIMATED', 'source_id': SRC_GUIDE, **k})[0]
        self.assertEqual(tyre(100, vehicle_id=V_A), 201)
        self.assertEqual(tyre(50, generation_id=G1), 201)                                # re-added later by a research re-run
        self.assertAlmostEqual(self.units()[CAR_A]['components']['tyres'], 60000 / 45000 * 400)

    def test_unknown_is_never_shown_as_zero_388(self):
        """C6: a risk without a mileage, a free electricity price, a warranty of unknown age and a fix at an unknown km."""
        self.sql_write('UPDATE listings SET mileage_km=NULL WHERE id=?', (CAR_A,))
        d = self.req('GET', f'/api/listings/{CAR_A}')[1]
        self.assertTrue(d['fault_plan'])
        self.assertTrue(all(r['expected_eur'] is None and r['probability'] is None for r in d['fault_plan']))
        self.assertIsNone(d['components']['repairs'])
        # a price of 0 is a known price (fuel 0), only an unset one is unknown; the table forbids 0, the live preview accepts it
        self.req('POST', '/api/parameters', {'home_charging': 'wallbox', 'home_charging_pct': 100, 'electricity_home_eur_kwh': 0.4})
        e, v, l = self.ev_listing()
        self.agent('POST', 'observations', {'vehicle_id': v['id'], 'category': 'consumption', 'metric': config.PRIMARY_CONSUMPTION_EV,
                                            'value_num': 16.0, 'unit': 'kWh/100 km', 'status': 'PRIMARY', 'source_id': SRC_GUIDE})
        self.assertGreater(self.units()[l['id']]['components']['fuel'], 0)
        free = self.req('GET', '/api/tco?electricity_home_eur_kwh=0')[1]['listings']
        self.assertEqual(next(u for u in free if u['id'] == l['id'])['components']['fuel'], 0)
        self.req('POST', '/api/parameters', {'electricity_home_eur_kwh': None})
        self.assertIsNone(self.units()[l['id']]['components']['fuel'])
        # a warranty counts from the first registration: without it, or without any limit, there is no cover to claim
        f = {'id': 1, 'component': 'Chain', 'part': 'ENGINE', 'consequence': 'ENGINE_DAMAGE', 'parts_eur': 400, 'labor_eur': 600,
             'curve_km': json.dumps([[100000, 0.1], [200000, 0.4]]), 'warranty_share': 0.5, 'warranty_km': 900000, 'warranty_years': 40}
        plan = lambda f, age: costs.fault_plan([f], 90000, 60000, age, 48, annual_km=15000)[0]
        self.assertGreater(plan(f, 5.0)['warranty_cover'], 0)
        self.assertEqual(plan(f, None)['warranty_cover'], 0)                            # was: the car counted as brand new
        self.assertEqual(plan({**f, 'warranty_km': None, 'warranty_years': None}, 5.0)['warranty_cover'], 0)   # was: unlimited
        self.assertGreater(plan({**f, 'warranty_years': None}, None)['warranty_cover'], 0)   # a km limit alone needs no age
        # a documented fix at an unknown km: unknown, whether the fault's own curve (restarted at that km) or a fixed part's curve follows
        g = {**f, 'id': 2, 'curve_km': json.dumps([[200000, 0.05]]), 'warranty_share': None}
        run = lambda fixed: costs.fault_plan([{**f, 'warranty_share': None, 'fixed_fault_id': fixed}], 90000, 60000, 5.0, 48,
                                             done={1: None}, by_id={2: g})[0]
        self.assertIsNone(run(None)['expected_eur'])                                    # was: 0, the fix taken as a zero risk
        self.assertIsNone(run(2)['expected_eur'])                                       # was: the fix taken at km 0
        self.assertEqual((run(2)['fixed'], run(2)['repaired_at_km']), (True, None))     # the fix is registered, its km is not
        self.assertIsNotNone(costs.fault_plan([{**f, 'warranty_share': None, 'fixed_fault_id': 2}], 90000, 60000, 5.0, 48,
                                              done={1: 80000}, by_id={2: g})[0]['expected_eur'])

    def test_a_fixed_fault_restarts_its_own_curve_2026_11_22(self):
        """Owner rule (2026-11-22): a DONE repair means the part is new from its km (and date). A fault with its own curve and no
        replacement curve follows that curve restarted there (a belt done at 60,000 km, car at 100,000 km: the chance over the
        next window, not zero); a fixed_fault_id keeps the replacement part's curve; the owner's own chance overrides both."""
        from carlos import costs
        curve = [[80000, 0.3], [160000, 0.8]]                                            # belt: replaced every 80,000 km
        belt = {'id': 1, 'component': 'Timing belt', 'part': 'ENGINE', 'consequence': 'ENGINE_DAMAGE', 'parts_eur': 400, 'labor_eur': 600,
                'curve_km': json.dumps(curve), 'warranty_share': None}
        plan = lambda f, done, **kw: costs.fault_plan([f], 100000, 40000, None, 48, done={1: done}, **kw)[0]
        # (a) the window starts at the DONE km: F(80k) - F(40k) over 1 - F(40k) (about 17.6 %), not the window at 100,000 km (about 43 %)
        self.assertAlmostEqual(plan(belt, 60000)['expected_eur'], round(costs.conditional(curve, 40000, 80000, config.CURVE_END_KM) * 1000, 2), places=2)
        self.assertAlmostEqual(plan(belt, 60000)['expected_eur'], 176.47, places=2)
        self.assertNotAlmostEqual(plan(belt, 60000)['expected_eur'], round(costs.conditional(curve, 100000, 140000, config.CURVE_END_KM) * 1000, 2), places=0)
        self.assertIsNone(plan(belt, None)['expected_eur'])                              # a fix at an unknown km: unknown, never 0
        self.assertFalse(plan(belt, 60000)['age_unknown'])                               # no age curve: nothing is unknown about age
        # the age part: restarted at the DONE date when known; without it the km curve alone is used and the age part is marked unknown
        aged = {**belt, 'curve_km': None, 'curve_age': json.dumps([[5, 0.1], [10, 0.4]])}
        unknown = costs.fault_plan([aged], 100000, 40000, 8.0, 48, done={1: 60000})[0]
        self.assertEqual((unknown['expected_eur'], unknown['age_unknown']), (None, True))
        dated = costs.fault_plan([aged], 100000, 40000, 8.0, 48, done={1: 60000}, done_age={1: 2.0})[0]
        self.assertEqual(dated['age_unknown'], False)
        self.assertAlmostEqual(dated['expected_eur'], round(costs.conditional([[5, 0.1], [10, 0.4]], 2.0, 6.0, config.CURVE_END_YEARS) * 1000, 2), places=2)
        self.assertEqual(costs.fault_done_ages([{'status': 'DONE', 'fault_id': 1, 'event_date': '2022-11-22'},
                                                {'status': 'DONE', 'fault_id': 2, 'event_date': None}], datetime.date(2026, 11, 22)), {1: 4.0, 2: None})
        # (b) a fixed_fault_id keeps using the replacement part's curve from the DONE km (unchanged), not the fault's own curve
        repl = {'id': 2, 'curve_km': json.dumps([[200000, 0.05]])}
        b = costs.fault_plan([{**belt, 'fixed_fault_id': 2}], 100000, 40000, None, 48, done={1: 60000}, by_id={2: repl})[0]
        self.assertAlmostEqual(b['expected_eur'], round(costs.conditional([[200000, 0.05]], 40000, 80000, config.CURVE_END_KM) * 1000, 2), places=2)
        self.assertIsNone(costs.fault_plan([{**belt, 'fixed_fault_id': 2}], 100000, 40000, None, 48, done={1: None}, by_id={2: repl})[0]['expected_eur'])
        # (c) the owner's own chance for this car overrides the curve after the fix
        o = plan(belt, 60000, chance={1: {'probability': 0.3, 'reason': 'x'}})
        self.assertEqual((round(o['expected_eur'], 2), o['probability'], o['owner_chance']['probability']), (300.0, 0.3, 0.3))

    def test_fault_price_and_hours_follow_the_diy_choice_c4(self):
        """C4 (improve-core): a fault with a maintenance job code is priced like a maintenance job: the account's DIY choice
        (diy_jobs) picks the DIY parts price or the workshop price, never the other one; the owner's hours are shown
        (listing diy_hours, the fault row) and never priced. A DIY fault without a DIY price is unknown, not workshop-priced."""
        from carlos import costs
        curve = [[0, 0], [300000, 0.5]]
        st, f = self.agent('POST', 'faults', {'generation_id': G1, 'component': 'Clutch judder', 'component_code': 'CLUTCH', 'part': 'GEARBOX',
                                              'consequence': 'COST', 'existence': 'CONFIRMED', 'curve_km': curve, 'probability_basis': 'ESTIMATE',
                                              'parts_eur': 300, 'labor_eur': 200, 'diy_parts_eur': 100, 'diy_hours': 3, 'job': 'CLUTCH',
                                              'source_id': SRC_GUIDE})
        self.assertEqual(st, 201, f)
        fid = f['id']
        a = self.req('GET', f'/api/listings/{CAR_A}')[1]
        p = costs.conditional(curve, a['mileage_km'], a['mileage_km'] + a['period_km'], config.CURVE_END_KM)
        plan = lambda: {x['id']: x for x in self.req('GET', f'/api/listings/{CAR_A}')[1]['fault_plan']}[fid]
        hours = lambda: self.req('GET', f'/api/listings/{CAR_A}')[1]['diy_hours'] or 0
        self.sql_write("INSERT INTO project_preferences (preference_key, preference_value, unit, status) VALUES ('diy_jobs', 'clutch', 'text', 'USER_SETTING')")
        on, hours_on = plan(), hours()
        self.assertEqual((on['diy'], on['price_eur']), (True, 100))                       # the DIY parts price, not 500
        self.assertAlmostEqual(on['expected_eur'], round(p * 100, 2), places=2)
        self.assertAlmostEqual(on['diy_hours_expected'], round(p * 3, 2), places=2)     # hours shown, not priced
        self.sql_write("UPDATE project_preferences SET preference_value='yearly service' WHERE preference_key='diy_jobs'")
        off = plan()
        self.assertEqual((off['diy'], off['price_eur'], off['diy_hours_expected']), (False, 500, None))
        self.assertAlmostEqual(off['expected_eur'], round(p * 500, 2), places=2)
        self.sql_write("UPDATE project_preferences SET preference_value='clutch' WHERE preference_key='diy_jobs'")
        self.assertEqual(self.agent('PATCH', f'faults/{fid}', {'diy_parts_eur': None})[0], 200)
        self.assertIsNone(plan()['expected_eur'])                                          # DIY without its price: unknown
        self.assertIsNone(self.req('GET', f'/api/listings/{CAR_A}')[1]['components']['repairs'])
        self.assertEqual(self.agent('PATCH', f'faults/{fid}', {'diy_parts_eur': 100})[0], 200)
        self.assertEqual(self.agent('PATCH', f'faults/{fid}', {'archived': 1})[0], 200)
        self.assertAlmostEqual(hours(), hours_on - round(p * 3, 2), places=2)              # the fault's hours leave with it
        self.assertEqual(self.agent('POST', 'faults', {**{k: v for k, v in f.items() if k not in ('id', 'archived')}, 'job': 'NOT_A_JOB'})[0], 400)

    def test_a_certain_repair_and_its_fault_are_not_both_counted_c3(self):
        """C3 (improve-core): a certain repair that fixes a fault (a unit_costs repair linked by fault_id, or a PRESENT history
        item with fault_id) replaces that fault's expected cost for the period, never adds to it. A DONE fix is different: the
        part is new from that km, so its chance over the period still counts (owner rule 2026-11-22)."""
        from carlos import costs
        curve = [[0, 0], [300000, 0.5]]
        st, f = self.agent('POST', 'faults', {'generation_id': G1, 'component': 'Timing belt tensioner', 'component_code': 'TIMING_BELT',
                                              'part': 'ENGINE', 'consequence': 'ENGINE_DAMAGE', 'existence': 'CONFIRMED', 'curve_km': curve,
                                              'probability_basis': 'ESTIMATE', 'parts_eur': 400, 'labor_eur': 600, 'source_id': SRC_GUIDE})
        self.assertEqual(st, 201, f)
        fid = f['id']
        a = self.req('GET', f'/api/listings/{CAR_A}')[1]
        p = costs.conditional(curve, a['mileage_km'], a['mileage_km'] + a['period_km'], config.CURVE_END_KM)
        plan = lambda: {x['id']: x for x in self.req('GET', f'/api/listings/{CAR_A}')[1]['fault_plan']}[fid]
        repairs = lambda: self.req('GET', f'/api/listings/{CAR_A}')[1]['cost_detail']
        before = repairs()
        self.assertAlmostEqual(plan()['expected_eur'], round(p * 1000, 2), places=2)
        row = next(u for u in self.sql('SELECT id FROM unit_costs WHERE listing_id=? AND item=?', (CAR_A, 'Timing chain tensioner due')))
        self.assertEqual(self.agent('PATCH', f'unit_costs/{row[0]}', {'fault_id': fid})[0], 200)   # the certain 500 € fixes this fault
        self.assertEqual((plan()['expected_eur'], plan()['covered_by_certain']), (0.0, True))
        after = repairs()
        self.assertAlmostEqual(after['repairs_expected'], before['repairs_expected'] - round(p * 1000, 2), places=2)
        self.assertEqual(after['repairs_certain'], before['repairs_certain'])                    # the certain cost itself is unchanged
        self.assertEqual(self.agent('PATCH', f'unit_costs/{row[0]}', {'fault_id': None})[0], 200)
        # a PRESENT history item with fault_id: certain, and the same fault adds no expected cost
        self.assertAlmostEqual(plan()['expected_eur'], round(p * 1000, 2), places=2)
        st, present = self.agent('POST', 'listing_history', {'listing_id': CAR_A, 'fault_id': fid, 'item': 'Chain tensioner rattles',
                                                             'status': 'PRESENT', 'category': 'repairs', 'parts_eur': 150, 'labor_eur': 100,
                                                             'evidence': 'OBSERVED'})
        self.assertEqual(st, 201)
        self.assertEqual((plan()['expected_eur'], plan()['covered_by_certain']), (0.0, True))
        self.assertEqual(repairs()['repairs_certain'], before['repairs_certain'] + 250)
        # a DONE fix at today's km is not a certain cost of the period: the new part's chance still counts (the PRESENT row is
        # archived: its repair is the DONE row now)
        self.assertEqual(self.agent('PATCH', f"listing_history/{present['id']}", {'archived': 1})[0], 200)
        self.assertEqual(self.agent('POST', 'listing_history', {'listing_id': CAR_A, 'fault_id': fid, 'item': 'Tensioner renewed', 'status': 'DONE',
                                                                'km': a['mileage_km'], 'evidence': 'DOCUMENTED'})[0], 201)
        self.assertGreater(plan()['expected_eur'], 0)
        self.assertFalse(plan()['covered_by_certain'])

    def test_a_certain_cost_without_a_figure_is_unknown_388(self):
        """C6 (data-truth review): a certain cost with neither parts nor labour is a pending price, so its component is
        unknown, not 0. A PRESENT history item may have no figure; the unit_costs CHECK forbids it today, a legacy row may not."""
        base = self.units()[CAR_A]['components']
        st, _ = self.agent('POST', 'listing_history', {'listing_id': CAR_A, 'job': 'BRAKES_FRONT', 'item': 'Front brake pads worn',
                                                       'status': 'PRESENT', 'category': 'repairs', 'evidence': 'OBSERVED'})
        self.assertEqual(st, 201)
        a = self.units()[CAR_A]
        self.assertIsNone(a['components']['repairs'])                              # was 500 + the expected repairs, as if the pads were free
        self.assertIn('repairs', a['missing_components'])
        self.assertFalse(a['tco_complete'])
        self.assertEqual(a['components']['maintenance'], base['maintenance'])      # other categories keep their total
        self.agent('POST', 'listing_history', {'listing_id': CAR_A, 'job': 'BRAKES_FRONT', 'item': 'Brake discs worn', 'status': 'PRESENT',
                                               'category': 'repairs', 'evidence': 'OBSERVED', 'parts_eur': 90})
        self.assertIsNone(self.units()[CAR_A]['components']['repairs'])            # a priced item beside it does not hide the gap
        c = sqlite3.connect(config.DB)
        c.execute('PRAGMA ignore_check_constraints=ON')
        c.execute("INSERT INTO unit_costs (listing_id, category, item, status) VALUES (?, 'purchase_sale', 'Plates', 'ESTIMATED')", (CAR_B,))
        c.execute("INSERT INTO unit_costs (listing_id, category, item, status) VALUES (?, 'maintenance', 'Brake fluid', 'ESTIMATED')", (CAR_B,))
        c.commit(); c.close()
        b = self.units()[CAR_B]['components']
        self.assertIsNone(b['purchase_sale'])
        self.assertIsNone(b['maintenance'])

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
        self.assertAlmostEqual(sum(x['expected_eur'] for x in d['fault_plan']), d['cost_detail']['repairs_expected'])

    def test_figures_the_ui_totals_rely_on(self):
        """The UI never recomputes: per month = subtotal / period_months, and the repairs component = certain + risks + weak points
        (the dossier's Repairs total shows exactly these parts); an unpriced weak point makes the component unknown, never smaller."""
        for u in self.units().values():
            if u['known_cost_per_month'] is not None:
                self.assertAlmostEqual(u['known_cost_per_month'] * u['period_months'], u['known_cost_subtotal'])
        self.sql_write('UPDATE reliability_items SET archived=1')
        d = self.req('GET', f'/api/listings/{CAR_B}')[1]
        fault = {'engine_id': d['engine_id'], 'component': 'Timing chain', 'component_code': 'TIMING_CHAIN', 'part': 'ENGINE', 'consequence': 'ENGINE_DAMAGE',
                 'existence': 'REPORTED', 'curve_km': [[100000, 0.1], [200000, 0.4]], 'probability_basis': 'ESTIMATE', 'source_id': SRC_GUIDE}
        st, f = self.agent('POST', 'faults', {**fault, 'parts_eur': 400, 'labor_eur': 600})
        self.assertEqual(st, 201, f)
        d = self.req('GET', f'/api/listings/{CAR_B}')[1]
        cd = d['cost_detail']
        self.assertTrue(d['fault_plan'])
        self.assertAlmostEqual(cd['repairs_expected'], sum(x['expected_eur'] for x in d['fault_plan']))
        self.assertAlmostEqual(d['components']['repairs'], (cd['repairs_certain'] or 0) + cd['repairs_expected'])
        self.agent('PATCH', f"faults/{f['id']}", {'parts_eur': None, 'labor_eur': None})
        d = self.req('GET', f'/api/listings/{CAR_B}')[1]
        self.assertIsNone(d['components']['repairs'])                         # unpriced weak point: unknown, so the UI shows "+n pending"
        self.assertIsNone(d['cost_detail']['repairs_expected'])

    def test_repairs_total_cases_the_dossier_defers_to_the_server(self):
        """The dossier's Repairs total is d.components.repairs, never a client sum: it is unknown without a mileage, with only a
        certain repair (no researched risk), and it also counts PRESENT history items that no unit_costs row lists."""
        self.sql_write('UPDATE reliability_items SET archived=1')
        get = lambda: self.req('GET', f'/api/listings/{CAR_B}')[1]
        base = get()
        self.assertIsNotNone(base['components']['repairs'])
        self.assertTrue(base['fault_plan'])
        # (a) a PRESENT history cost is a certain repair although unit_costs lists nothing
        src = self.agent('POST', 'sources', {'title': 'Workshop quote', 'source_type': 'listing'})[1]['id']
        self.assertEqual(self.agent('POST', 'listing_history', {'listing_id': CAR_B, 'job': 'CLUTCH', 'item': 'Worn clutch', 'status': 'PRESENT', 'category': 'repairs',
                                                                'parts_eur': 120, 'labor_eur': 80, 'evidence': 'OBSERVED', 'source_id': src})[0], 201)
        d = get()
        self.assertEqual(d['cost_detail']['repairs_certain'], 200)
        self.assertEqual([x for x in d['unit_costs'] if x['category'] == 'repairs'], [])
        self.assertAlmostEqual(d['components']['repairs'], 200 + d['cost_detail']['repairs_expected'])
        # (b) no mileage: expected repairs unknown, so the component is unknown although the fault plan lists rows
        mileage = base['mileage_km']
        self.assertEqual(self.agent('PATCH', f'listings/{CAR_B}', {'mileage_km': None})[0], 200)
        d = get()
        self.assertIsNone(d['cost_detail']['repairs_expected'])
        self.assertIsNone(d['components']['repairs'])
        self.assertEqual(self.agent('PATCH', f'listings/{CAR_B}', {'mileage_km': mileage})[0], 200)
        # (c) only a certain repair, nothing researched: the component stays unknown
        for r in base['fault_plan']:
            self.assertEqual(self.agent('PATCH', f"faults/{r['id']}", {'archived': 1})[0], 200)
        d = get()
        self.assertEqual(d['cost_detail']['repairs_certain'], 200)
        self.assertIsNone(d['components']['repairs'])

    def test_valuation_sources_are_listed_with_the_dossier(self):
        """A valuation's source is a link in the dossier, so the source must be in d.sources even when nothing else cites it."""
        src = self.agent('POST', 'sources', {'title': 'Resale comparison', 'source_type': 'listing', 'url': 'https://example.test/resale'})[1]['id']
        self.assertEqual(self.agent('POST', 'valuations', {'listing_id': CAR_B, 'kind': 'resale_end', 'expected_eur': 4000, 'status': 'ESTIMATED', 'source_id': src})[0], 201)
        d = self.req('GET', f'/api/listings/{CAR_B}')[1]
        self.assertIn(src, {s['id'] for s in d['sources']})

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

    def test_new_car_and_lease_are_refused_165(self):
        """Second-hand purchases only (#165): a capture refuses a new car and a lease offer; a used ad without a first
        registration is not special (its gap is listed in the to-do); the legacy lease columns keep their controlled codes."""
        import capture_listing
        cap = {'url': 'https://x.example/1', 'platform': 'mobile.de', 'captured_at': '2026-11-06', 'vehicle_id': 1, 'mileage_km': 0, 'price_eur': 22990}
        with self.assertRaises(ValueError):
            capture_listing.validate(cap)  # a new car is not captured
        capture_listing.validate({**cap, 'mileage_km': 0, 'listing': {'first_registration': '2024-03'}})  # a registered car with 0 km is used
        with self.assertRaises(ValueError):
            capture_listing.validate({**cap, 'price_eur': 0})  # a price is never 0
        for lease in ({'lease_monthly_eur': 224}, {'lease_kind': 'abo'}, {'lease_includes': 'insurance'}):
            with self.assertRaises(ValueError):
                capture_listing.validate({**cap, 'mileage_km': 50000, 'listing': {'first_registration': '2020-01', **lease}})
        e, v, l = self.ev_listing('Petrol', listing_id='NEW1', mileage_km=0, first_registration=None, price_eur=22990)
        todo = next(x for x in self.req('GET', '/api/agent/todo')[1]['listings'] if x['listing_id'] == l['id'])['todo']
        self.assertIn('listing field missing: first_registration', todo)
        self.assertEqual(self.agent('PATCH', f"listings/{l['id']}", {'lease_kind': 'rent'})[0], 400)          # controlled code
        self.assertEqual(self.agent('PATCH', f"listings/{l['id']}", {'lease_includes': 'insurance, tax'})[0], 400)  # no spaces
        self.assertEqual(self.agent('PATCH', f"listings/{l['id']}", {'lease_includes': 'insurance,tax,gap'})[0], 200)
        self.assertNotIn('offer', self.units()[l['id']])   # every car is costed as a purchase

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
        for bad in ('ftp://example.com/x', 'not a link', 'https://' + 'a' * 500 + '.com', 'javascript:alert(1)',
                    'http://127.0.0.1:8000/api/health', 'http://192.168.1.1/ad.html', 'https://user:pw@www.example.com/car', 'https://www.example.com:8443/car'):  # #386
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
        """A request without a unit is refused (owner decision 2026-11-22); the gate of the unit-split requests is in test_dual_flow."""
        self.req('POST', '/api/requests', {'url': 'https://www.example.com/car/9'})
        self.sql_write("UPDATE research_requests SET unit=NULL")   # a request without a unit: the retired single run (2026-11-22)
        self.assertIsNone(self.req('POST', '/api/worker/claim', {'worker': 'w'})[1]['request'])   # refused at the claim, never handed out
        self.assertEqual(self.sql("SELECT status, result FROM research_requests WHERE parent_id IS NULL")[0], ('FAILED', research_units.refusal(None)))
        self.assertIn('without a unit', self.sql("SELECT result FROM research_requests")[0][0])


    def test_failed_run_names_only_the_requesters_listing(self):  # round 2 finding A: a listing_id is checked on FAILED too
        self.second_account()
        H = {'X-Carlos-Account': str(self.sql("SELECT id FROM users WHERE username='maria'")[0][0])}
        st, src = self.agent('POST', 'sources', {'title': 'Her listing', 'source_type': 'listing'}, headers=H)
        st, foreign = self.agent('POST', 'listings', {'vehicle_id': V_B, 'source_id': src['id'], 'platform': 'Test', 'listing_id': 'F1', 'price_eur': 4000}, headers=H)
        rid = self.req('POST', '/api/requests', {'url': 'https://www.example.com/car/fail'})[1]['id']
        self.sql_write("UPDATE research_requests SET unit='CAPTURE' WHERE id=?", (rid,))
        got = self.req('POST', '/api/worker/claim', {'worker': 'w'})[1]['request']
        self.assertEqual(got['id'], rid)
        st, r = self.req('POST', f'/api/worker/requests/{rid}', {'status': 'FAILED', 'listing_id': foreign['id'], 'result': 'blocked'})
        self.assertEqual(st, 400, r)                                                # another account's listing: refused, the run stays RUNNING
        self.assertEqual(self.sql('SELECT status, listing_id FROM research_requests WHERE id=?', (rid,))[0], ('RUNNING', None))
        st, r = self.req('POST', f'/api/worker/requests/{rid}', {'status': 'FAILED', 'listing_id': 999999, 'result': 'blocked'})
        self.assertEqual(st, 400, r)                                                # a listing that does not exist
        st, r = self.req('POST', f'/api/worker/requests/{rid}', {'status': 'FAILED', 'listing_id': CAR_A, 'result': 'blocked'})
        self.assertEqual((st, r['status'], r['listing_id']), (200, 'FAILED', CAR_A), r)   # the requester's own listing is stored

    def test_duplicate_fault_guard_221(self):
        """The same fault filed twice is refused (409) when one catalogue variant would carry both; distinct_of overrides it with a reason."""
        from carlos import consistency
        self.assertTrue(consistency.same_fault('Timing chain stretch', 'timing-chain stretch N47'))
        self.assertFalse(consistency.same_fault('Timing chain', 'Timing belt'))
        self.sql_write('UPDATE faults SET archived=1')   # the fixture's priced repairs would conflict with the faults filed here
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

    def test_checklist_covers_faults_and_recalls_223(self):
        """A fault with an inspection_action and a recall row each get a checklist item (linked by fault_id / recall_id); until then
        lst.checklist is MISSING, afterwards met; a fault without an action is not required; the helper is idempotent."""
        from capture_listing import checklist_items
        self.sql_write('UPDATE faults SET archived=1')   # the fixture's priced repairs would conflict with the faults filed here
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
        self.sql_write('UPDATE faults SET archived=1')   # the fixture's priced repairs would conflict with the faults filed here
        n0 = self.sql('SELECT max(id) FROM faults')[0][0]
        ins = "INSERT INTO faults (component, part, consequence, existence, source_id, {}, notes) VALUES (?, 'ENGINE', 'COST', 'REPORTED', ?, ?, ?)"
        self.sql_write(ins.format('engine_id'), ('Timing chain stretch', SRC_GUIDE, E_A, None))
        self.sql_write(ins.format('generation_id'), ('Timing chain stretching', SRC_GUIDE, G1, None))
        self.sql_write(ins.format('generation_id'), ('Turbo failure', SRC_GUIDE, G1, None))
        with sqlite3.connect(config.DB) as c:
            c.row_factory = sqlite3.Row
            pairs, lifts = consistency.duplicates(c)
            self.assertEqual(list(pairs), [(n0 + 1, n0 + 2)])
            c.execute(f"UPDATE faults SET notes='Distinct from fault #{n0 + 1}: tensioner' WHERE id={n0 + 2}")
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
        self.req('POST', '/api/requests', {'url': 'https://www.example.com/car/9'})
        claim = lambda: self.req('POST', '/api/worker/claim', {'worker': 'w'})[1]['request']
        self.sql_write("UPDATE research_requests SET unit='VARIANT'")         # a retired single-run unit (2026-11-22)
        self.assertIsNone(claim())
        self.assertEqual(self.sql("SELECT status, result FROM research_requests")[0], ('FAILED', research_units.refusal('VARIANT')))
        self.assertIn('unit VARIANT is retired', research_units.refusal('VARIANT'))

    def test_worker_insurance_removed_2026_11_22(self):
        """The worker's insurance quotes are gone (owner decision 2026-11-22, CHECK24 bans automated applications): INSURANCE is
        not a unit, a queued INSURANCE row is SKIPPED when claimed (never handed out), the preference insurance_worker_quotes is
        refused, and only clearing a stored value is allowed."""
        from carlos import research_requests as rq, research_units as ru, staging
        self.assertNotIn('INSURANCE', ru.UNITS)
        self.assertNotIn('INSURANCE', ru.UNIT_OF.values())
        self.assertNotIn('INSURANCE', staging.UNIT_TABLES)
        from carlos.agent import NotAllowed
        with self.assertRaises(NotAllowed):                             # a non-staged write under the old unit name is refused
            staging.check_unit_write(None, {'unit': 'INSURANCE'}, 'tax_data', None, {})
        st, ck = self.login()
        for value in ('yes', 'maybe'):
            st, body = self.req('POST', '/api/preferences', {'insurance_worker_quotes': value}, token=None, cookie=ck)
            self.assertEqual(st, 400, value)
            self.assertIn('removed', body['error'])
        self.sql_write("INSERT INTO project_preferences (owner_id, preference_key, preference_value) VALUES (1, 'insurance_worker_quotes', 'yes 2026-11-07')")
        self.assertEqual(self.req('POST', '/api/preferences', {'insurance_worker_quotes': None}, token=None, cookie=ck)[0], 200)
        self.assertEqual(self.sql("SELECT count(*) FROM project_preferences WHERE preference_key='insurance_worker_quotes'")[0][0], 0)
        self.sql_write("INSERT INTO research_requests (owner_id, url, unit, status) VALUES (1, 'https://www.example.com/old-insurance', 'INSURANCE', 'QUEUED')")
        self.assertIsNone(self.req('POST', '/api/worker/claim', {'worker': 'w'})[1]['request'])
        self.assertEqual(self.sql("SELECT status, result FROM research_requests WHERE unit='INSURANCE'")[0], ('SKIPPED', rq.INSURANCE_REMOVED))

    def server_day(self):
        """The server's today, frozen for one test: a midnight tick between the test's clock and the server's would move the
        60-day quote boundary by a day. The server reads datetime.date.today() only, so the module's name is swapped for a shim."""
        day = datetime.date.today()
        shim = type('shim', (), {'date': type('Clock', (datetime.date,), {'today': classmethod(lambda cls: day)})})
        patch = mock.patch.object(server, 'datetime', shim); patch.start(); self.addCleanup(patch.stop)
        return day

    def test_manual_quote_399(self):
        """Any account enters an insurance quote for its own car: validated, stored as QUOTE from a user_data source (quality D),
        costed like a worker quote, logged, clears the to-do line; never another account's car or the reference car."""
        uid2, c2 = self.second_account()
        st, adm = self.login()
        today = self.server_day()
        post = lambda body, ck=adm: self.req('POST', '/api/ui/listing_quotes', body, token=None, cookie=ck)
        self.agent('PATCH', 'insurance_data/1', {'quote_date': '2026-01-01'})
        todo = lambda: {x['listing_id']: x['todo'] for x in self.agent('GET', 'todo')[1]['listings']}[CAR_A]
        self.assertTrue(any('lst.insurance missing' in x and 'Costs tab' in x for x in todo()))
        good = {'listing_id': CAR_A, 'premium_eur': 50, 'period': 'month', 'insurer': ' Example ', 'cover': 'Vollkasko', 'deductible_eur': 300, 'sf_class': 'SF 2'}
        st, r = post(good)
        self.assertEqual(st, 201, r)
        q = self.sql('SELECT annual_premium_eur, premium_status, insurer, quote_date, quote_profile, notes FROM listing_quotes WHERE id=?', (r['id'],))[0]
        self.assertEqual(q[:3], (600.0, 'QUOTE', 'Example'))
        self.assertEqual(q[3], datetime.date.today().isoformat())
        self.assertEqual(json.loads(q[4]), {'cover': 'Vollkasko', 'deductible_eur': 300.0, 'sf_class': 'SF 2', 'entered_period': 'month'})
        self.assertIn('50.00 EUR per month', q[5])
        self.assertEqual(self.sql("SELECT s.source_type, s.quality FROM sources s JOIN listing_quotes q ON q.source_id=s.id WHERE q.id=?", (r['id'],))[0], ('user_data', 'D'))
        self.assertEqual(self.sql("SELECT kind, text FROM listing_events WHERE listing_id=? ORDER BY id DESC LIMIT 1", (CAR_A,))[0][0], 'user_data')
        self.assertEqual(self.units()[CAR_A]['annual_insurance'], 600.0)           # costed like any quote
        self.assertFalse(any('lst.insurance missing' in x for x in todo()))
        post({**good, 'premium_eur': 700, 'period': 'year'})
        self.assertEqual(self.sql("SELECT count(*) FROM sources WHERE source_type='user_data'")[0][0], 1)  # one source per account
        self.assertEqual(self.units()[CAR_A]['annual_insurance'], 700.0)           # the newest quote counts
        # validation
        for bad in ({'premium_eur': 0}, {'premium_eur': -5}, {'premium_eur': 'abc'}, {'premium_eur': None}, {'premium_eur': True}, {'premium_eur': 30000},
                    {'period': 'week'}, {'quote_date': '2999-01-01'}, {'quote_date': 'yesterday'}, {'cover': 'Gold'}, {'deductible_eur': -1},
                    {'insurer': 'x' * 81}, {'sf_class': 'SF 12345678'}, {'listing_id': 'x'}, {'listing_id': 99999}, {'listing_id': REF},
                    {'premium_eur': 10 ** 400}, {'premium_eur': float('nan')}, {'deductible_eur': 10 ** 400}, {'listing_id': 10 ** 400},
                    {'insurer': {'a': 1}}, {'tariff': ['x']}, {'sf_class': 5}, {'cover': ['Vollkasko']}, {'period': {'x': 1}},
                    {'quote_date': (today - datetime.timedelta(days=config.QUOTE_MAX_AGE_DAYS + 1)).isoformat()}, {'quote_date': '2999-01-01'}):
            self.assertEqual(post({**good, **bad})[0], 400, bad)
        self.assertIn('older than', post({**good, 'quote_date': '2001-01-01'})[1]['error'])           # an accurate message, not "future"
        self.assertIn('future', post({**good, 'quote_date': '2999-01-01'})[1]['error'])
        # free text: control characters and runs of whitespace become one space (it reaches the log and the Markdown dossiers)
        st, rr = post({**good, 'insurer': 'Ex\nample\x00  AG', 'tariff': 'a\r\n\t b', 'sf_class': 'SF\x7f1', 'premium_eur': 701})
        self.assertEqual(st, 201, rr)
        self.assertEqual(self.sql('SELECT insurer, tariff FROM listing_quotes WHERE id=?', (rr['id'],))[0], ('Ex ample AG', 'a b'))
        self.assertNotRegex(self.sql("SELECT text FROM listing_events WHERE listing_id=? ORDER BY id DESC LIMIT 1", (CAR_A,))[0][0], r'[\x00-\x1f\x7f]')
        # an older quote entered later never replaces a fresher one; the oldest accepted date and one day ahead (browser clock) are fine
        old = (today - datetime.timedelta(days=config.QUOTE_MAX_AGE_DAYS)).isoformat()
        self.assertEqual(post({**good, 'premium_eur': 123, 'period': 'year', 'quote_date': old})[0], 201)
        self.assertEqual(self.units()[CAR_A]['annual_insurance'], 8412.0)
        st, rr = post({**good, 'premium_eur': 702, 'period': 'year', 'quote_date': (today + datetime.timedelta(days=1)).isoformat()})
        self.assertEqual(st, 201, rr)
        self.assertEqual(self.sql('SELECT quote_date FROM listing_quotes WHERE id=?', (rr['id'],))[0][0], today.isoformat())  # clamped to the server's today
        self.assertEqual(self.req('PATCH', f'/api/ui/listing_quotes/{r["id"]}', {'premium_eur': 1}, token=None, cookie=adm)[0], 404)
        self.assertEqual(post(good, ck='nope')[0], 401)
        # another account cannot quote this car, and its own quote does not appear in this account
        self.assertEqual(post(good, ck=c2)[0], 400)
        self.assertEqual(self.sql('SELECT count(*) FROM listing_quotes WHERE listing_id=?', (CAR_A,))[0][0], 5)

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
        # the capture's shell as the helpers make it: a known generation and engine are POSTed (answered existing, logged as the run's reuse; SEC-B/E)
        self.assertEqual(self.agent('POST', 'generations', {'make': 'Alpha', 'model': 'Hatch', 'name': 'Mk1', 'start_year': 2008}, token=rt)[1]['id'], G1)
        self.assertEqual(self.agent('POST', 'engines', {'code': 'AM14', 'fuel_type': 'Petrol', 'displacement_cc': 1400, 'power_kw': 74, 'power_ps': 100}, token=rt)[1]['id'], E_A)
        st, v = self.agent('POST', 'vehicles', {'generation_id': G1, 'engine_id': E_A, 'trim': 'Her 1.4', 'transmission': 'Manual', 'body_style': 'Hatchback, 5 doors',
                                                'emissions_standard': 'Euro 5', 'co2_g_km': 140, 'hsn': '5151', 'tsn': 'WWW', 'technical_status': 'VERIFIED'}, token=rt)
        self.assertEqual(st, 201, v)  # SEC-2: a capture lists on a variant it created (a known variant is not its to name)
        st, l = self.agent('POST', 'listings', {'vehicle_id': v['id'], 'source_id': src['id'], 'platform': 'Test', 'listing_id': 'W1',
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
        with mock.patch.dict(os.environ, {'WORKER_TOKEN': new, 'CARLOS_ACCOUNT': '9'}):  # the worker's own environment, not the run's
            worker.work_one(api, 'desk', "sh -c 'echo tok=$AGENT_TOKEN acct=${CARLOS_ACCOUNT:-none} worker=${WORKER_TOKEN:-none}; echo CARLOS_RESULT failed: test'", logs, 30)
        log = next(logs.glob('request-*.log')).read_text()
        self.assertIn('acct=none', log)
        self.assertIn('worker=none', log)                    # the run's environment is an allow-list (#386)
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
        wt = self.req('POST', '/api/admin/workers', {'name': 'test'})[1]['token']   # a registered worker: its own token only (no admin fallback)
        def api():
            a = Api(self.base, wt); a.worker = True
            return a
        self.req('POST', '/api/requests', {'url': 'https://www.example.com/car/7'})
        logs = Path(self.tmp.name) / 'logs'
        # the fake agent gets no account header and no worker or admin token: only the request's own token
        cmd = f"sh -c 'echo acct=${{CARLOS_ACCOUNT:-none}} worker=${{WORKER_TOKEN:-none}}; echo CARLOS_RESULT listing_id={CAR_A}'"
        self.assertTrue(worker.work_one(api(), 'test', cmd, logs, 30))
        r = self.req('GET', '/api/requests')[1][0]
        self.assertEqual((r['status'], r['listing_id'], r['worker']), ('DONE', CAR_A, 'test'))
        log = (logs / f'request-{r["id"]}.log').read_text()
        self.assertIn('acct=none worker=none', log)
        self.assertNotIn(wt, log)
        self.assertFalse(worker.work_one(api(), 'test', cmd, logs, 30))   # queue empty
        self.req('POST', '/api/requests', {'url': 'https://www.example.com/car/8'})
        worker.work_one(api(), 'test', "sh -c 'echo CARLOS_RESULT failed: page blocked'", logs, 30)
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
        wt = self.req('POST', '/api/admin/workers', {'name': 'test'})[1]['token']
        api = Api(self.base, wt); api.worker = True
        logs = Path(self.tmp.name) / 'logs'
        self.req('POST', '/api/requests', {'url': 'https://www.example.com/car/206'})
        cmd = "sh -c 'echo You have hit your 5-hour limit · resets 4am; exit 1'"
        with self.assertRaises(worker.UsageLimit):
            worker.work_one(api, 'test', cmd, logs, 30)
        r = self.req('GET', '/api/requests')[1][0]
        self.assertEqual((r['status'], r['worker']), ('QUEUED', None))          # released, not FAILED
        self.assertIn('Released', r['result'])
        self.assertEqual(worker.pause_seconds('x', fallback=5), 5)
        now = datetime.datetime(2026, 11, 7, 23, 0)
        self.assertEqual(worker.pause_seconds("resets 4am (Europe/Berlin)", now), 5 * 3600 + 60)
        self.assertEqual(worker.pause_seconds("resets 11:30pm", now), 30 * 60 + 60)

    def test_insurance_quotes(self):
        quote = {'vehicle_id': V_A, 'premium_status': 'QUOTE', 'annual_premium_eur': 850,
                 'insurer': 'Test Insurer', 'tariff': 'Basic', 'quote_date': fx.TODAY, 'source_id': SRC_QUOTE,
                 'quote_profile': {'cover': 'Teilkasko', 'deductible_eur': 150}}
        self.assertEqual(self.agent('POST', 'insurance_data', quote)[0], 201)
        self.assertEqual(self.units()[CAR_A]['annual_insurance'], 850)        # the latest quote wins
        self.assertEqual(self.agent('POST', 'insurance_data', {**quote, 'quote_profile': 'x'})[0], 400)
        self.assertEqual(self.agent('POST', 'insurance_data', {**quote, 'quote_date': '03.11.2026'})[0], 400)
        st, row = self.agent('POST', 'insurance_data', {'vehicle_id': V_A, 'insurer': 'Test AG', 'source_id': SRC_QUOTE})
        self.assertEqual(st, 201)
        self.assertEqual(self.sql('SELECT owner_id FROM insurance_data WHERE id=?', (row['id'],))[0][0],
                         self.sql("SELECT id FROM users WHERE username='admin'")[0][0])  # N6: never a shared (NULL) owner
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
        self.assertIn('generation rel.tuev missing: TÜV-Report key with a rating of the newest imported edition (or a check: N/A, not in the report)', mod[V_A])
        self.assertIn('generation gen.recalls missing: recall search (KBA / manufacturer)', mod[V_A])
        self.assertEqual({x['vehicle_id']: x['state'] for x in d['models']}[V_A], 'incomplete')
        self.assertEqual(set(d['catalogue']), {'generations', 'engines', 'variants'})
        e_a = {x['id']: x for x in d['catalogue']['engines']}[E_A]
        self.assertIn('eng.coolant', e_a['missing'])
        self.assertIn('eng.oil', e_a['accepted'])                               # a DIY price from a C source
        self.assertNotIn('items', e_a)
        # an expired quote is the listing's own research item
        self.agent('PATCH', 'insurance_data/1', {'quote_date': '2026-01-01'})
        self.assertIn(f'listing lst.insurance missing: an insurance quote younger than {config.QUOTE_MAX_AGE_DAYS} days (enter it in the dossier Costs tab)',
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

    def test_rel_sources_357(self):
        """Contract v10: a source key with its rating (or an N/A check) satisfies the fixed reliability items; recalls stay."""
        from carlos import research
        self.assertEqual(research.CONTRACT_VERSION, 10)
        ids = {i[0] for i in research.ITEMS}
        self.assertLessEqual({'gen.recalls', 'gen.risks', 'eng.risks'}, ids)
        self.assertFalse(ids & {'rel.coverage', 'gen.baseline', 'var.gearbox'} or any(i.startswith('rel.') and i.count('.') > 1 for i in ids))
        todo = lambda: ' | '.join(next(m for m in self.agent('GET', 'todo')[1]['models'] if m['vehicle_id'] == V_A)['todo'])
        for iid in ('rel.autoscore', 'rel.enginescope', 'rel.adac_gwinfo', 'rel.adac', 'rel.tuev'):
            self.assertIn(iid + ' missing', todo())
        src = fx.SRC_HU  # a B source of the fixture
        # a key alone does not satisfy a rated source; the key with a rating does; N/A with a reason does too
        key = {'source_key': 'ADAC_PANNENSTATISTIK', 'external_key': 'Test', 'url': 'https://www.adac.de/x', 'source_id': src,
               'generation_id': G1, 'checked_date': '2026-11-10'}
        self.assertEqual(self.agent('POST', 'source_keys', key)[0], 201)
        self.assertIn('rel.adac missing', todo())
        self.assertEqual(self.agent('POST', 'source_ratings', {'source_key': 'ADAC_PANNENSTATISTIK', 'external_key': 'test', 'edition': '2026',
                         'reg_year': 2015, 'band': 2, 'url': 'https://www.adac.de/x', 'source_id': src, 'checked_date': '2026-11-10'})[0], 201)
        self.assertNotIn('rel.adac missing', todo())
        self.assertEqual(self.agent('POST', 'research_checks', {'generation_id': G1, 'task': 'rel.tuev', 'result': 'N/A', 'source_id': src,
                                                                'notes': 'not in the report'})[0], 201)
        self.assertNotIn('rel.tuev missing', todo())

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
        self.assertEqual(a['metrics']['confidence'], research.confidence(a['research']))
        # every contract item is documented in the protocol, so code and docs stay in step
        doc = (config.ROOT / 'docs' / 'cost-research-protocol.md').read_text()
        self.assertEqual([i[0] for i in research.ITEMS if f'`{i[0]}`' not in doc], [])
        # the schema publishes the contract
        sch = self.agent('GET', 'schema')[1]
        self.assertEqual(sch['research_contract']['version'], research.CONTRACT_VERSION)
        self.assertIn('rel.autoscore', {i['id'] for i in sch['research_contract']['items']})
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

    def test_cost_order_ignores_the_other_cars_r3(self):
        """R3 (improve-core): the cost anchor is the candidates' median, so adding or removing an unrelated car shifts every
        car's cost points by the same amount. Clipping the points at 0–100 let two cars tie at the top and made their order
        depend on that anchor; unclipped, the order and the gap between two cars never change."""
        car = lambda i, cost: {'id': i, 'is_reference': 0, 'listing_status': 'UNDER REVIEW', 'research': [], 'budget_status': 'within',
                               'metrics': {k: None for k in ranking.CRITERIA} | {'cost_month': cost}}
        w = {k: 0 for k in ranking.CRITERIA} | {'cost_month': 5}
        gaps = []
        for extra in ([], [car(3, 1000)], [car(3, 1000), car(4, 1000)], [car(3, 400), car(4, 400), car(5, 1000)]):
            rows = [car(1, 250), car(2, 270), *extra]
            ranking.rank(rows, w)
            r = {x['id']: x['score'] for x in rows}
            self.assertGreater(r[1], r[2], extra)                       # the cheaper car stays ahead
            gaps.append(r[1] - r[2])
        self.assertTrue(all(abs(g - 112 * math.log(270 / 250)) < 0.11 for g in gaps), gaps)   # the same gap every time (scores rounded to 0.1)

    def test_inspection_points_follow_the_checked_share_r1(self):
        """R1 (improve-core): the inspection points are 100 − 25 per PROBLEM, scaled by the share of the checklist that was
        checked (coverage shown beside them). One ticked OK item of two is 50 points, not a full 100."""
        insp = lambda: next(e for e in self.units()[CAR_A]['explain'] if e['criterion'] == 'inspection')
        self.assertIsNone(insp()['score'])                                                    # nothing checked: not scored (#323)
        self.sql_write("UPDATE inspection_items SET status='OK' WHERE id=1")
        self.assertEqual((insp()['value'], insp()['coverage'], insp()['score']), (0, 0.5, 50))
        self.sql_write("UPDATE inspection_items SET status='OK' WHERE id=2")
        self.assertEqual((insp()['coverage'], insp()['score']), (1.0, 100))
        self.sql_write("UPDATE inspection_items SET status='PROBLEM' WHERE id=2")
        self.assertEqual((insp()['value'], insp()['score']), (1, 75))                         # one problem: 100 − 25, all checked

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
        fault = {'generation_id': G1, 'consequence': 'COST', 'existence': 'CONFIRMED', 'curve_km': [[100000, 0.1], [200000, 0.4]],
                 'probability_basis': 'ESTIMATE', 'parts_eur': 50, 'source_id': SRC_GUIDE}
        self.assertEqual(self.agent('POST', 'faults', {**fault, 'component': 'x', 'component_code': 'BODY_RUST', 'part': 'CHASSIS', 'applies_from': '2011-13'})[0], 400)
        names = lambda: {r['component'] for r in self.req('GET', f'/api/listings/{CAR_A}')[1]['fault_plan']}   # CAR_A: 2011-06
        for comp, code, part, lo, hi in (('Early rust', 'BODY_RUST', 'CHASSIS', None, '2011-12'), ('Facelift wiring', 'WIRING', 'ELECTRICS', '2012-01', None)):
            self.assertEqual(self.agent('POST', 'faults', {**fault, 'component': comp, 'component_code': code, 'part': part,
                                                           'applies_from': lo, 'applies_to': hi})[0], 201)
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
        pump = next(r for r in a['fault_plan'] if r['component'] == 'Water pump')
        self.assertEqual(self.agent('PATCH', f"faults/{pump['id']}", {'archived': 1})[0], 200)
        a2 = self.req('GET', f'/api/listings/{CAR_A}')[1]
        self.assertNotIn(pump['id'], [r['id'] for r in a2['fault_plan']])
        self.assertEqual(self.agent('PATCH', f"faults/{pump['id']}", {'archived': 0})[0], 200)   # restore
        self.assertEqual(self.agent('PATCH', f"faults/{pump['id']}", {'archived': 2})[0], 400)
        st, r = self.agent('DELETE', f"vehicles/{V_A}")
        self.assertEqual(st, 400); self.assertIn('listings.vehicle_id', r['error'])            # still used by a listing
        self.assertEqual(self.agent('DELETE', 'listings')[0], 405)
        self.assertEqual(self.agent('DELETE', 'listings/99999')[0], 404)
        n_children = self.sql('SELECT count(*) FROM inspection_items WHERE listing_id=?', (CAR_A,))[0][0]
        self.assertEqual(self.agent('POST', 'listing_history', {'listing_id': CAR_A, 'job': 'BRAKES_FRONT', 'item': 'Front brake pads worn', 'status': 'PRESENT', 'category': 'repairs', 'evidence': 'OBSERVED'})[0], 201)
        self.assertEqual(self.agent('POST', 'listing_quotes', {'listing_id': CAR_A, 'annual_premium_eur': 777, 'premium_status': 'QUOTE',
                                                               'quote_date': fx.TODAY, 'source_id': SRC_QUOTE})[0], 201)
        st, r = self.agent('DELETE', f'listings/{CAR_A}')  # its history and quotes go with it (review D-06)
        self.assertEqual((st, r['deleted'], r['removed_children']['inspection_items']), (200, True, n_children))
        self.assertEqual((r['removed_children']['listing_history'], r['removed_children']['listing_quotes']), (1, 1))
        self.assertEqual(self.sql('SELECT count(*) FROM listings WHERE id=?', (CAR_A,))[0][0], 0)
        self.assertEqual(self.sql("SELECT action FROM change_log WHERE table_name='listings' AND row_id=? ORDER BY id DESC LIMIT 1", (CAR_A,))[0][0], 'delete')
        self.assertEqual(self.req('GET', f'/api/listings/{CAR_A}')[0], 404)

    def test_listing_delete_never_unlinks_a_file_outside_the_media_folder(self):  # review D-07
        outside = config.DATA_DIR / 'keep.txt'; outside.write_bytes(b'not a photo')
        c = sqlite3.connect(config.DB)
        c.execute("INSERT INTO listing_media (listing_id, captured_at, file_path, mime, bytes, sha256) VALUES (?, ?, '../keep.txt', 'image/jpeg', 3, 'x')",
                  (CAR_A, fx.TODAY)); c.commit(); c.close()
        st, r = self.agent('DELETE', f'listings/{CAR_A}')
        self.assertEqual((st, r['deleted']), (200, True), r)
        self.assertEqual(outside.read_bytes(), b'not a photo')  # refused: the row is gone, the file outside the media folder stays

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
        self.req('POST', '/api/preferences', {'onboarding_done': '2026-11-05'})
        d = self.req('GET', '/api/todo')[1]
        self.assertFalse(any(x.startswith('setup not finished') for x in d['account']))
        self.assertFalse(any('insurance' in x for x in d['account']))           # no insurance profile to complete any more

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
        st, p = self.req('POST', '/api/parameters', {'annual_km': 12000, 'postal_code': '  '})
        self.assertEqual(st, 200)
        self.assertEqual((p['annual_km'], p['postal_code']), (12000, None))
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

    def test_agent_write_logs_and_regenerates_markdown(self):
        st, r = self.agent('PATCH', f'listings/{CAR_A}', {'verdict': 'Strong candidate, inspection pending'})
        self.assertEqual((st, r), (200, {'table': 'listings', 'id': CAR_A}))
        old, new = self.sql("SELECT old_json, new_json FROM change_log WHERE table_name='listings' ORDER BY id DESC LIMIT 1")[0]
        self.assertEqual(json.loads(new), {'verdict': 'Strong candidate, inspection pending'})
        self.assertIsNone(json.loads(old)['verdict'])
        md = dossier_path('Alpha-Hatch-Test-A1').read_text()
        self.assertIn('Strong candidate, inspection pending', md)
        self.assertIn('BC12T', dossier_path('Beta-City-Test-B1').read_text())
        self.assertTrue(dossier_path('Alpha-Hatch-OWNED-u').exists())
        self.agent('PATCH', f'listings/{CAR_A}', {'verdict': 'x'})
        self.assertNotIn('inspection pending', dossier_path('Alpha-Hatch-Test-A1').read_text())
        self.assertEqual(self.agent('POST', 'export-md')[0], 200)

    def test_dossiers_follow_saved_parameters(self):
        md = lambda: dossier_path('Alpha-Hatch-Test-A1').read_text()
        self.agent('POST', 'export-md')
        self.assertIn('4 years, 60,000 km', md())
        self.req('GET', '/api/tco?ownership_years=2')
        self.assertIn('4 years, 60,000 km', md())                              # a preview changes nothing
        self.req('POST', '/api/parameters', {'ownership_years': 2})
        self.assertIn('2 years, 30,000 km', md())

    @mock.patch.object(server.threading, 'Timer')  # photo exports are deferred (export_later); the test runs the export itself
    def test_archive_snapshot_and_photos(self, timer):
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
        jpg = fx.jpeg([(0xE0, b'x' * 100)])
        st, m = self.upload(jpg, L, q=f'?url=https://img.example/1.jpg&snapshot_id={r["id"]}')
        self.assertEqual((st, m['created']), (201, True))
        self.assertEqual(self.upload(jpg, L)[1]['created'], False)                 # deduplicated by sha256
        self.assertEqual(self.upload(b'GIF89a', L)[0], 400)                         # type not allowed
        self.assertEqual(self.upload(jpg, L, ctype='application/json')[0], 415)
        self.assertEqual(self.upload(jpg, lid=999)[0], 404)
        self.assertEqual(self.upload(b'\xff\xd8\xff' + b'x' * config.MAX_IMAGE_BYTES, L)[0], 413)
        budget, config.STORAGE_BUDGET = config.STORAGE_BUDGET, 0
        try:
            self.assertEqual(self.upload(jpg + b'more', L)[0], 507)                 # quota
        finally:
            config.STORAGE_BUDGET = budget
        d = self.req('GET', f'/api/listings/{L}')[1]
        self.assertEqual(len(d['media']), 1)
        self.assertEqual((d['cover'], d['photo_count']), (d['media'][0]['file_path'], 1))
        r = urllib.request.Request(f"{self.base}/media/{d['media'][0]['file_path']}", headers={'Authorization': f'Bearer {TOKEN}'})
        resp = urllib.request.urlopen(r)
        self.assertEqual((resp.read(), resp.headers['Cache-Control']), (jpg, 'private, no-cache'))  # review D-09: no year-long cache of a photo
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(f"{self.base}/media/{d['media'][0]['file_path']}")   # login required
        timer.assert_called()  # the dossier follows the photo once the deferred export runs
        server.export_deferred(1)
        md = dossier_path('Beta-City-Test-T1').read_text()
        self.assertIn('> Line 2', md)
        self.assertIn('| Getriebe | Automatik |', md)
        self.assertIn(f'../../media/{L}/', md)
        self.assertEqual(len(list((config.MEDIA_DIR / str(L)).iterdir())), 1)  # no orphan files

    def photo_status(self, path, cookie):
        """The HTTP status of a file request made with a login session (images are not JSON, so req() cannot read them)."""
        r = urllib.request.Request(self.base + path, headers={'Cookie': f'{auth.COOKIE}={cookie}'})
        try:
            return urllib.request.urlopen(r).status
        except urllib.error.HTTPError as e:
            return e.code

    def test_remove_photo_archive_then_delete_for_good(self):
        """Owner-approved removal (plate or VIN in a photo): archive hides at once and keeps the file; the permanent
        delete needs an archived photo, its own id and confirm: true, and only then removes the row and the file."""
        adm = self.login()[1]
        self.assertEqual(self.upload(fx.jpeg([(0xE0, b'a' * 60)]), CAR_A)[0], 201)
        self.assertEqual(self.upload(fx.jpeg([(0xE0, b'b' * 60)]), CAR_A)[0], 201)
        media = self.req('GET', f'/api/listings/{CAR_A}')[1]['media']
        keep, gone = media[0], media[1]
        files = {m['id']: config.MEDIA_DIR / m['file_path'] for m in media}
        ui = lambda method, mid, body=None, **kw: self.req(method, f'/api/ui/photo/{mid}', body, **{'token': None, 'cookie': adm, **kw})
        self.assertEqual(ui('PATCH', gone['id'], {'archived': 1}, token=TOKEN)[0], 403)   # login session only, never an agent token
        self.assertEqual(ui('PATCH', gone['id'], {'archived': 2})[0], 400)                 # only 0 or 1
        self.assertEqual(ui('PATCH', gone['id'], {'archived': 1, 'x': 1})[0], 400)
        self.assertEqual(ui('PATCH', 99999, {'archived': 1})[0], 404)
        # archive: hidden from the listing, the cover, the count and the photo URL, the file stays
        self.assertEqual(ui('PATCH', gone['id'], {'archived': 1}), (200, {'table': 'listing_media', 'id': gone['id'], 'archived': 1}))
        d = self.req('GET', f'/api/listings/{CAR_A}')[1]
        self.assertEqual([m['id'] for m in d['media']], [keep['id']])
        self.assertEqual((d['photo_count'], d['cover']), (1, keep['file_path']))
        self.assertEqual([m['id'] for m in d['removed_media']], [gone['id']])
        self.assertEqual(self.photo_status('/media/' + gone['file_path'], adm), 404)
        self.assertTrue(files[gone['id']].is_file())
        # permanent delete: needs the archived photo, its own id and confirm: true
        self.assertEqual(ui('DELETE', keep['id'], {'id': keep['id'], 'confirm': True})[0], 400)   # not archived: archive first
        self.assertEqual(ui('DELETE', gone['id'], {'confirm': True})[0], 400)                      # no id in the body
        self.assertEqual(ui('DELETE', gone['id'], {'id': gone['id'], 'confirm': 'yes'})[0], 400)   # confirm must be true
        self.assertEqual(ui('DELETE', gone['id'], {'id': keep['id'], 'confirm': True})[0], 400)    # another photo's id
        self.assertTrue(files[gone['id']].is_file())
        self.assertEqual(self.sql('SELECT COUNT(*) FROM listing_media WHERE id=?', (gone['id'],))[0][0], 1)
        # restore: shown again, file served
        self.assertEqual(ui('PATCH', gone['id'], {'archived': 0})[0], 200)
        self.assertEqual(self.req('GET', f'/api/listings/{CAR_A}')[1]['photo_count'], 2)
        self.assertEqual(self.photo_status('/media/' + gone['file_path'], adm), 200)
        # archived again, then deleted for good: the row and the file go, and the change is logged
        ui('PATCH', gone['id'], {'archived': 1})
        self.assertEqual(ui('DELETE', gone['id'], {'id': gone['id'], 'confirm': True}), (200, {'table': 'listing_media', 'id': gone['id'], 'deleted': True}))
        self.assertEqual(self.sql('SELECT COUNT(*) FROM listing_media WHERE id=?', (gone['id'],))[0][0], 0)
        self.assertFalse(files[gone['id']].is_file())
        self.assertEqual(self.sql("SELECT COUNT(*) FROM change_log WHERE table_name='listing_media' AND row_id=? AND action='delete'", (gone['id'],))[0][0], 1)
        self.assertTrue(files[keep['id']].is_file())                                    # the other photo is untouched
        self.assertEqual(self.req('GET', f'/api/listings/{CAR_A}')[1]['photo_count'], 1)

    def test_removed_photo_is_not_brought_back_by_a_recapture(self):
        adm = self.login()[1]
        jpg = fx.jpeg([(0xE0, b'c' * 60)])
        self.assertEqual(self.upload(jpg, CAR_A)[0], 201)
        mid = self.req('GET', f'/api/listings/{CAR_A}')[1]['media'][0]['id']
        self.assertEqual(self.req('PATCH', f'/api/ui/photo/{mid}', {'archived': 1}, token=None, cookie=adm)[0], 200)
        st, again = self.upload(jpg, CAR_A)                                             # the same photo captured again
        self.assertEqual((st, again['created'], again['id']), (200, False, mid))         # answered as a duplicate: stays removed
        self.assertEqual(self.req('GET', f'/api/listings/{CAR_A}')[1]['photo_count'], 0)
        st, why = self.ui('POST', f'media/{CAR_A}', raw=jpg, ctype='image/jpeg')                  # the owner adds it again from the phone
        self.assertEqual(st, 409)
        self.assertIn('restore it', why['error'])

    def test_photo_upload_only_into_own_listing(self):
        """D08: an account cannot store a photo on another account's listing (404), by either upload route; the owner can."""
        adm = self.login()[1]
        st, u = self.req('POST', '/api/admin/users', {'username': 'maria'}, token=None, cookie=adm)
        self.req('POST', '/api/auth/invite/' + u['invite'].rsplit('/', 1)[1], {'password': 'marias password'}, token=None)
        maria = self.login('maria', 'marias password')[1]
        jpg = fx.jpeg([(0xE0, b'd' * 40)])
        ui_post = lambda cookie: self.req('POST', f'/api/ui/media/{CAR_A}', raw=jpg, ctype='image/jpeg', token=None, cookie=cookie)
        agent_post = lambda cookie: self.req('POST', f'/api/agent/media/{CAR_A}', raw=jpg, ctype='image/jpeg', token=None, cookie=cookie)
        self.assertEqual(ui_post(maria)[0], 404)
        self.assertEqual(agent_post(maria)[0], 404)
        self.assertEqual(self.sql('SELECT COUNT(*) FROM listing_media WHERE listing_id=?', (CAR_A,))[0][0], 0)
        self.assertEqual(ui_post(adm)[0], 201)   # the owner's own listing
        self.assertEqual(self.sql('SELECT COUNT(*) FROM listing_media WHERE listing_id=?', (CAR_A,))[0][0], 1)

    def test_remove_photo_is_scoped_to_the_account(self):
        adm = self.login()[1]
        self.assertEqual(self.upload(fx.jpeg([(0xE0, b'd' * 60)]), CAR_A)[0], 201)
        mid = self.req('GET', f'/api/listings/{CAR_A}')[1]['media'][0]['id']
        _, maria = self.second_account()
        for method, body in (('PATCH', {'archived': 1}), ('DELETE', {'id': mid, 'confirm': True})):
            self.assertEqual(self.req(method, f'/api/ui/photo/{mid}', body, token=None, cookie=maria)[0], 404, method)   # not her listing
        self.assertEqual(self.sql('SELECT archived FROM listing_media WHERE id=?', (mid,))[0][0], 0)
        self.assertEqual(self.req('PATCH', f'/api/ui/photo/{mid}', {'archived': 1}, token=None, cookie=adm)[0], 200)
        self.assertEqual(self.req('DELETE', f'/api/ui/photo/{mid}', {'id': mid, 'confirm': True}, token=None, cookie=maria)[0], 404)
        self.assertEqual(self.sql('SELECT COUNT(*) FROM listing_media WHERE id=?', (mid,))[0][0], 1)

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
        self.assertEqual(self.ui('POST', f'media/{CAR_A}', raw=fx.jpeg([(0xE0, b'v' * 50)]), ctype='image/jpeg')[0], 201)
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
        self.assertEqual(sorted(auth.FAILS), ['127.0.0.1', 'u:admin'])        # the client and, apart, the username (10 of 20 fails: not locked)
        auth.FAILS['127.0.0.1'].update(until=0.0, last=0.0)                   # the lock expired long ago: purged on the next call
        self.assertEqual(self.login()[0], 200)
        self.assertNotIn('127.0.0.1', auth.FAILS)

    def test_wrong_passwords_are_capped_per_minute_across_usernames(self):  # N5: a new name and address each time, only the minute cap counts
        from carlos.db import connect
        c = connect()
        self.addCleanup(c.close)
        self.addCleanup(auth.MINUTE.update, start=0.0, fails=0)
        auth.MINUTE.update(start=time.time(), fails=0)
        for i in range(auth.LOGIN_MAX_PER_MINUTE):
            self.assertIsNone(auth.login(c, f'ghost{i}', 'wrong', client=f'10.9.{i // 250}.{i % 250}'))
        self.assertTrue(auth.capped())
        self.assertIsNone(auth.login(c, 'admin', PASSWORD, client='10.8.0.1'))  # the right password waits for the next minute
        auth.MINUTE.update(start=time.time() - 61)
        self.assertIsNotNone(auth.login(c, 'admin', PASSWORD, client='10.8.0.2'))
        self.assertFalse(auth.capped())

    def test_json_body_size_is_capped(self):
        r = urllib.request.Request(self.base + '/api/auth/login', b'{}', {'Content-Type': 'application/json', 'Content-Length': str(server.MAX_JSON_BYTES + 1)}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(r)
        self.assertEqual(cm.exception.code, 413)

    # --- hardening (issue #383) ---
    def run_token(self, unit):
        """The per-request token of a claimed request of `unit` (the admin token claims it as the worker)."""
        rid = self.req('POST', '/api/requests', {'url': f'https://www.example.com/car/{unit.lower()}'})[1]['id']
        self.sql_write('UPDATE research_requests SET unit=? WHERE id=?', (unit, rid))
        return self.req('POST', '/api/worker/claim', {'worker': 'w'})[1]['request']['request_token']

    def fake_handler(self, token=None, cookie=None, method='GET', path='/api/tco'):
        h = object.__new__(server.Handler)
        h.command, h.path = method, path
        h.headers = {**({'Authorization': f'Bearer {token}'} if token else {}), **({'Cookie': f'{auth.COOKIE}={cookie}'} if cookie else {})}
        return h

    def raw_http(self, head):
        import socket
        s = socket.create_connection(('127.0.0.1', self.srv.server_port), timeout=5)
        try:
            s.sendall(head.encode())
            return s.recv(4096).split(b'\r\n', 1)[0].decode()
        finally:
            s.close()

    def test_security_headers_on_every_response(self):
        for path in ('/', '/login', '/static/js/boot.js', '/api/auth/me', '/nothing-here'):
            try:
                resp = urllib.request.urlopen(urllib.request.Request(self.base + path))
            except urllib.error.HTTPError as e:
                resp = e
            h = resp.headers
            self.assertIn("script-src 'self';", h['Content-Security-Policy'], path)
            self.assertIn("frame-ancestors 'none'", h['Content-Security-Policy'])
            self.assertEqual((h['X-Content-Type-Options'], h['X-Frame-Options'], h['Referrer-Policy']), ('nosniff', 'DENY', 'no-referrer'), path)
            self.assertIsNone(h['Strict-Transport-Security'])                           # plain http: no HSTS
        r = urllib.request.Request(self.base + '/login', headers={'X-Forwarded-Proto': 'https'})
        self.assertIn('max-age=', urllib.request.urlopen(r).headers['Strict-Transport-Security'])

    def test_no_inline_style_or_script_in_static(self):
        # the CSP has style-src 'self' (no 'unsafe-inline'): styles are classes in static/css or data-style set by ui.js
        csp = urllib.request.urlopen(self.base + '/login').headers['Content-Security-Policy']
        self.assertIn("style-src 'self';", csp)
        static = os.path.join(os.path.dirname(__file__), '..', 'static')
        bad = []
        for dirpath, _, names in os.walk(static):
            for n in names:
                if not n.endswith(('.html', '.js')):
                    continue
                text = open(os.path.join(dirpath, n), encoding='utf-8').read()
                if re.search(r'\sstyle=|<style|\ssetAttribute\(\s*[\'"]style', text):
                    bad.append(n)
        self.assertEqual(bad, [], 'inline style in static/: move it to a class in static/css or to data-style')

    def test_pages_need_no_inline_script(self):
        """The CSP forbids inline scripts and handlers: every page loads its code from /static/js."""
        for page in ('index.html', 'auth.html'):
            html = (config.STATIC / page).read_text()
            self.assertEqual(re.findall(r'<script(?![^>]*\bsrc=)[^>]*>', html), [], page)
            self.assertEqual(re.findall(r'\son[a-z]+\s*=\s*["\']', html), [], page)
        for js in config.STATIC.glob('js/**/*.js'):
            self.assertEqual(re.findall(r'\son(?:click|change|input|submit|load|error)\s*=\s*\\?["\']', js.read_text()), [], js.name)
        self.assertIn("location.protocol === 'https:' ? '; Secure'", (config.STATIC / 'js' / 'app.js').read_text())   # the carlos_view cookie

    def test_login_page_has_landmarks_and_loads_its_strings(self):
        """The sign-in page has one h1 and a main, and loads its strings as a module from the app's i18n file."""
        html = (config.STATIC / 'auth.html').read_text()
        self.assertEqual(html.count('<h1'), 1)
        self.assertIn('<main>', html)
        self.assertIn('<script type="module" src="/static/js/auth.js">', html)
        self.assertIn("from './i18n.js'", (config.STATIC / 'js' / 'auth.js').read_text())

    def test_negative_and_oversized_content_length(self):
        head = 'POST /api/auth/login HTTP/1.0\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: %s\r\n\r\n'
        self.assertIn(' 400 ', self.raw_http(head % '-1'))                              # answered at once, no wait for a body
        self.assertIn(' 400 ', self.raw_http(head % 'abc'))
        self.assertIn(' 413 ', self.raw_http(head % str(server.MAX_JSON_BYTES + 1)))
        self.assertIn(' 414 ', self.raw_http('GET /' + 'a' * 70000 + ' HTTP/1.0\r\n\r\n'))             # an error before the headers exist still answers

    def test_stalled_client_is_dropped(self):
        import socket, time
        self.assertEqual(server.Handler.timeout, server.SOCKET_TIMEOUT)
        with mock.patch.object(server.Handler, 'timeout', 0.3):
            s = socket.create_connection(('127.0.0.1', self.srv.server_port), timeout=5)
            s.sendall(b'POST /api/auth/login HTTP/1.0\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: 50\r\n\r\n{')   # promises 50 bytes, sends 1
            t0 = time.time()
            self.assertEqual(s.recv(100), b'')                                         # the server gave up and closed the connection
            self.assertLess(time.time() - t0, 4)
            s.close()

    def test_unknown_host_name_is_refused(self):
        import socket
        def status(host_line):
            s = socket.create_connection(('127.0.0.1', self.srv.server_port), timeout=5)
            try:
                s.sendall(f'GET /login HTTP/1.1\r\n{host_line}Connection: close\r\n\r\n'.encode())
                return s.recv(4096).split(b'\r\n', 1)[0].decode()
            finally:
                s.close()
        self.assertIn(' 200 ', status(f'Host: 127.0.0.1:{self.srv.server_port}\r\n'))
        self.assertIn(' 200 ', status('Host: localhost\r\n'))
        self.assertIn(' 400 ', status('Host: evil.example\r\n'))                       # DNS rebinding: another name, same port
        self.assertIn(' 400 ', status('Host: 127.0.0.1@evil.example\r\n'))
        self.assertIn(' 400 ', status(''))                                              # HTTP/1.1 without a Host header
        with mock.patch.object(config, 'ALLOWED_HOSTS', {'127.0.0.1', 'carlos.example.net'}):
            self.assertIn(' 200 ', status('Host: carlos.example.net\r\n'))             # the name the reverse proxy passes through
            self.assertTrue(server.host_allowed('Carlos.Example.NET:443'))
            self.assertFalse(server.host_allowed('localhost'))
            self.assertFalse(server.host_allowed(None))
            self.assertFalse(server.host_allowed('[::1]'))
        h = self.fake_handler()
        h.headers = {'X-Forwarded-Host': 'evil.example', 'X-Forwarded-Proto': 'https'}
        self.assertEqual(server.Handler.invite_url(h, 'tok'), f'https://{config.HOST}:{config.PORT}/invite/tok')   # not a link to evil.example

    def test_connections_past_the_thread_cap_get_503(self):
        import socket, time
        srv = server.BoundedServer(('127.0.0.1', 0), server.Handler, max_threads=1)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        with mock.patch.object(server.Handler, 'timeout', 5):
            held = socket.create_connection(('127.0.0.1', srv.server_port), timeout=5)   # its thread waits for the rest of the headers
            self.addCleanup(held.close)
            held.sendall(b'GET /login HTTP/1.1\r\nHost: 127.0.0.1\r\n')
            s = socket.create_connection(('127.0.0.1', srv.server_port), timeout=5)
            try:
                s.sendall(b'GET /login HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n')
                reply = s.recv(4096)
            finally:
                s.close()
            self.assertTrue(reply.startswith(b'HTTP/1.1 503 '), reply[:40])
            self.assertIn(b'{"error": "overloaded"}', reply)
            held.close()                                                                  # the slot comes back when the thread ends
            deadline = time.time() + 5
            while time.time() < deadline and self.raw_status(srv.server_port) != 200:
                time.sleep(0.05)
            self.assertEqual(self.raw_status(srv.server_port), 200)

    def raw_status(self, port):
        import socket
        s = socket.create_connection(('127.0.0.1', port), timeout=5)
        try:
            s.sendall(b'GET /login HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n')
            return int(s.recv(4096).split(b' ')[1])
        finally:
            s.close()

    def test_admin_password_minimum_and_common_passwords(self):
        with self.assertRaises(ValueError):
            auth.check_new_password('elevenchars', admin=True)                           # 11 characters: an admin needs 12
        auth.check_new_password('elevenchars')                                          # 11 is fine for a member
        auth.check_new_password('twelvechars!', admin=True)
        for common in ('Password', 'changeme', 'Administrator'):                        # refused at any length they reach
            with self.assertRaises(ValueError):
                auth.check_new_password(common)
        with self.assertRaises(ValueError):
            auth.check_new_password('administrator', admin=True)                       # 13 characters, still on the list
        _, cookie = self.login()
        self.assertEqual(self.req('POST', '/api/account/password', {'old': PASSWORD, 'new': 'short-pass1'}, token=None, cookie=cookie)[0], 400)
        self.assertEqual(self.login()[0], 200)                                          # the old password still works: nothing changed

    def test_data_directory_and_database_are_owner_only(self):
        import stat
        old = os.umask(0o022)
        self.addCleanup(os.umask, old)
        config.DATA_DIR.chmod(0o755)
        config.DB.chmod(0o644)
        server.secure_data_dir()
        self.assertEqual(stat.S_IMODE(config.DATA_DIR.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(config.DB.stat().st_mode), 0o600)
        probe = config.DATA_DIR / 'probe.txt'
        probe.write_text('x')                                                          # a file the process creates later: owner only
        self.assertEqual(stat.S_IMODE(probe.stat().st_mode), 0o600)

    def test_worker_and_capture_write_owner_only_files(self):
        import capture_listing, worker
        with mock.patch('os.umask') as umask, mock.patch.object(worker, 'refuse_shared_checkout', side_effect=SystemExit('stop')):
            with self.assertRaises(SystemExit):
                worker.main([])
        umask.assert_called_with(0o077)
        cap = config.DATA_DIR / 'capture.json'
        cap.write_text('{}')
        with mock.patch('os.umask') as umask, mock.patch.object(capture_listing, 'load_token', return_value='t'), \
                mock.patch.object(capture_listing, 'import_capture', side_effect=SystemExit('stop')):
            with self.assertRaises(SystemExit):
                capture_listing.main([str(cap), '--api', self.base])
        umask.assert_called_with(0o077)

    def test_quote_profile_keeps_only_the_insurance_keys(self):
        quote = {'vehicle_id': V_A, 'premium_status': 'QUOTE', 'annual_premium_eur': 850, 'insurer': 'Test Insurer', 'quote_date': fx.TODAY,
                 'source_id': SRC_QUOTE,
                 'quote_profile': {'cover': 'Teilkasko', 'deductible_eur': 150, 'sf_class': 'S', 'start_date': '2027-01-01',
                                   'holder_name': 'Max Muster', 'birth_date': '1980-01-01', 'postal_code': '10115', 'licence_date': '2000-01-01'}}
        st, body = self.agent('POST', 'insurance_data', quote)
        self.assertEqual(st, 201)
        stored = json.loads(self.sql('SELECT quote_profile FROM insurance_data WHERE id=?', (body['id'],))[0][0])
        self.assertEqual(stored, {'cover': 'Teilkasko', 'deductible_eur': 150, 'sf_class': 'S', 'start_date': '2027-01-01'})
        self.assertEqual(self.agent('POST', 'insurance_data', {**quote, 'quote_profile': '["Max Muster"]'})[0], 400)   # not an object

    def test_log_line_hides_invite_tokens_and_query(self):
        self.assertEqual(server.redact_log('"GET /invite/AbC-123_xyz HTTP/1.1" 200 -'), '"GET /invite/... HTTP/1.1" 200 -')
        self.assertEqual(server.redact_log('"GET /api/auth/invite/AbC-123_xyz HTTP/1.1" 200 -'), '"GET /api/auth/invite/... HTTP/1.1" 200 -')
        self.assertNotIn('secret', server.redact_log('"GET /api/tco?token=secret&annual_km=1 HTTP/1.1" 200 -'))

    def test_sqlite_error_text_only_for_agents(self):
        boom = sqlite3.OperationalError('no such column: secret_table.hidden_col')
        _, cookie = self.login()
        with mock.patch.object(server, 'model_tree', side_effect=boom):
            st, body = self.req('GET', '/api/models', token=None, cookie=cookie)
            self.assertEqual(st, 400)
            self.assertNotIn('hidden_col', json.dumps(body))                            # a browser gets no schema detail
            self.assertIn('hidden_col', self.req('GET', '/api/models')[1]['error'])     # an agent token still gets the exact text

    def test_storage_and_health_are_admin_only(self):
        _, c2 = self.second_account()
        for path in ('/api/storage', '/api/health'):
            self.assertEqual(self.req('GET', path, token=None, cookie=c2)[0], 403, path)
            self.assertEqual(self.req('GET', path)[0], 200, path)
        rt = self.run_token('CAPTURE')
        for path in ('/api/storage', '/api/health'):
            self.assertEqual(self.req('GET', path, token=rt)[0], 403, path)

    def test_request_token_reads_an_allow_list(self):
        """M3/N6: a research run reads the research endpoints; no request token reads the profile."""
        self.sql_write("INSERT INTO project_preferences (owner_id, preference_key, preference_value) VALUES (1, 'insurance_holder_birth_date', '1980-01-01'), (1, 'diy_jobs', 'oil and filters')")
        self.sql_write("UPDATE project_parameters SET postal_code='80331' WHERE owner_id=1")
        rt = self.run_token('CAPTURE')
        for path in ('/api/agent/todo', '/api/todo', '/api/agent/schema', '/api/models', '/api/vehicles', f'/api/vehicles/{V_A}', '/api/generations',
                     '/api/engines', '/api/sources', '/api/listings', f'/api/listings/{CAR_A}', '/api/tco', '/api/preferences'):
            self.assertEqual(self.req('GET', path, token=rt)[0], 200, path)
        for path in ('/api/parameters', '/api/ranking', '/api/storage', '/api/health', '/api/requests', '/api/ui/check', '/api/admin/users'):
            self.assertEqual(self.req('GET', path, token=rt)[0], 403, path)
        # what the open endpoints still carry of the profile: the DIY choices, not the person
        self.assertEqual({r['preference_key'] for r in self.req('GET', '/api/preferences', token=rt)[1]}, {'diy_jobs'})
        for path in ('/api/tco', '/api/listings'):
            body = self.req('GET', path, token=rt)[1]
            self.assertTrue({'postal_code', 'sf_class', 'driver_age', 'ranking_answers'}.isdisjoint(body['parameters']), path)
            self.assertIn('ownership_years', body['parameters'])
            self.assertNotIn('weights', body['ranking'])
        self.assertEqual(self.req('GET', '/api/tco', token=TOKEN)[1]['parameters']['postal_code'], '80331')   # the owner's own view is whole

    def test_request_token_is_a_curator_never_an_admin(self):
        """N3: the research token writes the catalogue (curator) but inherits no admin check."""
        from carlos import db
        def flags(**kw):
            h, c = self.fake_handler(**kw), db.connect()
            try:
                h.require(c)
            finally:
                c.close()
            return h.admin, h.curator
        self.assertEqual(flags(token=TOKEN), (True, True))
        self.assertEqual(flags(token=self.run_token('CAPTURE')), (False, True))
        self.assertEqual(flags(cookie=self.second_account()[1]), (False, False))
        c = db.connect()
        try:
            with self.assertRaises(server.NotAllowed):
                self.fake_handler(token=self.run_token('TAX')).require(c, admin=True)
        finally:
            c.close()

    def test_login_backoff_per_username_and_last_forwarded_hop(self):
        login = lambda ip, pw='wrong', user='admin': self.req('POST', '/api/auth/login', {'username': user, 'password': pw}, token=None,
                                                              headers={'X-Forwarded-For': f'6.6.6.6, {ip}'})[0]
        self.assertEqual(login('9.9.9.9'), 401)
        self.assertIn('9.9.9.9', auth.FAILS)                                             # the last hop (the proxy's), not 6.6.6.6
        self.assertNotIn('6.6.6.6', auth.FAILS)
        for i in range(auth.USER_MAX_FAILS - 1):                                         # rotating the address does not help against one username
            login(f'10.0.{i // 200}.{i % 200}')
        self.assertEqual(login('10.9.9.9', PASSWORD), 429)                               # locked for every address, even with the right password
        self.assertEqual(login('10.9.9.9', 'wrong', user='nobody'), 401)                 # other usernames are not affected
        auth.FAILS['u:admin'].update(until=0.0, last=0.0)
        self.assertEqual(login('10.9.9.8', PASSWORD), 200)

    def test_unknown_username_costs_a_scrypt_check(self):
        with mock.patch.object(auth, 'check_password', wraps=auth.check_password) as chk:
            self.assertEqual(self.login('nobody', 'x')[0], 401)
            self.assertEqual(chk.call_count, 1)                                          # same work as for a known name
            self.assertEqual(self.login('admin', 'x')[0], 401)
            self.assertEqual(chk.call_count, 2)
        self.assertFalse(auth.check_password(auth.DUMMY_HASH, 'carlos-dummy-password'))

    def test_password_change_ends_other_sessions_and_is_rate_limited(self):
        _, here = self.login(); _, other = self.login()
        self.assertEqual(self.req('POST', '/api/account/password', {'old': PASSWORD, 'new': 'a new password'}, token=None, cookie=here)[0], 200)
        self.assertEqual(self.req('GET', '/api/tco', token=None, cookie=here)[0], 200)   # the caller stays signed in
        self.assertEqual(self.req('GET', '/api/tco', token=None, cookie=other)[0], 401)  # every other session is gone
        for _ in range(auth.LOGIN_MAX_FAILS):
            self.assertEqual(self.req('POST', '/api/account/password', {'old': 'nope', 'new': 'another password'}, token=None, cookie=here)[0], 401)
        self.assertEqual(self.req('POST', '/api/account/password', {'old': 'a new password', 'new': 'another password'}, token=None, cookie=here)[0], 429)

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
        st, m = self.upload(fx.jpeg([(0xE0, b'p' * 20)]))
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
        self.assertTrue(dossier_path('Alpha-Hatch-Test-A1').exists())
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
        self.assertEqual(len(list((config.DB.parent / 'trash').rglob('x/b.jpg'))), 1)  # moved to the trash, not unlinked
        st, d = self.req('GET', f'/api/listings/{CAR_A}')   # a listing awaiting research stays readable
        self.assertEqual((st, d['vehicle_id'], d['research_levels']['variant']['state']), (200, None, 'incomplete'))
        self.assertEqual(self.req('GET', '/api/tco')[0], 200)
        self.assertEqual(research_reset.run(config.DB, apply=True, keep=1), {})   # idempotent
        # a listing awaiting research is queued by reference, not by an ad link (#194)
        self.assertEqual(self.req('POST', '/api/requests', {'url': f'carlos://listing/{CAR_A}'})[0], 201)
        self.assertEqual(self.req('POST', '/api/requests', {'url': 'carlos://listing/99999'})[0], 400)

    def test_research_reset_reliability_361(self):
        """#361: --reliability archives rel.* checks only (dry run first), keeps faults, --delete removes them."""
        import research_reset
        c = sqlite3.connect(config.DB)
        total0 = c.execute("SELECT count(*) FROM research_checks").fetchone()[0]
        for task in ('rel.ENGINE.adac', 'rel.HU.tuev', 'eng.code'):
            c.execute("INSERT INTO research_checks (engine_id, task, source_id, result, contract_version) VALUES (?, ?, ?, 'N/A', 9)",
                      (E_A, task, SRC_GUIDE))
        c.commit()
        live = lambda: c.execute("SELECT count(*) FROM research_checks WHERE task LIKE 'rel.%' AND archived=0").fetchone()[0]
        n = live()
        self.assertGreaterEqual(n, 2)
        self.assertEqual(research_reset.reset_reliability(config.DB), n)
        self.assertEqual(live(), n)   # dry run
        self.assertEqual(research_reset.reset_reliability(config.DB, apply=True), n)
        self.assertEqual(live(), 0)
        self.assertEqual(c.execute("SELECT count(*) FROM research_checks").fetchone()[0], total0 + 3)   # archived, not deleted
        self.assertEqual(c.execute("SELECT count(*) FROM research_checks WHERE task='eng.code' AND archived=0").fetchone()[0], 1)
        research_reset.reset_reliability(config.DB, apply=True, delete=True)
        self.assertEqual(c.execute("SELECT count(*) FROM research_checks WHERE task LIKE 'rel.%'").fetchone()[0], 0)
        c.close()

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


    def test_review_fixes_on_write_and_read(self):
        """Code review round 1: a rating's values are checked on write, a saved filter is checked on save, a decision keeps an owned
        car's status, a negative limit is clamped, a refused duplicate request leaves no transaction open, reliability_items are not read."""
        url = 'https://www.tuev-verband.de/x'
        self.assertEqual(self.agent('POST', 'source_keys', {'source_key': 'TUEV_REPORT', 'external_key': 'Polo', 'generation_id': G1, 'url': url,
                                                            'source_id': fx.SRC_HU, 'checked_date': '2026-11-10'})[0], 201)
        R = {'source_key': 'TUEV_REPORT', 'external_key': 'polo', 'edition': '2026', 'age_from': 6, 'age_to': 7, 'value_num': 5,
             'class_average': 10, 'url': url, 'source_id': fx.SRC_HU, 'checked_date': '2026-11-10'}
        self.assertEqual(self.agent('POST', 'source_ratings', {**R, 'class_average': 0})[0], 400)     # no average to measure against
        self.assertEqual(self.agent('POST', 'source_ratings', R)[0], 201)
        A = {'source_key': 'ADAC_PANNENSTATISTIK', 'external_key': 'Polo', 'generation_id': G1, 'url': url, 'source_id': fx.SRC_HU,
             'checked_date': '2026-11-10'}
        self.assertEqual(self.agent('POST', 'source_keys', A)[0], 201)
        B = {'source_key': 'ADAC_PANNENSTATISTIK', 'external_key': 'polo', 'edition': '2026', 'reg_year': 2015, 'url': url,
             'source_id': fx.SRC_HU, 'checked_date': '2026-11-10'}
        self.assertEqual(self.agent('POST', 'source_ratings', {**B, 'band': 6})[0], 400)              # the bands are 1-5
        self.assertEqual(self.agent('POST', 'source_ratings', {**B, 'band': 2})[0], 201)
        # saved filters the ranking can read
        self.assertEqual(self.req('POST', '/api/preferences', {'filter_hu_months': 'soon'})[0], 400)
        self.assertEqual(self.req('POST', '/api/preferences', {'filter_seller': 'BOTH'})[0], 400)
        self.assertEqual(self.req('POST', '/api/preferences', {'filter_hu_months': 12, 'filter_seller': 'DEALER'})[0], 200)
        self.assertTrue(self.units())
        # a decision on a bought car leaves its status alone
        self.sql_write("UPDATE listings SET listing_status='OWNED' WHERE id=?", (CAR_B,))
        self.assertEqual(self.ui('POST', f'decision/{CAR_B}', {'decision': 'reject', 'reason': 'too far'})[0], 201)
        self.assertEqual(self.sql('SELECT listing_status, verdict FROM listings WHERE id=?', (CAR_B,))[0][0], 'OWNED')
        # a negative limit returns one row, not every row
        st, admin = self.login()
        self.assertGreater(len(self.req('GET', '/api/admin/changes?limit=1000', token=None, cookie=admin)[1]), 1)
        self.assertEqual(len(self.req('GET', '/api/admin/changes?limit=-5', token=None, cookie=admin)[1]), 1)
        # a refused duplicate leaves no transaction open: the next request still gets in
        uid2, t2 = self.second_account()
        self.assertEqual(self.req('POST', '/api/requests', {'url': 'https://www.example.com/car/1'}, token=None, cookie=t2)[0], 201)
        self.assertEqual(self.req('POST', '/api/requests', {'url': 'https://www.example.com/car/1'}, token=None, cookie=t2)[0], 400)
        self.assertEqual(self.req('POST', '/api/requests', {'url': 'https://www.example.com/car/2'}, token=None, cookie=t2)[0], 201)
        # reliability_items (retired) are not read: the listing's reliability is empty
        self.assertEqual(self.req('GET', f'/api/listings/{CAR_A}')[1]['reliability'], [])

if __name__ == '__main__':
    unittest.main()
