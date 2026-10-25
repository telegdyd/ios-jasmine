#!/usr/bin/env python3
"""One bounded frame/CPU/memory capture. Never boots, flashes, changes clocks,
installs software, or retries a failed workload. Requires kernel patch j0099.

  framebench.py run --out research/framebench/current --ui-ready --kernel K --lib L
  framebench.py run --out research/framebench/settings --manual --seconds 45
  framebench.py report research/framebench/current [--kernel K --lib L]

Standard run assumes an unlocked, settled UI. Manual mode injects no input: start
it before entering the Settings page of interest. Output contains local device
diagnostics and must remain ignored. Offline reporting never contacts the phone.
"""
import argparse
import bisect
import collections
import contextlib
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import sys
import time
import uuid

EVENT = struct.Struct('<IHHQIIII')
SAMPLE = struct.Struct('<IIQQQHBBI')
STACK = struct.Struct('<QII48Q')
MAX_BLOB = 12 * 1024 * 1024
DEFAULT_LOCK = (r'C:\Users\teleg\AppData\Local\Claude-Data\claude_pzs8sxrjxfjjc'
                r'\side-session-notes\local_b57c5c9a-db18-434e-a448-e6d69fa0dddf\phone.lock')
PHASES = {1: 'idle-before', 2: 'spotlight-first-observed', 3: 'spotlight-repeat',
          4: 'warmup', 5: 'home-a', 6: 'control-a', 7: 'home-b', 8: 'control-b',
          9: 'idle-after', 10: 'manual-settings'}


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def log(out, kind, **data):
    row = dict(host_time=datetime.datetime.now().astimezone().isoformat(), kind=kind, **data)
    with (out / 'progress.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps(row) + '\n')
        f.flush()
    return row


@contextlib.contextmanager
def phone_lock(path):
    """Atomic ownership; never remove another invocation's lock, even on error."""
    owner = f'framebench {os.getpid()} {uuid.uuid4()}\n'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(owner)
        yield
    finally:
        try:
            if Path(path).read_text() == owner:
                Path(path).unlink()
        except FileNotFoundError:
            pass


class Client:
    def __init__(self, host, port=5141):
        self.host, self.port = host, port

    def request(self, command, timeout=3, binary=False):
        deadline = time.monotonic() + timeout
        with socket.create_connection((self.host, self.port), timeout=min(1, timeout)) as s:
            s.sendall(command.encode('ascii') + b'\n')
            data = bytearray()
            expected = None
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f'deadline reading {command}')
                s.settimeout(remaining)
                chunk = s.recv(65536)
                if not chunk:
                    break
                data.extend(chunk)
                if binary and expected is None and b'\n' in data:
                    header, _, rest = data.partition(b'\n')
                    if not re.fullmatch(rb'OK [0-9]+', header):
                        raise ValueError(f'{command}: {header.decode(errors="replace")}')
                    expected = int(header[3:])
                    if expected > MAX_BLOB:
                        raise ValueError('blob exceeds protocol memory budget')
                    data = bytearray(rest)
                limit = MAX_BLOB if binary else 256 * 1024
                if len(data) > limit:
                    raise ValueError('response exceeds protocol limit')
            if binary:
                if expected is None or len(data) != expected:
                    raise ValueError(f'short binary response for {command}: {len(data)} of {expected}')
                return bytes(data)
            answer = data.decode('utf-8', errors='replace').strip()
            if not answer or answer.startswith('ERR'):
                raise ValueError(f'{command}: {answer or "empty response"}')
            return answer


def discover(host=None):
    errors = []
    for address in ([host] if host else ['192.168.7.2', '169.254.7.2']):
        client = Client(address)
        try:
            caps = client.request('bench caps', timeout=2)
            sizes = kv(caps)
            if not caps.startswith('bench-v1 ') or any(sizes.get(k) != n for k, n in
                    [('events', EVENT.size), ('samples', SAMPLE.size), ('stacks', STACK.size)]):
                raise ValueError('j0099 framebench capability absent; no boot attempted')
            return client, caps
        except (OSError, ValueError) as exc:
            errors.append(f'{address}: {exc}')
    raise RuntimeError('; '.join(errors))


def kv(text):
    return {k: int(v) for k, v in re.findall(r'(\w+)=([0-9]+)', text)}


