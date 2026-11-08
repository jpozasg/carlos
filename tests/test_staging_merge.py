"""Staging merge (#253 phase P4): the agreed and arbitrated findings of two runs are written through agent_write by POST /api/agent/merge.
The research_matches rows are built by hand here (the comparison is P3)."""
import json, unittest
from carlos import auth, config
from tests import fixture as fx, test_staging as ts
from tests.fixture import CAR_A, ADMIN, E_A, E_B, V_A, TOKEN

FAULT, SRC = ts.FAULT, ts.SRC


class MergeTest(ts.StagingTest):
    def setUp(self):
        super().setUp()
        self.sql("INSERT INTO research_requests (id, owner_id, url, status, listing_id, parent_id, unit, claimed_at, request_token_hash) "
                 "VALUES (104, ?, 'u', 'RUNNING', ?, 100, 'MERGE', datetime('now'), ?)", (ADMIN, CAR_A, auth.digest('tok-MERGE')))
        self.tokens['MERGE'] = 'tok-MERGE'
        self.src = {'a': self.stage('sources', {**SRC, 'url': 'https://example.test/a'}, 'RESEARCH_A')[1]['id'],
                    'b': self.stage('sources', {**SRC, 'url': 'https://example.test/b'}, 'RESEARCH_B')[1]['id']}

    def f(self, run, table, body):
        st, r = self.stage(table, {**body, **({'source_id': self.src[run]} if table != 'engines' else {})}, 'RESEARCH_A' if run == 'a' else 'RESEARCH_B')
        self.assertEqual(st, 201, r)
        return -r['id']

    def match(self, kind, key, a=None, b=None, outcome='AGREED', **kw):
        cols = {'parent_id': 100, 'kind': kind, 'key': key, 'a_id': a, 'b_id': b, 'outcome': outcome, **kw}
        self.sql(f'INSERT INTO research_matches ({",".join(cols)}) VALUES ({",".join("?" * len(cols))})', list(cols.values()))

    def merge(self):
        st, r = self.api('POST', 'agent/merge', {}, 'MERGE')
        self.assertEqual(st, 200, r)
        return r

    def test_agreed_takes_the_less_favourable_figure_and_cites_both_runs(self):
        a = self.f('a', 'faults', {**FAULT, 'frequency_band': 'common', 'parts_eur': 300, 'labor_eur': 600})
        b = self.f('b', 'faults', {**FAULT, 'frequency_band': 'widespread', 'parts_eur': 300, 'labor_eur': 600})
        self.match('fault', 'fault:ENGINE:ENGINE_INTERNALS', a, b)
        before = self.sql('SELECT count(*) FROM faults')[0][0]
        r = self.merge()
        self.assertEqual((r['written'], r['skipped'], r['flags']), (1, [], []))
        row = self.sql("SELECT frequency_band, notes, source_id FROM faults ORDER BY id DESC LIMIT 1")[0]
        self.assertEqual(self.sql('SELECT count(*) FROM faults')[0][0], before + 1)
        self.assertEqual(row[0], 'widespread')
        self.assertIn('Second independent run agreed', row[1]); self.assertIn('example.test/a', row[1]); self.assertIn('example.test/b', row[1])
        self.assertEqual(self.sql('SELECT url FROM sources WHERE id=?', (row[2],)), [('https://example.test/b',)])
        self.assertEqual(self.sql("SELECT count(*) FROM change_log WHERE table_name='faults' AND action='insert'")[0][0], 1)
        self.assertEqual(self.sql('SELECT status FROM research_findings WHERE id=?', (a,))[0][0], 'SKIPPED')
        self.assertEqual(self.sql('SELECT status FROM research_findings WHERE id=?', (b,))[0][0], 'MERGED')

    def test_merge_twice_writes_nothing(self):
        a = self.f('a', 'faults', FAULT)
        self.match('fault', 'k', a, None, 'ONLY_A')
        self.assertEqual(self.merge()['written'], 1)
        n = {t: self.sql(f'SELECT count(*) FROM {t}')[0][0] for t in ('faults', 'sources', 'change_log')}
        self.assertEqual(self.merge()['written'], 0)
        self.assertEqual({t: self.sql(f'SELECT count(*) FROM {t}')[0][0] for t in n}, n)
        self.assertIn('Found by one of two', self.sql('SELECT notes FROM faults ORDER BY id DESC LIMIT 1')[0][0])

    def test_verdicts(self):
        base = self.sql('SELECT count(*) FROM faults')[0][0]
        gasket = self.f('a', 'faults', FAULT)
        leak = self.f('b', 'faults', {**FAULT, 'component': 'Cylinder head gasket leak (coolant loss)'})
        self.match('fault', 'fault:ENGINE:ENGINE_INTERNALS', gasket, leak, 'DISPUTED', material=1, verdict='BOTH', verdict_reason='The leak is a separate failure from the blown gasket')
        pump = self.f('a', 'faults', {**FAULT, 'component': 'Water pump', 'component_code': 'COOLING'})
        pump_b = self.f('b', 'faults', {**FAULT, 'component': 'Water pump leak', 'component_code': 'COOLING', 'frequency_band': 'rare'})
        self.match('fault', 'fault:ENGINE:COOLING', pump, pump_b, 'DISPUTED', material=1, verdict='NEITHER', verdict_reason='no evidence for this engine')
        # OWN: the arbiter's staged finding is written
        own = self.f('a', 'faults', {**FAULT, 'component': 'Oil pump', 'component_code': 'OIL_LEAK'})
        self.match('fault', 'fault:ENGINE:OIL_LEAK', own, None, 'ONLY_A', material=1)   # open dispute: the arbiter may stage its key
        st, o = self.stage('faults', {**FAULT, 'component': 'Oil pump drive', 'component_code': 'OIL_LEAK', 'source_id': self.stage('sources', {**SRC, 'url': 'https://example.test/c'}, 'ARBITER')[1]['id']}, 'ARBITER')
        self.assertEqual(st, 201, o)
        self.sql("UPDATE research_matches SET verdict='OWN', verdict_id=?, verdict_reason='x' WHERE key='fault:ENGINE:OIL_LEAK'", (-o['id'],))
        r = self.merge()
        rows = self.sql('SELECT component, notes FROM faults ORDER BY id')[-3:-1]
        self.assertEqual(self.sql('SELECT count(*) FROM faults')[0][0], base + 3)
        self.assertEqual(rows[0][0], 'Cylinder head gasket')
        self.assertTrue(rows[1][1].startswith('Distinct from fault #'), rows[1][1])
        self.assertEqual([s['reason'] for s in r['skipped']], ['rejected by the arbiter: no evidence for this engine'])
        self.assertEqual(self.sql('SELECT count(*) FROM faults WHERE component LIKE \'Water pump%\'')[0][0], 0)
        self.assertEqual(self.sql('SELECT component FROM faults ORDER BY id DESC LIMIT 1'), [('Oil pump drive',)])

    def test_unresolved_material_disputes_flag_and_identity_stays_unwritten(self):
        a = self.f('a', 'faults', FAULT)
        st, pa = self.api('PATCH', f'agent/engines/{E_A}', {'power_kw': 99}, 'RESEARCH_A')
        st, pb = self.api('PATCH', f'agent/engines/{E_A}', {'power_kw': 77}, 'RESEARCH_B')
        self.match('fault', 'f', a, None, 'ONLY_A', material=1)
        self.match('patch', f'patch:engines:{E_A}', -pa['id'], -pb['id'], 'DISPUTED', material=1,
                   diffs=json.dumps([{'field': 'power_kw', 'a': 99, 'b': 77, 'rule': 'equal'}]))
        r = self.merge()
        self.assertEqual(len(r['flags']), 2)
        self.assertEqual(self.sql('SELECT power_kw FROM engines WHERE id=?', (E_A,)), [(74,)])      # identity left alone
        flags = self.sql("SELECT kind, what, why, created_by, engine_id FROM review_flags ORDER BY id")
        self.assertEqual({x[0] for x in flags}, {'SOURCES_DISAGREE'})
        pf = next(x for x in flags if 'power_kw' in x[1])
        self.assertIn('power_kw 99', pf[1]); self.assertIn('power_kw 77', pf[1])
        self.assertEqual(pf[3], 'merge of request #100'); self.assertEqual(pf[4], E_A)
        self.assertEqual([s['key'] for s in r['skipped']], [f'patch:engines:{E_A}'])

    def test_guard_conflict_with_a_real_row_is_skipped(self):
        self.sql("INSERT INTO faults (engine_id, component, component_code, part, consequence, existence, source_id, parts_eur, labor_eur) "
                 "VALUES (?, 'Cylinder head gasket', 'ENGINE_INTERNALS', 'ENGINE', 'COST', 'CONFIRMED', ?, 100, 100)", (E_A, fx.SRC_GUIDE))
        # the staging write refuses a duplicate of a real row, so stage a different one, then make it collide in the catalogue before the merge
        a = self.f('a', 'faults', {**FAULT, 'component': 'Oil pump', 'component_code': 'OIL_LEAK'})
        self.sql("INSERT INTO faults (engine_id, component, component_code, part, consequence, existence, source_id, parts_eur, labor_eur) "
                 "VALUES (?, 'Oil pump failure', 'OIL_LEAK', 'ENGINE', 'COST', 'CONFIRMED', ?, 100, 100)", (E_A, fx.SRC_GUIDE))
        self.match('fault', 'k', a, None, 'ONLY_A')
        n = self.sql('SELECT count(*) FROM faults')[0][0]
        r = self.merge()
        self.assertEqual(self.sql('SELECT count(*) FROM faults')[0][0], n)
        self.assertRegex(r['skipped'][0]['reason'], r'^exists as faults #\d+$')

    def test_staged_levels_and_relink(self):
        st, g = self.stage('gearboxes', {'code': 'NEWBOX', 'type': 'MANUAL'}); self.assertEqual(st, 201, g)
        self.sql("INSERT INTO gearboxes (code, type) VALUES ('NEWBOX', 'MANUAL')")                  # the catalogue got it meanwhile
        fa = self.f('a', 'faults', {**FAULT, 'engine_id': None, 'gearbox_id': g['id'], 'component': 'Clutch', 'component_code': 'CLUTCH', 'part': 'GEARBOX'})
        self.match('level', 'lvl:gearboxes:NEWBOX', -g['id'], None, 'ONLY_A')
        self.match('fault', 'k', fa, None, 'ONLY_A')
        boxes = self.sql('SELECT count(*) FROM gearboxes')[0][0]
        self.merge()
        self.assertEqual(self.sql('SELECT count(*) FROM gearboxes')[0][0], boxes)
        self.assertEqual(self.sql("SELECT g.code FROM faults f JOIN gearboxes g ON g.id=f.gearbox_id WHERE f.component='Clutch'"), [('NEWBOX',)])
        # the shell engine turns out to be the catalogue's engine: the variant is relinked, the shell is named, nothing is deleted
        code, kw = self.sql('SELECT code, power_kw FROM engines WHERE id=?', (E_B,))[0]
        _, p = self.api('PATCH', f'agent/engines/{E_A}', {'code': code, 'power_kw': kw}, 'RESEARCH_A')
        self.match('patch', f'patch:engines:{E_A}', -p['id'], None, 'ONLY_A')
        r = self.merge()
        self.assertEqual(r['orphans'], [{'engine_id': E_A, 'relinked_to': E_B}])
        self.assertEqual(self.sql('SELECT engine_id FROM vehicles WHERE id=?', (V_A,)), [(E_B,)])
        self.assertEqual(self.sql('SELECT count(*) FROM engines WHERE id=?', (E_A,)), [(1,)])

    def test_only_the_merge_unit_may_merge(self):
        for unit in ('RESEARCH_A', 'ARBITER'):
            self.assertEqual(self.api('POST', 'agent/merge', {}, unit)[0], 403)
        self.assertEqual(self.api('POST', 'agent/merge', {}, token=TOKEN)[0], 403)
        self.assertEqual(self.api('POST', 'agent/merge', {}, 'MERGE')[0], 400)                       # nothing was compared

    def test_job_checks_and_flags_are_unions(self):
        ja = self.f('a', 'maintenance_items', {'engine_id': E_A, 'item': 'Wiper blades', 'job': 'WIPERS', 'interval_km': 20000, 'reference_cost_eur': 90})
        jb = self.f('b', 'maintenance_items', {'engine_id': E_A, 'item': 'Wiper blades', 'job': 'WIPERS', 'interval_km': 15000, 'reference_cost_eur': 80})
        self.match('job', 'job:WIPERS', ja, jb)
        self.merge()
        self.assertEqual(self.sql("SELECT interval_km, reference_cost_eur FROM maintenance_items WHERE job='WIPERS'"), [(15000, 80.0)])   # the shorter interval


for _n in dir(ts.StagingTest):  # the inherited staging tests run in their own module
    if _n.startswith('test_'):
        setattr(MergeTest, _n, None)


if __name__ == '__main__':
    unittest.main()
