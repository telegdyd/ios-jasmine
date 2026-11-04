/*
 * Move files or directories on the phone with rename(2) (the root has no mv, and sweet_cp
 * copies, which a nearly full root cannot afford):
 *   sweet_mv SRC DST [SRC DST ...]
 * Each DST must not exist and must be on the same filesystem as its SRC. Stops at the first
 * failure. Run it through sweetd.
 */
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

int
main(int argc, char **argv)
{
	if (argc < 3 || (argc - 1) % 2) {
		fprintf(stderr, "usage: sweet_mv SRC DST [SRC DST ...]\n");
		return 2;
	}
	for (int i = 1; i < argc; i += 2) {
		struct stat st;
		if (lstat(argv[i + 1], &st) == 0) {
			fprintf(stderr, "%s exists\n", argv[i + 1]);
			return 1;
		}
		if (rename(argv[i], argv[i + 1]) != 0) {
			fprintf(stderr, "rename %s -> %s: %s\n", argv[i], argv[i + 1], strerror(errno));
			return 1;
		}
		printf("%s -> %s\n", argv[i], argv[i + 1]);
	}
	return 0;
}
