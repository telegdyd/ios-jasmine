#!/bin/bash
# Boot image for a GPU test kernel (run in WSL):
#   wsl bash .../tools/g2/mkimg.sh TAG
# takes xnu/out-jasmine-TAG/kernel.development.sweet and writes
# shim/out/shim-boot-TAG-gpu.img (GPU588 MHz, DDR1804, debug logging on).
# Current Jasmine kernels default to eight cores and automatic CPU scaling.
# DDR at its stock top rate, 1804 MHz (sweetddr=, j0064): the GPU is memory-bound during motion
# (PERF-GPU-TIME-20261025.md: Home B 37.5 -> 32.9 ms, Control Center 53 -> 41 ms over 1296).
# EXTRA_ARGS="..." appends boot-args (e.g. sweetenv=...), GPUDBG=0 turns sweetgpu_debug off,
# VARIANT=name writes shim/out/shim-boot-TAG-name.img instead of -gpu.
# RO=1: root read-only (no ufsrw=1 rootrw=1), for a first boot of a risky kernel.
# New 4K Jasmine kernels select AMP=1, CPUS=8, CPU_DVFS=1 automatically.
# CPU_DVFS=0 disables scaling; CPUS=4 retains four Gold cores for diagnostics.
# Older kernels retain their legacy AMP=0/CPUS=4 defaults. AMP=1 selects the AMP ADT.
set -e
T=${1:?usage: mkimg.sh TAG (kernel in xnu/out-jasmine-TAG)}
cd "/mnt/c/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine"
K=xnu/out-jasmine-$T/kernel.development.sweet
PROFILE=0
LC_ALL=C grep -Faq 'SWEET DVFS: jasmine defaults v1' "$K" && PROFILE=1
AMP=${AMP:-$PROFILE}
CPU_DVFS=${CPU_DVFS:-$PROFILE}
CPUS=${CPUS:-$([ "$AMP" = 1 ] && echo 8 || echo 4)}
case "$CPU_DVFS" in 0|1) ;; *) echo 'CPU_DVFS must be 0 or 1' >&2; exit 1;; esac
if [ "$CPU_DVFS" = 1 ] && { [ "$PROFILE" != 1 ] || [ "$AMP" != 1 ] || { [ "$CPUS" != 4 ] && [ "$CPUS" != 8 ]; }; }; then
  echo 'CPU scaling needs a current Jasmine 4K kernel, AMP=1 and CPUS=4 or 8' >&2; exit 1
fi
CPU_ARGS=" sweetdvfs=$CPU_DVFS sweetdvfsauto=$CPU_DVFS"
[ "$CPU_DVFS" = 1 ] && CPU_ARGS="$CPU_ARGS sweetcmd=1"
B="debug=0xc serial=3 cpus=$CPUS keepsyms=1 -noprogress rd=ufsroot0 ufsroot=userdata unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 panicwait=60 sweetfb_hz=30 ufsrw=1 rootrw=1 rtcoffset=1790955133 sweetgold=1747"
[ "${RO:-0}" = 1 ] && B=${B/ ufsrw=1 rootrw=1/}
# The integrated kernel defaults to Wi-Fi. Explicit off images omit the wlan node.
python3 tools/mkadt.py shim/out/jasmine-$T.adt --highmem $([ "${AMP:-0}" = 1 ] && echo --amp) $(case " ${EXTRA_ARGS:-} " in *" wifi=0 "*|*" modem=0 "*) echo --no-wlan;; esac) >/dev/null
for v in ${VARIANT:-gpu}:" sweetgpu=4 gpumhz=588 sweetddr=1804 sweetwdt=20 sweetgpu_debug=${GPUDBG:-1}$CPU_ARGS${EXTRA_ARGS:+ $EXTRA_ARGS}"; do n=${v%%:*}; extra=${v#*:}
  python3 tools/mkpayload.py $K shim/out/jasmine-$T.adt shim/out/payload-$T-$n.bin --cmdline "$B$extra" >/dev/null
  bash shim/build.sh shim/out/payload-$T-$n.bin >shim/out/build-$T-$n.log 2>&1 || { cat shim/out/build-$T-$n.log; exit 1; }
  cp shim/out/shim-boot.img shim/out/shim-boot-$T-$n.img; ls -la shim/out/shim-boot-$T-$n.img
done
