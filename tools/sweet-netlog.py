#!/usr/bin/env python3
"""Live iOS console log over USB Ethernet (kernel patch j0021, bsd/dev/sweet_usb.c).

The phone serves its console ring on TCP port 5140 at 192.168.7.2 (and the
link-local 169.254.7.2): the whole ring first (the boot so far), then new
lines as they come. This connects (retrying until the phone is up) and copies
everything to stdout and to OUT.

    sweet-netlog.py OUT.txt [--wait SECONDS] [--for SECONDS]

--wait: give up if no connection within this time (default 300).
--for:  stop this long after connecting (default: until the phone goes away).
"""
import argparse
import socket
import sys
import time

HOSTS = ('192.168.7.2', '169.254.7.2')
PORT = 5140


def connect(deadline):
    while time.time() < deadline:
        for host in HOSTS:
            try:
                return socket.create_connection((host, PORT), timeout=2), host
            except OSError:
                pass
        time.sleep(1)
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--wait', type=float, default=300)
    ap.add_argument('--for', dest='duration', type=float, default=0)
    a = ap.parse_args()
    sock, host = connect(time.time() + a.wait)
    if sock is None:
        sys.exit(f'no log server at {" or ".join(HOSTS)}:{PORT} within {a.wait:.0f} s')
    print(f'# connected to {host}:{PORT}', file=sys.stderr)
    end = time.time() + a.duration if a.duration else None
    sock.settimeout(1)
    with open(a.out, 'ab') as f:
        while end is None or time.time() < end:
            try:
                data = sock.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                break
            f.write(data)
            f.flush()
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
    print('# connection closed', file=sys.stderr)


if __name__ == '__main__':
    main()
