import unittest

from metallifetimes import audit
from test_metalpasses import capture, row


def access(kind, rid=1, logical=100, surface=0, mask=15, detail=0, level=0):
    return row(1, 1, 'access', [kind, rid, logical, surface, level, 0,
        0, 0, 0, 64, 64, 1, mask, detail, 64, 64, 0, 1, 1, 9])


def graph(*events):
    return capture().replace('\n1,1,end,', '\n' + '\n'.join(events) + '\n1,1,end,')


class LifetimeTests(unittest.TestCase):
    def test_fetch_clear_copy_and_cpu_observers_preserved(self):
        r = audit(graph(access(1, mask=1, detail=1 << 32), access(2),
            access(3, mask=31), access(6), access(10), access(1, detail=2)))
        t = r['transitions'][0]
        self.assertEqual(t['intervening'], dict(clear=1, draw=1, copy_src=1, cpu_read=1))
        self.assertEqual(t['fetching_draws'], 1)
        self.assertFalse(t['removable'])
        self.assertEqual(r['graph'][2]['write_mask'], 15)

    def test_surface_alias_and_resource_pool_reuse_remain_hazards(self):
        r = audit(graph(access(1, surface=17), access(1, rid=2, logical=200, surface=17),
            access(14, surface=17), access(1, rid=3)))
        self.assertEqual(r['surface_aliases'], {'17': [1, 2]})
        self.assertEqual(r['logical_reuse_or_aliases'], {'100': [1, 3]})
        self.assertEqual(r['proven_removals'], 0)

    def test_complete_clear_and_capture_end_are_not_deadness_proofs(self):
        r = audit(graph(access(1), access(2), access(1, detail=2)))
        self.assertEqual(r['proven_removals'], 0)
        self.assertFalse(r['transitions'][0]['removable'])

    def test_identity_changes_loss_and_missing_access_rejected(self):
        for bad in [capture(), graph(access(1), access(2, logical=200)),
                    graph(access(1)).replace('dropped=0', 'dropped=1')]:
            with self.assertRaises(ValueError):
                audit(bad)

    def test_access_outside_scope_and_unknown_depth_masks(self):
        r = audit(graph(access(3, mask=0xffffffff)))
        self.assertIsNone(r['graph'][0]['fetch'])
        with self.assertRaises(ValueError):
            audit(capture() + '\n' + access(1))


if __name__ == '__main__':
    unittest.main()
