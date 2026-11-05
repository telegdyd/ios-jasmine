#!/usr/bin/env python3
"""Send command-port lines (j0114+ port 5141) and print the replies:
    port.py "cmd" ["cmd" ...]      a bare number N as an argument sleeps N seconds
"""
import socket
import sys
import time

HOSTS = ('192.168.7.2', '169.254.7.2')


def one(line, timeout=4):
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
    return '(phone not reachable)'


for a in sys.argv[1:]:
    if a.replace('.', '', 1).isdigit():
        time.sleep(float(a))
        continue
    print('>>', a)
    print(one(a), flush=True)
