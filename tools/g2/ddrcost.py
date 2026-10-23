#!/usr/bin/env python3
"""Per-flush GL cost per DDR rate in a ddrround.sh log (j0064).

    ddrcost.py LOG

libsweetca prints one "prof: GL X of Y ms; N submits (S ms in the call), W waits (T ms)" line
per 100 flushes. Y includes the idle time between gestures, so ddrsum.py's "ms each" mostly
measures the gesture script; X (time inside GL calls: Mesa's CPU work plus the GPU waits) and
T (GPU waits) are per-flush costs. Every play runs the same gestures, so the totals over one
DDR rate compare directly. A window that spans a rate switch is counted where it ends.
"""
import re
import sys

text = open(sys.argv[1], encoding='utf-8', errors='replace').read().splitlines()
seg, rows = 'bootloader rate', {}
order = [seg]
for line in text:
    m = re.search(r'SWEET DDR: ddr (\d+): ok', line)
    if m:
        seg = f'{m.group(1)} MHz (#{len(order)})'
        order.append(seg)
        continue
    m = re.search(r'sweetca: prof: GL (\d+) of (\d+) ms; (\d+) submits \((\d+) ms in the call\), (\d+) waits \((\d+) ms\)',
                  line)
    if m:
        rows.setdefault(seg, []).append([int(x) for x in m.groups()])

print(f'{"rate":<22} {"windows":>7} {"GL/flush":>9} {"wait/flush":>11} {"GL-wait":>8} {"submit":>7} {"busy":>6}')
for seg in order:
    r = rows.get(seg, [])
    busy = [x for x in r if x[0] > 1000]       # windows with real motion (> 10 ms GL per flush)
    if not busy:
        print(f'{seg:<22} {len(r):>7}  no busy window')
        continue
    n = 100 * len(busy)
    gl = sum(x[0] for x in busy) / n
    wait = sum(x[5] for x in busy) / n
    sub = sum(x[3] for x in busy) / n
    print(f'{seg:<22} {len(r):>7} {gl:>8.1f}  {wait:>10.1f} {gl - wait:>8.1f} {sub:>7.1f} {len(busy):>6}')
print('ms per flush over windows with > 10 ms of GL per flush; GL-wait = Mesa CPU time')
