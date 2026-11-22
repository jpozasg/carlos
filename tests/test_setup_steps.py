"""The setup wizard (static/js/pages/start.js) asks no insurance questions since 2026-11-22: its step list is fixed here, so a
change to the steps in start.js has to change this test too. Settings (static/js/pages/settings.js) has no worker-quote switch.
Standard library only; reads the source files, no server."""
import re, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
START = (ROOT / 'static' / 'js' / 'pages' / 'start.js').read_text(encoding='utf8')
SETTINGS = (ROOT / 'static' / 'js' / 'pages' / 'settings.js').read_text(encoding='utf8')


def array(name):
    m = re.search(rf'const {name} = \[([^\]]*)\]', START)
    assert m, name
    return re.findall(r"'([a-z_]+)'", m.group(1))


class SetupSteps(unittest.TestCase):
    def test_step_list_and_optional_steps(self):
        self.assertEqual(array('STEPS'), ['drive', 'money', 'search', 'workshop', 'charging', 'priorities', 'done'])
        self.assertEqual(array('OPTIONAL'), ['workshop', 'charging'])
        self.assertNotIn('insurance', array('STEPS'))
        self.assertNotIn('drivers', array('STEPS'))

    def test_postal_code_is_asked_in_the_search_step(self):
        search = START[START.index('  search: () =>'):START.index('  workshop: () =>')]
        self.assertIn("field('postal_code'", search)
        self.assertIn("params.postal_code = val('postal_code')", START)

    def test_settings_has_no_worker_quote_switch(self):
        self.assertNotIn('insurance_worker_quotes', SETTINGS)
        self.assertNotIn('insurance_worker_quotes', START)


if __name__ == '__main__':
    unittest.main()
