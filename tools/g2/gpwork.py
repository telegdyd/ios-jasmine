#!/usr/bin/env python3
"""Fixed workload for a SWEETCA_GPUPROF / SWEETCA_DRAWPROF boot (no boot of its own): wait for the
command port and libsweetca's first log lines, unlock, settle, ~35 s of home page swipes, 10 s idle,
~25 s of Control Center open/close, 10 s idle. Prints the live log's line count at each marker,
so tools/g2/gpuwin.py LOG FIRST LAST can be run on one workload.

    gpwork.py LOG [--settle S]     (LOG: the file tools/sweet-run.py is writing)
"""
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uibench

log = sys.argv[1]
settle = int(sys.argv[3]) if len(sys.argv) > 3 else 90

def lines():
    while not os.path.exists(log):
        time.sleep(2)
    with open(log, 'rb') as f:
        return f.read().count(b'\n')

def mark(name):
    print(f'{time.strftime("%H:%M:%S")} {name} line {lines()}', flush=True)

t0 = time.time()
while uibench.cmd('t') is None:
    if time.time() - t0 > 400:
        sys.exit('no command port')
    time.sleep(3)
mark('command port up')
# backboardd with the library: wait for its first lines
while b'sweetca:' not in open(log, 'rb').read():
    if time.time() - t0 > 500:
        sys.exit('no sweetca lines')
    time.sleep(3)
mark('sweetca up')
time.sleep(45)
uibench.cmd('key 3 1'); uibench.cmd('key 3 0'); time.sleep(1.5)
uibench.cmd('swipe 540 2150 540 900 250'); time.sleep(3)
mark('unlocked')
time.sleep(settle)
mark('home start')
for _ in range(30):
    uibench.cmd('swipe 900 1200 150 1200 250'); time.sleep(.3)
    uibench.cmd('swipe 150 1200 900 1200 250'); time.sleep(.3)
mark('home end')
time.sleep(10)
mark('cc start')
for _ in range(15):
    uibench.cmd('swipe 1000 4 1000 1100 300'); time.sleep(.6)
    uibench.cmd('key 3 1'); uibench.cmd('key 3 0'); time.sleep(.6)
mark('cc end')
time.sleep(10)
mark('done')
for c in ('dvfs stat', 'gpu state', 'ddr state', 'tsens'):
    print(uibench.cmd(c, timeout=10))
