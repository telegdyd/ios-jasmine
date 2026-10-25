"""Offline correctness and failure-path tests; never contact the phone."""
import argparse
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock
import importlib.util
import struct

import framebench as fb


def event(us, kind, phase=5, a=0, b=0, c=0, d=0, tid=1):
    return fb.EVENT.pack(us, kind, phase, tid, a, b, c, d)


def snapshot(us=1000000, free=128 << 20, wanted=0, footprint=64 << 20, uniqueid=99):
    return fb.parse_snapshot(f'memory {us} 2147483648 {free} 400000000 200000000 100000000 {wanted} 4096 10 2000000 5 3000000 0 0 0 0\n'
        f'process 123 {uniqueid} {footprint} {footprint} 0 PosterBoard\ntasks 1 1\n')


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def capture(self, events=b'', progress=(), status='captured', stat=None):
        fb.save_json(self.root / 'manifest.json', {'mode': 'standard', 'status': status, 'capture_stat': stat or {}})
        (self.root / 'events.bin').write_bytes(events)
        for p in progress:
            fb.log(self.root, 'memory', snapshot=p)
        return fb.analyze(self.root)

    def test_boundary_stall_survives_zero_frames(self):
        s = self.capture(event(0, 4, a=1) + event(2500000, 3))
        m = s['phases']['home-a']['motion']
        self.assertEqual(m['updates_per_second'], 0)
        self.assertEqual(m['max_no_update_including_boundaries_ms'], 2500)
        self.assertEqual(m['stalls_over_100ms'], 1)

    def test_intentional_hold_excluded_but_slow_motion_retained(self):
        data = event(0, 4, a=1) + event(10000, 11, a=1) + event(220000, 11, a=2)
        data += event(250000, 4, a=0) + event(5000000, 3)
        m = self.capture(data)['phases']['home-a']['motion']
        self.assertEqual(m['active_seconds'], .25)
        self.assertEqual(m['p95_ms'], 210)
        self.assertEqual(m['updates_per_second'], 8)

    def test_timeout_and_copy_never_become_hardware_latches(self):
        data = event(0, 4, a=1) + event(1000, 15, a=1) + event(2000, 16, a=2)
        data += event(3000, 14, a=3) + event(4000, 14, a=3) + event(100000, 4, a=0)
        p = self.capture(data)['phases']['home-a']
        self.assertEqual(p['ctl_clear_observation_proxy']['updates'], 1)
        self.assertEqual(p['latch_timeout_fallbacks'], 1)
        self.assertEqual(p['immediate_or_copy_retirements'], 1)
        self.assertIsNone(p['displayed_fps'])

    def test_pressure_beats_historical_cpu_ranking(self):
        s = self.capture(progress=[snapshot(free=16 << 20, wanted=2)], status='partial')
        self.assertIn('20', s['ranking'][0]['task'])
        self.assertIn('pressure', s['ranking'][0]['evidence'] if 'pressure' in s['ranking'][0]['evidence'] else s['ranking'][0]['task'])

    def test_growth_is_not_called_leak_or_pressure(self):
        s = self.capture(progress=[snapshot(), snapshot(us=2000000, footprint=300 << 20)])
        self.assertEqual(s['ranking'][0]['task'], '20')
        self.assertIn('does not prove', s['ranking'][0]['confidence'])

    def test_pid_reuse_does_not_create_fake_growth(self):
        s = self.capture(progress=[snapshot(), snapshot(us=2000000, footprint=300 << 20, uniqueid=100)])
        self.assertEqual(max(r['observed_growth_bytes'] for r in s['memory']['process_growth']), 0)
        self.assertEqual(s['memory']['observed_process_incarnations']['PosterBoard'], 2)
        self.assertFalse(s['memory']['process_growth'][0]['present_at_end'])

    def test_no_old_task5_fallback_without_evidence(self):
        s = self.capture()
        self.assertIn('missing attribution', s['ranking'][0]['task'])

    def test_multi_job_surface_and_completion_watermark(self):
        data = event(1, 20, a=8) + event(2, 22, a=8, b=50) + event(3, 20, a=9)
        data += event(4, 21, a=9) + event(5, 22, a=9, b=50)
        s = self.capture(data)
        jobs = s['gpu']['matched_jobs']
        self.assertEqual([j['sequence'] for j in jobs], [8, 9])
        self.assertEqual([j['surfaces'] for j in jobs], [[50], [50]])

    def test_reused_surface_generations_are_preserved(self):
        data = event(1, 13, a=1, b=50, c=8) + event(2, 13, a=2, b=50, c=9)
        rows = list(fb.EVENT.iter_unpack(data))
        self.assertNotEqual(rows[0][6], rows[1][6])

    def test_truncated_and_absent_dictionary_are_rejected(self):
        (self.root / 'broken.bin').write_bytes(b'\x00')
        with self.assertRaisesRegex(ValueError, 'truncated'):
            fb.unpack_file(self.root / 'broken.bin', fb.EVENT)
        fb.save_json(self.root / 'manifest.json', {'mode': 'standard', 'status': 'captured'})
        (self.root / 'samples.bin').write_bytes(fb.SAMPLE.pack(1, 0, 1, 1, 0, 5, 0, 0, 0))
        with self.assertRaisesRegex(ValueError, 'absent stack'):
            fb.analyze(self.root)

    def test_event_loss_is_visible(self):
        s = self.capture(stat={'event_dropped': 10})
        self.assertTrue(any('overflow' in q for q in s['quality']))
        self.assertTrue((self.root / 'report.md').exists())


