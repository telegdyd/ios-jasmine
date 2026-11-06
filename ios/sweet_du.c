/*
 * sweet_du: disk usage by directory (the iOS root has no du).
 *
 *   sweet_du [-d DEPTH] [-m MIN_MB] PATH
 *
 * Walks PATH on its own file system (does not cross mounts), adds up allocated blocks (st_blocks; a file
 * with N hard links counts 1/N at each link) and prints "MB path" for every directory at most DEPTH below PATH (default 2) that
 * holds at least MIN_MB (default 50), deepest first, then the total.
 */
#include <errno.h>
#include <fts.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define MAXDEPTH 64

int
main(int argc, char **argv)
{
	int depth = 2, c;
	double min_mb = 50;

	while ((c = getopt(argc, argv, "d:m:")) != -1) {
		switch (c) {
		case 'd': depth = atoi(optarg); break;
		case 'm': min_mb = atof(optarg); break;
		default:
			fprintf(stderr, "usage: sweet_du [-d DEPTH] [-m MIN_MB] PATH\n");
			return 2;
		}
	}
	if (optind >= argc) {
		fprintf(stderr, "usage: sweet_du [-d DEPTH] [-m MIN_MB] PATH\n");
		return 2;
	}
	char *paths[2] = { argv[optind], NULL };
	FTS *f = fts_open(paths, FTS_PHYSICAL | FTS_XDEV | FTS_NOCHDIR, NULL);
	if (f == NULL) {
		fprintf(stderr, "%s: %s\n", argv[optind], strerror(errno));
		return 1;
	}
	uint64_t sum[MAXDEPTH] = { 0 }, total = 0, errors = 0;
	FTSENT *e;
	while ((e = fts_read(f)) != NULL) {
		int lv = (int)e->fts_level;
		if (lv >= MAXDEPTH) {
			lv = MAXDEPTH - 1;
		}
		switch (e->fts_info) {
		case FTS_D:
			sum[lv] = 0;
			break;
		case FTS_DP: {
			uint64_t s = sum[lv] + (e->fts_statp ? (uint64_t)e->fts_statp->st_blocks * 512 : 0);
			if (lv <= depth && s >= (uint64_t)(min_mb * 1048576)) {
				printf("%8.0f MB  %s\n", s / 1048576.0, e->fts_path);
			}
			if (lv > 0) {
				sum[lv - 1] += s;
			} else {
				total = s;
			}
			break;
		}
		case FTS_DNR:
		case FTS_ERR:
		case FTS_NS:
			errors++;
			break;
		default:
			if (e->fts_statp != NULL) {
				uint64_t s = (uint64_t)e->fts_statp->st_blocks * 512;
				if (e->fts_statp->st_nlink > 1) {
					s /= e->fts_statp->st_nlink;      /* hard links: shared out */
				}
				if (lv > 0) {
					sum[lv - 1] += s;
				}
			}
			break;
		}
	}
	fts_close(f);
	printf("%8.0f MB  total (%llu unreadable)\n", total / 1048576.0, (unsigned long long)errors);
	return 0;
}
