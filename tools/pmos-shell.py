#!/usr/bin/env python3
"""Run a command in the postmarketOS initramfs debug shell (telnet, port 23).

jasmine's recovery path without a recovery partition: `fastboot boot` the Nura
(postmarketOS) boot image with `pmos.debug-shell` on its command line
(shim/out/nura-debugshell.img); it stops in the initramfs with busybox telnetd
on the USB network. Nothing is mounted, so the iOS userdata is untouched.

    pmos-shell.py 'ls /dev/mmcblk*'                    # print the output
    pmos-shell.py --raw 'dd if=/dev/mmcblk0p69 ...' > file   # binary stdout

--raw base64-encodes on the phone (busybox base64) and decodes here, so
terminal handling cannot corrupt the bytes.
"""
import base64
import socket
import sys

HOST, PORT = '172.16.42.1', 23
IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240
END = '__PMOS_SHELL_DONE__'


def strip_telnet(sock, data):
    """Refuse every option the server offers; return the plain bytes."""
    out, i = bytearray(), 0
    while i < len(data):
        b = data[i]
        if b != IAC or i + 1 >= len(data):
            out.append(b)
            i += 1
            continue
        cmd = data[i + 1]
        if cmd in (DO, DONT, WILL, WONT) and i + 2 < len(data):
            opt = data[i + 2]
            if cmd == DO:
                sock.sendall(bytes([IAC, WONT, opt]))
            elif cmd == WILL:
                sock.sendall(bytes([IAC, DONT, opt]))
            i += 3
        elif cmd == SB:
            j = data.find(bytes([IAC, SE]), i)
            i = len(data) if j < 0 else j + 2
        elif cmd == IAC:
            out.append(IAC)
            i += 2
        else:
            i += 2
    return bytes(out)


def run(command, raw=False, timeout=600):
    sock = socket.create_connection((HOST, PORT), timeout=timeout)
    if raw:
        command = f'{command} | base64'
    # The terminal echoes what we send: switch echo off first, and let the
    # shell assemble the markers (printf), so they never appear literally in
    # an echoed command line.
    sock.sendall(b'stty -echo 2>/dev/null\n')
    half = len(END) // 2

    def mark(n):
        return f"printf '%s%s{n}\\n' '{END[:half]}' '{END[half:]}'"

    sock.sendall(f'{mark(0)}; {command}; echo; {mark(1)}\n'.encode())
    buf = b''
    while True:
        chunk = sock.recv(1 << 16)
        if not chunk:
            break
        buf += strip_telnet(sock, chunk)
        if f'{END}1'.encode() in buf:
            break
    sock.close()
    text = buf.split(f'{END}0'.encode(), 1)[-1].split(f'{END}1'.encode(), 1)[0]
    text = text.replace(b'\r\n', b'\n').strip(b'\n')
    if raw:
        return base64.b64decode(b''.join(text.split()))
    return text + b'\n'


def main():
    args = sys.argv[1:]
    raw = args[:1] == ['--raw']
    if raw:
        args = args[1:]
    if len(args) != 1:
        sys.exit(__doc__)
    out = run(args[0], raw=raw)
    sys.stdout.buffer.write(out)


if __name__ == '__main__':
    main()
