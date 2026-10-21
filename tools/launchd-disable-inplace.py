#!/usr/bin/env python3
"""Take launchd jobs out of service in a binary launchd.plist, in place.

  launchd-disable-inplace.py IN OUT LABEL...

For a root already on the phone, where rewriting the file would change its
size and the HFS+ metadata: the file keeps its length and only value
references change. Each job's MachServices and LaunchEvents point to an
existing empty dictionary, RunAtLoad and KeepAlive to the existing `false`,
so launchd never starts it (no boot launch, no on-demand launch, no
relaunch). Same effect as deleting the job (tools/sweet-root-tweaks.py does
that for new images). Checks the result with plistlib.

jasmine 2026-10-21: bluetoothd and fairplayd.H2 (no hardware) exited at
once and were relaunched on demand about every 10 s; KeepAlive alone did
not stop it.
"""
import plistlib, struct, sys

src, dst, labels = sys.argv[1], sys.argv[2], sys.argv[3:]
b = bytearray(open(src, 'rb').read())
assert b[:8] == b'bplist00'
osz, rsz, nobj, top, otab = struct.unpack('>6xBBQQQ', b[-32:])
offs = [int.from_bytes(b[otab + i * osz: otab + (i + 1) * osz], 'big') for i in range(nobj)]


def count(pos, low):
    if low != 0xf:
        return low, pos + 1
    m = b[pos + 1]
    assert m >> 4 == 0x1
    n = 1 << (m & 0xf)
    return int.from_bytes(b[pos + 2: pos + 2 + n], 'big'), pos + 2 + n


def string(i):
    p = offs[i]
    m = b[p]
    n, q = count(p, m & 0xf)
    if m >> 4 == 0x5:
        return b[q:q + n].decode('ascii')
    if m >> 4 == 0x6:
        return b[q:q + 2 * n].decode('utf-16-be')
    return None


def dict_refs(i):
    """[(key string, value ref, byte position of the value ref)]"""
    p = offs[i]
    m = b[p]
    assert m >> 4 == 0xd, hex(m)
    n, q = count(p, m & 0xf)
    out = []
    for k in range(n):
        kr = int.from_bytes(b[q + k * rsz: q + (k + 1) * rsz], 'big')
        vpos = q + (n + k) * rsz
        out.append((string(kr), int.from_bytes(b[vpos: vpos + rsz], 'big'), vpos))
    return out


FALSE = next(i for i, o in enumerate(offs) if b[o] == 0x08)
EMPTY = next(i for i, o in enumerate(offs) if b[o] == 0xd0)
target = {'MachServices': EMPTY, 'LaunchEvents': EMPTY, 'RunAtLoad': FALSE, 'KeepAlive': FALSE}
daemons = dict((k, v) for k, v, _ in dict_refs(top))['LaunchDaemons']
seen = set()
for path, job, _ in dict_refs(daemons):
    refs = dict_refs(job)
    label = next((string(v) for k, v, _ in refs if k == 'Label'), None)
    if label not in labels:
        continue
    seen.add(label)
    for k, v, pos in refs:
        if k in target and v != target[k]:
            b[pos: pos + rsz] = target[k].to_bytes(rsz, 'big')
            print(f'{label}: {k} ref {v} -> {target[k]} at byte {pos:#x}')
assert seen == set(labels), seen
open(dst, 'wb').write(b)

new, old = plistlib.loads(bytes(b)), plistlib.loads(open(src, 'rb').read())
for j in new['LaunchDaemons'].values():
    if j.get('Label') in labels:
        print('check', j['Label'], {k: j.get(k) for k in target})
changed = [k for k in old['LaunchDaemons'] if old['LaunchDaemons'][k] != new['LaunchDaemons'][k]]
print('jobs changed:', len(changed), '; rest equal:', all(old[k] == new[k] for k in old if k != 'LaunchDaemons'))
