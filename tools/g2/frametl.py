"""Per-frame pipeline timeline of one framebench capture (task 27; WSL, repo root: needs prof.py's symbolizer).
    python3 tools/g2/frametl.py research/framebench/NAME KERNEL LIB [--phase control-a] [--lanes N] [--start K]
For every swap the render thread ended in the CPU-sampled window: when its first ticket was begun (render thread,
first GPU write of the frame), SwapEnd, the ticket SEAL (gdrv0, after the frame's last submit), the GPU completion
of that submit (observed), FLIP and LATCH, plus what the render thread waited on in that frame. --lanes prints
N frames as 0.5 ms lanes: R render thread (C CA, M Mesa, K kernel, s SwapWait wait, r runnable, g glthread wait,
l lock, . other wait), W glthread worker, D gdrv0 on CPU, G GPU job outstanding (submit..observed), with event
marks (B ticket begin, E SwapEnd, S seal, F flip, L latch)."""
import collections
import statistics
import sys
from pathlib import Path
sys.path.insert(0, 'tools/g2')
import framebench as fb
import prof

args = sys.argv[1:]
opt = {}
for k in ('--phase', '--lanes', '--start'):
    if k in args:
        i = args.index(k)
        opt[k] = args[i + 1]
        del args[i:i + 2]
out, K, L = Path(args[0]), args[1], args[2]
PNAME = opt.get('--phase', 'control-a')
PHASE = {v: k for k, v in fb.PHASES.items()}[PNAME]
LIBNAME = Path(L).name
events = sorted(fb.unpack_file(out / 'events.bin', fb.EVENT), key=lambda e: e[0])
samples = fb.unpack_file(out / 'samples.bin', fb.SAMPLE)
stacks = fb.unpack_file(out / 'stacks.bin', fb.STACK)
meta = prof.Meta(str(out / 'profile.meta'))
sym = prof.Sym(meta, K, [L])
P = meta.vals.get('period_us', 2000)
C = meta.vals.get('census_us', 5000)
cache = {}


def frames_of(sid, pid):
    if (sid, pid) not in cache:
        s = stacks[sid]
        nk, nu = s[1:3]
        fr = list(s[3:3 + nk + nu])
        pairs = [sym.kernel(x) for x in fr[:nk]] + [sym.user(pid, x if i == 0 else x - 1) for i, x in enumerate(fr[nk:])]
        cache[(sid, pid)] = [(img, sym.name(n)) for img, n in pairs]
    return cache[(sid, pid)]


def tname(tid):
    return meta.threads.get(tid, (0, ''))[1]


def render_state(kind, fr):
    trace = ' '.join(n for _, n in fr)
    images = [i for i, _ in fr]
    if kind == 3:
        return 'r'
    if kind == 2:
        if 'SwapWait' in trace or 'swap_wait' in trace:
            return 's'
        if '_mesa_glthread_finish' in trace:
            return 'g'
        if 'psynch' in trace or 'ulock' in trace:
            return 'l'
        return '.'
    if kind == 1:
        return 'K'
    if any(i.startswith('libsweetca') or i == LIBNAME for i in images):
        return 'M'
    if 'QuartzCore' in images:
        return 'C'
    return 'o'


GRID = 500
ps = [s for s in samples if s[5] == PHASE]
t0, t1 = min(s[0] for s in ps), max(s[0] for s in ps)
nb = (t1 - t0) // GRID + 1
lane = {k: [' '] * nb for k in 'RWDG'}
rthread = None
for us, sid, tid, pt, ev, p, kind, cpu, pad in ps:
    pid = pt & 0xffffffff
    task, tn = meta.tasks.get(pid, ''), tname(tid)
    if task != 'backboardd':
        continue
    span = P if kind < 2 else C
    lo, hi = (us - t0) // GRID, min(nb - 1, (us - t0 + span - 1) // GRID)
    if 'display.primary' in tn:
        rthread = tid
        st = render_state(kind, frames_of(sid, pid))
        for i in range(lo, hi + 1):
            if lane['R'][i] == ' ' or kind < 2:
                lane['R'][i] = st
    elif kind < 2 and ('gdrv0' in tn or tn.endswith(':gl0')):
        k = 'D' if 'gdrv0' in tn else 'W'
        for i in range(lo, hi + 1):
            lane[k][i] = '#'

ev = [e for e in events if t0 - 100000 <= e[0] <= t1 + 100000]
submits, done_at = {}, []
for us, kind, ph, tid, a, b, c, d in ev:
    if kind == 20:
        submits[a] = us
    elif kind == 21:
        done_at.append((us, a))
done_at.sort()


def gpu_done(seq):
    for us, a in done_at:
        if ((a - seq) & 0xffffffff) < 0x80000000:
            return us
    return None


