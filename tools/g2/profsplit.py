#!/usr/bin/env python3
"""Per-frame split of CoreAnimation's display thread from a j0057 profile (WSL, as prof.py report).

    profsplit.py OUT KERNEL LIBSWEETCA

Uses the 250-ms stretches in which com.apple.coreanimation.display.primary was on a CPU at least
40 % of the time (the UI moving), counts frames as separate runs of samples inside
AppleCLCD::present (sweetfb_sync=1 copies each frame there), and prints the thread's on-CPU
samples by category (display copy, Mesa user code, SweetGPU ioctls, CA's own code, ...) and its
census records (waits) in ms per frame, then the hottest user functions.
"""
import os
import sys, collections, bisect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prof
OUT, KERNEL, LIB = sys.argv[1:4]
recs=list(prof.records(open(OUT+'.bin','rb').read()))
meta=prof.Meta(OUT+'.meta')
TID=[t for t,(p,n) in meta.threads.items() if n=='com.apple.coreanimation.display.primary'][0]
sym=prof.Sym(meta, KERNEL, [LIB])
mine=[r for r in recs if r['tid']==TID]
for r in mine:
    r['f']=[sym.kernel(x) for x in r['k']]+[sym.user(r['pid'], x if i==0 else x-1) for i,x in enumerate(r['u'])]
sym.finish(); N=sym.name
on=[r for r in mine if r['kind'] in (0,1)]
# active 250 ms buckets: thread on CPU in >= 40% of the bucket's 250 ms
cnt=collections.Counter(r['us']//250000 for r in on)
act={b for b,c in cnt.items() if c>=100}
A=[r for r in on if r['us']//250000 in act]
asecs=len(act)*0.25
# frames: runs of samples inside AppleCLCD::present
pres=sorted(r['us'] for r in A if any('AppleCLCD::present' in N(n) for i,n in r['f'][:len(r['k'])]))
frames=0; last=-10**9
for t in pres:
    if t-last>3000: frames+=1
    last=t
# off-CPU in active buckets
cen=[r for r in mine if r['cpu']==0xff and r['us']//250000 in act]
for r in cen:
    pass
def cat(r):
    f=r['f']; nk=len(r['k'])
    ks=[N(n) for i,n in f[:nk]]; us=[(i,N(n)) for i,n in f[nk:]]
    imgs=[i for i,n in us]
    if r['kind']==1:
        if any('AppleCLCD::' in k for k in ks):
            if any('composeFit' in k for k in ks[:1]): return 'display copy: composeFit (CPU scale 1125x2436 -> 997x2160)'
            if any('delay' in k for k in ks[:3]): return 'display: wait for the previous flip to latch'
            return 'display: present/swap other (cache upkeep, locks)'
        if any('SweetGPU' in k or 'sweet_gpu' in k for k in ks):
            if any('create' in k or 'mapGPU' in k or 'vm_map' in k or 'Buffer::free' in k or 'vm_unmap' in k or 'bufferAt' in k or 'addBuffer' in k for k in ks): return 'GL kernel: GPU buffer create/map/free'
            if any('sweet_gpu_wait' in k for k in ks): return 'GL kernel: GPU wait (spin/sleep path)'
            if any('maintain' in k or 'Flush' in k or 'flush' in k for k in ks): return 'GL kernel: cache upkeep'
            return 'GL kernel: other SweetGPU ioctl'
        if 'libsweetca.dylib' in imgs: return 'GL kernel: other syscall from Mesa'
        if any('ipc_kmsg' in k or 'mach_msg' in k for k in ks): return 'kernel: mach_msg (CA IPC)'
        if any('vm_fault' in k or 'pmap' in k for k in ks): return 'kernel: page faults / VM'
        return 'kernel: other'
    if us and us[0][0]=='libsweetca.dylib': return 'GL user: Mesa/libsweetca'
    if 'libsweetca.dylib' in imgs:
        return 'GL user: libc/malloc under Mesa'
    if us and us[0][0]=='QuartzCore': return 'CA user: QuartzCore'
    return 'CA user: libc/malloc/objc/CF under CA'
c=collections.Counter(cat(r) for r in A)
print(f'tid {TID}: {len(act)} active 250-ms buckets ({asecs:.2f} s), {len(A)} on-CPU samples ({len(A)/asecs:.0f} ms/s), {frames} presents -> {asecs*1000/frames:.1f} ms per frame')
for k,v in c.most_common(): print(f'  {v/frames:6.2f} ms/frame  {100*v/len(A):5.1f}%  {k}')
cc=collections.Counter()
for r in cen:
    callers=[N(n) for i,n in r['f'] if i not in ('libsystem_kernel.dylib','IOKit')][:2]
    cc[(prof.KIND[r['kind']], ' < '.join(prof.short(x,45) for x in callers))]+=2
tot=sum(cc.values())
print(f'off CPU in active buckets: {tot/frames:.2f} ms/frame')
for (k,p),v in cc.most_common(8): print(f'  {v/frames:6.2f} ms/frame  {k}  {p}')
# top QuartzCore self & inclusive in active window, user only
leaf=collections.Counter(); inc=collections.Counter()
for r in A:
    nk=len(r['k'])
    u=[(i,N(n)) for i,n in r['f'][nk:]]
    if r['kind']==0 and u: leaf[u[0]]+=1
    seen=set()
    for x in u:
        if x not in seen: seen.add(x); inc[x]+=1
print('user self top:')
for (i,n),v in leaf.most_common(25): print(f'  {v/frames:5.2f} ms/f  {i}: {prof.short(n,100)}')
print('user inclusive top (QuartzCore):')
for (i,n),v in [x for x in inc.most_common(200) if x[0][0]=='QuartzCore'][:30]: print(f'  {v/frames:5.2f} ms/f  {prof.short(n,110)}')
print('libsweetca inclusive top:')
for (i,n),v in [x for x in inc.most_common(300) if x[0][0]=='libsweetca.dylib'][:25]: print(f'  {v/frames:5.2f} ms/f  {prof.short(n,110)}')
