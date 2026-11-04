#!/usr/bin/env python3
"""Wait for a GPU hang (j0129 kernel), then dump it. No gestures: the user drives the phone.

    hangwatch.py [--minutes M]

Polls `gpu state` every second; when `completed` stays below the submitted count for 1 s it
sends `gpu hang` (the dump goes to the console, i.e. the running netlog) and exits 0.
Exits 1 if nothing hangs within M minutes (default 30).
"""
import re
import socket
import sys
import time


def cmd(line):
    for host in ('192.168.7.2', '169.254.7.2'):
        try:
            with socket.create_connection((host, 5141), timeout=3) as s:
                s.sendall(line.encode() + b'\n')
                s.settimeout(8)
                return s.recv(8192).decode(errors='replace').strip()
        except OSError:
            continue
    return None


def main():
    minutes = float(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == '--minutes' else 30
    end = time.time() + minutes * 60
    stuck = None
    while time.time() < end:
        m = re.search(r'completed (\d+) of (\d+)', cmd('gpu state') or '')
        if m:
            done, sub = int(m.group(1)), int(m.group(2))
            if done < sub:
                if stuck and stuck[0] == done and time.time() - stuck[1] >= 1:
                    print(time.strftime('%H:%M:%S'), 'GPU stuck at', done, 'of', sub, flush=True)
                    print(cmd('gpu hang'), flush=True)
                    return 0
                if not stuck or stuck[0] != done:
                    stuck = (done, time.time())
            else:
                stuck = None
        time.sleep(0.3)
    print('no hang within', minutes, 'min')
    return 1


if __name__ == '__main__':
    sys.exit(main())
