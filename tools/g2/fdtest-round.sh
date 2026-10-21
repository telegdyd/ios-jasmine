#!/bin/bash
# one hands-free fdtest round: boot the image with the live log, wait for
# SweetGPU + sweetd, push the test, run it, then let the log run out.
# BINS are pushed and run, PUSH only pushed (libraries), all from xnu/out-mesa.
# The tests' own output also goes to LOG.tests.
cd "/c/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine" || exit 1
export MSYS_NO_PATHCONV=1
IMG=$1
LOG=$2
# fastboot, or a running kernel whose command port sweet-run can reboot
for i in $(seq 1 60); do
	[ -n "$(fastboot devices)" ] && break
	python -c "import socket; socket.create_connection(('169.254.7.2', 5141), timeout=2)" 2>/dev/null && break
	sleep 2
done
python tools/sweet-run.py "$IMG" "$LOG" --secs ${SECS:-200} > "$LOG.run" 2>&1 &
RUN=$!
for i in $(seq 1 120); do
	grep -q "SweetGPU service published" "$LOG" 2>/dev/null && break
	sleep 2
done
grep -q "SweetGPU service published" "$LOG" 2>/dev/null || { echo "SweetGPU never published"; wait $RUN; exit 1; }
echo "# SweetGPU up at $(date +%T)"
# sweetd starts with launchd; retry the push until it gets through
BINS=${BINS:-sweetgpu_fdtest}
for b in $BINS $PUSH; do
	for i in $(seq 1 40); do
		python tools/sweet-fs.py put "xnu/out-mesa/$b" /usr/local/bin/$b --mode 755 && break
		sleep 3
	done
done
for i in $(seq 1 40); do
	python -c "import socket,sys; socket.create_connection(('169.254.7.2', 5143), timeout=3)" 2>/dev/null && break
	sleep 3
done
for b in $BINS; do
	echo "# sweetd up, running $b at $(date +%T)"
	python tools/sweet-sh.py --timeout 60 /usr/local/bin/$b 2>&1 | tee -a "$LOG.tests"
	echo "# $b exit ${PIPESTATUS[0]} at $(date +%T)" | tee -a "$LOG.tests"
done
wait $RUN
echo "# log done"
