#!/usr/bin/env python3
"""Offline configd provisioning checks; no device/network access."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('wifi_config', Path(__file__).with_name('wifi-root-config.py'))
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)


class WiFiConfigTest(unittest.TestCase):
    def test_fresh_and_idempotent(self):
        original = {'System': {'System': {'ComputerName': 'iPhone'}}}
        result = config.configure(original)
        self.assertEqual(config.configure(result), result)
        self.assertEqual(result['System'], original['System'])
        sid, service = next(iter(result['NetworkServices'].items()))
        self.assertEqual(service['IPv4']['ConfigMethod'], 'DHCP')
        network = result['Sets'][result['CurrentSet'][6:]]['Network']
        self.assertEqual(network['Global']['IPv4']['ServiceOrder'], [sid])
        self.assertEqual(network['Service'][sid]['__LINK__'], '/NetworkServices/' + sid)
        self.assertNotIn('NetworkServices', original)

    def test_preserves_existing_networks_and_static_wifi(self):
        service = {'Interface': {'DeviceName': 'en0'},
                   'IPv4': {'ConfigMethod': 'Manual', 'Addresses': ['192.0.2.2']}}
        original = {'CurrentSet': '/Sets/A', 'NetworkServices': {'W': service, 'U': {'USB': True}},
                    'Sets': {'A': {'Network': {'Global': {'IPv4': {'ServiceOrder': ['U']}}}},
                             'B': {'untouched': True}}, 'Other': [1, 2]}
        result = config.configure(original)
        self.assertEqual(result['NetworkServices'], original['NetworkServices'])
        self.assertEqual(result['Sets']['B'], original['Sets']['B'])
        self.assertEqual(result['Other'], [1, 2])
        self.assertEqual(result['Sets']['A']['Network']['Global']['IPv4']['ServiceOrder'], ['U', 'W'])
        self.assertEqual(config.configure(result), result)

    def test_stale_current_set_is_repaired_without_deleting_sets(self):
        result = config.configure({'CurrentSet': '/Sets/missing', 'Sets': {'old': {'kept': True}}})
        self.assertIn(result['CurrentSet'][6:], result['Sets'])
        self.assertEqual(result['Sets']['old'], {'kept': True})


if __name__ == '__main__':
    unittest.main()
