#!/usr/bin/env python3
"""Sampling profile of the UI (kernel j0057, `prof` on the USB command port).

    prof.py fetch OUT [--secs S] [--us US] [--census US] [--tasks backboardd,SpringBoard]
        (Windows, phone on USB) starts a profile, waits for it, saves OUT.bin (samples) and
        OUT.meta (slides, task / thread names, file mappings).
    prof.py report OUT [--kernel K] [--lib PATH...] [--pid-name backboardd] [--top N]
        (WSL: needs ipsw and c++filt) symbolicates and prints where the time goes.

Records (osfmk/arm64/sweet_prof.c): 8-byte words hdr, tid, pid | trap << 32, lr, event, then
nk kernel and nu user frames. hdr: us since start (0-31), cpu (32-39, 0xff = census), kind
(40-43: 0 on CPU in user mode, 1 on CPU in the kernel, 2 waiting, 3 runnable), nk (44-51),
nu (52-59). On-CPU samples come every --us per busy CPU, census records every --census per
waiting/runnable thread of the --tasks that ran in the last 500 ms.

Shared-cache addresses are unslid with the meta's slide and named with `ipsw dyld macho
IMAGE --symbols` (cached in ~/ios-work/prof-syms); the kernel with its Mach-O symbol table
(xnu/out-jasmine-*/kernel.development.sweet); other images (libsweetca.dylib) from --lib
Mach-O files, placed by the meta's file mappings.
"""
import argparse
import bisect
import collections
import os
import re
import socket
import struct
import subprocess
import sys
import time

HOSTS = ('192.168.7.2', '169.254.7.2')
PORT = 5141
DSC = os.path.expanduser('~/ios-work/gl/dsc/dyld_shared_cache_arm64')
IPSW = os.path.expanduser('~/ios-work/tools/ipsw-3.1.739/x/ipsw')
SYMDIR = os.path.expanduser('~/ios-work/prof-syms')
KIND = {0: 'user', 1: 'kernel', 2: 'wait', 3: 'runnable'}


def cmd(line, timeout=20):
    for host in HOSTS:
        try:
            with socket.create_connection((host, PORT), timeout=3) as s:
                s.sendall(line.encode() + b'\n')
                s.settimeout(timeout)
                out = b''
                while True:
                    b = s.recv(65536)
                    if not b:
                        break
                    out += b
                return out.decode(errors='replace')
        except OSError:
            continue
    return None


def fetch(a):
    r = cmd(f'prof start {a.secs} {a.us} {a.census} {a.tasks}')
    print(time.strftime('%H:%M:%S'), (r or 'no command port').strip(), flush=True)
    if not r or 'started' not in r:
        sys.exit(1)
    time.sleep(a.secs + 1)
    while True:
        st = cmd('prof stat') or ''
        if 'idle' in st:
            break
        time.sleep(1)
    print(st.strip(), flush=True)
    data = bytearray()
    while True:
        r = (cmd(f'prof get {len(data)}') or '').strip()
        if not r or r.startswith('prof:'):
            break
        data += bytes.fromhex(r)
    meta = ''
    while True:
        r = cmd(f'prof meta {len(meta.encode())}') or ''
        if not r:
            break
        meta += r
        if meta.rstrip().endswith('end'):
            break
    open(a.out + '.bin', 'wb').write(data)
    open(a.out + '.meta', 'w').write(meta)
    print(f'{len(data)} bytes of samples, {len(meta)} of meta -> {a.out}.bin/.meta')


def records(data):
    o = 0
    n = len(data)
    while o + 40 <= n:
        hdr, tid, pt, lr, ev = struct.unpack_from('<5Q', data, o)
        nk = (hdr >> 44) & 0xff
        nu = (hdr >> 52) & 0xff
        if o + 40 + 8 * (nk + nu) > n:
            break
        fr = struct.unpack_from(f'<{nk + nu}Q', data, o + 40)
        o += 40 + 8 * (nk + nu)
        if hdr == 0 and tid == 0:
            break
        trap = (pt >> 32) & 0xffffffff
        if trap & 0x80000000:
            trap -= 1 << 32
        yield dict(us=hdr & 0xffffffff, cpu=(hdr >> 32) & 0xff, kind=(hdr >> 40) & 0xf, tid=tid,
                   pid=struct.unpack('<i', struct.pack('<I', pt & 0xffffffff))[0], trap=trap, lr=lr,
                   event=ev & 0xffffffffffff, hint=(ev >> 48) & 0xff, pri=(ev >> 56) & 0xff,
                   k=fr[:nk], u=fr[nk:])


