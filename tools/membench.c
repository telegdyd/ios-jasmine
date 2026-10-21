/* membench: 64 MiB write / read / copy bandwidth on one CPU (Linux reference for the XNU bench) */
#define _GNU_SOURCE
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static double now(void)
{
	struct timespec t;
	clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec + t.tv_nsec / 1e9;
}

int main(int argc, char **argv)
{
	int cpu = argc > 1 ? atoi(argv[1]) : -1;
	if (cpu >= 0) {
		cpu_set_t s;
		CPU_ZERO(&s);
		CPU_SET(cpu, &s);
		if (sched_setaffinity(0, sizeof(s), &s)) {
			perror("affinity");
		}
	}
	size_t size = 64u << 20;
	uint8_t *b = aligned_alloc(4096, size);
	memset(b, 1, size);
	double t0 = now();
	for (int i = 0; i < 3; i++) { memset(b, i + 2, size); __asm__ volatile("" : : "r"(b) : "memory"); }
	double tw = now() - t0;
	volatile uint64_t sum = 0;
	t0 = now();
	for (int i = 0; i < 3; i++) {
		const uint64_t *p = (const uint64_t *)b;
		uint64_t s = 0;
		for (size_t k = 0; k < size / 8; k += 4) s += p[k] + p[k + 1] + p[k + 2] + p[k + 3];
		sum += s;
	}
	double tr = now() - t0;
	t0 = now();
	for (int i = 0; i < 3; i++) { b[i] ^= 1; __asm__ volatile("" : : "r"(b) : "memory"); memcpy(b + size / 2, b, size / 2); __asm__ volatile("" : : "r"(b) : "memory"); sum += b[size / 2 + i]; }
	double tc = now() - t0;
	printf("cpu %d: write %.0f MB/s, read %.0f MB/s, copy %.0f MB/s\n", cpu,
	    3 * size / tw / 1e6, 3 * size / tr / 1e6, 3 * (size / 2) / tc / 1e6);
	return 0;
}
