#!/usr/bin/env python3
"""Poll `batt` over Wi-Fi (or USB) every N seconds and log the answers:
    wifiwatch.py OUT.txt [HOST=192.168.1.186] [SECS=20] [DURATION=1800]"""
import socket, sys, time
out = sys.argv[1]
host = sys.argv[2] if len(sys.argv) > 2 else '192.168.1.186'
step = float(sys.argv[3]) if len(sys.argv) > 3 else 20
dur = float(sys.argv[4]) if len(sys.argv) > 4 else 1800
t0 = time.time()
with open(out, 'a') as f:
    while time.time() - t0 < dur:
        for h in (host, '192.168.7.2'):
            try:
                with socket.create_connection((h, 5141), timeout=3) as s:
                    s.sendall(b'batt\n'); s.settimeout(3)
                    r = s.recv(4096).decode(errors='replace').strip()
                line = f'{time.strftime("%H:%M:%S")} {h} {r}'
                break
            except OSError as e:
                line = f'{time.strftime("%H:%M:%S")} {h} no answer ({e.__class__.__name__})'
        print(line, file=f, flush=True)
        time.sleep(step)
