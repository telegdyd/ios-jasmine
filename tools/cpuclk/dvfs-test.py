#!/usr/bin/env python3
"""Fault-test the actual DVFS core; optionally compare runtime OPPs to the DT model.

python3 dvfs-test.py XNU/osfmk/arm64/sweet_dvfs.h [--dts STOCK --fuses CAPTURE]
Device dumps are optional local inputs and never become test fixtures in git.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--dts', type=Path)
    parser.add_argument('--fuses', type=Path)
    args = parser.parse_args()
    source = args.source.read_text().split('/* DVFS kernel worker */')[0]
    source = source.replace('__asm__ volatile ("dsb sy" ::: "memory");', '')
    harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define OSM_BASE 0x179c0000ull
#define APCS_COMMON 0x179d1000ull
static uint64_t fuse_rows[80], pages[16];
static uint32_t memory[16][4096], rail[4];
static unsigned failure, consumed, writes, stage;
static uint64_t cpuvolt_base(unsigned c) { return c ? 0x17912000 : 0x17812000; }
static uint32_t *osm_ptr(uint64_t pa) {
    uint64_t page=pa & ~0x3fffull;
    for (unsigned i=0;i<16;i++) {
        if (!pages[i]) pages[i]=page;
        if (pages[i]==page) return &memory[i][(pa & 0x3fff)/4];
    }
    assert(0);return 0;
}
static uint64_t phys(volatile uint32_t *p,unsigned off) {
    for (unsigned i=0;i<16;i++) {
        uintptr_t delta=(uintptr_t)p-(uintptr_t)memory[i];
        if (delta<sizeof(memory[i])) return pages[i]+delta+off;
    }
    assert(0);return 0;
}
static bool fail(unsigned kind) {
    if (failure==6 || (failure==kind && !consumed)) { consumed++;return true; }
    return false;
}
static unsigned hardware_khz(unsigned c) {
    uint64_t rcg=c ? 0x17911050 : 0x17811050, pll=c ? 0x17916000 : 0x17816000;
    unsigned cfg=*osm_ptr(rcg+4), div=(cfg&31)+1;
    return ((cfg>>8)&7)==4 ? 1200000/div : *osm_ptr(pll+4)*38400/div;
}
static void delay(unsigned us) { assert(us && us<=100); }
static uint32_t osm_rd(volatile uint32_t *p,unsigned off) { return p[off/4]; }
static int sweet_pmic_peek(unsigned sid,unsigned addr,unsigned n,uint32_t *v) {
    unsigned id=1+(addr-0x1400)/0x300, off=(addr-0x1400)%0x300;
    assert(sid==1 && id<=3);
    if (off==0x40) { assert(n==4);*v=rail[id]|rail[id]<<16; }
    else if (off==0x45) { assert(n==2);*v=0x8006; }
    else { assert(off==4 && n==2);*v=0xa1c; }
    return 0;
}
static void osm_wr(volatile uint32_t *p,unsigned off,uint32_t v) {
    uint64_t pa=phys(p,off);writes++;
    p[off/4]=v;
    for (unsigned c=0;c<2;c++) {
        uint64_t saw=cpuvolt_base(c), pll=c ? 0x17916000 : 0x17816000;
        uint64_t rcg=c ? 0x17911050 : 0x17811050, ctl=c ? 0x179d0004 : 0x179d0010;
        if (pa==saw+0x900 || pa==saw+0x4c) {
            assert(hardware_khz(c)<=300000); /* supply changes require safe mux */
            assert((v&0x170000)==0x100000);
            if (pa==saw+0x4c) {
                assert((*osm_ptr(saw+0x900)&0x17ffff)==(v&0x17ffff));
                if (fail(1)) { *osm_ptr(saw+0xc18)=0x10000|(v&0xffff); }
                else {
                    *osm_ptr(saw+0xc18)=0x40000|(v&0xffff);
                    if (c) rail[1]=v&0xffff;
                    else { rail[2]=rail[3]=v&0xffff;if(fail(2)) rail[3]^=4; }
                }
            }
        }
        if (pa==ctl) {
            assert(hardware_khz(c)<=300000);
            assert(c ? rail[1]==872 : rail[2]==872 && rail[3]==872);
            if (!fail(5)) *osm_ptr(ctl+8)=(v&2) ? 0x1f000003 : 0;
        }
        if (pa==pll) {
            assert(hardware_khz(c)<=300000); /* never disable a selected PLL */
            *osm_ptr(pll+0x2c)=(v==7 && !fail(3)) ? 0x10000 : 0;
        }
        if (pa==rcg && (v&1) && !fail(4)) p[off/4]&=~1u;
    }
}
'''
    harness += source + r'''
static void reset(void) {
    memset(memory,0,sizeof(memory));memset(pages,0,sizeof(pages));
    memset(dvfs_state,0,sizeof(dvfs_state));memset(fuse_rows,0,sizeof(fuse_rows));
    failure=consumed=writes=stage=0;dvfs_ready=true;dvfs_auto=false;
    fuse_rows[38]=1ull<<29;fuse_rows[71]=2ull<<28;
    rail[1]=872;rail[2]=rail[3]=868;
    assert(dvfs_build_table());
    for(unsigned i=0;i<5;i++) { dvfs_mem_boot[i]=0x1234+i;*osm_ptr(APCS_COMMON+0x360+4*i)=dvfs_mem_boot[i]; }
    for(unsigned c=0;c<2;c++) {
        dvfs_state[c].current=dvfs_boot[c];
        *osm_ptr(dvfs_pll[c])=7;*osm_ptr(dvfs_pll[c]+4)=dvfs_boot[c].l;
        *osm_ptr(dvfs_pll[c]+0x2c)=0x10000;
        *osm_ptr(dvfs_rcg[c])=2;*osm_ptr(dvfs_rcg[c]+4)=dvfs_boot[c].cfg;
        assert(dvfs_context(c,&dvfs_boot[c],0));
    }
}
int main(void) {
    reset();fuse_rows[38]=0;assert(!dvfs_build_table());
    reset();fuse_rows[71]=0;assert(!dvfs_build_table());
    for(unsigned c=0;c<2;c++) {
        reset();
        for(unsigned repeat=0;repeat<3;repeat++) {
            for(unsigned i=0;i<dvfs_count[c];i++) {
                struct dvfs_opp *o=&dvfs_opps[c][i];
                assert(dvfs_transition(c,o,o->mv>=872));
                assert(dvfs_context(c,o,o->mv>=872));
            }
            for(unsigned i=dvfs_count[c];i-->0;) {
                struct dvfs_opp *o=&dvfs_opps[c][i];
                assert(dvfs_transition(c,o,o->mv>=872));
            }
        }
        assert(dvfs_transition(c,&dvfs_boot[c],0));
        assert(dvfs_context(c,&dvfs_boot[c],0));
    }
    for(unsigned f=1;f<=5;f++) {
        reset();failure=f;dvfs_auto=true;
        assert(!dvfs_transition(0,&dvfs_opps[0][6],1));
        assert(consumed && !dvfs_auto && !dvfs_state[0].fault);
        assert(dvfs_context(0,&dvfs_boot[0],0)); /* independently verified rollback */
        assert(dvfs_state[0].current.khz==1747200);
    }
    reset();failure=6;assert(!dvfs_transition(0,&dvfs_opps[0][6],1));
    assert(dvfs_state[0].fault);unsigned old_writes=writes;failure=0;
    assert(!dvfs_transition(0,&dvfs_opps[0][0],0) && writes==old_writes);
    reset();rail[3]^=4;assert(!dvfs_transition(0,&dvfs_opps[0][6],1) && !writes);
    reset();*osm_ptr(APCS_COMMON+0x360)^=1;assert(!dvfs_transition(0,&dvfs_opps[0][6],1) && !writes);
    reset();dvfs_state[0].current=dvfs_opps[0][0];
    assert(dvfs_policy(0,65)==6 && dvfs_state[0].quiet==0); /* fast boost */
    dvfs_state[0].current=dvfs_opps[0][6];
    for(unsigned i=0;i<4;i++) assert(dvfs_policy(0,0)==6);
    assert(dvfs_policy(0,0)==0); /* idle hysteresis then floor */
    dvfs_state[0].quiet=0;
    for(unsigned i=0;i<4;i++) assert(dvfs_policy(0,20)==6);
    assert(dvfs_policy(0,20)==5);
    assert(dvfs_policy(0,50)==6 && dvfs_state[0].quiet==0);
    puts("DVFS core: all levels, divider, supply/APM/PLL ordering, five injected failures, rollback, sticky fault and load policy PASS");
MODEL_CASE
}
'''
    model_case = ''
    expected = None
    if bool(args.dts) != bool(args.fuses):
        parser.error('--dts and --fuses must be supplied together')
    if args.dts:
        import cpuclk_model as model
        rows = model.parse_fuses(args.fuses)
        model_case = 'memset(fuse_rows,0,sizeof(fuse_rows));\n'
        for row, value in rows.items():
            model_case += f'fuse_rows[{row}]=0x{value:x}ull;\n'
        model_case += 'assert(dvfs_build_table());\n'
        model_case += 'for(unsigned c=0;c<2;c++) for(unsigned i=0;i<dvfs_count[c];i++) printf("MODEL %u %u %u\\n",c,dvfs_opps[c][i].khz,dvfs_opps[c][i].mv);\n'
        expected = []
        text = args.dts.read_text()
        for cid, cluster in enumerate(('gold', 'silver')):
            ctrl = model.parse_dts_node(text, model.CLUSTERS[cluster]['node'])
            dt = model.parse_dts_node(text[text.find(model.CLUSTERS[cluster]['node']):], 'regulator')
            dt['ctrl'] = ctrl
            corners = model.cprh_model(dt, rows, lambda *_: None, cluster)['corners']
            expected += [f'MODEL {cid} {x.freq // 1000} {x.open_loop // 1000}' for x in corners if x.freq]
    harness = harness.replace('MODEL_CASE', model_case)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path / 'dvfs.c').write_text(harness)
        subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-Wall', '-Wextra', '-Werror',
                        str(path / 'dvfs.c'), '-o', str(path / 'dvfs')], check=True)
        result = subprocess.run([str(path / 'dvfs')], check=True, text=True, capture_output=True)
        print(result.stdout)
        if expected is not None:
            actual = [line for line in result.stdout.splitlines() if line.startswith('MODEL ')]
            assert actual == expected, (actual, expected)
            print('Runtime fuse OPPs match independent Python/stock DT model PASS')


if __name__ == '__main__':
    main()
