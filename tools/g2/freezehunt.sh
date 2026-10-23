#!/bin/bash
# PERF-TASKS task 14: boot KTAG with ARGS up to N times, no gestures. A boot is clean as soon as
# backboardd's 10-second line shows >= 25 submits (the lock screen draws); it is frozen when that
# has not happened LIMIT s after the boot. On the first freeze: a full census (j0069, `all`) of
# backboardd and SpringBoard into logs/prof-TAG-N, then stop. Logs: logs/netlog-TAG-N.txt.
#   N=6 LIMIT=150 bash tools/g2/freezehunt.sh KTAG TAG "ARGS"
K=${1:?usage: freezehunt.sh KTAG TAG "ARGS"}
T=${2:?}
ARGS=${3:-}
cd "/c/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine" || exit 1
export MSYS_NO_PATHCONV=1
L="${PHONE_LOCK:-C:/Users/teleg/AppData/Local/Claude-Data/claude_pzs8sxrjxfjjc/side-session-notes/local_b57c5c9a-db18-434e-a448-e6d69fa0dddf/phone.lock}"
( set -C; echo "freezehunt $T ($$), $(date +%H:%M:%S)" > "$L" ) 2>/dev/null || { echo "phone busy: $(cat "$L")"; exit 2; }
trap 'grep -q "freezehunt $T ($$)" "$L" 2>/dev/null && rm -f "$L"' EXIT
for n in $(seq 1 ${N:-6}); do
	LOG=logs/netlog-$T-$n.txt
	rm -f "$LOG" "$LOG.run"
	AMP=1 CPUS=4 SECS=$((${LIMIT:-150} + 120)) bash tools/cpuclk/osm-round.sh - $K "sweetosm=0 sweetcmd=1 $ARGS" "$LOG" > /dev/null 2>&1 &
	R=$!
	for i in $(seq 1 150); do grep -q "^# booted" "$LOG.run" 2>/dev/null && break; sleep 2; done
	if ! grep -q "^# booted" "$LOG.run" 2>/dev/null; then
		# the reboot into fastboot hung (a command-port reboot can hang in shutdown): power + volume-down
		echo "$(date +%T) boot $n: no boot ($(grep -v '^#' "$LOG.run" | tail -1)); stopped"
		kill $R 2>/dev/null
		exit 1
	fi
	t0=$(date +%s)
	verdict=frozen
	while [ $(( $(date +%s) - t0 )) -lt ${LIMIT:-150} ]; do
		if grep -aq "PANIC\|panic(cpu" "$LOG" 2>/dev/null; then verdict=panic; break; fi
		# (-a: a stray byte makes grep call the log binary and print "Binary file matches", t14h-5)
		if grep -aoE "SWEET GPU: backboardd: [0-9]+ submits" "$LOG" 2>/dev/null |
		    awk '$4 ~ /^[0-9]+$/ && $4 + 0 >= 25 {f=1} END {exit !f}'; then
			verdict=clean; break
		fi
		sleep 3
	done
	echo "$(date +%T) boot $n: $verdict after $(( $(date +%s) - t0 )) s; $(grep -aoE 'backboardd: [0-9]+ submits' "$LOG" | tr '\n' ' ')"
	if [ $verdict != clean ]; then
		python tools/g2/prof.py fetch logs/prof-$T-$n --secs 3 --census 200000 --tasks backboardd,SpringBoard,all 2>&1 | tail -1
		python -c "import sys; sys.path.insert(0, 'tools/g2'); import prof; print(prof.cmd('gpu state'))"
		wait $R
		exit 0
	fi
	kill $R 2>/dev/null; pkill -f "sweet-run.py.*$LOG" 2>/dev/null
	wait $R 2>/dev/null
done
echo "no freeze in ${N:-6} boots"
