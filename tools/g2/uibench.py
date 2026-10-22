#!/usr/bin/env python3
"""Unattended UI round (kernel j0056 + boot-arg sweetcmd=1): play the same gestures
every time through the USB command port, then summarise the live log.

    uibench.py play [--wait S]       gestures (about 75 s) once the phone answers
    uibench.py sum LOG [--from TEXT] frame and flicker figures from LOG

play: waits for the command port, then S seconds more (default 0) for SpringBoard,
then home-page swipes, Control Center, Notification Center and Spotlight, each
closed with the home key. Panel pixels (jasmine 1080x2160).

sum: the libsweetca 100-flush lines (frame interval, glFinish; stretches slower
than 150 ms a frame count as idle), SWEET FB flicker checks (A-B-A flashes in the
dock band and the whole panel) and SweetGPU's draws into surfaces the display
still held, from the first line containing TEXT on (default: the whole log).
tools/g2/uiround.sh boots an image and does both.
"""
import argparse
import re
import socket
import sys
import time

HOSTS = ('192.168.7.2', '169.254.7.2')
PORT = 5141


def cmd(line, timeout=8):
    for host in HOSTS:
        try:
            with socket.create_connection((host, PORT), timeout=3) as s:
                s.sendall(line.encode() + b'\n')
                s.settimeout(timeout)
                return s.recv(8192).decode(errors='replace').strip()
        except OSError:
            continue
    return None


def gestures():
    g = []
    for _ in range(6):                                  # home pages, the dock stays on screen
        g += ['swipe 900 1200 150 1200 250', 'd 100000', 'd 100000', 'd 100000', 'd 100000', 'd 100000',
              'swipe 150 1200 900 1200 250', 'd 100000', 'd 100000', 'd 100000', 'd 100000', 'd 100000']
    for _ in range(3):
        g += ['swipe 1000 4 1000 1100 300'] + ['d 100000'] * 15 + ['key 3 1', 'key 3 0'] + ['d 100000'] * 10   # Control Center
        g += ['swipe 200 4 200 1500 300'] + ['d 100000'] * 15 + ['key 3 1', 'key 3 0'] + ['d 100000'] * 10    # Notification Center
        g += ['swipe 540 900 540 1500 250'] + ['d 100000'] * 15 + ['key 3 1', 'key 3 0'] + ['d 100000'] * 10  # Spotlight
    return g


def play(wait):
    t0 = time.time()
    while cmd('t') is None:
        if time.time() - t0 > 400:
            sys.exit('no command port (sweetcmd=1 in the boot-args?)')
        time.sleep(3)
    time.sleep(wait)
    print(f'uibench: start {time.strftime("%H:%M:%S")}', flush=True)
    # one gesture per command line: a line runs in the kernel's command thread, keep each short
    line = []
    for g in gestures():
        line.append(g)
        if len(line) == 6:
            if cmd('; '.join(line), timeout=30) is None:
                print('uibench: command port lost', flush=True)
                return
            line = []
    if line:
        cmd('; '.join(line), timeout=30)
    print(f'uibench: end {time.strftime("%H:%M:%S")}', flush=True)


def summary(path, mark):
    text = open(path, encoding='utf-8', errors='replace').read()
    at = text.find(mark) if mark else 0
    body = text[at:] if at >= 0 else text
    frames = [(float(m.group(1)), float(m.group(2)))
              for m in re.finditer(r'sweetca: 100 flushes in \d+ ms \(([\d.]+) ms each, ([\d.]+) in glFinish', body)]
    moving = sorted(f for f, _ in frames if f < 150)
    flick = [tuple(int(x) for x in m.groups())
             for m in re.finditer(r'flicker check: 300 frames, dock (\d+) changes (\d+) A-B-A, screen (\d+) changes (\d+) A-B-A', body)]
    held = [int(m.group(1)) for m in re.finditer(r'(\d+) drew into a surface the display holds', body)]
    print(f'{path}:')
    if moving:
        med = moving[len(moving) // 2]
        print(f'  frame interval while moving: median {med:.1f} ms, best {moving[0]:.1f}, worst {moving[-1]:.1f} '
              f'({len(moving)} x 100 frames); glFinish {sum(g for _, g in frames) / len(frames):.1f} ms')
    else:
        print('  no moving 100-frame stretch')
    if flick:
        d = sum(f[1] for f in flick)
        s = sum(f[3] for f in flick)
        print(f'  flicker: {d} A-B-A in the dock band, {s} on the whole panel, in {300 * len(flick)} frames')
    print(f'  GPU jobs drawing into a surface on the display: {sum(held)}')


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest='what', required=True)
    p = sp.add_parser('play')
    p.add_argument('--wait', type=float, default=0)
    s = sp.add_parser('sum')
    s.add_argument('log')
    s.add_argument('--from', dest='mark', default='')
    a = ap.parse_args()
    if a.what == 'play':
        play(a.wait)
    else:
        summary(a.log, a.mark)


if __name__ == '__main__':
    main()
