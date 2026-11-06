/*
 * sweet_beep: play a test tone (or a raw file) through /dev/redwood-audio, without the audio server.
 *
 *   sweet_beep [-s SECONDS] [-f HZ] [-d DBFS] [-v BELOW_EIGHTHS_DB] [-r FILE.raw]
 *
 * Default: 2 s of 440 Hz at -20 dBFS. -r plays 48 kHz 16-bit stereo little-endian PCM from a file.
 * -v sets the device volume first (REDWOOD_AUDIO_SET_VOLUME, eighths of a dB under the top).
 * Writes 10 ms at a time, paced by the clock, as the audio server's I/O thread would.
 */
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

struct redwood_audio_volume { uint32_t below, muted; };
#define REDWOOD_AUDIO_SET_VOLUME _IOW('r', 1, struct redwood_audio_volume)

#define RATE    48000
#define CHUNK   480                     /* frames: 10 ms */

static uint64_t
now_ns(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

int
main(int argc, char **argv)
{
	double secs = 2, hz = 440, dbfs = -20;
	const char *raw = NULL;
	long below = -1;
	int c;

	while ((c = getopt(argc, argv, "s:f:d:v:r:")) != -1) {
		switch (c) {
		case 's': secs = atof(optarg); break;
		case 'f': hz = atof(optarg); break;
		case 'd': dbfs = atof(optarg); break;
		case 'v': below = atol(optarg); break;
		case 'r': raw = optarg; break;
		default:
			fprintf(stderr, "usage: sweet_beep [-s SECONDS] [-f HZ] [-d DBFS] [-v BELOW] [-r FILE.raw]\n");
			return 2;
		}
	}
	int fd = open("/dev/redwood-audio", O_WRONLY);
	if (fd < 0) {
		fprintf(stderr, "/dev/redwood-audio: %s\n", strerror(errno));
		return 1;
	}
	if (below >= 0) {
		struct redwood_audio_volume v = { (uint32_t)below, 0 };
		if (ioctl(fd, REDWOOD_AUDIO_SET_VOLUME, &v) != 0) {
			fprintf(stderr, "volume ioctl: %s\n", strerror(errno));
		}
	}
	FILE *in = NULL;
	if (raw != NULL && (in = fopen(raw, "rb")) == NULL) {
		fprintf(stderr, "%s: %s\n", raw, strerror(errno));
		return 1;
	}
	int16_t buf[CHUNK * 2];
	double amp = 32767.0 * pow(10.0, dbfs / 20.0), ph = 0, step = 2 * M_PI * hz / RATE;
	uint64_t t0 = now_ns(), frames = 0, total = in ? UINT64_MAX : (uint64_t)(secs * RATE);
	while (frames < total) {
		size_t n = CHUNK;
		if (in != NULL) {
			n = fread(buf, 4, CHUNK, in);
			if (n == 0) {
				break;
			}
		} else {
			for (size_t i = 0; i < n; i++) {
				int16_t v = (int16_t)lrint(amp * sin(ph));
				ph += step;
				buf[2 * i] = buf[2 * i + 1] = v;
			}
			if (ph > 2 * M_PI) {
				ph = fmod(ph, 2 * M_PI);
			}
		}
		if (write(fd, buf, n * 4) < 0) {
			fprintf(stderr, "write: %s\n", strerror(errno));
			return 1;
		}
		frames += n;
		uint64_t due = t0 + frames * 1000000000ull / RATE, t = now_ns();
		if (due > t + 2000000) {
			usleep((useconds_t)((due - t) / 1000 - 1000));     /* keep ~1 ms ahead */
		}
	}
	printf("played %llu frames (%.2f s)\n", (unsigned long long)frames, frames / (double)RATE);
	close(fd);
	return 0;
}
