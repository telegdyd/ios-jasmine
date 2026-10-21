"""show.py ADDR [N]: QuartzCore disassembly from ADDR (N lines, default to function end), with
bl targets named (QuartzCore functions, objc stubs -> selector, other stubs -> image+symbol) and adrp+add strings."""
import os, re, sys, bisect, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsc
OUT = os.path.expanduser('~/ios-work/gl/out2')
QCS = os.path.expanduser('~/ios-work/gl/out/qc.s')
start = int(sys.argv[1], 16)
maxn = int(sys.argv[2]) if len(sys.argv) > 2 else 100000
c = dsc.Cache()
funcs = {}
for line in open(f'{OUT}/qc-symbols.txt', errors='replace'):
    m = re.match(r'(0x[0-9a-f]+):\s+\((__\w+,__\w+)\)\s+\S.*?\t(.+?)\t?$', line)
    if m:
        funcs[int(m.group(1), 16)] = m.group(3).strip()
selrefs = {}
for line in open(f'{OUT}/qc-objc.txt', errors='replace'):
    m = re.match(r'(0x[0-9a-f]+) => (0x[0-9a-f]+): (\S+)$', line.strip())
    if m:
        selrefs[int(m.group(1), 16)] = m.group(3)
other = {}
for fn in os.listdir(OUT):
    if fn.endswith('-symbols.txt') and fn != 'qc-symbols.txt':
        for line in open(f'{OUT}/{fn}', errors='replace'):
            m = re.match(r'(0x[0-9a-f]+):\s+\(__TEXT,__text\)\s+\S.*?\t(.+?)\t?$', line)
            if m:
                other[int(m.group(1), 16)] = m.group(2).strip()


def cstr(va):
    b = c.read(va, 200)
    if not b:
        return None
    s = b.split(b'\0')[0]
    if len(s) >= 3 and all(32 <= x < 127 for x in s):
        return s.decode()
    return None


def name(t):
    if t in funcs:
        return funcs[t]
    if 0x18854f98c <= t < 0x188700000:  # objc stubs / auth stubs of QuartzCore
        i0, i1 = c.u32(t), c.u32(t + 4)
        p = dsc.adrp(i0, t)
        if p is not None and i1 & 0xffc00000 == 0xf9400000:
            sr = p + ((i1 >> 10) & 0xfff) * 8
            if sr in selrefs:
                return 'msgSend$' + selrefs[sr]
    r = dsc.resolve_stub(c, t)
    tgt = r[1] if r[0] == 'direct' else None
    if r[0] == 'got':
        tgt = r[2] & 0xfffffffff
        tgt += 0x180000000 if tgt < 0x180000000 else 0
    if tgt is not None:
        return other.get(tgt, f'ext:{tgt:#x}')
    return None


pat = re.compile(r'^(0x[0-9a-f]+):\s+((?:[0-9a-f]{2} ){4})\s*(.*)$')
on = False
n = 0
regs = {}
for line in open(QCS):
    m = pat.match(line)
    if not m:
        if on and line.startswith('sub_') and n > 0 and maxn == 100000:
            break
        continue
    pc = int(m.group(1), 16)
    if pc == start:
        on = True
    if not on:
        continue
    insn = int(''.join(reversed(m.group(2).split())), 16)
    txt = m.group(3)
    note = ''
    mm = re.match(r'(bl|b)\s+(0x[0-9a-f]+)', txt)
    if mm:
        nm = name(int(mm.group(2), 16))
        if nm:
            note = nm
    a = dsc.adrp(insn, pc)
    if a is not None:
        regs[insn & 31] = a
    elif insn & 0xffc00000 == 0x91000000 and ((insn >> 5) & 31) in regs:
        v = regs[(insn >> 5) & 31] + ((insn >> 10) & 0xfff)
        s = cstr(v)
        note = repr(s) if s else funcs.get(v, f'{v:#x}')
    elif insn & 0xffc00000 == 0xf9400000 and ((insn >> 5) & 31) in regs:
        v = regs[(insn >> 5) & 31] + ((insn >> 10) & 0xfff) * 8
        note = selrefs.get(v, f'[{v:#x}]')
        if v not in selrefs:
            p = c.u64(v)
            if p:
                pp = p & 0xfffffffff
                pp += 0x180000000 if pp < 0x180000000 else 0
                s = cstr(pp)
                if s:
                    note += f' -> {s!r}'
    if pc in funcs and pc != start:
        print(f'--- {funcs[pc]}')
    print(f'{pc:#x}  {txt:40s} {("; " + note) if note else ""}')
    n += 1
    if n >= maxn:
        break
