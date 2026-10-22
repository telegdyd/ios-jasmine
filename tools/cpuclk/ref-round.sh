#!/bin/bash
# Stock-kernel OSM reference round (Git Bash): boot shim/out/stock-ref-boot.img (the
# backed-up msm-4.4 kernel with tools/cpuclk/refinit.c as /init), let it reboot into
# fastboot, boot our kernel with the live tool (sweetosm=8) and read its kernel log
# back out of ramoops (osmctl "ramoops KEY").
#   bash tools/cpuclk/ref-round.sh KERNEL_RUN TAG
G="/c/Program Files/GitHub CLI/gh"
KR=${1:?usage: ref-round.sh KERNEL_RUN TAG}
T=${2:?}
cd "/c/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine" || exit 1
export MSYS_NO_PATHCONV=1
"$G" run watch $KR -R telegdyd/ios-jasmine --exit-status --interval 30 >/dev/null 2>&1
[ "$("$G" run view $KR -R telegdyd/ios-jasmine --json conclusion -q .conclusion)" = success ] || { echo "CI $KR failed"; exit 1; }
rm -rf xnu/out-jasmine-$T
"$G" run download $KR -R telegdyd/ios-jasmine -n xnu-kernel -D xnu/out-jasmine-$T || exit 1
BASE="gpudelay=1 gpupause=0 sweetenv=backboardd:DYLD_INSERT_LIBRARIES=/usr/local/bin/libsweetca.dylib"
wsl env GPUDBG=0 VARIANT=osm EXTRA_ARGS="$BASE sweetosm=8" bash "/mnt/c/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine/tools/g2/mkimg.sh" $T >/dev/null || exit 1
[ -n "$(fastboot devices)" ] || python tools/sweet-cmd.py reboot
for i in $(seq 1 60); do [ -n "$(fastboot devices)" ] && break; sleep 2; done
fastboot boot shim/out/stock-ref-boot.img || exit 1
echo "# reference booted at $(date +%T)"
sleep 8
for i in $(seq 1 90); do [ -n "$(fastboot devices)" ] && break; sleep 2; done
[ -n "$(fastboot devices)" ] || { echo "reference did not come back to fastboot"; exit 1; }
echo "# back in fastboot at $(date +%T)"
python tools/sweet-run.py shim/out/shim-boot-$T-osm.img logs/netlog-$T-osm.txt --secs 3600 > logs/netlog-$T-osm.txt.run 2>&1 &
for i in $(seq 1 120); do grep -q "SWEET OSM: table ready" logs/netlog-$T-osm.txt 2>/dev/null && break; sleep 3; done
for k in SWEETREF Linux_version clk-cpu-osm cprh OSM panic DBGC; do
	echo "=== $k"
	python tools/cpuclk/osmctl.py "ramoops $k"
done
