#!/usr/bin/env python3
"""Compile the actual SAW16 helper against a fault-injecting MMIO/PMIC model.

Usage: python3 voltage-test.py XNU/osfmk/arm64/sweet_cpu_voltage.h
Host evidence covers transaction ordering and rollback, not physical hardware.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    source = args.source.read_text().replace('__asm__ volatile ("dsb sy" ::: "memory");', '')
    harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define OSM_BASE 0x179c0000ull
#define APCS_APM 0x179d0000ull
#define APCS_COMMON 0x179d1000ull
#define LCK_GRP_DECLARE(n,s) int n __attribute__((unused))
#define LCK_MTX_DECLARE(n,g) int n
static unsigned enabled, locked, writes, sends, failure, rail[4], phases;
static bool read_fail;
static uint64_t pages[16];
static uint32_t memory[16][4096];
static uint32_t *osm_ptr(uint64_t pa) {
    uint64_t page=pa & ~0x3fffull;
    for (unsigned i=0;i<16;i++) {
        if (!pages[i]) pages[i]=page;
        if (pages[i]==page) return &memory[i][(pa & 0x3fff)/4];
    }
    assert(0); return 0;
}
static void lck_mtx_lock(int *p) { (void)p; assert(!locked); locked=1; }
static void lck_mtx_unlock(int *p) { (void)p; assert(locked); locked=0; }
static int PE_parse_boot_argn(const char *key, uint32_t *v, unsigned n) {
    assert(!strcmp(key,"sweetcpuvolt") && n==4); *v=enabled; return enabled!=0;
}
static uint32_t osm_rd(volatile uint32_t *p, unsigned off) { assert(locked); return p[off/4]; }
static void delay(unsigned us) { assert(locked && (us==1 || us==100000)); }
static int sweet_pmic_peek(unsigned sid, unsigned addr, unsigned n, uint32_t *v) {
    assert(locked && sid==1);
    unsigned id=1+(addr-0x1400)/0x300, off=(addr-0x1400)%0x300;
    assert(id<=3);
    if (read_fail) return -1;
    if (off==0x40) { assert(n==4); *v=rail[id] | rail[id]<<16; }
    else if (off==0x45) { assert(n==2); *v=0x8006; }
    else { assert(off==4 && n==2); *v=0xa1c; }
    return 0;
}
static void osm_wr(volatile uint32_t *p, unsigned off, uint32_t v) {
    assert(locked); writes++;
    assert(off==0xc1c || off==0x900 || off==0x4c);
    if (off==0xc1c) { assert(v==1 && phases==0); phases=1; }
    else {
        assert((v & 0x17ffff)==(0x100000 | (v & 0xffff)));
        assert((v & ~0x17ffffu)==(p[off/4] & ~0x17ffffu));
        if (off==0x900) { assert(phases==1); phases=2; }
        else {
            assert(phases==2 && (v & 0x17ffff)==(p[0x900/4] & 0x17ffff)); phases=0;
            sends++;
            bool fail=(failure && sends==1) || failure==3;
            unsigned mv=v & 0xffff;
            p[0xc18/4]=(fail && failure!=2) ? 0x10000|mv : 0x40000|mv;
            if (!fail || failure==1) {
                if (p==osm_ptr(0x17812000)) rail[2]=rail[3]=mv;
                else { assert(p==osm_ptr(0x17912000)); rail[1]=mv; }
            }
        }
    }
    p[off/4]=v;
}
'''
    harness += source + r'''
static char output[512];
static void reset(void) {
    assert(!locked); memset(memory,0,sizeof(memory)); memset(pages,0,sizeof(pages));
    memset(cpuvolt_state,0,sizeof(cpuvolt_state));
    enabled=1; writes=sends=failure=phases=0; read_fail=false;
    rail[1]=872; rail[2]=rail[3]=868;
    for (unsigned c=0;c<2;c++) {
        uint64_t pll=c ? 0x17916000 : 0x17816000, rcg=c ? 0x17911050 : 0x17811050;
        *osm_ptr(pll)=7; *osm_ptr(pll+4)=c ? 0x48 : 0x5b;
        *osm_ptr(rcg)=2; *osm_ptr(rcg+4)=c ? 0x501 : 0x301;
        *osm_ptr(cpuvolt_base(c)+0xc04)=0x2020016f;
        *osm_ptr(cpuvolt_base(c)+0x900)=0xa8000000;
        *osm_ptr(cpuvolt_base(c)+0x4c)=0x05000000;
    }
    for (unsigned i=0;i<14;i++) *osm_ptr(0x10ae0a0+4*i)=(1<<21)|500;
}
static void request(unsigned c, unsigned mv, const char *want) {
    sweet_cpu_voltage(c,mv,output,sizeof(output));
    assert(strstr(output,want) && !locked && !phases);
}
int main(void) {
    reset(); enabled=0; request(0,872,"REFUSED"); assert(!writes);
    reset(); enabled=2; request(0,872,"REFUSED"); assert(!writes);
    reset(); request(2,872,"cluster"); assert(!writes);
    reset(); request(0,876,"REFUSED"); request(1,868,"REFUSED"); assert(!writes);
    reset(); request(0,0,"status"); assert(!writes);
    reset(); read_fail=true; request(0,872,"REFUSED"); assert(!writes);
    reset(); rail[3]=872; request(0,872,"REFUSED"); assert(!writes);
    reset(); *osm_ptr(0x17816004)=0x73; request(0,872,"REFUSED"); assert(!writes);
    reset(); *osm_ptr(APCS_APM+4)=1; request(1,876,"REFUSED"); assert(!writes);
    reset(); *osm_ptr(APCS_COMMON+0x368)=1; request(0,872,"REFUSED"); assert(!writes);
    reset(); *osm_ptr(0x17812c04)=0; request(0,872,"REFUSED"); assert(!writes);
    reset(); *osm_ptr(OSM_BASE+0x3004)=1; request(0,872,"REFUSED"); assert(!writes);
    reset(); *osm_ptr(0x10ae0a0)=0; request(0,872,"REFUSED"); assert(!writes);
    reset(); *osm_ptr(0x10ae0a0)=(1<<21)|700; request(0,872,"REFUSED"); assert(!writes);
    for (unsigned c=0;c<2;c++) {
        reset(); unsigned low=c ? 872 : 868;
        request(c,low," OK "); request(c,low+4," OK ");
        assert(cpuvolt_state[c].requested==low+4 && cpuvolt_state[c].verified==low+4);
        assert(c ? rail[2]==868 && rail[3]==868 : rail[1]==872);
        *osm_ptr(0x10ae0a0)=0; /* sensor failure must not prevent restoration */
        request(c,low," OK "); assert(cpuvolt_state[c].verified==low && sends==3);
    }
    for (unsigned f=1;f<=2;f++) {
        reset(); failure=f; request(0,872,"FAILED, restored");
        assert(sends==2 && rail[2]==868 && rail[3]==868);
        assert(cpuvolt_state[0].requested==872 && cpuvolt_state[0].verified==868);
        assert(!cpuvolt_state[0].fault);
    }
    reset(); failure=3; request(0,872,"FAULT, rollback unverified");
    assert(sends==2 && cpuvolt_state[0].fault && !cpuvolt_state[0].verified);
    failure=0; request(0,868,"REFUSED"); assert(sends==2); /* sticky fault */
    reset(); request(0,872," OK "); rail[3]=868;
    request(0,0,"FAULT, state changed"); assert(!cpuvolt_state[0].verified);
    puts("CPU SAW16: gates, paired rails, ordering, timeout, rollback, fault latch PASS");
}
'''
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path / 'voltage.c').write_text(harness)
        subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-Wall', '-Wextra', '-Werror',
                        str(path / 'voltage.c'), '-o', str(path / 'voltage')], check=True)
        subprocess.run([str(path / 'voltage')], check=True)


if __name__ == '__main__':
    main()
