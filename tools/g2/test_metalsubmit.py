import unittest
from metalsubmit import analyze


class InventoryTests(unittest.TestCase):
    def fixture(self):
        return ('# commits=1 dropped=0; diagnostic\ncb,event,a,b,c,d,e,f,g,h\n'
                '1,begin,3,0,0,0,0,0,0,0\n'
                '1,enqueue,12,0,40,2,0,0,0,0\n'
                '1,kernel,12,1,40,1,184,0,0,0\n'
                '1,kernel-result,12,45,0,0,0,0,0,0\n'
                '1,end,0,0,0,0,0,0,0,0\n')

    def test_summary(self):
        r = analyze(self.fixture())
        self.assertEqual(r['kernel_calls'], 1)
        self.assertEqual(r['enqueue_reasons'], {'policy_limit': 1})
        self.assertEqual(r['max_kernel_bos'], 40)
        self.assertEqual(r['legacy_policy_projected_calls'], 1)

    def test_projection_retains_explicit_drains_and_ignores_group_drains(self):
        s = ('# commits=1 dropped=0; diagnostic\ncb,event,a,b,c,d,e,f,g,h\n'
             '1,begin,3,0,0,0,0,0,0,0\n'
             '1,enqueue,1,0,40,2,0,0,0,1\n'
             '1,enqueue,2,0,40,2,2,0,0,1\n'
             '1,group-capacity,3,0,600,6,0,0,0,0\n'
             '1,drain,0,0,4,0,0,0,0,0\n'
             '1,kernel,2,2,60,2,0,0,0,0\n'
             '1,kernel-result,2,10,0,0,0,0,0,0\n'
             '1,enqueue,3,0,12,2,0,0,0,1\n'
             '1,drain,0,0,2,0,0,0,0,0\n'
             '1,kernel,3,1,12,1,0,0,0,0\n'
             '1,kernel-result,3,11,0,0,0,0,0,0\n'
             '1,end,0,0,0,0,0,0,0,0\n')
        r = analyze(s)
        self.assertEqual(r['kernel_calls'], 2)
        self.assertEqual(r['legacy_policy_projected_calls'], 3)

    def test_rejects_incomplete_evidence(self):
        s = self.fixture()
        for broken in (s.replace('dropped=0', 'dropped=1'),
                       s.replace('commits=1', 'commits=2'),
                       s[:s.index('1,end')],
                       s.replace('1,end', '1,begin'),
                       s.replace('1,kernel-result,12,45,0', '1,kernel-result,12,45,5'),
                       '\n'.join(line for line in s.splitlines() if 'kernel-result' not in line)):
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                analyze(broken)


if __name__ == '__main__':
    unittest.main()
