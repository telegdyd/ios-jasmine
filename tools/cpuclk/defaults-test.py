#!/usr/bin/env python3
"""Exercise actual board/build/default/override gates without touching MMIO."""
from pathlib import Path
import os,subprocess,sys,tempfile
s=Path(sys.argv[1]).read_text()
def function(signature):
    start=s.index(signature);opening=s.index('{',start);end=opening+1;depth=1
    while depth:
        depth+=(s[end]=='{')-(s[end]=='}');end+=1
    return s[start:end]
functions='\n'.join(function(sig) for sig in ('static bool\nsweet_dvfs_enabled(void)',
    'static bool\nsweet_dvfs_automatic(void)','static void\nsweet_dvfs_start(void)'))
harness=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef void *thread_t;
#define KERN_SUCCESS 0
static uint32_t osm_mode;
static int board,enabled_present,auto_present,starts,deallocs,voltage_probe,rpm_probe;
static uint32_t enabled_arg,auto_arg;
static int __attribute__((unused)) sweet_board_is(const char *name){assert(!strcmp(name,"xiaomi,jasmine"));return board;}
static int PE_parse_boot_argn(const char *key,uint32_t *v,unsigned size){
    assert(size==sizeof(*v));
    if(!strcmp(key,"sweetdvfs") && enabled_present){*v=enabled_arg;return 1;}
    if(!strcmp(key,"sweetdvfsauto") && auto_present){*v=auto_arg;return 1;}
    if(!strcmp(key,"sweetcpuvolt") && voltage_probe){*v=1;return 1;}
    if(!strcmp(key,"sweetcpurpm") && rpm_probe){*v=1;return 1;}
    return 0;
}
static void dvfs_worker(void *arg,int r){(void)arg;(void)r;}
static int kernel_thread_start(void (*fn)(void*,int),void *arg,thread_t *t){
    assert(fn==dvfs_worker && !arg);*t=NULL;starts++;return 0;}
static void thread_deallocate(thread_t t){assert(!t);deallocs++;}
'''
tail=r'''
int main(void){
    board=1;assert(sweet_dvfs_automatic());
    auto_present=1;auto_arg=0;assert(!sweet_dvfs_automatic());
    auto_arg=1;assert(sweet_dvfs_automatic());auto_arg=2;assert(!sweet_dvfs_automatic());
#if defined(TOPAZ_4K)
    assert(sweet_dvfs_enabled());sweet_dvfs_start();assert(starts==1 && deallocs==1);
    voltage_probe=1;assert(!sweet_dvfs_enabled());voltage_probe=0;
    rpm_probe=1;assert(!sweet_dvfs_enabled());rpm_probe=0;
    osm_mode=1;sweet_dvfs_start();assert(starts==1);osm_mode=0;
    enabled_present=1;enabled_arg=0;assert(!sweet_dvfs_enabled());sweet_dvfs_start();assert(starts==1);
    enabled_arg=1;assert(sweet_dvfs_enabled());enabled_arg=2;assert(!sweet_dvfs_enabled());
    enabled_arg=1;board=0;assert(!sweet_dvfs_enabled());sweet_dvfs_start();assert(starts==1);
#else
    assert(!sweet_dvfs_enabled());enabled_present=1;enabled_arg=1;
    assert(!sweet_dvfs_enabled());sweet_dvfs_start();assert(starts==0 && deallocs==0);
#endif
    puts("Jasmine defaults: actual board/build gates, opt-out, manual mode and OSM exclusion PASS");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    p=Path(tmp);(p/'test.c').write_text(harness+functions+tail)
    for flags in ([],['-DTOPAZ_4K=1']):
        subprocess.run([os.environ.get('CC','cc'),'-std=c11','-Wall',*flags,str(p/'test.c'),'-o',str(p/'test')],check=True)
        subprocess.run([str(p/'test')],check=True)
