#!/usr/bin/env python3
"""Per-DDR-rate summary of a ddrround.sh log (j0064).

    ddrsum.py LOG

The log is cut at each kernel line "SWEET DDR: ddr MHZ: ..." (the command port's vote); the
part before the first one ran at the bootloader's rate. For each part: libsweetca's moving
100-flush windows (under 150 ms a frame) as clksum.py reads them (frame median and best,
glFinish, GPU waits per frame), the "ddr bench" line, and the medians of the "ddr bw" samples
taken during the play (CPU bwmon MB/s, GPU busy, VBIF beats and RAM-starved cycles per second).
Samples with a known read load ("load N MB/s") are listed apart: they calibrate the bwmon unit.
The kernel prints bwmon2 MB/s for a 64 KiB unit (the DT's count-unit); j64a's calibration showed
1 MiB units (a 3554 MB/s read load added 3880 MiB/s), so the MB/s here come from the raw units.
"""
import re
import statistics
import sys

text = open(sys.argv[1], encoding='utf-8', errors='replace').read().splitlines()
parts, cur = [], ('bootloader rate', [])
for line in text:
    m = re.search(r'SWEET DDR: ddr (\d+): (.*)', line)
    if m:
        parts.append(cur)
        cur = (f'{m.group(1)} MHz: {m.group(2)[:120]}', [])
    else:
        cur[1].append(line)
parts.append(cur)

BW = re.compile(r'ddr bw at (\d+) MHz over (\d+) ms: bwmon2 (\d+) units in (\d+) windows \((\d+) MB/s at 64 KiB\), '
                r'zone cnt (\w+) max0 (\d+), mon cnt (\d+) \((\d+) MB/s at 64 KiB\); load (\d+) MB/s'
                r'(?:; gpu busy (\d+) Mcyc/s, vbif beats (\d+) M/s, ram-starved (\d+) Mcyc/s)?')


def bwmon_mbps(m):
    """CPU bwmon2 MB/s from the raw count: 1 MiB units over the window's ms"""
    return int(m.group(3)) * 1048576 // (int(m.group(2)) * 1000)


def med(xs):
    return statistics.median(xs) if xs else None


for title, lines in parts:
    print(title)
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
    if moving:
        waits = [w[2] for w in moving if w[2] is not None]
        gw = f'{sum(waits) / len(waits):.1f} ms' if waits else '?'
        print(f'  {len(moving)} moving windows: frame median {moving[len(moving) // 2][0]:.1f} ms, '
              f'best {moving[0][0]:.1f}; glFinish {sum(w[1] for w in moving) / len(moving):.1f} ms, '
              f'GPU waits {gw} per frame')
    else:
        print('  no moving 100-frame window')
    for line in lines:
        m = re.search(r'SWEET DDR: (ddr bench .*)', line)
        if m:
            print(f'  {m.group(1)}')
    plain, loaded = [], []
    for line in lines:
        m = BW.search(line)
        if m:
            (loaded if int(m.group(10)) else plain).append(m)
    for m in loaded:
        print(f'  calibration: load {m.group(10)} MB/s read, bwmon2 {bwmon_mbps(m)} MB/s at 1 MiB units '
              f'({m.group(3)} units in {m.group(4)} windows)')
    if plain:
        def col(k):
            return [int(m.group(k)) for m in plain if m.group(k) is not None]
        busy, beats, starved = med(col(11)), med(col(12)), med(col(13))
        gpu = (f'; GPU busy {busy} Mcyc/s, VBIF beats {beats} M/s, RAM-starved {starved} Mcyc/s'
               if busy is not None else '')
        print(f'  {len(plain)} bus samples (median): CPU bwmon2 {med([bwmon_mbps(m) for m in plain])} MB/s{gpu}')
