#!/usr/bin/env python3
"""Compile and exercise the actual kernel stack-intern function on a host.
Requires gcc/clang and pthreads. No kernel headers, network or device access.
"""
from pathlib import Path
import subprocess
import tempfile

SOURCE = Path(__file__).with_name('framebench_kernel.inc')


def main():
    source = SOURCE.read_text()
    structures = source[source.index('#define BC_EVENTS'):source.index('static struct bc_store *bc;')]
    function = source[source.index('static void\nbc_sample_put'):source.index('/* One bounded snapshot')]
    shim = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#define SP_KFRAMES 16
#define SP_UFRAMES 32
#define acquire __ATOMIC_ACQUIRE
#define release __ATOMIC_RELEASE
#define relaxed __ATOMIC_RELAXED
#define os_atomic_load(p,o) __atomic_load_n(p,o)
#define os_atomic_store(p,v,o) __atomic_store_n(p,v,o)
#define os_atomic_add_orig(p,v,o) __atomic_fetch_add(p,v,o)
#define os_atomic_inc(p,o) __atomic_add_fetch(p,1,o)
#define os_atomic_dec(p,o) __atomic_sub_fetch(p,1,o)
#define os_atomic_cmpxchg(p,v,n,o) ({ uint32_t expected_=(v); __atomic_compare_exchange_n(p,&expected_,n,false,o,relaxed); })
'''
    globals_ = r'''
static struct bc_store *bc;
static volatile uint32_t bc_writers, bc_phase=5, bc_ns, bc_nk, bc_sample_drop;
static volatile uint64_t sp_samples;
struct sp_rec { uint64_t hdr, tid, pidtrap, lr, event; };
static uint64_t mach_absolute_time(void) { return 1; }
static bool bc_sampling(uint64_t now) { (void)now; return true; }
'''
    test = r'''
static void *worker(void *arg) {
    uintptr_t id=(uintptr_t)arg;
    for (unsigned i=0; i<4000; i++) {
        uintptr_t k[1]={0x100000+id*16}, u[1]={0x200000+(i%512)*16};
        struct sp_rec r={.hdr=i, .tid=id, .pidtrap=id};
        bc_sample_put(&r,k,1,u,1);
    }
    return NULL;
}
int main(void) {
    bc=calloc(1,sizeof(*bc)); assert(bc);
    pthread_t t[8];
    for (uintptr_t i=0; i<8; i++) assert(!pthread_create(&t[i],NULL,worker,(void*)i));
    for (int i=0; i<8; i++) assert(!pthread_join(t[i],NULL));
    assert(bc_ns==32000 && sp_samples==32000 && bc_sample_drop==0 && bc_writers==0);
    for (unsigned i=0; i<bc_ns; i++) {
        struct bc_sample *s=&bc->samples[i];
        assert(s->stack<bc_nk && s->stack<BC_STACKS);
        struct bc_stack *k=&bc->stacks[s->stack];
        assert(k->nk==1 && k->nu==1 && k->frames[0]==0x100000+s->tid*16);
        assert(s->phase==5 && s->pidtrap==s->tid);
    }
    uintptr_t k[1]={0x100000}, u[1]={0x200000};
    struct sp_rec r={0};
    for (unsigned i=0; i<BC_SAMPLES; i++) bc_sample_put(&r,k,1,u,1);
    assert(bc_ns==32000+BC_SAMPLES && sp_samples==BC_SAMPLES);
    assert(bc_sample_drop==32000 && bc_writers==0);
    printf("PASS: eight concurrent writers, 32000 samples, no contention loss; capacity bounded; capture bytes %zu\n",sizeof(*bc));
    free(bc);
    return 0;
}
'''
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        c = root / 'intern.c'
        c.write_text(shim + structures + globals_ + function + test)
        exe = root / 'intern'
        subprocess.run(['gcc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-pthread', str(c), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True, timeout=15)


if __name__ == '__main__':
    main()
