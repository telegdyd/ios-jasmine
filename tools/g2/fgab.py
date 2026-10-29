#!/usr/bin/env python3
"""Paired fuel-gauge A/B over the command port (j0114 `batt`), e.g. the DDR governor off vs on:
    fgab.py CYCLES SECS "ddrgov off" "ddrgov on"
Each cycle runs A and B for SECS (order flipped every cycle to cancel drift), samples `batt` every 1 s
(first 4 s after a switch dropped) and prints B-A; positive means B draws less. Valid while the battery
discharges (unplugged, or USB with the charger input saturated)."""
import re
import socket
import statistics
import sys
import time

HOSTS = ('192.168.7.2', '169.254.7.2')


def one(line, timeout=30):
    for host in HOSTS:
        try:
            with socket.create_connection((host, 5141), timeout=3) as s:
                s.sendall(line.encode() + b'\n')
                s.settimeout(timeout)
                out = b''
                try:
                    while True:
                        b = s.recv(65536)
                        if not b:
                            break
                        out += b
                except socket.timeout:
                    pass
                return out.decode(errors='replace').strip() or '(no answer)'
        except OSError:
            continue
    return None


cycles, secs = int(sys.argv[1]), float(sys.argv[2])
cmds = {'A': sys.argv[3], 'B': sys.argv[4]}


def phase(k):
    for c in filter(None, cmds[k].split(';')):
        one(c)
    t0 = time.time()
    ma = []
    while time.time() - t0 < secs:
        r = one('batt') or ''
        m = re.search(r'(\d+) mV (-?\d+) mA', r)
        if m and time.time() - t0 > 4:
            ma.append(int(m.group(2)))
        time.sleep(1)
    return statistics.mean(ma) if ma else float('nan')


diffs = []
for i in range(cycles):
    order = 'AB' if i % 2 == 0 else 'BA'
    v = {k: phase(k) for k in order}
    diffs.append(v['B'] - v['A'])
    print(f'cycle {i}: A {v["A"]:.0f} mA, B {v["B"]:.0f} mA, B-A {diffs[-1]:+.0f}', flush=True)
sd = statistics.stdev(diffs) if len(diffs) > 1 else 0
print(f'B-A mean {statistics.mean(diffs):+.1f} mA, sd {sd:.1f}, n {len(diffs)} (positive: B draws less)', flush=True)
g = one('ddrgov') or ''
print(g[:400])
