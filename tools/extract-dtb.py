#!/usr/bin/env python3
"""Extract the DTB(s) appended to the kernel of an Android boot image (header v0-v2).

jasmine's ABL boots `Image.gz-dtb` kernels; the shim reuses the DTB from a boot.img
this ABL is known to accept (the Nura/pmOS one):

    python3 tools/extract-dtb.py ../images/boot.img dtb/jasmine.dtb
"""
import struct
import sys


def main():
    src, out = sys.argv[1], sys.argv[2]
    d = open(src, 'rb').read()
    if d[:8] != b'ANDROID!':
        sys.exit(f'{src}: not an Android boot image')
    ksz = struct.unpack('<I', d[8:12])[0]
    page = struct.unpack('<I', d[36:40])[0]
    kernel = d[page:page + ksz]
    dtbs, i = [], 0
    while (i := kernel.find(b'\xd0\x0d\xfe\xed', i)) >= 0:
        size = struct.unpack('>I', kernel[i + 4:i + 8])[0]
        if 0x100 < size < 0x400000 and i + size <= len(kernel):
            dtbs.append(kernel[i:i + size])
            i += size
        else:
            i += 4
    if not dtbs:
        sys.exit('no appended DTB found')
    open(out, 'wb').write(dtbs[0])
    print(f'{len(dtbs)} DTB(s) found, wrote the first ({len(dtbs[0])} bytes) to {out}')


if __name__ == '__main__':
    main()