class SocketStub:
    def __init__(self, chunks):
        self.chunks = iter(chunks)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def sendall(self, value):
        pass

    def settimeout(self, value):
        pass

    def recv(self, count):
        return next(self.chunks, b'')


class TransportTests(unittest.TestCase):
    def request(self, chunks, binary=True):
        with mock.patch.object(socket, 'create_connection', return_value=SocketStub(chunks)):
            return fb.Client('test').request('bench data events', binary=binary)

    def test_binary_nuls_and_chunked_header(self):
        self.assertEqual(self.request([b'O', b'K 3\n\x00', b'\n\xff']), b'\x00\n\xff')

    def test_empty_binary_is_valid(self):
        self.assertEqual(self.request([b'OK 0\n']), b'')

    def test_short_binary_and_error_are_rejected(self):
        for chunks in ([b'OK 5\nabc'], [b'ERR busy\n'], [b'OK 99999999\n']):
            with self.subTest(chunks=chunks), self.assertRaises(ValueError):
                self.request(chunks)

    def test_socket_failure_is_not_retried_by_client(self):
        with mock.patch.object(socket, 'create_connection', side_effect=TimeoutError('lost')) as connect:
            with self.assertRaises(TimeoutError):
                fb.Client('test').request('bench caps')
            self.assertEqual(connect.call_count, 1)


