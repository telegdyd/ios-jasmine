#!/usr/bin/env python3
"""Run a program on the phone's iOS userland through sweetd (ios/sweetd.c, TCP 5143).

    sweet-sh.py [--timeout S] /absolute/program [args...]

Prints the program's output (stdout and stderr merged) as it comes and exits
with its status (128 + signal when it was killed). From Git Bash, set
MSYS_NO_PATHCONV=1 so absolute phone paths are not rewritten.
"""
import socket
import sys

HOSTS = ('192.168.7.2', '169.254.7.2')
PORT = 5143
END = b'__SWEETD_END__'


def main():
    args = sys.argv[1:]
    timeout = 60
    if args[:1] == ['--timeout']:
        timeout = int(args[1])
        args = args[2:]
    if not args or not args[0].startswith('/'):
        sys.exit(__doc__)
    for host in HOSTS:
        try:
            s = socket.create_connection((host, PORT), timeout=5)
            break
        except OSError:
            s = None
    if s is None:
        sys.exit(f'no sweetd at {" or ".join(HOSTS)}:{PORT}')
    s.settimeout(timeout + 30)
    s.sendall(f'RUN {timeout} {len(args)}\n'.encode() + b''.join(a.encode() + b'\n' for a in args))
    buf = b''
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
        # print everything that cannot be the start of the end marker
        cut = buf.rfind(b'\n' + END)
        keep = len(buf) - len(END) - 16 if cut < 0 else cut
        if keep > 0:
            sys.stdout.buffer.write(buf[:keep])
            sys.stdout.buffer.flush()
            buf = buf[keep:]
    cut = buf.rfind(b'\n' + END)
    if cut < 0:
        sys.stdout.buffer.write(buf)
        sys.exit('\n(connection closed without a status)')
    sys.stdout.buffer.write(buf[:cut] + b'\n')
    status = int(buf[cut + len(END) + 1:].split()[0])
    sys.exit(status if status >= 0 else 128 - status)


if __name__ == '__main__':
    main()
