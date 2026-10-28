#!/usr/bin/env python3
"""Exercise the actual surface-release method with independently retained mappings."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

s=Path(sys.argv[1]).read_text()
start=s.index('IOReturn\nIOSurfaceRootUserClient::trapRelease(')
opening=s.index('{',start);end=opening+1;depth=1
while depth:
    depth+=(s[end]=='{')-(s[end]=='}');end+=1
method=s[start:end]
harness=r'''
#include <cassert>
#include <cstdint>
#include <vector>
#include <cstdio>
using IOReturn=int;
const int kIOReturnSuccess=0,kIOReturnNotFound=1;
static int pixels,states,data_maps;
static void IOLockLock(void*){}
static void IOLockUnlock(void*){}
#define OSSafeReleaseNULL(p) do {if(p){(p)->release();(p)=nullptr;}}while(0)
struct Mapping {
    bool state;
    Mapping(bool s):state(s){if(s)states++;else data_maps++;}
    void release(){if(state)states--;else data_maps--;delete this;}
};
struct Surface {
    unsigned id,users=1,refs=1;bool dead=false;
    Surface(unsigned i):id(i){pixels++;}
    void retain(){assert(!dead);refs++;}
    void release(){assert(refs);if(!--refs){pixels--;dead=true;}}
};
static void sweet_surface_put(Surface *s){assert(s->users);if(!--s->users)s->release();}
static int write_ends;
static void sweet_fb_write_end(Surface *s){assert(s && !s->dead);write_ends++;}
struct Ref {
    Surface *surface;Mapping *data,*state;unsigned count=1,refs=1,writeLocks=0;bool detached=true,released=false;
    Ref(Surface *s):surface(s),data(new Mapping(false)),state(new Mapping(true)){s->retain();}
    void retain(){refs++;}
    void release(){assert(refs);if(!--refs){
        OSSafeReleaseNULL(data);OSSafeReleaseNULL(state);
        if(surface){if(!released)sweet_surface_put(surface);surface->release();}delete this;}}
};
using SweetSurfaceRef=Ref;
struct Array {
    std::vector<Ref*> a;
    bool setObject(Ref *r){r->retain();a.push_back(r);return true;}
    unsigned getCount(){return a.size();}
    void removeObject(unsigned i){auto r=a[i];a.erase(a.begin()+i);r->release();}
    void clear(){while(!a.empty())removeObject(0);}
};
struct IOSurfaceRootUserClient {
    void *fLock=nullptr;Array refs,zombies;Array *fRefs=&refs,*fZombies=&zombies;
    Ref *findRef(uint32_t id,unsigned *index,bool detached=false){
        for(unsigned i=0;i<refs.getCount();i++)if(refs.a[i]->surface->id==id && refs.a[i]->detached==detached){
            if(index)*index=i;return refs.a[i];}return nullptr;}
    IOReturn trapRelease(void*,void*,void*,void*,void*,void*);
    void add(Ref *r){refs.setObject(r);r->release();}
    int drop(unsigned id){return trapRelease((void*)(uintptr_t)id,nullptr,nullptr,nullptr,nullptr,nullptr);}
};
'''
tail=r'''
int main(){
    IOSurfaceRootUserClient c;
    for(unsigned i=1;i<=300;i++){
        Surface s(i);c.add(new Ref(&s));assert(c.drop(i)==0);
        assert(s.dead && pixels==0 && data_maps==0);
        assert(states==(int)(i<256?i:256));
    }
    c.zombies.clear();assert(states==0);
    // An independent live user keeps pixels alive after this view is released.
    Surface s(400);s.retain();auto r=new Ref(&s);r->count=2;r->detached=false;c.add(r);
    assert(c.drop(400)==0 && !s.dead && data_maps==1 && c.refs.getCount()==1);
    assert(c.drop(400)==0 && !s.dead && data_maps==0 && states==1);
    s.release();assert(s.dead && pixels==0 && states==1);
    c.zombies.clear();assert(states==0);
    // Two clients: dropping one must preserve the other's mapping and pixels.
    IOSurfaceRootUserClient other;Surface shared(500);shared.users=2;
    c.add(new Ref(&shared));other.add(new Ref(&shared));
    assert(c.drop(500)==0 && !shared.dead && shared.users==1 && data_maps==1);
    assert(other.drop(500)==0 && shared.dead && pixels==0 && data_maps==0 && states==2);
    c.zombies.clear();other.zombies.clear();assert(states==0);
    assert(c.drop(999)==kIOReturnNotFound);
    // Present-queue write reservations (j0109) end with the view, while its surface is still alive.
    const bool reservations=RESERVATIONS;
    Surface locked(600);auto w=new Ref(&locked);w->writeLocks=2;c.add(w);
    assert(c.drop(600)==0 && locked.dead && pixels==0 && write_ends==(reservations?2:0));
    c.zombies.clear();assert(states==0);
    puts("PASS actual surface release: pixels freed, state pages preserved, 256-view bound, independent/live clients, write reservations ended");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    p=Path(tmp);(p/'test.cpp').write_text(harness+method+tail.replace('RESERVATIONS','true' if 'writeLocks' in method else 'false'))
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++17','-O2',str(p/'test.cpp'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True,timeout=15)
