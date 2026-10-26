#!/usr/bin/env python3
"""Replay pinned Xcode 15 IIG output on supported macOS runners.

The xnu-8796 RPC ABI stays unchanged. All source headers and IIG definitions
must match the successful bootstrap build, except private SweetSurface.h,
which is not an IIG input. Generated Apple files remain artifacts, never git.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tarfile

EXPECTED_MANIFEST = '08a1ba9244a14654a2b12ccaeecf470b26e94b20396931590fda2e62e0aad0ee'
EXCLUDED = {'iokit/Kernel/arm/SweetSurface.h',
            # SDK copies for independent HFS/libpthread builds, outside IIG's
            # include search paths. Their contents vary with the runner SDK.
            'bsd/pthread/sweet_libpthread/TargetConditionals.h',
            'bsd/sweet_hfs/TargetConditionals.h'}
BOOTSTRAP_RUN = '40159794543'
BOOTSTRAP_SHA = '37f54b1650d31b29c503d8bee72bedd7300ad663'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def seed(archive, out):
    if out.exists():
        raise ValueError('refusing to overwrite cache ' + str(out))
    out.mkdir(parents=True)
    manifest = {'bootstrap_run': BOOTSTRAP_RUN, 'bootstrap_sha': BOOTSTRAP_SHA,
                'inputs': {}, 'outputs': {}}
    generated = {}
    with tarfile.open(archive, 'r|gz') as tar:
        for member in tar:
            if not member.isfile():
                continue
            name = member.name
            relative = name.removeprefix('xnu/')
            if name.startswith('xnu/') and relative not in EXCLUDED and (
                    relative.endswith(('.h', '.iig')) or relative == 'iokit/DriverKit/Makefile'):
                manifest['inputs'][relative] = sha(tar.extractfile(member).read())
            prefix = 'build/xnu.obj/DEVELOPMENT_ARM64_SWEET/iokit/DriverKit/'
            if name.startswith(prefix) and name.endswith(('.h', '.iig.cpp')):
                generated[name.removeprefix(prefix)] = tar.extractfile(member).read()
        definitions = sorted(n for n in manifest['inputs'] if n.endswith('.iig'))
        if len(definitions) != 17:
            raise ValueError(f'expected 17 IIG definitions, got {len(definitions)}')
        for definition in definitions:
            stem = Path(definition).stem
            for suffix in ('.h', '.iig.cpp'):
                name = stem + suffix
                data = generated[name]
                (out / name).write_bytes(data)
                manifest['outputs'][name] = sha(data)
    data = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()
    if sha(data) != EXPECTED_MANIFEST:
        raise ValueError('bootstrap buildtree does not match pinned IIG inputs/outputs')
    (out / 'manifest.json').write_bytes(data)
    print('IIG manifest SHA256', sha(data), 'inputs', len(manifest['inputs']), 'outputs', len(manifest['outputs']))


def validate(cache, source):
    data = (cache / 'manifest.json').read_bytes()
    if sha(data) != EXPECTED_MANIFEST:
        raise ValueError('legacy IIG manifest does not match the pinned bootstrap')
    manifest = json.loads(data)
    for name, expected in manifest['inputs'].items():
        path = source / name
        if not path.is_file() or sha(path.read_bytes().replace(b'\r\n', b'\n')) != expected:
            raise ValueError('legacy IIG source mismatch: ' + name)
    definitions = {str(p.relative_to(source)).replace('\\', '/') for p in source.rglob('*.iig')}
    if definitions != {n for n in manifest['inputs'] if n.endswith('.iig')}:
        raise ValueError('IIG definition set changed')
    for name, expected in manifest['outputs'].items():
        if sha((cache / name).read_bytes()) != expected:
            raise ValueError('legacy IIG output mismatch: ' + name)
    return manifest


def replay(cache, args):
    options, flags = args[:args.index('--')], args[args.index('--')+1:]
    if len(options) != 8:
        raise ValueError('unexpected IIG generator options')
    opts = dict(zip(options[::2], options[1::2]))
    if set(opts) != {'--def', '--header', '--impl', '--framework-name'} or opts['--framework-name'] != 'DriverKit':
        raise ValueError('unsupported IIG output/framework options')
    defines = {arg for arg in flags if arg.startswith(('-D', '-U'))}
    if defines != {'-D__IIG=1', '-DDRIVERKIT_PRIVATE=1', '-DPRIVATE_WIFI_ONLY=1', '-DXNU_PLATFORM_MacOSX'}:
        raise ValueError('IIG preprocessor configuration changed: ' + repr(defines))
    definition = Path(opts['--def']).resolve()
    source = definition.parents[2]
    manifest = validate(cache, source)
    relative = str(definition.relative_to(source)).replace('\\', '/')
    if relative not in manifest['inputs'] or not relative.startswith('iokit/DriverKit/'):
        raise ValueError('unexpected IIG definition')
    for option, suffix in [('--header', '.h'), ('--impl', '.iig.cpp')]:
        name = definition.stem + suffix
        if Path(opts[option]).name != name:
            raise ValueError('unexpected IIG destination')
        shutil.copyfile(cache / name, opts[option])
    print('legacy IIG verified/replayed:', definition.name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    p = subs.add_parser('seed')
    p.add_argument('archive', type=Path)
    p.add_argument('out', type=Path)
    p = subs.add_parser('validate')
    p.add_argument('cache', type=Path)
    p.add_argument('source', type=Path)
    p = subs.add_parser('replay')
    p.add_argument('--cache', type=Path, required=True)
    p.add_argument('arguments', nargs=argparse.REMAINDER)
    a = parser.parse_args()
    if a.command == 'seed':
        seed(a.archive, a.out)
    elif a.command == 'validate':
        validate(a.cache, a.source)
        print('Pinned legacy IIG inputs and outputs PASS')
    else:
        replay(a.cache, a.arguments[1:] if a.arguments[:1] == ['--'] else a.arguments)
