/*
 * Check of kernel j0033's DYLD_* path: the sweetenv boot-arg puts variables
 * into this program's environment, the "AMFI" policy answers dyld's policy
 * call, and dyld then loads the DYLD_INSERT_LIBRARIES library. Boot with
 *   sweetenv=sweet_envtest:SWEET_ENVTEST=1,DYLD_INSERT_LIBRARIES=/usr/local/bin/sweet_inject.dylib
 * and run it through sweetd. Prints PASS or FAIL lines; exit 0 on PASS.
 */
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

int __mac_syscall(const char *policy, int call, void *arg);

int
main(void)
{
	const char *mark = getenv("SWEET_ENVTEST");
	const char *insert = getenv("DYLD_INSERT_LIBRARIES");
	uint64_t out = 0;
	struct {
		uint64_t in;
		uint64_t out;
	} arg = {0, (uint64_t)(uintptr_t)&out};
	int rc = __mac_syscall("AMFI", 90, &arg);
	int (*loaded)(void) = (int (*)(void))dlsym(RTLD_DEFAULT, "sweet_inject_loaded");
	int fail = 0;

	printf("sweet_envtest: SWEET_ENVTEST=%s\n", mark ? mark : "(unset)");
	printf("sweet_envtest: DYLD_INSERT_LIBRARIES=%s\n", insert ? insert : "(unset)");
	printf("sweet_envtest: AMFI dyld policy rc %d flags %#llx\n", rc, (unsigned long long)out);
	printf("sweet_envtest: injected library %s\n", loaded ? "loaded" : "not loaded");
	if (mark == NULL || mark[0] != '1') {
		printf("FAIL: sweetenv did not reach the environment\n");
		fail = 1;
	}
	if (rc != 0 || (out & 0x2) == 0) {
		printf("FAIL: dyld policy call refused or path variables not allowed\n");
		fail = 1;
	}
	if (loaded == NULL || loaded() != 1) {
		printf("FAIL: DYLD_INSERT_LIBRARIES library not in the process\n");
		fail = 1;
	}
	printf(fail ? "FAIL\n" : "PASS: sweetenv + dyld policy + library insertion\n");
	return fail;
}
