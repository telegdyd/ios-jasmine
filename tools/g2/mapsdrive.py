import re, sys, time
sys.path.insert(0, r'C:\Users\teleg\Documents\Code\Xiaomi A2\ios-jasmine\tools\g2')
import uibench

c = uibench.cmd
def st():
    r = c('gpu state') or ''
    m = re.search(r'completed (\d+) of (\d+)', r)
    return (int(m.group(1)), int(m.group(2))) if m else None

def tap(x, y):
    c(f'swipe {x} {y} {x} {y} 60')

stuck_since = None
def check(tag):
    global stuck_since
    s = st()
    t = time.strftime('%H:%M:%S')
    print(t, tag, s, flush=True)
    if s is None:
        return False
    done, sub = s
    if done < sub:
        if stuck_since and stuck_since[0] == done:
            if time.time() - stuck_since[1] > 3:
                print(t, 'GPU STUCK at', s, flush=True)
                return True
        else:
            stuck_since = (done, time.time())
    else:
        stuck_since = None
    return False

print('start', time.strftime('%H:%M:%S'), st(), flush=True)
tap(899, 1303)                       # Maps icon (where the user tapped last time)
for _ in range(8):
    time.sleep(1); check('launch')
pans = [(540, 1300, 540, 700), (540, 700, 540, 1300), (300, 1100, 800, 1100), (800, 1100, 300, 1100),
        (300, 800, 800, 1400), (800, 1400, 300, 800)]
t0 = time.time()
i = 0
while time.time() - t0 < float(sys.argv[1] if len(sys.argv) > 1 else 180):
    x0, y0, x1, y1 = pans[i % len(pans)]
    c(f'swipe {x0} {y0} {x1} {y1} 250')
    if check(f'pan{i}'): break
    if i % 3 == 2:                   # double tap = zoom in
        tap(540, 1000); time.sleep(0.08); tap(540, 1000)
        time.sleep(0.6)
        if check(f'zoom{i}'): break
    time.sleep(0.4)
    i += 1
print('end', time.strftime('%H:%M:%S'), st(), flush=True)
