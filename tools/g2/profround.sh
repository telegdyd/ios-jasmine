#!/bin/bash
# One unattended UI round with a sampling profile (kernel j0057): tools/g2/uiround.sh KTAG TAG
# "sweetfps=1 ARGS" and, PDELAY s (default 2) after the gestures start, tools/g2/prof.py fetch
# for PSECS s (default 20) into logs/prof-TAG.{bin,meta}. The report runs in WSL afterwards:
#   bash tools/g2/profround.sh KTAG TAG "ARGS"
cd "/c/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine" || exit 1
K=${1:?usage: profround.sh KTAG TAG "ARGS"}
T=${2:?}
ARGS=${3:-}
D="$(dirname "$0")"
OUT=logs/round-$T.txt
bash "$D/uiround.sh" "$K" "$T" "sweetfps=1 $ARGS" > "$OUT" 2>&1 &
R=$!
for i in $(seq 1 400); do grep -q "^uibench: start" "$OUT" 2>/dev/null && break; kill -0 $R 2>/dev/null || break; sleep 1; done
if grep -q "^uibench: start" "$OUT"; then
	sleep ${PDELAY:-2}
	python "$D/prof.py" fetch logs/prof-$T --secs ${PSECS:-20} --us ${PUS:-1000} --census ${PCENSUS:-2000} \
	    --tasks ${PTASKS:-backboardd,SpringBoard} 2>&1 | tee -a logs/prof-$T.txt
fi
wait $R
cat "$OUT"
