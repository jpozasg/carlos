"""Research staging (#253 phase P2): a RESEARCH_A/B or ARBITER token's /api/agent writes land in research_findings with negative
ids and never in the catalogue. Synthetic database (tests/fixture.py)."""
import json, sqlite3, tempfile, threading, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
import migrate
from carlos import auth, config, server, staging
from tests import fixture as fx
from tests.fixture import CAR_A, ADMIN, E_A, E_B, G1, V_A, TOKEN

SRC = {'title': 'Guide AM14', 'url': 'https://example.test/guide', 'source_type': 'buying_guide', 'quality': 'C', 'accessed_date': fx.TODAY,
       'supports': 'Faults', 'limitations': 'Single guide', 'engine_id': E_A}
FAULT = {'engine_id': E_A, 'component': 'Cylinder head gasket', 'component_code': 'ENGINE_INTERNALS', 'part': 'ENGINE', 'consequence': 'ENGINE_DAMAGE', 'existence': 'CONFIRMED',
         'frequency_band': 'common', 'shape': 'WEAR_KM', 'parts_eur': 300, 'labor_eur': 600}


class StagingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.Handler.log_message = lambda *a: None
        cls.srv = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f'http://127.0.0.1:{cls.srv.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        config.DATA_DIR, config.DB, config.MD_DIR, config.MEDIA_DIR = d, d / 'cars.sqlite', d / 'dossiers', d / 'media'
        fx.build(config.DB)
        auth.FAILS.clear()
        self.addCleanup(self.tmp.cleanup)
        self.sql("INSERT INTO research_requests (id, owner_id, url, status, listing_id, unit) VALUES (100, ?, 'u', 'WAITING', ?, 'CAPTURE')", (ADMIN, CAR_A))
        self.tokens = {}
        for rid, unit in ((101, 'RESEARCH_A'), (102, 'RESEARCH_B'), (103, 'ARBITER')):
            self.tokens[unit] = f'tok-{unit}'
            self.sql("INSERT INTO research_requests (id, owner_id, url, status, listing_id, parent_id, unit, claimed_at, request_token_hash, scope) "
                     "VALUES (?, ?, 'u', 'RUNNING', ?, 100, ?, datetime('now'), ?, ?)",
                     (rid, ADMIN, CAR_A, unit, auth.digest(self.tokens[unit]), json.dumps([['engine_id', E_A], ['generation_id', G1], ['vehicle_id', V_A]])))

    def sql(self, q, args=()):
        c = sqlite3.connect(config.DB)
        try:
            r = c.execute(q, args).fetchall(); c.commit(); return r
        finally:
            c.close()

    def api(self, method, path, body=None, unit='RESEARCH_A', token=None):
        h = {'Content-Type': 'application/json', 'Authorization': f'Bearer {token or self.tokens.get(unit, TOKEN)}'}
        r = urllib.request.Request(f'{self.base}/api/{path}', json.dumps(body).encode() if body is not None else None, h, method=method)
        try:
            resp = urllib.request.urlopen(r); return resp.status, json.load(resp)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def stage(self, table, body, unit='RESEARCH_A'):
        return self.api('POST', f'agent/{table}', body, unit)

    def counts(self):
        return {t: self.sql(f'SELECT count(*) FROM {t}')[0][0] for t in ('sources', 'faults', 'engines', 'gearboxes', 'listings', 'listing_events')}

    def test_writes_go_to_staging_with_negative_ids(self):
        before = self.counts()
        st, s = self.stage('sources', SRC)
        self.assertEqual((st, s['staged']), (201, True)); self.assertLess(s['id'], 0)
        st, f = self.stage('faults', {**FAULT, 'source_id': s['id']})
        self.assertEqual(st, 201, f); self.assertLess(f['id'], 0)
        self.assertEqual(self.counts(), before)                                    # no real row was written
        self.assertEqual(self.sql("SELECT kind, run, key, level, level_id FROM research_findings ORDER BY id"),
                         [('source', 'A', 'src:https://example.test/guide', 'engine', E_A), ('fault', 'A', 'fault:ENGINE:ENGINE_INTERNALS', 'engine', E_A)])
        self.assertEqual(self.stage('sources', SRC)[1], {**s, 'existing': True})   # a source is filed once per run
        # the arbiter is run C; another request token is not a staged run for the legacy units
        self.assertEqual(self.stage('sources', {**SRC, 'url': 'https://example.test/c'}, 'ARBITER')[0], 201)
        self.assertEqual(self.sql("SELECT run FROM research_findings ORDER BY id DESC LIMIT 1"), [('C',)])

    def test_staged_references(self):
        _, s = self.stage('sources', SRC)
        _, other = self.stage('sources', {**SRC, 'url': 'https://example.test/b'}, 'RESEARCH_B')
        self.assertEqual(self.stage('faults', {**FAULT, 'source_id': other['id']})[0], 400)         # run B's source is not visible to run A
        self.assertEqual(self.stage('faults', {**FAULT, 'source_id': -999})[0], 400)
        self.assertEqual(self.stage('faults', {**FAULT, 'source_id': s['id'], 'gearbox_id': -1, 'engine_id': None})[0], 400)  # -1 is a source, not a gearbox
        st, gb = self.stage('gearboxes', {'code': 'XG5', 'type': 'MANUAL'})
        self.assertEqual(st, 201, gb)
        # a staged level as the level of a fault
        st, f = self.stage('faults', {**FAULT, 'engine_id': None, 'gearbox_id': gb['id'], 'component': 'Clutch', 'component_code': 'CLUTCH', 'part': 'GEARBOX', 'source_id': s['id']})
        self.assertEqual(st, 201, f)
        self.assertEqual(self.sql('SELECT level, level_id FROM research_findings WHERE id=?', (-f['id'],)), [('gearbox', gb['id'])])

    def test_refusals(self):
        _, s = self.stage('sources', SRC)
        for table, body in (('listings', {'vehicle_id': V_A}), ('listing_events', {'listing_id': CAR_A}), ('reliability_items', {'part': 'ENGINE'}),
                            ('insurance_data', {'vehicle_id': V_A}), ('engines', {'code': 'NEW', 'fuel_type': 'Petrol'})):
            self.assertEqual(self.stage(table, body)[0], 403, table)
        # engine E_B is outside the run's scope
        st, e = self.stage('faults', {**FAULT, 'engine_id': E_B, 'source_id': s['id']})
        self.assertEqual(st, 403, e)
        # a required column is checked now, not at the merge
        self.assertEqual(self.stage('faults', {**FAULT, 'source_id': s['id'], 'consequence': None})[0], 400)
        self.assertEqual(self.stage('faults', {**FAULT, 'source_id': s['id'], 'component_code': 'CLUTCH'})[0], 400)   # a gearbox code on an engine fault
        self.assertEqual(self.stage('faults', {**{k: v for k, v in FAULT.items() if k != 'component_code'}, 'source_id': s['id']})[0], 400)
        self.assertEqual(self.api('POST', 'agent/export-md', {}, 'RESEARCH_A')[0], 403)

    def test_duplicates(self):
        _, s = self.stage('sources', SRC)
        st, f = self.stage('faults', {**FAULT, 'source_id': s['id']})
        st, dup = self.stage('faults', {**FAULT, 'component': 'Cylinder head gasket leak (coolant loss)', 'source_id': s['id']})
        self.assertEqual(st, 409); self.assertIn(str(f['id']), dup['error'])
        # distinct_of plus a reason is accepted
        st, ok = self.stage('faults', {**FAULT, 'component': 'Cylinder head gasket leak (coolant loss)', 'source_id': s['id'], 'distinct_of': [f['id']],
                                       'notes': 'The tensioner fails on its own, the chain itself is fine'})
        self.assertEqual(st, 201, ok)
        # a real fault on the same level: the #221 409 is unchanged
        self.sql("INSERT INTO faults (engine_id, component, part, consequence, existence, source_id, parts_eur, labor_eur) VALUES (?, 'Water pump leak', 'ENGINE', 'COST', 'CONFIRMED', ?, 100, 100)", (E_A, fx.SRC_GUIDE))
        st, real = self.stage('faults', {**FAULT, 'component': 'Water pump leak', 'component_code': 'COOLING', 'source_id': s['id']})
        self.assertEqual(st, 409, real); self.assertIn('faults #', real['error'])
        # unique kinds: the same job twice is one finding
        job = {'engine_id': E_A, 'item': 'Wiper blades', 'job': 'WIPERS', 'interval_km': 15000, 'reference_cost_eur': 90, 'source_id': s['id']}
        st, j = self.stage('maintenance_items', job); self.assertEqual(st, 201, j)
        self.assertEqual(self.stage('maintenance_items', job)[0], 409)

    def test_patch_staged_and_real_rows(self):
        _, s = self.stage('sources', SRC)
        _, f = self.stage('faults', {**FAULT, 'source_id': s['id']})
        self.assertEqual(self.api('PATCH', f'agent/faults/{f["id"]}', {'parts_eur': 450})[0], 200)
        self.assertEqual(json.loads(self.sql('SELECT payload FROM research_findings WHERE id=?', (-f['id'],))[0][0])['parts_eur'], 450)
        # a PATCH of a real row is one patch finding; the next one merges into it
        st, a = self.api('PATCH', f'agent/engines/{E_A}', {'status': 'PARTIAL'})
        self.assertEqual(st, 200, a)
        st, b = self.api('PATCH', f'agent/engines/{E_A}', {'power_kw': 75})
        self.assertEqual(b['id'], a['id'])
        self.assertEqual(json.loads(self.sql('SELECT payload FROM research_findings WHERE id=?', (-a['id'],))[0][0]), {'status': 'PARTIAL', 'power_kw': 75})
        self.assertEqual(self.sql('SELECT status, power_kw FROM engines WHERE id=?', (E_A,)), [('VERIFIED', 74)])
        self.assertEqual(self.api('PATCH', f'agent/engines/{E_B}', {'status': 'PARTIAL'})[0], 403)   # outside the scope
        self.assertEqual(self.api('PATCH', 'agent/engines/9999', {'status': 'PARTIAL'})[0], 404)
        # another run's staged row cannot be patched
        self.assertEqual(self.api('PATCH', f'agent/faults/{f["id"]}', {'parts_eur': 1}, 'RESEARCH_B')[0], 400)

    def test_runs_are_independent(self):
        self.stage('sources', SRC)
        st, view = self.api('GET', 'agent/stage', unit='RESEARCH_B')
        self.assertEqual((st, view['findings'], view['run']), (200, [], 'B'))
        st, view = self.api('GET', 'agent/stage', unit='RESEARCH_A')
        self.assertEqual([x['kind'] for x in view['findings']], ['source'])
        self.assertEqual(self.api('GET', 'agent/stage', token=TOKEN)[0], 403)                     # an admin token has no staging area

    def test_dry_grade_leaves_the_catalogue_alone(self):
        missing0 = self.api('GET', 'agent/stage')[1]['missing']
        self.assertIn('gen.baseline', missing0)
        _, s = self.stage('sources', {**SRC, 'engine_id': None, 'generation_id': G1, 'quality': 'B', 'url': 'https://example.test/tuev'})
        st, t = self.stage('research_checks', {'generation_id': G1, 'task': 'gen.baseline', 'result': 'N/A', 'source_id': s['id'],
                                               'checked_date': '2026-11-10', 'notes': 'too new for the TÜV and ADAC tables'})
        self.assertEqual(st, 201, t)
        before = {t: self.sql(f'SELECT count(*) FROM {t}')[0][0] for t in ('research_checks', 'sources', 'research_findings')}
        missing1 = self.api('GET', 'agent/stage')[1]['missing']
        self.assertNotIn('gen.baseline', missing1)
        self.assertEqual(set(missing0) - set(missing1), {'gen.baseline'})
        self.assertEqual({t: self.sql(f'SELECT count(*) FROM {t}')[0][0] for t in before}, before)  # rolled back: nothing real was written
        # run B has staged nothing: it still lacks the item; the staged to-do reads the run's own staging
        self.assertIn('gen.baseline', self.api('GET', 'agent/stage', unit='RESEARCH_B')[1]['missing'])
        st, td = self.api('GET', 'agent/todo')
        self.assertEqual(st, 200)
        mine = next(m for m in td['models'] if m['vehicle_id'] == V_A)['todo']
        self.assertFalse(any('gen.baseline' in x for x in mine), mine)

    def test_migration_040_keeps_every_038_row(self):
        """The 038 table (its CREATE statement, read from the migration) with rows survives the rebuild; scope starts NULL."""
        m38 = (config.ROOT / 'migrations' / '038_insurance_unit.sql').read_text(encoding='utf-8')
        start = m38.index('CREATE TABLE')
        create = m38[start:m38.index(');', start) + 1].replace('research_requests_new', 'research_requests')
        c = sqlite3.connect(':memory:')
        c.executescript('CREATE TABLE users (id INTEGER PRIMARY KEY); CREATE TABLE listings (id INTEGER PRIMARY KEY); CREATE TABLE review_flags (id INTEGER PRIMARY KEY);'
                        + create + ';')
        c.execute("INSERT INTO research_requests (owner_id, url, status, unit, level_id, missing, attempts) VALUES (1, 'u', 'DONE', 'ENGINE', 7, '[\"eng.oil\"]', 2)")
        before = c.execute('SELECT * FROM research_requests').fetchall()
        c.executescript((config.ROOT / 'migrations' / '040_research_staging.sql').read_text(encoding='utf-8'))
        self.assertEqual(c.execute('SELECT * FROM research_requests').fetchall(), [r + (None,) for r in before])
        c.execute("INSERT INTO research_requests (owner_id, url, unit, scope) VALUES (1, 'u', 'RESEARCH_A', '[[\"engine_id\", 1]]')")
        with self.assertRaises(sqlite3.IntegrityError):
            c.execute("INSERT INTO research_requests (owner_id, url, unit) VALUES (1, 'u', 'NOPE')")
        c.close()


if __name__ == '__main__':
    unittest.main()
