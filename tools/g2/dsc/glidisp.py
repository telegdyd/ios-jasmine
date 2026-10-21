"""Which GLI dispatch entries does QuartzCore call, and from where.
1) OpenGLES exports: glFoo = mrs tpidrro; ldr x8,[x8,#0xf0]; ldr fn,[x8,#OFF]; ldr x0,[x8,#0x20]; br -> OFF-0x20 is the
   offset inside {GLIContext ctx; dispatch...} (what getMacroContextPrivate returns).
2) QuartzCore: registers loaded from [obj,#0x7f8] (GLESContext's macro context) or returned by getMacroContextPrivate;
   loads [reg,#imm] from them are dispatch entries."""
import os, re, sys, bisect, collections
OUT = os.path.expanduser('~/ios-work/gl/out2')
QCS = os.path.expanduser('~/ios-work/gl/out/qc.s')

# 1) OpenGLES offsets
gsym = {}
for line in open(f'{OUT}/gles-symbols.txt', errors='replace'):
    m = re.match(r'(0x[0-9a-f]+):\s+\(__TEXT,__text\)\s+external\s+(_gl\w+)', line)
    if m:
        gsym[int(m.group(1), 16)] = m.group(2)[1:]
lines = {}
order = []
for line in open(f'{OUT}/gles.s'):
    m = re.match(r'^(0x[0-9a-f]+):\s+(?:[0-9a-f]{2} ){4}\s*(.*)$', line)
    if m:
        a = int(m.group(1), 16)
        lines[a] = m.group(2).strip()
        order.append(a)
idx = {a: i for i, a in enumerate(order)}
off2name = collections.defaultdict(list)
unmapped = []
for a, n in sorted(gsym.items(), key=lambda x: x[1]):
    if a not in idx:
        unmapped.append(n)
        continue
    i = idx[a]
    found = None
    base_reg = None
    for j in range(i, min(i + 24, len(order))):
        t = lines[order[j]]
        m = re.match(r'ldr\s+(x\d+), \[(x\d+), #0xf0\]', t)
        if m:
            base_reg = m.group(1)
            continue
        m = re.match(r'ldr\s+(x\d+), \[(x\d+), #(0x[0-9a-f]+)\]', t)
        if m and base_reg and m.group(2) == base_reg and int(m.group(3), 16) not in (0x20,):
            found = int(m.group(3), 16) - 0x20
            break
        if t.startswith('ret') or t.startswith('b\t') or t.startswith('br'):
            if found is None and not t.startswith('br'):
                pass
    if found is None:
        unmapped.append(n)
    else:
        off2name[found].append(n)
print('OpenGLES gl exports', len(gsym), 'mapped', sum(len(v) for v in off2name.values()), 'unmapped', len(unmapped))

# 2) QuartzCore uses
funcs = {}
for line in open(f'{OUT}/qc-symbols.txt', errors='replace'):
    m = re.match(r'(0x[0-9a-f]+):\s+\(__TEXT,__text\)\s+\S.*?\t(.+?)\t?$', line)
    if m:
        funcs[int(m.group(1), 16)] = m.group(2).strip()
fs = sorted(funcs)
GMCP = 0x1885c9f00  # objc stub getMacroContextPrivate
uses = collections.defaultdict(set)
cur_f = None
marked = set()
pat = re.compile(r'^(0x[0-9a-f]+):\s+(?:[0-9a-f]{2} ){4}\s*(\S+)\s*(.*)$')
NOWRITE = {'str', 'stp', 'strb', 'strh', 'stur', 'cmp', 'cmn', 'tst', 'cbz', 'cbnz', 'tbz', 'tbnz', 'b', 'br', 'ret',
           'ccmp', 'fcmp', 'stlr', 'stlrb', 'blr', 'bl', 'braa', 'blraa', 'retab'}


def r64(r):
    return 'x' + r[1:] if r[0] in 'wx' else r


for line in open(QCS):
    m = pat.match(line)
    if not m:
        if line.startswith('sub_'):
            marked = set()
        continue
    pc = int(m.group(1), 16)
    f = fs[bisect.bisect_right(fs, pc) - 1]
    if f != cur_f:
        cur_f = f
        marked = set()
    op, args = m.group(2), m.group(3)
    ops = [a.strip() for a in re.split(r',(?![^\[]*\])', args)] if args else []
    if op in ('ldr', 'ldur') and len(ops) == 2:
        mm = re.match(r'\[(x\d+|sp|fp)(?:, #(0x[0-9a-f]+|\d+))?\]$', ops[1])
        dst = r64(ops[0])
        if mm:
            base, imm = mm.group(1), int(mm.group(2) or '0', 0)
            if base in marked and ops[0].startswith('x'):
                uses[imm].add(funcs[f])
                marked.discard(dst)
                continue
            if imm == 0x7f8 and ops[0].startswith('x'):
                marked.add(dst)
                continue
        marked.discard(dst)
        continue
    if op == 'ldp' and len(ops) >= 3:
        mm = re.match(r'\[(x\d+)(?:, #(0x[0-9a-f]+|\d+))?\]', ops[2])
        if mm and mm.group(1) in marked:
            imm = int(mm.group(2) or '0', 0)
            uses[imm].add(funcs[f])
            uses[imm + 8].add(funcs[f])
        marked.discard(r64(ops[0]))
        marked.discard(r64(ops[1]))
        continue
    if op == 'mov' and len(ops) == 2 and ops[1] in marked and ops[0].startswith('x'):
        marked.add(ops[0])
        continue
    if op in ('bl', 'blr', 'blraa', 'blraaz'):
        keep = {r for r in marked if r[0] == 'x' and r[1:].isdigit() and 19 <= int(r[1:]) <= 28}
        marked = keep
        if op == 'bl' and ops and ops[0] == hex(GMCP):
            marked.add('x0')
        continue
    if ops and op not in NOWRITE:
        marked.discard(r64(ops[0]))

print('QuartzCore dispatch offsets used:', len(uses))
rows = []
for off in sorted(uses):
    names = off2name.get(off, ['?'])
    rows.append((off, names, uses[off]))
with open(f'{OUT}/qc-gli-uses.txt', 'w') as fo:
    for off, names, fns in rows:
        fo.write(f'{off:#06x}\t{"/".join(names)}\t{len(fns)}\t' + ' | '.join(sorted(fns)) + '\n')
for off, names, fns in rows:
    print(f'{off:#06x} {"/".join(names):40s} {len(fns)}')
print('unmapped exports:', ' '.join(unmapped[:80]))