for seq, us in submits.items():
    e = gpu_done(seq)
    if e is None:
        continue
    for i in range(max(0, (us - t0) // GRID), min(nb, (e - t0) // GRID + 1)):
        lane['G'][i] = '#'

# frames keyed by swap id
F = collections.defaultdict(dict)
gen2swap, seal = {}, {}
first_begin = {}  # generation -> first BEGIN us (render thread)
for us, kind, ph, tid, a, b, c, d in ev:
    if kind == 11:
        F[a]['end'] = us
    elif kind == 10:
        F[a]['swbegin'] = us
    elif kind == 39:
        gen2swap[b] = a
    elif kind == 31:
        seal[a] = (us, c)
    elif kind == 30:
        first_begin.setdefault(b, us)
    elif kind == 33:
        F[a]['flip'] = us
    elif kind == 14:
        F[a].setdefault('latch', us)
    elif kind == 18:
        pass
for g, s in gen2swap.items():
    if g in seal:
        F[s]['seal'], F[s]['seq'] = seal[g]
        F[s]['done'] = gpu_done(seal[g][1])
    if g in first_begin:
        F[s]['tbegin'] = first_begin[g]
# render thread swap waits: kind 18 events from the render thread
waits = collections.defaultdict(list)
for us, kind, ph, tid, a, b, c, d in ev:
    if kind == 18:
        waits[a].append((us - b, us, c))
ids = sorted(s for s, f in F.items() if 'end' in f and t0 <= f['end'] <= t1)


def at(us):
    return (us - t0) // GRID


rows = []
for prev, s in zip(ids, ids[1:]):
    f, fp = F[s], F[prev]
    if not all(f.get(k) is not None for k in ('seal', 'done', 'flip', 'latch', 'tbegin')) or 'latch' not in fp:
        continue
    a, b = at(fp['end']), at(f['end'])
    cnt = collections.Counter(lane['R'][a:b])
    rows.append(dict(id=s, period=(f['end'] - fp['end']) / 1000,
                     tb_after_prev_end=(f['tbegin'] - fp['end']) / 1000,
                     tb_after_prev_latch=(f['tbegin'] - fp['latch']) / 1000,
                     render=(f['end'] - f['tbegin']) / 1000,
                     end_seal=(f['seal'] - f['end']) / 1000,
                     seal_done=(f['done'] - f['seal']) / 1000,
                     done_flip=(f['flip'] - f['done']) / 1000,
                     flip_latch=(f['latch'] - f['flip']) / 1000,
                     tb_latch=(f['latch'] - f['tbegin']) / 1000,
                     **{f'R{k}': v * GRID / 1000 for k, v in cnt.items()},
                     D=lane['D'][a:b].count('#') * GRID / 1000, W=lane['W'][a:b].count('#') * GRID / 1000,
                     G=lane['G'][a:b].count('#') * GRID / 1000))
print(f'{PNAME}: {len(rows)} frames with the full chain (of {len(ids)} swaps ended in the window)')
keys = ['period', 'tb_after_prev_end', 'tb_after_prev_latch', 'render', 'end_seal', 'seal_done', 'done_flip',
        'flip_latch', 'tb_latch', 'D', 'W', 'G'] + sorted({k for r in rows for k in r if k.startswith('R')})
for k in keys:
    v = [r.get(k, 0) for r in rows]
    print(f'  {k:20s} mean {statistics.mean(v):6.2f}  median {statistics.median(v):6.2f}  min {min(v):6.2f}  max {max(v):6.2f}')
print('  first-ticket-begin lags the previous frame\'s latch (ms):',
      dict(sorted(collections.Counter(round(r['tb_after_prev_latch']) for r in rows).items())))

n = int(opt.get('--lanes', 0))
if n:
    first = int(opt.get('--start', 10))
    sel = ids[first:first + n + 1]
    a, b = at(F[sel[0]].get('tbegin', F[sel[0]]['end'])) - 4, at(F[sel[-1]]['end']) + 40
    a, b = max(0, a), min(nb, b)
    marks = [' '] * nb
    for s in sel:
        for k, ch in (('tbegin', 'B'), ('end', 'E'), ('seal', 'S'), ('flip', 'F'), ('latch', 'L')):
            if k in F[s] and a <= at(F[s][k]) < b:
                marks[at(F[s][k])] = ch if marks[at(F[s][k])] == ' ' else '*'
    W = 120
    for o in range(a, b, W):
        print(f'\n  t={(o - a) * GRID / 1000:7.1f} ms')
        print('  ev ' + ''.join(marks[o:min(b, o + W)]))
        for k in 'RWDG':
            print(f'  {k}  ' + ''.join(lane[k][o:min(b, o + W)]))
    print('\n  swaps:', ', '.join(f'{s}: B{(F[s].get("tbegin", 0) - F[sel[0]]["end"]) / 1000:.1f} E{(F[s]["end"] - F[sel[0]]["end"]) / 1000:.1f} '
                                 f'S{(F[s].get("seal", 0) - F[sel[0]]["end"]) / 1000:.1f} F{(F[s].get("flip", 0) - F[sel[0]]["end"]) / 1000:.1f} '
                                 f'L{(F[s].get("latch", 0) - F[sel[0]]["end"]) / 1000:.1f}' for s in sel))
sym.finish()

# SwapWait calls (framebench event 18, only those over 0.1 ms): by the waited swap relative to the swap last
# ended, id 0 (j0119 sets the last word for SwapWait(0) with sweetfb_wait0=1) and result, ms per ended swap
nend = sum(1 for e in events if e[1] == 11 and e[2] == PHASE)
last, sw = None, collections.defaultdict(list)
for us, kind, ph, tid, a, b, c, d in events:
    if ph != PHASE:
        continue
    if kind == 11:
        last = a
    elif kind == 18 and last is not None:
        sw[(a - last, d, c)].append(b)
print(f'\n  SwapWait over 0.1 ms, {PNAME}, {nend} swaps ended (rel = waited id - last ended id; id0 = SwapWait(0) under j0119):')
for (r, d, c), v in sorted(sw.items()):
    print(f'    rel {r:+d}{" id0" if d else "    "} {"done   " if c else "timeout"} {len(v):5d} calls, median {statistics.median(v) / 1000:.2f} ms, '
          f'{sum(v) / 1000 / max(1, nend):.2f} ms per swap')