def parse_snapshot(text):
    result = {'processes': []}
    keys = ['us', 'physical_bytes', 'free_bytes', 'wired_bytes', 'active_bytes',
            'inactive_bytes', 'free_wanted', 'page_size', 'gpu_bo_count',
            'gpu_bo_mapped_bytes', 'surface_count', 'surface_requested_bytes',
            'gpu_pool_allocated_bytes', 'reserved_5', 'gpu_buffer_alloc_failures', 'gpu_frees_inflight']
    for line in text.splitlines():
        words = line.split()
        if words and words[0] == 'memory':
            if len(words) != len(keys) + 1:
                raise ValueError('incompatible memory snapshot')
            result.update(zip(keys, map(int, words[1:])))
        elif words and words[0] == 'process':
            if len(words) < 7:
                raise ValueError('truncated process snapshot')
            result['processes'].append(dict(pid=int(words[1]), uniqueid=int(words[2]),
                footprint_bytes=int(words[3]), resident_bytes=int(words[4]),
                compressed_bytes=int(words[5]), name=' '.join(words[6:])))
        elif words and words[0] == 'tasks':
            result['tasks_captured'], result['tasks_total'] = map(int, words[1:])
    if 'us' not in result:
        raise ValueError('memory snapshot not ready')
    return result


class Run:
    def __init__(self, client, out, duration):
        self.client, self.out = client, out
        self.deadline = time.monotonic() + duration
        self.next_snapshot = 0
        self.phase_id = 0
        self.moving = False

    def command(self, command):
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError('device activity deadline reached')
        reply = self.client.request(command, timeout=min(3, left))
        log(self.out, 'command', command=command, reply=reply)
        return reply

    def checkpoint(self):
        if self.moving or time.monotonic() < self.next_snapshot:
            return
        self.next_snapshot = time.monotonic() + 1
        try:
            text = self.client.request('bench snapshot', timeout=min(2, max(.1, self.deadline - time.monotonic())))
            snap = parse_snapshot(text)
        except ValueError as exc:
            log(self.out, 'snapshot-unavailable', error=str(exc))
            return
        log(self.out, 'memory', snapshot=snap)
        # Only emergency pressure aborts input. Low free alone can be normal when
        # reclaimable caches exist; do not impose an arbitrary cache budget.
        if snap['free_bytes'] < 32 * 1024 * 1024 and snap['free_wanted'] > 0:
            raise RuntimeError('memory pressure: free <32 MiB with page waiters; input stopped')

    def rest(self, seconds):
        until = min(time.monotonic() + seconds, self.deadline)
        while time.monotonic() < until:
            time.sleep(max(0, min(.2, until - time.monotonic())))
            self.checkpoint()
        if time.monotonic() >= self.deadline:
            raise TimeoutError('device activity deadline reached')

    def phase(self, number, sample_ms=0):
        self.phase_id = number
        print(f'framebench: {PHASES[number]}', flush=True)
        self.command(f'bench phase {number} {sample_ms}')

    def gesture(self, command, tail=.15):
        self.checkpoint()
        self.command('bench mark 1')
        self.moving = True
        self.command(command)
        self.rest(tail)
        self.command('bench mark 0')
        self.moving = False

    def home(self):
        for _ in range(10):
            self.gesture('swipe 900 1200 150 1200 250')
            self.gesture('swipe 150 1200 900 1200 250')

    def control(self):
        for _ in range(7):
            self.gesture('swipe 1000 4 1000 1100 300', .4)
            self.gesture('key 3 1; key 3 0', .3)
            self.rest(.1)

    def standard(self):
        self.command('key 3 1; key 3 0')
        self.phase(1)
        self.rest(3)
        for n in (2, 3):
            self.phase(n, 2000 if n == 2 else 0)
            self.gesture('swipe 540 900 540 1500 250', .7)
            self.rest(1)
            self.gesture('key 3 1; key 3 0', .5)
        self.phase(4)
        self.gesture('swipe 900 1200 150 1200 250', .3)
        self.gesture('swipe 150 1200 900 1200 250', .3)
        self.gesture('swipe 1000 4 1000 1100 300', .6)
        self.gesture('key 3 1; key 3 0', .5)
        self.rest(2)
        for n in (5, 6, 7, 8):
            self.phase(n, 4000 if n in (5, 6) else 0)
            self.home() if n in (5, 7) else self.control()
            self.command('key 3 1; key 3 0')
            self.rest(.4)
        self.phase(9)
        self.rest(5)

    def manual(self, seconds):
        self.phase(10, 1000)
        self.command('bench census-all')
        print('framebench: manual capture active; open the Settings page now', flush=True)
        end = time.monotonic() + seconds
        for _ in range(math.ceil(seconds)):
            if time.monotonic() >= end:
                break
            self.rest(min(1, end - time.monotonic()))
            # Short periodic windows keep a late freeze observable without
            # continuously sampling or exhausting the compact sample budget.
            if int(end - time.monotonic()) % 10 == 0:
                self.command('bench phase 10 1000')


