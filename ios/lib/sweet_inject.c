/* The library sweet_envtest expects dyld to insert (DYLD_INSERT_LIBRARIES). */
#include <stdio.h>

static int loaded;

__attribute__((constructor)) static void
sweet_inject_init(void)
{
	loaded = 1;
	fprintf(stderr, "sweet_inject: constructor ran\n");
}

__attribute__((visibility("default"))) int
sweet_inject_loaded(void)
{
	return loaded;
}
