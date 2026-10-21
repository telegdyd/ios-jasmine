"""GLI dispatch table of GLEngine's gliInitDispatchTable: slot index -> implementation symbol.

Reads gle.s / gle-symbols.txt (see README) and follows adrp+add into `str xR, [xB, #off]`
(slot = off / 8: the table pointer is disp[0], so struct offsets in ca-gles-calls-ios16.txt are off + 8).
Output: one line per slot: index, offset, symbol (or address if unnamed).
"""
import os, re, sys
OUT = os.path.expanduser('~/ios-work/gl/out2')
START = 0x1f6e9ae20
syms = {}
for l in open(f'{OUT}/gle-symbols.txt', errors='replace'):
    m = re.match(r'(0x[0-9a-f]+):\s+\(__TEXT,__text\)\s+(?:external|non-external[^\t]*)\t(\S+)', l)
    if m:
        syms[int(m.group(1), 16)] = m.group(2)
regs = {}
slots = {}
started = False
n = 0
for l in open(f'{OUT}/gle.s'):
    m = re.match(r'^(0x[0-9a-f]+):\s+(?:[0-9a-f]{2} ){4}\s*(.*)$', l)
    if not m:
        continue
    a = int(m.group(1), 16)
    if a == START:
        started = True
    if not started:
        continue
    t = m.group(2).split('\t')
    op = t[0].strip()
    args = t[1].strip() if len(t) > 1 else ''
    if a != START and a in syms and syms[a].startswith('_gli') is False and op == 'mov' and False:
        break
    if op == 'adrp':
        r, v = [x.strip() for x in args.split(',')]
        regs[r] = int(v, 16)
    elif op == 'add':
        p = [x.strip() for x in args.split(',')]
        if len(p) == 3 and p[1] in regs and p[2].startswith('#'):
            regs[p[0]] = regs[p[1]] + int(p[2][1:], 0)
        else:
            regs.pop(p[0], None)
    elif op == 'str':
        m2 = re.match(r'(x\d+), \[(x\d+), #(0x[0-9a-f]+)\]$', args)
        if m2 and m2.group(1) in regs:
            off = int(m2.group(3), 16)
            if off >= 8 and off % 8 == 0 and off <= 0x2020:
                slots[off // 8] = regs[m2.group(1)]
    if a > START + 0x20000 or (a != START and a in syms and syms[a] != '_gliInitDispatchTable' and a > START + 0x100):
        break
for i in sorted(slots):
    print(i, hex(8 * i), syms.get(slots[i], hex(slots[i])))
print(len(slots), 'slots', file=sys.stderr)
