#!/bin/bash
# Wait for CI runs; re-run one whose jobs no hosted runner picked up
# (macOS arm64 capacity: "The job was not acquired by Runner"), up to 4 times.
#   bash tools/g2/ci-wait.sh RUN...
G="/c/Program Files/GitHub CLI/gh"
R=telegdyd/ios-jasmine
for run in "$@"; do
	for attempt in 1 2 3 4 5; do
		"$G" run watch $run -R $R --exit-status --interval 30 >/dev/null 2>&1
		c=$("$G" run view $run -R $R --json conclusion -q .conclusion)
		echo "run $run attempt $attempt: $c"
		[ "$c" = success ] && break
		why=""
		for try in 1 2 3; do       # the API answers 502 now and then
			job=$("$G" api repos/$R/actions/runs/$run/jobs -q '[.jobs[] | select(.conclusion != "skipped")][0].id')
			[ -n "$job" ] && why=$("$G" api repos/$R/check-runs/$job/annotations -q '.[].message') && break
			sleep 10
		done
		echo "$why" | grep -q "not acquired by Runner" || exit 1
		[ $attempt = 5 ] && exit 1
		"$G" run rerun $run -R $R || exit 1
		sleep 20
	done
done