class ImageTests(unittest.TestCase):
    def test_repack_preserves_shim_and_updates_payload_and_id(self):
        spec = importlib.util.spec_from_file_location('fb_image', Path(fb.__file__).with_name('framebench-image.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        header = bytearray(4096)
        header[:8] = b'ANDROID!'
        struct.pack_into('<10I', header, 8, 4, 0x8000, 4, 0x1000000, 0, 0, 0x100, 4096, 0, 0)
        original = bytes(header) + b'SHIM' + bytes(4092) + b'OLD!' + bytes(4092)
        image = module.repack_v0(original, b'NEW-PAYLOAD')
        new_header, shim, payload, second, page = module.split_v0(image)
        self.assertEqual(shim, b'SHIM')
        self.assertEqual(payload, b'NEW-PAYLOAD')
        self.assertEqual(second, b'')
        self.assertNotEqual(new_header[576:608], header[576:608])
        with self.assertRaises(ValueError):
            module.split_v0(original[:-1])


class OwnershipTests(unittest.TestCase):
    def test_other_lock_is_never_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / 'phone.lock'
            lock.write_text('another agent')
            with self.assertRaises(FileExistsError):
                with fb.phone_lock(lock):
                    pass
            self.assertEqual(lock.read_text(), 'another agent')

    def test_replaced_lock_survives_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / 'phone.lock'
            with fb.phone_lock(lock):
                lock.write_text('new owner')
            self.assertEqual(lock.read_text(), 'new owner')

    def test_own_lock_released_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / 'phone.lock'
            with self.assertRaises(ValueError):
                with fb.phone_lock(lock):
                    raise ValueError('fail')
            self.assertFalse(lock.exists())

    def test_failed_preflight_writes_report_without_start_or_gestures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = argparse.Namespace(out=root / 'out', kernel=None, lib=[], manual=False,
                ui_ready=True, lock=root / 'lock', host=None, seconds=45, export_timeout=1)
            with mock.patch.object(fb, 'discover', side_effect=RuntimeError('unsupported')):
                self.assertEqual(fb.collect(args), 1)
            s = json.loads((args.out / 'summary.json').read_text())
            self.assertEqual(s['manifest']['status'], 'preflight-failed')
            self.assertIn('preflight', s['ranking'][0]['task'])
            self.assertFalse(args.lock.exists())

    def test_no_checkpoint_during_motion(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = mock.Mock()
            run = fb.Run(client, Path(tmp), 10)
            run.moving = True
            run.checkpoint()
            client.request.assert_not_called()

    def test_midrun_loss_keeps_memory_evidence_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = argparse.Namespace(out=root / 'out', kernel=None, lib=[], manual=False,
                ui_ready=True, lock=root / 'lock', host=None, seconds=45, export_timeout=1)
            calls = []
            def request(command, **kwargs):
                calls.append(command)
                if command == 'bench stop':
                    raise TimeoutError('device lost')
                if command == 'bench start 90':
                    return 'OK bench started'
                return 'bench-v1 active=0 busy=0'
            client = mock.Mock()
            client.host = 'test-only'
            client.request.side_effect = request
            def standard(run):
                fb.log(run.out, 'memory', snapshot=snapshot(free=16 << 20, wanted=2))
                raise TimeoutError('device lost')
            with mock.patch.object(fb, 'discover', return_value=(client, 'test caps')), \
                 mock.patch.object(fb.Run, 'standard', standard):
                self.assertEqual(fb.collect(args), 1)
            s = json.loads((args.out / 'summary.json').read_text())
            self.assertEqual(s['manifest']['status'], 'partial')
            self.assertEqual(s['memory']['snapshots'], 1)
            self.assertIn('20', s['ranking'][0]['task'])
            self.assertFalse(args.lock.exists())
            self.assertEqual(calls.count('bench start 90'), 1)
            self.assertEqual(calls.count('bench stop'), 1)
            self.assertFalse(any('reboot' in c or 'clk' in c for c in calls))

    def test_successful_capture_exports_each_blob_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = argparse.Namespace(out=root / 'out', kernel=None, lib=[], manual=False,
                ui_ready=True, lock=root / 'lock', host=None, seconds=45, export_timeout=1)
            calls = []
            def request(command, **kwargs):
                calls.append(command)
                if command == 'bench start 90':
                    return 'OK bench started'
                if command.startswith('bench data '):
                    return b'end\n' if command.endswith('meta') else b''
                return 'bench-v1 active=0 busy=0 events=0 samples=0 stacks=0'
            client = mock.Mock()
            client.host = 'test-only'
            client.request.side_effect = request
            with mock.patch.object(fb, 'discover', return_value=(client, 'test caps')), \
                 mock.patch.object(fb.Run, 'standard', return_value=None):
                self.assertEqual(fb.collect(args), 0)
            s = json.loads((args.out / 'summary.json').read_text())
            self.assertEqual(s['manifest']['status'], 'captured')
            for what in ('events', 'samples', 'stacks', 'meta'):
                self.assertEqual(calls.count('bench data ' + what), 1)
            self.assertFalse(args.lock.exists())


if __name__ == '__main__':
    unittest.main()
