#!/bin/bash
# One hands-free CPU clock round from Git Bash on Windows: wait for a kernel CI
# run, download it, build the G2 test image with extra boot-args (as the
# current phone state, plus ARGS), boot it with the live log for SECS seconds.
#   bash tools/cpuclk/osm-round.sh KERNEL_RUN|- TAG "ARGS" [LOG]
# KERNEL_RUN "-" reuses xnu/out-jasmine-TAG. The image is shim/out/shim-boot-TAG-osm.img.
# The phone must be in fastboot or running a kernel with the command port.
G="/c/Program Files/GitHub CLI/gh"
KR=${1:?usage: osm-round.sh KERNEL_RUN|- TAG "ARGS" [LOG]}
T=${2:?}
ARGS=${3:-sweetosm=1}
LOG=${4:-logs/netlog-$T-osm.txt}
cd "/c/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine" || exit 1
export MSYS_NO_PATHCONV=1
if [ "$KR" != - ]; then
	"$G" run watch $KR -R telegdyd/ios-jasmine --exit-status --interval 30 >/dev/null 2>&1
	c=$("$G" run view $KR -R telegdyd/ios-jasmine --json conclusion -q .conclusion)
	echo "run $KR: $c"
	[ "$c" = success ] || exit 1
	rm -rf xnu/out-jasmine-$T
	"$G" run download $KR -R telegdyd/ios-jasmine -n xnu-kernel -D xnu/out-jasmine-$T || exit 1
fi
# G2 state of 2026-10-22 05:04 (shim-boot-j38-bb8.img) + ARGS
BASE="gpudelay=1 gpupause=0 sweetenv=backboardd:DYLD_INSERT_LIBRARIES=/usr/local/bin/libsweetca.dylib"
wsl env GPUDBG=0 VARIANT=osm EXTRA_ARGS="$BASE $ARGS" bash "/mnt/c/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine/tools/g2/mkimg.sh" $T || exit 1
for i in $(seq 1 ${WAIT:-60}); do
	[ -n "$(fastboot devices)" ] && break
	python -c "import socket; socket.create_connection(('169.254.7.2', 5141), timeout=2)" 2>/dev/null && break
	sleep 2
done
echo "# booting shim/out/shim-boot-$T-osm.img at $(date +%T)"
python tools/sweet-run.py shim/out/shim-boot-$T-osm.img "$LOG" --secs ${SECS:-120} > "$LOG.run" 2>&1
echo "# log ends at $(date +%T)"
grep -c "SWEET OSM" "$LOG"
grep -n "SWEET PANIC\|panic(cpu" "$LOG" | head
