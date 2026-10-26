#!/usr/bin/env python3
"""Package matched 4/8-core temporary images from a verified 4K kernel.

Reuses the accepted AMP hardware ADT and shim; never accesses the phone.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import adt
import mkpayload

spec = importlib.util.spec_from_file_location('framebench_image', Path(__file__).resolve().parents[1] / 'g2/framebench-image.py')
image = importlib.util.module_from_spec(spec)
spec.loader.exec_module(image)


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def prepare(kernel, baseline, out, revision, ci_run):
    if out.exists():
        raise ValueError('refusing to overwrite ' + str(out))
    blob = baseline.read_bytes()
    _, shim, old, second, _ = image.split_v0(blob)
    if old[:8] != b'SWEETXNU':
        raise ValueError('baseline has no SWEETXNU payload')
    offset, size = struct.unpack_from('<QQ', old, 0x20)
    dt = old[offset:offset + size]
    tree, end = adt.parse(dt)
    if end != size:
        raise ValueError('invalid ADT extent')
    cpus = next(n for n in tree.children if n.name == 'cpus').children
    if len(cpus) != 8:
        raise ValueError('expected the accepted eight-CPU AMP ADT')
    for i, node in enumerate(cpus):
        expected = (0x100 + i, ord('P')) if i < 4 else (i - 4, ord('E'))
        actual = tuple(struct.unpack('<I', node.prop(p))[0] for p in ('reg', 'cluster-type'))
        if actual != expected:
            raise ValueError('unexpected CPU order/type: ' + node.name)
    args = old[72:680].split(b'\0')[0].decode('ascii').split()
    for required in ('rd=ufsroot0', 'sweetgold=1747', 'gpumhz=588', 'sweetfb_sync=1'):
        if required not in args:
            raise ValueError('baseline missing ' + required)
    # Omit broad OSM probes and retain the normal manual Gold clock. DDR is
    # held at the current production setting in both variants, even if the
    # accepted Wi-Fi image inherited a baseline without a sweetddr argument.
    replace = {'cpus', 'sweetosm', 'osmwatch', 'sweetcmd', 'sweetddr'}
    common = [a for a in args if a.split('=')[0] not in replace]
    model = mkpayload.parse_macho(kernel.read_bytes())
    if model['cputype'] != 0x100000c or model['cpusub'] != 0:
        raise ValueError('expected a plain arm64 4K kernel')
    out.mkdir(parents=True)
    dtpath = out / 'hardware.adt'
    dtpath.write_bytes(dt)
    record = dict(revision=revision, ci_run=ci_run, kernel=str(kernel.resolve()),
                  kernel_sha256=digest(kernel.read_bytes()), baseline=str(baseline.resolve()),
                  baseline_sha256=digest(blob), adt_sha256=digest(dt),
                  checker_reference=b'SWEET CPUCHECK: boot reference ready' in kernel.read_bytes(),
                  four_k_provenance='caller must verify CI topaz_4k=1', images={})
    for count in (4, 8):
        cmdline = ' '.join(common + [f'cpus={count}', 'sweetcmd=1', 'sweetddr=1804'])
        if len(cmdline.encode()) >= mkpayload.BOOT_LINE_LENGTH:
            raise ValueError('boot arguments would be truncated')
        payload, _ = mkpayload.build(str(kernel), str(dtpath), cmdline)
        packed = image.repack_v0(blob, payload)
        _, checkshim, recovered, checksecond, _ = image.split_v0(packed)
        if (checkshim, recovered, checksecond) != (shim, payload, second):
            raise ValueError('image roundtrip mismatch')
        ao, az = struct.unpack_from('<QQ', recovered, 0x20)
        if recovered[ao:ao + az] != dt or recovered[72:680].split(b'\0')[0].decode() != cmdline:
            raise ValueError('payload ADT/arguments mismatch')
        path = out / f'cpu{count}.img'
        path.write_bytes(packed)
        record['images'][str(count)] = dict(path=str(path.resolve()), sha256=digest(packed), cmdline=cmdline)
    (out / 'manifest.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--ci-run', required=True, type=int)
    a = parser.parse_args()
    prepare(a.kernel, a.baseline, a.out, a.revision, a.ci_run)
