#!/bin/bash
# DDR clock round (j0064, PERF-TASKS.md task 9): boot xnu/out-jasmine-KTAG like clkround.sh, then in
# one boot: "ddr state", "ddr bench" and bus counters at the bootloader's DDR rate (idle, then the
# bwmon calibration with a known read load), a uibench play there, and for each rate in LEVELS
# "ddr MHZ" (the first one hands every RPM clock off and turns RPM clock scaling on), "ddr state",
# "ddr bench" and a play. During every play "ddr bw 10000 bg" samples the bus counters every ~11 s
# (results in the log). Stops at the first rate whose vote fails or loses the phone (sweetwdt=20).
#   AMP=1 CPUS=4 LEVELS="1296 768 1804 1017 1296 1804" bash tools/g2/ddrround.sh KTAG TAG "ARGS"
# Log logs/netlog-TAG-ddr.txt; per-rate summary from tools/g2/ddrsum.py at the end.
K=${1:?usage: ddrround.sh KTAG TAG "ARGS"}
T=${2:?}
ARGS=${3:-}
LEVELS=${LEVELS-1296 768 1804 1017 1296 1804}
cd "/c/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine" || exit 1
export MSYS_NO_PATHCONV=1
L="${PHONE_LOCK:-C:/Users/teleg/AppData/Local/Claude-Data/claude_pzs8sxrjxfjjc/side-session-notes/local_b57c5c9a-db18-434e-a448-e6d69fa0dddf/phone.lock}"
( set -C; echo "ddrround $T ($$), $(date +%H:%M:%S)" > "$L" ) 2>/dev/null || { echo "phone busy: $(cat "$L")"; exit 2; }
trap 'grep -q "ddrround $T ($$)" "$L" 2>/dev/null && rm -f "$L"' EXIT
LOG=logs/netlog-$T-ddr.txt
[ "$K" = "$T" ] || { rm -rf xnu/out-jasmine-$T; cp -r xnu/out-jasmine-$K xnu/out-jasmine-$T; }
rm -f "$LOG.run"
n=$(( $(echo $LEVELS | wc -w) + 1 ))
# a play takes about 200 s (j60a), a bench and the counters ~20 s
SECS=${SECS:-$(( 240 + 240 * n ))} bash tools/cpuclk/osm-round.sh - $T "sweetosm=0 sweetcmd=1 $ARGS" "$LOG" > /dev/null &
R=$!
for i in $(seq 1 120); do grep -q "^# booted" "$LOG.run" 2>/dev/null && break; sleep 2; done
q() { python -c "import sys; sys.path.insert(0, 'tools/g2'); import uibench; r = uibench.cmd(sys.argv[1], timeout=60); print(r if r is not None else 'NO ANSWER')" "$1"; }
# one play with bus samples alongside
play() {
	python tools/g2/uibench.py play &
	local P=$!
	while kill -0 $P 2>/dev/null; do q "ddr bw 10000 bg" > /dev/null; sleep 11; done
	wait $P
}
python -c "import sys; sys.path.insert(0, 'tools/g2'); import uibench, time
while uibench.cmd('t') is None: time.sleep(2)"
sleep ${UIWAIT:-75}                     # SpringBoard up and settled, as uibench's --wait
q "ddr state"
q "ddr bench"
q "ddr bw 2000"
q "ddr bw 2000 load"
play
for m in $LEVELS; do
	r=$(q "ddr $m")
	echo "$(date +%H:%M:%S) $r"
	case "$r" in *": ok "*) ;; *) echo "stopping at $m MHz"; break ;; esac
	q "ddr state"
	q "ddr bench"
	play
done
q "ddr bw 2000 load"
wait $R
python tools/g2/ddrsum.py "$LOG"
