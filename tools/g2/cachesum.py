#!/usr/bin/env python3
"""SweetGPU buffer churn and Mesa buffer cache counters in a uiround log (PERF-TASKS task 4).

    cachesum.py LOG...

libsweetca (task 4 builds on) prints, with each 100-flush "prof: GL" line, the SweetGPU buffers created,
mapped and freed (newer builds also the IOSurfaces imported and the handles held) and the bo / ring cache
counters since the last report. Per log: the counters per flush over all windows and over the windows with
real motion (> 10 ms GL per flush, as ddrcost.py), Mesa CPU per flush (GL - wait) over those, and the
SweetGPU handles the client holds after each window (a leak grows).
"""
import re
import sys

GL = re.compile(r'sweetca: prof: GL (\d+) of (\d+) ms; (\d+) submits \((\d+) ms in the call\), (\d+) waits \((\d+) ms\)')
BUF = re.compile(r'sweetca: prof: SweetGPU buffers: (\d+) created, (\d+) mapped, (\d+) freed(?:; (\d+) imported, (-?\d+) held)?')
CACHE = re.compile(r'sweetca: prof: (bo|ring): (\d+) hits, (\d+) misses \((\d+) at a busy head, (\d+) flag skips\), '
                   r'(\d+) expired, (\d+) cached')

for path in sys.argv[1:]:
    wins, cur = [], None
    for line in open(path, encoding='utf-8', errors='replace'):
        m = GL.search(line)
        if m:
            cur = {'gl': int(m.group(1)), 'wait': int(m.group(6))}
            wins.append(cur)
            continue
        if cur is None:
            continue
        m = BUF.search(line)
        if m:
            cur['new'], cur['map'], cur['free'] = (int(x) for x in m.groups()[:3])
            if m.group(5) is not None:
                cur['imp'], cur['held'] = int(m.group(4)), int(m.group(5))
            continue
        m = CACHE.search(line)
        if m:
            cur[m.group(1)] = [int(x) for x in m.groups()[1:]]
    wins = [w for w in wins if 'new' in w]
    print(f'{path}: {len(wins)} windows with counters')
    if not wins:
        continue
    held, trail = 0, []
    for w in wins:
        held += w['new'] + w.get('imp', 0) - w['free']
        trail.append(w.get('held', held))
    busy = [w for w in wins if w['gl'] > 1000]
    for name, ws in (('all windows', wins), (f'busy ({len(busy)})', busy)):
        if not ws:
            continue
        n = 100 * len(ws)
        s = lambda k: sum(w[k] for w in ws)
        c = lambda which, i: sum(w.get(which, [0] * 6)[i] for w in ws)
        print(f'  {name:<12} per flush: created {s("new") / n:.2f}, mapped {s("map") / n:.2f}, freed {s("free") / n:.2f}; '
              f'ring {c("ring", 0) / n:.1f} hits {c("ring", 1) / n:.2f} misses; bo {c("bo", 0) / n:.2f} hits '
              f'{c("bo", 1) / n:.2f} misses ({c("bo", 3) / n:.2f} flag skips)')
    if busy:
        n = 100 * len(busy)
        gl = sum(w['gl'] for w in busy) / n
        wait = sum(w['wait'] for w in busy) / n
        print(f'  Mesa CPU per flush (GL - wait, busy windows): {gl - wait:.1f} ms (GL {gl:.1f}, wait {wait:.1f})')
    what = 'SweetGPU handles held' if 'held' in wins[0] else 'created - freed (imports not counted)'
    print(f'  {what} after each window: {" ".join(str(x) for x in trail)}')
