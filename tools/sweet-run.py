#!/usr/bin/env python3
"""One hands-free test round on jasmine: phone -> fastboot -> IMAGE -> live log.

    sweet-run.py IMAGE LOG [--secs N] [--grep TEXT]

1. If the phone is not in fastboot, ask the running iOS kernel to reboot over
   the USB Ethernet command port (j0022; every reboot ends in fastboot) and
   wait for the fastboot device.
2. `fastboot boot IMAGE`.
3. Record the live console log (j0021, port 5140) to LOG for N seconds
   (default 90) after it connects; --grep prints only lines containing TEXT.

Needs a phone running a j0022+ kernel or sitting in fastboot. A hung boot
still needs the buttons (power + volume down).
"""
import argparse
import os
import socket
import subprocess
import sys
import time

HOSTS = ('192.168.7.2', '169.254.7.2')
HERE = os.path.dirname(os.path.abspath(__file__))


def in_fastboot():
    r = subprocess.run(['fastboot', 'devices'], capture_output=True, text=True)
    return 'fastboot' in r.stdout


def command(cmd):
    for host in HOSTS:
        try:
            with socket.create_connection((host, 5141), timeout=3) as s:
                s.sendall(cmd.encode() + b'\n')
                s.settimeout(5)
                return s.recv(256).decode(errors='replace').strip()
        except OSError:
            continue
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image')
    ap.add_argument('log')
    ap.add_argument('--secs', type=float, default=90)
    ap.add_argument('--grep')
    a = ap.parse_args()

    if not in_fastboot():
        answer = command('reboot')
        print(f'# reboot over the command port: {answer}', file=sys.stderr)
        if answer is None:
            sys.exit('phone neither in fastboot nor answering on the command port')
        deadline = time.time() + 90
        while not in_fastboot():
            if time.time() > deadline:
                sys.exit('no fastboot device 90 s after the reboot command')
            time.sleep(2)
    subprocess.run(['fastboot', 'boot', a.image], check=True)
    print(f'# booted {a.image} at {time.strftime("%H:%M:%S")}', file=sys.stderr)
    args = [sys.executable, os.path.join(HERE, 'sweet-netlog.py'), a.log, '--wait', '180', '--for', str(a.secs)]
    if a.grep is None:
        sys.exit(subprocess.run(args).returncode)
    p = subprocess.Popen(args, stdout=subprocess.PIPE)
    for line in p.stdout:
        if a.grep.encode() in line:
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
    sys.exit(p.wait())


if __name__ == '__main__':
    main()
