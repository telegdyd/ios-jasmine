/*
 * sweet_growfs: grow the mounted HFS+ root to fill its partition (iOS has no hfs_resize / diskutil).
 *
 *   sweet_growfs [-y] [-s BYTES] [MOUNTPOINT [DEVICE]]   default / and /dev/ufsroot0
 *
 * -s BYTES: target size instead of the whole device (the mounted root device refuses a second open, and on
 * jasmine the last 4 MiB of userdata hold the SWEET console log: stay below it).
 *
 * Reads the device size (DKIOCGETBLOCKSIZE x DKIOCGETBLOCKCOUNT) and the volume's block size, prints the
 * current and the possible size, and with -y asks HFS to extend the volume in place
 * (fsctl HFSIOC_RESIZE_VOLUME -> hfs_extendfs: journaled, grows the allocation bitmap, moves the
 * alternate volume header to the end of the partition). Without -y it only reports.
 */
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mount.h>
#include <unistd.h>

/* sys/disk.h and sys/fsctl.h are not in the iOS SDK (libSystem has fsctl) */
int fsctl(const char *, unsigned long, void *, unsigned int);
#define DKIOCGETBLOCKSIZE       _IOR('d', 24, uint32_t)
#define DKIOCGETBLOCKCOUNT      _IOR('d', 25, uint64_t)
#define HFSIOC_RESIZE_PROGRESS  _IOR('h', 1, u_int32_t)
#define HFSIOC_RESIZE_VOLUME    _IOW('h', 2, u_int64_t)

int
main(int argc, char **argv)
{
	int yes = 0, c;
	uint64_t size_arg = 0;
	while ((c = getopt(argc, argv, "ys:")) != -1) {
		if (c == 'y') {
			yes = 1;
		} else if (c == 's') {
			size_arg = strtoull(optarg, NULL, 0);
		} else {
			fprintf(stderr, "usage: sweet_growfs [-y] [-s BYTES] [MOUNTPOINT [DEVICE]]\n");
			return 2;
		}
	}
	const char *mnt = optind < argc ? argv[optind] : "/";
	const char *dev = optind + 1 < argc ? argv[optind + 1] : "/dev/ufsroot0";

	struct statfs sf;
	if (statfs(mnt, &sf) != 0) {
		fprintf(stderr, "statfs %s: %s\n", mnt, strerror(errno));
		return 1;
	}
	if (strcmp(sf.f_fstypename, "hfs") != 0) {
		fprintf(stderr, "%s is %s, not hfs\n", mnt, sf.f_fstypename);
		return 1;
	}
	uint32_t bsz = 512;
	uint64_t cnt = size_arg / 512;
	if (size_arg == 0) {
		/* the mounted root device may refuse a second open (EBUSY): then pass -s */
		int fd = open(dev, O_RDONLY);
		if (fd < 0) {
			fprintf(stderr, "%s: %s (pass -s BYTES)\n", dev, strerror(errno));
			return 1;
		}
		if (ioctl(fd, DKIOCGETBLOCKSIZE, &bsz) != 0 || ioctl(fd, DKIOCGETBLOCKCOUNT, &cnt) != 0 || bsz == 0) {
			fprintf(stderr, "%s: block size/count: %s\n", dev, strerror(errno));
			return 1;
		}
		close(fd);
	}
	uint64_t devbytes = size_arg ? size_arg : (uint64_t)bsz * cnt, fsbytes = (uint64_t)sf.f_bsize * sf.f_blocks;
	uint64_t want = devbytes - devbytes % sf.f_bsize;          /* whole allocation blocks */
	printf("%s on %s (%s): volume %.2f GiB (%llu blocks of %u), free %.2f GiB\n", mnt, sf.f_mntfromname, dev,
	    fsbytes / 1073741824.0, (unsigned long long)sf.f_blocks, sf.f_bsize, sf.f_bavail * (double)sf.f_bsize / 1073741824.0);
	printf("device %.2f GiB (%llu x %u); can grow to %llu bytes (%.2f GiB)\n", devbytes / 1073741824.0,
	    (unsigned long long)cnt, bsz, (unsigned long long)want, want / 1073741824.0);
	if (want <= fsbytes) {
		printf("nothing to grow\n");
		return 0;
	}
	if (!yes) {
		printf("dry run: pass -y to grow\n");
		return 0;
	}
	printf("growing...\n");
	fflush(stdout);
	if (fsctl(mnt, HFSIOC_RESIZE_VOLUME, &want, 0) != 0) {
		fprintf(stderr, "HFSIOC_RESIZE_VOLUME: %s\n", strerror(errno));
		return 1;
	}
	if (statfs(mnt, &sf) == 0) {
		printf("done: volume %.2f GiB, free %.2f GiB\n", (double)sf.f_bsize * sf.f_blocks / 1073741824.0,
		    sf.f_bavail * (double)sf.f_bsize / 1073741824.0);
	}
	return 0;
}
