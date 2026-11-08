"""The dual research flow (#253 phase P5a): stages, skip, overlap and release, compare trigger, finish gates, legacy parents,
progress detail, and the worker's handling of the new units. Direct calls on a synthetic database, no HTTP."""
import json, tempfile, unittest
from pathlib import Path
from unittest import mock
from carlos import config, research_requests as rq, research_units as ru
from carlos.db import connect
from tests import fixture as fx
from tests.fixture import ADMIN, CAR_A, E_A, G1, V_A

FAULT = {'component': 'Turbocharger', 'component_code': 'TURBO', 'part': 'ENGINE', 'consequence': 'COST', 'existence': 'CONFIRMED',
         'frequency_band': 'common', 'shape': 'WEAR_KM', 'parts_eur': 400, 'labor_eur': 400, 'engine_id': E_A}


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        config.DB = Path(self.tmp.name) / 'cars.sqlite'
        ru.SECOND_RUN = True; self.addCleanup(setattr, ru, 'SECOND_RUN', False)
        fx.build(config.DB)
        self.c = connect(); self.addCleanup(self.c.close)
        self.real = []     # contract items missing on the real rows
        self.staged = []   # ... with a run's staged rows applied
        self.mi = lambda owner, lid: list(self.real)
        self.sm = lambda req: list(self.staged)

    def parent(self, listing=CAR_A):
        with self.c:
            pid = self.c.execute("INSERT INTO research_requests (owner_id, url, status, listing_id, unit) VALUES (?, 'u', 'WAITING', ?, 'CAPTURE')",
                                 (ADMIN, listing)).lastrowid
        return pid

    def kids(self, pid):
        return {r['unit']: dict(r) for r in self.c.execute('SELECT * FROM research_requests WHERE parent_id=? ORDER BY id', (pid,))}

    def status(self, pid):
        return {u: k['status'] for u, k in self.kids(pid).items()}

    def go(self, pid, unit, status='DONE'):
        rid = self.kids(pid)[unit]['id']
        with self.c:
            self.c.execute("UPDATE research_requests SET status='RUNNING', worker='w', claimed_at=datetime('now') WHERE id=?", (rid,))
        rq.finish(self.c, rid, {'status': status, 'result': 'x'}, missing=self.mi, staged=self.sm)
        return self.kids(pid)[unit]

    def finding(self, pid, unit, run, payload=FAULT, kind='fault', key='fault:ENGINE:TURBO'):
        with self.c:
            self.c.execute("INSERT INTO research_findings (request_id, parent_id, run, kind, op, target_table, key, level, level_id, payload) "
                           "VALUES (?,?,?,?,'insert','faults',?, 'engine', ?, ?)", (self.kids(pid)[unit]['id'], pid, run, kind, key, E_A, json.dumps(payload)))

    def test_stages_skip_and_scope(self):
        self.real = ['eng.risks', 'gen.hu', 'lst.checklist']
        pid = self.parent()
        rq.advance(self.c, pid, self.mi)
        k = self.kids(pid)
        self.assertEqual(self.status(pid), {'RESEARCH_A': 'QUEUED', 'RESEARCH_B': 'QUEUED'})
        self.assertEqual((json.loads(k['RESEARCH_A']['missing']), json.loads(k['RESEARCH_A']['scope'])),
                         (['eng.risks', 'gen.hu'], [['engine_id', E_A], ['generation_id', G1]]))
        self.assertEqual((k['RESEARCH_A']['missing'], k['RESEARCH_A']['scope']), (k['RESEARCH_B']['missing'], k['RESEARCH_B']['scope']))
        # nothing missing in the research: the whole block is skipped and the flow goes on to TAX / LISTING
        self.real = ['lst.checklist']
        p2 = self.parent()
        rq.advance(self.c, p2, self.mi)
        self.assertEqual(self.status(p2), {'RESEARCH_A': 'SKIPPED', 'RESEARCH_B': 'SKIPPED', 'ARBITER': 'SKIPPED', 'MERGE': 'SKIPPED',
                                           'TAX': 'SKIPPED', 'LISTING': 'QUEUED'})

    def test_single_run_skips_b_and_arbiter(self):
        ru.SECOND_RUN = False
        self.real = ['eng.risks', 'lst.checklist']
        pid = self.parent()
        rq.advance(self.c, pid, self.mi)
        self.assertEqual(self.status(pid), {'RESEARCH_A': 'QUEUED', 'RESEARCH_B': 'SKIPPED'})
        self.finding(pid, 'RESEARCH_A', 'A')                                   # one-sided finding: no arbiter without a second run
        self.assertEqual(self.go(pid, 'RESEARCH_A')['status'], 'DONE')
        s = self.status(pid)
        self.assertEqual((s['ARBITER'], s['MERGE']), ('SKIPPED', 'QUEUED'))

    def test_full_flow_with_a_dispute(self):
        self.real = ['eng.risks', 'gen.hu', 'lst.checklist']
        pid = self.parent()
        rq.advance(self.c, pid, self.mi)
        self.finding(pid, 'RESEARCH_A', 'A')                                   # only run 1 found a common turbo fault: a material dispute
        self.staged = []
        self.assertEqual(self.go(pid, 'RESEARCH_A')['status'], 'DONE')
        self.assertNotIn('ARBITER', self.status(pid))                          # waits for run B
        self.assertEqual(self.go(pid, 'RESEARCH_B')['status'], 'DONE')
        arb = self.kids(pid)['ARBITER']
        self.assertEqual(arb['status'], 'QUEUED')
        dispute = self.c.execute('SELECT id FROM research_matches WHERE parent_id=? AND material=1', (pid,)).fetchone()[0]
        self.assertEqual(json.loads(arb['missing']), [dispute])
        # the done gate: an unanswered dispute re-queues once, then the arbiter closes DONE
        self.assertEqual(self.go(pid, 'ARBITER')['status'], 'QUEUED')
        self.assertEqual(self.go(pid, 'ARBITER')['status'], 'DONE')
        merge = self.kids(pid)['MERGE']
        self.assertEqual((merge['status'], json.loads(merge['missing'])), ('QUEUED', ['eng.risks', 'gen.hu']))
        # the merge is graded on the real rows: items still missing = FAILED, the parent still runs TAX and LISTING
        self.real = ['eng.risks', 'lst.checklist']
        m = self.go(pid, 'MERGE')
        self.assertEqual(m['status'], 'FAILED'); self.assertIn('Still missing after merge: eng.risks', m['result'])
        self.assertEqual(self.status(pid)['LISTING'], 'QUEUED')
        self.real = []
        self.go(pid, 'LISTING')
        top = self.c.execute('SELECT status, result FROM research_requests WHERE id=?', (pid,)).fetchone()
        self.assertEqual(top['status'], 'FAILED'); self.assertIn('MERGE', top['result'])

    def test_no_dispute_skips_the_arbiter_and_a_clean_merge_is_done(self):
        self.real = ['eng.risks']
        pid = self.parent()
        rq.advance(self.c, pid, self.mi)
        for unit, run in (('RESEARCH_A', 'A'), ('RESEARCH_B', 'B')):          # both runs found the same cheap, rare fault: agreed
            self.finding(pid, unit, run, {**FAULT, 'frequency_band': 'rare', 'parts_eur': 50, 'labor_eur': 50})
            self.go(pid, unit)
        s = self.status(pid)
        self.assertEqual((s['ARBITER'], s['MERGE']), ('SKIPPED', 'QUEUED'))
        self.assertIn('No material disagreement', self.kids(pid)['ARBITER']['result'])
        self.real = []
        self.assertEqual(self.go(pid, 'MERGE')['status'], 'DONE')
        self.assertEqual(self.c.execute('SELECT status FROM research_requests WHERE id=?', (pid,)).fetchone()[0], 'DONE')

    def test_research_closes_done_with_gaps_after_two_attempts(self):
        self.real = ['eng.risks', 'gen.hu']
        pid = self.parent()
        rq.advance(self.c, pid, self.mi)
        self.staged = ['eng.risks', 'gen.hu', 'lst.checklist']                 # lst.* and ids outside the run's items never count
        a = self.go(pid, 'RESEARCH_A', 'FAILED')                              # a run that says failed is graded anyway
        self.assertEqual((a['status'], a['attempts'], json.loads(a['missing'])), ('QUEUED', 1, ['eng.risks', 'gen.hu']))
        self.staged = ['gen.hu']
        a = self.go(pid, 'RESEARCH_A')
        self.assertEqual((a['status'], json.loads(a['missing'])), ('DONE', ['gen.hu']))   # gaps kept, never FAILED
        self.assertIn('Closed with 1 contract items missing: gen.hu', a['result'])

    def test_overlap_waits_and_is_released_by_the_merge(self):
        self.real = ['eng.risks', 'gen.hu']
        p1, p2 = self.parent(), self.parent()
        rq.advance(self.c, p1, self.mi)
        rq.advance(self.c, p2, self.mi)
        a1 = self.kids(p1)['RESEARCH_A']['id']
        self.assertEqual(self.status(p2), {'RESEARCH_A': 'WAITING', 'RESEARCH_B': 'WAITING'})
        self.assertEqual({k['shared_id'] for k in self.kids(p2).values()}, {a1})
        for unit, run in (('RESEARCH_A', 'A'), ('RESEARCH_B', 'B')):
            self.finding(p1, unit, run, {**FAULT, 'frequency_band': 'rare', 'parts_eur': 50, 'labor_eur': 50})
            self.go(p1, unit)
        self.assertEqual(self.status(p2)['RESEARCH_A'], 'WAITING')            # the research closing does not release
        self.real = []                                                          # the merge researched everything
        self.assertEqual(self.go(p1, 'MERGE')['status'], 'DONE')
        s = self.status(p2)
        self.assertEqual((s['RESEARCH_A'], s['RESEARCH_B'], s['ARBITER'], s['MERGE']), ('DONE', 'DONE', 'SKIPPED', 'SKIPPED'))
        self.assertIn(f'Researched by request #{p1}', self.kids(p2)['RESEARCH_A']['result'])

    def test_a_failed_merge_releases_the_waiters_and_they_research_what_is_left(self):
        self.real = ['eng.risks', 'gen.hu']
        p1, p2 = self.parent(), self.parent()
        rq.advance(self.c, p1, self.mi)
        rq.advance(self.c, p2, self.mi)
        for unit, run in (('RESEARCH_A', 'A'), ('RESEARCH_B', 'B')):
            self.finding(p1, unit, run, {**FAULT, 'frequency_band': 'rare', 'parts_eur': 50, 'labor_eur': 50})
            self.go(p1, unit)
        self.real = ['gen.hu']
        self.assertEqual(self.go(p1, 'MERGE')['status'], 'FAILED')
        k = self.kids(p2)
        self.assertEqual((k['RESEARCH_A']['status'], k['RESEARCH_B']['status']), ('QUEUED', 'QUEUED'))
        self.assertEqual((json.loads(k['RESEARCH_A']['missing']), json.loads(k['RESEARCH_A']['scope']), k['RESEARCH_A']['shared_id']),
                         (['gen.hu'], [['generation_id', G1]], None))

    def test_cancel_with_a_running_research_releases_waiters_and_leaves_no_merge(self):
        self.real = ['eng.risks']
        p1, p2 = self.parent(), self.parent()
        rq.advance(self.c, p1, self.mi)
        rq.advance(self.c, p2, self.mi)
        with self.c:
            self.c.execute("UPDATE research_requests SET status='RUNNING' WHERE parent_id=? AND unit='RESEARCH_A'", (p1,))
        rq.cancel(self.c, ADMIN, p1)
        self.assertEqual(self.status(p1), {'RESEARCH_A': 'RUNNING', 'RESEARCH_B': 'CANCELLED'})
        self.go(p1, 'RESEARCH_A')
        self.assertNotIn('MERGE', self.status(p1))
        self.assertEqual(self.status(p2)['RESEARCH_A'], 'QUEUED')              # nothing was merged: p2 does its own research

    def test_legacy_parent_keeps_the_legacy_stages(self):
        self.real = ['var.tyres', 'gen.hu', 'lst.checklist']
        pid = self.parent()
        with self.c:
            self.c.execute("INSERT INTO research_requests (owner_id, url, status, listing_id, parent_id, unit) VALUES (?, 'u', 'DONE', ?, ?, 'VARIANT')",
                           (ADMIN, CAR_A, pid))
        rq.advance(self.c, pid, self.mi)
        self.assertEqual(self.status(pid), {'VARIANT': 'DONE', 'GENERATION': 'SKIPPED', 'GEN_MAINTENANCE': 'QUEUED', 'ENGINE': 'SKIPPED', 'GEARBOX': 'SKIPPED'})
        with mock.patch.object(ru, 'FLOW', 'units'):                           # the rollback switch: a new parent starts with VARIANT
            p2 = self.parent()
            rq.advance(self.c, p2, self.mi)
            self.assertEqual(self.status(p2), {'VARIANT': 'QUEUED'})
        self.assertEqual([p['unit'] for p in rq.mine(self.c, ADMIN)[0]['parts']], ['VARIANT'])

    def test_progress_detail(self):
        self.real = ['eng.risks']
        pid = self.parent()
        rq.advance(self.c, pid, self.mi)
        self.finding(pid, 'RESEARCH_A', 'A')
        self.finding(pid, 'RESEARCH_A', 'A', {'a': 1}, 'check', 'check:eng.risks')
        parts = {p['unit']: p for p in rq.mine(self.c, ADMIN)[0]['parts']}
        self.assertEqual(list(parts), ['RESEARCH_A', 'RESEARCH_B'])
        self.assertEqual(parts['RESEARCH_A']['detail']['staged'], {'fault': 1, 'check': 1})
        self.assertEqual((parts['RESEARCH_A']['detail']['last'], parts['RESEARCH_A']['detail']['missing']), ('check eng.risks', ['eng.risks']))
        self.assertEqual(parts['RESEARCH_B']['detail']['staged'], {})
        for unit in ('ARBITER', 'MERGE'):
            with self.c:
                self.c.execute("INSERT INTO research_requests (owner_id, url, status, parent_id, unit, listing_id) VALUES (?, 'u', 'QUEUED', ?, ?, ?)",
                               (ADMIN, pid, unit, CAR_A))
        kids = {p['unit']: p['detail'] for p in rq.mine(self.c, ADMIN)[0]['parts']}
        self.assertEqual(kids['ARBITER'], {'disputes': 0, 'answered': 0})
        self.assertEqual(set(kids['MERGE']), {'agreement', 'written', 'skipped', 'flags'})


