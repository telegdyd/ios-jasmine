# Dump an NXP TFA98xx container (vendor/firmware/tfa98xx.cnt): device list and profiles: python tools/tfa-cnt.py FILE
import struct,sys
d=open(sys.argv[1],'rb').read()
T=['Device','Profile','Register','String','File','Patch','Marker','Mode','InSel','OutSel','ProgCfg','LagW','Gains','vBat','SensesCal','SensesDelay','Bitfield','Default','LiveData','LiveDataStr','Group','Cmd','MBDrc','Filter','NoInit','Features','CfMem','FwkUseCase','VddpConfig']
ndev,nprof,nld=struct.unpack('<HHH',d[40:46])
print('ndev',ndev,'nprof',nprof,'nlive',nld,'size',struct.unpack('<I',d[6:10]))
def ptr(o): v,=struct.unpack('<I',d[o:o+4]); return v&0xffffff, v>>24
def s(off): return d[off:d.index(b'\0',off)].decode('latin1')
def item(o,ind='   '):
    off,t=ptr(o); tn=T[t] if t<len(T) else t
    if t==3: print(ind,'String',s(off)); return
    if t==2:
        a,v,m=struct.unpack('<BHH',d[off:off+5]); print(ind,'Reg %02x val %04x mask %04x'%(a,v,m)); return
    if t==16:
        v,f=struct.unpack('<HH',d[off:off+4]); print(ind,'Bitfield %04x = %u'%(f,v)); return
    if t==17:
        v,f=struct.unpack('<HH',d[off:off+4]); print(ind,'Default %04x'%f); return
    if t in(4,5):
        no,nt=ptr(off); sz,=struct.unpack('<I',d[off+4:off+8]); print(ind,tn,s(no),sz,'bytes @%x'%(off+8)); return
    if t==7: print(ind,'Mode',struct.unpack('<i',d[off:off+4])); return
    if t==24: print(ind,'NoInit',d[off]); return
    if t==25: print(ind,'Features',struct.unpack('<3H',d[off:off+6])); return
    if t==21: print(ind,'Cmd @%x'%off, d[off:off+16].hex()); return
    if t==6: print(ind,'Marker'); return
    print(ind,tn,'@%x'%off,d[off:off+12].hex())
off,_=ptr(46)
ln=d[off]
for k in range(ln):
    o2,t2=ptr(off+12+4*k)
    if t2!=1: continue
    v,=struct.unpack('<I',d[o2:o2+4]); pl=v&0xff; no,_=ptr(o2+4)
    print('PROFILE',s(no),'items',pl)
    for j in range(pl-1): item(o2+8+4*j)
