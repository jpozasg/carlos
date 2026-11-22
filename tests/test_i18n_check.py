"""The i18n check script (.claude/skills/carlos-i18n-check): it must flag a broken synthetic UI and run cleanly on
the repository. The repository's own result is not asserted: known failures are listed in the skill until fixed."""
import importlib.util, json, tempfile, unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / '.claude' / 'skills' / 'carlos-i18n-check' / 'scripts' / 'i18n_check.py'
spec = importlib.util.spec_from_file_location('i18n_check', SCRIPT)
chk = importlib.util.module_from_spec(spec); spec.loader.exec_module(chk)


def write(root, files):
    for name, content in files.items():
        p = Path(root) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content if isinstance(content, str) else json.dumps(content), encoding='utf8')


class I18nCheck(unittest.TestCase):
    def test_synthetic_fixture_fails(self):
        en = {'hello': 'Hello {name}', 'years': {'one': 'year', 'other': 'years'}, 'only_en': 'x', 'codes': {'VERIFIED': 'Verified'}}
        de = {'hello': 'Hallo', 'years': {'one': 'Jahr'}, 'extra': 'y', 'codes': {}}
        with tempfile.TemporaryDirectory() as d:
            write(d, {'static/i18n/en.json': en, 'static/i18n/de.json': de, 'fixed.json': {'t.c': ['VERIFIED', 'ZZZ']},
                      'static/js/a.js': 'const s = `<b>${n.toLocaleString()}</b> ` + x + " €";\nconst ok = 1.toFixed(2); // i18n-ok\n'
                                        'const h = `<button>Save changes</button>`;\n'})
            errors, warnings = chk.run(d, Path(d) / 'fixed.json')
        text = '\n'.join(errors)
        for needle in ('de lacks key only_en', 'de has extra key extra', 'placeholders: de.hello', 'plural: de.years',
                       'codes: de lacks', 'ZZZ', 'toLocaleString', 'euro sign'):
            self.assertIn(needle, text)
        self.assertNotIn('toFixed', '\n'.join(warnings))  # suppressed by i18n-ok
        self.assertTrue(any('Save changes' in w for w in warnings))

    def test_missing_language_empty_value_and_missing_key(self):
        en = {'hello': 'Hello', 'bye': 'Goodbye for now', 'codes': {}}
        with tempfile.TemporaryDirectory() as d:
            write(d, {'static/i18n/en.json': en, 'static/i18n/de.json': {'hello': '', 'bye': 'Goodbye for now', 'codes': {}},
                      'static/js/i18n.js': "export const LANGS = { en: 'en-GB', de: 'de-DE', pl: 'pl-PL' };",
                      'static/js/a.js': "const a = t('hello') + t('nope') + t('why_' + x);\nconst b = `<td>${n}\u00a0€</td>`;\n"
                                        "const c = n; // price in €\n"})
            errors, warnings = chk.run(d)  # no carlos/agent.py under d: the fixed-codes check is skipped with a warning
        text = '\n'.join(errors)
        for needle in ('pl.json is missing', 'empty: de.hello', "t('nope')", 'euro sign'):
            self.assertIn(needle, text)
        self.assertNotIn("t('hello')", text)
        self.assertNotIn('a.js:3', text)  # a trailing comment is not code
        self.assertTrue(any('untranslated: de' in w and 'bye' in w for w in warnings))

    def test_clean_fixture_passes(self):
        en = {'hello': 'Hello {name}', 'codes': {'VERIFIED': 'Verified'}}
        with tempfile.TemporaryDirectory() as d:
            write(d, {'static/i18n/en.json': en, 'static/i18n/pl.json': {'hello': 'Cześć {name}', 'codes': {'VERIFIED': 'Zweryfikowane'}},
                      'fixed.json': {'t.c': ['VERIFIED']}, 'static/js/a.js': 'export const a = 1;\n',
                      'static/js/i18n.js': "export const LANGS = { en: 'en-GB', pl: 'pl-PL' };"})
            self.assertEqual(chk.run(d, Path(d) / 'fixed.json')[0], [])

    def test_repository_has_no_errors(self):  # a regression in the language files, codes or euro/unit formatting fails the suite
        errors, warnings = chk.run(SCRIPT.parents[4])
        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