def identify(path):
    p = Path(path).resolve()
    h = hashlib.sha256()
    with p.open('rb') as f:
        for data in iter(lambda: f.read(1024 * 1024), b''):
            h.update(data)
    return {'path': str(p), 'sha256': h.hexdigest(), 'bytes': p.stat().st_size}


def collect(a):
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    manifest = dict(protocol=1, started=datetime.datetime.now().astimezone().isoformat(),
        mode='manual' if a.manual else 'standard', ui_state='ready (operator supplied)' if a.ui_ready else 'unknown',
        kernel=identify(a.kernel) if a.kernel else None, libs=[identify(p) for p in a.lib],
        symbol_identity='local files supplied; installed library identity not independently verified',
        status='preflight', display_validation='unvalidated hardware observation proxy')
    save_json(out / 'manifest.json', manifest)
    started = False
    t0 = time.monotonic()
    error = None
    client = None
    try:
        with phone_lock(a.lock):
            try:
                client, caps = discover(a.host)
                manifest.update(host=client.host, caps=caps)
                for query in ('prof stat', 'bench stat', 'gpu state', 'ddr state', 'tsens', 'state'):
                    reply = client.request(query)
                    manifest[query] = reply
                    if query == 'prof stat' and 'running' in reply:
                        raise RuntimeError('another profiler is active')
                    if query == 'bench stat' and (kv(reply).get('active') or kv(reply).get('busy')):
                        raise RuntimeError('another framebench capture is active')
                if not a.manual and not a.ui_ready:
                    raise ValueError('standard mode requires --ui-ready: unlocked and settled UI')
                manifest['status'] = 'capturing'
                save_json(out / 'manifest.json', manifest)
                duration = min(90, a.seconds + 5) if a.manual else 90
                reply = client.request(f'bench start {duration}')
                if reply != 'OK bench started':
                    raise RuntimeError(reply)
                started = True
                run = Run(client, out, duration - 2)
                run.manual(a.seconds) if a.manual else run.standard()
                manifest['status'] = 'captured'
            except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
                error = str(exc) or 'interrupted by operator'
                manifest['status'] = 'partial' if started else 'preflight-failed'
                manifest['error'] = error
                log(out, 'failure', error=error)
            finally:
                manifest['activity_seconds'] = round(time.monotonic() - t0, 3)
                if started:
                    try:
                        client.request('bench stop', timeout=2)
                        stop_deadline = time.monotonic() + 6
                        for _ in range(25):
                            status = client.request('bench stat', timeout=1)
                            manifest['capture_stat'] = kv(status)
                            if not manifest['capture_stat'].get('busy'):
                                break
                            if time.monotonic() >= stop_deadline:
                                raise TimeoutError('capture worker did not stop by deadline')
                            time.sleep(.1)
                        else:
                            raise TimeoutError('capture worker busy')
                        export_end = time.monotonic() + a.export_timeout
                        total = 0
                        for what in ('events', 'samples', 'stacks', 'meta'):
                            left = export_end - time.monotonic()
                            if left <= 0:
                                raise TimeoutError('export deadline reached')
                            data = client.request(f'bench data {what}', timeout=left, binary=True)
                            total += len(data)
                            if total > MAX_BLOB:
                                raise ValueError('combined export exceeds memory budget')
                            (out / ('profile.meta' if what == 'meta' else what + '.bin')).write_bytes(data)
                        manifest['export_bytes'] = total
                        for query in ('gpu state', 'ddr state', 'tsens'):
                            manifest['final ' + query] = client.request(query, timeout=2)
                    except (OSError, ValueError, RuntimeError) as exc:
                        manifest['export_error'] = str(exc)
                        manifest['status'] = 'partial'
                        error = error or str(exc)
    except (OSError, ValueError, RuntimeError) as exc:
        error = str(exc)
        manifest.update(status='preflight-failed', error=error)
    manifest['total_collect_seconds'] = round(time.monotonic() - t0, 3)
    save_json(out / 'manifest.json', manifest)
    analyze(out, a.kernel, a.lib)
    if error:
        print(f'framebench stopped: {error}; partial report: {out / "report.md"}', file=sys.stderr)
        return 1
    print(f'framebench complete: {out / "report.md"}', flush=True)
    return 0


def unpack_file(path, layout):
    if not path.exists():
        return []
    data = path.read_bytes()
    if len(data) % layout.size:
        raise ValueError(f'truncated {path.name}')
    return list(layout.iter_unpack(data))


def percentile(values, q):
    if not values:
        return None
    xs = sorted(values)
    return xs[max(0, math.ceil(q * len(xs)) - 1)]


