#!/usr/bin/env python3
"""Per-GPU-level summary of a clkround.sh log (j0060).

    clksum.py LOG

The log is cut at each kernel line "SWEET GPU: gpu clk MHZ: ..." (the command port's
switch); the part before the first one ran at the boot level (gpumhz=, 266 MHz). For
each part, over libsweetca's 100-flush windows while moving (under 150 ms a frame):
the frame interval (median, best), the time in glFinish and the GPU waits per frame
(the "prof:" line after each window), plus the switch line itself.
"""
import re
import sys

text = open(sys.argv[1], encoding='utf-8', errors='replace').read().splitlines()
parts, cur = [], ('boot level (gpumhz=)', [])
for line in text:
    m = re.search(r'SWEET GPU: gpu clk (\d+): (.*)', line)
    if m:
        parts.append(cur)
        cur = (f'{m.group(1)} MHz: {m.group(2)[:160]}', [])
    else:
        cur[1].append(line)
parts.append(cur)

for title, lines in parts:
    win = []
    for i, line in enumerate(lines):
        m = re.search(r'sweetca: 100 flushes in \d+ ms \(([\d.]+) ms each, ([\d.]+) in glFinish', line)
        if not m:
            continue
        wait = None
        for nxt in lines[i + 1:i + 4]:
            w = re.search(r'sweetca: prof: GL .* (\d+) waits \((\d+) ms\)', nxt)
            if w:
                wait = int(w.group(2)) / 100
                break
        win.append((float(m.group(1)), float(m.group(2)), wait))
    moving = sorted(w for w in win if w[0] < 150)
    print(title)
    if not moving:
        print('  no moving 100-frame window')
        continue
    med = moving[len(moving) // 2][0]
    fin = sum(w[1] for w in moving) / len(moving)
    waits = [w[2] for w in moving if w[2] is not None]
    gw = f'{sum(waits) / len(waits):.1f} ms' if waits else '?'
    print(f'  {len(moving)} moving windows: frame median {med:.1f} ms, best {moving[0][0]:.1f}; '
          f'glFinish {fin:.1f} ms, GPU waits {gw} per frame')
