"""Per-frame critical path from one framebench capture (WSL, repo root: needs prof.py's symbolizer).
    python3 tools/g2/framecrit.py research/framebench/NAME xnu/out-jasmine-K/kernel.development.sweet LIB
For every swap interval inside the CPU-sampled motion windows: GPU occupancy (union of
submit..completion-observed, an upper bound), the CoreAnimation render thread's state, SpringBoard's
main thread, the GPU driver thread and (task 26) Mesa's glthread worker "gl0", on a 0.5 ms grid."""
import collections
import json
import statistics
import sys
from pathlib import Path
sys.path.insert(0, 'tools/g2')
import framebench as fb
import prof

out, K, L = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
LIBNAME = Path(L).name  # test libraries under other names (task 26: t26.dylib) count as Mesa too
events = sorted(fb.unpack_file(out / 'events.bin', fb.EVENT), key=lambda e: e[0])
samples = fb.unpack_file(out / 'samples.bin', fb.SAMPLE)
stacks = fb.unpack_file(out / 'stacks.bin', fb.STACK)
summary = json.loads((out / 'summary.json').read_text())
meta = prof.Meta(str(out / 'profile.meta'))
sym = prof.Sym(meta, K, [L])
print('meta vals', meta.vals)
P = meta.vals.get('period_us', 2000)
C = meta.vals.get('census_us', 5000)
cache = {}


def frames_of(sid, pid):
    key = (sid, pid)
    if key not in cache:
        s = stacks[sid]
        nk, nu = s[1:3]
        fr = list(s[3:3 + nk + nu])
        pairs = [sym.kernel(x) for x in fr[:nk]] + [sym.user(pid, x if i == 0 else x - 1) for i, x in enumerate(fr[nk:])]
        cache[key] = [(img, sym.name(n)) for img, n in pairs]
    return cache[key]


def tname(tid):
    return meta.threads.get(tid, (0, ''))[1]


def classify_render(kind, fr):
    trace = ' '.join(n for _, n in fr)
    images = [i for i, _ in fr]
    if kind == 3:
        return 'runnable'
    if kind == 2:
        if 'sweet_fb_gpu_write_wait' in trace or 'AppleCLCD' in trace:
            return 'wait-panel'
        if '_mesa_glthread_finish' in trace:
            return 'wait-glthread'
        if 'ir3_get_shader' in trace or 'util_queue_fence_wait' in trace:
            return 'wait-shader'
        if 'darwin_pipe_wait' in trace or 'sweet_gpu_wait' in trace:
            return 'wait-gpu-fence'
        if 'mach_msg' in trace:
            return 'wait-mach_msg'
        if 'psynch' in trace or 'ulock' in trace:
            return 'wait-lock'
        return 'wait-other'
    if kind == 1:
        if any(n in trace for n in ('FlushPoC', 'flush_dcache', 'sweet_gpu_flush_all', 'IOFlushProcessorCache')):
            return 'cpu-k-cachemaint'
        if 'SweetGPU' in trace or 'sweet_gpu' in trace:
            return 'cpu-k-gpudrv'
        if 'AppleCLCD' in trace or 'sweet_fb' in trace:
            return 'cpu-k-display'
        return 'cpu-k-other'
    if any(i.startswith('libsweetca') or i == LIBNAME for i in images):
        return 'cpu-mesa'
    if 'QuartzCore' in images:
        return 'cpu-CA'
    return 'cpu-other'


