import re, unittest
import worker

UNITS = ['CAPTURE', 'VARIANT', 'GENERATION', 'GEN_MAINTENANCE', 'ENGINE', 'GEARBOX', 'TAX', 'LISTING']
LEFT = re.compile(r'\{[A-Z_]+\}')


def req(**kw):
    return {'id': 7, 'owner_id': 3, 'url': 'https://x/ad', 'note': None, 'listing_id': 42, 'attempts': 1, **kw}


class PromptTests(unittest.TestCase):
    def test_every_unit_has_a_file_and_fills_every_placeholder(self):
        for u in UNITS:
            self.assertTrue((worker.ROOT / 'docs' / 'prompts' / 'units' / f'{u.lower()}.md').exists(), u)
            p = worker.prompt_for(req(unit=u, level_id=11, parent_id=5, missing=['eng.oil', 'eng.risks'], result='earlier'))
            self.assertNotRegex(p, LEFT, u)
            for s in (u, 'eng.oil, eng.risks', 'Attempt 2', 'earlier', 'request 7'):
                self.assertIn(s, p, u)
            self.assertIn('CARLOS_RESULT', p)

    def test_unit_without_optional_fields(self):
        self.assertNotRegex(worker.prompt_for({'id': 1, 'owner_id': 2, 'unit': 'CAPTURE', 'url': None}), LEFT)

    def test_legacy_rows_keep_the_single_run_prompt(self):
        p = worker.prompt_for(req())
        self.assertIn('shared research worker of Carlos', p)
        self.assertNotIn('Your unit:', p)
        self.assertNotRegex(p, LEFT)
        self.assertNotIn('CONTINUATION (attempt', p)
        self.assertIn('CONTINUATION (attempt 2)', worker.prompt_for(req(missing=['lst.checklist'])))

    def test_outcome(self):
        self.assertEqual(worker.outcome('x\nCARLOS_RESULT done: ok')['status'], 'DONE')
        self.assertEqual(worker.outcome('CARLOS_RESULT failed: nope'), {'status': 'FAILED', 'result': 'nope'})
        self.assertEqual(worker.outcome('CARLOS_RESULT listing_id=9')['listing_id'], 9)
        self.assertEqual(worker.outcome('nothing')['status'], 'FAILED')


if __name__ == '__main__':
    unittest.main()