class Meta:
    def __init__(self, path):
        self.kslide = 0
        self.vals = {}
        self.tasks = {}
        self.threads = {}
        self.slide = {}
        self.mh = {}
        self.maps = collections.defaultdict(list)
        for line in open(path, errors='replace'):
            w = line.split()
            if not w:
                continue
            if w[0] == 'kslide':
                self.kslide = int(w[1], 16)
            elif w[0] in ('period_us', 'census_us', 'samples', 'bytes', 'dropped'):
                self.vals[w[0]] = int(w[1])
            elif w[0] == 'task':
                self.tasks[int(w[1])] = ' '.join(w[2:])
            elif w[0] == 'thread':
                self.threads[int(w[1])] = (int(w[2]), ' '.join(w[3:]))
            elif w[0] == 'slide':
                self.slide[int(w[1])] = int(w[2], 16)
                if len(w) > 4:
                    self.mh[int(w[1])] = int(w[4], 16)
            elif w[0] == 'map':
                self.maps[int(w[1])].append((int(w[2], 16), int(w[3], 16), int(w[4], 16), int(w[5], 16),
                                             ' '.join(w[6:])))


def demangle(names):
    names = list(names)
    try:
        r = subprocess.run(['c++filt', '-_'], input='\n'.join(names), capture_output=True, text=True)
        out = r.stdout.splitlines()
        if len(out) == len(names):
            return dict(zip(names, out))
    except OSError:
        pass
    return {n: n for n in names}


class SymTab:
    """sorted (addr, name) with a lookup"""

    def __init__(self, pairs):
        pairs = sorted(set(pairs))
        self.a = [p[0] for p in pairs]
        self.n = [p[1] for p in pairs]

    def find(self, addr):
        i = bisect.bisect_right(self.a, addr) - 1
        if i < 0:
            return None, 0
        return self.n[i], addr - self.a[i]


def macho_syms(path):
    """(text vmaddr, [(addr, name)]) of a thin arm64 Mach-O"""
    d = open(path, 'rb').read()
    magic, = struct.unpack_from('<I', d, 0)
    if magic == 0xbebafeca:                     # fat: take arm64
        n, = struct.unpack_from('>I', d, 4)
        for i in range(n):
            ct, cs, off, size, al = struct.unpack_from('>5I', d, 8 + 20 * i)
            if ct == 0x0100000c:
                d = d[off:off + size]
                break
    ncmds, = struct.unpack_from('<I', d, 16)
    o = 32
    text = 0
    syms = []
    for _ in range(ncmds):
        c, sz = struct.unpack_from('<II', d, o)
        if c == 0x19:                           # LC_SEGMENT_64
            name = d[o + 8:o + 24].rstrip(b'\0')
            if name == b'__TEXT':
                text, = struct.unpack_from('<Q', d, o + 24)
        elif c == 0x2:                          # LC_SYMTAB
            symoff, nsyms, stroff, strsize = struct.unpack_from('<4I', d, o + 8)
            for i in range(nsyms):
                strx, typ, sect, desc, val = struct.unpack_from('<IBBHQ', d, symoff + 16 * i)
                if typ & 0xe0 or (typ & 0x0e) != 0x0e or val == 0:   # stabs / not in a section
                    continue
                e = d.index(b'\0', stroff + strx)
                syms.append((val, d[stroff + strx:e].decode(errors='replace')))
        o += sz
    return text, syms


