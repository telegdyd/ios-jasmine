"""xref.py ADDR|STRING ... : QuartzCore code locations that branch to ADDR or form it with adrp+add/ldr.
A non-hex argument is looked up in qc-strings.txt (exact string)."""
import os, re, sys, bisect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsc
OUT = os.path.expanduser('~/ios-work/gl/out2')
QCS = os.path.expanduser('~/ios-work/gl/out/qc.s')
targets = {}
strs = None
for a in sys.argv[1:]:
    if re.fullmatch(r'0x[0-9a-fA-F]+', a):
        targets[int(a, 16)] = a
    else:
        if strs is None:
            strs = {}
            for line in open(f'{OUT}/qc-strings.txt', errors='replace'):
                m = re.match(r'(0x[0-9a-f]+): "(.*)"$', line.strip())
                if m:
                    strs.setdefault(m.group(2), []).append(int(m.group(1), 16))
        for v in strs.get(a, []):
            targets[v] = a
funcs = {}
for line in open(f'{OUT}/qc-symbols.txt', errors='replace'):
    m = re.match(r'(0x[0-9a-f]+):\s+\(__TEXT,__text\)\s+\S.*?\t(.+?)\t?$', line)
    if m:
        funcs[int(m.group(1), 16)] = m.group(2).strip()
fs = sorted(funcs)
pat = re.compile(r'^(0x[0-9a-f]+):\s+((?:[0-9a-f]{2} ){4})\s*(\S+)\s*(.*)$')
regs = {}
for line in open(QCS):
    m = pat.match(line)
    if not m:
        continue
    pc = int(m.group(1), 16)
    insn = int(''.join(reversed(m.group(2).split())), 16)
    hit = None
    if m.group(3) in ('bl', 'b'):
        try:
            hit = int(m.group(4).split()[0], 16)
        except ValueError:
            pass
    a = dsc.adrp(insn, pc)
    if a is not None:
        regs[insn & 31] = a
    elif insn & 0xffc00000 == 0x91000000 and ((insn >> 5) & 31) in regs:  # add imm
        hit = regs[(insn >> 5) & 31] + ((insn >> 10) & 0xfff)
    elif insn & 0xffc00000 == 0xf9400000 and ((insn >> 5) & 31) in regs:  # ldr x
        hit = regs[(insn >> 5) & 31] + ((insn >> 10) & 0xfff) * 8
    if hit in targets:
        f = fs[bisect.bisect_right(fs, pc) - 1]
        print(f'{targets[hit]}\t{pc:#x}\t{funcs[f]}+{pc - f:#x}')
