import os
import unittest
from unittest import mock

os.environ.setdefault("AGENT_TOKEN", "x")
import agent_tools  # noqa: E402


class ScopeGuard(unittest.TestCase):
    def test_missing_level_raises(self):
        with mock.patch.object(agent_tools, 'get', return_value={'engine_family_id': None, 'engine_id': 3}):
            with self.assertRaisesRegex(ValueError, 'no engine_family yet'):
                agent_tools.scope(1, 'engine_family')
            self.assertEqual(agent_tools.scope(1, 'engine'), {'engine_id': 3})


class ResaleRule(unittest.TestCase):
    def test_known_car_by_hand(self):
        # 20,000 € at 60,000 km, 4 years, 15,000 km a year: km driven 60,000 + 4 × 15,000 = 120,000
        # expected: (20,000 − 495 × 4 − 0.051 × 120,000) × 0.90 = 11,900 × 0.90 = 10,710
        # low: (20,000 − 1.5 × 8,100) × 0.80 = 7,850 × 0.80 = 6,280; high: (20,000 − 0.5 × 8,100) × 0.95 = 15,152.5 → 15,150
        self.assertEqual(agent_tools.resale_values(20000, 60000, 4, 15000),
                         {'low_eur': 6280, 'expected_eur': 10710, 'high_eur': 15150})
        self.assertEqual(agent_tools.resale_values(20000, 60000, 4, 15000, electric=True)['expected_eur'], 6280)
        self.assertEqual(agent_tools.resale_values(5000, 200000, 10, 15000)['expected_eur'], 0)   # floored at 0, never negative

    def test_rule_posts_a_valuation(self):
        listing = {'price_eur': 20000, 'mileage_km': 60000}
        params = {'parameters': {'ownership_years': 4, 'annual_km': 15000}}
        with mock.patch.object(agent_tools, 'listing', return_value=listing), \
                mock.patch.object(agent_tools, 'get', return_value=params), \
                mock.patch.object(agent_tools, 'shared_source', return_value=7), \
                mock.patch.object(agent_tools, 'post', return_value={'id': 1}) as post:
            agent_tools.resale_rule_of_thumb(5)
        kind, body = post.call_args[0]
        self.assertEqual((kind, body['kind'], body['horizon_years'], body['status'], body['source_id']), ('valuations', 'resale_end', 4, 'ESTIMATED', 7))
        self.assertEqual((body['low_eur'], body['expected_eur'], body['high_eur']), (6280, 10710, 15150))
        self.assertIn('0.051', body['notes'])

    def test_nan_or_inf_is_unknown_never_zero(self):  # S5
        nan, inf = float('nan'), float('inf')
        self.assertEqual(agent_tools.resale_values(nan, 60000, 4, 15000), {'low_eur': None, 'expected_eur': None, 'high_eur': None})
        self.assertEqual(agent_tools.resale_values(20000, 60000, nan, 15000)['expected_eur'], None)
        self.assertEqual(agent_tools.resale_values(inf, 60000, 4, 15000)['high_eur'], None)

    def test_stored_resale_moved_to_another_period_stays_unknown_for_nan(self):  # S5, costs.resale_at
        from carlos import costs
        end = {'horizon_years': 4, 'low_eur': float('nan'), 'expected_eur': 10000, 'high_eur': 12000}
        out = costs.resale_at(end, 6, 15000)
        self.assertIsNone(out['low_eur'])
        self.assertIsInstance(out['expected_eur'], float)
        out = costs.resale_at({'horizon_years': 4, 'low_eur': 6000, 'expected_eur': float('nan'), 'high_eur': 8000}, 6, 15000)
        self.assertIsNone(out['expected_eur'])
        self.assertEqual(out['low_eur'] > 0, True)


if __name__ == '__main__':
    unittest.main()
