"""static/js/ui.js helpers the pages share (unit joins, dates, unknowns as pending, zero deltas, certain costs, stale
threshold), run in node against the real modules with a stubbed DOM and the real i18n files. Skipped without node."""
import json, shutil, subprocess, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HARNESS = r'''
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';
const root = process.argv[1];
globalThis.document = { documentElement: {}, getElementById: () => null };
globalThis.MutationObserver = class { observe() {} };
globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.fetch = async url => ({ ok: true, json: async () => JSON.parse(fs.readFileSync(root + url, 'utf8')) });
const i18n = await import(pathToFileURL(root + '/static/js/i18n.js').href);
const ui = await import(pathToFileURL(root + '/static/js/ui.js').href);
const out = {};
for (const l of ['en', 'de', 'pl']) {
  await i18n.load(l);
  out[l] = {
    km: ui.unit(150000, 'km'), ps: ui.unit(75, 'ps'), unitNull: ui.unit(null, 'km'),
    carShort: ui.carShort({ model: 'Golf', displacement_cc: 1998, first_registration: '2019-03-01' }),
    dateDay: ui.fmtDate('2024-03-05'), dateMonth: ui.fmtDate('2019-03'), dateEsc: ui.fmtDate('<b>x'),
    dateNone: ui.fmtDate(null),
    zero: ui.deltaTxt(0), up: ui.deltaTxt(5), down: ui.deltaTxt(-5),
    interval: ui.intervalTxt(null, null), fault: ui.faultProb({}),
    certainOne: ui.certainEur({ parts_eur: 10, labor_eur: null }), certainBoth: ui.certainEur({ parts_eur: 10, labor_eur: 5 }),
    certainNone: ui.certainEur({ parts_eur: null, labor_eur: null }),
    partial: ui.partsLaborP(10, null), stale: ui.statusTags({ stale: 1 })[0], over: ui.statusTags({ budget_status: 'over_max' })[0],
    missingCode: i18n.tv('MISSING'), staleDays: ui.STALE_DAYS,
  };
}
console.log(JSON.stringify(out));
'''


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class UiHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p = subprocess.run(['node', '--input-type=module', '-e', HARNESS, str(ROOT)], capture_output=True, text=True, timeout=120)
        assert p.returncode == 0, p.stderr
        cls.o = json.loads(p.stdout)

    def test_units_join_with_no_break_space_and_pl_says_km_for_power(self):
        self.assertEqual(self.o['en']['km'], '150,000 km')
        self.assertEqual(self.o['en']['ps'], '75 PS')
        self.assertEqual(self.o['pl']['ps'], '75 KM')
        self.assertIn('class="pending"', self.o['en']['unitNull'])

    def test_car_short_uses_the_locale_decimal_separator(self):
        self.assertEqual(self.o['en']['carShort'], 'Golf 2.0 · 2019')
        self.assertEqual(self.o['de']['carShort'], 'Golf 2,0 · 2019')

    def test_dates_are_locale_formatted_and_escaped_or_month_only(self):
        self.assertNotIn('-03-', self.o['en']['dateDay'])
        self.assertIn('2019', self.o['en']['dateMonth'])
        self.assertNotIn('1', self.o['en']['dateMonth'].replace('2019', ''))  # no invented day
        self.assertEqual(self.o['en']['dateEsc'], '&lt;b&gt;x')
        self.assertEqual(self.o['en']['dateNone'], '')

    def test_zero_delta_has_no_arrow_and_no_euro_amount(self):
        z = self.o['en']['zero']
        self.assertNotIn('€', z); self.assertNotIn('▲', z); self.assertNotIn('▼', z)
        self.assertIn('▲', self.o['en']['up']); self.assertIn('▼', self.o['en']['down'])

    def test_unknowns_are_pending_not_dashes(self):
        self.assertIn('class="pending"', self.o['en']['interval'])
        self.assertIn('class="pending"', self.o['en']['fault'])

    def test_certain_cost_needs_both_sides(self):
        self.assertIsNone(self.o['en']['certainOne'])
        self.assertEqual(self.o['en']['certainBoth'], 15)
        self.assertIsNone(self.o['en']['certainNone'])
        self.assertIn('tag warn', self.o['en']['partial'])

    def test_stale_threshold_is_a_named_constant_and_glyphs_are_hidden(self):
        self.assertEqual(self.o['en']['staleDays'], 14)
        self.assertIn('Not checked for over 14 days', self.o['en']['stale'])
        self.assertIn('aria-hidden="true"', self.o['en']['stale'])
        self.assertIn('aria-hidden="true"', self.o['en']['over'])

    def test_fixed_codes_have_a_label_in_every_language(self):
        self.assertEqual(self.o['pl']['missingCode'], 'Brak')
        self.assertEqual(self.o['en']['missingCode'], 'Missing')


if __name__ == '__main__':
    unittest.main()
