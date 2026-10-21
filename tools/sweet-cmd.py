#!/usr/bin/env python3
"""Send a command to the phone's kernel over USB Ethernet (j0022, bsd/dev/sweet_usb.c).

    sweet-cmd.py reboot      clean reboot; on jasmine it ends in fastboot

TCP port 5141 at 192.168.7.2 (or the link-local 169.254.7.2), one line per
connection; prints the phone's answer.
"""
import socket
import sys

HOSTS = ('192.168.7.2', '169.254.7.2')
PORT = 5141


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    for host in HOSTS:
        try:
            with socket.create_connection((host, PORT), timeout=3) as s:
                s.sendall(sys.argv[1].encode() + b'\n')
                s.settimeout(5)
                print(s.recv(256).decode(errors='replace').strip() or '(no answer)')
                return
        except OSError:
            continue
    sys.exit(f'no command port at {" or ".join(HOSTS)}:{PORT}')


if __name__ == '__main__':
    main()
