/*
 * Static /init for the stock-kernel OSM reference (jasmine, 2026-10-22).
 * Replaces Android's ramdisk in the backed-up msm-4.4 boot image, so no Android
 * userspace runs and nothing touches a partition. The kernel's own OSM / CPRh
 * drivers have probed by then (arch_initcall). This logs, as "SWEETREF" lines in
 * the kernel log (which the kernel keeps in ramoops at 0xa0000000 over a warm
 * reboot): cpu4's cpufreq state, the OSM driver's debugfs clock measurement,
 * and the time of a fixed workload with cpu4 pinned at its lowest and highest
 * frequency. Then it reboots into fastboot.
 *   aarch64-linux-gnu-gcc -static -O2 -o init refinit.c
 */
#define _GNU_SOURCE
#include <fcntl.h>
#include <sched.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>
#include <linux/reboot.h>

#ifndef REF_FIRST_SLEEP
#define REF_FIRST_SLEEP 5
#endif
static int kmsg = -1;

static void
rlog(const char *fmt, ...)
{
	char buf[600];
	va_list ap;
	int n = snprintf(buf, sizeof(buf), "<0>SWEETREF: ");
	va_start(ap, fmt);
	n += vsnprintf(buf + n, sizeof(buf) - n, fmt, ap);
	va_end(ap);
	if (kmsg >= 0) {
		(void)write(kmsg, buf, (size_t)n);
	}
}

static void
cat(const char *path)
{
	char buf[512];
	int fd = open(path, O_RDONLY);
	if (fd < 0) {
		rlog("%s: (missing)\n", path);
		return;
	}
	ssize_t n = read(fd, buf, sizeof(buf) - 1);
	close(fd);
	buf[n > 0 ? n : 0] = 0;
	for (char *p = buf; *p; p++) {
		if (*p == '\n' && p[1]) {
			*p = ' ';
		}
	}
	rlog("%s: %s%s", path, buf, (n > 0 && buf[n - 1] == '\n') ? "" : "\n");
}

static void
put(const char *path, const char *val)
{
	int fd = open(path, O_WRONLY);
	if (fd >= 0) {
		(void)write(fd, val, strlen(val));
		close(fd);
	}
	rlog("%s <- %s%s\n", path, val, fd < 0 ? " (failed)" : "");
}

static volatile uint64_t seed = 0x9e3779b97f4a7c15ull;

static uint64_t
work(uint64_t n)                        /* the j0015 workload */
{
	uint64_t x = seed, h = 0;
	for (uint64_t i = 0; i < n; i++) {
		x = x * 6364136223846793005ull + 1442695040888963407ull;
		h ^= (x >> 17) + (h << 5) + (h >> 2);
		h = (h << 7) | (h >> 57);
	}
	return h;
}

static uint64_t
timed(const char *what)                 /* returns the estimated MHz */
{
	struct timespec a, b;
	clock_gettime(CLOCK_MONOTONIC, &a);
	uint64_t r = work(4000000);
	clock_gettime(CLOCK_MONOTONIC, &b);
	uint64_t us = (uint64_t)(b.tv_sec - a.tv_sec) * 1000000 + (uint64_t)(b.tv_nsec - a.tv_nsec) / 1000;
	/* 14227 us = 1747.2 MHz on XNU (j0015) */
	rlog("%s: workload %llu us (~%llu MHz), result %016llx\n", what, (unsigned long long)us,
	    (unsigned long long)(1747ull * 14227 / (us ? us : 1)), (unsigned long long)r);
	return 1747ull * 14227 / (us ? us : 1);
}

int
main(void)
{
	mkdir("/dev", 0755);
	mkdir("/proc", 0755);
	mkdir("/sys", 0755);
	mount("devtmpfs", "/dev", "devtmpfs", 0, NULL);
	mount("proc", "/proc", "proc", 0, NULL);
	mount("sysfs", "/sys", "sysfs", 0, NULL);
	mkdir("/sys/kernel/debug", 0755);
	mount("debugfs", "/sys/kernel/debug", "debugfs", 0, NULL);
	kmsg = open("/dev/kmsg", O_WRONLY);
	rlog("start\n");
	sleep(5);

	cpu_set_t set;
	CPU_ZERO(&set);
	CPU_SET(4, &set);
	rlog("pinned to cpu4: %s\n", sched_setaffinity(0, sizeof(set), &set) == 0 ? "yes" : "no");
	const char *cf = "/sys/devices/system/cpu/cpu4/cpufreq/";
	char p[160];
	static const char *files[] = { "scaling_driver", "scaling_governor", "scaling_available_frequencies",
		"cpuinfo_cur_freq", "scaling_cur_freq", "scaling_min_freq", "scaling_max_freq" };
	for (unsigned i = 0; i < sizeof(files) / sizeof(files[0]); i++) {
		snprintf(p, sizeof(p), "%s%s", cf, files[i]);
		cat(p);
	}
	cat("/sys/kernel/debug/clk/perfcl_clk/measure");
	cat("/sys/kernel/debug/clk/perfcl_clk/clk_rate");
	cat("/sys/kernel/debug/clk/pwrcl_clk/measure");

	snprintf(p, sizeof(p), "%sscaling_governor", cf);
	put(p, "userspace");
	static const char *steps[] = { "300000", "1747200", "2208000" };
	uint64_t mhz[3] = { 1, 1, 1 };
	for (unsigned i = 0; i < 3; i++) {
		snprintf(p, sizeof(p), "%sscaling_setspeed", cf);
		put(p, steps[i]);
		sleep(1);
		snprintf(p, sizeof(p), "%scpuinfo_cur_freq", cf);
		cat(p);
		cat("/sys/kernel/debug/clk/perfcl_clk/measure");
		char what[32];
		snprintf(what, sizeof(what), "cpu4 at %s kHz", steps[i]);
		mhz[i] = timed(what);
	}
	cat("/proc/cmdline");
	/*
	 * The answer also goes out as time, in case nothing of the log survives: the
	 * reboot waits 10 s per unit of speed ratio 2208-setting : 300-setting (OSM
	 * scaling: ~7 -> ~70 s; clock not following: ~1 -> ~10 s). The PC measures
	 * fastboot boot -> fastboot again (about 23 s without the wait).
	 */
	uint64_t ratio10 = mhz[0] ? mhz[2] * 10 / mhz[0] : 10;
	if (ratio10 > 120) {
		ratio10 = 120;
	}
	rlog("done: %llu / %llu / %llu MHz, ratio %llu.%llu; rebooting into fastboot in %llu s\n",
	    (unsigned long long)mhz[0], (unsigned long long)mhz[1], (unsigned long long)mhz[2],
	    (unsigned long long)(ratio10 / 10), (unsigned long long)(ratio10 % 10), (unsigned long long)ratio10);
	sync();
	sleep((unsigned)ratio10);
	syscall(SYS_reboot, LINUX_REBOOT_MAGIC1, LINUX_REBOOT_MAGIC2, LINUX_REBOOT_CMD_RESTART2, "bootloader");
	for (;;) {
		pause();
	}
}
