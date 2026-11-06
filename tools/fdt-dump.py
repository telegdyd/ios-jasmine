# Dump FDT nodes whose path matches a regex: python tools/fdt-dump.py DTB REGEX (phandles shown as target node names; small ints may be mislabelled)
import struct,sys,re
d=open(sys.argv[1],'rb').read()
magic,tot,off_s,off_str,off_m,ver,lcv,bcpu,sz_str,sz_s=struct.unpack('>10I',d[:40])
strs=d[off_str:off_str+sz_str]
def gs(o): return strs[o:strs.index(b'\0',o)].decode()
p=off_s; path=[]; nodes={}; cur=None; order=[]
while True:
    tok,=struct.unpack('>I',d[p:p+4]); p+=4
    if tok==1:
        e=d.index(b'\0',p); name=d[p:e].decode(); p=(e+4)&~3
        path.append(name); cur='/'.join(path) or '/'; nodes[cur]={}; order.append(cur)
    elif tok==2: path.pop(); cur='/'.join(path)
    elif tok==3:
        ln,no=struct.unpack('>II',d[p:p+8]); p+=8; v=d[p:p+ln]; p=(p+ln+3)&~3
        nodes[cur][gs(no)]=v
    elif tok==4: continue
    elif tok==9: break
ph={}
for n,pr in nodes.items():
    if 'phandle' in pr: ph[struct.unpack('>I',pr['phandle'])[0]]=n
def fmt(k,v):
    if v and v[-1:]==b'\0' and all(32<=c<127 or c==0 for c in v[:-1]) and not v.startswith(b'\0'):
        return repr(v.decode().rstrip('\0').split('\0'))
    if len(v)%4==0:
        w=struct.unpack('>%dI'%(len(v)//4),v)
        if k in('interrupt-parent','phandle'): return '%s'%ph.get(w[0],w[0])
        return ' '.join('%x'%x+('('+ph[x].split('/')[-1]+')' if x in ph and k not in('reg','interrupts','ranges') and x>0x10 else '') for x in w)
    return v.hex()
pat=re.compile(sys.argv[2])
for n in order:
    if pat.search(n):
        print('==',n)
        for k,v in nodes[n].items(): print('   ',k,'=',fmt(k,v)[:300])
