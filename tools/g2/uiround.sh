#!/bin/bash
# One unattended UI round: boot xnu/out-jasmine-KTAG (osm-round.sh, AMP/CPUS as there) with
# sweetcmd=1 + ARGS, play tools/g2/uibench.py's gestures once SpringBoard is up, summarise.
#   bash tools/g2/uiround.sh KTAG TAG "ARGS"      log: logs/netlog-TAG-ui.txt
# Takes phone.lock in the shared notes folder atomically (refuses if another round holds it).
K=${1:?usage: uiround.sh KTAG TAG "ARGS"}
T=${2:?}
ARGS=${3:-}
cd "/c/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine" || exit 1
export MSYS_NO_PATHCONV=1
L="${PHONE_LOCK:-C:/Users/teleg/AppData/Local/Claude-Data/claude_pzs8sxrjxfjjc/side-session-notes/local_b57c5c9a-db18-434e-a448-e6d69fa0dddf/phone.lock}"
( set -C; echo "uiround $T ($$), $(date +%H:%M:%S)" > "$L" ) 2>/dev/null || { echo "phone busy: $(cat "$L")"; exit 2; }
trap 'grep -q "uiround $T ($$)" "$L" 2>/dev/null && rm -f "$L"' EXIT
LOG=logs/netlog-$T-ui.txt
[ "$K" = "$T" ] || { rm -rf xnu/out-jasmine-$T; cp -r xnu/out-jasmine-$K xnu/out-jasmine-$T; }
rm -f "$LOG.run"
SECS=${SECS:-200} bash tools/cpuclk/osm-round.sh - $T "sweetosm=0 sweetcmd=1 $ARGS" "$LOG" > /dev/null &
R=$!
for i in $(seq 1 120); do grep -q "^# booted" "$LOG.run" 2>/dev/null && break; sleep 2; done
python tools/g2/uibench.py play --wait ${UIWAIT:-75}
wait $R
python tools/g2/uibench.py sum "$LOG"
