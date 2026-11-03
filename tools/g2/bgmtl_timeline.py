#!/usr/bin/env python3
"""Parse the M8 libbgmtl timeline ring and print per-CB intervals.

The file is written by mesa/metal/src/bg_timeline.h:
  header 48 bytes: magic 'BGTL', version 1, pid, count, dropped,
                   start/end mach ticks, timebase numer/denom
  records 32 bytes: <uint64 ticks, uint32 kind, uint32 cb, uint64 a, uint64 b>

This module is intentionally free of device/symbol dependencies so the pure
parser and interval math can be unit-tested.  frametl.py calls report().
"""
import collections
import json
import math
import re
import struct
import sys
from pathlib import Path

CAP = 8192
HDR = struct.Struct('<IHHIIIIQQII')   # 48 bytes, matches struct bg_tl_hdr
REC = struct.Struct('<QIIQQ')         # 32 bytes, matches struct bg_tl_rec
MAGIC = b'BGTL'

KIND = {
    1: 'CREATE', 2: 'COMMIT_ENTER', 3: 'REPLAY_BEGIN', 4: 'TICKET_BEGIN',
    5: 'SUBMIT_BEGIN', 6: 'SUBMIT_END', 7: 'REPLAY_END', 8: 'SCHEDULED_RUN',
    9: 'FENCE_OBSERVED', 10: 'COMPLETED_RUN', 11: 'PRESENT_POST', 12: 'PRESENT_ENTER',
}
QUEUE = {0: 'replay', 1: 'completion', 2: 'inline'}

# name, label, positive-only (fence->scheduled is normally negative)
INTERVALS = [
    ('create_to_commit', 'create -> commit (encode)', True),
    ('commit_to_replay', 'commit -> replay_begin (handoff)', True),
    ('replay_to_submit_begin', 'replay_begin -> submit_begin', True),
    ('submit_begin_to_end', 'submit_begin -> submit_end (flush+drain+ioctl)', True),
    ('submit_end_to_fence', 'submit_end -> fence_observed (GPU wait)', True),
    ('submit_end_to_scheduled', 'submit_end -> scheduled (scheduled callback)', True),
    ('fence_to_scheduled', 'fence -> scheduled (only if not earlier)', True),
    ('fence_to_completed', 'fence -> completed (callback)', True),
    ('present_enter_to_post', 'present_enter -> present_post', True),
]


def load(path):
    """Read and validate one .bin; returns {header..., 'records': [...], 'error': None}."""
    data = Path(path).read_bytes()
    if len(data) < HDR.size:
        raise ValueError(f'{path}: short timeline header')
    magic, version, hdr_size, pid, count, dropped, _pad, start, end, numer, denom = HDR.unpack_from(data, 0)
    if data[:4] != MAGIC:
        raise ValueError(f'{path}: bad magic {data[:4]!r}')
    if version != 1:
        raise ValueError(f'{path}: unsupported version {version}')
    if hdr_size != HDR.size:
        raise ValueError(f'{path}: header size {hdr_size}, expected {HDR.size}')
    if count > CAP:
        raise ValueError(f'{path}: count {count} exceeds ring capacity')
    if len(data) < HDR.size + count * REC.size:
        raise ValueError(f'{path}: truncated records ({len(data)} bytes, need {HDR.size + count * REC.size})')
    records = []
    for i in range(count):
        t, kind, cb, a, b = REC.unpack_from(data, HDR.size + i * REC.size)
        records.append(dict(t=t, kind=kind, cb=cb, a=a, b=b, name=KIND.get(kind, f'KIND{kind}')))
    return dict(pid=pid, count=count, dropped=dropped, start=start, end=end,
                numer=numer, denom=denom, records=records)


def to_us(t, epoch, numer, denom):
    if not numer or not denom:
        raise ValueError('timebase numer/denom must be non-zero')
    return ((t - epoch) * numer) / denom / 1000.0


