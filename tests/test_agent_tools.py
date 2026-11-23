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
        # 20,000 € at 60,000 km, 4 years, 15,000 km a year: km at the end 60,000 + 4 × 15,000 = 120,000
        # loss = 1,367.4 × 4 − 25.28 × 16 + 159.6 × 12 = 5,469.60 − 404.48 + 1,915.20 = 6,980.32
        # expected: (20,000 − 6,980.32) × 0.90 = 11,717.71 → 11,720; low: (20,000 − 1.5 × 6,980.32) × 0.80 = 7,623.62 → 7,620;
        # high: (20,000 − 0.5 × 6,980.32) × 0.95 = 15,684.35 → 15,680
        self.assertEqual(agent_tools.resale_values(20000, 60000, 4, 15000),
                         {'low_eur': 7620, 'expected_eur': 11720, 'high_eur': 15680})
        self.assertEqual(agent_tools.resale_values(20000, 60000, 4, 15000, electric=True)['expected_eur'], 7620)

    def test_held_zero_years_and_zero_km_keeps_the_list_value(self):
        # no loss: list value less only the private-sale discount of each case
        self.assertEqual(agent_tools.resale_values(20000, 0, 0, 15000),
                         {'low_eur': 16000, 'expected_eur': 18000, 'high_eur': 19000})

    def test_never_negative(self):
        # 25 years, 250,000 km: loss = 34,185 − 15,800 + 3,990 = 22,375 > 20,000 → 0 (low and expected);
        # high halves the loss: (20,000 − 11,187.50) × 0.95 = 8,371.88 → 8,370
        self.assertEqual(agent_tools.resale_values(20000, 250000, 25, 0),
                         {'low_eur': 0, 'expected_eur': 0, 'high_eur': 8370})

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
        self.assertEqual((body['low_eur'], body['expected_eur'], body['high_eur']), (7620, 11720, 15680))
        self.assertIn('1367.4', body['notes'])

    def test_nan_or_inf_is_unknown_never_zero(self):  # S5
        nan, inf = float('nan'), float('inf')
        self.assertEqual(agent_tools.resale_values(nan, 60000, 4, 15000), {'low_eur': None, 'expected_eur': None, 'high_eur': None})
        self.assertEqual(agent_tools.resale_values(20000, 60000, nan, 15000)['expected_eur'], None)
        self.assertEqual(agent_tools.resale_values(inf, 60000, 4, 15000)['high_eur'], None)

    def test_stored_resale_moved_to_another_period_stays_unknown_for_nan(self):  # S5, costs.resale_at
        from carlos import costs
        end = {'horizon_years': 4, 'low_eur': float('nan'), 'expected_eur': 10000, 'high_eur': 12000}
        out = costs.resale_at(end, 6, 15000, km_now=60000)
        self.assertIsNone(out['low_eur'])
        self.assertIsInstance(out['expected_eur'], float)
        out = costs.resale_at({'horizon_years': 4, 'low_eur': 6000, 'expected_eur': float('nan'), 'high_eur': 8000}, 6, 15000, km_now=60000)
        self.assertIsNone(out['expected_eur'])
        self.assertEqual(out['low_eur'] > 0, True)

    def test_rescale_is_the_loss_difference_of_the_same_formula(self):  # costs.resale_at = costs.resale_loss
        from carlos import costs
        end = {'horizon_years': 4, 'low_eur': 7620, 'expected_eur': 11720, 'high_eur': 15680}
        out = costs.resale_at(end, 6, 15000, km_now=60000)
        # loss(6 years, 150,000 km) − loss(4 years, 120,000 km) = 2,708.00 €, scaled per case and discounted
        d = costs.resale_loss(6, 60000 + 6 * 15000) - costs.resale_loss(4, 60000 + 4 * 15000)
        self.assertAlmostEqual(out['expected_eur'], round(11720 - d * 0.90, 2), delta=0.01)
        self.assertAlmostEqual(out['low_eur'], round(7620 - 1.5 * d * 0.80, 2), delta=0.01)
        self.assertAlmostEqual(out['high_eur'], round(15680 - 0.5 * d * 0.95, 2), delta=0.01)
        self.assertIsNone(costs.resale_at(end, 6, 15000, km_now=None)['expected_eur'])


if __name__ == '__main__':
    unittest.main()