def intervals(events, end_us):
    """Predefined motion windows, including censored boundaries and final stalls."""
    opened = {}
    windows = collections.defaultdict(list)
    for e in events:
        us, kind, phase = e[:3]
        if kind == 4:
            if e[4]:
                if phase in opened:
                    raise ValueError('nested motion marker')
                opened[phase] = us
            elif phase in opened:
                windows[phase].append((opened.pop(phase), us))
        elif kind == 2:
            for p, start in list(opened.items()):
                windows[p].append((start, us))
                del opened[p]
    for phase, start in opened.items():
        windows[phase].append((start, end_us))
    return windows


def window_stats(times, windows):
    times = sorted(set(times))
    gaps, censored = [], []
    count = 0
    for start, end in windows:
        selected = times[bisect.bisect_left(times, start):bisect.bisect_right(times, end)]
        count += len(selected)
        gaps.extend((b - a) / 1000 for a, b in zip(selected, selected[1:]))
        censored.extend([(selected[0] - start) / 1000, (end - selected[-1]) / 1000] if selected else [(end - start) / 1000])
    active = sum(max(0, b - a) for a, b in windows) / 1e6
    return dict(updates=count, active_seconds=active, updates_per_second=count / active if active else None,
        interval_samples=len(gaps), median_ms=percentile(gaps, .5), p95_ms=percentile(gaps, .95),
        p99_descriptive_ms=percentile(gaps, .99), max_interval_ms=max(gaps, default=None),
        max_no_update_including_boundaries_ms=max(gaps + censored, default=None),
        stalls_over_100ms=sum(g > 100 for g in gaps + censored),
        boundary_lower_bounds_ms=censored)


def cpu_report(samples, stacks, out, kernel=None, libs=()):
    if kernel and os.name == 'nt':
        def linux_path(path):
            p = str(Path(path).resolve()).replace('\\', '/')
            if len(p) > 2 and p[1] == ':':
                return '/mnt/' + p[0].lower() + p[2:]
            raise ValueError('WSL attribution needs drive-local files')
        try:
            command = ['wsl.exe', '--exec', 'timeout', '40s', 'python3', linux_path(__file__),
                       '_cpu', linux_path(out), '--kernel', linux_path(kernel)]
            for lib in libs:
                command += ['--lib', linux_path(lib)]
            proc = subprocess.run(command, capture_output=True, text=True, timeout=45)
            if proc.returncode == 0:
                return json.loads(proc.stdout)
            reason = (proc.stderr or proc.stdout)[-1500:]
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            reason = str(exc)
        answer = cpu_report(samples, stacks, out, None, ())
        answer['limitation'] = 'WSL symbolication unavailable: ' + reason
        return answer
    import prof
    meta_path = out / 'profile.meta'
    if not samples or not meta_path.exists():
        return {'available': False, 'reason': 'no samples/metadata'}
    meta = prof.Meta(str(meta_path))
    symbolizer = None
    reason = 'supply matching --kernel and --lib for symbolized attribution'
    if kernel:
        try:
            symbolizer = prof.Sym(meta, str(kernel), list(map(str, libs)))
        except (OSError, ValueError, struct.error) as exc:
            reason = str(exc)
    stack_names = {}
    if symbolizer:
        # Resolve a stack separately for each PID: shared-cache slides/maps differ.
        for sample in samples:
            sid, pid = sample[1], sample[3] & 0xffffffff
            key = (sid, pid)
            if key not in stack_names:
                s = stacks[sid]
                nk, nu = s[1:3]
                frames = list(s[3:3 + nk + nu])
                stack_names[key] = [symbolizer.kernel(x) for x in frames[:nk]] + [
                    symbolizer.user(pid, x if i == 0 else x - 1) for i, x in enumerate(frames[nk:])]
        symbolizer.finish()
    phases = {}
    for phase in sorted({s[5] for s in samples}):
        process, thread, state, leaf, categories = [collections.Counter() for _ in range(5)]
        mine = [s for s in samples if s[5] == phase]
        duration_us = max((s[0] for s in mine), default=0) - min((s[0] for s in mine), default=0)
        duration = duration_us / 1e6
        for us, sid, tid, pt, ev, p, kind, cpu, pad in mine:
            pid = pt & 0xffffffff
            name = meta.tasks.get(pid, f'pid-{pid}')
            weight = meta.vals.get('period_us', 2000) / 1000 if kind < 2 else meta.vals.get('census_us', 5000) / 1000
            pairs = stack_names.get((sid, pid), [])
            names = [symbolizer.name(n) for image, n in pairs] if symbolizer else []
            images = [image for image, n in pairs]
            trace = ' '.join(names)
            thread_name = meta.threads.get(tid, (0, ''))[1]
            state[f'{name}:{thread_name}:{prof.KIND.get(kind, "unknown")}'] += weight
            if kind < 2:
                process[name] += weight
                thread[f'{name}:{thread_name}:{tid}'] += weight
                if names:
                    leaf[f'{images[0]}:{names[0]}'] += weight
                if name == 'backboardd' and 'coreanimation.display' in thread_name:
                    if 'libsweetca.dylib' in images:
                        categories['render-Mesa-CPU'] += weight
                    elif 'QuartzCore' in images:
                        categories['render-CA-CPU'] += weight
                    else:
                        categories['render-other-CPU'] += weight
                elif name == 'SpringBoard':
                    categories['SpringBoard-CPU'] += weight
            elif name == 'backboardd' and 'coreanimation.display' in thread_name:
                if kind == 3:
                    categories['render-runnable'] += weight
                elif 'sweet_fb_gpu_write_wait' in trace or 'AppleCLCD' in trace:
                    categories['render-panel-surface-wait'] += weight
                elif 'ir3_get_shader' in trace or 'util_queue_fence_wait' in trace:
                    categories['render-shader-worker-wait'] += weight
                elif 'darwin_pipe_wait' in trace or 'sweet_gpu_wait' in trace:
                    categories['render-GPU-fence-wait'] += weight
                elif 'SweetGPUBuffer::free' in trace or 'sweet_gpu_vm_unmap' in trace:
                    categories['render-buffer-free-wait'] += weight
                else:
                    categories['render-other-wait'] += weight
        phases[PHASES.get(phase, str(phase))] = dict(sample_span_seconds=duration,
            process_cpu_estimated_ms=dict(process.most_common(20)), thread_cpu_estimated_ms=dict(thread.most_common(20)),
            thread_state_estimated_ms=dict(state.most_common(50)), self_cpu_estimated_ms=dict(leaf.most_common(25)),
            categories_estimated_ms=dict(categories))
    return dict(available=True, symbolized=bool(symbolizer), limitation=None if symbolizer else reason, phases=phases)