def manifest_epoch(out):
    """The raw mach-tick epoch framebench stores for a capture, or None."""
    p = Path(out) / 'manifest.json'
    if not p.exists():
        return None
    manifest = json.loads(p.read_text(encoding='utf-8'))
    # capture_epoch/capture_stat are taken after bench start and are the only
    # guaranteed-current epochs; bench_epoch is the pre-start value and may be
    # stale from an earlier capture.
    for key in ('capture_epoch', 'capture_stat', 'bench_epoch', 'bench_stat'):
        value = manifest.get(key)
        if isinstance(value, int) and value:
            return value
        if isinstance(value, dict) and value.get('epoch'):
            return int(value['epoch'])
    for key in ('bench stat', 'capture_stat'):
        raw = manifest.get(key)
        if isinstance(raw, str):
            m = re.search(r'epoch=(\d+)', raw)
            if m:
                return int(m.group(1))
    return None


def _first(events):
    first = {}
    for e in events:
        first.setdefault(e['kind'], e)
    return first


def _positive(a, b):
    return (b - a) / 1000.0 if a is not None and b is not None and b >= a else None


def build(capture, epoch=None):
    """Group records by CB and compute signed/optional intervals in ms."""
    epoch = capture['start'] if epoch is None else epoch
    numer, denom = capture['numer'], capture['denom']
    for rec in capture['records']:
        rec['us'] = to_us(rec['t'], epoch, numer, denom)
    grouped = collections.defaultdict(list)
    for rec in capture['records']:
        grouped[rec['cb']].append(rec)
    rows = []
    for cb, evs in sorted(grouped.items()):
        evs.sort(key=lambda e: e['us'])
        first = _first(evs)
        f = lambda k: first[k]['us'] if k in first else None
        create, commit, replay = f(1), f(2), f(3)
        sub_b, sub_e, rep_e = f(5), f(6), f(7)
        sched, fence, completed = f(8), f(9), f(10)
        pres_b, pres_e = f(12), f(11)
        ticket = first.get(4)
        tickets = [e for e in evs if e['kind'] == 4]
        generations = [e['a'] for e in tickets if e['a']]
        row = dict(cb=cb, create=create, commit=commit, replay=replay,
                   submit_begin=sub_b, submit_end=sub_e, replay_end=rep_e,
                   scheduled=sched, fence=fence, completed=completed,
                   present_enter=pres_b, present_post=pres_e,
                   generation=ticket['a'] if ticket else None,
                   generations=generations,
                   ticket_deferred=bool(ticket and (ticket['b'] >> 63)),
                   ticket_epoch=(ticket['b'] & ~(1 << 63)) if ticket else None,
                   seqno=first[6]['a'] if 6 in first else None,
                   submit_failed=bool(first[6]['b']) if 6 in first else False,
                   completed_status=first[10]['a'] if 10 in first else None,
                   scheduled_queue=QUEUE.get(first[8]['a'], str(first[8]['a'])) if 8 in first else None,
                   completed_queue=QUEUE.get(first[10]['b'], str(first[10]['b'])) if 10 in first else None)
        row['create_to_commit'] = _positive(create, commit)
        row['commit_to_replay'] = _positive(commit, replay)
        row['replay_to_submit_begin'] = _positive(replay, sub_b)
        row['submit_begin_to_end'] = _positive(sub_b, sub_e)
        row['submit_end_to_fence'] = _positive(sub_e, fence)
        row['submit_end_to_scheduled'] = _positive(sub_e, sched)
        row['fence_to_scheduled'] = _positive(fence, sched)
        row['scheduled_before_fence'] = fence is not None and sched is not None and sched < fence
        row['fence_to_completed'] = _positive(fence, completed)
        row['present_enter_to_post'] = _positive(pres_b, pres_e)
        end = completed if completed is not None else (pres_e if pres_e is not None else
              max((e['us'] for e in evs), default=None))
        row['total'] = _positive(create, end) if create is not None else None
        row['missing_completed'] = completed is None
        row['dominant'] = _dominant(row)
        rows.append(row)
    return rows


def _dominant(row):
    best = None
    for name, _label, _positive_only in INTERVALS:
        value = row.get(name)
        if value is not None and (best is None or value > best[1]):
            best = (name, value)
    return best


def percentile(values, q):
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None
    return xs[max(0, math.ceil(q * len(xs)) - 1)]


