#!/usr/bin/env python3
"""sweet_shot's raw file ("SHOT w h\\n" + BGRA rows) to PNG, no libraries needed.

    shot2png.py IN.raw OUT.png
"""
import struct
import sys
import zlib


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)


def main():
    raw = open(sys.argv[1], 'rb').read()
    head, _, px = raw.partition(b'\n')
    _, w, h = head.split()
    w, h = int(w), int(h)
    rows = []
    for y in range(h):
        r = px[y * w * 4:(y + 1) * w * 4]
        rgb = bytearray(w * 3)
        rgb[0::3] = r[2::4]
        rgb[1::3] = r[1::4]
        rgb[2::3] = r[0::4]
        rows.append(b'\0' + bytes(rgb))
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(b''.join(rows), 6)) + chunk(b'IEND', b'')
    open(sys.argv[2], 'wb').write(png)


if __name__ == '__main__':
    main()
