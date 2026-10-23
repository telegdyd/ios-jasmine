#!/bin/bash
# Put a finished configuration on the phone (PERF-TASKS.md "Done means on the phone"): wait for the phone lock,
# take it, bring the phone to fastboot (command port "reboot" if iOS is up), flash boot_b with IMAGE, reboot into
# slot b and keep the live log of the first boot for SECS seconds (default 180).
#   bash tools/g2/flash-slotb.sh shim/out/shim-boot-KTAG-slotb.img logs/netlog-KTAG-slotb.txt
# Only boot_b, only an image built with abmark=b (the user's standing OK since 2026-10-23).
IMG=${1:?usage: flash-slotb.sh IMAGE LOG}
LOG=${2:?}
cd "/c/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine" || exit 1
export MSYS_NO_PATHCONV=1
[ -f "$IMG" ] || { echo "no $IMG"; exit 1; }
python -c "import sys; d=open(sys.argv[1],'rb').read(); sys.exit(0 if b'abmark=b' in d else 1)" "$IMG" ||
	{ echo "$IMG has no abmark=b: not a slot b image"; exit 1; }
L="${PHONE_LOCK:-C:/Users/teleg/AppData/Local/Claude-Data/claude_pzs8sxrjxfjjc/side-session-notes/local_b57c5c9a-db18-434e-a448-e6d69fa0dddf/phone.lock}"
until ( set -C; echo "flash-slotb $(basename "$IMG") ($$), $(date +%H:%M:%S)" > "$L" ) 2>/dev/null; do sleep 10; done
trap 'grep -q "flash-slotb .* ($$)" "$L" 2>/dev/null && rm -f "$L"' EXIT
echo "# lock taken at $(date +%T)"
if [ -z "$(fastboot devices)" ]; then
	echo "# reboot over the command port: $(python tools/sweet-cmd.py reboot 2>&1)"
	for i in $(seq 1 90); do [ -n "$(fastboot devices)" ] && break; sleep 2; done
fi
[ -n "$(fastboot devices)" ] || { echo "no fastboot device"; exit 1; }
echo "# current slot: $(fastboot getvar current-slot 2>&1 | grep -o 'current-slot: [ab]')"
fastboot flash boot_b "$IMG" || exit 1
fastboot reboot || exit 1
echo "# rebooted at $(date +%T)"
python tools/sweet-netlog.py "$LOG" --wait 300 --for ${SECS:-180} > /dev/null
echo "# log ends at $(date +%T)"
