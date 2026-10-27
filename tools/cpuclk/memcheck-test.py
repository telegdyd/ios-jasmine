#!/usr/bin/env python3
"""Run the actual pinned-core memory diagnostic with concurrent host workers."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

source = Path(sys.argv[1]).read_text().replace('#include <kern/kalloc.h>', '')
harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <time.h>
#include <unistd.h>
#define MAX_CPUS 8
#define __unused __attribute__((unused))
#define LCK_GRP_DECLARE(n,s) int n
#define LCK_MTX_DECLARE(n,g) pthread_mutex_t n = PTHREAD_MUTEX_INITIALIZER
#define lck_mtx_lock pthread_mutex_lock
#define lck_mtx_unlock pthread_mutex_unlock
#define Z_WAITOK 0
#define Z_ZERO 0
#define PROCESSOR_NULL 0
#define THREAD_CONTINUE_NULL 0
#define KERN_SUCCESS 0
typedef int wait_result_t;
typedef int processor_t;
typedef pthread_t thread_t;
static unsigned real_ncpus;
static int mode, allocations, launches;
static _Thread_local int actual_cpu;
static void *allocate(size_t n) { if(mode==1)return NULL; allocations++; return calloc(1,n); }
static void deallocate(void *p) { assert(p); allocations--; free(p); }
#define kalloc_data(n,f) allocate(n)
#define kfree_data(p,n) deallocate(p)
static uint64_t mach_absolute_time(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return t.tv_sec*1000000000ull+t.tv_nsec; }
static void absolutetime_to_nanoseconds(uint64_t t,uint64_t *n) {*n=t;}
static void delay(unsigned us) {usleep(us);}
static processor_t cpu_to_processor(unsigned cpu) { return cpu+1; }
static void thread_bind(processor_t p) {actual_cpu=p-1; if(mode==3 && p==1)actual_cpu=7;}
static void thread_block(int c) {(void)c;}
static int cpu_number(void) {return actual_cpu;}
struct packet {void (*fn)(void*,int); void *arg;};
static void *worker(void *v) {struct packet p=*(struct packet*)v;free(v);p.fn(p.arg,0);return NULL;}
static int kernel_thread_start(void (*fn)(void*,int),void *arg,thread_t *t);
static void thread_deallocate(thread_t t) {pthread_detach(t);}
'''
tail = r'''
static int kernel_thread_start(void (*fn)(void*,int),void *arg,thread_t *t) {
    launches++;
    if(mode==2 && (uintptr_t)arg==2)return -1;
    if(mode==4 && memcheck.phase && (uintptr_t)arg==0)memcheck.buffer[0]^=1;
    struct packet *p=malloc(sizeof(*p));assert(p);p->fn=fn;p->arg=arg;
    int e=pthread_create(t,NULL,worker,p);if(e)free(p);return e;
}
int main(void) {
    char out[4096];
    for(unsigned n=4;n<=8;n+=4)for(mode=0;mode<=4;mode++) {
        real_ncpus=n; launches=0;
        int len=memcheck_command(1,out,sizeof(out));
        assert(len>0 && len<(int)sizeof(out));assert(allocations==0);
        if(mode==0){assert(strstr(out,"checkmem: OK"));assert(launches==n*8);}
        else if(mode==1){assert(strstr(out,"allocation failed"));assert(launches==0);}
        else {assert(strstr(out,"checkmem: FAILED"));}
    }
    launches=0;assert(memcheck_command(2,out,sizeof(out))>0);assert(launches==0);
    real_ncpus=0;assert(memcheck_command(1,out,sizeof(out))>0);assert(allocations==0);
    puts("PASS actual memory diagnostic: concurrent 4/8 CPUs, corruption, wrong binding, allocation/start failure, cleanup");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path/'test.c').write_text(harness+source+tail)
    subprocess.run([os.environ.get('CC','cc'),'-std=gnu11','-O2','-pthread',str(path/'test.c'),'-o',str(path/'test')],check=True)
    subprocess.run([str(path/'test')],check=True,timeout=30)
