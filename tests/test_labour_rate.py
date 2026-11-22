"""One workshop labour rate (owner, 2026-11-22): every instruction to an agent and the config constant say the same EUR/h figure."""
import os, re, unittest
from carlos import config

ROOT = os.path.join(os.path.dirname(__file__), '..')
# "EUR 100/h", "100 €/h", "about 90 EUR/h", "labour ≈ 100 €/h": the rate is the number next to EUR/€ and /h
RATE = re.compile(r'(?:EUR|€)\s*(\d+)\s*/\s*h\b|(\d+)\s*(?:EUR|€)\s*/\s*h\b')
SCAN = ['AGENTS.md', 'README.md', 'docs', '.claude/skills', 'carlos', 'agent_tools.py', 'worker.py']
# the audit's record of the old contradiction quotes the wrong figures on purpose
SKIP = {os.path.join('.claude', 'skills', 'research-audit', 'references', 'prompt-contradictions.md')}


class LabourRate(unittest.TestCase):
    def test_constant_is_the_owner_rate(self):
        self.assertEqual(config.WORKSHOP_LABOUR_EUR_PER_H, 100)

    def test_every_documented_rate_matches_the_constant(self):
        bad, found = [], 0
        for entry in SCAN:
            path = os.path.join(ROOT, entry)
            files = [path] if os.path.isfile(path) else [os.path.join(d, f) for d, _, fs in os.walk(path) for f in fs]
            for f in files:
                rel = os.path.relpath(f, ROOT)
                if not f.endswith(('.md', '.py')) or rel in SKIP:
                    continue
                with open(f, encoding='utf-8') as fh:
                    for i, line in enumerate(fh, 1):
                        for m in RATE.finditer(line):
                            found += 1
                            if int(m.group(1) or m.group(2)) != config.WORKSHOP_LABOUR_EUR_PER_H:
                                bad.append(f'{rel}:{i}: {line.strip()[:120]}')
        self.assertGreater(found, 0)  # the scan must see the rate somewhere, or the pattern is broken
        self.assertEqual(bad, [])

    def test_protocol_states_the_rule(self):
        with open(os.path.join(ROOT, 'docs', 'cost-research-protocol.md'), encoding='utf-8') as fh:
            self.assertIn('**EUR 100/h**', fh.read())


if __name__ == '__main__':
    unittest.main()
