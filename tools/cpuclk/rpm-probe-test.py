#!/usr/bin/env python3
"""Host-test the actual gated, voltage-neutral CPU RPM probe function.

Usage: python3 tools/cpuclk/rpm-probe-test.py XNU/bsd/dev/sweet_rpm.c
This verifies request construction and refusal paths, not PMIC behavior.
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
    source = args.source.read_text()
    start = source.index('bool\nsweet_rpm_cpu_probe(uint32_t id)')
    opening = source.index('{', start)
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    harness = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <assert.h>
#define KEY_SWEN 0x6e657773u
static unsigned opt_in, calls, reads, locked, requested_id;
static bool bad_before, bad_enable, bad_read, bad_after, ack;
static int sweet_rpm_lock;
static int PE_parse_boot_argn(const char *key, uint32_t *v, unsigned size) {
    (void)key; (void)size; *v=opt_in; return opt_in!=0;
}
static void lck_mtx_lock(int *l) { (void)l; assert(!locked); locked=1; }
static void lck_mtx_unlock(int *l) { (void)l; assert(locked); locked=0; }
static int sweet_pmic_peek(unsigned sid, unsigned addr, unsigned n, uint32_t *out) {
    assert(!locked && sid==1);
    unsigned base=0x1400+(requested_id-1)*0x300;
    ++reads;
    if (bad_read) return -1;
    unsigned mv=requested_id==1 ? 872 : 868;
    if (n==4) {
        assert(addr==base+0x40);
        *out=mv|(mv<<16);
        if (bad_before || (bad_after && reads>=3)) *out^=4;
    } else { assert(n==1 && addr==base+0x46); *out=bad_enable ? 0 : 0x80; }
    return 0;
}
static bool rpm_request(const char *what, uint32_t set, uint32_t type,
                        uint32_t id, const uint32_t *kv, unsigned nkvp) {
    (void)what;
    assert(locked && set==0 && type==0x61706d73 && id==requested_id && nkvp==2);
    assert(kv[0]==0x7675 && kv[1]==(id==1 ? 872000u : 868000u));
    assert(kv[2]==KEY_SWEN && kv[3]==1); /* one request, never implicit disable */
    ++calls; return ack;
}
'''
    harness += source[start:end] + r'''
static void reset(unsigned id) {
    requested_id=id; opt_in=1; calls=reads=locked=0;
    bad_before=bad_enable=bad_read=bad_after=false; ack=true;
}
int main(void) {
    reset(2); opt_in=0; assert(!sweet_rpm_cpu_probe(2) && !reads && !calls);
    reset(2); opt_in=2; assert(!sweet_rpm_cpu_probe(2) && !reads && !calls);
    reset(0); assert(!sweet_rpm_cpu_probe(0) && !reads && !calls);
    reset(4); assert(!sweet_rpm_cpu_probe(4) && !reads && !calls);
    reset(2); bad_before=true; assert(!sweet_rpm_cpu_probe(2) && !calls);
    reset(2); bad_enable=true; assert(!sweet_rpm_cpu_probe(2) && !calls);
    reset(2); bad_read=true; assert(!sweet_rpm_cpu_probe(2) && !calls);
    for (unsigned id=1; id<=3; ++id) {
        reset(id); assert(sweet_rpm_cpu_probe(id) && calls==1 && reads==4 && !locked);
    }
    reset(2); ack=false; assert(!sweet_rpm_cpu_probe(2) && calls==1 && !locked);
    reset(2); bad_after=true; assert(!sweet_rpm_cpu_probe(2) && calls==1 && !locked);
    puts("CPU RPM neutral probe: 12 scenarios PASS");
}
'''
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path/'probe.c').write_text(harness)
        subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-Wall', '-Wextra', '-Werror',
                        str(path/'probe.c'), '-o', str(path/'probe')], check=True)
        subprocess.run([str(path/'probe')], check=True)


if __name__ == '__main__':
    main()
