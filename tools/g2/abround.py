#!/usr/bin/env python3
"""One temporary boot + one standard framebench capture, for A/B comparisons of boot images.

    abround.py IMAGE NAME --kernel K --lib L [--settle S] [--lock PATH]

Boots IMAGE with tools/sweet-run.py (command-port reboot -> fastboot boot; the live log goes to
logs/netlog-NAME.txt), waits for the command port and libsweetca's first lines, unlocks
(power key, swipe up), waits S seconds (default 150: the post-boot accessory sync), then runs
framebench into research/ab/NAME. The phone stays in the temporary boot afterwards; a reboot
returns to the installed slot. Prints the capture's Home B / Control A / Control B rates.
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import uibench  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('image')
    p.add_argument('name')
    p.add_argument('--kernel', required=True)
    p.add_argument('--lib', required=True)
    p.add_argument('--settle', type=int, default=150)
    p.add_argument('--lock')
    p.add_argument('--pin-cpu', action='store_true', help='dvfs auto 0 and both clusters at their top rate after the unlock')
    a = p.parse_args()
    os.chdir(ROOT)
    log = f'logs/netlog-{a.name}.txt'
    out = f'research/ab/{a.name}'
    if os.path.exists(out) or os.path.exists(log):
        sys.exit(f'{out} or {log} exists')
    run = subprocess.Popen([sys.executable, 'tools/sweet-run.py', a.image, log, '--secs', '900'],
                           stdout=open(log + '.run', 'w'), stderr=subprocess.STDOUT)
    t0 = time.time()
    while not (os.path.exists(log) and b'sweetca:' in open(log, 'rb').read()):
        if run.poll() is not None or time.time() - t0 > 500:
            sys.exit(f'no libsweetca lines in {log} (see {log}.run)')
        time.sleep(3)
    while uibench.cmd('t') is None:
        time.sleep(2)
    print(f'{time.strftime("%H:%M:%S")} up after {time.time() - t0:.0f} s', flush=True)
    time.sleep(45)
    uibench.cmd('key 3 1'); uibench.cmd('key 3 0'); time.sleep(1.5)
    uibench.cmd('swipe 540 2150 540 900 250')
    if a.pin_cpu:
        for c_ in ('dvfs auto 0', 'dvfs set 0 2208000', 'dvfs set 1 1843200'):
            print(uibench.cmd(c_), flush=True)
    print(f'{time.strftime("%H:%M:%S")} unlocked; settling {a.settle} s', flush=True)
    time.sleep(a.settle)
    cmd = [sys.executable, 'tools/g2/framebench.py', 'run', '--out', out, '--ui-ready',
           '--kernel', a.kernel, '--lib', a.lib]
    if a.lock:
        cmd += ['--lock', a.lock]
    rc = subprocess.run(cmd).returncode
    for c in ('dvfs stat', 'gpu state', 'ddr state', 'tsens'):
        print(uibench.cmd(c, timeout=10), flush=True)
    if rc:
        sys.exit(f'framebench exit {rc}')
    s = json.load(open(os.path.join(out, 'summary.json')))
    for ph in ('home-b', 'control-a', 'control-b', 'spotlight-repeat'):
        m = s['phases'][ph]['motion']
        print(f'{a.name} {ph}: {m["updates_per_second"] or 0:.2f}/s, median {m["median_ms"]} ms, p95 {m["p95_ms"]} ms')


if __name__ == '__main__':
    main()
