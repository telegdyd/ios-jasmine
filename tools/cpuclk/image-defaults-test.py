#!/usr/bin/env python3
"""Exercise actual mkimg profile selection without building images or using a device."""
from pathlib import Path
import os,subprocess,sys,tempfile
source=Path(sys.argv[1]).read_text().split('\nB=',1)[0]
lines=[]
for line in source.splitlines():
    if line.startswith('cd '):continue
    if line.startswith('K='):line='K="$TEST_KERNEL"'
    lines.append(line)
script='\n'.join(lines)+'\nprintf "%s %s %s\\n" "$AMP" "$CPUS" "$CPU_DVFS"\n'
with tempfile.TemporaryDirectory() as tmp:
    p=Path(tmp);new=p/'current';new.write_bytes(b'\0SWEET DVFS: jasmine defaults v1\0')
    old=p/'legacy';old.write_bytes(b'legacy kernel')
    cases=[(new,{},'1 8 1'),(old,{},'0 4 0'),(new,{'CPU_DVFS':'0'},'1 8 0'),
        (new,{'CPUS':'4'},'1 4 1'),(new,{'AMP':'0','CPU_DVFS':'0'},'0 4 0'),
        (new,{'AMP':'0'},None),(old,{'CPU_DVFS':'1'},None)]
    for kernel,settings,expected in cases:
        env={k:v for k,v in os.environ.items() if k not in ('AMP','CPUS','CPU_DVFS')}
        env.update(settings);env['TEST_KERNEL']=str(kernel)
        r=subprocess.run(['bash','-c',script,'mkimg-test','test'],env=env,text=True,capture_output=True)
        if expected is None:assert r.returncode!=0,r.stdout+r.stderr
        else:assert r.returncode==0 and r.stdout.strip()==expected,(r.returncode,r.stdout,r.stderr)
    print('Image defaults: actual mkimg current8/auto, legacy4, opt-out and incompatible overrides PASS')
