#!/bin/bash
# GPU clock round (j0060): boot xnu/out-jasmine-KTAG like uiround.sh (gpumhz=588 from mkimg.sh; pass gpumhz=266 in ARGS for the old start), play
# tools/g2/uibench.py's gestures at 266 MHz, then switch with the command port's "gpu clk MHZ" to each
# level in LEVELS and play them again, all in one boot. Stops at the first level whose switch fails or
# loses the phone (sweetwdt=20 sends a hang back to fastboot).
#   LEVELS="370 465 588 647 700 750" bash tools/g2/clkround.sh KTAG TAG "ARGS"
# PLAYS=N plays the boot level N times (e.g. LEVELS= PLAYS=3 ARGS=gpumhz=647: a 10-minute series).
# Log logs/netlog-TAG-clk.txt; per-level summaries from tools/g2/clksum.py at the end.
K=${1:?usage: clkround.sh KTAG TAG "ARGS"}
T=${2:?}
ARGS=${3:-}
LEVELS=${LEVELS-370 465 588 647 700 750}
cd "/c/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine" || exit 1
export MSYS_NO_PATHCONV=1
L="${PHONE_LOCK:-C:/Users/teleg/AppData/Local/Claude-Data/claude_pzs8sxrjxfjjc/side-session-notes/local_b57c5c9a-db18-434e-a448-e6d69fa0dddf/phone.lock}"
( set -C; echo "clkround $T ($$), $(date +%H:%M:%S)" > "$L" ) 2>/dev/null || { echo "phone busy: $(cat "$L")"; exit 2; }
trap 'grep -q "clkround $T ($$)" "$L" 2>/dev/null && rm -f "$L"' EXIT
LOG=logs/netlog-$T-clk.txt
[ "$K" = "$T" ] || { rm -rf xnu/out-jasmine-$T; cp -r xnu/out-jasmine-$K xnu/out-jasmine-$T; }
rm -f "$LOG.run"
PLAYS=${PLAYS:-1}
n=$(( $(echo $LEVELS | wc -w) + PLAYS ))
# a play takes about 200 s (j60a, 2026-10-23)
SECS=${SECS:-$(( 200 + 215 * n ))} bash tools/cpuclk/osm-round.sh - $T "sweetosm=0 sweetcmd=1 $ARGS" "$LOG" > /dev/null &
R=$!
for i in $(seq 1 120); do grep -q "^# booted" "$LOG.run" 2>/dev/null && break; sleep 2; done
q() { python -c "import sys; sys.path.insert(0, 'tools/g2'); import uibench; r = uibench.cmd(sys.argv[1], timeout=60); print(r if r is not None else 'NO ANSWER')" "$1"; }
python tools/g2/uibench.py play --wait ${UIWAIT:-75}
for i in $(seq 2 $PLAYS); do python tools/g2/uibench.py play; done
q "gpu state"
for m in $LEVELS; do
	r=$(q "gpu clk $m")
	echo "$(date +%H:%M:%S) $r"
	case "$r" in *": ok "*"self-test PASS"*) ;; *) echo "stopping at $m MHz"; break ;; esac
	python tools/g2/uibench.py play
	q "gpu state"
done
wait $R
python tools/g2/clksum.py "$LOG"
