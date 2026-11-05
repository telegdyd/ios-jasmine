"""A/B of Wi-Fi scan timings with Settings > Wi-Fi open (it rescans by itself): scanab.py LOG CFG... (CFG "150 50 500")
Per config: 70 s of console log; prints each scan's channels, duration and how many results wifid read."""
import re, socket, subprocess, sys, time
sys.path.insert(0, 'tools/g2'); import prof
log = sys.argv[1]
for cfg in sys.argv[2:]:
    print('==', prof.cmd('wscan ' + cfg).strip(), flush=True)
    out = f'{log}-{cfg.replace(" ", "_")}.txt'
    subprocess.run([sys.executable, 'tools/sweet-netlog.py', out, '--wait', '10', '--for', '70'], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    lines = open(out, 'rb').read().decode(errors='replace').splitlines()
    # only the part after our wscan took effect: from the first scan line naming this rest
    want = 'rest %s-%s ms' % tuple(cfg.split()[1:3])
    start = next((i for i, l in enumerate(lines) if want in l), len(lines))
    cur = None
    for l in lines[start:]:
        m = re.search(r't=(\d+) ms: scan: (\w+), (\d+) channels', l)
        if m:
            cur = [int(m[1]), m[2], int(m[3]), 0]
        m = re.search(r't=(\d+) ms: \*\*\* scan \d+ done.*\((\d+) probe', l)
        if m and cur:
            cur.append(int(m[1]) - cur[0])
        if cur and 'SCAN_RESULT' in l and 'answered' in l:
            cur[3] += 1
        if cur and 'SCAN_RESULT' in l and 'error' in l and len(cur) > 4:
            print(f'  {cur[1]:7s} {cur[2]:2d} ch  {cur[4]/1000:5.2f} s  {cur[3]} results', flush=True)
            cur = None
