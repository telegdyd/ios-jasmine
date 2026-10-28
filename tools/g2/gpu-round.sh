#!/bin/bash
# One hands-free GPU round from Git Bash on Windows: build the kernel and Mesa
# (on the macOS VM, or wait for and download CI runs), make the boot image,
# boot it, push the tests through sweetd and run them.
#   bash tools/g2/gpu-round.sh KERNEL_RUN MESA_RUN TAG [LOG]
# KERNEL_RUN / MESA_RUN: "vm" builds this checkout on the VM (tools/vm-build.sh,
# tools/vm-mesa.sh; the default way), a number takes that CI run's artifact.
# KERNEL_RUN may be "-" to reuse xnu/out-jasmine-TAG (and its image) as it is.
# IOS_RUN=vm|N also puts the ios-tools (ios/*.c, ios/lib) next to the Mesa tests;
# EXTRA_ARGS goes to mkimg.sh, PUSH to fdtest-round.sh.
# The phone must be in fastboot or running a kernel with the command port.
G="/c/Program Files/GitHub CLI/gh"
KR=${1:?usage: gpu-round.sh KERNEL_RUN|- MESA_RUN TAG [LOG]}
MR=${2:?}
T=${3:?}
LOG=${4:-logs/netlog-$T-gpu.txt}
cd "/c/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine" || exit 1
export MSYS_NO_PATHCONV=1
for R in $([ "$KR" = - ] || echo $KR) $MR $IOS_RUN; do
	[ "$R" = vm ] && continue
	"$G" run watch $R -R telegdyd/ios-jasmine --exit-status --interval 30 >/dev/null 2>&1
	c=$("$G" run view $R -R telegdyd/ios-jasmine --json conclusion -q .conclusion)
	echo "run $R: $c"
	[ "$c" = success ] || exit 1
done
if [ "$KR" != - ]; then
	rm -rf xnu/out-jasmine-$T
	if [ "$KR" = vm ]; then
		sh tools/vm-build.sh $T || exit 1
	else
		"$G" run download $KR -R telegdyd/ios-jasmine -n xnu-kernel -D xnu/out-jasmine-$T || exit 1
	fi
	wsl env EXTRA_ARGS="$EXTRA_ARGS" bash "/mnt/c/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine/tools/g2/mkimg.sh" $T || exit 1
fi
rm -rf xnu/out-mesa
if [ "$MR" = vm ]; then
	OUT=xnu/out-mesa sh tools/vm-mesa.sh mesa $T || exit 1
else
	"$G" run download $MR -R telegdyd/ios-jasmine -n mesa-ios -D xnu/out-mesa || exit 1
fi
if [ "$IOS_RUN" = vm ]; then
	sh tools/vm-mesa.sh ios $T && cp xnu/out-ios-$T/* xnu/out-mesa/ || exit 1
elif [ -n "$IOS_RUN" ]; then
	"$G" run download $IOS_RUN -R telegdyd/ios-jasmine -n ios-tools -D xnu/out-mesa || exit 1
fi
echo "=== fdtest + gltest on $T"
BINS="${BINS:-sweetgpu_fdtest sweetgpu_gltest}" SECS=${SECS:-200} bash tools/g2/fdtest-round.sh shim/out/shim-boot-$T-gpu.img "$LOG"
grep -n "SWEET PANIC\|panic(cpu\|not imported\|hang" "$LOG" | head -20
echo "=== done"
