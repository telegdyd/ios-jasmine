# List a FAT16 image (modem partition) and optionally extract one file: python tools/fat16-ls.py IMG [PATH OUT]
import struct,sys
f=open(sys.argv[1],'rb'); b=f.read(512)
bps,spc,res,nf,ne,ts16,md,spf=struct.unpack('<HBHBHHBH',b[11:24]); 
fat_off=res*bps; root_off=fat_off+nf*spf*bps; data_off=root_off+ne*32
f.seek(fat_off); fat=f.read(spf*bps)
def chain(c):
    while 2<=c<0xfff8: yield c; c=struct.unpack('<H',fat[c*2:c*2+2])[0]
def rd(c): 
    out=b''
    for x in chain(c): f.seek(data_off+(x-2)*spc*bps); out+=f.read(spc*bps)
    return out
def ls(raw,path):
    lfn=''
    for i in range(0,len(raw),32):
        e=raw[i:i+32]
        if e[0]==0: break
        if e[0]==0xe5: lfn='';continue
        if e[11]==0xf: lfn=e[1:11].decode('utf-16le','ignore')+e[14:26].decode('utf-16le','ignore')+e[28:32].decode('utf-16le','ignore')+lfn; continue
        n=e[0:8].decode().strip(); x=e[8:11].decode().strip(); nm=(lfn.split('\0')[0] if lfn else n+('.'+x if x else '')); lfn=''
        cl=struct.unpack('<H',e[26:28])[0]; sz=struct.unpack('<I',e[28:32])[0]
        if nm in('.','..'): continue
        if e[11]&0x10: ls(rd(cl),path+nm+'/')
        else: print(sz,path+nm)
        if len(sys.argv)>2 and (path+nm).lower()==sys.argv[2].lower(): open(sys.argv[3],'wb').write(rd(cl)[:sz])
f.seek(root_off); ls(f.read(ne*32),'')