def memory_report(progress):
    snaps = [p['snapshot'] for p in progress if p['kind'] == 'memory']
    if not snaps:
        return {'available': False}
    first, last = snaps[0], snaps[-1]
    by_id = {}
    for snap in snaps:
        for p in snap['processes']:
            key = (p['pid'], p['uniqueid'])
            row = by_id.setdefault(key, {'name': p['name'], 'pid': p['pid'], 'uniqueid': p['uniqueid'],
                'first_bytes': p['footprint_bytes'], 'peak_bytes': 0, 'last_bytes': 0,
                'first_us': snap['us'], 'last_us': snap['us']})
            row['peak_bytes'] = max(row['peak_bytes'], p['footprint_bytes'])
            row.update(last_bytes=p['footprint_bytes'], last_us=snap['us'])
    for row in by_id.values():
        row['observed_growth_bytes'] = row['last_bytes'] - row['first_bytes']
        row['present_at_end'] = any(p['pid'] == row['pid'] and p['uniqueid'] == row['uniqueid'] for p in last['processes'])
    incarnations = collections.Counter(row['name'] for row in by_id.values())
    return dict(available=True, snapshots=len(snaps), first=first, last=last,
        observed_process_incarnations=dict(incarnations),
        min_free_bytes=min(s['free_bytes'] for s in snaps), max_wired_bytes=max(s['wired_bytes'] for s in snaps),
        page_waiter_snapshots=sum(s['free_wanted'] > 0 for s in snaps),
        max_gpu_bo_mapped_bytes=max(s['gpu_bo_mapped_bytes'] for s in snaps),
        max_surface_requested_bytes=max(s['surface_requested_bytes'] for s in snaps),
        gpu_alloc_failures_delta=last['gpu_buffer_alloc_failures'] - first['gpu_buffer_alloc_failures'],
        process_high_water=sorted(by_id.values(), key=lambda r: r['peak_bytes'], reverse=True)[:25],
        process_growth=sorted(by_id.values(), key=lambda r: r['observed_growth_bytes'], reverse=True)[:25],
        limitation='Footprints overlap mapped GPU/surface memory; do not sum these counters. Short growth does not prove a leak. Exited processes are not treated as retained.')


