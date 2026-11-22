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


if __name__ == '__main__':
    unittest.main()
