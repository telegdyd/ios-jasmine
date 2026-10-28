"""Per-100-flush windows of a netlog: frame time, draws, GPU busy, flush reasons, top shaders.
    python tools/g2/gpuwin.py LOG [FIRST_LINE LAST_LINE] [--shaders]
"""
import re, sys

log = open(sys.argv[1], 'rb').read().decode('utf-8', 'replace').splitlines()
lo, hi = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 and sys.argv[2].isdigit() else (1, len(log))
shaders = '--shaders' in sys.argv
wins = []
for i, l in enumerate(log, 1):
    m = re.search(r'sweetca: 100 flushes in \d+ ms \(([\d.]+) ms each.*?(\d+) draws', l)
    if m and lo <= i <= hi:
        wins.append((i, float(m.group(1)), int(m.group(2))))
for k, (i, each, draws) in enumerate(wins):
    end = wins[k + 1][0] if k + 1 < len(wins) else min(i + 400, len(log))
    w = log[i:end]
    busy = next((float(x.group(1)) for x in (re.search(r'gpuprof: \d+ batches, GPU busy ([\d.]+)', l) for l in w) if x), 0)
    nb = next((int(x.group(1)) for x in (re.search(r'gpuprof: (\d+) batches', l) for l in w) if x), 0)
    ev = {}
    for l in w:
        x = re.search(r'drawevent: (\S+) (\d+)', l)
        if x:
            ev[x.group(1)] = int(x.group(2))
    cls = [re.sub(r'.*gpuprof: ', '', l) for l in w if re.search(r'gpuprof: (sysmem|gmem|nondraw|sysfb) ', l)]
    fl = {k[6:]: v for k, v in ev.items() if k.startswith('flush-')}
    print(f'line {i}: {each:.1f} ms/frame, {draws/100:.0f} draws, {nb/100:.0f} batches, GPU {busy/100:.1f} ms per frame; '
          f'flushes/frame ' + ', '.join(f'{k} {v/100:.1f}' for k, v in fl.items()))
    for c in cls:
        x = re.match(r'(\S+)\s+(\S+)\s+(\d+) batches\s+([\d.]+) ms, max\s+([\d.]+)', c)
        if x:
            print(f'    {x.group(1)} {x.group(2)}: {int(x.group(3))/100:.1f} batches {float(x.group(4))/100:.1f} ms per frame, max {x.group(5)}')
    if shaders:
        for l in w:
            x = re.search(r'gpudraw: shader (\d+): (\d+) draws ([\d.]+) ms, max ([\d.]+) ms; slowest: (.*)', l)
            if x:
                print(f'    shader {x.group(1)}: {int(x.group(2))/100:.1f} draws {float(x.group(3))/100:.2f} ms per frame, '
                      f'max {x.group(4)}: {x.group(5)[:200]}')
