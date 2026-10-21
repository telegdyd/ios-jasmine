/*
 * sweetd: a tiny remote command runner for the phone's iOS userland (jasmine).
 *
 * Started by launchd as root (tools/sweet-launchd.py adds the job to
 * /System/Library/xpc/launchd.plist), it listens on TCP port 5143 of the USB
 * Ethernet link (j0021) and runs one command per connection:
 *
 *   request:  "RUN <timeout-seconds> <argc>\n" then argc lines, one argument
 *             each (argv[0] is an absolute path)
 *   reply:    the command's stdout and stderr, merged, as they come, then
 *             "\n" SWEETD_END " <status>\n" where status is the exit code,
 *             -SIGNAL when killed, or -1000 when it could not be started
 *
 * The client is tools/sweet-sh.py. No authentication: the link is a USB
 * cable to one PC. Clients are served one at a time.
 */
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <poll.h>
#include <signal.h>
#include <spawn.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define PORT            5143
#define MAX_ARGS        64
#define MAX_LINE        4096
#define SWEETD_END      "__SWEETD_END__"

extern char **environ;

static int
read_line(int fd, char *buf, size_t max)
{
	size_t n = 0;
	while (n < max - 1) {
		char c;
		ssize_t r = read(fd, &c, 1);
		if (r <= 0) {
			return -1;
		}
		if (c == '\n') {
			break;
		}
		buf[n++] = c;
	}
	buf[n] = 0;
	return (int)n;
}

static void
send_all(int fd, const char *buf, size_t len)
{
	while (len > 0) {
		ssize_t w = write(fd, buf, len);
		if (w <= 0) {
			return;
		}
		buf += w;
		len -= (size_t)w;
	}
}

static void
serve(int cs)
{
	char line[MAX_LINE];
	char *argv[MAX_ARGS + 1];
	int timeout = 0, argc = 0;

	if (read_line(cs, line, sizeof(line)) < 0 || sscanf(line, "RUN %d %d", &timeout, &argc) != 2 ||
	    argc < 1 || argc > MAX_ARGS) {
		dprintf(cs, "bad request\n%s -1000\n", SWEETD_END);
		return;
	}
	for (int i = 0; i < argc; i++) {
		if (read_line(cs, line, sizeof(line)) < 0) {
			return;
		}
		argv[i] = strdup(line);
	}
	argv[argc] = NULL;

	int out[2];
	pid_t pid = -1;
	int status = -1000;
	if (pipe(out) == 0) {
		posix_spawn_file_actions_t fa;
		posix_spawn_file_actions_init(&fa);
		posix_spawn_file_actions_addopen(&fa, 0, "/dev/null", O_RDONLY, 0);
		posix_spawn_file_actions_adddup2(&fa, out[1], 1);
		posix_spawn_file_actions_adddup2(&fa, out[1], 2);
		posix_spawn_file_actions_addclose(&fa, out[0]);
		int err = posix_spawn(&pid, argv[0], &fa, NULL, argv, environ);
		posix_spawn_file_actions_destroy(&fa);
		close(out[1]);
		if (err != 0) {
			dprintf(cs, "sweetd: cannot start %s: %s\n", argv[0], strerror(err));
			pid = -1;
		}
		time_t deadline = time(NULL) + (timeout > 0 ? timeout : 3600);
		bool killed = false;
		for (;;) {
			struct pollfd p = { .fd = out[0], .events = POLLIN };
			int r = poll(&p, 1, 500);
			if (r > 0) {
				char buf[4096];
				ssize_t n = read(out[0], buf, sizeof(buf));
				if (n <= 0) {
					break;
				}
				send_all(cs, buf, (size_t)n);
			}
			if (pid > 0 && !killed && time(NULL) > deadline) {
				kill(pid, SIGKILL);
				killed = true;
				dprintf(cs, "\nsweetd: timeout after %d s, killed\n", timeout);
			}
			if (pid <= 0 && r == 0) {
				break;
			}
		}
		close(out[0]);
		if (pid > 0) {
			int st = 0;
			if (waitpid(pid, &st, 0) == pid) {
				status = WIFEXITED(st) ? WEXITSTATUS(st) : WIFSIGNALED(st) ? -WTERMSIG(st) : -1000;
			}
		}
	}
	dprintf(cs, "\n%s %d\n", SWEETD_END, status);
	for (int i = 0; i < argc; i++) {
		free(argv[i]);
	}
}

int
main(void)
{
	signal(SIGPIPE, SIG_IGN);
	int ls = socket(AF_INET, SOCK_STREAM, 0);
	int on = 1;
	setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &on, sizeof(on));
	struct sockaddr_in a = { .sin_len = sizeof(a), .sin_family = AF_INET, .sin_port = htons(PORT),
		                 .sin_addr.s_addr = htonl(INADDR_ANY) };
	while (bind(ls, (struct sockaddr *)&a, sizeof(a)) != 0 || listen(ls, 4) != 0) {
		sleep(2);       /* ue0 may not be up yet */
	}
	fprintf(stderr, "sweetd: listening on port %d\n", PORT);
	for (;;) {
		int cs = accept(ls, NULL, NULL);
		if (cs < 0) {
			continue;
		}
		serve(cs);
		close(cs);
	}
}
