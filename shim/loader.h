#pragma once
#include <stdint.h>

/* Boot the SWEETXNU payload found in the ABL ramdisk; returns only on error. */
const char *loader_boot(uintptr_t dtb);

/* shim.c: last step before the jump (powers the parked silver boot core off for cpus>4). */
void shim_before_xnu(const char *cmdline);