def stats(rows):
    result = {}
    for name, _label, _positive_only in INTERVALS:
        values = [r[name] for r in rows if r.get(name) is not None]
        result[name] = dict(count=len(values), p50=percentile(values, .50),
                            p90=percentile(values, .90), p99=percentile(values, .99),
                            max=max(values) if values else None)
    result['scheduled_before_fence'] = sum(1 for r in rows if r.get('scheduled_before_fence'))
    return result


def kernel_join(rows, events):
    seqnos, gens, gen_low = set(), set(), set()
    for e in events:
        us, kind, phase, tid, a, b, c, d = e[:8]
        if kind == 20:
            seqnos.add(a)
        elif kind == 30:       # a=surface id, b/c=generation low/high
            gens.add(b | (c << 32))
        elif kind == 31:       # a/b=generation low/high
            gens.add(a | (b << 32))
        elif kind == 39:       # b=generation low at a present wait
            gen_low.add(b)
    gen_low |= {g & 0xffffffff for g in gens}
    for r in rows:
        r['seqno_match'] = bool(r['seqno'] and r['seqno'] in seqnos)
        gens_here = [g for g in r.get('generations', []) if g]
        r['generation_match'] = any(g in gens or (g & 0xffffffff) in gen_low for g in gens_here)
    return dict(seqno_matches=sum(r['seqno_match'] for r in rows),
                generation_matches=sum(r['generation_match'] for r in rows),
                seqnos=len(seqnos), generations=len(gens | gen_low))


def report(path, events=(), epoch=None, out=sys.stdout):
    capture = load(path)
    epoch = capture['start'] if epoch is None else epoch
    rows = build(capture, epoch)
    join = kernel_join(rows, events)
    incomplete = []
    if capture['dropped']:
        incomplete.append(f"{capture['dropped']} ring records dropped")
    if capture['count'] != len(capture['records']):
        incomplete.append('header count does not match records')
    missing = [r['cb'] for r in rows if r['missing_completed']]
    if missing:
        incomplete.append(f"{len(missing)} CBs missing COMPLETED_RUN (cb {missing[:8]}{'...' if len(missing) > 8 else ''})")

    def emit(*args):
        print(*args, file=out)

    emit(f"\n  BGMTL timeline: {path} (pid {capture['pid']}, {len(rows)} CBs, "
         f"{len(capture['records'])} records, epoch {epoch})")
    if incomplete:
        emit('  CAPTURE INCOMPLETE: ' + '; '.join(incomplete))
    else:
        emit('  capture complete: no dropped records, every CB has COMPLETED_RUN')
    emit(f"  kernel join: seqno {join['seqno_matches']}/{len(rows)} CBs, "
         f"ticket generation {join['generation_matches']}/{len(rows)} CBs "
         f"({join['seqnos']} seqnos, {join['generations']} generations in capture)")
    if not rows:
        return dict(capture=capture, rows=rows, stats={}, incomplete=incomplete, join=join)

    emit('\n  interval                          n      p50      p90      p99      max   (ms)')
    st = stats(rows)
    for name, label, _ in INTERVALS:
        s = st[name]
        if not s['count']:
            continue
        emit(f"  {label:34s} {s['count']:4d} {s['p50']:8.3f} {s['p90']:8.3f} "
             f"{s['p99']:8.3f} {s['max']:8.3f}")
    if st['scheduled_before_fence']:
        emit(f"  note: scheduled ran before fence observation on {st['scheduled_before_fence']} CBs "
             "(expected when BGMTL_DEFER_SCHEDULED is off)")

    emit('\n  10 longest frames (by create -> completed):')
    longest = sorted((r for r in rows if r['total'] is not None), key=lambda r: r['total'], reverse=True)[:10]
    for r in longest:
        dom = f"{r['dominant'][0]} {r['dominant'][1]:.3f} ms" if r['dominant'] else '-'
        queue = f" sched={r['scheduled_queue']} completed={r['completed_queue']}"
        emit(f"    cb {r['cb']:4d} total {r['total']:8.3f} ms  dominant {dom}{queue}")
    return dict(capture=capture, rows=rows, stats=st, incomplete=incomplete, join=join)
