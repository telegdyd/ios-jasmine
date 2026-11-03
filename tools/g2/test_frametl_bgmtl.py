import io
import struct
import shutil
from contextlib import contextmanager
import unittest
from pathlib import Path

import bgmtl_timeline as btl
import framebench as fb


def record(t, kind, cb, a=0, b=0):
    return btl.REC.pack(t, kind, cb, a, b)


def site(file, line, tid):
    return (file << 62) | (line << 48) | tid


def write_ring(path, records, *, dropped=0, numer=1, denom=1, start=1_000_000, count=None):
    if count is None:
        count = len(records)
    header = btl.HDR.pack(0x4c544742, 1, btl.HDR.size, 4242, count, dropped, 0,
                          start, start + 8_000_000_000, numer, denom)
    Path(path).write_bytes(header + b''.join(records))


@contextmanager
def workdir():
    """Workspace-local scratch dir; tempfile's ACL under the DSH sandbox is denied."""
    d = Path(__file__).resolve().parent / '.tl-test-tmp'
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir()
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


class TimelineParserTests(unittest.TestCase):
    def fixture(self, tmp, *, dropped=0):
        start = 1_000_000
        recs = [
            record(start + 0, 1, 1),             # CREATE
            record(start + 100_000, 2, 1, 3),    # COMMIT_ENTER, 3 work items
            record(start + 150_000, 4, 1, 5, 7),  # TICKET_BEGIN gen 5, epoch 7
            record(start + 200_000, 3, 1, 0, 99),  # REPLAY_BEGIN inline, thread 99
            record(start + 400_000, 5, 1),       # SUBMIT_BEGIN
            record(start + 450_000, 6, 1, 450),  # SUBMIT_END, kernel seqno 450
            record(start + 460_000, 8, 1, 0, 99),  # SCHEDULED_RUN replay
            record(start + 500_000, 7, 1, 4),    # REPLAY_END, status 4
            record(start + 700_000, 9, 1, 0, 250),  # FENCE_OBSERVED, 250 us
            record(start + 700_000, 14, 1, 1, 99),  # HANDLERS_BEGIN, 1 handler, thread 99
            record(start + 900_000, 10, 1, 4, 1),  # COMPLETED_RUN, status 4, completion
            record(start + 910_000, 12, 1, 1, 99),  # PRESENT_ENTER
            record(start + 930_000, 11, 1, 0, 1),  # PRESENT_POST
            # CB 2 never completes: the parser must flag it.
            record(start + 900_000, 1, 2),
            record(start + 950_000, 2, 2, 1),
            record(start + 1_000_000, 3, 2, 0, 99),
            record(start + 1_100_000, 5, 2),
            record(start + 1_150_000, 6, 2, 451),
            record(start + 1_160_000, 7, 2, 4),
            record(start + 1_200_000, 9, 2, 0, 50),
            # LOCK_WAITs have cb=NO_CB and must never create a CB row.
            record(start + 850_000, 13, btl.NO_CB, site(0, 1472, 99), 150_000),
            record(start + 1_000_000, 13, btl.NO_CB, site(1, 39, 99), 100_000),
        ]
        path = Path(tmp) / 'bgmtl-tl-4242.bin'
        write_ring(path, recs, dropped=dropped)
        return path, start

    def test_intervals_and_incomplete(self):
        with workdir() as tmp:
            path, _ = self.fixture(tmp)
            cap = btl.load(path)
            self.assertEqual(cap['count'], len(cap['records']))
            rows = btl.build(cap)
            self.assertEqual([r['cb'] for r in rows], [1, 2])
            a, b = rows
            self.assertAlmostEqual(a['create_to_commit'], 0.100, places=6)
            self.assertAlmostEqual(a['commit_to_replay'], 0.100, places=6)
            self.assertAlmostEqual(a['replay_to_submit_begin'], 0.200, places=6)
            self.assertAlmostEqual(a['submit_begin_to_end'], 0.050, places=6)
            self.assertAlmostEqual(a['submit_end_to_fence'], 0.250, places=6)
            self.assertAlmostEqual(a['submit_end_to_scheduled'], 0.010, places=6)
            self.assertIsNone(a['fence_to_scheduled'])       # scheduled ran before fence
            self.assertTrue(a['scheduled_before_fence'])
            self.assertAlmostEqual(a['fence_to_handlers_begin'], 0.000, places=6)
            self.assertAlmostEqual(a['handlers_begin_to_completed'], 0.200, places=6)
            self.assertAlmostEqual(a['fence_to_completed'], 0.200, places=6)
            self.assertEqual(a['handler_count'], 1)
            self.assertEqual(a['handler_tid'], 99)
            self.assertAlmostEqual(a['present_enter_to_post'], 0.020, places=6)
            self.assertAlmostEqual(a['total'], 0.900, places=6)
            self.assertEqual(a['dominant'][0], 'submit_end_to_fence')
            self.assertEqual(a['seqno'], 450)
            self.assertEqual(a['generation'], 5)
            self.assertEqual(a['scheduled_queue'], 'replay')
            self.assertEqual(a['completed_queue'], 'completion')
            self.assertTrue(b['missing_completed'])
            self.assertIsNone(b['fence_to_completed'])

            st = btl.stats(rows)
            self.assertEqual(st['create_to_commit']['count'], 2)
            self.assertEqual(st['fence_to_completed']['count'], 1)
            self.assertAlmostEqual(st['create_to_commit']['p50'], 0.050, places=6)

    def test_lock_waits_handler_overlap_and_report(self):
        with workdir() as tmp:
            path, _ = self.fixture(tmp)
            cap = btl.load(path)
            rows = btl.build(cap)
            self.assertEqual([r['cb'] for r in rows], [1, 2], 'NO_CB lock wait made a CB row')
            waits = btl.annotate_waits(btl.lock_waits(cap), rows)
            self.assertEqual(len(waits), 2)
            inside = [w for w in waits if w['inside']]
            self.assertEqual(len(inside), 1)
            self.assertEqual(inside[0]['cb'], btl.NO_CB)
            self.assertEqual(inside[0]['tid'], 99)
            self.assertEqual(inside[0]['inside'], [1])
            self.assertAlmostEqual(inside[0]['ms'], 0.150, places=6)
            self.assertEqual([w for w in waits if not w['inside']][0]['inside'], [])
            st = btl.lock_stats(waits)
            self.assertEqual(len(st), 2)
            self.assertEqual(st[0]['count'], 1)
            self.assertEqual(st[0]['inside_count'], 1)
            out = io.StringIO()
            summary = btl.report(path, out=out)
            text = out.getvalue()
            self.assertIn('bg_lock waits', text)
            self.assertIn('waits inside completed handlers', text)
            self.assertIn('bgmtl.m:1472', text)
            self.assertIn('bg_write_admission.h:39', text)
            self.assertIn('10 slowest completed-handler runs', text)
            self.assertEqual(len(summary['waits']), 2)
            self.assertEqual(len(summary['lock_stats']), 2)

    def test_source_site_resolves_current_getbytes(self):
        src = (btl.SRC_DIR / 'bgmtl.m').read_text(encoding='utf-8', errors='replace').splitlines()
        start = next(i for i, line in enumerate(src, 1)
                     if '- (void)getBytes:(void *)bytes bytesPerRow' in line)
        label = btl._site_label(0, start + 4)
        self.assertIn('bgmtl.m:', label)
        self.assertIn('getBytes', label)

    def test_report_flags_missing_completed_and_dropped(self):
        with workdir() as tmp:
            path, _ = self.fixture(tmp, dropped=2)
            out = io.StringIO()
            summary = btl.report(path, out=out)
            self.assertTrue(summary['incomplete'])
            text = out.getvalue()
            self.assertIn('CAPTURE INCOMPLETE', text)
            self.assertIn('2 ring records dropped', text)
            self.assertIn('missing COMPLETED_RUN', text)

    def test_kernel_join_by_seqno_and_generation(self):
        with workdir() as tmp:
            path, _ = self.fixture(tmp)
            rows = btl.build(btl.load(path))
            events = [
                (1_000_000, 20, 5, 1, 450, 1, 2, 0),   # submit seqno 450
                (1_000_100, 30, 5, 1, 7, 5, 0, 7),     # ticket gen 5 (a=surface, b/c gen)
                (1_000_200, 39, 5, 1, 8, 5, 0, 1000),  # present wait maps swap 8 -> gen 5
            ]
            join = btl.kernel_join(rows, events)
            self.assertEqual(join['seqno_matches'], 1)
            self.assertEqual(join['generation_matches'], 1)
            self.assertTrue(rows[0]['seqno_match'])
            self.assertTrue(rows[0]['generation_match'])

    def test_rejects_truncated_or_bad_magic(self):
        with workdir() as tmp:
            path = Path(tmp) / 'bad.bin'
            path.write_bytes(b'BGTL' + b'\0' * 10)
            with self.assertRaises(ValueError):
                btl.load(path)
            write_ring(path, [record(1_000_000, 1, 1)])
            data = path.read_bytes()
            path.write_bytes(b'XXXX' + data[4:])
            with self.assertRaises(ValueError):
                btl.load(path)

    def test_manifest_epoch_variants(self):
        import json
        with workdir() as tmp:
            out = Path(tmp)
            (out / 'manifest.json').write_text(json.dumps({'bench_epoch': 12345}), encoding='utf-8')
            self.assertEqual(btl.manifest_epoch(out), 12345)
            (out / 'manifest.json').write_text(json.dumps({'bench stat': 'bench-v1 active=0 epoch=54321 elapsed_us=0'}), encoding='utf-8')
            self.assertEqual(btl.manifest_epoch(out), 54321)
            (out / 'manifest.json').write_text(json.dumps({'capture_epoch': 222, 'bench_epoch': 111}), encoding='utf-8')
            self.assertEqual(btl.manifest_epoch(out), 222)
            (out / 'manifest.json').write_text(json.dumps({'capture_stat': {'epoch': 777}}), encoding='utf-8')
            self.assertEqual(btl.manifest_epoch(out), 777)


class Event40Tests(unittest.TestCase):
    def test_memory_snapshot_is_not_ticket_owner(self):
        # bc_memory_snapshot: a=free pages, b=wired pages (non-zero), c=free_wanted, d=tasks.
        memory = (1, 40, 5, 7, 100000, 50000, 2, 300)
        # sweet_ticket_metadata: a/b=generation, c/d=identity, always followed by a
        # 41 for the same generation; a non-zero generation high word must still count.
        owner = (2, 40, 5, 7, 5, 1, 9, 0)
        epoch = (3, 41, 5, 7, 5, 1, 4, 0)
        p = fb.present_report([memory, owner, epoch])
        self.assertEqual(p['counts'].get('TICKET_OWNER'), 1)
        self.assertEqual(p['timeline'][0]['generation'], (1 << 32) | 5)


if __name__ == '__main__':
    unittest.main()
