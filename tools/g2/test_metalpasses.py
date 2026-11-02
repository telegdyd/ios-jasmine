import unittest
from metalpasses import analyze, union_ticks


def row(cb, p, event, values=()):
    return ','.join(map(str, [cb, p, event, *values, *([0]*(20-len(values)))]))


def capture(shared=False):
    rows = [row(1, 0, 'begin'), row(1, 1, 'pass', [64, 64, 1, 1, 80]),
            row(1, 1, 'link', [42, 7])]
    if shared:
        rows += [row(1, 2, 'pass', [64, 64, 1, 1, 80]), row(1, 2, 'link', [42, 7])]
    rows += [row(1, 1, 'batch', [42, 7, 64, 64, 1, 1, 9, 0, 1, 2, 1, 1, 1, 0, 0, 19200, 38400]), row(1, 1, 'end')]
    return '# commits=1 dropped=0 pending=0 pid=123\ncb,pass,event,' + ','.join(f'v{k}' for k in range(20)) + '\n' + '\n'.join(rows)


class AttributionTests(unittest.TestCase):
    def test_shared_batch_not_charged_twice(self):
        r = analyze(capture(True))
        self.assertEqual((r['batches'], r['encoded_passes'], r['shared_batches']), (1, 2, 1))
        self.assertEqual(r['gpu_sum_ms'], 1)
        self.assertEqual(len(r['ranked'][0]['encoded_passes']), 2)

    def test_union_handles_overlap_and_out_of_order(self):
        self.assertEqual(union_ticks([(20, 40), (10, 30), (100, 110)]), 40)

    def test_shader_label_and_sampled_shapes_preserved(self):
        label = b'fragment_blur\0'.ljust(96, b'\0')
        words = [int.from_bytes(label[k:k+8], 'little') for k in range(0, 96, 8)]
        shader = row(1, 1, 'shader', words + [3, 828, 1792, 80, 207, 448, 10, 2])
        result = analyze(capture().replace('\n1,1,link,', '\n'+shader+'\n1,1,link,'))
        group = result['ranked'][0]
        self.assertEqual(group['linked_shader_draws'], {'fragment_blur': 3})
        self.assertEqual(group['sampled_first_two'], [(828, 1792, 80, 207, 448, 10, 2)])

    def test_reject_loss_pending_bad_stamps_missing_end(self):
        s = capture()
        for bad in [s.replace('dropped=0', 'dropped=1'), s.replace('pending=0', 'pending=1'),
                    s.replace(',19200,38400,', ',38400,19200,'), s.rsplit('\n', 1)[0]]:
            with self.assertRaises(ValueError):
                analyze(bad)


if __name__ == '__main__':
    unittest.main()
