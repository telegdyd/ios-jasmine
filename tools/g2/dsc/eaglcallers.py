"""QuartzCore functions that send EAGL selectors (through __objc_stubs or inline selref loads)."""
import os, re, sys, bisect, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsc
OUT = os.path.expanduser('~/ios-work/gl/out2')
QCS = os.path.expanduser('~/ios-work/gl/out/qc.s')
want = r'API|currentContext|initWithAPI:\S*|setCurrentContext:|attachImage:\S*|presentRenderbuffer:\S*|setParameter:to:|getParameter:to:|texImageIOSurface:\S*|getMacroContextPrivate|GetMacroContextPrivate|rendererWithEAGLContext:options:|_initWithEAGLContext:options:|renderbufferStorage:fromDrawable:|sharegroup|setBlockFence:onQueue:|EAGLContext'
selref = {}
for line in open(f'{OUT}/qc-objc.txt', errors='replace'):
    m = re.match(r'(0x[0-9a-f]+) => (0x[0-9a-f]+): (\S+)$', line.strip())
    if m and re.fullmatch(want, m.group(3)):
        selref[int(m.group(1), 16)] = m.group(3)
print(len(selref), 'refs')
funcs = {}
for line in open(f'{OUT}/qc-symbols.txt', errors='replace'):
    m = re.match(r'(0x[0-9a-f]+):\s+\(__TEXT,__text\)\s+\S.*?\t(.+?)\t?$', line)
    if m:
        funcs[int(m.group(1), 16)] = m.group(2).strip()
fs = sorted(funcs)
c = dsc.Cache()


def selref_of_stub(t):
    i0, i1 = c.u32(t), c.u32(t + 4)
    p = dsc.adrp(i0, t)
    if p is None or i1 & 0xffc00000 != 0xf9400000:
        return None
    return p + ((i1 >> 10) & 0xfff) * 8


use = collections.defaultdict(set)
pat = re.compile(r'^(0x[0-9a-f]+):\s+((?:[0-9a-f]{2} ){4})\s*(\S+)\s*(.*)$')
cache = {}
last_adrp = {}
for line in open(QCS):
    m = pat.match(line)
    if not m:
        continue
    pc = int(m.group(1), 16)
    insn = int(''.join(reversed(m.group(2).split())), 16)
    op = m.group(3)
    hit = None
    if op == 'bl' or op == 'b':
        t = int(m.group(4).split()[0], 16)
        if 0x18854f98c <= t < 0x188700000:
            if t not in cache:
                cache[t] = selref_of_stub(t)
            hit = cache[t]
    a = dsc.adrp(insn, pc)
    if a is not None:
        last_adrp[insn & 31] = a
    elif insn & 0xffc00000 == 0xf9400000:  # ldr xT, [xN, #imm]
        n = (insn >> 5) & 31
        if n in last_adrp:
            hit = hit or (last_adrp[n] + ((insn >> 10) & 0xfff) * 8)
    if hit in selref:
        use[selref[hit]].add(funcs[fs[bisect.bisect_right(fs, pc) - 1]])
for s in sorted(use):
    print(s)
    for f in sorted(use[s]):
        print('    ', f)
