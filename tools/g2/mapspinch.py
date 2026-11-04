import re, sys, time, socket
HOST = '192.168.7.2'

def c(line):
    try:
        with socket.create_connection((HOST, 5141), timeout=3) as s:
            s.sendall(line.encode() + b'\n'); s.settimeout(8)
            return s.recv(8192).decode(errors='replace').strip()
    except OSError:
        return None

def st():
    r = c('gpu state') or ''
    m = re.search(r'completed (\d+) of (\d+)', r)
    return (int(m.group(1)), int(m.group(2))) if m else None

def two(a0, a1, b0, b1, ms=450):
    """finger 0 a0->a1, finger 1 b0->b1"""
    steps = max(4, ms // 16)
    c(f'touch 0 1 {a0[0]} {a0[1]}'); c(f'touch 1 1 {b0[0]} {b0[1]}')
    for i in range(1, steps + 1):
        f = i / steps
        c(f'touch 0 1 {int(a0[0] + (a1[0]-a0[0])*f)} {int(a0[1] + (a1[1]-a0[1])*f)}')
        c(f'touch 1 1 {int(b0[0] + (b1[0]-b0[0])*f)} {int(b0[1] + (b1[1]-b0[1])*f)}')
        time.sleep(0.012)
    c(f'touch 0 0 {a1[0]} {a1[1]}'); c(f'touch 1 0 {b1[0]} {b1[1]}')

G = {
    'pinch_in':  ((471, 1522), (624, 1397), (809, 743), (648, 1107)),   # what the user did at 1441
    'pinch_in2': ((712, 683), (583, 1131), (413, 1645), (603, 1450)),
    'spread':    ((600, 1150), (450, 1600), (500, 950), (700, 600)),
    'tilt_up':   ((400, 1500), (400, 1000), (700, 1500), (700, 1000)),  # two-finger drag = 3D pitch
    'tilt_down': ((400, 1000), (400, 1500), (700, 1000), (700, 1500)),
    'rotate':    ((540, 700), (900, 1100), (540, 1500), (180, 1100)),
}
order = sys.argv[2].split(',') if len(sys.argv) > 2 else ['pinch_in', 'pinch_in2', 'spread', 'spread', 'tilt_up', 'rotate', 'tilt_down']
t0 = time.time(); n = 0; stuck = None
print('start', time.strftime('%H:%M:%S'), st(), flush=True)
while time.time() - t0 < float(sys.argv[1]):
    g = order[n % len(order)]
    two(*G[g])
    time.sleep(0.5)
    s = st(); t = time.strftime('%H:%M:%S')
    print(t, n, g, s, flush=True)
    n += 1
    if s and s[0] < s[1]:
        time.sleep(3); s2 = st()
        print(t, 'recheck', s2, flush=True)
        if s2 and s2[0] == s[0]:
            print(time.strftime('%H:%M:%S'), 'GPU STUCK', s2, flush=True)
            break
print('end', time.strftime('%H:%M:%S'), st(), flush=True)
