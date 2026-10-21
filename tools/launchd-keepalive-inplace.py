"""Repoint KeepAlive of the given jobs in launchd.plist (binary plist) to the
existing `false` object, in place (same length). Usage: bpatch.py IN OUT LABEL..."""
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
    """[(key string, value ref index, byte position of the value ref)]"""
    p = offs[i]
    m = b[p]
    assert m >> 4 == 0xd, hex(m)
    n, q = count(p, m & 0xf)
    out = []
    for k in range(n):
        kr = int.from_bytes(b[q + k * rsz: q + (k + 1) * rsz], 'big')
        vpos = q + (n + k) * rsz
        vr = int.from_bytes(b[vpos: vpos + rsz], 'big')
        out.append((string(kr), vr, vpos))
    return out


false = [i for i, o in enumerate(offs) if b[o] == 0x08]
assert false, 'no false object'
F = false[0]
daemons = dict(((k, v) for k, v, _ in dict_refs(top)))['LaunchDaemons']
done = []
for path, job, _ in dict_refs(daemons):
    refs = dict_refs(job)
    label = next((string(v) for k, v, _ in refs if k == 'Label'), None)
    if label in labels:
        for k, v, pos in refs:
            if k == 'KeepAlive':
                b[pos: pos + rsz] = F.to_bytes(rsz, 'big')
                done.append(label)
                print(f'{label}: KeepAlive ref {v} -> {F} (false) at byte {pos:#x}')
assert sorted(done) == sorted(labels), done
open(dst, 'wb').write(b)
p = plistlib.loads(bytes(b))
for k, j in p['LaunchDaemons'].items():
    if j.get('Label') in labels:
        print('check', j['Label'], 'KeepAlive =', j.get('KeepAlive'))
o = plistlib.loads(open(src, 'rb').read())
diff = [k for k in o['LaunchDaemons'] if o['LaunchDaemons'][k] != p['LaunchDaemons'][k]]
print('jobs changed:', len(diff), 'other top keys equal:', all(o[k] == p[k] for k in o if k != 'LaunchDaemons'))