class Cache:
    def __init__(self, path=DSC):
        with open(path, 'rb') as f:
            h = f.read(0x200)
            ioff, icnt = struct.unpack_from('<II', h, 0x1c0)
            if icnt == 0:
                ioff, icnt = struct.unpack_from('<II', h, 0x18)
            f.seek(ioff)
            raw = f.read(32 * icnt)
            imgs = []
            for i in range(icnt):
                addr, _, _, poff, _ = struct.unpack_from('<QQQII', raw, 32 * i)
                f.seek(poff)
                p = f.read(256).split(b'\0')[0].decode()
                imgs.append((addr, p))
        imgs.sort()
        self.base = [a for a, _ in imgs]
        self.path = [p for _, p in imgs]
        self.lo, self.hi = self.base[0], self.base[-1] + 0x20000000
        self.tabs = {}

    def image(self, addr):
        i = bisect.bisect_right(self.base, addr) - 1
        return self.path[i] if i >= 0 else None

    def syms(self, img):
        if img in self.tabs:
            return self.tabs[img]
        os.makedirs(SYMDIR, exist_ok=True)
        fn = os.path.join(SYMDIR, os.path.basename(img) + '.txt')
        if not os.path.exists(fn):
            r = subprocess.run([IPSW, 'dyld', 'macho', DSC, os.path.basename(img), '--symbols', '--no-color'],
                               capture_output=True, text=True)
            open(fn, 'w').write(r.stdout)
        pairs = []
        for line in open(fn, errors='replace'):
            m = re.match(r'(0x[0-9a-f]+):\s+(?:\([^)]*\)\s+)?(?:\S+\t)?(.+)$', line.rstrip())
            if m:
                name = m.group(2).split('\t')[0].strip()
                if name:
                    pairs.append((int(m.group(1), 16), name))
        self.tabs[img] = SymTab(pairs)
        return self.tabs[img]


class Sym:
    def __init__(self, meta, kernel, libs):
        self.meta = meta
        self.cache = Cache()
        kt, ks = macho_syms(kernel)
        self.k = SymTab(ks)
        self.libs = {}
        for p in libs:
            t, s = macho_syms(p)
            self.libs[os.path.basename(p)] = (t, SymTab(s))
        self.memo = {}
        self.dem = {}

    def name(self, n):
        return self.dem.get(n, n)

    def kernel(self, a):
        key = ('k', a)
        if key not in self.memo:
            n, off = self.k.find(a - self.meta.kslide)
            self.memo[key] = ('kernel', n or hex(a))
        return self.memo[key]

    def user(self, pid, a):
        key = (pid, a)
        if key in self.memo:
            return self.memo[key]
        r = None
        slide = self.meta.slide.get(pid, 0)
        ua = a - slide
        if self.cache.lo <= ua < self.cache.hi:
            img = self.cache.image(ua)
            if img:
                n, off = self.cache.syms(img).find(ua)
                r = (os.path.basename(img), n or hex(ua))
        if r is None:
            for start, size, foff, prot, path in self.meta.maps.get(pid, []):
                if start <= a < start + size:
                    b = os.path.basename(path)
                    base = start - foff
                    if b in self.libs:
                        t, tab = self.libs[b]
                        n, off = tab.find(a - base + t)
                        r = (b, n or hex(a - base))
                    else:
                        r = (b, hex(a - base))
                    break
        if r is None:
            r = ('?', hex(a))
        self.memo[key] = r
        return r

    def finish(self):
        names = {v[1] for v in self.memo.values()}
        self.dem = demangle(names)


def short(s, n=90):
    return s if len(s) <= n else s[:n - 3] + '...'


