"""Per-process / per-thread on-CPU ms/s and wakeup-ish counts from a prof.py capture.
    python research/cpu-idle-20261105/tally.py CAPTURE [N]"""
import sys, collections
sys.path.insert(0, 'tools/g2'); import prof
m = prof.Meta(sys.argv[1] + '.meta'); d = open(sys.argv[1] + '.bin', 'rb').read()
N = int(sys.argv[2]) if len(sys.argv) > 2 else 15
P = m.vals.get('period_us', 2000) / 1000
rs = [r for r in prof.records(d) if r['cpu'] != 0xff and r['kind'] < 2]
secs = (max(r['us'] for r in rs) - min(r['us'] for r in rs)) / 1e6
bp = collections.Counter(); bt = collections.Counter(); cl = collections.Counter()
for r in rs:
    n = m.tasks.get(r['pid'], 'pid%d' % r['pid'])
    bp[n] += P / secs; bt[(n, r['tid'])] += P / secs
    cl['gold' if r['cpu'] >= 4 else 'silver'] += P / secs
print(f'{secs:.1f} s; total {sum(cl.values()):.0f} ms/s', {k: round(v) for k, v in cl.items()})
for n, v in bp.most_common(N): print(f'{v:7.1f}  {n}')
print('threads:')
for k, v in bt.most_common(N): print(f'{v:7.1f}  {k}')
