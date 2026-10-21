"""Pattern scan: ldr xF,[xB,#off] ; ldr x0,[xB] (any order, within 6 insns) ; blr/br xF  => GLI dispatch call off.
Uses OpenGLES export map from glidisp.py logic."""
import os, re, sys, bisect, collections
OUT = os.path.expanduser('~/ios-work/gl/out2')
QCS = os.path.expanduser('~/ios-work/gl/out/qc.s')
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'glimap.py')).read())
funcs = {}
for line in open(f'{OUT}/qc-symbols.txt', errors='replace'):
    m = re.match(r'(0x[0-9a-f]+):\s+\(__TEXT,__text\)\s+\S.*?\t(.+?)\t?$', line)
    if m:
        funcs[int(m.group(1), 16)] = m.group(2).strip()
fs = sorted(funcs)
pat = re.compile(r'^(0x[0-9a-f]+):\s+(?:[0-9a-f]{2} ){4}\s*(\S+)\s*(.*)$')
win = []
uses = collections.defaultdict(set)
for line in open(QCS):
    m = pat.match(line)
    if not m:
        continue
    pc, op, args = int(m.group(1), 16), m.group(2), m.group(3)
    win.append((op, args))
    win = win[-8:]
    if op in ('blr', 'br') :
        fr = args.strip()
        fn_off = None
        base = None
        ctx_ok = False
        for o, a in win[:-1]:
            mm = re.match(r'(x\d+), \[(x\d+), #(0x[0-9a-f]+)\]$', a)
            if o == 'ldr' and mm and mm.group(1) == fr:
                fn_off, base = int(mm.group(3), 16), mm.group(2)
        if base:
            for o, a in win[:-1]:
                if o == 'ldr' and a == f'x0, [{base}]':
                    ctx_ok = True
        if fn_off is not None and ctx_ok and fn_off >= 8 and fn_off % 8 == 0:
            f = fs[bisect.bisect_right(fs, pc) - 1]
            uses[fn_off].add(funcs[f])
with open(f'{OUT}/qc-gli-uses.txt', 'w') as fo:
    for off in sorted(uses):
        fo.write(f'{off:#06x}\t{"/".join(off2name.get(off, ["?"]))}\t{len(uses[off])}\t' + ' | '.join(sorted(uses[off])) + '\n')
print(len(uses), 'entries')
for off in sorted(uses):
    print(f'{off:#06x} {"/".join(off2name.get(off, ["?"]))[:60]:60s} {len(uses[off])}')
