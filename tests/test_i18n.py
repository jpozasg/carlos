"""The four UI language files carry identical keys (also inside the nested `codes` map)."""
import json, unittest
from pathlib import Path

D = Path(__file__).resolve().parent.parent / 'static' / 'i18n'


def keys(d, pre=''):
    return {pre + k for k, v in d.items() if not isinstance(v, dict)} | {k2 for k, v in d.items() if isinstance(v, dict) for k2 in keys(v, pre + k + '.')}


class I18nParity(unittest.TestCase):
    def test_same_keys(self):
        ks = {l: {k for k in keys(json.loads((D / f'{l}.json').read_text(encoding='utf8'))) if not k.endswith(('.few', '.many'))} for l in ('en', 'es', 'de', 'pl')}  # pl has extra plural forms
        for l, k in ks.items():
            self.assertEqual(ks['en'] - k, set(), f'{l} lacks keys')
            self.assertEqual(k - ks['en'], set(), f'{l} has extra keys')
