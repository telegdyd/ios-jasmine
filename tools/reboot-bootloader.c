/*
 * reboot-bootloader: reboot a Linux (the postmarketOS initramfs shell) into
 * fastboot. busybox's reboot cannot pass the "bootloader" argument that the
 * qcom-pon reboot-mode driver turns into the PMIC PON reboot mode ABL reads.
 * Static aarch64 build, pushed with tools/pmos-push.py:
 *   aarch64-linux-gnu-gcc -static -O2 -o reboot-bootloader tools/reboot-bootloader.c
 */
#include <linux/reboot.h>
#include <stdio.h>
#include <sys/syscall.h>
#include <unistd.h>

int
main(void)
{
	sync();
	syscall(SYS_reboot, LINUX_REBOOT_MAGIC1, LINUX_REBOOT_MAGIC2, LINUX_REBOOT_CMD_RESTART2, "bootloader");
	perror("reboot");
	return 1;
}