def rank(summary):
    candidates = []
    memory = summary['memory']
    if memory.get('available'):
        growth = max((p['observed_growth_bytes'] for p in memory['process_growth']), default=0)
        pressure = memory['page_waiter_snapshots'] > 0 and memory['min_free_bytes'] < 64 * 1024 * 1024
        if pressure or memory['gpu_alloc_failures_delta'] > 0:
            candidates.append(dict(task='20 / memory-pressure bug investigation', confidence='high for pressure/allocation failure, cause unproven',
                evidence=f"min free {memory['min_free_bytes']/2**20:.1f} MiB, {memory['page_waiter_snapshots']} waiter snapshots, {memory['gpu_alloc_failures_delta']} GPU buffer allocation failures",
                next='Attribute the largest live footprints/backing allocations and inspect pressure/crash logs before optimizing draw cost.', score=100))
        elif growth > 128 * 1024 * 1024:
            candidates.append(dict(task='20', confidence='medium; growth alone does not prove pressure or leak', evidence=f'process footprint grew {growth/2**20:.1f} MiB within capture', next='Check the named growing process and post-idle recovery.', score=60))
    cats = collections.Counter()
    for phase in summary['cpu'].get('phases', {}).values():
        cats.update(phase['categories_estimated_ms'])
    rules = [('render-buffer-free-wait', '14', 'Identify the blocked free/unmap operation with the captured stacks.'),
             ('render-Mesa-CPU', '5', 'Split the hottest validation/emission/batch path and test one focused optimization.'),
             ('render-runnable', '6 investigation', 'Check CPU placement and scheduler contention; no 4/8-core conclusion from this boot.'),
             ('render-shader-worker-wait', '17 feasibility', 'Confirm compilation rather than state emission; compare first-observed and repeat.'),
             ('render-panel-surface-wait', '16 investigation', 'Inspect linked surface/fence/display events before changing synchronization.'),
             ('render-GPU-fence-wait', '16 investigation', 'Separate GPU work, queue delay and display protection; quantify available overlap.')]
    total = sum(cats[k] for k, _, _ in rules)
    for key, task, followup in rules:
        if cats[key] >= 10:
            candidates.append(dict(task=task, confidence='medium; sample-weighted opportunity, not removable frame time',
                evidence=f'{cats[key]:.1f} estimated ms in {key}', next=followup, score=50*cats[key]/max(total, 1)))
    if cats['SpringBoard-CPU'] > 100:
        candidates.append(dict(task='19', confidence='lead; producer critical-path causality not established',
            evidence=f"{cats['SpringBoard-CPU']:.1f} estimated ms in SpringBoard", next='Correlate transaction production with slow render intervals.', score=15))
    if not candidates:
        candidates.append(dict(task='18 / resolve missing attribution', confidence='insufficient evidence',
            evidence='No usable pressure or symbolized critical-thread attribution; do not reuse the old task-5 ranking.',
            next='Inspect capture validity and provide matching symbols, or use bounded manual capture on the failing Settings page.', score=0))
    if summary['manifest'].get('status') == 'preflight-failed':
        return [dict(task='Fix capture preflight', confidence='no device workload measured', evidence=summary['manifest'].get('error'), next='Resolve the stated capability/ownership error; do not boot/retry automatically.', score=0)]
    if summary['manifest'].get('capture_stat', {}).get('sample_dropped'):
        for candidate in candidates:
            if candidate['task'] not in ('20', '20 / memory-pressure bug investigation'):
                candidate['confidence'] += '; provisional because CPU records were dropped'
    return sorted(candidates, key=lambda r: r['score'], reverse=True)


