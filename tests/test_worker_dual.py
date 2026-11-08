"""The worker and the two-agent units (#253 phase P5a): prompts for RESEARCH_A/B and ARBITER, MERGE without Claude, the research timeout."""
import re, tempfile, unittest
from pathlib import Path
from unittest import mock
import worker

LEFT = re.compile(r'\{[A-Z_]+\}')


def req(**kw):
    return {'id': 7, 'owner_id': 3, 'url': 'https://x/ad', 'note': None, 'listing_id': 42, 'attempts': 0, 'parent_id': 5, 'request_token': 'tok', **kw}


class FakeApi:
    base, token, worker = 'http://x', 'worker-token', True

    def __init__(self, claimed):
        self.claimed, self.calls = claimed, []

    def call(self, method, path, body=None, **kw):
        self.calls.append((method, path, body))
        return {'request': self.claimed} if path == '/api/worker/claim' else {}


class WorkerDualTest(unittest.TestCase):
    def test_research_prompt_uses_the_shared_file_and_lists_the_scope(self):
        d = Path(tempfile.mkdtemp())
        (d / 'docs' / 'prompts' / 'units').mkdir(parents=True)
        (d / 'docs' / 'prompts' / 'units' / '_header.md').write_text('HEADER {UNIT}\n', encoding='utf-8')
        (d / 'docs' / 'prompts' / 'units' / 'research.md').write_text('Scope: {SCOPE}. Missing: {MISSING}. Request {REQUEST_ID}.', encoding='utf-8')
        for unit in ('RESEARCH_A', 'RESEARCH_B'):
            with mock.patch.object(worker, 'ROOT', d):
                p = worker.prompt_for(req(unit=unit, scope=[['generation_id', 64], ['engine_id', 69]], missing=['eng.risks', 'gen.hu']))
            self.assertIn(f'HEADER {unit}', p)
            self.assertIn('Scope: generation 64, engine 69. Missing: eng.risks, gen.hu. Request 7.', p)
            self.assertNotRegex(p, LEFT)

    def test_arbiter_prompt_takes_dispute_ids(self):
        p = worker.prompt_for(req(unit='ARBITER', missing=[11, 12], scope=None))
        self.assertNotRegex(p, LEFT)
        self.assertIn('11, 12', p)

    def test_merge_runs_no_claude_and_reports_the_summary(self):
        api = FakeApi({**req(unit='MERGE'), 'id': 9})
        merged = []
        with mock.patch.object(worker, 'Api') as A, mock.patch.object(worker.subprocess, 'Popen', side_effect=AssertionError('Claude was launched')):
            A.return_value.call.side_effect = lambda m, path, body=None: merged.append((m, path)) or {'written': 41, 'skipped': [1, 2, 3], 'flags': [4, 5]}
            self.assertTrue(worker.work_one(api, 'w', 'false', tempfile.mkdtemp(), 30))
        self.assertEqual(A.call_args[0][1], 'tok')                              # the merge uses the request's own token
        self.assertEqual(merged, [('POST', '/api/agent/merge')])
        self.assertEqual(api.calls[-1], ('POST', '/api/worker/requests/9', {'status': 'DONE', 'result': 'Merged: 41 written, 3 skipped, 2 flags'}))

    def test_merge_error_is_a_failed_finish(self):
        api = FakeApi({**req(unit='MERGE'), 'id': 9})
        with mock.patch.object(worker, 'Api') as A:
            A.return_value.call.side_effect = worker.ApiError('POST /api/agent/merge: HTTP 400: nothing to merge', 400)
            worker.work_one(api, 'w', 'false', tempfile.mkdtemp(), 30)
        self.assertEqual(api.calls[-1][2]['status'], 'FAILED')
        self.assertIn('nothing to merge', api.calls[-1][2]['result'])

    def test_research_units_get_the_research_timeout(self):
        for unit, expect in (('RESEARCH_A', 5), ('ARBITER', 2)):
            api = FakeApi({**req(unit=unit), 'id': 9})
            proc = mock.Mock(returncode=0); proc.communicate.return_value = ('CARLOS_RESULT done: ok', None)
            with mock.patch.object(worker, 'prompt_for', return_value='p'), mock.patch.object(worker.subprocess, 'Popen', return_value=proc), \
                 mock.patch.object(worker.time, 'time', return_value=1000.0):
                worker.work_one(api, 'w', 'sh', tempfile.mkdtemp(), 2, research_timeout_s=5)
            self.assertEqual(api.calls[-1][2]['status'], 'DONE')
            self.assertEqual(proc.communicate.call_args[1]['timeout'], expect)   # frozen clock: the first wait is the unit's timeout

    def test_outcome_of_a_research_run(self):
        self.assertEqual(worker.outcome('CARLOS_RESULT done: staged 40 findings')['status'], 'DONE')


if __name__ == '__main__':
    unittest.main()
