#!/bin/bash
# Boot image for a GPU test kernel (run in WSL):
#   wsl bash .../tools/g2/mkimg.sh TAG
# takes xnu/out-jasmine-TAG/kernel.development.sweet and writes
# shim/out/shim-boot-TAG-gpu.img (sweetgpu=4 at 266 MHz, debug logging on).
# EXTRA_ARGS="..." appends boot-args (e.g. sweetenv=...), GPUDBG=0 turns sweetgpu_debug off,
# VARIANT=name writes shim/out/shim-boot-TAG-name.img instead of -gpu.
# RO=1: root read-only (no ufsrw=1 rootrw=1), for a first boot of a risky kernel.
# AMP=1: all eight cores for a TOPAZ_4K kernel (mkadt.py --amp, cpus=8; CPUS=N overrides).
set -e
T=${1:?usage: mkimg.sh TAG (kernel in xnu/out-jasmine-TAG)}
cd "/mnt/c/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine"
K=xnu/out-jasmine-$T/kernel.development.sweet
CPUS=${CPUS:-$([ "${AMP:-0}" = 1 ] && echo 8 || echo 4)}
B="debug=0xc serial=3 cpus=$CPUS keepsyms=1 -noprogress rd=ufsroot0 ufsroot=userdata unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 panicwait=60 sweetfb_hz=30 ufsrw=1 rootrw=1 rtcoffset=1790955133 sweetgold=1747"
[ "${RO:-0}" = 1 ] && B=${B/ ufsrw=1 rootrw=1/}
python3 tools/mkadt.py shim/out/jasmine-$T.adt --highmem $([ "${AMP:-0}" = 1 ] && echo --amp) >/dev/null
for v in ${VARIANT:-gpu}:" sweetgpu=4 gpumhz=266 sweetwdt=20 sweetgpu_debug=${GPUDBG:-1}${EXTRA_ARGS:+ $EXTRA_ARGS}"; do n=${v%%:*}; extra=${v#*:}
  python3 tools/mkpayload.py $K shim/out/jasmine-$T.adt shim/out/payload-$T-$n.bin --cmdline "$B$extra" >/dev/null
  bash shim/build.sh shim/out/payload-$T-$n.bin 2>&1 | grep -E "warn|error" || true
  cp shim/out/shim-boot.img shim/out/shim-boot-$T-$n.img; ls -la shim/out/shim-boot-$T-$n.img
done