def analyze(out, kernel=None, libs=()):
    manifest = json.loads((out / 'manifest.json').read_text())
    progress = []
    for line in (out / 'progress.jsonl').read_text().splitlines() if (out / 'progress.jsonl').exists() else []:
        progress.append(json.loads(line))
    events = sorted(unpack_file(out / 'events.bin', EVENT), key=lambda e: e[0])
    samples = unpack_file(out / 'samples.bin', SAMPLE)
    stacks = unpack_file(out / 'stacks.bin', STACK)
    for s in stacks:
        if s[1] > 16 or s[2] > 32:
            raise ValueError('invalid stack frame count')
    if any(s[1] >= len(stacks) for s in samples):
        raise ValueError('sample references an absent stack')
    ending = next((e[0] for e in reversed(events) if e[1] == 3), None)
    end_us = ending if ending is not None else max([e[0] for e in events] + [p['snapshot']['us'] for p in progress if p['kind'] == 'memory'] + [0])
    windows = intervals(events, end_us)
    if manifest['mode'] == 'manual':
        starts = [e[0] for e in events if e[1] == 2 and e[2] == 10]
        if starts:
            windows[10] = [(starts[0], end_us)]
    phases = {}
    refresh = [(e[0], e[4]) for e in events if e[1] == 17]
    periods = []
    for (ta, ca), (tb, cb) in zip(refresh, refresh[1:]):
        delta = (cb - ca) & 0xffffffff
        if 0 < delta < 100 and tb > ta:
            periods.append((tb-ta)/delta/1000)
    refresh_ms = percentile(periods, .5)
    for phase, name in PHASES.items():
        selected = [e for e in events if e[2] == phase]
        arriving = [e[0] for e in selected if e[1] == 11]
        # Unique swap identities; timeout/immediate-copy paths are separate.
        observed = {e[4]: e[0] for e in selected if e[1] == 14}
        phases[name] = dict(motion=window_stats(arriving, windows.get(phase, [])),
            ctl_clear_observation_proxy=window_stats(list(observed.values()), windows.get(phase, [])),
            latch_timeout_fallbacks=sum(e[1] == 15 for e in selected),
            immediate_or_copy_retirements=sum(e[1] == 16 for e in selected),
            panel_surface_wait_us=sum(e[5] for e in selected if e[1] in (18, 19)),
            displayed_fps=None)
    submit, associations, jobs, waits = {}, collections.defaultdict(list), [], {}
    for e in events:
        us, kind, phase, tid, a, b, c, d = e
        if kind == 20:
            submit[a] = (us, phase)
        elif kind == 22:
            associations[a].append(b)
        elif kind == 21:
            for seq in list(submit):
                if ((a-seq) & 0xffffffff) < 0x80000000:
                    start, p = submit.pop(seq)
                    jobs.append(dict(sequence=seq, phase=PHASES.get(p, str(p)), submit_us=start,
                        completion_observed_us=us, latency_upper_bound_us=us-start,
                        surfaces=associations[seq]))
        elif kind == 23:
            waits[tid] = (us, a)
        elif kind == 24:
            waits.pop(tid, None)
    stats = manifest.get('capture_stat', {})
    quality = []
    if stats.get('event_dropped'):
        quality.append('event buffer overflow: timeline/percentiles incomplete')
    if stats.get('sample_dropped'):
        quality.append('compact sample/dictionary contention or capacity loss: CPU shares approximate')
    if not events:
        quality.append('frame trace unavailable; memory checkpoints may still contain freeze evidence')
    if not (out / 'profile.meta').exists() or not (out / 'profile.meta').read_text(errors='replace').rstrip().endswith('end'):
        quality.append('profile metadata incomplete or unavailable')
    quality.append('Displayed FPS unavailable until CTL-clear observation is validated against actual scanout; timer ticks are not refresh proof.')
    summary = dict(manifest=manifest, quality=quality, phases=phases, memory=memory_report(progress),
        hardware_frame_counter_period_ms=refresh_ms, hardware_counter_samples=len(periods),
        cpu=cpu_report(samples, stacks, out, kernel, libs),
        gpu=dict(matched_jobs=jobs, unmatched_submissions=len(submit), incomplete_waits=list(waits.items()),
            limitation='Detailed jobs are captured only in CPU-sampled windows. Fence observation latency includes queueing/execution/observation delay; not GPU execution time.'),
        tail_note='p99 is descriptive for this short sample; boundary stalls are lower bounds and included separately.')
    summary['ranking'] = rank(summary)
    summary['slow_intervals'] = slow_intervals(events, samples, windows)
    save_json(out / 'summary.json', summary)
    write_report(out, summary)
    return summary


def slow_intervals(events, samples, windows):
    rows = []
    for phase, spans in windows.items():
        times = [e[0] for e in events if e[1] == 11 and e[2] == phase]
        for start, end in spans:
            pts = [start] + [t for t in times if start <= t <= end] + [end]
            for a, b in zip(pts, pts[1:]):
                rows.append(dict(phase=PHASES.get(phase, str(phase)), start_us=a, end_us=b,
                    no_swap_ms=(b-a)/1000, censored=(a == start or b == end),
                    sample_states=dict(collections.Counter(str(s[6]) for s in samples if a <= s[0] < b)),
                    top_sample_stacks=[dict(stack=k[0], tid=k[1], pid=k[2], kind=k[3], count=count)
                        for k, count in collections.Counter((s[1], s[2], s[3] & 0xffffffff, s[6])
                            for s in samples if a <= s[0] < b).most_common(8)]))
    return sorted(rows, key=lambda r: r['no_swap_ms'], reverse=True)[:20]