GRID = 500
for phase, pname in ((5, 'home-a'), (6, 'control-a')):
    ps = [s for s in samples if s[5] == phase]
    if not ps:
        print(pname, 'no samples'); continue
    t0, t1 = min(s[0] for s in ps), max(s[0] for s in ps)
    wins = fb.intervals(events, t1).get(phase, [])
    swaps = sorted({e[0] for e in events if e[1] == 11 and e[2] == phase})
    jobs = [j for j in summary['gpu']['matched_jobs'] if j['phase'] == pname]
    # grid bins
    nb = (t1 - t0) // GRID + 1
    gpu = [0] * nb
    for j in jobs:
        a, b = max(j['submit_us'], t0), min(j['completion_observed_us'], t1)
        for i in range((a - t0) // GRID, (b - t0) // GRID + 1) if b > a else ():
            gpu[i] = 1
    render = [None] * nb
    sbmain = [0] * nb
    gdrv = [0] * nb
    glw = [0] * nb
    rstack = collections.defaultdict(collections.Counter)
    sbstack = collections.Counter()
    for us, sid, tid, pt, ev, p, kind, cpu, pad in ps:
        pid = pt & 0xffffffff
        task = meta.tasks.get(pid, '')
        tn = tname(tid)
        span = P if kind < 2 else C
        lo, hi = (us - t0) // GRID, min(nb - 1, (us - t0 + span - 1) // GRID)
        if task == 'backboardd' and 'display.primary' in tn:
            fr = frames_of(sid, pid)
            cat = classify_render(kind, fr)
            for i in range(lo, hi + 1):
                if render[i] is None or kind < 2:
                    render[i] = cat
            leaf = next((f'{img}:{n}' for img, n in fr if not n.startswith('_') or kind < 2), '?')
            # wait: the first user frame outside libsystem tells what it waits for
            if kind >= 2:
                leaf = ' < '.join(n for img, n in fr[:12] if img and 'kernel' not in img)[:220]
            rstack[cat][leaf] += span / 1000
        elif task == 'SpringBoard' and tid == min((t for t, (pp, nn) in meta.threads.items() if pp == pid), default=-1):
            if kind < 2:
                for i in range(lo, hi + 1):
                    sbmain[i] = 1
                fr = frames_of(sid, pid)
                sbstack[next((f'{img}:{n}' for img, n in fr), '?')] += span / 1000
        elif task == 'backboardd' and 'gdrv0' in tn and kind < 2:
            for i in range(lo, hi + 1):
                gdrv[i] = 1
        elif task == 'backboardd' and tn.endswith(':gl0') and kind < 2:
            for i in range(lo, hi + 1):
                glw[i] = 1
    rows = []
    for a, b in zip(swaps, swaps[1:]):
        if a < t0 or b > t1 or not any(wa <= a and b <= wb + 50000 for wa, wb in wins):
            continue
        ia, ib = (a - t0) // GRID, (b - t0) // GRID
        r = collections.Counter()
        n = dict(gpu=0, rcpu=0, sb=0, gdrv=0, glw=0, idle_both=0, idle_all=0)
        for i in range(ia, ib):
            cat = render[i] or 'unsampled'
            r[cat] += GRID / 1000
            rc = cat.startswith('cpu')
            n['gpu'] += gpu[i]; n['rcpu'] += rc; n['sb'] += sbmain[i]; n['gdrv'] += gdrv[i]; n['glw'] += glw[i]
            if not gpu[i] and not rc:
                n['idle_both'] += 1
                if not sbmain[i] and not gdrv[i]:
                    n['idle_all'] += 1
        rows.append(dict(ms=(b - a) / 1000, **{k: v * GRID / 1000 for k, v in n.items()}, render=r,
                         jobs=sum(a <= j['submit_us'] < b for j in jobs)))
    print(f'\n===== {pname}: {len(rows)} sampled frames, sampled span {(t1-t0)/1e6:.2f} s, {len(jobs)} GPU jobs')
    if not rows:
        continue
    def st(k):
        v = [x[k] for x in rows]
        return f'mean {statistics.mean(v):6.2f}  median {statistics.median(v):6.2f}'
    for k in ('ms', 'gpu', 'rcpu', 'sb', 'gdrv', 'glw', 'idle_both', 'idle_all', 'jobs'):
        print(f'  {k:10s} {st(k)}')
    tot = collections.Counter()
    for x in rows:
        tot.update(x['render'])
    print('  render thread per frame (ms):', {k: round(v / len(rows), 2) for k, v in tot.most_common()})
    # frame length histogram in 16.7 ms periods
    h = collections.Counter(round(x['ms'] / 16.667) for x in rows)
    print('  periods:', dict(sorted(h.items())))
    # slow vs fast frames
    rows.sort(key=lambda x: x['ms'])
    q = len(rows) // 4 or 1
    for lab, sel in (('fastest 25%', rows[:q]), ('slowest 25%', rows[-q:])):
        print(f'  {lab}: ms {statistics.mean(x["ms"] for x in sel):.1f} gpu {statistics.mean(x["gpu"] for x in sel):.1f} '
              f'rcpu {statistics.mean(x["rcpu"] for x in sel):.1f} sb {statistics.mean(x["sb"] for x in sel):.1f} '
              f'idle_both {statistics.mean(x["idle_both"] for x in sel):.1f} jobs {statistics.mean(x["jobs"] for x in sel):.1f}')
    print('  render thread top stacks per category (ms over the window):')
    for cat, ctr in sorted(rstack.items(), key=lambda kv: -sum(kv[1].values())):
        print(f'   [{cat}] {sum(ctr.values()):.0f} ms')
        for leaf, v in ctr.most_common(5):
            print(f'      {v:6.0f}  {leaf}')
    print('  SpringBoard main top leaves:')
    for leaf, v in sbstack.most_common(10):
        print(f'      {v:6.0f}  {leaf}')
    lat = sorted(j['latency_upper_bound_us'] for j in jobs)
    print(f'  job submit->observed us: median {lat[len(lat)//2]} p90 {lat[int(len(lat)*.9)]} max {lat[-1]}')
sym.finish()
