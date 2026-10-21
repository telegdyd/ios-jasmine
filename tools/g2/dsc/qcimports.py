"""Which other images does QuartzCore call (bl/b through stub islands), and from which QuartzCore functions."""
import os, re, sys, struct, bisect, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsc

OUT = os.path.expanduser('~/ios-work/gl/out2')
QCS = os.path.expanduser('~/ios-work/gl/out/qc.s')

c = dsc.Cache()

# image list from the main cache header (imagesTextOffset 0x88 / count 0x90)
with open(dsc.DSC, 'rb') as f:
    h = f.read(0x200)
    toff, tcnt = struct.unpack_from('<QQ', h, 0x88)
    f.seek(toff)
    raw = f.read(tcnt * 32)
    images = []
    for i in range(tcnt):
        uuid, load, tsize, poff = struct.unpack_from('<16sQII', raw, i * 32)
        f.seek(poff)
        path = f.read(256).split(b'\0')[0].decode()
        images.append((load, tsize, path))
images.sort()
starts = [i[0] for i in images]


def image_of(va):
    k = bisect.bisect_right(starts, va) - 1
    if k >= 0 and va < images[k][0] + images[k][1]:
        return images[k][2]
    return None


def load_syms(path):
    d = {}
    if not os.path.exists(path):
        return d
    for line in open(path, errors='replace'):
        m = re.match(r'(0x[0-9a-f]+):\s+\(__TEXT,__text\)\s+\S.*?\t(.+?)\t?$', line)
        if m:
            d[int(m.group(1), 16)] = m.group(2).strip()
    return d


qsyms = load_syms(f'{OUT}/qc-symbols.txt')
qstarts = sorted(qsyms)
other = {}
for fn in os.listdir(OUT):
    if fn.endswith('-symbols.txt') and fn != 'qc-symbols.txt':
        other.update(load_syms(f'{OUT}/{fn}'))


def qc_func(va):
    k = bisect.bisect_right(qstarts, va) - 1
    return qsyms[qstarts[k]] if k >= 0 else '?'


qc_img = image_of(0x188285f84)
calls = collections.defaultdict(set)  # target name -> set of caller names
unres = collections.Counter()
stubcache = {}
pat = re.compile(r'^(0x[0-9a-f]+):\s+(?:[0-9a-f]{2} ){4}\s*(bl|b)\s+(0x[0-9a-f]+)\s*$')
for line in open(QCS):
    m = pat.match(line)
    if not m:
        continue
    pc, t = int(m.group(1), 16), int(m.group(3), 16)
    if image_of(t) == qc_img:
        continue
    if t not in stubcache:
        r = dsc.resolve_stub(c, t)
        tgt = None
        if r[0] == 'direct':
            tgt = r[1]
        elif r[0] == 'got':
            tgt = r[2] & 0xfffffffff  # low 36 bits: vmaddr offset or address in chained format
            if tgt < 0x180000000:
                tgt += 0x180000000
        stubcache[t] = (r, tgt)
    r, tgt = stubcache[t]
    if tgt is None:
        unres[(t, r[0])] += 1
        continue
    img = image_of(tgt) or '?'
    name = other.get(tgt, hex(tgt))
    calls[(img, name)].add(qc_func(pc))

byimg = collections.Counter(k[0] for k in calls)
for img, n in byimg.most_common(60):
    print(f'{n:5d} {img}')
print('unresolved', len(unres), list(unres.items())[:10])
with open(f'{OUT}/qc-imports.txt', 'w') as f:
    for (img, name), callers in sorted(calls.items()):
        f.write(f'{img}\t{name}\t{len(callers)}\t' + ' | '.join(sorted(callers)) + '\n')
