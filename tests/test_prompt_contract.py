"""One rule per topic (research-audit, prompt-contradictions C7, C8, C10, C16, C17): the protocol's contract table and DIY list
are generated from the same code as the grading, the prompts carry no retired instruction, and the validators that exist
(fault_checks, check_component_code) keep their behaviour."""
import os, re, sqlite3, unittest
from carlos import agent, config, research

ROOT = os.path.join(os.path.dirname(__file__), '..')
PROTOCOL = os.path.join(ROOT, 'docs', 'cost-research-protocol.md')
PROMPTS = [os.path.join(ROOT, 'docs', 'prompts', f) for f in ('research-car.md', 'research-request.md')] + \
    [os.path.join(ROOT, 'docs', 'prompts', 'units', f) for f in ('_header.md', 'research.md', 'listing.md', 'tax.md', 'arbiter.md', 'capture.md')]


def read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def accepted(item):
    """The text the protocol table prints in "Accepted results" (the same rule as the grading in research.ITEMS)."""
    rows_ok, results = item[3] is not None, item[4]
    if rows_ok and results:
        return 'rows or check ' + ' / '.join(results)
    return 'rows' if rows_ok else 'check ' + ' / '.join(results)


class ProtocolTable(unittest.TestCase):
    def test_every_item_prints_the_accepted_results_of_its_code(self):
        table = {}
        for line in read(PROTOCOL).split('\n'):
            if not line.startswith('| `'):
                continue
            cells = [c.strip() for c in line.strip().strip('|').split('|')]
            for iid in re.findall(r'`([a-z]+\.[a-z_]+)`', cells[0]):
                table[iid] = cells[3]
        for item in research.ITEMS:
            self.assertEqual(table.get(item[0]), accepted(item), item[0])

    def test_check_decision_table_is_in_the_protocol(self):
        doc = read(PROTOCOL)
        self.assertIn('| Situation | Record | `notes` must hold |', doc)
        self.assertIn('| Item | Level | Accepted when | Accepted results | Min. quality |', doc)


class DiyList(unittest.TestCase):
    def test_protocol_names_the_config_lists(self):
        doc = read(PROTOCOL)
        diy = re.search(r'config\.DIYABLE_JOBS` \(([A-Z_, ]+)\)', doc)
        workshop = re.search(r'the others \(([A-Z_, ]+)\) are \*\*workshop-only\*\*', doc)
        self.assertIsNotNone(diy)
        self.assertIsNotNone(workshop)
        self.assertEqual({j.strip() for j in diy.group(1).split(',')}, config.DIYABLE_JOBS)
        self.assertEqual({j.strip() for j in workshop.group(1).split(',')}, set(config.JOBS) - config.DIYABLE_JOBS)


class RetiredPhrases(unittest.TestCase):
    """Phrases that a prompt must not carry any more (the contradictions file, C10, C16 and C5)."""
    BANNED = ['{REPO}/.env', 'gearbox_families', 'review_flags', 'Research agents never use a browser']

    def test_prompts_and_protocol_carry_none_of_them(self):
        for path in PROMPTS + [PROTOCOL]:
            doc = read(path)
            for phrase in self.BANNED:
                self.assertNotIn(phrase, doc, f'{os.path.relpath(path, ROOT)} still says {phrase!r}')


class ExistingValidators(unittest.TestCase):
    """The audit's validators that exist (carlos/agent.py); the rest are listed in the protocol under 'Validators still to add'."""

    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.c.execute('CREATE TABLE sources (id INTEGER PRIMARY KEY, quality TEXT)')
        self.c.executemany('INSERT INTO sources VALUES (?, ?)', [(1, 'D'), (2, 'A')])

    def tearDown(self):
        self.c.close()

    def test_forum_only_fault_is_capped_at_common(self):
        with self.assertRaises(ValueError):
            agent.fault_checks(self.c, {'frequency_band': 'widespread', 'source_id': 1})
        agent.fault_checks(self.c, {'frequency_band': 'common', 'source_id': 1})
        agent.fault_checks(self.c, {'frequency_band': 'rare', 'source_id': 1})

    def test_systemic_needs_a_manufacturer_trace(self):
        with self.assertRaises(ValueError):
            agent.fault_checks(self.c, {'frequency_band': 'systemic', 'source_id': 2})
        agent.fault_checks(self.c, {'frequency_band': 'systemic', 'source_id': 2, 'manufacturer_trace': 'extended warranty'})

    def test_window_without_an_ab_source_stays_uncertain(self):
        out = {'applies_from': '2015-01', 'source_id': 1}
        agent.fault_checks(self.c, out)
        self.assertEqual(out['window_uncertain'], 1)
        out = {'applies_from': '2015-01', 'source_id': 2}
        agent.fault_checks(self.c, out)
        self.assertNotIn('window_uncertain', out)

    def test_component_code_is_required_on_insert_and_other_needs_notes(self):
        with self.assertRaises(ValueError):
            agent.check_component_code(None, {'part': 'ENGINE', 'component': 'rattle'}, None)
        with self.assertRaises(ValueError):
            agent.check_component_code(None, {'part': 'ENGINE', 'component_code': 'OTHER', 'notes': ' '}, None)
        agent.check_component_code(None, {'part': 'ENGINE', 'component_code': 'OTHER', 'notes': 'a rattle from the ECU fan'}, None)


if __name__ == '__main__':
    unittest.main()