def report(a):
    meta = Meta(a.out + '.meta')
    recs = list(records(open(a.out + '.bin', 'rb').read()))
    per = meta.vals.get('period_us', 1000) / 1000.0
    cen = meta.vals.get('census_us', 2000) / 1000.0
    secs = max((r['us'] for r in recs), default=0) / 1e6 or 1
    sym = Sym(meta, a.kernel, a.lib)

    def frames(r):
        """symbolicated (image, name) list, leaf first: kernel frames, then user frames"""
        out = [sym.kernel(x) for x in r['k']]
        for i, x in enumerate(r['u']):
            out.append(sym.user(r['pid'], x if i == 0 else x - 1))
        return out

    for r in recs:
        r['f'] = frames(r)
    sym.finish()
    N = sym.name
    print(f'# {len(recs)} records over {secs:.1f} s, on-CPU sample every {per:g} ms per busy CPU, '
          f'census every {cen:g} ms; dropped {meta.vals.get("dropped", 0)}')

    oncpu = [r for r in recs if r['kind'] in (0, 1)]
    by_proc = collections.Counter()
    for r in oncpu:
        by_proc[r['pid']] += 1
    print('\n## CPU time per process (ms per second, all CPUs)')
    for pid, c in by_proc.most_common(a.top):
        print(f'{c * per / secs:8.1f}  {meta.tasks.get(pid, "?")}[{pid}]')

    by_thr = collections.Counter()
    for r in oncpu:
        by_thr[(r['pid'], r['tid'])] += 1
    print('\n## busiest threads (ms per second)')
    for (pid, tid), c in by_thr.most_common(a.top):
        print(f'{c * per / secs:8.1f}  {meta.tasks.get(pid, "?")}[{pid}] tid {tid} '
              f'"{meta.threads.get(tid, (0, ""))[1]}"')

    targets = [p for p, n in meta.tasks.items() if n in a.pid_name.split(',')]
    for pid in targets:
        tr = [r for r in recs if r['pid'] == pid]
        st = collections.defaultdict(collections.Counter)
        for r in tr:
            st[r['tid']][r['kind']] += 1
        print(f'\n## {meta.tasks[pid]}[{pid}] threads: ms per second on CPU (user / kernel), waiting, runnable')
        rows = []
        for tid, c in st.items():
            on_u, on_k = c[0] * per / secs, c[1] * per / secs
            rows.append((on_u + on_k, tid, on_u, on_k, c[2] * cen / secs, c[3] * cen / secs))
        for tot, tid, on_u, on_k, w, rn in sorted(rows, reverse=True)[:a.top]:
            print(f'{tot:7.1f} ({on_u:6.1f} / {on_k:6.1f})  wait {w:6.1f}  runnable {rn:6.1f}  tid {tid} '
                  f'"{meta.threads.get(tid, (0, ""))[1]}"')
        hot = [t for _, t, *_ in sorted(rows, reverse=True)[:a.threads]]
        for tid in hot:
            tname = meta.threads.get(tid, (0, ''))[1]
            rs = [r for r in tr if r['tid'] == tid]
            on = [r for r in rs if r['kind'] in (0, 1)]
            print(f'\n### tid {tid} "{tname}": {len(on) * per / secs:.1f} ms/s on CPU')
            img = collections.Counter()
            leaf = collections.Counter()
            incl = collections.Counter()
            kpath = collections.Counter()
            for r in on:
                f = r['f']
                img[f[0][0]] += 1
                leaf[(f[0][0], N(f[0][1]))] += 1
                seen = set()
                for x in f:
                    k = (x[0], N(x[1]))
                    if k not in seen:
                        seen.add(k)
                        incl[k] += 1
                if r['kind'] == 1:
                    ks = [N(x[1]) for x in f[:len(r['k'])]]
                    kpath[' < '.join(short(s, 40) for s in ks[:4])] += 1
            tot = len(on) or 1
            print('self time by image:')
            for k, c in img.most_common(12):
                print(f'  {100 * c / tot:5.1f}%  {k}')
            print('self time by function:')
            for (i, n), c in leaf.most_common(a.top):
                print(f'  {100 * c / tot:5.1f}%  {i}: {short(n)}')
            print('inclusive (function on the stack):')
            for (i, n), c in incl.most_common(a.top * 2):
                print(f'  {100 * c / tot:5.1f}%  {i}: {short(n)}')
            if kpath:
                print('kernel stacks (leaf < callers):')
                for p, c in kpath.most_common(a.top):
                    print(f'  {100 * c / tot:5.1f}%  {p}')
            off = [r for r in rs if r['kind'] in (2, 3)]
            if off:
                waits = collections.Counter()
                for r in off:
                    callers = [N(x[1]) for x in r['f'] if x[0] not in ('libsystem_kernel.dylib',)][:3]
                    waits[(KIND[r['kind']], r['trap'], ' < '.join(short(c, 50) for c in callers))] += 1
                print(f'off CPU (census, ms per second): wait {sum(c for (k, *_), c in waits.items() if k == "wait") * cen / secs:.1f}, '
                      f'runnable {sum(c for (k, *_), c in waits.items() if k == "runnable") * cen / secs:.1f}')
                for (k, trap, p), c in waits.most_common(a.top):
                    print(f'  {c * cen / secs:7.1f}  {k} trap {trap}  {p}')


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest='cmd', required=True)
    f = sp.add_parser('fetch')
    f.add_argument('out')
    f.add_argument('--secs', type=int, default=10)
    f.add_argument('--us', type=int, default=1000)
    f.add_argument('--census', type=int, default=2000)
    f.add_argument('--tasks', default='backboardd,SpringBoard')
    r = sp.add_parser('report')
    r.add_argument('out')
    r.add_argument('--kernel', required=True)
    r.add_argument('--lib', action='append', default=[])
    r.add_argument('--pid-name', default='backboardd')
    r.add_argument('--top', type=int, default=15)
    r.add_argument('--threads', type=int, default=3)
    a = ap.parse_args()
    fetch(a) if a.cmd == 'fetch' else report(a)


if __name__ == '__main__':
    main()
