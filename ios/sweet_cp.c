/*
 * Copy a file or a directory tree on the phone (the root has no cp, and the file server's
 * PUT/GET paths cannot contain spaces):
 *   sweet_cp SRC DST
 * DST must not exist. Directories keep their mode, files their mode and bytes; owner is the
 * caller's (root through sweetd). Prints one line per file and a total. Run it through sweetd.
 */
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static unsigned long long total;
static unsigned files;

static int
copy_file(const char *src, const char *dst, mode_t mode)
{
	int in = open(src, O_RDONLY);
	if (in < 0) { fprintf(stderr, "open %s: %s\n", src, strerror(errno)); return -1; }
	int out = open(dst, O_WRONLY | O_CREAT | O_EXCL, mode & 07777);
	if (out < 0) { fprintf(stderr, "create %s: %s\n", dst, strerror(errno)); close(in); return -1; }
	char buf[65536];
	ssize_t n;
	unsigned long long bytes = 0;
	while ((n = read(in, buf, sizeof(buf))) > 0) {
		for (ssize_t done = 0; done < n;) {
			ssize_t w = write(out, buf + done, (size_t)(n - done));
			if (w <= 0) { fprintf(stderr, "write %s: %s\n", dst, strerror(errno)); close(in); close(out); return -1; }
			done += w;
		}
		bytes += (unsigned long long)n;
	}
	int bad = n < 0 || fsync(out) != 0;
	close(in);
	if (close(out) != 0 || bad) { fprintf(stderr, "copy %s: %s\n", src, strerror(errno)); return -1; }
	/* read both back and compare: the file server cannot read these paths (spaces) */
	FILE *a = fopen(src, "rb"), *b = fopen(dst, "rb");
	int same = a && b;
	while (same) {
		char x[65536], y[65536];
		size_t na = fread(x, 1, sizeof(x), a), nb = fread(y, 1, sizeof(y), b);
		if (na != nb || memcmp(x, y, na)) same = 0;
		if (na == 0) break;
	}
	if (a) fclose(a);
	if (b) fclose(b);
	if (!same) { fprintf(stderr, "verify %s: copy differs\n", dst); return -1; }
	printf("%llu %s (verified)\n", bytes, dst);
	total += bytes;
	files++;
	return 0;
}

static int
copy_tree(const char *src, const char *dst)
{
	struct stat st;
	if (lstat(src, &st) != 0) { fprintf(stderr, "stat %s: %s\n", src, strerror(errno)); return -1; }
	if (S_ISREG(st.st_mode)) return copy_file(src, dst, st.st_mode);
	if (!S_ISDIR(st.st_mode)) { fprintf(stderr, "%s: not a file or directory, skipped\n", src); return -1; }
	if (mkdir(dst, st.st_mode & 07777) != 0 && errno != EEXIST) { fprintf(stderr, "mkdir %s: %s\n", dst, strerror(errno)); return -1; }
	DIR *d = opendir(src);
	if (!d) { fprintf(stderr, "opendir %s: %s\n", src, strerror(errno)); return -1; }
	int rc = 0;
	struct dirent *e;
	while ((e = readdir(d)) != NULL) {
		if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
		char s[1024], t[1024];
		if (snprintf(s, sizeof(s), "%s/%s", src, e->d_name) >= (int)sizeof(s) ||
		    snprintf(t, sizeof(t), "%s/%s", dst, e->d_name) >= (int)sizeof(t)) {
			fprintf(stderr, "path too long under %s\n", src);
			rc = -1;
			continue;
		}
		if (copy_tree(s, t) != 0) rc = -1;
	}
	closedir(d);
	return rc;
}

int
main(int argc, char **argv)
{
	if (argc != 3) { fprintf(stderr, "usage: sweet_cp SRC DST\n"); return 2; }
	int rc = copy_tree(argv[1], argv[2]);
	printf("%s: %u files, %llu bytes\n", rc ? "FAILED" : "done", files, total);
	return rc ? 1 : 0;
}
