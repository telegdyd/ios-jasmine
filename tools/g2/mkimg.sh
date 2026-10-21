#!/bin/bash
# Boot image for a GPU test kernel (run in WSL):
#   wsl bash .../tools/g2/mkimg.sh TAG
# takes xnu/out-jasmine-TAG/kernel.development.sweet and writes
# shim/out/shim-boot-TAG-gpu.img (sweetgpu=4 at 266 MHz, debug logging on).
set -e
T=${1:?usage: mkimg.sh TAG (kernel in xnu/out-jasmine-TAG)}
cd "/mnt/c/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine"
K=xnu/out-jasmine-$T/kernel.development.sweet
B="debug=0xc serial=3 cpus=4 keepsyms=1 -noprogress rd=ufsroot0 ufsroot=userdata unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 panicwait=60 sweetfb_hz=30 ufsrw=1 rootrw=1 rtcoffset=1790955133 sweetgold=1747"
python3 tools/mkadt.py shim/out/jasmine-$T.adt --highmem >/dev/null
for v in gpu:" sweetgpu=4 gpumhz=266 sweetwdt=20 sweetgpu_debug=1"; do n=${v%%:*}; extra=${v#*:}
  python3 tools/mkpayload.py $K shim/out/jasmine-$T.adt shim/out/payload-$T-$n.bin --cmdline "$B$extra" >/dev/null
  bash shim/build.sh shim/out/payload-$T-$n.bin 2>&1 | grep -E "warn|error" || true
  cp shim/out/shim-boot.img shim/out/shim-boot-$T-$n.img; ls -la shim/out/shim-boot-$T-$n.img
done
