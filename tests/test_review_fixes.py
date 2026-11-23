"""Code review fixes (round 1, 2026-11-22): unit checks of the rules that the API tests do not reach directly."""
import os
import sqlite3
import unittest

os.environ.setdefault("AGENT_TOKEN", "x")
from carlos import agent, config, costs, ranking  # noqa: E402
import markdown_export  # noqa: E402


def K(i, src, key, **kw):
    return {**dict(id=i, source_key=src, external_key=key, url=f'https://x.test/{key}', engine_id=None, generation_id=None), **kw}


def R(i, src, key, **kw):
    return {**dict(id=i, source_key=src, external_key=key, edition='2026', value_num=None, value_text=None, band=None, class_average=None,
                   age_from=None, age_to=None, reg_year=None, url=f'https://x.test/{src}'), **kw}


class FaultSeverity(unittest.TestCase):
    def fault(self, consequence, price=None):
        return {'consequence': consequence, 'parts_eur': price, 'labor_eur': None}

    def test_an_unpriced_fault_is_not_compared_with_the_thresholds(self):
        self.assertEqual(costs.fault_severity(self.fault('STRANDS')), 'MEDIUM')          # not LOW-MEDIUM: its price is unknown, not 0
        self.assertEqual(costs.fault_severity(self.fault('SAFETY')), 'MEDIUM')
        self.assertEqual(costs.fault_severity(self.fault('ENGINE_DAMAGE')), 'HIGH')     # the consequence alone decides
        self.assertEqual(costs.fault_severity(self.fault('WEAR')), 'LOW')
        self.assertEqual(costs.fault_severity(self.fault('STRANDS', 50)), 'LOW-MEDIUM')  # a known cheap price still counts
        self.assertEqual(costs.fault_severity(self.fault('STRANDS', config.SEVERITY_MEDIUM_EUR)), 'HIGH')


class ReliabilityGuards(unittest.TestCase):
    def test_a_stored_zero_average_or_a_band_outside_1_to_5_is_no_figure(self):
        keys = [K(1, 'TUEV_REPORT', 'Polo', generation_id=1), K(2, 'ADAC_PANNENSTATISTIK', 'Polo', generation_id=1)]
        ratings = [R(1, 'TUEV_REPORT', 'Polo', age_from=6, age_to=7, value_num=5.0, class_average=0),
                   R(2, 'ADAC_PANNENSTATISTIK', 'Polo', reg_year=2014, band=7, value_num=3.1)]
        r = costs.reliability_sources(keys, ratings, 6.5, 2014)  # no ZeroDivisionError, no KeyError
        self.assertEqual((r['score'], r['missing']), (None, ['ENGINE', 'HU', 'BREAKDOWNS']))
        ratings[1]['band'] = 2
        self.assertEqual(costs.reliability_sources(keys, ratings, 6.5, 2014)['slots']['BREAKDOWNS']['points'], 75)


class Filters(unittest.TestCase):
    def test_a_saved_filter_is_checked_before_it_is_read(self):
        ranking.check_filter('filter_hu_months', '12')
        ranking.check_filter('filter_seller', 'DEALER')
        for k, v in (('filter_hu_months', 'soon'), ('filter_hu_months', '-3'), ('filter_seller', 'BOTH')):
            with self.assertRaises(ValueError, msg=(k, v)):
                ranking.check_filter(k, v)


class Tax(unittest.TestCase):
    def test_an_unknown_registration_keeps_a_windowed_tax_row(self):
        k = costs.Knowledge.__new__(costs.Knowledge)  # only the rows of one table: no database needed
        k.t, k.jobs = {'tax_data': [{'id': 1, 'vehicle_id': 1, 'annual_tax_eur': 100, 'status': 'VERIFIED',
                                     'registered_from': '2015-01', 'registered_to': '2019-12'}]}, None
        self.assertEqual(k.tax({'id': 1}, None)['id'], 1)
        self.assertEqual(k.tax({'id': 1}, '2017-05')['id'], 1)
        self.assertIsNone(k.tax({'id': 1}, '2021-05'))


class Dossier(unittest.TestCase):
    def test_dossier_names_differ_for_listings_that_differ_only_in_punctuation(self):
        base = dict(make='VW', model='Golf', platform='Test', trim=None)
        a = markdown_export.filename({**base, 'id': 4, 'listing_id': 'A-1'})
        b = markdown_export.filename({**base, 'id': 5, 'listing_id': 'A1'})
        self.assertNotEqual(a, b)
        self.assertTrue(a.endswith('-4.md') and b.endswith('-5.md'))


class GenerationName(unittest.TestCase):
    def test_an_empty_name_matches_no_catalogue_generation_by_name(self):
        c = sqlite3.connect(':memory:')
        c.row_factory = sqlite3.Row
        c.executescript((config.ROOT / 'schema.sql').read_text(encoding='utf-8'))
        c.execute("INSERT INTO main.generations (make, model, name, start_year, owner_id) VALUES ('VW', 'Polo', '', 2010, NULL)")
        new = {'make': 'VW', 'model': 'Polo', 'name': '', 'start_year': 2030}
        self.assertIsNone(agent.resolve_level(c, 'generations', new))
        self.assertIsNotNone(agent.resolve_level(c, 'generations', {**new, 'start_year': 2010}))  # same start year still matches


class BindAddressTest(unittest.TestCase):  # S3: loopback or a Tailscale address only
    def test_loopback_and_tailscale_addresses_are_accepted(self):
        for h in ('127.0.0.1', 'localhost', 'LOCALHOST', '100.64.0.1', '100.101.102.103', '100.127.255.254'):
            self.assertTrue(config.host_ok(h), h)

    def test_public_wildcard_and_other_addresses_are_refused(self):
        for h in ('0.0.0.0', '203.0.113.5', '100.63.255.255', '100.128.0.0', '192.168.1.10', '::', 'example.com', '', '100.64.0.0/10'):
            self.assertFalse(config.host_ok(h), h)


if __name__ == '__main__':
    unittest.main()
