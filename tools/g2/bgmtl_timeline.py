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
    13: 'LOCK_WAIT', 14: 'HANDLERS_BEGIN',
}
QUEUE = {0: 'replay', 1: 'completion', 2: 'inline'}
NO_CB = 0xffffffff
FILE_NAMES = {0: 'bgmtl.m', 1: 'bg_write_admission.h', 2: 'bg_work_admission.h'}

# Call-site line -> enclosing function, as of the source at this commit. Lines are
# the source line of each bg_lock() token; file tags come from the header macros
# (1=bg_write_admission.h, 2=bg_work_admission.h, 0=bgmtl.m). Keep this table in
# sync when bgmtl.m moves; an unknown site is still printed as file:line.
SITES = {
    (0, 920): '-[BGMTLDevice newTextureWithBytesNoCopy:...]',
    (0, 1031): '-[BGMTLDevice newRenderPipelineStateWithDescriptor:error:]',
    (0, 1037): '-[BGMTLDevice newRenderPipelineStateWithDescriptor:error:] cleanup',
    (0, 1064): '-[BGMTLDevice bgPipelineForFunction:descriptor:error:]',
    (0, 1069): '-[BGMTLDevice bgPipelineForFunction:descriptor:error:] cleanup',
    (0, 1111): '-[BGMTLBuffer initWithBGDevice:length:]',
    (0, 1136): '-[BGMTLBuffer dealloc]',
    (0, 1180): '-[BGMTLComputePipeline dealloc]',
    (0, 1229): '-[BGMTLCommandBuffer dealloc]',
    (0, 1472): '-[BGMTLCommandBuffer commit]',
    (0, 1508): '-[BGMTLCommandBuffer bgReplayFrom:]',
    (0, 2260): '-[BGMTLTexture initWithBGDevice:descriptor:iosurface:plane:] surface',
    (0, 2286): '-[BGMTLTexture initWithBGDevice:descriptor:iosurface:plane:] allocate',
    (0, 2296): '-[BGMTLTexture dealloc]',
    (0, 2352): '-[BGMTLTexture rwaTextureSampled]',
    (0, 2405): '-[BGMTLTexture rwaTexture] refresh epoch',
    (0, 2413): '-[BGMTLTexture rwaTexture] no-copy cache',
    (0, 2428): '-[BGMTLTexture rwaTexture] linear source',
    (0, 2486): '-[BGMTLTexture replaceRegion:...]',
    (0, 2502): '-[BGMTLTexture getBytes:...]',
    (0, 2527): '-[BGMTLSampler initWithBGDevice:descriptor:]',
    (0, 2534): '-[BGMTLSampler dealloc]',
    (0, 2556): '-[BGMTLDepthStencil initWithBGDevice:descriptor:]',
    (0, 2567): '-[BGMTLDepthStencil dealloc]',
    (0, 2578): '-[BGMTLRenderPipeline dealloc]',
    (1, 39): 'bg_adm_lock',
    (2, 34): '-[BGMTLCommandBuffer bgCollectWrites:]',
}

