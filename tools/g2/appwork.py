#!/usr/bin/env python3
"""In-app motion beyond framebench's Home/CC/Spotlight: Settings list scrolling, a Settings
sub-page pushed and popped, and an app opened from the dock and closed. Gestures go through the
command port (panel pixels, 1080x2160); each one is wrapped in `bench mark 1/0`, so a framebench
manual capture running at the same time counts swap arrivals during the motion.

    appwork.py play ACTIVITY                   gestures only (e.g. during a GPUPROF boot)
    appwork.py capture ACTIVITY OUT --kernel K --lib L [--lock PATH] [--seconds S]
                                               framebench manual capture OUT around the gestures
    appwork.py all OUTPREFIX --kernel K --lib L [--lock PATH]
                                               capture of every activity into OUTPREFIX-<activity>

ACTIVITY: settings-scroll, settings-sub, app-open. Each starts and ends on the home screen
(first home page). Never boots, flashes or installs anything.
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

# first home page of the installed image (Photos, App Store, Settings; dock Phone, Safari, Messages)
SETTINGS = (163, 523)
SAFARI = (541, 2008)
# a Settings row on the top-level list ("General" sits below the account block)
SUB_ROW = (540, int(os.environ.get('APPWORK_SUB_Y', '1420')))
BACK = (70, 150)


def c(line):
    return uibench.cmd(line)


def tap(xy):
    c(f'swipe {xy[0]} {xy[1]} {xy[0]} {xy[1]} 40')


def marked(line, tail):
    c('bench mark 1')
    if callable(line):
        line()
    else:
        c(line)
    time.sleep(tail)
    c('bench mark 0')


def home():
    c('key 3 1'); c('key 3 0')


def settings_scroll(rounds=8):
    tap(SETTINGS); time.sleep(3)
    for _ in range(rounds):
        marked('swipe 540 1750 540 450 300', .9)
        time.sleep(.3)
        marked('swipe 540 450 540 1750 300', .9)
        time.sleep(.3)
    home(); time.sleep(2)


def settings_sub(rounds=6):
    tap(SETTINGS); time.sleep(3)
    for _ in range(rounds):
        marked(lambda: tap(SUB_ROW), 1.2)
        time.sleep(.5)
        marked('swipe 4 1100 800 1100 250', 1.2)     # edge swipe back
        time.sleep(.5)
    home(); time.sleep(2)


def app_open(rounds=5):
    for _ in range(rounds):
        marked(lambda: tap(SAFARI), 2.0)
        time.sleep(1.0)
        marked(home, 1.5)
        time.sleep(1.0)


ACTS = {'settings-scroll': settings_scroll, 'settings-sub': settings_sub, 'app-open': app_open}


def capture(act, out, kernel, lib, lock, seconds):
    cmd = [sys.executable, os.path.join(HERE, 'framebench.py'), 'run', '--out', out, '--manual',
           '--seconds', str(seconds), '--kernel', kernel, '--lib', lib]
    if lock:
        cmd += ['--lock', lock]
    fb = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT)
    t0 = time.time()
    lines = []
    for line in fb.stdout:
        lines.append(line)
        if 'manual capture active' in line:
            break
        if time.time() - t0 > 120:
            break
    t1 = time.time()
    ACTS[act]()
    print(f'appwork: {act} gestures {time.time() - t1:.1f} s', flush=True)
    rest, _ = fb.communicate()
    lines.append(rest or '')
    open(out + '.framebench.txt', 'w').write(''.join(lines))
    if fb.returncode:
        print(''.join(lines)[-2000:])
        return None
    s = json.load(open(os.path.join(ROOT, out, 'summary.json')))
    m = s['phases']['manual-settings']['motion']
    print(f'appwork {act}: {m["updates_per_second"] or 0:.2f}/s, median {m["median_ms"]} ms, '
          f'p95 {m["p95_ms"]} ms, active {m["active_seconds"]} s', flush=True)
    return m


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('what', choices=['play', 'capture', 'all'])
    p.add_argument('arg')
    p.add_argument('out', nargs='?')
    p.add_argument('--kernel')
    p.add_argument('--lib')
    p.add_argument('--lock')
    p.add_argument('--seconds', type=int, default=50)
    a = p.parse_args()
    if a.what == 'play':
        ACTS[a.arg]()
    elif a.what == 'capture':
        capture(a.arg, a.out, a.kernel, a.lib, a.lock, a.seconds)
    else:
        for act in ACTS:
            capture(act, f'{a.arg}-{act}', a.kernel, a.lib, a.lock, a.seconds)
            time.sleep(3)


if __name__ == '__main__':
    main()
