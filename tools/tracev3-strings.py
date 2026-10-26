#!/usr/bin/env python3
"""Printable strings of a tracev3 file, chunk by chunk (LZ4 'bv41' chunksets decompressed).

    tracev3-strings.py FILE [MIN]

No format strings (they live in uuidtext / the shared cache): what comes out is the
argument text (%@, %s), the catalog's process/subsystem names and oversize payloads.
Each output line: chunkset number, offset in the decompressed data, the string.
"""
import re
import struct
import sys


def lz4_block(src, size):
    out = bytearray()
    i = 0
    while i < len(src):
        token = src[i]
        i += 1
        n = token >> 4
        if n == 15:
            while True:
                b = src[i]
                i += 1
                n += b
                if b != 255:
                    break
        out += src[i:i + n]
        i += n
        if i >= len(src):
            break
        off = src[i] | src[i + 1] << 8
        i += 2
        m = token & 15
        if m == 15:
            while True:
                b = src[i]
                i += 1
                m += b
                if b != 255:
                    break
        m += 4
        start = len(out) - off
        for k in range(m):
            out.append(out[start + k])
    return bytes(out[:size])


def bv41(data):
    out = bytearray()
    i = 0
    while i + 4 <= len(data):
        magic = data[i:i + 4]
        if magic == b'bv41':
            dsize, csize = struct.unpack_from('<II', data, i + 4)
            out += lz4_block(data[i + 12:i + 12 + csize], dsize)
            i += 12 + csize
        elif magic == b'bv4-':
            dsize, = struct.unpack_from('<I', data, i + 4)
            out += data[i + 8:i + 8 + dsize]
            i += 8 + dsize
        else:
            break
    return bytes(out)


def main():
    path = sys.argv[1]
    least = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    data = open(path, 'rb').read()
    pattern = re.compile(rb'[\x20-\x7e]{%d,}' % least)
    i, n = 0, 0
    while i + 16 <= len(data):
        tag, sub, size = struct.unpack_from('<IIQ', data, i)
        body = data[i + 16:i + 16 + size]
        if tag == 0x600d:
            body = bv41(body)
        for m in pattern.finditer(body):
            print(f'{n} {tag:x} {m.start():x} {m.group().decode()}')
        n += 1
        i += 16 + size
        i = (i + 7) & ~7


if __name__ == '__main__':
    main()
