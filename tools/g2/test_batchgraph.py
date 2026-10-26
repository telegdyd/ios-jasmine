"""Host parser tests: interleaved contexts, incomplete edges, and lost data."""
import unittest
from batchgraph import analyze


def log(events):
    return '\n'.join(f'sweetca: batchtrace e={n} us=1 cause=test {e}'
                     for n, e in enumerate(events, 1))


class GraphTest(unittest.TestCase):
    def test_only_complete_intervals(self):
        result = analyze(log([
            'event=draw ctx=a screen=s batch=1 draws=5',
            'event=frame-end ctx=a frame=10',
            'event=draw ctx=a screen=s batch=2 draws=1',
            'event=bound-view ctx=a screen=s batch=2 aliases=1',
            'event=read-dependency ctx=a screen=s batch=3 other=2',
            'event=flush ctx=a screen=s batch=2 draws=1',
            'event=select-sysmem ctx=a screen=s batch=2',
            'event=frame-end ctx=a frame=11',
            'event=draw ctx=a screen=s batch=4 draws=1',
        ]))
        self.assertTrue(result['valid'])
        self.assertEqual(result['complete_flush_intervals'], 1)
        ctx = result['contexts']['a']
        self.assertEqual(ctx['draw_records'], 1)
        self.assertEqual(ctx['potential_feedback_batches'], 1)
        self.assertEqual(ctx['dependency_edges'], 1)
        self.assertEqual(ctx['batches_without_bound_alias_evidence'], 0)

    def test_contexts_and_carry_in(self):
        result = analyze(log([
            'event=frame-end ctx=a frame=1',
            'event=frame-end ctx=b frame=20',
            'event=draw ctx=a screen=s batch=1 draws=1',
            'event=draw ctx=b screen=s batch=2 draws=3',
            'event=flush ctx=b screen=s batch=2 draws=3',
            'event=frame-end ctx=b frame=21',
            'event=flush ctx=a screen=s batch=1 draws=1',
            'event=frame-end ctx=a frame=2',
        ]))
        self.assertEqual(result['complete_flush_intervals'], 2)
        self.assertEqual(result['contexts']['a']['batches_without_bound_alias_evidence'], 1)
        self.assertEqual(result['contexts']['b']['carry_in_or_unseen_draw_batches'], 1)

    def test_missing_or_truncated_records(self):
        text = log(['event=frame-end ctx=a frame=1', 'event=frame-end ctx=a frame=2'])
        self.assertFalse(analyze(text.replace('e=2', 'e=3'))['valid'])
        self.assertFalse(analyze(text + ' truncated=1')['valid'])

    def test_marker_loss_and_frame_gap(self):
        for middle in ('event=frame-marker-lost ctx=a frame=2',
                       'event=draw ctx=a screen=s batch=1 draws=1'):
            result = analyze(log(['event=frame-end ctx=a frame=1', middle,
                                  'event=frame-end ctx=a frame=3']))
            self.assertFalse(result['valid'])
            self.assertEqual(result['complete_flush_intervals'], 0)

    def test_malformed_fields(self):
        for event in ('event=draw ctx=a batch=1',
                      'event=bound-view ctx=a batch=1 aliases=garbage',
                      'event=frame-end ctx=a frame=bad'):
            self.assertFalse(analyze(log([event]))['valid'])

    def test_device_console_concatenation_and_damaged_tail(self):
        text = ('|backboardd| sweetca: batchtrace e=1 us=1 cause=test event=frame-end ctx=a frame=1\n'
                '|backboardd| sweetca: batchtrace e=2 us=2 cause=test event=draw ctx=a '
                'screen=s batch=1 draws=1 clear=0 |backboardd| e=4\n'
                '|backboardd| sweetca: batchtrace e=3 us=3 cause=test event=target ctx=a batch=1 '
                'valid=|backboardd| sweetca: batchtrace e=4 us=4 cause=test '
                'event=flush ctx=a screen=s batch=1 draws=1\n'
                '|backboardd| sweetca: batchtrace e=5 us=5 cause=test event=frame-end ctx=a frame=2\n')
        result = analyze(text)
        self.assertTrue(result['valid'])
        self.assertEqual(result['records'], 5)
        self.assertFalse(result['complete_record_fields'])
        self.assertEqual(result['contexts']['a']['draw_records'], 1)
        self.assertEqual(result['contexts']['a']['flushes'], 1)


if __name__ == '__main__':
    unittest.main()