def write_report(out, s):
    lines = ['# Framebench report', '', f"Status: **{s['manifest']['status']}**. One capture; no automatic boot/retry.", '',
             '## Recommended next work', '']
    for row in s['ranking'][:3]:
        lines.extend([f"- **Task {row['task']}** — {row['evidence']}",
                      f"  Confidence: {row['confidence']}. Next: {row['next']}"])
    lines.extend(['', '## Frame update observations', '',
        'These are swap arrivals and unvalidated CTL-clear observations, not confirmed displayed FPS.', '',
        '| Phase | Motion s | Swap arrivals/s | Median / p95 ms | Worst no-update incl. boundaries ms | CTL observations/s | Latch timeout fallbacks |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |'])
    def fmt(x):
        return f'{x:.2f}' if x is not None else 'unavailable'
    for name, phase in s['phases'].items():
        m, p = phase['motion'], phase['ctl_clear_observation_proxy']
        if m['active_seconds']:
            lines.append(f"| {name} | {m['active_seconds']:.2f} | {fmt(m['updates_per_second'])} | {fmt(m['median_ms'])} / {fmt(m['p95_ms'])} | {fmt(m['max_no_update_including_boundaries_ms'])} | {fmt(p['updates_per_second'])} | {phase['latch_timeout_fallbacks']} |")
    lines.extend(['', '## Memory', ''])
    mem = s['memory']
    if mem.get('available'):
        lines.extend([f"{mem['snapshots']} saved snapshots; minimum free {mem['min_free_bytes']/2**20:.1f} MiB, maximum wired {mem['max_wired_bytes']/2**20:.1f} MiB, {mem['page_waiter_snapshots']} snapshots with page waiters.", '',
            '| Process | Peak footprint MiB | Observed growth MiB | Present at end |', '| --- | ---: | ---: | --- |'])
        for p in mem['process_high_water'][:12]:
            lines.append(f"| {p['name']} ({p['pid']}) | {p['peak_bytes']/2**20:.1f} | {p['observed_growth_bytes']/2**20:.1f} | {p['present_at_end']} |")
        lines.extend(['', mem['limitation']])
    else:
        lines.append('No memory snapshot available.')
    lines.extend(['', '## CPU attribution', ''])
    if s['cpu'].get('symbolized'):
        for name, phase in s['cpu']['phases'].items():
            lines.append(f"- {name}: " + ', '.join(f'{k} {v:.1f} estimated ms' for k, v in phase['categories_estimated_ms'].items()))
            for fn, ms in list(phase['self_cpu_estimated_ms'].items())[:5]:
                lines.append(f'  - {ms:.1f} estimated ms: `{fn}`')
    else:
        lines.append(s['cpu'].get('limitation') or s['cpu'].get('reason', 'Unavailable'))
    lines.extend(['', '## Validity and limits', ''])
    lines.extend('- ' + q for q in s['quality'])
    lines.extend(['- ' + s['tail_note'], '- ' + s['gpu']['limitation'],
        '- Current plugin-enabled software is a fresh baseline; old task-5 results do not establish this run\'s bottleneck.',
        '- Physical refresh counter estimates and CTL observation resolution require on-phone validation.',
        '- A/B segments estimate gross sampling perturbation; they are not a calibrated overhead bound.',
        '- No boot, core-count, persistent-cache, long-soak or physical touch-to-photon conclusion is supported.', '',
        'Exact configuration, counters, CPU stacks, GPU links and slow-interval details are in summary.json and the saved capture.', ''])
    (out / 'report.md').write_text('\n'.join(lines), encoding='utf-8')


def parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='action', required=True)
    run = sub.add_parser('run')
    run.add_argument('--out', type=Path, required=True)
    run.add_argument('--host')
    run.add_argument('--lock', default=os.environ.get('PHONE_LOCK', DEFAULT_LOCK))
    run.add_argument('--ui-ready', action='store_true')
    run.add_argument('--manual', action='store_true')
    run.add_argument('--seconds', type=int, default=45)
    run.add_argument('--export-timeout', type=float, default=45)
    report = sub.add_parser('report')
    report.add_argument('out', type=Path)
    cpu = sub.add_parser('_cpu', help=argparse.SUPPRESS)
    cpu.add_argument('out', type=Path)
    for command in (run, report, cpu):
        command.add_argument('--kernel', type=Path)
        command.add_argument('--lib', type=Path, action='append', default=[])
    return p


def main():
    a = parser().parse_args()
    if a.action == 'run':
        if not 1 <= a.seconds <= 80 or not 1 <= a.export_timeout <= 120:
            raise SystemExit('seconds must be 1..80; export timeout 1..120')
        return collect(a)
    if a.action == '_cpu':
        print(json.dumps(cpu_report(unpack_file(a.out / 'samples.bin', SAMPLE),
            unpack_file(a.out / 'stacks.bin', STACK), a.out, a.kernel, a.lib)))
        return 0
    analyze(a.out.resolve(), a.kernel, a.lib)
    print(a.out / 'report.md')
    return 0


if __name__ == '__main__':
    sys.exit(main())
