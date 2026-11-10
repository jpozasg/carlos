"""Staging compare and the arbiter interface (#253 phase P3): pairing, tolerances, material disputes, agreement, disputes API."""
import json, sqlite3, unittest
from carlos import config, staging
from carlos.db import connect
from tests import test_staging as ts
from tests.fixture import E_A, TOKEN

BASE = {'engine_id': E_A, 'part': 'ENGINE', 'consequence': 'COST', 'existence': 'CONFIRMED', 'shape': 'WEAR_KM'}


class CompareTest(unittest.TestCase):
    # the HTTP fixture of the staging tests, without running them again
    setUpClass = classmethod(ts.StagingTest.setUpClass.__func__)
    tearDownClass = classmethod(ts.StagingTest.tearDownClass.__func__)
    setUp, sql, api, stage = ts.StagingTest.setUp, ts.StagingTest.sql, ts.StagingTest.api, ts.StagingTest.stage

    def fault(self, unit, comp, code, band, parts, labor, **kw):
        if not hasattr(self, 'src'):
            self.src = {}
        if unit not in self.src:
            self.src[unit] = self.stage('sources', {**ts.SRC, 'url': f'https://example.test/{unit}'}, unit)[1]['id']
        st, f = self.stage('faults', {**BASE, 'component': comp, 'component_code': code, 'frequency_band': band, 'parts_eur': parts,
                                      'labor_eur': labor, 'source_id': self.src[unit], **kw}, unit)
        self.assertEqual(st, 201, f)
        return f['id']

    def pair(self, a, b, code, band=('common', 'common'), money=((300, 600), (350, 750)), **kw):
        self.fault('RESEARCH_A', a, code, band[0], *money[0], **kw)
        self.fault('RESEARCH_B', b, code, band[1], *money[1], **kw)

    def run_compare(self):
        c = connect()
        try:
            return staging.compare(c, 100)
        finally:
            c.close()

    def match(self, key_part):
        r = self.sql("SELECT outcome, material, diffs FROM research_matches WHERE key LIKE ?", (f'%{key_part}%',))
        self.assertEqual(len(r), 1, (key_part, r))
        return r[0][0], r[0][1], [d['field'] for d in json.loads(r[0][2] or '[]')]

    def build(self):
        self.pair('Cylinder head gasket', 'Head gasket failure', 'ENGINE_INTERNALS')                                   # within 30 %: agreed
        self.pair('Camshaft sprocket stretch', 'Sprocket tensioner failure', 'TIMING_CHAIN', ('widespread', 'rare'))            # 3 bands apart
        self.pair('Water pump leak', 'Water pump seepage', 'COOLING', money=((400, 600), (500, 750)))                   # 1000 vs 1250 agreed
        self.pair('Ignition coil failure', 'Ignition coil fault', 'IGNITION', money=((400, 600), (600, 900)))           # 1000 vs 1500
        self.pair('Exhaust gas recirculation valve', 'Particulate filter blocked', 'EMISSIONS')                         # one each: wording differs
        self.fault('RESEARCH_A', 'Fuel pump relay', 'FUEL_SYSTEM', 'rare', 20, 30)                                      # cheap and rare: not material
        self.fault('RESEARCH_B', 'Turbocharger bearing failure', 'TURBO', 'common', 400, 400)                           # one-sided, common
        a = self.stage('sources', {**ts.SRC, 'engine_id': None, 'generation_id': ts.G1, 'url': 'https://example.test/a'}, 'RESEARCH_A')[1]['id']
        self.assertEqual(self.api('PATCH', f'agent/engines/{E_A}', {'power_kw': 75}, 'RESEARCH_A')[0], 200)
        self.assertEqual(self.api('PATCH', f'agent/engines/{E_A}', {'power_kw': 80}, 'RESEARCH_B')[0], 200)
        return self.run_compare()

    def test_outcomes_and_material(self):
        out = self.build()
        self.assertEqual(self.match('ENGINE_INTERNALS'), ('AGREED', 0, []))
        self.assertEqual(self.match('TIMING_CHAIN'), ('DISPUTED', 1, ['frequency_band']))
        self.assertEqual(self.match('COOLING'), ('AGREED', 0, []))
        self.assertEqual(self.match('IGNITION'), ('DISPUTED', 1, ['price']))
        self.assertEqual(self.match('EMISSIONS'), ('DISPUTED', 1, ['component']))
        self.assertEqual(self.match('FUEL_SYSTEM'), ('ONLY_A', 0, []))
        self.assertEqual(self.match('TURBO'), ('ONLY_B', 1, []))
        self.assertEqual(self.match('patch:engines'), ('DISPUTED', 1, ['power_kw']))
        self.assertEqual((out['matches'], out['material']), (8, 5))
        self.assertEqual(out['agreement'], round(2 / 8, 4))
        self.assertEqual(out['per_kind']['fault']['agreement'], round(2 / 7, 4))

    def test_compare_is_idempotent(self):
        first = self.build()
        n = self.sql('SELECT count(*) FROM research_matches')[0][0]
        self.assertEqual(self.run_compare(), first)
        self.assertEqual(self.sql('SELECT count(*) FROM research_matches')[0][0], n)

    def test_disputes_api(self):
        self.build()
        self.assertEqual(self.api('GET', 'agent/disputes')[0], 403)                      # a research run is not the arbiter
        self.assertEqual(self.api('GET', 'agent/disputes', token=TOKEN)[0], 403)
        st, view = self.api('GET', 'agent/disputes', unit='ARBITER')
        self.assertEqual(st, 200, view)
        d = view['disputes']
        self.assertEqual([x['kind'] for x in d][0], 'patch')                              # identity first
        self.assertEqual(len(d), 5)
        ign = next(x for x in d if 'IGNITION' in x['key'])
        self.assertEqual(ign['question'], 'Which repair price is right?')
        self.assertEqual(ign['a']['sources'][0]['url'], 'https://example.test/RESEARCH_A')
        turbo = next(x for x in d if 'TURBO' in x['key'])
        self.assertIsNone(turbo['a']); self.assertEqual(turbo['question'], 'Is this fault real for this car, and is its band and price right?')
        # verdicts
        answer = lambda i, body: self.api('PATCH', f'agent/disputes/{i}', body, 'ARBITER')
        self.assertEqual(answer(9999, {'verdict': 'A', 'reason': 'x'})[0], 404)
        self.assertEqual(answer(ign['id'], {'verdict': 'MAYBE', 'reason': 'x'})[0], 400)
        self.assertEqual(answer(ign['id'], {'verdict': 'A'})[0], 400)                     # the reason is required
        self.assertEqual(answer(turbo['id'], {'verdict': 'A', 'reason': 'x'})[0], 400)    # run 1 did not stage it
        self.assertEqual(answer(turbo['id'], {'verdict': 'BOTH', 'reason': 'x'})[0], 400)
        self.assertEqual(answer(ign['id'], {'verdict': 'OWN', 'reason': 'x'})[0], 400)   # OWN needs a staged finding
        self.assertEqual(self.api('PATCH', f'agent/disputes/{ign["id"]}', {'verdict': 'A', 'reason': 'x'})[0], 403)  # run 1 is no arbiter
        # only keys under dispute are writable for the arbiter; a source always is
        s = self.stage('sources', {**ts.SRC, 'url': 'https://example.test/c'}, 'ARBITER')[1]
        self.assertEqual(self.stage('faults', {**BASE, 'component': 'Cylinder head gasket', 'component_code': 'ENGINE_INTERNALS', 'frequency_band': 'common',
                                               'source_id': s['id']}, 'ARBITER')[0], 403)
        st, own = self.stage('faults', {**BASE, 'component': 'Ignition coil failure', 'component_code': 'IGNITION', 'frequency_band': 'common',
                                        'parts_eur': 500, 'labor_eur': 600, 'source_id': s['id']}, 'ARBITER')
        self.assertEqual(st, 201, own)
        self.assertEqual(answer(ign['id'], {'verdict': 'OWN', 'reason': 'two garages agree', 'finding': own['id'], 'source_id': s['id']})[0], 200)
        self.assertEqual(answer(turbo['id'], {'verdict': 'B', 'reason': 'listed in the TSB'})[0], 200)
        self.assertEqual(self.sql('SELECT verdict, verdict_reason, verdict_source_id, verdict_id FROM research_matches WHERE id=?', (ign['id'],)),
                         [('OWN', 'two garages agree', s['id'], -own['id'])])
        view = self.api('GET', 'agent/disputes', unit='ARBITER')[1]
        self.assertEqual((view['answered'], len(view['open'])), (2, 3))
        c = connect()
        try:
            self.assertEqual(len(staging.unanswered(c, 100)), 3)
        finally:
            c.close()

    def test_dispute_limit_and_order(self):
        self.build()
        old = config.MAX_DISPUTES
        config.MAX_DISPUTES = 2
        try:
            view = self.api('GET', 'agent/disputes', unit='ARBITER')[1]
        finally:
            config.MAX_DISPUTES = old
        self.assertEqual([x['kind'] for x in view['disputes']], ['patch', 'fault'])
        self.assertIn('IGNITION', view['disputes'][1]['key'])                             # the dearest fault first


if __name__ == '__main__':
    unittest.main()
