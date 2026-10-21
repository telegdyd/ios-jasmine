import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsc
OUT = os.path.expanduser('~/ios-work/gl/out2')
c = dsc.Cache()
syms = {}
for line in open(f'{OUT}/amglr-syms.txt', errors='replace'):
    m = re.match(r'(0x[0-9a-f]+):\s+\(__TEXT,__text\)\s+\S.*?\t(.+?)\t?$', line)
    if m:
        syms[int(m.group(1), 16)] = m.group(2).strip()
base = int(sys.argv[1], 16)
for i in range(int(sys.argv[2])):
    v = c.u64(base + 8 * i)
    p = v & 0xfffffffff
    p += 0x180000000 if p < 0x180000000 else 0
    print(f'{8*i:#05x} {v:#018x} {syms.get(p, hex(p))}')
