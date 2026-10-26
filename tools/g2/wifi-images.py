#!/usr/bin/env python3
"""Prepare default, diagnostic and radio-off temporary boot images offline.

Reuse the verified j99 shim and hardware ADT. No device access or flashing.
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
import prof

spec = importlib.util.spec_from_file_location('framebench_image', Path(__file__).with_name('framebench-image.py'))
image = importlib.util.module_from_spec(spec)
spec.loader.exec_module(image)


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def prepare(kernel, baseline, out, revision, ci_run):
    if out.exists():
        raise ValueError(f'refusing to overwrite {out}')
    blob = baseline.read_bytes()
    header, shim, old, second, page = image.split_v0(blob)
    if old[:8] != b'SWEETXNU':
        raise ValueError('baseline has no SWEETXNU payload')
    offset, size = struct.unpack_from('<QQ', old, 0x20)
    if offset < 680 or offset + size > len(old):
        raise ValueError('invalid ADT extent')
    tree, end = adt.parse(old[offset:offset+size])
    if end != size:
        raise ValueError('unexpected ADT trailing data')
    armio = next(n for n in tree.children if n.name == 'arm-io')
    if not any(n.name == 'wlan' for n in armio.children):
        raise ValueError('expected a verified Wi-Fi baseline with a wlan node')
    args = old[72:680].split(b'\0')[0].decode('ascii')
    if 'rd=ufsroot0' not in args or 'sweetfb_sync=1' not in args:
        raise ValueError('expected synchronized iOS baseline')
    _, symbols = prof.macho_syms(str(kernel))
    names = {name for _, name in symbols}
    for name in ('_sweet_bench_event', '_sweet_bench_blob', '__Z17sweet_surface_pinP12SweetSurface',
                 '__Z19sweet_surface_unpinP12SweetSurface', '_sweet_surface_pinned_note',
                 '_topaz_modem_init', '_topaz_modem_stop'):
        if name not in names:
            raise ValueError('missing integration symbol ' + name)
    model = mkpayload.parse_macho(kernel.read_bytes())
    if model['cputype'] != 0x100000c or model['cpusub'] != 0:
        raise ValueError('expected plain arm64 kernel (no arm64e/PAC)')
    remove = {'modem', 'wifi', 'modem_delay', 'wifi_diag'}
    common = ' '.join(a for a in args.split() if a.split('=')[0] not in remove)
    out.mkdir(parents=True)
    record = {'revision': revision, 'ci_run': ci_run, 'kernel': str(kernel.resolve()),
              'kernel_sha256': digest(kernel.read_bytes()), 'baseline': str(baseline.resolve()),
              'baseline_sha256': digest(blob), 'device_access': False, 'images': {}}
    for variant, extra in [('default', ''), ('diagnostic', ' wifi_diag=1'), ('off', ' modem=0 wifi=0')]:
        # Parse afresh so the off variant cannot modify either Wi-Fi tree.
        current, _ = adt.parse(old[offset:offset+size])
        if variant == 'off':
            bus = next(n for n in current.children if n.name == 'arm-io')
            bus.children = [n for n in bus.children if n.name != 'wlan']
        dt = adt.serialize(current)
        if variant != 'off' and dt != old[offset:offset+size]:
            raise ValueError('Wi-Fi ADT changed during serialization')
        cmdline = common + extra
        if len(cmdline.encode()) >= mkpayload.BOOT_LINE_LENGTH:
            raise ValueError('boot arguments would be truncated')
        dtpath = out / (variant + '.adt')
        dtpath.write_bytes(dt)
        payload, info = mkpayload.build(str(kernel), str(dtpath), cmdline)
        packed = image.repack_v0(blob, payload)
        _, newshim, recovered, newsecond, _ = image.split_v0(packed)
        assert newshim == shim and newsecond == second and recovered == payload
        ao, az = struct.unpack_from('<QQ', recovered, 0x20)
        assert recovered[ao:ao+az] == dt
        assert recovered[72:680].split(b'\0')[0].decode() == cmdline
        path = out / ('wifi-' + variant + '.img')
        path.write_bytes(packed)
        record['images'][variant] = {'path': str(path.resolve()), 'sha256': digest(packed),
            'adt_sha256': digest(dt), 'cmdline': cmdline, 'build_info': info}
    (out / 'manifest.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--ci-run', required=True)
    a = parser.parse_args()
    prepare(a.kernel, a.baseline, a.out, a.revision, a.ci_run)
