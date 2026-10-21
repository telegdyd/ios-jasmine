"""gshow.py ADDR [N]: OpenGLES disassembly (gles.s) from ADDR with strings and names; 'x' as ADDR = list
OpenGLES functions referencing the strings given as further args."""
import os, re, sys, bisect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsc
OUT = os.path.expanduser('~/ios-work/gl/out2')
c = dsc.Cache()
funcs = {}
for line in open(f'{OUT}/' + os.environ.get('SYMS', 'gles-symbols.txt'), errors='replace'):
    m = re.match(r'(0x[0-9a-f]+):\s+\(__TEXT,__text\)\s+\S.*?\t(.+?)\t?$', line)
    if m:
        funcs[int(m.group(1), 16)] = m.group(2).strip()
other = {}
for fn in os.listdir(OUT):
    if fn.endswith('-symbols.txt'):
        for line in open(f'{OUT}/{fn}', errors='replace'):
            m = re.match(r'(0x[0-9a-f]+):\s+\(__TEXT,__text\)\s+\S.*?\t(.+?)\t?$', line)
            if m:
                other[int(m.group(1), 16)] = m.group(2).strip()
fs = sorted(funcs)


def cstr(va):
    b = c.read(va, 200)
    if not b:
        return None
    s = b.split(b'\0')[0]
    return s.decode() if len(s) >= 3 and all(32 <= x < 127 for x in s) else None


def name(t):
    if t in other:
        return other[t]
    r = dsc.resolve_stub(c, t)
    tgt = r[1] if r[0] == 'direct' else None
    if r[0] == 'got':
        tgt = r[2] & 0xfffffffff
        tgt += 0x180000000 if tgt < 0x180000000 else 0
    if tgt is not None:
        return other.get(tgt, f'ext:{tgt:#x}')
    # objc stub: adrp x1; ldr x1 -> selref -> selector string
    i0, i1 = c.u32(t), c.u32(t + 4)
    p = dsc.adrp(i0, t) if i0 else None
    if p is not None and i1 & 0xffc00000 == 0xf9400000:
        sr = p + ((i1 >> 10) & 0xfff) * 8
        v = c.u64(sr)
        if v:
            v &= 0xfffffffff
            v += 0x180000000 if v < 0x180000000 else 0
            s = cstr(v)
            if s:
                return 'msgSend$' + s
    return None


pat = re.compile(r'^(0x[0-9a-f]+):\s+((?:[0-9a-f]{2} ){4})\s*(.*)$')
mode_x = sys.argv[1] == 'x'
want = set(sys.argv[2:]) if mode_x else None
start = None if mode_x else int(sys.argv[1], 16)
maxn = int(sys.argv[2]) if (not mode_x and len(sys.argv) > 2) else 100000
on, n, regs = False, 0, {}
for line in open(f'{OUT}/' + os.environ.get('ASM', 'gles.s')):
    m = pat.match(line)
    if not m:
        if on and line.startswith('sub_') and n > 0 and maxn == 100000:
            break
        continue
    pc = int(m.group(1), 16)
    if not mode_x and pc == start:
        on = True
    if not mode_x and not on:
        continue
    insn = int(''.join(reversed(m.group(2).split())), 16)
    txt = m.group(3)
    note = ''
    mm = re.match(r'(bl|b)\s+(0x[0-9a-f]+)', txt)
    if mm:
        note = name(int(mm.group(2), 16)) or ''
    a = dsc.adrp(insn, pc)
    if a is not None:
        regs[insn & 31] = a
    elif insn & 0xffc00000 == 0x91000000 and ((insn >> 5) & 31) in regs:
        v = regs[(insn >> 5) & 31] + ((insn >> 10) & 0xfff)
        s = cstr(v)
        note = repr(s) if s else f'{v:#x}'
        if mode_x and s in want:
            f = fs[bisect.bisect_right(fs, pc) - 1]
            print(f'{s}\t{pc:#x}\t{funcs[f]}+{pc - f:#x}')
    elif insn & 0xffc00000 == 0xf9400000 and ((insn >> 5) & 31) in regs:
        v = regs[(insn >> 5) & 31] + ((insn >> 10) & 0xfff) * 8
        p = c.u64(v)
        note = f'[{v:#x}]'
        if p:
            pp = p & 0xfffffffff
            pp += 0x180000000 if pp < 0x180000000 else 0
            s = cstr(pp)
            if s:
                note += f' -> {s!r}'
    if mode_x:
        continue
    if pc in funcs and pc != start:
        print(f'--- {funcs[pc]}')
    print(f'{pc:#x}  {txt:40s} {("; " + note) if note else ""}')
    n += 1
    if n >= maxn:
        break
