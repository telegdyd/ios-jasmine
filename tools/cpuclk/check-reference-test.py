#!/usr/bin/env python3
"""Compile and exercise the actual sweet_osm_init function with host stubs.

Usage: python3 tools/cpuclk/check-reference-test.py XNU/osfmk/arm64/sweet_osm.c
This tests initialization branches, not ARM code generation or device behavior.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    source = args.source.read_text()
    start = source.index("void\nsweet_osm_init(void)")
    opening = source.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    function = source[start:end]
    harness = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
typedef void *thread_t;
#define KERN_SUCCESS 0
#define OSM_WORK 123
static uint32_t osm_mode, input_mode, input_cmd;
static uint64_t osm_ref, osm_ns_boot;
static unsigned work_calls, thread_calls, dealloc_calls;
static void osm_thread(void) {}
static void osm_watch_thread(void) {}
static int PE_parse_boot_argn(const char *key, uint32_t *value, unsigned size) {
    (void)size;
    if (!strcmp(key, "sweetosm")) { *value=input_mode; return input_mode!=0; }
    if (!strcmp(key, "sweetcmd")) { *value=input_cmd; return input_cmd!=0; }
    return 0;
}
static uint64_t mach_absolute_time(void) { return 10; }
static uint64_t osm_workload(uint64_t n) { assert(n==OSM_WORK); ++work_calls; return 0x12345678; }
static void absolutetime_to_nanoseconds(uint64_t t, uint64_t *out) { *out=t; }
static int kernel_thread_start(void (*entry)(void), void *arg, thread_t *thread) {
    (void)entry; (void)arg; *thread=NULL; ++thread_calls; return KERN_SUCCESS;
}
static void thread_deallocate(thread_t t) { (void)t; ++dealloc_calls; }
'''
    if 'sweet_dvfs_start();' in function:
        harness += 'static void sweet_dvfs_start(void) {}\n'
    harness += function + r'''
static void scenario(unsigned mode, unsigned cmd, unsigned expected_work, unsigned expected_threads) {
    input_mode=mode; input_cmd=cmd; osm_mode=0; osm_ref=0;
    work_calls=thread_calls=dealloc_calls=0;
    sweet_osm_init();
    assert(work_calls==expected_work);
    assert(thread_calls==expected_threads && dealloc_calls==expected_threads);
    assert(osm_ref==(expected_work ? 0x12345678 : 0));
}
int main(void) {
    scenario(0, 0, 0, 0);  /* ordinary boot stays inert */
    scenario(0, 1, 1, 0);  /* live checker has reference, no OSM workers */
    scenario(1, 0, 1, 2);  /* original probe/watch retained */
    scenario(8, 1, 1, 2);  /* original table/watch retained */
    puts("CPU checker init: four scenarios PASS");
}
'''
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path / "check.c").write_text(harness)
        subprocess.run([os.environ.get("CC", "cc"), "-std=c11", "-Wall", "-Wextra",
                        "-Werror", str(path / "check.c"), "-o", str(path / "check")], check=True)
        subprocess.run([str(path / "check")], check=True)


if __name__ == "__main__":
    main()