class FinishOverHttpTest(unittest.TestCase):
    """The server wires the staged dry grade into finish: a research run's own staging is graded, not the catalogue."""
    from tests import test_staging as ts
    setUpClass = classmethod(ts.StagingTest.setUpClass.__func__)
    tearDownClass = classmethod(ts.StagingTest.tearDownClass.__func__)
    setUp, sql, api = ts.StagingTest.setUp, ts.StagingTest.sql, ts.StagingTest.api

    def test_research_run_is_graded_on_its_staging(self):
        self.sql("UPDATE research_requests SET missing=? WHERE id=101", (json.dumps(ru.RESEARCH_ITEMS),))
        st, out = self.api('POST', 'worker/requests/101', {'status': 'DONE', 'result': 'x'}, token=fx.TOKEN)
        self.assertEqual(st, 200, out)
        self.assertEqual((out['status'], out['attempts']), ('QUEUED', 1))      # nothing staged: the fixture is not fully researched
        self.assertTrue(json.loads(out['missing']) and set(json.loads(out['missing'])) <= set(ru.RESEARCH_ITEMS))


if __name__ == '__main__':
    unittest.main()


class SeverityTest(unittest.TestCase):
    def test_cheap_stranding_fault_is_not_high(self):  # #285
        from carlos.costs import fault_severity
        f = lambda c, p: {'consequence': c, 'parts_eur': p, 'labor_eur': 0}
        self.assertEqual(fault_severity(f('STRANDS', 135)), 'LOW-MEDIUM')
        self.assertEqual(fault_severity(f('SAFETY', 600)), 'HIGH')
        self.assertEqual(fault_severity(f('ENGINE_DAMAGE', 50)), 'HIGH')

    def test_rare_fault_weighs_little(self):  # #287
        from carlos.costs import fault_weight
        self.assertEqual([fault_weight({'frequency_band': b}) for b in ('systemic', 'common', 'occasional', 'rare')], [1, 1, 0.417, 0.125])
        self.assertEqual(fault_weight({}), 1)
