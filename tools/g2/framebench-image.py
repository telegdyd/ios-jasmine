#!/usr/bin/env python3
"""Package a temporary framebench image, preserving the baseline shim/ADT/args.
Only creates local files; never calls fastboot or accesses a device.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys


def split_v0(blob):
    if len(blob) < 1632 or blob[:8] != b'ANDROID!':
        raise ValueError('not an Android boot image')
    ks, ka, rs, ra, ss, sa, ta, page, version, osv = struct.unpack_from('<10I', blob, 8)
    if version != 0 or page < 2048 or page & (page - 1):
        raise ValueError('requires a baseline boot-header-v0 image with a valid page size')
    rounded = lambda n: (n + page - 1) // page * page
    if len(blob) != page + rounded(ks) + rounded(rs) + rounded(ss):
        raise ValueError('truncated image or unsupported trailing footer')
    rd = page + rounded(ks)
    second = rd + rounded(rs)
    return blob[:page], blob[page:page+ks], blob[rd:rd+rs], blob[second:second+ss], page


def repack_v0(baseline, payload):
    header, shim, old_payload, second, page = split_v0(baseline)
    header = bytearray(header)
    struct.pack_into('<I', header, 16, len(payload))
    digest = hashlib.sha1()
    for data in (shim, payload, second):
        digest.update(data)
        digest.update(struct.pack('<I', len(data)))
    header[576:608] = digest.digest() + bytes(12)
    pad = lambda data: data + bytes((-len(data)) % page)
    return bytes(header) + pad(shim) + pad(payload) + pad(second)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kernel', type=Path, required=True)
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    import prof
    _, symbols = prof.macho_syms(str(a.kernel))
    names = {name for address, name in symbols}
    for symbol in ('event', 'blob', 'enabled', 'alloc'):
        if '_sweet_bench_' + symbol not in names:
            raise SystemExit(f'kernel is missing framebench symbol: {symbol}')
    original = a.baseline.read_bytes()
    _, _, old, _, _ = split_v0(original)
    if old[:8] != b'SWEETXNU' or len(old) < 680:
        raise SystemExit('baseline image does not contain a SWEETXNU payload')
    offset, size = struct.unpack_from('<QQ', old, 0x20)
    if offset < 680 or offset + size > len(old):
        raise SystemExit('invalid baseline ADT extent')
    args = old[0x48:0x2a8].split(b'\0')[0].decode('ascii')
    if 'rd=ufsroot0' not in args or 'sweetfb_sync=1' not in args:
        raise SystemExit('expected an existing synchronized iOS device baseline')
    a.out.parent.mkdir(parents=True, exist_ok=True)
    adt = a.out.with_suffix('.adt')
    payload_path = a.out.with_suffix('.payload.bin')
    manifest_path = a.out.with_suffix('.json')
    for path in (a.out, adt, payload_path, manifest_path):
        if path.exists():
            raise SystemExit(f'refusing to overwrite {path}')
    adt.write_bytes(old[offset:offset+size])
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import mkpayload
    payload, info = mkpayload.build(str(a.kernel), str(adt), args)
    payload_path.write_bytes(payload)
    image = repack_v0(original, payload)
    header, shim, extracted, second, page = split_v0(image)
    assert extracted == payload
    assert split_v0(original)[1] == shim
    new_offset, new_size = struct.unpack_from('<QQ', payload, 0x20)
    assert payload[new_offset:new_offset+new_size] == adt.read_bytes()
    assert payload[0x48:0x2a8].split(b'\0')[0].decode() == args
    a.out.write_bytes(image)
    record = dict(kernel=str(a.kernel.resolve()), kernel_sha256=hashlib.sha256(a.kernel.read_bytes()).hexdigest(),
        baseline=str(a.baseline.resolve()), baseline_sha256=hashlib.sha256(original).hexdigest(),
        image=str(a.out.resolve()), image_sha256=hashlib.sha256(image).hexdigest(),
        payload_sha256=hashlib.sha256(payload).hexdigest(), adt_sha256=hashlib.sha256(adt.read_bytes()).hexdigest(),
        cmdline=args, verification='exact baseline shim, ADT and command line; payload round-trip matches',
        build_info=info, device_access=False)
    manifest_path.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
