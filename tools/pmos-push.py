#!/usr/bin/env python3
"""Copy a local file to the postmarketOS initramfs debug shell (see pmos-shell.py).

    pmos-push.py local-file /remote/path

The shell has no file transfer: the file goes over as base64 lines appended to
a temporary file (short lines, so the tty line limit never bites), is decoded
on the phone and checked with sha256sum.
"""
import base64
import hashlib
import importlib.util
import pathlib
import sys

spec = importlib.util.spec_from_file_location('pmos_shell', pathlib.Path(__file__).with_name('pmos-shell.py'))
shell = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shell)

CHUNK = 3000


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    data = pathlib.Path(sys.argv[1]).read_bytes()
    dst = sys.argv[2]
    tmp = f'{dst}.b64'
    text = base64.b64encode(data).decode()
    shell.run(f'rm -f {tmp}')
    for i in range(0, len(text), CHUNK):
        shell.run(f'echo {text[i:i + CHUNK]} >> {tmp}')
    out = shell.run(f'base64 -d {tmp} > {dst} && rm {tmp} && sha256sum {dst}').decode()
    want = hashlib.sha256(data).hexdigest()
    if want not in out:
        sys.exit(f'checksum mismatch for {dst}: {out.strip()}')
    print(f'{dst}: {len(data)} bytes, sha256 ok')


if __name__ == '__main__':
    main()
