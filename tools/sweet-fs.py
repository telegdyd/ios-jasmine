#!/usr/bin/env python3
"""Files in and out of the iOS root over USB Ethernet (kernel patch j0024, bsd/dev/sweet_netfs.c).

    sweet-fs.py put LOCAL /remote/path [--mode 0755] [--owner UID:GID]
    sweet-fs.py get /remote/path LOCAL
    sweet-fs.py ls /remote/dir
    sweet-fs.py mkdir /remote/dir          (with parents)
    sweet-fs.py rm /remote/file

TCP port 5142 at 192.168.7.2 (or 169.254.7.2), one request per connection,
kernel credentials. put creates missing parent directories, replaces the
file (unlink + create, so a running program keeps the old one) and fsyncs.
The default mode is 0644, or 0755 when LOCAL is executable; owner 0:0.
"""
import argparse
import os
import socket
import sys

HOSTS = ('192.168.7.2', '169.254.7.2')
PORT = 5142


def connect():
    for host in HOSTS:
        try:
            return socket.create_connection((host, PORT), timeout=5)
        except OSError:
            continue
    sys.exit(f'no file server at {" or ".join(HOSTS)}:{PORT}')


def readline(s):
    line = b''
    while not line.endswith(b'\n'):
        c = s.recv(1)
        if not c:
            break
        line += c
    return line.decode(errors='replace').strip()


def check(line):
    if not line.startswith('OK'):
        sys.exit(f'phone: {line or "(connection closed)"}')
    return line


def put(local, remote, mode, owner):
    data = open(local, 'rb').read()
    if mode is None:
        mode = 0o755 if os.access(local, os.X_OK) and not local.endswith(('.plist', '.txt')) else 0o644
    uid, gid = (int(x) for x in owner.split(':'))
    with connect() as s:
        s.settimeout(120)
        s.sendall(f'PUT {remote} {mode:o} {uid} {gid} {len(data)}\n'.encode())
        s.sendall(data)
        print(check(readline(s)), remote)


def get(remote, local):
    with connect() as s:
        s.settimeout(120)
        s.sendall(f'GET {remote}\n'.encode())
        size = int(check(readline(s)).split()[1])
        buf = bytearray()
        while len(buf) < size:
            chunk = s.recv(min(65536, size - len(buf)))
            if not chunk:
                sys.exit(f'short read: {len(buf)} of {size} bytes')
            buf += chunk
    open(local, 'wb').write(buf)
    print(f'{remote}: {size} bytes -> {local}')


def simple(cmd, remote):
    with connect() as s:
        s.settimeout(60)
        s.sendall(f'{cmd} {remote}\n'.encode())
        check(readline(s))
        if cmd != 'LS':
            print('OK')
            return
        while True:
            line = readline(s)
            if line in ('END', ''):
                break
            print(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['put', 'get', 'ls', 'mkdir', 'rm'])
    ap.add_argument('a')
    ap.add_argument('b', nargs='?')
    ap.add_argument('--mode', type=lambda v: int(v, 8))
    ap.add_argument('--owner', default='0:0')
    a = ap.parse_args()
    if a.cmd == 'put':
        put(a.a, a.b, a.mode, a.owner)
    elif a.cmd == 'get':
        get(a.a, a.b)
    else:
        simple(a.cmd.upper(), a.a)


if __name__ == '__main__':
    main()