# name, label, positive-only (fence->scheduled is normally negative)
INTERVALS = [
    ('create_to_commit', 'create -> commit (encode)', True),
    ('commit_to_replay', 'commit -> replay_begin (handoff)', True),
    ('replay_to_submit_begin', 'replay_begin -> submit_begin', True),
    ('submit_begin_to_end', 'submit_begin -> submit_end (flush+drain+ioctl)', True),
    ('submit_end_to_fence', 'submit_end -> fence_observed (GPU wait)', True),
    ('submit_end_to_scheduled', 'submit_end -> scheduled (scheduled callback)', True),
    ('fence_to_scheduled', 'fence -> scheduled (only if not earlier)', True),
    ('fence_to_handlers_begin', 'fence -> handlers_begin', True),
    ('handlers_begin_to_completed', 'handlers_begin -> completed (handlers)', True),
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
        if rec['cb'] == NO_CB:
            continue
        grouped[rec['cb']].append(rec)
    rows = []
    for cb, evs in sorted(grouped.items()):
        evs.sort(key=lambda e: e['us'])
        first = _first(evs)
        f = lambda k: first[k]['us'] if k in first else None
        create, commit, replay = f(1), f(2), f(3)
        sub_b, sub_e, rep_e = f(5), f(6), f(7)
        sched, fence, completed = f(8), f(9), f(10)
        handlers_begin, handlers_end = f(14), f(10)
        pres_b, pres_e = f(12), f(11)
        ticket = first.get(4)
        tickets = [e for e in evs if e['kind'] == 4]
        generations = [e['a'] for e in tickets if e['a']]
        row = dict(cb=cb, create=create, commit=commit, replay=replay,
                   submit_begin=sub_b, submit_end=sub_e, replay_end=rep_e,
                   scheduled=sched, fence=fence, completed=completed,
                   handlers_begin=handlers_begin, handlers_end=handlers_end,
                   handler_count=first[14]['a'] if 14 in first else None,
                   handler_tid=first[14]['b'] if 14 in first else None,
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
        row['fence_to_handlers_begin'] = _positive(fence, handlers_begin)
        row['handlers_begin_to_completed'] = _positive(handlers_begin, completed)
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


def _site_parts(a):
    file = (a >> 62) & 3
    line = (a >> 48) & 0x3fff
    tid = a & 0xffffffffffff
    return file, line, tid


def _site_label(file, line):
    owner = SITES.get((file, line))
    where = f'{FILE_NAMES.get(file, str(file))}:{line}'
    return f'{where} {owner}' if owner else where


def lock_waits(capture, epoch=None):
    """LOCK_WAIT records with their absolute start/end and call site."""
    epoch = capture['start'] if epoch is None else epoch
    numer, denom = capture['numer'], capture['denom']
    waits = []
    for rec in capture['records']:
        if rec['kind'] != 13:
            continue
        file, line, tid = _site_parts(rec['a'])
        us = to_us(rec['t'], epoch, numer, denom)
        wait_ms = (rec['b'] * numer) / denom / 1e6
        waits.append(dict(us=us, start_us=us - wait_ms * 1000.0, ms=wait_ms,
                          tid=tid, file=file, line=line,
                          site=_site_label(file, line), cb=rec['cb']))
    return waits


def annotate_waits(waits, rows):
    """Mark each wait that overlaps a handlers_begin->completed window on its tid."""
    windows = [(r['handlers_begin'], r['completed'], r['handler_tid'], r['cb'])
               for r in rows if r.get('handlers_begin') is not None and r.get('completed') is not None]
    for w in waits:
        w['inside'] = [cb for begin, end, tid, cb in windows
                       if tid == w['tid'] and w['start_us'] < end and w['us'] > begin]
    return waits


def lock_stats(waits):
    grouped = collections.defaultdict(list)
    for w in waits:
        grouped[(w['file'], w['line'], w['site'])].append(w)
    result = []
    for (file, line, site), ws in sorted(grouped.items(), key=lambda kv: -sum(w['ms'] for w in kv[1])):
        inside = [w for w in ws if w.get('inside')]
        result.append(dict(file=file, line=line, site=site, count=len(ws),
                           total_ms=sum(w['ms'] for w in ws),
                           max_ms=max(w['ms'] for w in ws),
                           inside_count=len(inside),
                           inside_ms=sum(w['ms'] for w in inside)))
    return result


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
    waits = annotate_waits(lock_waits(capture, epoch), rows)
    lock_st = lock_stats(waits)
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

    def show_locks():
        emit(f"\n  bg_lock waits >=100 us: {len(waits)} waits, "
             f"{sum(w['ms'] for w in waits):.3f} ms total")
        if not lock_st:
            emit('    (none)')
            return
        emit(f"    {'site':56s} {'n':>4s} {'total_ms':>9s} {'max_ms':>8s}")
        for s in lock_st:
            emit(f"    {s['site']:56s} {s['count']:4d} {s['total_ms']:9.3f} {s['max_ms']:8.3f}")
        inside = [s for s in lock_st if s['inside_count']]
        emit(f"\n  waits inside completed handlers: {sum(s['inside_count'] for s in inside)} waits, "
             f"{sum(s['inside_ms'] for s in inside):.3f} ms total")
        if inside:
            for s in inside:
                emit(f"    {s['site']:56s} {s['inside_count']:4d} {s['inside_ms']:9.3f} ms")
        else:
            emit('    (none)')
        handler_rows = sorted((r for r in rows if r['handlers_begin_to_completed'] is not None),
                              key=lambda r: r['handlers_begin_to_completed'], reverse=True)[:10]
        emit('\n  10 slowest completed-handler runs:')
        for r in handler_rows:
            ws = sorted((w for w in waits if w['tid'] == r['handler_tid'] and r['cb'] in w['inside']),
                        key=lambda w: -w['ms'])
            if ws:
                shown = '; '.join(f"{w['site']} {w['ms']:.3f}" for w in ws[:12])
                if len(ws) > 12:
                    shown += f'; +{len(ws) - 12} more'
            else:
                shown = '(none)'
            emit(f"    cb {r['cb']:4d} handlers {r['handlers_begin_to_completed']:8.3f} ms "
                 f"queue {r['completed_queue']}: {shown}")

    if not rows:
        emit(f"\n  BGMTL timeline: {path} (pid {capture['pid']}, 0 CBs, "
             f"{len(capture['records'])} records, epoch {epoch})")
        if incomplete:
            emit('  CAPTURE INCOMPLETE: ' + '; '.join(incomplete))
        show_locks()
        return dict(capture=capture, rows=rows, stats={}, incomplete=incomplete, join=join,
                    waits=waits, lock_stats=lock_st)

    emit(f"\n  BGMTL timeline: {path} (pid {capture['pid']}, {len(rows)} CBs, "
         f"{len(capture['records'])} records, epoch {epoch})")
    if incomplete:
        emit('  CAPTURE INCOMPLETE: ' + '; '.join(incomplete))
    else:
        emit('  capture complete: no dropped records, every CB has COMPLETED_RUN')
    emit(f"  kernel join: seqno {join['seqno_matches']}/{len(rows)} CBs, "
         f"ticket generation {join['generation_matches']}/{len(rows)} CBs "
         f"({join['seqnos']} seqnos, {join['generations']} generations in capture)")

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
    show_locks()
    return dict(capture=capture, rows=rows, stats=st, incomplete=incomplete, join=join,
                waits=waits, lock_stats=lock_st)
