#!/usr/bin/env python3
"""Summarize opt-in task-5 draw diagnostics, in elapsed ms/flush and us/call.

    drawsum.py LOG [--drop-first] [--all-windows]

Prefer logs sliced to one workload. Drop its first report window because that
window can include preceding idle/work. Times include waits and descheduling;
inclusive scopes overlap, and worker threads can run concurrently. No FPS or
CPU-time estimate is made. Exclusive time subtracts nested instrumented scopes.
"""
import argparse
import collections
import re

GL = re.compile(r'sweetca: prof: GL (\d+) of (\d+) ms;')
HEADER = re.compile(r'sweetca: drawprof v1: enabled (\d+)')
ROW = re.compile(r'sweetca: drawprof:\s+(\S+)\s+(\d+) calls ([\d.]+) incl ([\d.]+) excl ms')
EVENT = re.compile(r'sweetca: drawevent: (\S+) (\d+)')
WRAPPER = re.compile(r'sweetca: prof:\s+w_\w+\s+\d+ calls')


def windows(lines):
    current = None
    gl = None
    for line in lines:
        m = GL.search(line)
        if m:
            gl = int(m[1])
        m = HEADER.search(line)
        if m:
            if current is not None and current['complete']:
                yield current
            current = dict(enabled=bool(int(m[1])), gl=gl, rows={}, events={}, complete=False)
            continue
        if current is None:
            continue
        if WRAPPER.search(line):
            current['complete'] = True
        m = ROW.search(line)
        if m:
            current['rows'][m[1]] = (int(m[2]), float(m[3]), float(m[4]))
        m = EVENT.search(line)
        if m:
            current['events'][m[1]] = int(m[2])
    if current is not None and current['complete']:
        yield current


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('log')
    ap.add_argument('--drop-first', action='store_true')
    ap.add_argument('--all-windows', action='store_true')
    a = ap.parse_args()
    with open(a.log, encoding='utf-8', errors='replace') as f:
        ws = list(windows(f))
    if a.drop_first:
        ws = ws[1:]
    ws = [w for w in ws if w['enabled'] and (a.all_windows or (w['gl'] or 0) > 1000)]
    print(f'{a.log}: {len(ws)} complete report windows selected; elapsed time, NOT CPU time or frame time')
    if not ws:
        return
    totals = collections.defaultdict(lambda: [0, 0., 0.])
    events = collections.Counter()
    for w in ws:
        for name, row in w['rows'].items():
            for i, value in enumerate(row):
                totals[name][i] += value
        events.update(w['events'])
    nflush = len(ws) * 100
    ndraw = totals.get('draw-wrapper', [0])[0]
    print(f'{nflush} GL flushes, {ndraw} draws ({ndraw / nflush:.1f} draws/flush); flushes are not frames')
    print(f'{"scope":<25} {"calls/flush":>11} {"incl ms/flush":>13} {"excl ms/flush":>13} {"incl us/call":>13}')
    for name, (calls, incl, excl) in sorted(totals.items(), key=lambda item: -item[1][2]):
        print(f'{name:<25} {calls / nflush:>11.2f} {incl / nflush:>13.3f} {excl / nflush:>13.3f} '
              f'{incl * 1000 / calls if calls else 0:>13.3f}')
    print('events:')
    for name, count in sorted(events.items()):
        print(f'  {name:<29} {count:>12} total {count / nflush:>10.3f}/flush')
    hits, misses = events['program-hit'], events['program-miss']
    if hits + misses:
        print(f'program lookup hit rate: {100 * hits / (hits + misses):.3f}%')


if __name__ == '__main__':
    main()
