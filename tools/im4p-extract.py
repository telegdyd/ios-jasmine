#!/usr/bin/env python3
"""Extract the payload of an IM4P container (e.g. DeviceTree.d22ap.im4p from an IPSW).

    im4p-extract.py DeviceTree.d22ap.im4p research/ipsw-x/d22ap.adt

IM4P is DER: SEQUENCE { IA5String "IM4P", IA5String type, IA5String description,
OCTET STRING payload, ... }. An LZFSE payload ("bvx2") is decompressed with Apple's
lzfse command line tool, which must be on PATH. Stands in for `ipsw img4 im4p extract`.
"""
import os
import subprocess
import sys
import tempfile


def der(buf, pos):
    """(tag, content start, content end) of the DER element at pos."""
    tag = buf[pos]
    n = buf[pos + 1]
    pos += 2
    if n & 0x80:
        k = n & 0x7f
        n = int.from_bytes(buf[pos:pos + k], 'big')
        pos += k
    return tag, pos, pos + n


def main():
    src, out = sys.argv[1], sys.argv[2]
    buf = open(src, 'rb').read()
    tag, pos, end = der(buf, 0)
    if tag != 0x30:
        sys.exit('not a DER SEQUENCE')
    fields = []
    while pos < end:
        t, s, e = der(buf, pos)
        fields.append((t, buf[s:e]))
        pos = e
    if len(fields) < 4 or fields[0] != (0x16, b'IM4P') or fields[3][0] != 0x04:
        sys.exit('not an IM4P (expected "IM4P", type, description, payload)')
    payload = fields[3][1]
    print(f'type {fields[1][1].decode()}, {fields[2][1].decode()!r}, payload {len(payload)} bytes')
    if payload[:4] == b'bvx2':
        with tempfile.TemporaryDirectory() as d:
            raw = os.path.join(d, 'payload.lzfse')
            open(raw, 'wb').write(payload)
            subprocess.run(['lzfse', '-decode', '-i', raw, '-o', out], check=True)
    else:
        open(out, 'wb').write(payload)
    print(f'{out}: {os.path.getsize(out)} bytes')


if __name__ == '__main__':
    main()
