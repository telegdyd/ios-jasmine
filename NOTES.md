### 2026-10-29 21:30: boot_b = j0118 INSTALLED (user: "Flash j0118")

boot_b = shim/out/shim-boot-j0118-slotb.img (sha256 09377837...; kernel xnu/out-jasmine-j0118 = j0110..j0118: GPU idle
power on by default, USB diagnostics, previous-boot log, ue0 IPv4 repair + DHCP fallback). The command-port reboot hung
(no fastboot in 3 min, known root-unmount stall); user forced fastboot, flash OKAY. First boot logs/netlog-j0118-slotb.txt:
self-test PASS, PC got 192.168.7.1 by DHCP, the 169.254/16 route went missing again and was repaired, boot_b marked
successful in both GPTs, no panic. Rollback: `fastboot flash boot_b shim/out/shim-boot-j0116-slotb.img` (9d1fcc75...).
Open: who removes ue0's 169.254/16 route (guess configd); the j0117 previous-log header area read back invalid.

### 2026-10-29 20:30: USB dead link diagnosed (IPv4 state, not USB); j0117 (previous log) + j0118 (repair) built, j0118 temp boot verified; not flashed

The dead link of the j0116 boot_b (user report 20:00): previous log via j0117 (`sweet-fs.py get /.sweetlog-prev`,
saved logs/prevlog-j0116-deadlink.bin/.txt; its first 4 KiB header area was not a valid header, the ring starts at 4096).
Observed: after unplug/replug the USB side was healthy (disconnect, reset, connect done, SET_CONFIGURATION, NCM
configured, rx 1448 -> 1620 frames) but tx 1470 -> 1471 and every DHCP answer failed `send 51` (ENETUNREACH); only
the first DHCP answer of each boot ever went out (the j0089 255.255.255.255 host route is rejected by ARP at boot,
"bad gateway address"), so the PC always ran on 169.254 and depended on ue0's scoped 169.254/16 route. j0118 temp boot
(logs/netlog-j0118-test.txt) caught it live: ~1 min after boot (after configd/en0 came up) **ue0's 169.254/16 route went
MISSING** with both addresses still there (who removes it is not proven; guess configd). Fix j0118
(xnu/patches/j0118-jasmine-usb-ipv4-repair.patch, sweet_usb.c): (1) DHCP answers fall back to 192.168.7.255 -> the PC
now gets **192.168.7.1 by DHCP** (verified); (2) ue0's addresses, up/running and scoped routes are checked at every
SET_CONFIGURATION and every 30 s, logged on change and put back (verified: route repaired, state ok after).
j0117 (xnu/patches/j0117-jasmine-previous-log.patch): previous boot's log area kept in memory before the log thread
overwrites it, served as /.sweetlog-prev (neither Linux shell has a UFS driver). Linux shell gotcha: the old
nura-r109 shell has no reboot-bootloader (push shim/out/reboot-bootloader with pmos-push.py).
Images: shim/out/shim-boot-j0118-test.img (c5142aea...), slot b shim/out/shim-boot-j0118-slotb.img (09377837...).
**Not flashed** (flash needs the user's explicit OK). Phone: temporary j0118 boot; boot_b = j0116.

### 2026-10-29 20:02: charger app reads the battery under iOS too

tools/jasmine-charger.pyw: in the iOS state it now sends `batt` (j0114+ command port 5141) every poll and shows
voltage, current, the iOS fuel-gauge SOC, charging/full, temperature and screen state (no charger type or input
limit: those are only in the live log's `SWEET CHG:` lines). Skipped while anyone holds the phone lock; kernels
before j0114 fall back to "no battery readout". Checked against the running j0116 boot_b: 3.942 V, +0.42 A, 45 %,
display off. No phone state change.

### 2026-10-29 19:50: boot_b = j0116 (GPU idle power on by default + USB diagnostics) INSTALLED (user: "install the kernel")

boot_b = shim/out/shim-boot-j0116-slotb.img (sha256 9d1fcc75...; kernel xnu/out-jasmine-j0116 = j0110..j0116; args
byte-identical to the j0114d boot_b). Flashed at 36 % from the charging shell with tools/g2/flash-slotb.sh. First
boot logs/netlog-j0116-slotb.txt: self-test PASS, GPUPC mode 1 + HWCG on from boot (collapses/resumes, 0 failures),
USB device events logged (suspend/reset/connect done), DHCP ack, boot_b marked successful, no panic. Rollback:
`fastboot flash boot_b shim/out/shim-boot-j0114d-slotb.img` (f867f6b1...). USB dead-link bug: the user reports the
next occurrence; then read the j0116 USB lines (Power+VolDown -> fastboot -> charge-shell -> log ring via
pmos-shell.py --raw, not an iOS boot, which restarts the ring). Battery note: on the PC port AICL limits input to
~875 mA, below iOS's screen-on draw; the phone fell to 2 % today.

### 2026-10-29 19:30: j0115 defaults ON (j0115c) + j0116 USB diagnostics built, not booted yet; phone at 3 %, charging in the Linux shell

User: GPU idle power on by default. xnu/patches/j0115-jasmine-gpu-idle-power.patch now defaults `sweetgpucg=1`,
`sweetgpupc=1` (0 disables either). New xnu/patches/j0116-jasmine-usb-diag.patch (sweet_usb.c only): every DWC3
device event logged/counted (link state, wakeup, suspend, erratic error now enabled in DEVTEN), controller/NCM state
in the 30 s `ue0` line, command `usb vbusoff SECS` (session off that long). Reason: the USB link stays dead (PC adapter
169.254.x, DHCP and ping unanswered, Windows re-enumerates) after the phone was away from the PC for a long time
(user: overnight on the wall charger, and the drive home today); quick replugs and `usb vbuscycle` recover; an iOS
reboot fixes it. The failing boot's log was lost (the user rebooted into iOS; a fresh boot restarts the disk ring).
Kernel xnu/out-jasmine-j0116 (= j0110..j0116), image shim/out/shim-boot-j0116-test.img (061dbe1b..., installed
boot_b args). **Not booted:** the phone was at 2 % (3522 mV, -500 mA on boot_b: the PC port's AICL limit 875 mA is
below what iOS draws with the screen on), so it went to `shim/out/charge-shell.img` (+0.63 A at 3.69 V). Next: at
>= 30 % boot j0116-test, check GPU defaults (`gpu pc`), reproduce the dead link with `usb vbusoff 1800` etc.; if it
dies, Power+VolDown -> fastboot -> charge-shell -> read the log ring with `pmos-shell.py --raw` (do NOT boot iOS
first: it restarts the ring). boot_b unchanged (j0114d).

### 2026-10-29 17:15: GPU idle power (item 2) j0115 built and measured (temporary boots): ~60 mA saved screen off, ~70 mA screen-on idle; default off

Patch xnu/patches/j0115-jasmine-gpu-idle-power.patch (kernels xnu/out-jasmine-j0115, -j0115b = + `batt icl` aid),
report jasmine/GPU-IDLE-POWER.md "Bring-up results". Live switches `gpu cg 0|1` (HWCG, kgsl's a512 table), `gpu pc
on|off|offonly` (GX collapse, 80 ms hold, immediate with display off, resume in submit or pre-wake on touch/keys/
display on); boot-args `sweetgpucg=`, `sweetgpupc=` default 0. Observed: 800+ stress cycles + UI + 10 display
cycles, 0 failures / SMMU rewrites / zap resumes; resume ~0.35 ms (stress) to ~0.65-0.95 ms (UI), max 2.7 ms.
Framebench 11 runs (research/framebench/gpupc-*): no regression within noise (home-a on -1.5 % mean, overlapping).
fgab (USB input limited by `batt icl 100 3600`): screen off +58.5 mA (HWCG +52, collapse +12 on top), screen-on idle
+70 mA. Step 2b useless: VDD_CX stays 860 mV with our SVS vote. Command line has only 16 bytes left (591/607).
**Phone state:** temporary j0115b boot, both features ON live, charger limit restored; boot_b unchanged (j0114d).
Nothing flashed. The live log stops at 17:15:36 because the host laptop was closed (user), not a phone fault.
Next: the user's decision on defaults on + a slot-b image.

### 2026-10-29: GPU idle power (power plan item 2): design written, waiting for the user's OK before building

Design: jasmine/GPU-IDLE-POWER.md. Step 1 HWCG (kgsl's a512_hwcg_regs, live `gpu cg 0|1`); step 2 GX collapse
after an 80 ms idle hold (kgsl's sdm660 idle-timeout) and right after display off, sync resume in the submit path
(GX on, PLL, a5xx_hw_init + HWCG, CP_ME_INIT, CP_SET_SECURE_MODE 0; a512 has CPZ retention, so no TZ call), pre-wake
from the ddrgov touch/key/display hooks; CX GDSC, SMMU (qcom,retention) and the CX vote stay; optional step 2b lowers
the CX vote with the display off. Boot-args `sweetgpupc=0|1|2` (default 0), `sweetgpucg`. Planned patch
j0115-jasmine-gpu-idle-power.patch. Reference source: WSL Debian ~/lin660/drivers/gpu/msm (downstream kgsl).
Nothing built, booted or flashed. Phone unchanged (boot_b j0114d).

### 2026-10-29 15:45: boot_b = j0114d (DDR governor on by default) INSTALLED (user: "obviously flash it")

boot_b = shim/out/shim-boot-j0114d-slotb.img (sha256 f867f6b1...; kernel xnu/out-jasmine-j0114d = j0113 + j0114; args
byte-identical to the j0113 boot_b). `fastboot flash boot_b` OKAY; first boot logs/netlog-j0114d-slotb.txt: governor
mode 1 from boot, 0 failed votes, idle-off with the display off, boot_b marked successful in both GPTs, no panic.
Rollback: `fastboot flash boot_b shim/out/shim-boot-j0113-slotb.img` (0ff5c7a6...). Before the flash the clean
reboot again stalled at `hfs: unmount initiated on iOSRoot` but reached fastboot on its own after ~2 min.

### 2026-10-29 15:30: DDR governor ON by default (j0114d); temporary boot verified; boot_b not flashed yet

User: scaling is the proper configuration, turn it on. j0114 now defaults to `sweetddrgov=1` (0 = old fixed
sweetddr). Kernel xnu/out-jasmine-j0114d. Temporary boot shim/out/shim-boot-j0114d-test.img (installed boot_b args,
byte-identical): mode 1 from boot, 0 failed votes, framebench research/framebench/ddrgov-5-default-on at or above the
governor-off runs. Slot-b image shim/out/shim-boot-j0114d-slotb.img (sha256 f867f6b1...) ready; flash only with the
user's OK; rollback `fastboot flash boot_b shim/out/shim-boot-j0113-slotb.img`. Phone: running the temporary j0114d
boot; boot_b = j0113. Details: jasmine/DDR-GOVERNOR.md.

### 2026-10-29 15:10: DDR governor j0114 built and measured (temporary boots); saves ~11 mA screen off only; phone hung in reboot

Patch xnu/patches/j0114-jasmine-ddr-governor.patch (kernel xnu/out-jasmine-j0114c, VM build), default off
(`sweetddrgov=0`: old fixed sweetddr). Report: jasmine/DDR-GOVERNOR.md "Bring-up results". Observed on
temporary boots (j0114/j0114b, installed boot_b args + sweetpwrlog=30): raises 0.06-4.4 ms, 0 failed votes,
readback 768 / 398 MHz in the low states; paired fuel-gauge A/B (tools/g2/fgab.py): screen off DDR floor alone
**+11 mA saved**, NoC buses low 0 mA, both together -21 mA (costs); screen-on idle floor not measurable. Framebench
ABBA (research/framebench/ddrgov-*): no measurable regression (-1.0..+1.3 %, within run spread). Defaults now
bus=0, UFS raise only with buses low, cpu=60, bw=2000. Recommendation to the user: `sweetddrgov=2` (display off only).
Side findings for other items in the shared notes (lock screen renders ~50 fps forever; ~1 Hz UFS I/O).
A clean `reboot` from j0114b (governor off) hit the known root-unmount hang (`hfs: unmount initiated on iOSRoot`),
recovered via fastboot. **j0114c with `sweetddrgov=2` verified** (shim/out/shim-boot-j0114c-gt.img, logs/netlog-j0114c-gt.txt):
mode 2 from the boot-arg, screen on stays FULL, display off -> idle-off (DDR reads 398-400 MHz, no raises while dark),
key/display raise back, no panic/SMMU fault. **Phone state:** running the temporary j0114c boot, display on;
boot_b unchanged (j0113). Nothing flashed. Next: user decision on sweetddrgov=2 in boot_b; power items 2-7 for the real floor.

### 2026-10-29: DDR/bus governor (power plan item 1): design written, waiting for the user's OK before building

Design: jasmine/DDR-GOVERNOR.md (states FULL / IDLE_ON bimc 768 / IDLE_OFF bimc 200 + NoCs low; sync raise on GPU
submit, touch, keys, display on; bwmon trigger; `sweetddrgov=0|1|2` default 0; `ddrgov`, `batt`, `sweetpwrlog=S`).
Planned patch j0114-jasmine-ddr-governor.patch. Nothing built, booted or flashed. Phone unchanged (boot_b j0113).

### 2026-10-29: battery drain plan written: jasmine/POWER-PLAN-20261029.md; DDR scaling started in its own session

Observed: screen off, unplugged -437 mA at 3.88 V (single FG sample, logs/netlog-j0113d-wall.txt). User rule: no
performance trade-offs (DDR stays 1804 under load; scaling, idle power-down, IRQ-driven drivers only), each item
gated by framebench. Item 1 (DDR/bus scaling governor) handed to a separate session. Phone unchanged (boot_b j0113).

### 2026-10-29 12:55: boot_b = j0113 (charger: APSD re-run on SDP, USB session only towards a host)

boot_b = shim/out/shim-boot-j0113-slotb.img (sha256 0ff5c7a6..., 13:16, with the USB replug fix; kernel xnu/out-jasmine-j0113 = j0112 + j0113; boot-args and ADT as the j0112-xr
boot_b). Details: jasmine/NOTES.md "iOS side of the SDP fix". First boot logs/netlog-j0113c-slotb.txt: PC port SDP -> re-run -> CDP 1500 mA, USB
enumerated, boot_b marked successful. 13:00 regression (no USB after a replug) fixed: NCM endpoints reset on disconnect/bus reset. User wall-charger replugs: 5/5 DCP 1500 mA, PC replug reconnects USB by itself. Phone parked in the charging shell. Rollback: fastboot flash boot_b shim/out/shim-boot-j0112-xr-slotb.img.

### 2026-10-29 05:40: 828x1792@2 (j0112) INSTALLED to boot_b for the user's own test (user: "install it")

boot_b = shim/out/shim-boot-j0112-xr-slotb.img (sha256 3e5e7614375f0fb6...; kernel xnu/out-jasmine-j0112; args = previous boot_b
minus keepsyms=1 (608-byte cmdline room) + sweetenv SpringBoard:DYLD_INSERT_LIBRARIES=/s.dylib + sweetfb_lw=828; ADT --canvas
828x1792 --scale 2). Flashed from fastboot (OKAY; no charging-shell readback, battery low). Root: /s.dylib (sweet_sbshape,
3fa51848...), /usr/local/bin/sbs.conf "227,32,414", MG cache = research/render-size/regen-xr.plist (e898a694...). Normal boot:
"828x1792 fitted into 998x2160", hook log setExclusionArea 227x32, SWEET AB boot_b marked successful both GPTs.
ROLLBACK (both parts needed): fastboot flash boot_b research/t16port/j0110-mode2-slotb.img (9096026c...); then in iOS put
research/render-size/backup/com.apple.MobileGestalt.plist (c70accbb...) to the MG cache path, rm /s.dylib /usr/local/bin/sbs.conf.
Note: the PC's USB adapter sometimes stays at 169.254.x (phone DHCP missed); then nothing is reachable; reboot/replug fixes it.

### 2026-10-29 00:30: task 25 slowdown FIXED by j0112: 828x1792@2 Home 41.1/s vs base 29.5 (+39%); not installed

Report: jasmine/PERF-RENDER-SIZE-20261028.md ("CAUSE" section). Cause: SweetSurface's screen-sized bounds 1000x2000 excluded
828x1792 frames from the GPU pool -> no direct/MDP-scaler present, no mode-2 queue, CPU composeFit every frame. j0112 scales the
bounds with the j0111 canvas (no change without sweetfb_lw). One run rs-xr3b (shim-boot-j0112-rx3.img): Home B 41.06/s (24.2/30.4
ms), CC 30.0/29.5, Spotlight 32.5; ADMIT/FLIP back, no panic/SMMU fault. Single run, cooler phone; base not re-run.
Phone: MG cache restored (c70accbb), /s.dylib, sbs.conf, leftover sbs.dylib removed, lib 4780fbaa, back in installed boot_b.
Stale phone.lock (local_b57c5c9a, Oct 27) deleted. Next: user look at sharpness; install would need sweetfb_lw=828 + ADT canvas
in boot_b plus a persistent SpringBoard status-bar hook and the XR MG cache.

### 2026-10-28 22:50: task 25: 828x1792@2 works (SpringBoard notch hook) but is 20% SLOWER; not installed; phone parked

Report: jasmine/PERF-RENDER-SIZE-20261028.md (RESULT section). j0111 (lh optional), ios/sweet_sbshape.c (SpringBoard hook of
UISMutableDisplayContext setExclusionArea:, via sweetenv "...;SpringBoard:DYLD_INSERT_LIBRARIES=/s.dylib" + /usr/local/bin/sbs.conf "227,32,414"),
mkimg B_DROP, abround --pin-cpu, gpwork waits for the log. Framebench 2 alternating pairs: Home 29.5 -> 23.7 /s, Spotlight 27.6 -> 21.4, CC -9..-12%.
GPUPROF: GPU 15 ms/frame at xr (3x lower) but 43 ms frame, only 28% of it in GL: next limit is outside GL. User look NOT done (no point yet).
Root: MG cache restored byte-identical, test files removed (one unexplained name matching sbs|rsshot in /usr/local/bin: check). Nothing flashed.

### 2026-10-28 21:45: task 25: UIKit status bar rule found (pixel width in a fixed list); 750 impossible, 828x1792@2 possible

Disassembled UIKitCore (report section "UIKit status bar analysis"): the provider needs the render pixel width in
{828,1080,1125,1170,1242,1284} and exclusionArea*scaleRatio == the class's notch. 828x1792@2x (XR class, -46%
pixels) is the only useful candidate; needs MG exclusionArea/ArtworkDeviceSubType edited to XR values. Phone
parked r109 (MG cache original restored earlier). WSL/disk cleaned (xnu old builds, simg, dmgs, mesa-t24s*).

### 2026-10-28 20:30: task 25 small canvas: kernel/ADT path works, UIKit status bar blocks @2x; phone parked

Report: jasmine/PERF-RENDER-SIZE-20261028.md. Added j0111 (boot-args sweetfb_lw/lh, default off, CI guard),
`mkadt.py --canvas WxH --scale N`, `mkimg.sh CANVAS=`. Observed: 750x1624@2 boots, MDP upscales into
996x2160 at x 40, no faults; the MG cache must be removed for scale 2, and then SpringBoard shows the red
"No status bar visual provider" bar for 375x812@2 and 414x896@2 (radius 39); editing the MG cache's
39.0 (+776) to 41.5 did not change UIScreen's radius. No measurements, no user look, no install.
Only root change: MG cache plist deleted/edited/restored, byte-identical to the backup (c70accbb...) before
parking. boot_b untouched. Phone r109 charging shell 71%. Next: find the corner-radius source or hook the
provider choice (needs UIKitCore disassembly); see report.

### 2026-10-28 19:26: Mesa and ios-tools build on the local macOS VM too: `tools/vm-mesa.sh mesa|ios TAG`

`tools/vm-mesa.sh mesa TAG` -> xnu/out-mesa-TAG (the mesa-ios artifact's 5 files), `tools/vm-mesa.sh
ios TAG` -> xnu/out-ios-TAG (ios-tools' 5 files); OUT=xnu/out-mesa for the tools/g2 push scripts.
Sends mesa, ios, tools (uncommitted edits too) to `ssh mac`, runs tools/mesa-local.sh there with
the same flags, meson options, ninja targets and ad-hoc signing as xnu.yml. Takes the same
~/topaz-xnu-build/.lock as vm-build.sh. Mesa: cold 119 s, warm 6 s (~/topaz-mesa keeps the
pristine 26.2.5 clone and mesa-src/build; patched tree synced by content, so only changed files
rebuild); ios-tools 4 s. Entitlements byte-identical to CI 40717125371's gltest; SDK is iPhoneOS
18.0 (Xcode 16, as on the macos-15 runner), so binaries differ slightly from macos-14 runs. Not yet
run on the phone. Toolchain (one time, done): `ssh mac sh -s < tools/vm-mesa-setup.sh` built
OpenSSL 3.5.9, Python 3.13.18, bison 3.8.2 from upstream source into ~/topaz-mesa/tools + meson 1.12.1
venv (Mesa 26 needs Python >= 3.10, bison >= 3; Sonoma has 3.9.6/2.3); system flex 2.6.4.
Known: TASK24_CONTROLS=1 fails (reverse of patch0008 conflicts with 0009/0010); CI would fail the same.

### 2026-10-28 19:15: kernel builds now on the local macOS VM (no CI queue): `tools/vm-build.sh TAG`

`tools/vm-build.sh TAG` sends this checkout's xnu/patches + tools (uncommitted edits too) to the
Sonoma VM on the Proxmox server (`ssh mac` = telegdyd@192.168.1.123), runs tools/build-local.sh
there and writes xnu/out-jasmine-TAG/kernel.development.sweet, same place as the CI artifact, so
tools/g2/mkimg.sh TAG follows as usual. Warm build ~60 s (ccache 100%), cold 233 s; CI was 3-4 min
plus up to 16 min queue. Lock on the VM serializes sessions. Same 4 skipped darwin-xnu-build
patches as CI run 40609825244; all of ours apply. Kernels are not byte-reproducible (UUID etc.)
but size and segment layout match between VM builds. Not yet booted on the phone.
VM toolchain: Xcode 16.0 exported from macos-15-intel (branch xcode-export), IIG replayed from
~/topaz-xnu-build/legacy-iig like xnu.yml; KDK 13.5 + ccache/ninja/jq/cmake in ~/topaz-xnu-build
(no Homebrew: it dropped Intel). Mesa/ios-tools: see the 19:26 entry. The VM is now the default
build path (AGENTS.md); `tools/g2/gpu-round.sh vm vm TAG` builds both there (IOS_RUN=vm too).

### 2026-10-28 18:02: GMEM stage 3 EVALUATED; no global gain, no promotion, phone parked

Evaluation/report commit: d973634; code fixes: 649993e and ac758d5.
Report: jasmine/PERF-GMEM-STAGE3-20261028.md (plan and task 24 row updated).
Mesa macos-15 CI 40717125371 PASS, head 26ad0b2 (driver d7db729); lib d39a3243...,
gltest 27a1dcb0... under ignored research/t24/stage3/ci-40717125371/.
Pixel gate PASS 16/16, 1264 checks, actual GMEM on all required big target sizes.
Same-lib valid GPUPROF g0 vs g1-fixed: Home 27.46->27.94 GPU ms/frame, CC 34.61->36.75;
Home sysfb full still 14.37 ms/frame. Actual 1131x2442 CA target reaches GMEM.
Original s3gp-g1 INVALID for mode2 comparison: cmdline truncated, lost sweetgpu_tickets=1.
Fixed image shim/out/shim-boot-j0110-s3gp-g1-fixed.img (604 bytes, d87902c8...).
Guard against oversized/NUL cmdline committed 649993e; WSL driver diff matches 0010 exactly.

Four complete framebench exports (150s settle, GPU 588 / DDR 1804 / CPU auto): baseline1,
g1a2, baseline2, g1b. Rates Home B 33.90/32.88/32.28/32.95; CC A 25.30/22.51/23.56/22.85;
CC B 24.16/23.58/23.58/23.42; Spotlight 26.26/27.81/25.74/25.32. Mean changes Home -0.52%,
CC A-7.18%, CC B-1.56%, Spotlight+2.18%; no consistent gain/p95 improvement.
Evidence research/ab/s3fb-*/; all four complete exports zero dropped events/samples.
Partial s3fb-g1a EXCLUDED: timed out during Home A, no swaps there, metadata export incomplete;
cause unresolved. Fresh two GMEM captures completed. Request-failure logging committed ac758d5.
Six valid measurement boots: zero SMMU fault/panic/ticket-submit errors. Static Home/CC/
Settings/Safari look intact; NC bands/stale regions in BOTH baseline and GMEM dumps: not visually
signed off, cause unproven. User motion check has NOT happened.

Final production lib readback 4780fbaaafcf680cbf709f4c40512499576ba09e3442f62ace41e7031ee214b8.
Test libs s2/s3 REMOVED, gate executable removed. Future test images need library copied first.
No install, flash, kernel or clock change. Phone r109 charging shell: 71%, +0.56 A at 18:01,
backlight 0, float 4050000; own phone-gmem-active/framebench-private locks released.

Recommendation: keep current timed GMEM rule OFF, do not install as-is. User agreement on
keeping it off vs continuing feedback-path redesign is outstanding; task 24 is not installed/done.
Not attempted: per-barrier split, mid-pass resolve, or margin/sample/retry tuning. If continuing,
start with measured Home feedback cost, separately pixel-gate/measure any redesign. Stage 1/2 fixes
also remain uninstalled in production. Unrelated tracked tools/build-local.sh edit left untouched.

### 2026-10-28 17:52: second baseline captured, final GMEM run next

s3fb-base2 complete/exported: Home32.28/s (median28.304 p9550.857),
CC A23.56/s (38.564/62.162), CC B23.58/s (39.101/67.412),
Spotlight25.74/s (34.021/67.436). Baseline Home range32.28-33.90 already
encompasses g1a2 Home32.88; no supported Home uplift yet.
Phone parking; next s3fb-g1b --standard-only --final-check, then report/plan/NOTES.
Final-check verifies production4780fbaa and removes only test libs s2/s3 before parking.
All original CI artifacts remain local. No production replacement or flash authorized/performed.

### 2026-10-28 17:44: first VALID GMEM framebench complete

s3fb-g1a2 captured/exported successfully; same image/env/settle as excluded g1a.
Home B 32.88/s (median28.184 p9546.227), CC A22.51/s (40.173/65.167),
CC B23.58/s (39.848/60.799), Spotlight27.81/s (35.003/56.156).
Baseline1 Home33.90, CC25.30/24.16, Spotlight26.26. Mixed result, no global gain.
Fresh attempt passed all phases; original timeout cause still unproven. GPU588/DDR1804
readback, all10102 GPU submits completed. Phone parking; next baseline2 then g1b.
Evidence research/ab/s3fb-g1a2/; report must exclude partial s3fb-g1a.

### 2026-10-28 17:38: first GMEM framebench PARTIAL; fresh attempt next

s3fb-g1a stopped at 17:36:18 with command-port timed out during Home A (capture23.3s),
metadata export also timed out. Spotlight repeat 25.35/s and warmup31.00/s, but
Home A no swap arrivals during commanded motion; no Home B/CC comparison data.
Manifest status partial; EXCLUDE from performance comparison. Evidence research/ab/s3fb-g1a/.
GPU completed4271/4271 afterwards; no SMMU fault/panic/ticket error. Cause not established
(transport/sampling/UI response); do not claim GPU hang or clean acceptance.
Phone parked r109 71% at 17:38. Next fresh s3fb-g1a2, then baseline2/g1b.

### 2026-10-28 17:32: framebench sequence active

Baseline1 complete, no SMMU fault/panic/ticket error; GPU588 DDR1804 CPUauto verified,
max tsens 57.6 C at end. r109 71% before starting s3fb-g1a (first GMEM framebench).
Active helper research/t24/stage3/from-parked.py with private phone-gmem-active.lock;
framebench-private.lock is held only during capture. Run uses --standard-only (Home/CC/Spotlight),
150 s settle, no app captures/dumps repeated because GPUPROF already captured them.
After g1a: s3fb-base2 then s3fb-g1b; all return to charging shell. Report is WIP.

### 2026-10-28 17:30: first uninstrumented baseline framebench complete

s3fb-base1 (stage2 lib 1772b043, full mode2/tickets/queue args, 150 s settle):
Home B 33.90/s (median 28.169, p95 45.661 ms); CC A 25.30/s (37.325/56.815),
CC B 24.16/s (37.216/63.550); Spotlight repeat 26.26/s (34.443/66.036).
Evidence research/ab/s3fb-base1/ and logs/netlog-s3fb-base1.txt. Standard workload only;
app profiles/screenshots already captured in GPUPROF boots. Phone parking after run.
Next s3fb-g1a, then s3fb-base2 and s3fb-g1b. No install/flash/clock changes.

### 2026-10-28: corrected GMEM GPUPROF has no gain so far

s3gp-g1-fixed confirms full sweetgpu_tickets=1 and live BEGIN/SEAL, no errors.
Home (1000 trimmed frames): 101.8 draws, 19.4 batches, GPU 27.94 vs g0 27.46 ms;
2.67 GMEM batches/frame (1.7 full, 5.86 ms); retained sysfb full 14.37 ms.
CC (400 trimmed frames): 194.4 draws, 62.6 batches, GPU 36.75 vs g0 34.61 ms;
13.22 GMEM batches/frame (3.2 full, 6.47 ms), splits 5.67/frame. Settings scroll
9.73 vs g0 8.80 ms. No SMMU fault/panic/ticket error as of workload.
Initial g1 numbers above remain invalid because its image lost ticket boot arg.
Next: finish screenshots/park; alternating uninstrumented s3fb-base1, s3fb-g1a,
s3fb-base2, s3fb-g1b (images verified full mode2/ticket/queue args). No install/flash.
WSL driver source restored: its diff matches committed 0010 exactly (no flush diagnostics).

### 2026-10-28: GPUPROF g1 image bug found; original g1 result INVALID for mode2 comparison

Observed: shim-boot-j0110-s3gp-g1.img has 607-byte truncated cmdline ending swee,
so sweetgpu_tickets=1 is absent; g0/base retain it (606 bytes). This invalidates the
first g1 vs baseline comparison; per-draw flushing may be the capability fallback.
Same-library g0 Home: 18.6 batches/frame, GPU 27.46 ms, wall 29.3 (1000 trimmed frames).
Built shim/out/shim-boot-j0110-s3gp-g1-fixed.img from g0: add GMEM=1, omit default-zero
sweetgpu_debug=0; 604 bytes, full sweetgpu_tickets=1 retained. SHA256 d87902c85c8c88701087a00839a73321f25e42590685144f7c84bd4b1f31c2bd.
Manifest research/t24/stage3/g1-fixed-image.json verifies only cmdline/digest changed.
tools/mkpayload.py now rejects oversized/NUL cmdlines instead of silently truncating.
Checked 608-byte rejection, NUL rejection, 607-byte acceptance. No driver fix or diagnostic CI
needed yet; temporary diagnostic patch was reverted in repo (WSL source still has opt-in diag).
Next: finish g0, park, rerun fixed g1 as s3gp-g1-fixed; then four framebench runs.

### 2026-10-28: first GMEM GPUPROF completed; batching regression under investigation

s3gp-g1 (CI 40717125371 lib d39a3243): Home trimmed 200 frames, GPU 25.50 ms/frame
(vs stage2 27.40), but 106.6 batches/frame (baseline 18.6), 101.3 one-draw,
105.6 context-flush ends/frame; wall 85.7 ms/frame. Only 0.76 GMEM batches/frame.
CC has insufficient windows to trim; untrimmed GPU 29.28, 178.6 batches/frame.
Settings scroll GPU 10.78, 134.5 batches/frame. Settings-sub no complete 100-frame window.
No SMMU fault/panic/ticket error observed. Home dump visually matches baseline except clock/battery.
Evidence logs/netlog-s3gp-g1.txt, research/t24/stage3/s3gp-g1-* and *-summary.txt.
Phone returned to r109; battery 73% at 17:03. Next: same-lib GMEM-off s3gp-g0 control
to isolate per-draw flushing before spending four framebench boots. No install/flash.

### 2026-10-28: GMEM CI 40717125371 pixel gate PASS

16/16 cases PASS (14 cases 84 checks each, two diagnostics 44 each); gate-ci40717125371.
Required GMEM decisions: 1127x2438=200, 1131x2442=100, 1125x2436=200.
Test lib readback d39a3243... matches CI; production 4780fbaa... verified before and after.
Test binary removed by gate. Next: park then s3gp-g1 profiling, followed by alternating
framebench runs and report. No production install or flash.

### 2026-10-28: GMEM macOS 15 CI PASS; pixel gate started

CI 40717125371 PASS (head 26ad0b2, includes d7db729). Downloaded to ignored
research/t24/stage3/ci-40717125371/mesa-ios/. SHA256 lib d39a3243e297816f799dbee5ed564cfcc32151c47fa35122a8d85208174b203d;
gltest 27a1dcb006c50d647caf35679dfc5a49a2ea7ac59fb2f8ba46711950f6fc186f.
Battery observed 75% in r109. User requested continuation; booting installed iOS for
16-case pixel gate (gate-ci40717125371), then temporary GPUPROF/framebench boots if PASS.
Private ownership lock research/t24/stage3/phone-gmem-active.lock while gate runs. No flash.

### 2026-10-28 16:34: GMEM Mesa build re-dispatched on macOS 15 (user request)

User asked to try macOS 15 again. Dispatched xnu.yml on jasmine with build=mesa,
mesa_runner=macos-15: **CI 40717125371**, head 26ad0b2 (includes d7db729's pitch/extent fix).
Observed via GitHub API: Mesa job 122917756131 labels=[macos-15], queued, no runner assigned yet.
The superseded macOS 13 run 40710191541 is now completed/cancelled (workflow concurrency).
No build result or new artifacts yet; no device action. Next: check 40717125371, download its
mesa-ios artifact on success, then perform the 16-case pixel gate from the handoff below.
Run: https://github.com/telegdyd/ios-jasmine/actions/runs/40717125371

### 2026-10-28 16:25: GMEM stage 3 PAUSED again (user request): extent question answered, baseline GPUPROF done

Resumed from the 06:55 handoff (below). Nothing installed or flashed, no clock change, production lib 4780fbaa
unchanged (gate checks). No backboardd boot with GMEM yet.

**Observed:**
- Gate run with CI 40703479133 (308348e, decision + unsafe log, lib d5d99bf9, gltest 9239a552), force mode, installed
  iOS: PASS 76/76 checks, but **every imported IOSurface target was `sysmem:unsafe`**, GL allocations went GMEM.
  Log: `pitch 4544 < 1152 px` for 1125/1127/1131 wide, `384 < 128 px` for 67x45: on a512 `gmem_align_w` is **64 px**,
  and the test IOSurfaces got the kernel's 64-byte rows (4544 = 1136 px). Upstream also requires GMEM-capable imports
  to have rows aligned to gmem_align_w px (fd_layout_resource_for_handle), our darwin override relaxes it to 64 bytes
  for sysmem. The one padded case (4800-byte rows) failed the extent check by 2 KiB with my 124 KiB margin
  (need 11827200, have 11825152; bo size = IOSurface alloc 11698176, shared=1). So the kernel's reported size is
  right; the rule was too strict on the pad and needed upstream's pitch rule.
- CoreAnimation's display surfaces have **4608-byte rows** (sweet_shot: pitch 4608 = 1152 px), so they satisfy the
  pitch rule. Whether CA's 1127x2438 / 1131x2442 intermediates do is not known yet (`gmem-sys-unsafe` drawevent
  will show it in the g1 GPUPROF boot).
- appwork.py coordinates checked with dumps: Settings icon (163,523) and Safari (541,2008) open; Settings restores its
  last page, so it is now entered with one edge swipe back; sub-page row = General, y 1601; taps 80 ms; edge swipe
  back works. Safari opens a cached page (colosseumrecords.hu).
- **Baseline GPUPROF boot s3gp-base** (stage-2 lib s2 1772b043, SYS_BARRIER=2, image shim-boot-j0110-s3gp-base.img,
  logs/netlog-s3gp-base.txt, `bash research/t24/stage3/summ3.sh s3gp-base`), per frame:
  Home 101.7 draws, 18.6 batches, GPU 27.40 ms (full-screen sysmem 12.8 batches 26.83 ms);
  CC 193.6 draws, 55.8 batches, GPU 32.99 ms; Settings scroll 127.5 draws, 26.7 batches, GPU 9.82 ms;
  Settings sub-page 64.4 draws, 12.1 batches, GPU 5.13 ms; app open/close 67.9 draws, 14.6 batches, GPU 16.98 ms
  (full-screen 6.6 batches 15.80 ms). App phases' wall ms/frame include idle and are not frame rates.
  0 SMMU faults/panics/ticket errors. Dumps research/t24/stage3/s3gp-base-{home,cc,nc,settings}.*.

**Code since 06:55 (pushed):** 308348e (unsafe log), d7db729 (0010: pitch must be a multiple of gmem_align_w px and
hold align(w,64); `SWEETCA_GMEM_PITCH_ANY=1` test override; pad = full 128 KiB; gltest big targets now 4608/4864-byte
rows plus one kernel-default 4544 case and GL alloc; appwork fixes). gate.py has a `force-pitchany` case
(informational: GMEM on 1136-px rows).

**Half-done:** d7db729 is NOT built: GitHub macOS runner capacity problems; runs 40699351392 (macos-15, attempts 1-2),
40705035918 and 40707645611 (macos-14) were cancelled with "job was not acquired"; **run 40710191541 (macos-13)** was
still queued at 16:24 and may finish on its own (check it; if it failed, re-dispatch one run at a time: the workflow's
concurrency group cancels an in-progress run of the same group).

**Exact next step:** get a build of d7db729 (or later), push its lib as `/usr/local/bin/libsweetca-s3.dylib`
(readback), run `python research/t24/stage3/gate.py <ci>/mesa-ios/sweetgpu_gltest research/t24/stage3/gate2 1`
(16 cases; needs GMEM decisions on 1127x2438, 1131x2442, 1125x2436). Then GPUPROF `s3gp-g1` (and `s3gp-g0` if a
same-lib control is wanted), framebench `s3fb-base` and `s3fb-g1` twice each
(`MSYS_NO_PATHCONV=1 python research/t24/stage3/s3run.py IMG NAME gp|fb --lib LOCALLIB [--lock <private>]`),
then the report jasmine/PERF-GMEM-STAGE3-20261028.md. Park (`bash research/t24/stage3/park.sh`) between boots.

**Phone:** r109 charging shell, backlight 0, charge voltage 4050000, **75%** at 16:24 (+0.67 A). Test libs on the phone:
`/usr/local/bin/libsweetca-s3.dylib` = dab30309 (CI 40638109900, rule v2 before the pitch fix; inert),
`/usr/local/bin/libsweetca-s2.dylib` = 1772b043 (stage 2). No gltest binary, no lock held. Temporary files: screen
dumps `research/t24/stage3/coords-*`, scripts in research/t24/stage3/ (park.sh, s3run.py, gate.py, one.py, summ3.sh)
and research/t24/stage3/scripts/ (0010 source sg_block.c + sg_apply_v2.py + edit_pitch.py, mkmesa-s3.sh), WSL tree
~/ios-work/mesa-t24s3.

### 2026-10-28 06:55: GMEM stage 3 PAUSED (user request): rule v2 built, not yet gated or measured

Task: per-batch GMEM in the driver (jasmine/PERF-GMEM-PLAN-20261028.md stage 3). Nothing installed, nothing flashed,
no clock change; production lib 4780fbaa read back unchanged at every gate run. No boot with GMEM in backboardd yet.

**Code (all pushed to jasmine):** c6a9d51, 81a9c97, a9b28b3, 9e0bc32, 32cf9cd, 77f9316. New
`mesa/patches/0010-freedreno-a5xx-gmem-select.patch` (default off: needs `SWEETCA_GMEM>=1` and forced sysmem;
`FD_MESA_DEBUG` stays `sysmem,nofp16`). Current rule (v2, 32cf9cd/77f9316): each kind of batch (batch-key hash,
draws, cost, clear/restore masks) is timed with RB_DONE_TS stamps around its whole pass (gpuprof's mechanism):
2 sysmem times, then 2 GMEM times (exploration), then the faster mode (GMEM must win by `SWEETCA_GMEM_MARGIN`,
default 110%); timed 1/`SWEETCA_GMEM_SAMPLE` (8), other mode retried 1/`SWEETCA_GMEM_RETRY` (64); 1-draw uncleared
batches never tried. Never GMEM: retained feedback barrier, depth/stencil, MSAA, layers, queries, tess, tiled/UBWC,
or unsafe extents (need offset + pitch*align(h,32) <= bo size, +124 KiB of j0033's 128 KiB scratch pad for imported
buffers; pitch >= align(w,16)*cpp). Feedback split: at the first barrier, if the prefix would go GMEM the barrier
ends the batch (prefix timed in retained batches by a mid stamp). `SWEETCA_GMEM=2` = force (tests).
`SWEETCA_GMEM_LOG=1` logs every decision. gpuprof: class `sysfb` (sysmem with retained barriers) and `fb N pre N`
in top lines; drawevents `gmem-select/-split/-sys-*/-measured/-time-*-us`. gltest: `--gmem`, `--gmem-force`,
`--env=K=V`, new step "gmem targets" (imported 1127x2438, 1131x2442, 1125x2436, 1125x2436 with 4800-byte rows,
67x45; GL alloc 1127x2438; cleared / restored / prefix+feedback, 3 rounds each, CPU model, canaries).
tools/g2/appwork.py (Settings scroll / sub-page / Safari open-close with bench marks, framebench manual capture;
coordinates from the home dump, UNTESTED on the phone), gpuwin.py accepts `sysfb`, mkmesa.sh applies 0010+.

**Observed on the phone (installed boot_b, test-name gltest, CI builds):**
- v1 used RB_SAMPLE_COUNT/SAMPLES_PASSED to estimate sysmem bytes. With counting on, large targets lose the second
  triangle of a full-screen strip (diagonal wrong-pixel maps, 1.37M of 2.75M pixels) in **sysmem too** (rule round 1);
  with `SWEETCA_GMEM_COUNT=0` (CI 40635722378, gltest ff662186) force-GMEM passes all 54 gmem-target checks,
  `--sysbarrier-wide --gmem-force` and `--feedback-diagnostics --gmem-force` PASS, hw binning on or off PASS.
  Hence v2 (no counting). Patching the bits out of GMEM batches only (CI 40636476995) still failed (sysmem side).
- Sysmem today already writes in 16x4 blocks: row padding up to align(w,16) and 2 rows after a 2438-row image change
  (canaries), in sysmem and GMEM alike; padding beyond the 16-px rounding never changed.
- Stage-2 six cases with the new gltest (incl. gmem-targets step in sysmem): PASS (gate1, CI 40636476995).
- NOT yet known: whether imported big IOSurfaces pass `sg_safe` (in the v1 runs no GMEM decision was logged for
  them; the decision log exists only from 77f9316 on). Guess: kernel-reported bo size is smaller than alloc.

**Latest build (not run yet):** Mesa CI 40638109900 (77f9316): libsweetca dab30309...5e25, gltest 2baf8911...6b41,
in ignored research/t24/stage3/ci-40638109900/.

**Exact next step:** boot installed iOS (battery >= 30%, gauge reading in r109), push the 40638109900 lib as
`/usr/local/bin/libsweetca-s3.dylib` (readback hash), run
`python research/t24/stage3/gate.py research/t24/stage3/ci-40638109900/mesa-ios/sweetgpu_gltest research/t24/stage3/gate2 1`
(14 cases; it now requires GMEM decisions on the three big sizes). If imported targets log `sysmem:unsafe`, check
`fd_bo_size` of imported bos (darwin_bo_from_handle size = kernel BUFFER_INFO out[1]) vs IOSurface alloc. Then GPUPROF
boots `shim/out/shim-boot-j0110-s3gp-g0.img` (s3 lib, GMEM off) and `-s3gp-g1.img` (GMEM=1) via
`python research/t24/stage3/s3run.py IMG NAME gp --lib <lib>` (+ `bash research/t24/stage3/summ3.sh NAME`), then
framebench `s3fb-base` (= stage-2 s2fb-l2 args, lib s2) and `s3fb-g1`, 2 runs each (`s3run.py ... fb --lock <private>`).
Images were built for the earlier lib path name only (sweetenv points at libsweetca-s3.dylib / -s2.dylib), so they
stay valid. Expect ~20-25%/h drain in iOS with GPU tests; park between boots.

**Phone:** r109 charging shell (temporary boot, slot b unchanged), backlight 0, charge voltage 4050000, 53% at 06:50,
+0.87 A. Test libs on the phone: `/usr/local/bin/libsweetca-s3.dylib` = bb34cc58 (CI 40636476995, OBSOLETE v1,
inert), `/usr/local/bin/libsweetca-s2.dylib` = 1772b043 (stage 2). No gltest binary left. No lock held.
Local: private Mesa tree `~/ios-work/mesa-t24s3` (WSL; working copy = 0010), helper scripts in ignored
research/t24/stage3/scripts/ (sg_block.c + sg_apply_v2.py regenerate 0010 onto a clean tree; mkmesa-s3.sh
regenerates 0001 and 0010), stage-3 scripts gate.py, s3run.py, one.py, summ3.sh, s3sum.py in research/t24/stage3/.
jasmine/PERF-GMEM-STAGE3-20261028.md not written yet.

### 2026-10-28 05:35: GMEM stage 2: fewer batches measured; batches -66% Home, GPU time and fps unchanged

[Report](jasmine/PERF-GMEM-STAGE2-20261028.md). Commit 167c44a: drawevent counters for sysmem clears and 0008's
decisions; `SWEETCA_SYS_BARRIER` is now a level (1 = old narrow rule, 2 = widened: any draw count, cleared batches
without clear split, other pending batches/deps, any uncompressed color format; still forced sysmem only); gltest
`--sysbarrier-wide` + one new check (fast clear + 7 feedback draws). Mesa CI 40622879956: lib 1772b043..., gltest
dd0c6707.... 9 temporary boots of j0110 with the installed mode-2 args (only sweetenv differs), no flash, nothing
installed. Observed: (a) CA never clears after a draw in one batch (`clear-blit-after-draw` 0, `clear-blit-zs` 0 in
all Home/CC windows; all clears fast, first-in-batch), so no live lost-clear glitch in these screens and 0009 costs
nothing. GPUPROF per frame Home prod/L0/L1/L2: batches 50.8/54.6/25.7/18.5, GPU 26.5/27.6/27.4/27.4 ms; CC
100.6/104.2/72.5/54.3, GPU 33.1/32.2/30.5/30.9 ms. L2 leaves 0 barrier ends on Home; remaining ends = resource
dependencies (11 Home/37 CC) + context (6/11). Framebench Home B L0 33.7/32.9, L1 33.2, L2 33.8/33.5; CC A/B within
noise. Pixel gate 6 cases x 4 rounds = 24/24 PASS (markers correct); Home/CC dumps correct for prod/L0/L1/L2; no SMMU
fault/panic/hang/ticket error. Guess: GPU time is the draws' DRAM traffic, not batch overhead. Stage 3 caveat:
retained-barrier batches are forced sysmem, i.e. L2 keeps the big Home composites out of GMEM; GMEM needs a split
at the first feedback draw, or targets barrier-free batches (CC 1127x2438 backdrop / 1131x2442 blur batches with
clears, ~10-11 ms each). Phone: installed boot_b, unlocked home screen, USB, iOS battery 56% (r109 read 64% at
04:47); production lib 4780fbaa read back; test lib /usr/local/bin/libsweetca-s2.dylib left (test name). Own lock
released (framebench). Evidence: research/t24/stage2/, logs/netlog-s2*.txt, research/ab/s2fb-*.

### 2026-10-28 03:35: task 24 pixel gate (GMEM plan stage 1) explained, fixed, four-case PASS

[Pixel gate result](jasmine/PERF-TASK24-PIXEL-GATE.md#2026-10-28-root-causes-found-fixed-four-case-gate-pass).
Installed iOS (boot_b) only, no reboot/flash/clock change; test-name sweetgpu_gltest binaries, removed
afterwards; production lib readback 4780fbaa... before and after. Observed (Mesa CI 40618671188, source
cac0ae9, `--feedback-diagnostics`, current + pre-0008, TC on/off, all four alike): draw -> clear in one
batch keeps the draw's pixels (imported and GL-allocated, also with glFinish after the clear; finish
before the clear passes); separately, 16-112 stale pixels in whole 64-byte lines only on imported
IOSurfaces, equal to the previous glReadPixels result; one depth-step failure in cur --no-tc. 0008 is
not involved. Causes: (a) a5xx fast clear (GMEM BLIT event) unordered after draws in forced sysmem;
(b) Mesa's CPU reads of cacheable imported IOSurfaces bypassed the kernel's lazy upkeep (j0053,
invalidate at IOSurfaceLock): darwin cpu_prep was a no-op and not even called. Fix commit 97c59cf: patch
0009 (sysmem: u_blitter clear after draws and for depth/stencil), darwin_bo_cpu_prep does
IOSurfaceLock/Unlock (fd_bo_cpu_prep calls it on Darwin), regenerated 0001. Mesa CI 40620265076 PASS
(test ec7135de..., lib bdba84c3..., NOT installed). Phone: 28 diagnostics PASS x4; --sysbarrier-off,
-on, -off --no-tc, -on --no-tc all PASS 21/21, marker only in the on cases; 5 more rounds of all six
(30 runs) clean; no SMMU fault/hang/panic. Guesses: the blit's write is overwritten (not dropped); the
depth flake is the same blit path. Open (stage 2, not started): does CA hit draw -> clear in one batch
(possible live glitch source), cost of u_blitter clears, then batch counts with 0008. Phone left in
installed boot_b, home screen, USB; own lock (scratchpad) released. Evidence: research/t24/stage1/.

### 2026-10-28 02:50: j0110 + mode 2 INSTALLED to boot_b (user OK "Yes, flash when charged")

boot_b = research/t16port/j0110-mode2-slotb.img, SHA256 9096026c48341ba083cc8d0e593953eb7aae7cb2d8ee3418177fb89f464684a3
(kernel CI 40611111142, 02b946d9...; args = previous boot_b + sweetfb_sleep=1 sweetfb_queue=1 sweetgpu_tickets=1 and
SWEETCA_PIPELINE=2 in sweetenv; same as the A/B-tested shim-boot-j0110-m2.img plus abmark=b). Production library unchanged
(4780fbaa). Before flashing, in the r109 shell at 21-32% battery: full 64 MiB boot_b backup (SHA256 8cffb7d3..., prefix =
the Oct 27 image 5c81dba1) + both GPT copies in ignored research/t16port/install-backup/ (manifest.json). Install by
research/t16port/flash-mode2.py: only boot_b flashed; exact readback PASS, boot_a unchanged (7ac7aeb5), both GPT copies
valid and equal to the backup except boot_b attrs 0x6f.. -> 0x3f.. + CRCs (flash-verified.json, flash-mode2.log).
Normal boot (fastboot reboot, research/t16port/normal-boot-mode2.py, logs/netlog-j0110-installed.txt): SWEET ENV
PIPELINE=2, tickets begin/seal/abort 1212/1211/0, stale/error/timeout 0/0/0, no ticket/submit error, no panic/SMMU fault;
SWEET AB marked boot_b successful in both GPTs (0x77..); home screen dump correct (3 surfaces 2/4/9). Rollback:
write research/t16port/install-backup/boot_b-before.img to boot_b (fastboot flash boot_b), or the Oct 27
research/cpu-dvfs/promotion2-images/cpu8-slotb.img. Phone left in installed boot_b, unlocked, home screen, USB.
Open: user's own look at motion; longer use (task 14 freeze history); CC A p95 slightly worse in the one A/B.

### 2026-10-28 02:20: task 16 mode 2 ported to j0110, +22% Home; NOT installed, phone charging

[Report](jasmine/PERF-TASK16-MODE2-20261028.md). User asked to stop measuring and implement the most
beneficial task; chose pipelined presentation (GPU sat idle ~10 ms/frame waiting for CA's next frame).
Kernel: t16-build1 commits (j0100/b/c, j0101) cherry-picked cleanly onto j0108 as xnu/patches/j0109,
j0109b, j0109c, j0110 (fb9e470), boot-arg gated (sweetfb_sleep/queue, sweetgpu_tickets). CI 40609825244
failed only in tools/cpuclk/surface-release-test.py (harness lacked writeLocks); fixed; CI 40611111142
PASS, kernel 02b946d9... in xnu/out-jasmine-j0110/. WSL port tree ~/xnu-t16port (branch t16port).
A/B temporary boots, same kernel/lib (tools/g2/abround.py): mode 0 Home B 27.1/s, CC 21.7/22.0, Spotlight
20.4; mode 2 Home B 33.1/s (+22%, 69 frames at one period), CC 23.2/23.0 (+4-7%), Spotlight 25.6 (+26%).
Mode 2 stayed on: 1239 BEGIN = 1239 SEAL, 0 aborts, 0 guard rejections, no SMMU fault/panic, dumps correct.
Images shim/out/shim-boot-j0110-m0.img / -m2.img (no abmark). Battery fell 39% -> 14% over the night's
USB-powered iOS boots: phone parked in r109 charging shell (backlight 0, +0.85 A, 10% at 02:15). Next:
charge to >=30%, user eye-check of mode-2 motion, then (user OK) build abmark=b image of j0110 with the
mode-2 args and flash boot_b. Rollback = current boot_b image research/cpu-dvfs/promotion2-images/cpu8-slotb.img.

### 2026-10-28 01:25: GPU per-batch/per-draw profile on today's build (user OK for temporary boots)

Two temporary boots (no flash): shim/out/shim-boot-j0108-gprof1.img (sweetenv + SWEETCA_GPUPROF=1,
SWEETCA_DRAWPROF=1) and -gprof2.img (GPUPROF=2); boot-args otherwise = installed boot_b minus abmark=b. Workload
tools/g2/gpwork.py; logs/netlog-gprof1.txt, logs/netlog-gprof2.txt (marker lines in
research/bottleneck-20261028/gprof*-work.txt). Per frame: Home 100 draws, 54 batches (45 full-screen, ~34 with one
draw), GPU 26-27 ms (23 in draws); CC 195 draws, 103 batches, GPU 30-35 ms (24 in draws, ~10 outside: ~26 glClear
per frame on full-size intermediates in sysmem). Batch ends: barriers 37-39 (Home) / 54-56 (CC) per frame from
self-sampling draws. Top Home costs: shader 0 (14 small quads, 5.2 ms), shader 3 full-screen blended copy (5.5 ms
each, 4.6 ms/frame), wallpaper passes (shaders 14+7, 4.2 ms), dock material (2.7 ms). Full-res blur (87-instr,
~11 ms/draw) only in a few CC-open frames. No SMMU fault/panic. Then command-port reboot -> fastboot reboot: phone
back in installed boot_b (log shows abmark=b, no gpuprof lines, DVFS auto). Report section "Where the GPU time
goes" in jasmine/PERF-BOTTLENECK-20261028.md. Next candidates: drop redundant sysmem clears/copies (CC), cut barrier
splits then GMEM (task 24), panel-sized rendering (task 25). Shader ids are not yet mapped to CA layers.

### 2026-10-28 01:00: frame-rate bottleneck measured fresh: GPU DRAM traffic

[Report](jasmine/PERF-BOTTLENECK-20261028.md). Installed boot_b (j0108) + production lib 4780fbaa, one boot,
no flash/reboot. New tool tools/g2/sensround.py: runtime clock setting + one framebench capture per config,
restores `dvfs auto 1`, `gpu clk 588`, `ddr 1804` (restored and read back). Measured (swap arrivals/s, Home B /
Control B): base 26.3/22.7, repeat 27.1/22.0; CPU pinned max 27.0/23.0; CPU pinned 1401.6 MHz 26.6/23.5 (no
effect); GPU 430 25.3/20.3; GPU 647 27.3/22.1; DDR 1296 22.3/17.2. `ddr bw` counters in motion: GPU busy
~400 Mcyc/s, 56-66% RAM-starved, ~5.3 GB/s. GPU busy/frame (CC) 34.9 ms, +18% at DDR 1296, +5% at GPU 430.
Intervals quantized to the 16.7 ms frame clock (Home mostly 2 periods, CC 2-3). sweetfb_hz=30 is not a cap
(all swaps take the sweetfb_sync immediate path). Conclusion: sysmem rendering traffic; tasks 24/25 are the
levers, CPU work (task 5/DVFS) is not on the critical path now. Not done: per-batch GPUPROF on today's build
(needs a temporary boot with SWEETCA_GPUPROF in sweetenv). Phone left in installed boot_b, home screen, clocks
at defaults. Locks: my lock (scratchpad) released; stale locks from earlier agents still exist and were NOT
removed: Temp/claude/phone-j0108.lock (Oct 27 19:11) and the framebench DEFAULT_LOCK phone.lock
("Codex CPU default promotion", Oct 27 15:57), so plain framebench runs fail until someone deletes them.
Raw data ignored under research/bottleneck-20261028/.

### 2026-10-28 00:50: ds8 libsweetca INSTALLED as production (user OK)

/usr/local/bin/libsweetca.dylib = Mesa CI 40601658380 (52b450f: ds8 + opt-in SWEETCA_TRIGGER/region inputs),
SHA256 4780fbaaafcf680cbf709f4c40512499576ba09e3442f62ace41e7031ee214b8 (phone readback matches). Backup of the
previous production lib (8cb5863ccf7c1ded43fc1bbb868e20e994ecdb3ac7b5c83e1d8754cc90779e1e, CI 40585335072):
phone /usr/local/bin/libsweetca-pre-ds8.dylib (readback verified) and ignored research/libsweetca-backup/.
Rollback = copy it over libsweetca.dylib and reboot. Rebooted into installed boot_b: backboardd logs all five
texture functions installed and the ds8 shader built; no SMMU fault/panic (logs/netlog-ds8-installed.txt);
home screen renders (research/ds8-installed.png). boot_b image unchanged. Note: the console port 5140 replays its
backlog on every connect, so a reconnecting reader sees duplicated lines.

### 2026-10-28 00:40: texture function 0x1c = ds8 implemented; material chain verified; NOT installed

0x1c is "ds8" (names from MetalContext::get_TextureFunction_decoder dictionary 0x1d5b82198; 0x1a ds4, 0x1b ds6,
0x1d ups ...). Not a full-program function in GL create_shader (mask 0x1f3fec000000), so an expression entry
works. capture_backdrop uses it for backdrop scale < 1/4 with offset[4] = (k,k),(k,3k),(3k,k),(3k,3k) texels;
blur_surface for 1/8 (sets no weight). libsweetca sca_ds8 = mean of the 16 mirrored bilinear taps, case byte
0x1c := 0x0f (offset/weight lookup). Commit 052afdc, Mesa CI 40588221824. Details: side-session notes
texfn-0x1c-ds8.md.
Device (temporary boots, probe lib only): ds8 shader builds (2D sampler), runs on lock and home screens, no
textured program-less draws left except one 6-vertex 981x426 draw at unlock (fn unknown), no SMMU fault/panic.
Visual: pill/dock unchanged vs before ds8 (dock gap 115,126,180; CPU renderer 249,251,253).
Diagnostics (commit 52b450f, Mesa CI 40601658380, lib SHA256 4780fbaa..., on phone as libsweetca-probe.dylib):
SWEETCA_TRIGGER=/usr/local/bin/sca-go gates SWEETCA_PASS_TRACE and SWEETCA_REGION until the file exists; region
draws now log float uniforms, constant vertex_color and the target pixel after the draw.
MEASURED (logs/netlog-s3-ds8atlas.txt, region 0:0:140:110 = backdrop atlas corner, after page swipes): pill
backdrop chain ds4 -> luminanceCurve(function_arg -1.03,0.9,0.6,0.3, amount color.a 0.5) -> colour matrix
(saturation ~1.6, offset .08) -> 2-axis Gaussian (p71/p89) -> fade matrix (p85); every pass's centre pixel equals
what its CA parameters imply (checked luminanceCurve by hand). Dock composite p73 samples atlas 0..0.095 x
0..0.045 (coord_arg). So no GPU step is dropped any more; the darker GPU material is CA's GL recipe/parameters vs
its CPU renderer (UNPROVEN which is "right"; compare against a real iPhone photo or the Metal path next).
Tips: unlock/keys via command port 5141 (tools/g2/uibench.py cmd: 'key 3 1; key 3 0', 'swipe 540 2150 540 900
250'); 169.254.7.2 is NOT reachable from this PC (s3round's sweetd wait just times out). Region probe dedups per
program/texture/fbo and stops at 150; it also matches the vertically mirrored rect and skips draws >3x the rect.
Phone: returned to installed boot_b (production lib unchanged, SHA256 8cb5863c...). Production install of the
ds8 lib needs the user's OK.

### 2026-10-28: Chlorophyll (Metal driver) forked for Adreno 5xx; submodule mesa/metal

Goal: Metal for iOS processes (CoreAnimation/apps ship AIR in .metallib) via Chlorophyll (AIR -> NIR -> ir3, Metal API
over Gallium freedreno), written for Bergamota / Poco F1 / Adreno 630. Fork: https://github.com/telegdyd/Chlorophyll,
`main` = untouched upstream (ry-diffusion/Chlorophyll @ 787338f), our work on branch `adreno5xx` (same commit, no changes
yet). Submodule `mesa/metal` tracks `adreno5xx`; remote `upstream` added in the local clone. Its own nested submodules
(Mesa 25.0.7, libdrm 2.4.124) are deliberately NOT initialised: we build against our mesa-26.2.5 + mesa/patches tree.
CI (xnu.yml) checkout does not fetch submodules, so nothing builds it yet. License MIT; keep NOTICE.md/LICENSE.hackios-userland.
Porting plan (from reading the repo, nothing built): (1) replace their libdrm stand-in over the Bergamota kernel with our
darwin backend (mesa/darwin/darwin_*.c); (2) forward-port patches/ from Mesa 25.0.7 to 26.2.5 (ir3-* should apply, ir3 is
shared a5xx/a6xx; fd6-fb-barrier-reorder is a6xx-only); (3) check a5xx Gallium caps (compute, images, SSBO) vs air_metal.c
needs. GUESS: libsweetca and the Metal lib in one process (backboardd) should share one Mesa/device, so build both from one tree.
2026-10-28 later: call sites mapped in mesa/METAL-PORT.md (read only, nothing built). Observed: all 9 Chlorophyll Mesa
patches fail `git apply --check` on 26.2.5 (WSL ~/ios-work/mesa 052f0a0, temp index); a5xx has caps->fbfetch = 0 (used by
their CA SDF path); our xf86drm stub's drmOpenWithType returns -ENODEV; SweetGPU has no cache-sync selector (they call
sweet_drm_bo_sync). Chlorophyll targets iOS 18 22H352 private Metal classes; we run iOS 16.7, so bgmtl.m/plugin/inject
need re-reading against iOS 16 Metal.framework (likely the largest part).
2026-10-28 iOS 16 check (offline, ipsw on WSL ~/ios-work/gl/dsc, iOS 16.7): every private Metal class/initialiser bgmtl.m
subclasses exists with the same superclass; MTLAddDevice exported; MTLCopyAllDevices NOT exported (inject must call
MTLCreateSystemDefaultDevice to build _deviceArray); plugin route identical in MTLRegisterDevices (IOAcceleratorES ->
MetalPluginName bundle -> MetalPluginClassName/principalClass, subclass of _MTLDevice -> initWithAcceleratorPort: -> MTLAddDevice);
our patch 0138 already publishes an empty IOAcceleratorES. Details mesa/METAL-PORT.md section 4. Not checked: metallib/AIR
versions of iOS 16 files (root image not on this PC).
Next: libbgair compute-only build on 26.2.5 + darwin backend in CI (port air-frontend/air-ir3/ir3-* patches), and pull
iOS 16 metallibs to run air2nir on the host.

### 2026-10-27 22:40: fixed libsweetca INSTALLED as production; glyph confirmed on normal boot_b

User OK'd install. /usr/local/bin/libsweetca.dylib = Mesa CI 40585335072 (c3c0f36), SHA256
8cb5863ccf7c1ded43fc1bbb868e20e994ecdb3ac7b5c83e1d8754cc90779e1e (phone readback matches).
Backup of previous production lib (SHA256 14e32aea4121e9c8a357da8f5e6322fe572a85f1c22e496990af0e687cb19261):
phone /usr/local/bin/libsweetca-pre-argbfix.dylib and ignored research/libsweetca-backup/. Rollback = copy it
over libsweetca.dylib and reboot. Rebooted (command port -> fastboot reboot) into installed boot_b; user confirmed
glyph visible after unlock. boot_b image unchanged. /usr/local/bin/libsweetca-probe.dylib still present (same fixed
build, unused by the installed boot-args). Open: texture function 0x1c (material backdrop, still flat).

### 2026-10-27 22:25: home Search pill glyph FIXED (libsweetca A,R,G,B images)

Cause (measured on device, logs/netlog-s3-region4.txt): the magnifying glass is a 28x28 IOSurface CA creates
around its own memory with NO pixel format (fourcc 0, bpe 4, 112-byte rows -> attachImage shadow target).
Its coverage is in byte 0 only ("lanes max 255 0 0 0"): CA's own 32-bit images are A,R,G,B in memory, and
fmt_from_surface(0, 4) read them as B,G,R,A, so alpha = 0 and the glyph invisible. CPU renderer showed it
(research/cpuref-home2.png). Fix: libsweetca shadow targets of fourcc-0 surfaces byte-reverse each pixel on
upload and write-back (surf_fmt.argb). Commit c3c0f36; Mesa CI 40585335072
(macos-15). User confirmed glyph visible; dump research/argbfix-home.png; no SMMU fault/panic.
Same boot had two more fourcc-0 shadow targets (53x42, 53x53 pitch 212), now also reversed: effect unverified
(user says status bar looks fine).
Ruled out on the way: QuartzCore NULL texture functions 0x19/0x28 never requested; 0x1c IS requested (backdrop
draws of materials go out with no program when it is NULL) but filling it did not affect the glyph; 0x1c remains
unimplemented. Untextured program-0 full-screen draws are normal state draws.
Diagnostics now in libsweetca (opt-in env, NOTE sweetenv splits values on commas): SWEETCA_TEXFN_PROBE=1,
SWEETCA_ZERO_PROBE=1, SWEETCA_REGION=x0:y0:x1:y1 (draws touching a screen rect + small targets, byte lanes).
CI: workflow input mesa_runner (macos-15 queues far less than macos-14).
Phone: running temporary image shim/out/shim-boot-j0108-argbfix.img with /usr/local/bin/libsweetca-probe.dylib
(= fixed lib). [Superseded 22:40: installed as production, see above.]

### 2026-10-27: rendering gaps investigated (home Search glyph, wallpaper); desk research only, phone not used

User report: magnifying glass in the home "Search" pill is missing; wallpapers do not look right.
Observed in existing dumps: research/wifi-integration/device/fixed-home.png shows the pill and "Search" text but no
glyph; SF Symbol glyphs elsewhere render (t5/step2-control.png Control Center, Settings chevrons), so it is a
specific dropped draw, not missing symbol assets. Lock/home background in every dump is the same plain blue gradient.
Wallpaper: research/wp-j70-oslog.txt PosterBoard logs `(_buildSwitcherConfiguration...) No selected configuration,
no configuration to fallback to` and `Failed to update switcher configuration ... Code=-2214`: no poster is
configured, so the gradient is SpringBoard's fallback, not a rendered poster (Settings > Wallpaper "CURRENT" shows
two gray snapshots, framebench/20261025-first/wallpaper.png). Gallery dump (gallery.png): Emoji/Color previews draw,
Astronomy blank (inferred: needs Metal, which no process has), black streak artifacts below the rows.
QuartzCore GL tex_fragment_shaders (0x1d5b48a10, dumped from WSL ~/ios-work/gl/dsc with a scratch reader):
NULL entries besides the four libsweetca patches (0x14/0x26/0x27/0x2d) are **0x19, 0x1c, 0x28** (0x33+ = table end,
assumed). A draw using one of them fails create_shader and is dropped silently; libsweetca does not log it.
GUESS (unproven): the pill glyph uses a vibrancy/compositing texture function that hits one of these, or a CA
filter the GL renderer skips. Next: (1) libsweetca: log texture-function ids whose table entry is NULL / failed
create_shader (hook point = the patched case table), boot temporarily, open the home screen, read which id;
(2) wallpaper: select a poster from the lock-screen editor (Color/Emoji first), then dump, to separate "no
configuration" from poster-extension rendering failures. Phone needs >=30% battery first (see below).

### 2026-10-27 19:30: j0108 INSTALLED to boot_b (exact readback PASS); first installed boot died at 11% battery

boot_b flashed with research/cpu-dvfs/promotion2-images/cpu8-slotb.img (SHA256 5c81dba1d8d64afdf7902beba6c4455276698bac5ff72d4887ffab1d841e7432,
CI 40551286401 / 6b9c52b, args incl. abmark=b, sweetgpu_debug=0, libsweetca injection). Used COPIES of the promotion scripts
(package-promotion2.py, flash-promoted2.py, verify-flash-metadata2.py, inspect-slot-metadata2.py, normal-installed-boot2.py,
sessionlib2.py + owner2.json = own lock in Temp/claude/phone-j0108.lock); old promotion-* proof files untouched.
flash-promoted2 stopped at its strict whole-GPT hash (known); verify-flash-metadata2 PASS: only boot_b attrs 0x77..->0x3f.. + CRCs changed,
boot_a unchanged. Rollback: research/cpu-dvfs/promotion-images/cpu8-slotb.img (previous j0107a install, exact readback verified).
Installed boot reached the command port and logged WLED backlight off/on, then the phone powered off ~19:18 (log ends, no panic text).
Fastboot afterwards: slot b current, slot-successful:b no (SWEETAB never reached 60 s), unbootable no, retry 6. Charging shell shows
battery 11%/3.68 V: INFERRED brownout from ~25 min of USB-powered test boots, not a kernel fault. Do NOT boot iOS below ~30%.
Phone now in r109 charging shell (temporary boot). Next: charge to >=30%, `fastboot reboot` into installed boot_b, confirm
`slot-successful:b yes`, sleep backlight, then release own lock (delete phone-j0108.lock).

### 2026-10-27 19:05: j0108 confirmed on device (temporary boot); NOT installed to boot_b

User confirmed backlight turns off on sleep and UI is smooth. Image shim/out/shim-boot-j0108-wledgl0.img = CI 40551286401 kernel,
mkimg.sh GPUDBG=0 EXTRA_ARGS="gpudelay=1 gpupause=0 sweetfb_sync=1 sweetenv=backboardd:DYLD_INSERT_LIBRARIES=/usr/local/bin/libsweetca.dylib".
PITFALL: plain mkimg.sh (no sweetenv injection) = CPU renderer, glitchy; default sweetgpu_debug=1 = near-frozen. Always pass both.
Phone runs this temporary image (reboot returns installed boot_b kernel, which still has the sleep bug). Installing j0108 needs
the promotion packaging (package-promotion.py not in repo; ignored/staged elsewhere) + explicit user OK for the boot_b flash.

### 2026-10-27: sleep leaves the backlight on - root cause found, fix j0108 NOT yet built or booted

Observation (logs/): 368 of 424 logs with `SWEET WLED:` lack `SWEET FB: backlight via the PM660L WLED`;
there AppleCLCD::start printed its lines BEFORE `SWEET PMIC/WLED` (e.g. netlog-t16-baseline.txt 106-118),
and display off logs only `display off` (no `backlight off`). Logs where the PMIC came first
(netlog-j70ddr-slotb.txt) do switch the WLED off. Cause (inferred from the ordering, not proven on device):
IOKit matches the display nub on its own thread while SweetPlatformExpert::start is still in
sweet_pmic_init, so sweet_wled_get() returned -1 and fWled stayed false for the whole boot.
Temporary boot 18:54 of CI 40551286401 (image shim-boot-j0108-wled.img, log logs/netlog-j0108-wled.txt): WLED path active, backlight off/on logged (lines 1554, 1898); PMIC happened to win the race here too, so one boot does not prove the fix. User eye-check of the backlight pending.
Pushed; CI run 40551286401 (jasmine, defaults, build=kernel) started 17:30Z. Fix: xnu/patches/j0108-jasmine-wled-after-pmic.patch (commit 6b9c52b; sweet_pmic_ready flag, AppleCLCD::start
waits up to 10 s). Applies cleanly on the CPU-DVFS tree. Next: CI build, boot, expect
`backlight via the PM660L WLED` at boot and `backlight off (WLED 0): 0` on the power button.

### 2026-10-27: boot_b installed + exact readback PASS; normal boot validation next

flash-promoted.py28589 stopped after exactimage readback because its overly
strict whole-GPT-hash check saw a metadata change. Read-only inspection found
ONLY boot_b attrs0x77000000000000 ->0x3f000000000000 plus header/entry CRCs,
as part of bootloader flashing. Successfulbit54 cleared; no partition layout,
GUID, name or any other entry changed. Both primary/backup header+entry CRCs
valid and arrays match. No manual GPT write/restoration performed.
verify-flash-metadata.py reverified exact17440768-byte image, boot_a original
hash and normalized completeGPT copies (only boot_b attrs +CRCs may differ).
promotion-flash-verified.json PASS. Do not claim GPTbytesunchanged; layout is.

normal-installed-boot.py now returning from chargingLinux tofastboot and issuing
plain fastbootreboot into installedslotb (not fastbootboot XNU). Ownlockheld.
Need installed startup CPU/RAM checks, observe SWEETAB success marking after60s,
physicalUI confirmation, then final docs and release collector/lock. No reflash.

### 2026-10-27: promoted default validated; user confirmed boot_b and flash sent

GREEN CI40529045995/f9b1bfd/job122276484978 PASS all ARM/default/image/core/
memory/surface/integration guards. KernelSHA256
aaaaa461bb7aebbff0ede2598c218779b758df7ddb353ba7d9ef67070a3fb1b4.
Actualmkimg (default AMP/CPUS/CPU_DVFS, no override) built8-core auto image:
promotion-images/cpu8-slotb.img,17440768bytes,SHA256
1072ca12ca416ee594fa75c0c09ede7e6d7592d7e40f1f497f24893742f96d80.
ADT differs from accepted AMP tree ONLY in fresh random-seed; hardware unchanged.

Temporary promotion-default8 probe omitted sweetdvfs/sweetdvfsauto flags and
automatically reached ready1/auto1. Arithmetic8x20 and5 cross-core RAM checks
PASS; both300MHz floors and stock2208/1843.2MHz maxima observed,zero faults.
User explicitly confirmed screenworks AND "Screen works—install boot_b" for
image1072ca12ca41, per AGENTS destructive-step confirmation requirement.

fastboot flash boot_b succeeded (Sending17032KB OKAY,WritingOKAY,0.562s).
flash-promoted.py native28589 is now temporarily booting r109 and reading back
exact image plusboot_a/GPT integrity. DO NOT repeat flash while it is active.
Current device in charging Linux for readback; own lock held. No other partition
flashed. Need readback success filepromotion-flash-verified.json, then run
normal-installed-boot.py (normalfastbootreboot,not temporaryboot), validate-startup
promotion-installed and physicalUI confirmation. Then final docs/push/toolrelease.

### 2026-10-27: corrected promotion CI40529045995 compiling; installation staged

Publishedf9b1bfd includes source53d1842/j0107a compile fix. Corrected default
buildCI40529045995/job122276484978 running; watcher native42840 saves logs and
downloads only green kernel. Local Mac builder also now defaults4K (a33fe71);
OSM rounds preserve manual semantics with CPU_DVFS0 and inferred AMP profile.
package-promotion.py expects this corrected run/head. Backup is complete and
phone remains r109 charging shell with own lock held. No flash yet.

Staged scripts: package-promotion.py invokesactualmkimg with overrides cleared,
checks8CPUADT and persistentargsabmarkb, emits promotion-images manifest plus
promotion-default-probe without explicitDVFSargs. validate-startup.py now takes
an output name (use promotion-default8, preserve older logs). flash-promoted.py
requires --confirmed-boot-b, temporary startup result and verified rollback;
checks singleJasminefastbootdevice, slotb,64MiB boot_b; flashes ONLYboot_b, boots
Linux temporarily, verifies exact image prefix/boot_a/GPTunchanged. Then
normal-installed-boot.py uses fastbootreboot (NOTfastbootboot) and records proof.
User-facing physical/flash confirmation still to request after concrete image
passes temporary test. Do not execute flash before that confirmation.

### 2026-10-27 16:14: promotion build include-path failure fixed; no flash yet

CI40526565989/af69432 FAILED actualARM compile: sweet_dvfs.h249 cannotfind
dev/sweet_board.h (OSFMK does not export BSD dev headers). Source53d1842 exports
j0107a with matching externint sweet_board_is(constchar*) declaration instead.
Board/default logic unchanged. No local clang executable available; actual
ARM retry required. No failed kernel booted, no persistent flash performed.
Phone remains charging shell, own lock held, rollback/GPT/boot_a backup verified.
Need publish/buildfix, update package-promotion.py expected green run/head before
packaging, temporary no-flags default boot +CPU/RAM/UI checks, then confirmation
andboot_b-only flash/readback/normalboot. Promotion scripts are staged ignored.

### 2026-10-27 16:04: promotion published, CI building, installed-slot backup verified

Publishedaf69432/source09756bf j0107 default promotion; CI40526565989,
job122267674679 building using workflow defaults (no topaz_4k override supplied).
Actual default/override/init/transition and shell profile tests PASS. No CPU
electrical policy/OPP change. scripts preservelegacy probes by explicitopt-out.

Phone currently r109 charging shell,slot_b,81%,Charging,+631347uA,33.5C at entry;
own lock held. Installedboot_b is /dev/mmcblk1p63 (not mmcblk0),64MiB. Full
rollback backup verified against phone SHA256
bc59109ca42bca06fa46edd0086c723e16c116014c06217ad7fd4de4d87cc844.
Both GPT copies backed up and entry CRCs checked; primarySHA
f4e2eb6c507421ee13d95444f800740a9c8de7631e37c5259d088eb23d20087f,
completebackupSHA520cef056c24f874ef48aa6278ea47d0c1e58d2bd239933b0512d1a93689938b.
Boot_a hash7ac7aeb57e293c744adec0c568e73485f405d4bc75d8753478d31e3c94156117.
GPT uses72x128 entries but reserves32 sectors for backup array; follow header
entry LBA. Earlier partialreadfiles preserved; valid filegpt-backup-complete.bin.
Manifest in ignored promotion-backup-20261027; attrsboot_a0x72000000000000,
boot_b0x77000000000000 (active +successful; not unbootable). No flash yet.

Prepared package-promotion.py to verify green build, run actual mkimg defaults
(no AMP/CPUS/CPU_DVFS env override), preserveGPU588/DDR1804/injection, addabmarkb,
check8-node AMP layout, and stage boot_b image plus separate no-DVFS-args probe.
Next CI result, package, temporary default-probe test, physical UI/flash
confirmation as required by AGENTS, then ONLYboot_b flash/readback +normalboot.

### 2026-10-27: user requests promotion, build and persistent phone installation

Explicit new scope: make8-core/scaling the Jasmine default, build and install
on phone. Own exclusive lock reacquired; entering r109 charging shell to back
up installed boot_b/GPT before install. No persistent flash yet. Repository
AGENTS.md requires confirmation for destructive steps; prepare concrete tested
image/backup before asking. Existing flash-slotb script documents older standing
boot_b authorization, but do not infer authorization for other partitions.

Source09756bf in isolatedCPU worktree exportsj0107: default scaling/auto enabled
only on Jasmine+TOPAZ_4K, sweetdvfs0 opt-out, sweetdvfsauto0 manual, non-Jasmine/
legacy builds off, OSM and legacyRPM/voltage probes excluded. Initialization now
runs without sweetcmd flag when the default governor is enabled. CI4K default
and push fallback now1. mkimg detects default-profile kernel marker and selects
AMP1/CPUS8/CPU_DVFS1, with explicit overrides and legacy-kernel compatibility.
Matched diagnostic images explicitly disable DVFS unless requested.
Actual gate/override, checker-init, transition/rollback and image-default host
tests PASS. Kernel build/device/default-image validation and installation pending.

### 2026-10-27 15:48: CPU scaling + Wallpaper hang acceptance PASS; tools released

User confirmed Wallpaper -> Add New Wallpaper hang is GONE. Rendering remains
incorrect; user explicitly deferred that separate issue.140 dense observations
during manual trial: wired491.2–605.4MiB, backing71.8–184.2MiB, backing repeatedly
released back to~72MiB and ended96.3MiB; zero VM waiters/GPU allocation failures,
zero DVFS failures/faults. Do not claim wallpaper rendering fixed or task14's
separate GPU buffer-free hang universally resolved.

Final clean temporary boot dvfs-ready8 uses GREEN CI40520184930/headba35bbc,
job122244862831, kernelSHA256
156b9ebf43cf605dd752993bfb7f3c10e52e01b2a4ab902aab663966906a540a,
imageSHA256 b704c63935b57dd41e96facb84c45e8ce2d7d4ad1e2f65d074b86f41c8dece1a.
Booted15:42:27, cpus8,sweetdvfs1,sweetdvfsauto1. Automatically ready1/auto1
after worker initialization without host auto-enable command. Arithmetic8x20
PASS, five additional8-core cross-cluster memorychecks PASS under active scaling.
Both stock maxima observed. Bounded startup idle window minGold1113.6/Silver300;
later final status also observedGold300 (Silver1843.2 busy84%). Prior same-code
auto run observed both300 floors. Startup/final failures0/fault0. User explicitly
confirmed physical unlock/touch responsive after this FINAL reboot too.

Phone LEFT RUNNING this temporary8-core automatic iOS image for user use, NOT
parked in charging shell. Persistent boot partition/defaults unchanged; reboot
returns existing installed kernel. Thermal policy remains off per user's scope.
Stopped only our verified dvfs-ready8 log collector; no CPU-DVFS Python scripts
remained. Released ONLY our exact phone lock15:47:43.918+01:00. Do not use the
phone now without reacquiring the shared lock. Final state/rails/creator dump
ignored dvfs-ready8-final.json; startup-result.json records exact test window.

Completed source commits: isolatedCPU worktreef74baa6 diagnostics andd5f8701
surface fix; publishedf52ccce/50ea09c/ba35bbc. CI40517147150 was compile-success/
guard-failure,40516338522 cancelled; final40520184930 all gates green. All
source changes committed/pushed. Current code uses opt-in boot args; ready
4/8 auto images/manifests are under ignored research/cpu-dvfs/dvfs-ready-images.
Task2 controller + temporary8-core UI acceptance complete. Future work: only
explicitly requested persistent deployment, extended usage, thermal policy or
deferred wallpaper rendering. No claim of exhaustive hardware qualification.

### 2026-10-27 15:38: green CI; auto8 UI responsive; Wallpaper trial ongoing

CI40520184930/headba35bbc SUCCESS, job122244862831. KernelSHA256
156b9ebf43cf605dd752993bfb7f3c10e52e01b2a4ab902aab663966906a540a.
Actual ARM build, memory diagnostic + actual surface-release regression and all
prior integration/source/linked-symbol guards PASS. Corrected guard accepts S.
Artifact executable __TEXT_EXEC and __DATA_CONST/__DATA segments byte-identical
to tested50ea09c kernel80a07f5b; __TEXT/__CTF differ. Comparison saved ignored
ci-40520184930/executable-comparison.json. No need conflate whole-file hashes.

Fixed8 manual24snapshots (~4.5min) completed without pressure; then sameboot
auto enabled15:30:09. Auto24snapshots (~4.5min) completed: wired272.7–279.9MiB,
surfacebacking61.9–66.1MiB, zero VM page waiters/GPU allocation failures and
DVFS failures/faults. Both clusters observed300MHz and stockmax2208/1843.2MHz.
User explicitly confirmed physical UI responsive WHILE SWIPING under auto.
Earlier33 full-OPP cross-core RAM tests +4-corebaseline test also PASS.
Old/new wired baselines differ in profiler allocations; do not present their
raw difference alone as an isolated memory saving from the fix.

User asked whether Wallpaper hang might be fixed, then explicitly asked to try.
Told them try now and kept monitoring. watch-wallpaper.py native87462 runs
observe-integrity integrity8-wallpaper at2s cadence,4 boundedwindows. As of76
snapshots: wired491.3–600.2MiB; surfacebacking peaked184.2MiB then fell71.9MiB;
no faults. User's physical gallery result pending async question; do not declare
Wallpaper fixed before reply. No plugin disabled, no wallpaper selected by agent.
Phone still temporary integrity8,auto1,own lock +collector held. NewgreenCI
dvfs-ready-images/cpu8.img prepared with auto-on boot flags, SHA256
b704c63935b57dd41e96facb84c45e8ce2d7d4ad1e2f65d074b86f41c8dece1a.
This image has NOT been booted yet; don't interrupt user's active Wallpaper trial.
Next finish trial, record physical result, consider final clean auto-on boot,
then final docs/commit/push and release only our lock when stopping.

### 2026-10-27 15:25: fixed kernel4/8 memory PASS; physical8-core UI responsive

Published CI guard fixba35bbc; CI40520184930 building, watcher native91457.
Kernel from50ea09c/CI40517147150 ARM compile/link succeeded but CI guard failed
on S-vs-T type. Downloaded exact kernel + buildtree; kernel SHA256
80a07f5bb50013de237ff9c2f9a9b0a422e1cd4b0d65e5a70a814801ca13fea7.
Independently verified remaining defined Mach-O symbols, WiFi/framebench source/
skip guards, hash/markers, and actual trapRelease regression against packaged
build source: all PASS. CI status remains failure, do not describe as green.
Local evidence recordedci-40517147150/local-symbol-source-verification.json;
integrity-images manifest explicitly records CI failure and local validation.

Temporary integrity4 boot + bounded4-core memorycheck PASS (67.65ms), then
clean reboot and matched integrity8.33 memorychecks PASS: boot, Gold7/Silver8
points up/down, joint stockmax and restored boot. Each8 CPUs x1MiB x4patterns,
correct pinned CPU reports and0errors. All allocations freed. Finalboot restore
Gold1747.2/868mV,Silver1382.4/872mV,APMsMX; changes15/17,failures0/fault0.
User explicitly confirms physical8-core touch responsive AFTER sweep.
New memory wired~280MiB initially vs old settled~470MiB; no causal claim yet.
observe-integrity.py integrity8-manual running native92278,4 bounded90s windows
(~4.5min total) beforeauto reproduction. Own lock +integrity8 collector held.
Next complete manual observation, autoenable sameboot and repeat memory/creator
monitoring + physical UI check. Corrected CI40520184930 stillpending.

### 2026-10-27 15:19: ARM kernel compiled; new CI symbol-type guard too narrow

CI40517147150/head50ea09c actual ARM compile/link succeeded, Build Done14:17:55UTC;
checker/RPM/voltage/DVFS and new actual-header memory tests PASS. Build step then
failed because new sweet_surface_stats nm guard accepted onlyT/t; this XNU uses
S symbols (as existing guards already allow). Correcting toTtSs. Remaining
surface-release/WiFi/framebench gates were not reached in that failed step and
must be verified before device testing. No new kernel booted. Phone remains
responsive recovery4c, own lock/collector held. Existing renderer crash first16
exception frames match2026-10-24 report, so that specific abort predates DVFS;
does not establish the cause of auto-correlated surface growth.

### 2026-10-27: published surface fix50ea09c; combined CI40517147150 pending

Source d5f8701 + j0105 memory/creator diagnostics published50ea09c.
Combined CI40517147150/job122234342766 queued; watcher fetch-ci.py native
session12307 waits with30s polls and downloads only successful kernel/logs.
Diagnostic-only CI40516338522 explicitly cancelled; do NOT boot its partial
artifacts. Actual ARM/device acceptance of new patches still pending.
Regression source verification: IOMemoryMap::setMemoryDescriptor retains its
descriptor via OSSharedPtr/OSRetain, so cached state mapping survives releasing
the surface. See jasmine/PERF-CPU-UI-FREEZE-20261027.md for exact reproduction.
Four-core recovery physical touch confirmed; six idle observations completed
with wired memory stable~452MiB. Current phone recovery4c, own lock/collector held.
Prepared ignored package-integrity.py verifies expected CI head/hash/markers/
regression logs; validate-memory.py covers baseline4 and full8-core OPP sweep.
Next verify new kernel build, temporary4 then8, memory tests, physical UI check
before automatic reproduction. Keep original eight-core freeze evidence intact.

### 2026-10-27: concrete released-surface pixel retention bug fixed; CI pending

Diagnostic milestonef52ccce/sourcef74baa6 pushed; CI40516338522/job122231111407
queued when checked. New follow-up build will supersede it with j0106 fix.
Four-core recovery ui-recovery4c booted cleanly and user explicitly confirms
physical touch responsive again. Six bounded read-only fixed4 observations
running; own phone lock/collector held.

Source inspection found fZombies retains SweetSurfaceRef for up to256 released
views PER CLIENT to keep16KiB state mappings. But each ref retained its entire
SweetSurface and pixel memory until eviction, contradicting the state-only
comment. This is a concrete lifetime defect, plausibly explains large retained
backing; relation to CPU scaling/frozen UI still requires device A/B validation.
j0106/source d5f8701 drops ref->surface after sweet_surface_put, keeping the
independent state IOMemoryMap. Other clients/GPU imports/ports keep own retains.
Actual trapRelease regression test FAILS on old code and PASSES fix: immediate
pixel release, state-map retention,256-view bound, repeated release counts and
independent live clients. j0105 memory test remains included. No voltage/frequency
or governor policy change. Need push/build, verify actual ARM compile and boot,
repeat low/max memory tests and idle auto scaling + physical UI acceptance.

### 2026-10-27 14:54: freeze reproduced after auto enable without interaction

Resumed by user. Own exclusive phone lock reacquired. Temporary verified
2550347 manual8 image booted as ui-idle8. User explicitly confirmed physical
UI responsive. Six fixed-clock observations, zero DVFS transitions: wired
memory settled ~470MiB, compression/pageout flattened, kernel idle profile
~32ms/s. Then enabled auto on SAME boot without synthetic checker/stress.
User confirms frozen again and NO interaction. This is a tighter reproduction;
do not attribute it to wallpaper interaction, heat or established voltage error.

Within the first automatic observation interval wired rose to ~1.55GiB.
Kernel snapshots before/pressure: wired506937344 ->1756545024 bytes,
surface requested backing276397704 ->1709990656, surface count169 ->627;
GPU BO mapped114393088 ->261390336, pool98959360 ->140902400. Counters overlap.
Process footprints remain small/compressed. Profiles show compression and
eMMC busy-poll writes; no observed outstanding GPU jobs or DVFS faults.
Ordered dvfs restore succeeded: auto0, boot1747.2/1382.4MHz,868/872mV,APMsMX,
Gold37/Silver680 changes, failures0/fault0. UI/userland pressure did not recover;
later vm_stat/ps timed out despite kernel port responding. No causal proof yet:
need distinguish clock/voltage-induced corruption from surface retention.
Clean reboot DID succeed: actual fastboot14:54:12.761. Recovery baseline4 next.

Prepared sourcef74baa6 in isolated CPU worktree: j0105 adds checkmem (1MiB per
CPU, four patterns, verified pinned writer/readers across half-CPU offset;
all allocations freed after started workers finish), plus surfaces command
grouping live backing by creator PID/name (creator is NOT current holder).
Actual header concurrent host tests4/8 CPUs PASS incl corruption injection,
wrong binding, allocation/thread-start failures and cleanup. Actual ARM CI
and device validation pending; no default/voltage/governor policy change.
Ignored research/cpu-dvfs/ui-idle8*,ui-auto8* preserve exact observations.
Own phone lock remains held. Next build j0105, compare memory integrity at
boot/floor/max and capture creator growth during controlled auto reproduction.

### 2026-10-27: paused in charging shell; DVFS tests pass, physical UI freeze open

Latest user request: put phone in charging shell and prepare for later. Usage
interruption prevented final documentation; resumed only to finish parking and
handoff. Fresh verified Linux6.19.10-sdm660/r109, slot_b, charger online1,
status Full/health Good, backlight0, battery99%,33.5C,+26855uA,4312977uV.
Released ONLY our exact verified phone lock; no matching CPU-DVFS collectors or
CI watchers remain. Temporary fastboot boot only; no partition flash performed.

Published code2550347 (j0104+j0104a), source736adf1 in isolated WSL
/home/teleg/xnu-cpu-dvfs branch codex/cpu-dvfs. CI40444015228/job121990838172
SUCCESS; verified kernel SHA256
bca76245a10547f39f1268e34f6b3dc164169776da64788ca7e72199396deffd.
Previous CI40442814374/e123e85 failed C declaration after label; fixed before
any new-kernel device boot. Actual ARM build, host core/command/fault tests and
source/linked marker guards pass. See jasmine/PERF-CPU-DVFS-20261027.md.

New manual8 kernel passed all Gold7/Silver8 OPPs up/down, ten min/max ramp
cycles and sustained maximum checks:60 stress commands, each8 CPUs x20 runs,
zero checker errors; restored-state check also passed.70 set requests,
Gold33/Silver35 actual changes, failures0/fault0, verified boot restore.
Automatic settled run passed10 load checks and38 status records: each cluster
observed300MHz floor and stock max (Gold2208/Silver1843.2MHz), failures0/fault0.
Floors were not necessarily simultaneous. First short10s idle-window test did
not see Silver floor amid background work; do not label that first run PASS.
No thermal policy/gate in new governor, as user directed (thermal=off).

Physical UI acceptance FAILED again: user says already frozen BEFORE touching
it on new8-core kernel. CPU/TCP responsiveness does not establish UI health.
Earlier4-core baseline physical touch explicitly recovered. New frozen-run
profile shows heavy VM/compression/pageout and UFS-write polling; DVFS worker
small fraction. Wallpaper processes were present without user interaction;
causal attribution remains unproven. No RAM/VM/UI recovery fix implemented.
Next session: fresh8-core baseline without transition stress, compare physical
UI and VM/storage behavior, then test RAM/coherency across OPPs. Do not claim
usable governor/default8 until physical UI acceptance. Defaults unchanged.

Ignored research/cpu-dvfs contains dvfs-manual-images/ and dvfs-auto-images/
manifests, ci-40444015228/, dvfs-live8*, dvfs-auto8-settled*, dvfs-busy-prof.*,
ui-profile-summary.txt and pause-final-charging.txt. Preserve dumps out of git.
Do not rerun boot waiters or acquire phone until user resumes device work.

### 2026-10-27 04:36: baseline physical UI recovered; fixed governor CI PASS

User hardware-reset successfully; actualfastboot04:35:40.084. Waiterbooted
known baseline-images/cpu4.img (accepted d42bfb4 kernel) as ui-recovery4.
Freshrails872/868/868,Gold1747/Silver1382,GPU588/DDR1804,APMs0. Sweetd/sweet_shot
works, lockscreenbufferreadbackcapturedignored ui-recovered4*. User explicitly
confirmed physicaltouchresponsiveagain. Earlierfreeze remainsrealissue with
severeVMpageoutactivity; noestablishedcausal attribution toclocks/heat/governor.
Newgovernor wasnotrunningduringfreeze. FixedCI40444015228/2550347 SUCCESS,
job121990838172; artifactdownload/hashverificationinprogress. Needtemporary
newmanual8, fullAPIsweep/ramp/sustainedchecks, automaticboost/idle proof and
physicalUIacceptance. Continueworking; ownphone lockheld.

### 2026-10-27 04:31: user reports physically frozen UI; recovery in progress

User says iOSscreenfrozen, touchandbuttonsdo nothing. This is realacceptance
failure despitecommandporthavingresponded; doNOTequateCPUcheckerPASSwithUI.
Stilloldbcdc037 manualkernel dvfs-max8; newj0104/j0104a notbooted. Allclock/rail/
APMrestorationshadpassed. KernelHIDlogsreceivetouches, GPUcompleted943/943 no
pendingjobsatobservedsnapshot. SilverL48/cfg501,GoldL5b/cfg301,rails872/868/868,
APMs0. VM_pageout_scan consuming~25sCPUper30swindow, compressor/compactionactive;
VMpressureislead, causalconnectiontoDVFSnotestablished. No newGPU/SMMUpanicseen.
Boundedprofiler/screenshotattemptsfailedconnect; userlandsweetd5143unreachable.
Kernel5141becameintermittent, thenrebootconnectrequests timedout. No actual
fastbootafter90s. AskeduserholdPower+VolumeDownuntilFASTBOOT. Ownlockheld;
wait-ui-reset.py awaitsfastbootthenboots knownbaseline4 forUIrecovery.
Do notsendanotherbootinparallelwiththatwaiter. NewCI40444015228/2550347
job121990838172 buildingcompilerfix. Continuegovernorworkafterphysicalrecovery,
includingphysicalUIacceptance. Do notclaimfullyusableCPUgovernoruntiltested.
FastPMICtestwhileoldkernelresponsive verifiedGold868/872immediatePMICvalid
without100msdelay; command+allrailreadbacks~2.2-2.3ms, thenrestored868PASS.

### 2026-10-27 04:24: first governor CI compile failure fixed, broader host coverage

CI40442814374/e123e85 FAILED in sweet_dvfs.h status handler: declaration after
report label rejected by ARM C compiler (line365). No governor kernel booted.
Sourcefix736adf1 exportsj0104a: declare n beforelabel; portableuint64formatcasts.
Hosttestnowcompiles actualcommandhandler too and exercises status/auto/manual/
restore/unsupportedOPP, inadditiontoactualtransitionfaultcases. AllPASS; runtime
fuse OPPs stillmatch Python+stockDT. CIrebuildnext. Phone8-coreoldkernelresponsive,
bootclocks/railsrestored. Framebenchdiscovery1sconnect timedoutonce; direct5s
BringupClientread state/rails succeeds. No hardwarewrite fromfailedfastvalid
preflight. No thermal policy asuserdirected; keepgoingthroughgovernoracceptance.

### 2026-10-27 04:18: full exact-OPP up/down sweep PASS; governor CI building

Publish e123e85 implements j0104 source276c227. CI40442814374 job121986917941
running4Kkernel. CIguardexecutes actualDVFScorefaulttests andlinkedready marker.
All-opps raw sweep completed upward+downward for Gold7/Silver8 points at each
point's own fuse-derived voltage (including1958/880,2150/928,2208/948;
Silver1843.2/900). All8x20 perpointPASS; bootrestorePASS. Goldremained300during
Silver sweep, so simultaneouslowGold+variableSilver also exercised. TSENSpeak
~73C recorded without thermal gating peruser direction. Own phone lock/collector
remain held; oldbcdc037 kernelcurrentlyrestoredbootstate. Newkerneldevice test
prepared in ignored validate-dvfs.py; no j0104 phone result yet.

### 2026-10-27: all stock CPU frequency points pass; complete governor prepared

On fresh temporarydvfs-max8 boot using bcdc037/CI40437789398, Gold1958/2150/
2208 and Silver1401/1536/1747/1843.2 passed all8x20 checker runs, including both
clusters at stock maximum together. RailsGold948/Silver900, APMAPC. Ordered
restore of boot clocks/rails/APMsPASS. Temperatures recorded; user deferred
thermal throttling and heat/cooldown acceptance gates. No frequency above stock.
Raw scripts/results ignored max-clocks-*. No persistent flash/default change.

Lower OPP sweep low-opps2 PASS: Gold300/692mV,1113.6/692,1401.6/748,1747.2/828;
Silver300/612,633.6/612,902.4/648,1113.6/696,1401.6/780,1536/816,1747.2/876.
All8x20 correct at each, ordered boot restorePASS. Initiallow-opps Gold300check
passed but following read-only TCPconnect hit existing1s timeout; finallyrestore
PASS. Repeated using5s connection timeout and no retryafter-send; allpointsPASS.
Gold300 timed~84ms/run, Silver1382~26ms; no arbitrary thermal rejection.

Pinned firmware HALclkHWIO.h confirms actual CPU array registers: SilverC0
+0x360/364; GoldC1+0x368/36c/370; PLL LOCK_DET atSTATUS+0x2c bit16. Existingboot
array settings retained throughout successful stock-max and low-OPP tests.
No guessed MEM-ACC setting written. Publicheader ignoredreference/; facts only.

Newj0104 source276c227 in ~/xnu-cpu-dvfs implements runtime fuse OPP tables
(bin1/rev2 validated DT path), full SAW16/APM/PLL transitions via300MHz safe
source, fast independent PMIC-valid polling, sharedmutex with oldcpuvolt,
ordered rollback/fault latch and per-cluster demand governor.20ms sampling of
recount busy/idle, busiestcorepercluster; >=65% fast stockmax, <35% five-sample
hysteresis; <10% floor300, otherwise one step down. No thermal policy as directed.
Oldj0103 70C guard affects onlylegacycpuvolt helper, notnewDVFS. New bootarg
sweetdvfs=1 starts after30s; sweetdvfsauto=0/1 controls initialmanual/auto.
Commands dvfs stat|auto 0/1|set 0/1 kHz|restore. Bothrequested/actualfreq,mV,
load/changes/failures/fault exposed. Auto muststopbeforemanualset; restore stops
it and restores originalbootpoints includingSilver1382.4. Headerhosttests cover
alllevels/divider/order/fiveinjectedfailures/rollback/latch/policy; runtime tables
match independentPython+stockDT+localrealchipfuses exactly; no fusedump committed.
Source,behaviorandlinkedmarkerCIgatesprepared; actualARMbuild/devicepending.
Phone stillrunningmanualtestkernel atrestored bootstate, ownlockheld, collector
active. Nextpush/buildj0104, verifyhash/gates, temporarymanualthenautogovernor
validation through allpoints/repeatedramps/load/idle and UI. Continue until CPU
scaling is usable; do not stop just after the next diagnostic milestone.

### 2026-10-27: user directs completing CPU DVFS first, thermal policy deferred

Latest explicit scope supersedes prior thermal acceptance gates: complete both
clusters' clock transitions, stock maximum validation and demand scaling now.
Do not reject bring-up solely for heat/cooldown; GPU/RAM power policy is still
unfinished. Observe temperatures, but defer thermal throttling until the CPU
backend/governor works. Keep electrical limits, status checks, checker errors,
timeouts and rollback. User already authorized milestone pushes/builds/phone.
Phone lock reacquired: charging94%,34C,+631835uA,4305408uV,online1/Good,slot_b.
Next temporary8-core boot and max-clock validation; no flash.

### 2026-10-27: SAW16 backend 4/8 PASS; APM crossover proven; upper rail tests bounded

Published implementationbcdc037; source00866db in ~/xnu-cpu-dvfs (branch
codex/cpu-dvfs). CI40437789398/job121970563336 SUCCESS, verified kernelSHA
1ba0349f842523a80094e06667db90edc0d0e64f98e9e3df535e42111b465f1b.
Actual ARM compile + actual-header fault tests + source/linkedmarker and prior
checker/RPM/WiFi/framebench/source/symbol gatesPASS; four expected upstream skips.
Default4 temporary boot refused both voltage requests without opt-in, unchanged
rails, fourcorecheck0errors. Probe4 and8 each3raise/restorecycles perclusterPASS;
all sixraised +initial/final pinned20runs/core checksPASS. Eightcorestartup100/
corePASS. Silver executing during8-core voltage steps. BothGoldS2/S3 readback
verified. FinalbootrailsS1872/S2-S3868mV, clocksGold1747/Silver1382/GPU588/DDR1804.
ImageSHA4ee43d970e74588cf8ae77f52bd3a35def7b4263df736c5746c91fc38262c1ad0;
8:014300f3feaa5913b36c63b674cef21e2f8a22bc70ace067c4aaba589692ec21.
Default/voltage manifests, full CI logs/hashes, rawresults ignoredresearch/cpu-dvfs/.

At872mV each APM acceptedAPCbit1 and acknowledgedmode3underlow5bitmask0x1f.
Goldstatus0x1f000003,Silver0xff000303. All8x20 passed while each selected.
Both restoredMXcontrol/status0 beforeGoldlowered868; noPLL/MEM-ACCwrites.
FirstGoldhostparser expectedunmaskedstring, skippedcheck andrestored; corrected
apm-gold2 includescheckerPASS. Source audit/pinned references in voltage report.
MissingMEM-ACC DTproperties are normal onTZ-initialized path, not register recipes.

Goldrange/APC: bothsupplies target+valid every4mVthrough948. ChecksPASS880/896/
912/928/944. At948hottestTSENSraw8=70.2C(Goldraw4..7max69.6), global70C diagnostic
cutoff stoppedbeforetopchecker. Restored872->MX->868andall8checkPASS. This is a
thermal-gate rejection, NOT fullrangeacceptance or evidence for higher clocks.
Silverrange/APC target+valid876..900, all8checks880/896/900andrestoredPASS, peak61.8C.
BUTprecedingcooldown(<58Cthreeconsecutivewithin180s)FAILEDandPowerShellcontinued
nextnativecommand. Record aswarm electricalevidence, notplannedcooledacceptance.
Correctedcooled-range.pyuses subprocess.run(check=True) for dependentstages.
Retainraw+reviewedresults. Never infercooldowngatePASSfromoriginalrangescriptPASS.
Default4firstcheck26-27ms/Gold, settledprobe4/8~14.3msGold/~26.1msSilver. No freq
change observed; startupcontentionpossible, notproven. PrintedMHzproxy isnotclock.

Userthermalflagcontract sweetthermal=0|1 default1 documented: bypassnormalcaps
for tests; independentemergency/sensorvalidity/OPPstockceilings retained. Flag
notfunctionaluntilgovernorconnected. Onlyj0103smalltwolevelhelperisimplemented;
fullOPPbackend/APMrollbackintegration/PLL/arraysequencing/loadgovernor/thermals
remainopen. NextauditarrayregistersfromtargetTZconfig, integrateprovenAPMsequence,
validatecooledvoltage+PLL transitions withrollbackbeforestockmaxGold2208/Silver1843.
No speedgain/default/installation/flashclaimed. Phonepartitions/libraryunchangedbyus.

Allthreebootscleanactualfastboot (default4 03:33:32.685,probe4 03:35:31.898,
probe8 2026-10-27T03:45:52.834396+01:00). FinalRootUnmount+3188ms,0wrapped/0GPUimports/0pins;
systemunmount+3190ms,no newruntimeGPU/SMMUfault/panicobserved. Temporaryr109
parkingbootSUCCESS. Freshfinalcharging92%,+757812uA,4287098uV,34C,online1,
Charging/Good,backlight0,slot_b. Finalreading+lockrelease2026-10-27T03:47:44.837977+01:00.
Ownlockreleased; noPythoncollector/testprocessremained onfinalCIMcheck. CIwatcher
session53361completed0. Reacquirefreshsharedlock/readinessbeforenextphonework.
Detailedreports jasmine/PERF-CPU-VOLTAGE-20261027.md and PERF-TASK2-DVFS.md.

### 2026-10-27 03:33: SAW16 helper ARM CI PASS; temporary tests starting

Publishedbcdc037. CI40437789398/job121970563336 completedSUCCESS; kernelSHA
1ba0349f842523a80094e06667db90edc0d0e64f98e9e3df535e42111b465f1b
matches SHA256SUMS. Actual ARM build, checker/RPM/SAW16 behavior tests, linked
helper marker and existing WiFi/framebench/source/symbol gatesPASS. Only four
expected upstream skips. Full final.log/run.json savedignoredci-40437789398/.
Default/probe4+8 kits packaged and independently hash checked by image tool.
Old-kernel opt-in rejectionPASS; deliberately removedSIZE negative testFAILS
as required. Full clock transition/governor/thermal policy still unimplemented.

Shared phone lock reacquired; freshcharging92%,34C,+478027uA,4285389uV,
online1/Charging/Good,backlight0,slot_b. Ownlockheld. Temporary default4 boot
in progress (no opt-in) to verify refusal before gated4/8 ramp tests. No flash.
Sourceaudit confirms missing CPU MEM-ACC properties are normal with TZinit;
no array/APM write attempted. Detailed audit in voltage report. New thermal
flag remains planned until governor is connected, not functional yet.

### 2026-10-27: serialized SAW16 backend prepared; thermal test flag requested

User resumed CPU work and requested thermal caps on/off for testing. Planned
sweetthermal=0|1 (default1) bypasses normal policy caps only; emergency protection,
invalid/stale sensor handling and validated OPP/stock ceilings remain independent.
Flag is a documented contract until governor integration, not functional yet.

New j0103 source00866db in ~/xnu-cpu-dvfs adds mutex-serialized SAW16 helper,
opt-in sweetcpuvolt=1, cpuvolt 0|1 [mV] (0Gold/1Silver; omittedmV=status).
Only demonstrated levels Gold868/872 and Silver872/876 accepted. Exact boot
PLL/RCG, OSMoff, APM/MEM-ACC baseline, wide-capability and PMIC type/mode/enable
required. Both Gold supplies must match target+valid. Request uses full16bits,
bounded2ms SAWpoll and100ms diagnostic delayed readback. Failure requests prior
verified voltage; unverified rollback latches fault until reboot. State shows
requested versus live-revalidated verified mV. Raises require all14valid TSENS
below70C (diagnostic precondition, not production thermal policy). Restoration
is allowed with hot/invalid sensors. No PLL/APM/MEM-ACC writes or new defaults.

Host actual-header fault-injection tests PASS (gates, pairedrails, ordering,
status timeout, PMIC mismatch, rollback and stickyfault). Six model tests PASS,
whitespacePASS. CI now requires source include, behavior test and linked marker.
Image tool strips inherited sweetcpuvolt unless --cpu-voltage-probe explicitly
requested; requires kernel marker before image output. Kernel ARM build/device
results pending. Phone has not been acquired/rebooted in this continuation yet.

### 2026-10-27: CPU voltage blocker resolved by SAW4 wide requests

User resumed after credit-related automatic-review failure; successful build
40414145643/40b6e3d downloaded and verified. Kernel SHA256
9cbfef7aee241bfbd9ca488e03766339cba408cfea169580dce2360de2b570c8. CI4 checker
and12probe host scenarios, integration/source/symbol guards PASS; only4 expected
upstream skips. Device kit research/cpu-dvfs/probe-images/manifest.json:
4imgSHAa01d83b816634fbd9648b273fabff2ffd387b0a6e7c109bfab3e6601a4a81fae;
8imgSHA9b15f4b1c8ddbfa3828babce9a8f32e5782994a3682e67f417da89cd76f193fb.
Only4coreprobe image booted;8core checker already passed on e74a086.

RPM neutral S1/S2/S3 ACK+unchanged. A same-boot S1 request872->876mV after
explicit UV+swen initialization ACKed but changed neither target nor valid;
restored872vote, verifiedCPU0errors, rebooted/parked. This does NOT demonstrate
RPM voltage control. No Gold RPM increase attempted.

Root-cause breakthrough: pinned public SDM660 HALavsHWIOSAW4.h defines VCTL
SIZE bit20, data15:0, address index18:16; PMIC_DATA_3 has same fields. SAW IDs
0x2020016f on both include wide-data capabilitybit8. Old Linux mask0x700ff and
size0 requests only sent one byte. No port remapping needed. Fullwidth request
0x100000|mV and fullstatus mask0x3ffff commit the upper byte. Source/report:
jasmine/PERF-CPU-VOLTAGE-20261027.md, pinned hashes and links. Firmware source
ignored in research/cpu-dvfs/reference/, no source copied into kernel/git.

Temporary saw16 boot02:53:09, Gold4online, Silverparked. S1 neutral872 passed;
at02:54:39 S1 target+valid872->876->872 PASS. At02:58:22 Gold SAW neutral868
then bothS2/S3 target+valid868->872->868 PASS. FourGoldx20 pinnedcheck0errors
at872 and afterrestore; finalcheck0errors. Delayed100ms readbacks, all supply
mode06/enable80/limits unchanged; GoldL0x5b/RCG0x301, SilverL0x48/RCG0x501,
APM/MEM-ACC unchanged, GPU588/DDR1804. No PLL/frequency increase, no APM switch.
SAW controller request/shadow state now wide; voltage restored to boot values.
Transaction lines420-480us are not isolated voltage settling measurements.

Production readback after tests SHA14e32aea4121e9c8a357da8f5e6322fe572a85f1c22e496990af0e687cb19261
matches before. Raw logs/scripts/snapshots: research/cpu-dvfs/saw16*, neutral-s*,
s1-step*, ci-40414145643/, comparison.json. User confirmed screenshot artifacts
are absent from physical display. Baseline report remains 2026-10-26: no clear8
coreUIgain at existingclocks, sampledCA render Gold-only. No drop/flash/root or
library change. Voltage proof is small-step only, not governor/max-frequency
acceptance. Next implement serialized SAW16 per-cluster backend with per-chip
OPP bounds and rollback; audit/validate PLL/APM/MEM-ACC transitions; add load
policy and independent CPU+board thermal caps before higher-clock defaults.
Stock CPU thermal client IDs map to physical TSENS; Goldraw4-7, Silverraw10.
Stock50/53C quiet trips are ADCboard temperatures, not CPU limits. Active plan
records mapping and source; no arbitrary production thermal limits installed.

Completed voltage milestone published2ba7681 on origin/jasmine. WSL sourceworktree ~/xnu-cpu-dvfs branch
codex/cpu-dvfs source12fd873; shared jasmine-merge untouched. Final actualfastboot
03:04:04 followed by successful temporaryr109 boot. RootUnmount+574ms, zero
wrapped GPU imports/pins. Fresh final charging:86%,+658202uA,4201893uV,34C,
online1/Charging/Good,backlight0,slot_b. final-charging.txt and lock-released.txt
record exact times. Own lock released after verifying ownership and readiness;
no session Python/console collector remained. Own CI watchers completed0.
No partition flash, root/library change, higher CPU frequency or new default.
Keep phone parked and take a fresh shared lock/readiness check for next work.

### 2026-10-26 23:44: CPU checker device PASS on4/8; neutral RPM kernel building

Published40b6e3d (matched baseline report + bounded neutral probe). Probe
CI40414145643/40b6e3d in progress, job121892076489. It must pass12scenario
hostprobe test, marker/call and linked-symbol guard in addition to prior gates.
No neutralRPMrequest sent yet. New image-tool --cpu-rpm-probe opt-in checks
kernelmarker; negative oldkernel rejection PASS before writing an output dir.
Host tool strips inherited sweetcpurpm so default packaging never enables it.

Checker kernel CI40410605951/e74a086 temporarily tested4 and8 cores from
checker-images manifest. ImageSHA4fa92ac98081f6b9eb421577cfa44830b65f0fadd8b596269bf28a20ce941846c;
8:85c03675f7601113076c843dabeb41220913eb6855a52d344fd1798efb89f6bf.
Both print SWEET CPUCHECK boot reference ready; no SWEET OSM setup/watch/probe
lines. Startup100runs/CPU0errors. Livecheck4x20 and8x20 zeroerrors; every
worker pinned to expectedCPU/MPIDR/P-E. Gold14.3ms/run, Silver26.1ms/run for
this deterministic workload; not frequency measurements. Host validator fixed
to accept MPIDR0 printed as0, not0x0. Actual8corecheck itself passed both times.
Rails unchanged872/868/868mV, GoldL0x5b/RCG0x301, SilverL0x48/RCG0x501, GPU588,
DDR1804. Checker4 cleanactualfastboot; phone nowchecker8, own console collector
and lock held. LastTSENS max61.5C. No clock/voltage increase or partition flash.
Next successfulprobeCI: verifyhash/logs, temporary4coreopt-inprobe image,
runchecker then neutralS1first (Silver parked), read/statuscheck, thenS2/S3 only
if priorrequestACK+unchanged. Firmware support unknown; stoponfailure. Parkr109,
verifyproductionlibraryunchanged, releaseonlyownlock and updatefinalhandoff.

### 2026-10-26 23:36: CPU baseline complete; checker CI PASS; RPM probe prepared

Report jasmine/PERF-CPU-BASELINE-20261026.md. Accepted kernel d42bfb4 used for
two settled4 and two settled8 captures; no event/sample drops, matching symbols.
HomeB4:21.84/21.57 arrivals/s versus8:22.10/20.28; CCB4:20.23/21.19 versus
8:20.50/19.97. No clear8coreUIgain established; these are swap arrivals, not FPS.
CA primary render onCPU samples Gold-only1103/1552 (4),1646/1666 (8); no Silver.
8-a excluded for post-unlock sync; repeated8-b/c have no Home/CC syncCPU samples.
User confirmed artifacts absent from physical display, present only in dumps.
Baseline8 clean actual fastboot, parkedr109/backlight0:98%,34C,+162597uA,
4265614uV,Full. Own phone lock held, no newclock/voltage/root/library/flash change.

Checker CI40410605951/e74a086 PASS. Kernel SHA256
13a35267c329e36dbc06036a6d14bd164c5485fb03f43dd0cc67684fcf4ee6b2 verified against
CI SHA256SUMS. Actual-function4scenario CI test PASS, WiFi/source/symbol/framebench
gates PASS, only4 expected upstream skips. Kernel/log/run metadata and packaged
4/8 images ignored research/cpu-dvfs/{ci-40410605951,checker-images}/. Actual ARM
compile PASS; device check pending. Existing publication bec6e41 includes images
tool and interim handoff. Need commit/push this completed baseline milestone.

New lead: stock DT declares RPM smpa1/2/3 CPU resources, but Linux consumers are
disabled for OSM. Firmware support unknown. RPM transport works sincej60/j64,
after the original SAW investigation. Raw single-key RPM writes are unsuitable
for a first CPU supply vote: voltage+enable must be explicit in one request.
Prepared late patchj0102 (free; afterRPMj60/j64 dependencies), WSL source12fd873
on ~/xnu-cpu-dvfs. Opt-in sweetcpurpm=1, command cpurpm1|2|3 (with a space).
Only reasserts S1872/S2-S3868mV, active set, uv+swen1 atomically. Prechecks exact
set/valid and enable; verifies unchanged readback; no PLL/APM/SAW/sleep/mode or
increased-voltage request possible.12 actual-function host-CC scenarios PASS,
CI source/linked-symbol/test gate prepared. No live CPU-RPM request yet. Next
publish/build probe, validate checker at4/8 normal clocks, then one neutral
CPU-RPM resource at a time with full console/status capture; stop on failure.

### 2026-10-26 23:29: Task 2 current baseline capture; diagnostic CI running

User explicitly authorized pushing CPU DVFS milestones and building/testing as
needed. Diagnostic repo commit e74a086 published on jasmine; CI40410605951
(topaz_4k=1, kernel, Intel) running Build. New patch source8214a77; no Apple
clang locally. Own phone lock still held (research/cpu-dvfs/owner.json).

tools/cpuclk/images.py packages matched4/8 temporary images with accepted
shim+AMP ADT unchanged; args differ only cpus=4/8. Omits sweetosm; fixes DDR1804
for both (accepted Wi-Fi baseline omitted sweetddr). Independent image hash,
Android header SHA1, payload/ADT/shim and arguments checks PASS. Existing accepted
kernel d42bfb4/CI40398100808 used for baseline before new diagnostic kernel.

Temporary baseline4 boot23:15, production readback hash14e32aea... exact. Gold
1747, Silver PLL1382, GPU measured587-588, DDR1804, S1 set/valid872mV, S2/S3
868mV; APM and MEM-ACC still0. Startup4core100runs0errors. UI Home screenshot
viewed. After unlock+settling (trustd/accessoryupdater0ms/s), baseline4-a/b
framebench captures PASS, symbols matched, no dropped records. HomeB21.84/21.57
swap arrivals/s, median47.788/47.442ms; CCB20.23/21.19, median46.718/45.115ms.
Not displayed FPS. HomeA in4-a had no swaps and is excluded. EndTSENS max58.5C.
Clean actual fastboot23:23:27; RootUnmount0GPUimports/pins. Temporary baseline8
boot followed, all8CPU_ON success and8core100runs0errors at unchanged clocks.

baseline8-a is INVALID for comparison: settling check was before unlock; after
unlock trustd/accessoryupdater resumed (~638/439ms/s in HomeA sampled window).
Retained raw data. baseline8-postunlock gate0ms/s, baseline8-b now capturing.
Both4core captures show no sync-process sampledCPU. Screenshot buffer2 has
horizontal artifacts, buffer4 clean; -s dumps all render buffers, not confirmed
active scanout, so neither displayed corruption nor clean visual acceptance
is established. No new runtime GPU/SMMU fault observed; startupFSR0x400 baseline.
All evidence ignored research/cpu-dvfs/. No voltage/PLL write, root/library
change or partition flash. Phone currently running baseline8, own collector on.
Next finish two settled8 captures, verify CI/build/artifacts, test fixed checker
at normal4/8 clocks, park r109 and release only own lock. Governor/max clocks
and voltage commit/APM investigation remain open.

### 2026-10-26: Task 2 diagnostic kernel prepared; phone available

User explicitly approved pushing prior milestone and continuing with full phone
access from charging shell. Pushed0c52b12+b437aed to origin/jasmine. Own shared
phone lock held, ownership ignored research/cpu-dvfs/owner.json. Fresh preflight:
r109 kernel6.19.10-sdm660,99%,34C,+498046uA,4395252uV,online1/Charging/Good,
backlight0,slot_b. No phone reboot/clock/voltage change yet in this continuation.

Isolated WSL source worktree ~/xnu-cpu-dvfs branch codex/cpu-dvfs based on wifi
f7c66dd; source commit8214a77 exports j0059a-jasmine-cpu-check-reference.patch.
It initializes osm_ref before sweetgold for sweetcmd-only boots and returns
before starting OSM workers. All four extracted actual-function host-CC branch
tests PASS; pre-fix negative control fails missing-reference assertion as expected.
No local Apple clang available; actual ARM compile requires CI. Workflow now
requires the marker and host behavior test so skipped patch cannot pass silently.
Six model input tests still PASS. Generated AMP ADT verified correct8 CPU MPIDRs
and Gold2208/Silver1843.2MHz max metadata. Apparent generic1900MHz value is already
overridden by Jasmine; no mkadt change needed. Remaining: commit/build4K diagnostic
kernel, verify artifacts, temporary4/8-core baseline at unchanged clocks, then
PMIC/APM commit investigation. Root/partitions remain untouched.

### 2026-10-26: Task 2 restarted for both CPU clusters; offline milestone

User requested eight cores, stock-max availability, demand scaling and heat
control. Active plan jasmine/PERF-TASK2-DVFS.md combines task2 backend/governor,
task13 thermal caps and task6 placement/comparisons; task12 idle collapse remains
separate. Existing eight-core bring-up is historical PASS CI39798911718/m4kf;
no new device result. Kernel baseline d42bfb4, current repo handoff d88af7e.

Implemented --cluster gold|silver|both in tools/cpuclk/cpuclk_model.py using
saved stock DT and downstream CPRh maps; missing fuse rows now fail, as do
conflicting captures and >64-bit rows. Six input-integrity tests PASS. Existing
j39f capture + local stock DT generate both tables; Gold before/after output
byte-identical SHA2567cbbfc65d76eb1ba5670cd06fdd9843e72867666f6e0429d1b3fe6d8e20e7927
(saved PowerShell output). Synthetic --zero both PASS, explicitly labelled.
Derived top: Gold2208MHz floor908/open948/adjusted ceiling948mV; Silver1843.2
floor860/open900/ceiling900mV. These are model results, not validated OPPs.
Ignored artifacts research/cpu-dvfs/{stock.dts,gold-before.txt,gold-after.txt,
both.txt,silver.txt,zero.txt}; no dumps added to git. Reference hashes in active plan.

Voltage blocker unchanged: prior988mV request changed target, not valid868mV;
rollback previously restored868mV. APM link is hypothesis. Do not reuse988mV
as an arbitrary target; scaled-open-loop ceiling is below raw DT ceiling.
Source audit found two diagnostic traps: sweetosm8 skips sweetgold; sweetcmd
alone leaves live check's osm_ref unset. Use sweetcmd without sweetosm for
read-only state/rails/tsens/r baseline; repair check initialization before relying
on it. State is Gold-only; Silver requires explicit reads. Historical broad
sweetosm1 probes hit SError on some CPRh registers. Existing startup Gold
checker covers online cores. Next: current4K 4/8-core baseline, then audited
PMIC multibyte commit/APM/MEM-ACC transition at an already-supported low clock,
with delayed valid/status checks and rollback before any higher PLL setting.

No new kernel patch/build/CI dispatch/boot/phone command/voltage or clock change,
root write/flash. Phone remains in inherited charging-shell state; availability
and battery not rechecked here. Task24 and accepted Wi-Fi defaults untouched.
Implementation commit 0c52b12: cpuclk: model both clusters and restart thermal
DVFS plan. Six input tests and diff whitespace PASS after final edits; Gold,
Silver, combined and synthetic CLI modes exercised. No CI run required for this
host-tool/docs change. Remaining backend/governor/thermal/device gates are open.
Publication pending: automatic approval review rejected the combined handoff/
pull/push command before execution, calling origin an unverified publication
destination without specific user export authorization. Committed handoff locally
in a separate command. No push occurred; ask user approval before publishing.

### 2026-10-26: Wi-Fi acceptance passed; merged directly into jasmine

Report: jasmine/WIFI-ACCEPTANCE-20261026.md. Accepted kernel d42bfb4,
CI40398100808 PASS (12m27s job). All48 patches/source/symbol/skip guards pass.
Initial8405096 failed Settings off/on; j0100b now calls normal leave on power-off.
On device: actual leave26ms, fresh rejoin, HTTPS browser access and USB coexistence
PASS; GL7/7 +9sampler controls PASS83.9ms,exit0. Home/Settings/browser/CC/NC checked.
Two repaired joined reboots PASS: system unmount+1130/+956ms, GPU imports/pins0,
actual fastboot22:07:19/22:13:16 Budapest. Off fallback: no modem/radio/wifid,
USB/sweetd/file/bench and lock-screen UI work, clean reset/fastboot22:18:39.
No new runtime GPU/SMMU/modem fault/panic; baseline startup FSR0x400 unchanged.
AP-loss/wrong-password/spare-network cases NOT RUN per user's skip instruction.

Accepted kit original research/wifi-integration/ci-40398100808/images/manifest.json:
kernelSHA4f9c55643af4913da5fda53556a3f835a2a705d1d07a6f4e4516509b1b184589;
default9a16325f...; diagnostic1c074e86...; offa6f3db0a... (full hashes in report).
Device raw logs/screens/scripts/hashes original research/wifi-integration/device/.
Production library before/after14e32aea... identical. Test GL/screenshot files
removed; own collectors ended; own shared lock released22:22:13.
Phone r109 charging shell, backlight0,slot_b,78%,+802245uA/4163075uV,34C,
online1/Charging/Good at final read. No partition flash/GPT change.
Code/tests complete for agreed gate. Origin jasmine fast-forwarded from e4ac03c
to acceptance commit168cdea; tested kernel source remains d42bfb4. Optional
draft PR1 is superseded by the direct merge. Slot-b
installation is not done and still requires explicit confirmation. No own
phone/background task remains. Task24 library/defaults were not changed.

### 2026-10-26: Device test found Settings power-off bug; repair building

User home, phone in charging shell, authorized tests. Own shared phone lock
acquired; ownership original research/wifi-integration/device/owner.json.
Preflight r109 kernel6.19.10-sdm660,77%,34C,slot_b. First temporary default
8405096 boot21:26:45 Budapest succeeded. Auto-joined known home network without
network selection (join t11497ms after modem start), USB command/file/sweetd
work while joined, bench stat idle. Production readback SHA14e32aea... exact.
Home/Settings screenshots render correctly. Safari example.net loaded and en0
DHCP lease read over USB. Production-matched GL control7/7 PASS,111.7ms,exit0,
test-name file removed. No new runtime GPU/SMMU/modem fault observed.

FAIL: Settings Wi-Fi off emitted framework link0/power0 but no firmware leave;
on emitted power1 and did not restore association in Settings. Source confirms
topaz_sta.c sta_power was unconditional0, leaving firmware S_UP while framework
said link-down. This is not counted as passing off/on recovery.
Stopped test matrix. Reboot captured in boot1.txt (initial collector retained
the stream; second collector got no payload). Actual fastboot return verified
21:40:16; temporary r109 parking succeeded. Charging73%,+717773uA,4084462uV,34C,
backlight0. Lock still held for this authorized repair/retest session.

Added j0100b: power-off invokes existing asynchronous topaz_wlan_leave, power-on
keeps firmware loaded. Actual callback extracted and host-GCC checked: on does
not leave, off leaves, error propagation preserved. Patch applies; source gate
requires the callback. New kernel CI pending. No partition flash or production
library change. User requested skipping spare-AP cases; AP-loss/wrong-password
will be explicitly NOT RUN. Need repaired off/on+internet/USB, two clean joined
reboots, off fallback, cleanup screenshots, production hash check and park.
All raw evidence/scripts remain ignored under original research/wifi-integration/device/.

### 2026-10-26: Wi-Fi offline preparation complete; three verified images ready

Combined 4KiB kernel CI40358833912 PASS, source84050968075304307e93f16baeb7f507725e8d70.
Build job16:24:42–16:49:07UTC (24m25s, cold supported Intel runner). All repository
patches applied; source and linked-symbol gates PASS. Pinned legacy IIG17
definitions replayed exactly, no RPC-layout change. Original macos14 brownout
and queued ARM attempts are superseded; kernel job now macos-15-intel.

Verified CI SHA256SUMS kernel2c281ee61aec20187df365d1b07d6f2b121109ad5bc4e06458e93dabd38051be.
Images ready under original checkout's ignored research/wifi-integration/
ci-40358833912/images/ (all17403904 bytes):
- wifi-default.img SHA256f17574a2054d2dd50399d2779e3e42770a98fb63f66cc242ba9a6c739cf975fe
- wifi-diagnostic.img SHA25638d87a4eca45f7229fb3600b663e8d276ee1bf7e42e694f52f1f5e54d046a771
- wifi-off.img SHA2565f2d3c0c7aa1df73708c1cb1e6b8954692cb3f5edff0252bfa5423bcf5beeef3
manifest.json records exact args/source/kernel/baseline/ADT hashes. Default and
diagnostic preserve j99's exact shim+hardware ADT; off removes only wlan node.
Independent image SHA256, Android SHA1 header IDs, payload roundtrips and
variant arguments PASS. Default has no modem/wifi/delay args (tests defaults);
diagnostic adds wifi_diag=1; off adds modem=0 wifi=0. No new GPU library involved.

First all-run log download hit HTTP2 CANCEL before kernel/image creation;
wifi-build-kit.py now downloads the build-job log directly, retries and supports
exact-run --resume. Retry succeeded; build.log, run.json, kernel/SHA256SUMS,
kernel and images are saved. kit-retry-result.txt has packaging output.
Watch session10500 ended on that transient download error; retry77040 completed0.
No remaining background task/collector from this preparation.

Device acceptance NOT RUN. Ready runbook jasmine/WIFI-INTEGRATION.md includes
default boot/auto-join/internet+USB, production-matched GL7/7 control, AP-loss
and wrong-password recovery, two joined reboots and off fallback. Fresh shared
availability and charging-shell capacity>=30% before using phone; original12%
net-discharge observation was never rechecked here. No phone command, lock,
boot, installation, partition write or device result in this task.
After device acceptance, direct merge into jasmine is sufficient (draft PR1
optional). Slot-b flashing still requires explicit confirmation. Production
library14e32aea... and all device partitions/backups remain untouched.
Active isolated checkout/branch codex/wifi-integration-build; published canonical
branch origin/codex/wifi-integration. Final changes after8405096 are docs and
host downloader resilience, not kernel source/workflow changes.

### 2026-10-26: Wi-Fi cold Intel build progressing; production GL control staged

CI40358833912 /8405096 remains in Build. Live job log is downloadable with
gh api --allow-escape-sequences repos/telegdyd/ios-jasmine/actions/jobs/121698472232/logs;
save to file and strip ANSI before reading. At16:40UTC snapshot:632 compile
command lines, all17 legacy IIG definitions replayed (twice for export/build),
only4 expected upstream blacktop patch skips, no compiler error observed in
that snapshot. New SDK/compiler causes cold rebuild; completion still pending.
Own ignored watch-and-package.ps1 waits for success, then runs wifi-build-kit.py
with exact84050968075304307e93f16baeb7f507725e8d70 and original j99 baseline.
Its exec session10500 is active; output original research/wifi-integration/
kit-result.txt, expected kit directory ci-40358833912/. If CI fails, it saves
intel-failure.log and packages nothing. No retry/phone action in that script.

Prepared production-matched seven-step GL control from successful Mesa
CI40170072509 /a9e95ec8795969f7c227b4a56074ac5940ecd9df. Downloaded ignored
research/wifi-integration/production-gl-control/. Companion library SHA
14e32aea4121e9c8a357da8f5e6322fe572a85f1c22e496990af0e687cb19261 matches
production; plain-arm64 test SHA5bcc71b6613738fd379968a87964e15f8208af8e6fb4a7d4546239aaaaf5e6bc,
no Task24 barrier marker. control.json records provenance. Later install only
test-name binary, verify readback, bound20s, require7/7+exit0, remove test;
never replace production library. Runbook updated. No new device test/result.
Phone untouched throughout; availability/battery need fresh checks when home.

### 2026-10-26: Wi-Fi combined build now running on Intel; phone untouched

8405096 pushed to codex/wifi-integration; CI40358833912 accepted macos-15-intel
immediately and is in progress (setup/checkout/fetch passed, dependencies next).
Prior ARM40357619511 cancelled queued; no kernel produced. Current run includes
all47 integrated patches, quiet/default-on/fallback behavior, pinned legacy IIG
and strict skip/source/symbol checks. Source after8405096 is docs only.
Images still pending successful CI. No phone command/lock/boot/install/flash.
Direct merge supported after build/device acceptance; draft PR optional.

### 2026-10-26: Wi-Fi offline preparation continues on supported Intel runner

Supported macos15 ARM run40357619511 also remained queued without a runner;
cancellation requested to try the documented macos-15-intel pool. No build or
new device result from it. Kernel and pinned IIG outputs unchanged. Local IIG
replay matches both IOUserClient outputs byte-for-byte; modified definition
negative control rejects. Added download-time verification of CI SHA256SUMS.
Latest jasmine README/handoff e4ac03c merged as7b608e6; both handoffs preserved,
only docs changed since compiled-source candidate c83b9e3. PR is optional: user
asked why it exists; explained it is a review aid, not a merge requirement.
Direct branch merge after successful build/device acceptance remains valid.
No phone access/lock/boot/write. Next: commit/dispatch Intel runner, verify and
package artifacts if available; runbook/tools ready even if runner stays queued.

### 2026-10-26: README refreshed on jasmine for publication

User explicitly requested the approved README update on jasmine and origin.
Original review/update commits 4448775 and 9fc68dc were mistakenly left local
on codex/wifi-integration. Applied only the README to jasmine, without merging
Wi-Fi code or unrelated integration handoffs. Wi-Fi guides are linked to the
published integration branch because those files are not yet present on jasmine.
README now covers accelerated CA/Mesa, MDP scaling, optional 4K/eight-core builds,
four-Gold default, GPU 588/DDR 1804, tested versus pending Wi-Fi results, charging
and graphics limitations, build/library injection steps and current roadmap.
Checked local link targets, balanced code fences and git diff whitespace.
Documentation only: no CI/build, phone access, boot, install or partition write.
Task24/charging work below unchanged. Publish this documentation commit to
origin/jasmine and verify its remote SHA. Commit subject:
docs: refresh README with current GPU Wi-Fi and build status.

### 2026-10-26: Wi-Fi runner migration prepared; isolated build checkout

User requested all preparation possible without the phone. Draft integration
PR1 https://github.com/telegdyd/ios-jasmine/pull/1 is attached. Shared checkout
was switched to jasmine by another active chat; continuation moved to managed
worktree C:/Users/teleg/.codex/worktrees/wifi-integration-build/ios-jasmine,
branch codex/wifi-integration-build, based on published integration8768726.
Captured own workflow edits were removed from shared jasmine unchanged; no
other agent's work was reset. Original ignored evidence remains under
C:/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine/research/wifi-integration/.

GitHub macos14 retirement notice lists active brownout Oct26 14:00UTC through
Oct27 00:00UTC, retirement Nov2. Runs40353134781 and40354341764 cancelled while
queued; neither compiled. Prepared kernel job migration to supported macos15.
Preserve xnu8796 RPC ABI: tools/xnu-legacy-iig.py replays exact Xcode15 generated
header/implementation pairs from successful Wi-Fi CI40159794543 /37f54b1.
Pinned manifest08a1ba9244a14654a2b12ccaeecf470b26e94b20396931590fda2e62e0aad0ee:
1922 source header/definition hashes,34 output hashes. Private SweetSurface.h
(not an IIG input) and2 independent SDK TargetConditionals copies excluded.
Definition set/flags/output destinations strictly checked. No Apple generated
files in git; workflow refreshes verified seed as90-day artifact. Offline source
validation and exact IOUserClient replay PASS. Local reference source aligned
with3 existing blacktop header edits absent from WSL snapshot; CRLF normalized.
No kernel RPC-layout change. Supported-runner compile remains pending.

32 framebench tests and extracted intern concurrency/capacity check PASS;
3 provisioning tests, offline backup/idempotency fixture, ADT on/off and negative
skipped-patch/old-kernel checks pass. tools/g2/wifi-build-kit.py checks exact
successful CI head, downloads log/kernel and packages default/diagnostic/off.
Actual images await CI. No phone command/lock/boot/install/flash or new device
result. Charging observation inherited12% net discharge; fresh>=30% and shared
availability coordination before later device session. Next commit/build runner
repair, verify artifacts/package images, then update PR and handoff.

### 2026-10-26: t5tc-diag archived and retired

User approved the proposed archive-and-delete procedure. Annotated tag
archive/t5tc-diag-2026-10-25 pushed to origin and remote peeled commit verified
as d400e26b688ba97f86bd7eb66ce3fb3616f9ec91 before branch deletion.
Tag object f24c04068da7cd87a3759819c2cb47886a852f29 preserves diagnostic history;
annotation records production fix a9e95ec, diagnostic CI40169317271 (UI drawn,
GL7/7, dump never fired) and production CI40170072509. These are historical
results, not new tests. Deleted origin/t5tc-diag with expected-tip lease, then
local t5tc-diag. No worktree/files/artifacts removed; no device/build/CI action.
Six origin branches remain: jasmine, wifi, codex/wifi-integration,
codex/framebench-build, t16-build1, topaz (default). Five local branches remain
(same except topaz). Earlier cleanup commits: bbd67e6 and correction39e1f7d.
Task24/charging handoff unchanged. Next optional cleanup: topaz requires changing
GitHub default first; active build branches require consolidation/validation.
Milestone commit subject: docs: record archived task 5 diagnostic branch.

### 2026-10-26: approved branch cleanup completed

User approved deletion only for branches with the plain Delete recommendation.
Deleted origin branches jasmine-prof, jasmine-sched, t14-census, j0058-display,
j0064-ddr and main in one atomic push, each guarded by its audited tip lease.
Deleted the five corresponding local branches (no local main existed).
Profiler/scheduler worktrees preserved at their existing commits as detached
HEADs d7e7047/8620435; no directory or ignored artifact removed.
Prior audit committed as 67fdae4. Final live check found seven origin branches:
jasmine, wifi, codex/framebench-build, t16-build1, t5tc-diag, topaz (still
default), plus codex/wifi-integration newly published at 341b28f during this
cleanup by concurrent work. Remaining six local branches: same except topaz.
Topaz requires default change before retirement; t5tc-diag requires archive
preservation first; neither was approved for this deletion and both retained.
Current integration worktree already had four unrelated tracked modifications
(.github/workflows/xnu.yml, tools/g2/mkimg.sh, tools/mkadt.py, j0099 patch);
left untouched and excluded from this documentation commit; concurrent commit
341b28f had committed them by final verification. This cleanup ran no CI/build/
boot/device action. Task24/charging handoff below unchanged.
Milestone commit subject: docs: record approved branch deletions.

### 2026-10-26: branch cleanup audit (recommendations only)

Fetched all three remotes; GitHub origin has 12 branches, local has 11.
GitHub default remains topaz; gh pr list --state all returned no PRs.
Audit HEAD codex/wifi-integration 6a88ed5; jasmine/origin d34f5ca.
No branches/tags/worktrees deleted, no push/default-branch change, no device
access/build/boot/CI run. Existing Task24/charging handoff below unchanged.

Cleanup candidates (local and origin where present):
- jasmine-prof: local d7e7047 is ancestor of jasmine; remote a0c952b is
  patch-equivalent to a commit in jasmine (git cherry reports minus).
- jasmine-sched: local 8620435 is ancestor; remote ed43ab3 has two unique
  commits, but its entire changed patch matches jasmine's code, with only
  patch header/commit-message differences. No missing scheduler code found.
- t14-census 55b791b: ancestor of jasmine.
- j0064-ddr 23617b1: three unique commits, but only changed file is byte-for-byte
  identical to jasmine's j0064 patch.
- j0058-display 48d3dd3: four unique commits, but only changed file differs
  from jasmine's j0058 patch in embedded commit hash/file-mode metadata only.
- origin/main 347e190 and origin/topaz e3d156a: ancestors of jasmine;
  change GitHub default before deleting topaz. These are origin refs only;
  do not delete branches in the separate upstream sweet/topaz repositories.
- t5tc-diag d400e26: three unique temporary diagnostic commits, not merged;
  0004 matches current jasmine exactly, unique 0005 is batch-cache diagnostics.
  Recommend preserve tip in an archive tag before retiring this branch.

Keep jasmine; wifi daf1e6d (67 commits outside jasmine); current local-only
codex/wifi-integration (merge includes all jasmine and wifi); framebench-build
7ee9cb8 and t16-build1 18d59f1. Against integration, framebench has six unique
commits and t16 has five; neither tip contains the other. Consolidate/validate
before retiring these. Integration tip is not on origin; preserve before removal.
Five other registered worktrees inspected read-only: no tracked changes or
non-ignored untracked files. Ignored build artifacts were not inventoried;
branch cleanup is not authorization to delete their worktree directories.
Next if user requests cleanup: recheck tips, preserve diagnostic tip, retire
reviewed branches and handle occupied worktrees without losing ignored artifacts.
Milestone commit subject: docs: record branch cleanup audit and preservation needs.

### 2026-10-26: Wi-Fi offline test kit ready; CI guard corrected before build

Integration implementation341b28f pushed to codex/wifi-integration. First CI
40353134781 remained queued (no build steps); cancellation requested to include
correct C++-mangled pin/unpin names in the symbol guard, checked against the
prior j99 kernel symbol table. Replacement combined CI still pending.
Prepared tools/g2/wifi-images.py (default/diagnostic/off, baseline j99 shim+ADT,
plain-arm64/symbol/roundtrip/hash checks), tools/wifi-check-log.py (offline
evidence gate), jasmine/WIFI-INTEGRATION.md (bounded acceptance/recovery/merge
runbook), and --wifi opt-in in sweet-root-tweaks.py. Prior j99 boot/reboot logs
pass analyzer; missing-evidence/off-with-radio negative controls reject.
Generated default/off ADTs verify wlan present/absent;3 configd tests pass.
Images need successful combined kernel before packaging; no device test claim.
No phone commands/lock/boot/install/flash. Charging observation inherited only.

### 2026-10-26: Wi-Fi integration prepared offline; combined CI pending

User requested all preparation possible without phone access. Working branch
codex/wifi-integration merges jasmine d34f5ca and wifi daf1e6d (merge6a88ed5).
Found real patch-stack conflict despite clean Git merge: Wi-Fi j0099's
SweetGPU::free context collided with framebench accounting. Trimmed only the
conflicting trailing context; both behaviors preserved. All47 j0080..j0100
patches replay successfully in CI filename order on an isolated source base
(~/xnu-wifi 544ee9f^); evidence research/wifi-integration/patch-application.log.
No shared WSL source modified. Local Apple clang unavailable; CI compilation
still required. Source integration markers pass.

New j0100 defaults Wi-Fi/modem on for jasmine with validated45s startup delay;
wifi=0 disables radio/default DSP start, modem=0 explicitly disables DSP.
wifi_diag=1 opts into QRTR/packet/SMMU step diagnostics. State/fault/reboot
logs remain. mkadt defaults WLAN node on; --no-wlan is the fallback. mkimg
omits it for explicit wifi=0/modem=0 and now propagates shim build failure.
Offline tools/wifi-root-config.py seeds configd en0 on fresh mounted roots,
preserving existing services/configuration;3 provisioning tests pass.
CI now rejects skipped repository patches and verifies combined source/symbols.
Build/images/PR/device checklist still pending this milestone.
No phone command, lock, boot, install, partition write or new device result.
Latest charging observation remains prior12% net discharge; do not boot until
fresh capacity>=30% and coordinated phone availability. Nothing flashed.

### 2026-10-26 02:13: replug check shows net battery discharge

User replugged and requested another measurement. Three read-only samples at
02:13:39/45/51: capacity12%, battery current -85449/-107910/-83496uA,
voltage3702383/3701650/3710195uV,temp340. Charger online1/statusCharging,
healthGood, usb_type selectsSDP, current_max500000uA,float4050000; backlight0.
Battery current is negative despite Charging label: net discharge at those
samples. Reported500mA current_max is a charger/USB policy reading, not measured
input current or proof of physical supply capacity. Charger current_now still
No data available and voltage_now times out. No settings changed, no boot/test.
Own shared lock released. Ignored evidence research/t24/charge-replug-20261026-021339/.
Task24 GPU session remains deferred; charging problem now needs diagnosis before
further iOS runs. Do not assume r109 statusCharging proves net energy gain.

### 2026-10-26 02:12: requested charging recheck

Three read-only charging-shell samples5s apart: capacity13% all three,
Charging/online1; battery current +36621,+27832,+28808uA, voltage3720937,
3720205,3719961uV, temperature340 (34C). Backlight0/float4050000 unchanged.
Positive reported battery current is only28-37mA; this10s check does not establish
a rising capacity trend. No settings/boot/install/test changed. Own shared lock
released. Ignored evidence research/t24/charge-recheck-20261026-021215/.
Task24 diagnostic still deferred below30%; paired artifacts ready and session
approval recorded in handoff below. No automatic follow-up scheduled.

### 2026-10-26: task24 diagnostic session approved but deferred at13% battery

User approved phone-free paired baseline diagnostic session. Acquired own shared
lock;02:10:02 Budapest charging shell reports capacity13%, Charging,+41503uA,
3718984uV, chargeronline1, backlight0,float4050000. Below agreed30% pre-boot
threshold: no iOS boot, install, diagnostic process or collector ran. Phone left
in existing charging shell; own lock released. Evidence ignored under
research/t24/diagnostic-session/{charging-before.txt,state.json,lock-released.txt}.
Capacity fell from prior16%; this single check does not establish a cause or
reliable charge-rate estimate. No charger setting changed.
Paired artifacts/source339bb02 / Mesa CI40252267715 PASS remain ready; details
jasmine/PERF-TASK24-PIXEL-GATE.md. Existing baseline pixel failure unresolved,
retained path untested/defaultoff, no gain. User's phone-session approval is
recorded; next check shared availability and capacity>=30 before that unused
bounded session. No automatic follow-up scheduled; do not boot low battery.

### 2026-10-26: task24 paired baseline diagnostics built; phone coordination pending

Implementation339bb02 pushed. Mesa CI40252267715 PASS3m22s including reverse0008
control rebuild/sign. Signed tests SHA087c5668... (normal),1ed0608b... (pre0008);
Mach-O, diagnostic strings, retained marker present/absent and exported hashes
verified. Artifacts ignored research/t24/diagnostic-ios/; diagnostic-ci.json,
diagnostic-artifacts.json and diagnostic-build.log preserve exact evidence.
Report jasmine/PERF-TASK24-PIXEL-GATE.md has commands/28-check controls and scope.
Local syntax check passes; original acceptance body verified unchanged.
No driver fix or new GPU result, no gain. Phone untouched this turn; last verified
r109 charging16%, own lock released. Fresh coordination requested for 4processes:
normal/pre0008 x TC on/off, --feedback-diagnostics forces barrierOFF. Gate iOS
boot on charging-shell capacity>=30%; lower battery means defer/leave charging.
Expected pixel failures are diagnostic data, but timeout/missing checks/nonzero
GLerror/newGPUfault abort. Test-name only, verify production/remove files/restore
charging. Prior matrix's first disabled baseline failed; retained path untested.
Standing Task24 push/CI approval. Task24 open; defaults unchanged.

### 2026-10-26: task24 baseline diagnostic controls prepared offline

See jasmine/PERF-TASK24-PIXEL-GATE.md diagnostic section. Added explicit
--feedback-diagnostics mode, forced barrierOFF/sysmem/nofp16, preserving the
original acceptance sequence.28 checks compare imported vs GL allocation,
clear/draw/feedback stages, finish-before/after-clear and solid-clear controls,
same-name vs imported-name revisit and pre-alias readback checkpoint. Reports
all failures; no lowered expectations. Existing seven steps retained.
Optional Mesa CI input mesa_task24_controls builds/signs an otherwise identical
test with patch0008 removed, plus hashes/source provenance, after saving normal
signed outputs. This isolates0008, not installed production revision.
Regenerated0001; all8patches apply, reverse0008 check passes; GCC include syntax
with real GL/sweetgl declarations passes. iOS CI pending. No driver fix/gain.
Phone untouched this turn; inherits verified r109 charging shell16% from prior
session, own lock released. No automatic device repeat; coordinate once paired
artifacts ready. Standing Task24 push/CI approval. Next commit/build controls,
verify signed artifacts, then bounded diagnostic TC on/off per source variant.

### 2026-10-26: task 24 GPU gate stopped on disabled-baseline pixel failure

Report/next diagnostic: jasmine/PERF-TASK24-PIXEL-GATE.md. Source8b6f7e0,
Mesa CI40250210168 PASS; one approved bounded session. User supplied charging
shell; existing slot-b iOS boot01:49:11 (no flash). Test-name binary readback
matches CI68fcde5c... First --sysbarrier-off/TC-default case exit1,8steps97.9ms:
existing7steps pass; repeated feedback passes, clear/scissor4096/4096 wrong,
target revisit/imported alias112/4096 wrong, other target preserved. Matrix
stopped before any enabled case; retained path untested. No benchmark/gain.
No nonzero GL error or new runtime GPU/SMMU fault/panic observed; known startup
self-testFSR0x400 persists. Do not infer installed production reproduces failure:
the test embeds candidate Mesa, and baseline failure root cause is unresolved.
Raw case SHA0a2750c5..., evidence ignored research/t24/barrier-session/.
Own test removed, before/after production14e32aea... identical, collectors exited.
Temporary r109 parking boot succeeded, activeb verified;01:54:12 online1/Charging,
qcom-battery +162597uA/3701650uV/16%, backlight0/float4050000. Charger current/
voltage sysfs reads errored; quoted values are battery reads. Own lock released.
Next offline diagnostic design isolates clear-only/draw-clear/feedback-clear,
target contents before alias and explicit-completion controls; preserve original
acceptance sequence. Compare pre0008/disabled candidate and TC modes in a fresh
coordinated phone session before root-cause fix or four-case repeat. Candidate
default off, production unchanged, Task24 open. Standing Task24 push/CI approval.

### 2026-10-26: task 24 candidate CI passed; awaiting GPU correctness session

Candidate8b6f7e0, Mesa CI40250210168 PASS. Design/gate:
jasmine/PERF-TASK24-CANDIDATE.md. Signed library SHA2564b7eb493...;
signed GPU-test SHA25668fcde5c...; exact artifacts/provenance under ignored
research/t24/barrier-ios/, barrier-ci.json, barrier-artifact.json.
Both are compile/sign results only: no GPU correctness or gain established.
Default off SWEETCA_SYS_BARRIER; production still ordinary14e32aea... library,
slot-b j70/pipeline0/GPU588/DDR1804. Phone restored after the sole diagnostic,
all own test files removed; no phone lock held. No candidate installed/booted.
Fresh phone-free approval requested for on/off x TC on/off GPU pixel matrix.
Prepared runner research/t24/barrier-test.py (not yet run) installs only a new
test-name GL binary, no CA library replacement or planned reboot. Positive
cases must show retained-path marker and all eight steps PASS. Stop on any
failure/hang/fault and recover before benchmarking. User has standing Task24
push/CI approval. Next: after phone-free reply, run the bounded matrix; only
after it passes coordinate matched performance captures. Task24 remains open,
GMEM not enabled by default and no speed claim. Parser report distinguishes
zero-draw batches from zero-work; some captured mask tails remain incomplete.

### 2026-10-26: task 24 default-off sysmem barrier candidate prepared

Concrete design/test gate: jasmine/PERF-TASK24-CANDIDATE.md. New patch0008,
SWEETCA_SYS_BARRIER=1 only with forcedsysmem. Retains small1-5 draw linear8-bit
color-only batches; rejects clears/prologues, depth/MSAA, queries/streamout,
other pending batches and large islands. Existing a5xx CCU publish/completion/
invalidate + UCHE sequence; hardware correctness not yet proved. Durable
bypass veto and split-before-later-clear added. Dependencies/fences/kicks and
production defaults preserved. Real GPU pixel-reference tests added for repeated
feedback, clear/scissor, pending-target switches/revisits and imported aliases;
on/off x TC on/off matrix required, with retained-path marker in on cases.
All eight patches apply. Twelve GCC source checks (host/Apple guards) pass
without warnings; controller tests and six parser tests pass. iOS CI next.
No new device access since diagnostic cleanup; phone remains ordinary production
iOS, no lock held. No candidate installed/tested, no gain claimed, GMEM default
unchanged. User has standing Task24 push/CI approval; next phone use needs fresh
coordination for the concrete correctness matrix, before any speed benchmark.

### 2026-10-26: task 24 first batch graph collected; ordinary phone restored

Report: jasmine/PERF-TASK24-DEVICE-AUDIT.md. Source ccd9a88 + ad9d787;
Mesa CI40247556888 PASS. 20960 consecutive event prefixes;40 complete CA-flush
intervals,3970 draws/1575 sysmem batches. Barrier616/resource-read646 endings;
121 actual periodic-kick flush calls ended186 batches. Preserve real dependencies.
Main-target667 batches;84 have6-13 draws and no observed bound alias or clear.
Some large alias-free islands end at barriers: blanket retention can destroy
GMEM opportunities. Bound views/scissor unions are conservative, not active
sampling/actual shaded area. Diagnostic timings are not speed results.
Console fragments/concatenates long records and damages some tail fields.
Host parser repaired/tested (6 tests); all IDs and interior draw sequences pass.
Counts/alias fields survive; exact restore/resolve mask completeness is unproven.
Trace raw SHA2560dac2345...; ignored evidence/scripts under research/t24.
One authorized temporary boot01:10:53, pipeline0/GPU588/DDR1804, no partition flash.
Precheck zero on-CPU samples for named sync tasks, zero drops. No new runtime
GPU/SMMU fault/panic; startup FSR0x400 matches production. GL test7/7 PASS.
Ordinary slot-b boot restored01:17:54; production injection/DDR1804 verified,
lock-screen screenshot checked. Production before/after SHA25614e32aea... identical.
Own test files removed; own collectors ended, profiler idle, own lock released.
Phone in ordinary production iOS. No additional device round scheduled.
Next: default-off narrow sysmem barrier candidate plus GPU pixel-reference tests,
preserving large islands and global drain when other batches are pending; improve
future trace framing. No optimization/default GMEM change or gain claimed.
User granted standing approval for Task24 pushes/CI; further device validation
must be concrete and separately coordinated. Task24 remains open.

### 2026-10-26: task 24 diagnostic CI passed; authorized session starting

Repair ad9d787; Mesa CI40247556888 PASSED. First run40247120431 failed only
the missing assert_dt annotation. User granted standing Task24 push/CI approval
and confirmed phone free for one bounded diagnostic. Own phone lock remains
held; owner in ignored research/t24/lock-owner.txt. Test-name library installed
at /usr/local/bin/libsweetca-t24graph.dylib; exact installed readback SHA256
0a8d5fac5e28f6a92798bc176d6a373367f2fc67d99dcf44a10ffba4076e102f.
New GL test 7/7 PASS, active-sampler subchecks included, 104.8ms, exit0.
Production library14e32aea... untouched; exact backup research/t24/production-before.dylib.
Temporary image shim/out/shim-boot-t24graph.img SHA2568d1b50d5... preserves
j70 slot-b kernel/ADT, pipeline0/GPU588/DDR1804. Trace300s delay/40s/30000 events.
Temporary boot succeeded at01:10:53 Budapest. Test library armed, EAGL context
created; Home swap-surface screenshot visually verified at01:12. Startup FSR0x400
matches production baseline; no new runtime fault observed so far.
Session script research/t24/session.py is running one bounded Home/CC/NC graph
after accessory-sync precheck. This is not a speed test. No rendering defaults
changed, no partition flash. Next: collect, analyze, remove own test files,
restore ordinary slot-b boot, verify production hash/UI and release own lock.

### 2026-10-26: task 24 diagnostic CI annotation repair; phone lock held

Implementation ccd9a88 pushed with explicit user approval. Mesa CI40247120431
failed at Clang thread-safety analysis: fd_bt_draw lacked assert_dt while reading
bound_shader_stages. Added the required driver-thread annotation; no suppression.
Eight GCC checks and controller tests still pass; iOS rebuild is next.
User confirmed phone free for one bounded trace. Own shared lock acquired;
owner saved in research/t24/lock-owner.txt. Do not remove another owner's lock.
Production exact backup research/t24/production-before.dylib SHA25614e32aea...
matches prior handoff. Live baseline GPU588/DDR1804 verified in preboot log.
Temporary image prepared from exact j70 slot-b payload; only cmdline/digest
changed, pipeline0; SHA2568d1b50d5... . No test library installed, no reboot/boot,
no device graph yet. Phone still ordinary production iOS; own collectors ended.
Next: commit annotation repair/rebuild, artifact checks, test-name install and
one authorized diagnostic session; restore ordinary boot and release own lock.

### 2026-10-26: task 24 source audit and bounded batch graph prepared

User approved starting the plan. Report: jasmine/PERF-TASK24-AUDIT.md.
Isolated Mesa26.2.5 f9ce5e81... plus all seven patches applies cleanly.
Full source confirms UCHE invalidate alone is not a color-cache flush;
clear/alias/dependency handling prevents a blanket barrier removal. Added
default-off SWEETCA_BATCH_TRACE with shared deadline/event cap, driver batch
events/dependencies/bound views and FIFO CA-flush markers. Parser batchgraph.py
excludes incomplete intervals and rejects gaps; aliases remain conservative.
Eight local driver syntax checks (host/Apple guards) have no warnings; real
trace-controller concurrency/window tests and five parser tests pass.
No barrier optimization or GMEM policy/default change. No gain claimed.
Next: commit/push and Mesa CI, then artifact verification and one bounded graph
session if phone-free confirmation arrives. No phone access/lock/boot/install,
new device capture or CI dispatch yet. Production state not freshly checked.
Reproduction/evidence under ignored research/t24; no shared Mesa tree edited.
Milestone subject: mesa: add bounded task 24 driver batch graph diagnostics.

### 2026-10-26: task 24 investigated; plan ready for review

Plan: jasmine/PERF-TASK24-PLAN.md. Saved gm1/gd2 summaries rechecked.
Active feedback barriers still flush; stale-binding filtering already exists.
Recommend safe in-batch sysmem barriers, then selective non-feedback GMEM.
Merged feedback batches remain sysmem; 15-20 ms Home GPU is unproven.
Full-source cache/clear/resolve audit and eligible-batch graph remain needed.
WSL reads returned Wsl/E_ACCESSDENIED; inspected saved task16 driver subset
and current tracked wrapper. No implementation, build, CI, phone access/lock,
boot, capture or installation; no new gain. Device state not freshly checked.
Next after review: isolated Mesa26.2.5 plus current patches audit and concrete
cache/clear/bypass design, then bounded graph instrumentation/narrow candidate.
Task24 open; no device round scheduled. Task23 closure remains unchanged.
Milestone subject: docs: investigate task 24 and propose staged GMEM plan.

### 2026-10-26: task 23 closed at user request

Task 23 moved from open performance work to closed investigations in
jasmine/PERF-TASKS.md; task definition, plan and audit status updated.
Observed Gaussian downsampling disproves the blanket missing-copy premise for
that path. No optimization delivered or speedup measured; this is not proof
that all blur rendering is optimal. Variable-blur approximation remains a
documented limitation with unmeasured runtime impact, not scheduled work.
User requested closure; earlier task-23 next-work guidance is superseded.
Evidence commit b58d1c5; diagnostic e4ece21 / Mesa CI 40240384093 PASS and
exact prior boot results remain in jasmine/PERF-TASK23-DEVICE-AUDIT.md.
Documentation-only closure: no new build, CI, phone access, boot or install.
Device state inherited from prior handoff (production iOS, own lock released),
not freshly checked. Commit subject: docs: close task 23 blur investigation.

### 2026-10-25: task 23 device investigation complete; Gaussian downsampling works

Report: jasmine/PERF-TASK23-DEVICE-AUDIT.md. One authorized diagnostic session,
not a speed benchmark. 2,042 contiguous pre-draw records, flush counts192-204,
33 programs,43 weighted draws, all FBOs complete. Observed separate level-0
Gaussian chains through 74x156 and72x42 intermediates, then larger targets.
Full-size four-tap passes coexist. Universal missing-copy/mip premise disproved
for observed Gaussian path; large reused allocation/viewport is not shaded area.
Native GLES variable-blur level support/shaders are missing; current injected
0x26/27 approximation confirmed in source. Metal attachment setLevel verified.
No variable replacement executed in trace: runtime cost/visual impact unproven.
No fix or gain claimed; task23 stays open. Next: source-level design for complete
variable-blur support and specific expensive Gaussian kernels/logical bounds,
not a blanket missing-downsample fix. No additional device round scheduled.
Diagnostic e4ece21, Mesa CI40240384093 PASS (3m00s), test library SHA256
c172abc13e5a7ae63a9b93aca9e1f8e1ac5f64475e8511d45264c01df0e6d9c7.
Temporary image540ff31a... booted23:34:45, ordinary slot-b kernel/ADT preserved,
pipeline0/GPU588/DDR1804. No partition flash. Arm-observation lag shortened usable
window; Home/CC/NC commands sent, repeat pair skipped at deadline. Accessory-sync
precheck no on-CPU samples for named tasks; do not infer complete UI coverage.
Evidence/scripts/hashes under ignored research/t23, raw trace SHA256
3d7662bfaa617fcca1b0773b04c5d9c1fce07528760b1059b9b42711393943f1.
No new runtime fault/panic; startup self-test FSR0x400 also in production baseline.
Production library14e32aea... never replaced; exact backup production-before.dylib.
Restored ordinary slot-b boot, production injection path and DDR1804 verified,
lock screen visually checked. Own test library/screenshot files removed. Profiler
idle, own collectors ended, shared phone lock released. Phone in production iOS.
This supersedes the active-session handoff below. Final report commit subject:
docs: record device proof of Gaussian blur downsampling.

### 2026-10-25 23:38 Budapest: task 23 diagnostic CI passed, session active

Diagnostic implementation e4ece21; Mesa CI 40240384093 PASSED (3m00s).
Artifact SHA256 c172abc13e5a7ae63a9b93aca9e1f8e1ac5f64475e8511d45264c01df0e6d9c7,
20,441,584 bytes; diagnostic strings and installed test-name readback verified.
User confirmed phone free. Shared lock acquired with task23-passgraph owner
recorded in ignored research/t23/lock-owner.txt; do not remove another owner.
Live starting baseline: slot-b j70 kernel, pipeline 0, DDR1804/GPU588; production
library hash 14e32aea4121e9c8a357da8f5e6322fe572a85f1c22e496990af0e687cb19261,
backed up at research/t23/production-before.dylib. Production file untouched.
Temporary fastboot boot at 23:34:45: shim-boot-t23trace.img SHA256
540ff31a9802fa2b18406390d0f57222d8fbf3ec39041e12123c4462a196023e.
Exact slot-b shim/ADT/kernel payload preserved, only cmdline/digest changed.
Test library /usr/local/bin/libsweetca-t23trace.dylib loaded; trace armed at
23:35:06 host observation, fixed 300s delay/25s/3000 draws. Home swap surface
visually verified; CARenderServerRenderDisplay returned known black result.
Session script research/t23/session.py is running; boot/log evidence and state
in research/t23/session.json, boot-trace.txt, boot-client.txt. Accessory-sync
precheck and bounded Home/CC/NC gestures pending. No algorithm change/gain claim.
Next: finish this single session, analyze complete interior pass chains, remove
own screenshot files, restore ordinary boot state and release own lock.

### 2026-10-25: task 23 bounded diagnostic prepared

Native variable-blur level requests are honoured by Metal but GLES set_surface
attaches level 0; native GLSL entries 0x26/0x27 are NULL. Supplying shaders alone
cannot restore the shared path. See jasmine/PERF-TASK23-AUDIT.md follow-up.
Added opt-in SWEETCA_PASS_TRACE diagnostic (default off), bounded by time and
shared draw/event caps; actual FBO levels, bound texture levels, fragment sources
and import provenance. No rendering algorithm change, no glGetError/readpixels.
Usage/limits: jasmine/PERF-TASK23-TRACE.md. Host mocked-GL harness passes with
-Wall -Wextra -Werror; all Mesa patches apply in order from isolated checkout.
No local iOS compiler; actual Mesa CI build is next. User explicitly confirmed
phone free for one bounded diagnostic session; no phone access/lock yet.
No build artifact, device result or measured gain. Next: commit/push, Mesa CI,
then test-name library + temporary image, one bounded cross-UI blur trace.
Production library/root defaults remain unchanged; task 23 remains open.
Commit subject: mesa: add bounded shared blur pass diagnostics.

### 2026-10-25: task 23 initial offline blur audit complete

Findings: jasmine/PERF-TASK23-AUDIT.md. Gaussian has explicit 2x/4x separate-target
downsampling; GLES create_surface uses ordinary GL TexImage2D storage, separate
from IOSurface import. Universal missing-mip explanation is not established.
Variable blur's injected 0x26 shader deliberately discards intermediate draws;
0x27 uses centre +24 source samples. This is a confirmed approximation, not a
proven Gaussian defect or measured performance loss. Its level-0-only rationale
needs rechecking against ordinary GL temporary storage. Saved slowest-only
summaries cannot reconstruct the complete blur graph; smaller intermediates are
already observed. Corrected the causal claim in the GPU report/task guidance.
4,645 extracted instruction bytes match the existing cache; four GLES vtable
entries resolved and property-13 dispatch decoded. Ignored research/t23 contains
scripts, extracts and validation. No source implementation, build, CI, phone
lock/access, boot, new capture or installation; device state not rechecked.
Next: bounded complete-graph diagnostic design for Gaussian and variable blur,
linking shader semantics, storage provenance/levels, logical bounds and sampled
inputs; resolve variable GLES intermediate representation before replacing it.
Task 23 remains open, no gain claimed. User wants shared UI correctness and
performance, CC is only a benchmark. Commit subject:
docs: audit shared blur paths and correct missing-mip premise.

### 2026-10-25: task 23 scope corrected by user

Control Center is a benchmark, not the optimization boundary. Goal: higher
frame rates across the UI; fix confirmed incorrect blur handling everywhere
that uses the affected shared paths. Audit Gaussian and variable blur, including
existing sca_nop/sca_vblur workarounds. Preserve intended appearance; validate
Home/dock/folder, Notification Centre and available in-app cases alongside CC.
CC-only improvement is insufficient for completion; report gains by workload.
Updated task 23 definition and plan (jasmine/PERF-TASK23-PLAN.md).
Next remains offline path/evidence audit. No implementation, build, CI, device
access, boot or installation; no measured gain. Device state not rechecked.
This correction supersedes the earlier CC-specific interpretation. Commit
subject: docs: clarify task 23 targets shared UI blur paths.

### 2026-10-25: task 23 taken; pre-build plan presented

Task 23 scope and sequence: [plan](jasmine/PERF-TASK23-PLAN.md). Starting HEAD
`8bd08b9`, branch `jasmine`, tracked worktree clean before documentation.
Read current GPU report/task rules; older task-16 HOLD entries below are historical
and do not describe the later mode-2 GPU measurement rounds. Blur mip-chain
failure remains a hypothesis. Source observation: storage/mipmap/attachment
wrappers forward levels; TRACE=2 stops after 60 draws and may miss CC.
Next: offline saved-pass/source/QuartzCore audit, then a concrete bounded
capture design before building. User requested plan before build. No source
implementation, local build, CI dispatch, phone lock/access, boot, capture or
installation in this milestone; no measured gain. Device state not rechecked.
Plan/handoff commit uses subject `docs: plan task 23 Control Center blur work`.
Untracked local evidence preserved; task 23 remains open.

# iOS 16 on sweet (Redmi Note 10 Pro, SM7150) - working notes

### 2026-10-25 15:42 Budapest: task 16 G1 evaluated, HOLD

Report commit `ed56425`: [G1 decision](jasmine/PERF-TASK16-PLAN.md#g1-result-2026-10-25-hold).
G1(a) supported with S1 provenance/accessory-sync caveats: CC A flush drain +
GPU wait 19.16 ms/arrival (36.8%), Home A 29.37 ms (52.3%). G1(b) remains
unproven; no substantial pre-gate work or demonstrated third-target overlap.
Corrected two S2 branch errors against existing cache bytes: cooldown resets
only for page low flags ==2, input bit0 clear, arbitration case false; failed
wait clears available count only for input bit0 clear AND nonzero cooldown.
Input bit0 set preserves the already-counted free page. Do not reuse S2's old
opposite predicates. Repeated resets can prevent cooldown decay after four ticks.
9,916 byte checks, eight vtable checks, S1 assertions and 26 branch cases pass.
Ignored evidence: research/t16/g1-audit.py and g1-validation.json; existing S1/S2
outputs regenerated. Truth tables do not prove runtime reachability.
Next: S4 prepares a bounded availability/target diagnostic and concrete design
review; observe A scanning/B pending/C admitted with valid damage history before
passing G1. Generic FPS data cannot supply the missing CA flags/cooldown/Buffer
ownership. S6-S10 remain gated; S5 independently scoped. No kernel/Mesa change,
CI, build, phone access/lock, boot, capture or install; no gain measured. Device
state inherited from S0, not rechecked. Unrelated files preserved. This handoff
supersedes older next-step guidance; timestamps here use current UTC+1 Budapest.

### 2026-10-25 16:38 Budapest: task 16 S3 complete, offline only

Report commit `cbb477c`: [S3 lifecycle audit](jasmine/PERF-TASK16-PLAN.md#s3-result-2026-10-25-complete).
Audited clean S0 kernel `bfb61629...` and pristine Mesa 26.2.5 + patches 0001-0004;
51 source files inventoried; patch/source/provenance checks pass twice. Shared
Mesa modifications were not used as the final patched source. Full hold ledger,
state machine and invariants recorded. Required S4 work: durable dirty-target
identity, successful submission/error propagation, generation/connection ownership,
cancel/late-ready handling, physical latch retirement and fail-closed timeouts.
Current shown-write exception, ignored wait failures and legacy queue are not a
safe async protocol; task 14 freeze remains unresolved. G1 remains open on S2's
unobserved availability flags/cooldown; S1 provenance caveat unchanged. Next: S4
concrete design/test plan and user review before S6/S7; no implementation approved.
Ignored evidence: research/t16/s3-audit.py, s3-validation.json, s3-sites.txt,
s3-patch-apply.txt and s3-mesa* source subsets. No source implementation, CI run,
build, phone access, boot, capture or installation; no measured gain. Phone state
inherited from S0: temporary framebench99 iOS boot, no lock held; not rechecked.
This supersedes the S3-next handoff below; unrelated files preserved.

### 2026-10-25 15:27 Budapest: task 16 S2 complete, offline only

Report commit `8d72bb7`: [S2 result](jasmine/PERF-TASK16-PLAN.md#s2-result-2026-10-25-complete).
Existing 20H392 cache: AppleCLCD inherits a normal three-page ring, not a fixed
two-IOSurface allocation limit. Dynamic Buffer allocation can supply a third
surface, conditional on can_update_ policy (input flags, page flags, +0x364
cooldown); current-workload private state is unobserved. Main layer preparation
and render work follow the availability gate; no substantial pre-gate overlap
established. SwapWait uses stored SwapBegin IDs; SwapEnd has status but no
selector out-data. G1 remains open, neither failed nor implementation-approved.
Reproduction/evidence ignored under research/t16/s2-*: 9,916 selected instruction
encodings match cache bytes and eight relevant vtable slots pass. No phone access,
new capture, source implementation, CI, build, boot, install or measured speedup.
Phone state inherited from S0: temporary framebench99 iOS boot, no lock held;
not freshly checked. S1 provenance caveat remains. Next: S3 lifecycle audit,
then resolve conditional G1 feasibility with the user in S4 before S6/S7. This
supersedes the earlier S2-next handoff; no unrelated worktree files changed.

### 2026-10-25 15:14 Budapest: task 16 S1 complete, offline only

Report committed as `0ded7e7`: [S1 result](jasmine/PERF-TASK16-PLAN.md#s1-result-2026-10-25-complete).
Saved threaded2 capture: CC A display-thread flush drain + GPU-fence wait
19.16 ms/arrival (36.8% sampled occupancy); Home A 29.37 ms (52.3%). SwapEnd
itself averages ~19 us; driver surface-write protection remains measurable.
CPU data unavailable in CC B/Home B/Spotlight repeat by capture design. Corrected
CC flush drain from the old generic 700 ms to 670 ms; remaining queue waits are
outside the per-frame flush or unclassified. GPU completion bounds exclude three
Home jobs observed only after a sampling gap; their ~7 s bounds are not GPU times.
Capture uses fix+dump `bb543dc9...`; S0 verified installed final `14e32aea...`.
Source differs only by diagnostic 0005; final-binary performance equivalence is
inferred, not measured. Ignored script/results: `research/t16/budget.py`,
`budget.json`, `stacks.txt`; record/pair/CPU-summary consistency checks pass.
No phone access, new capture, source implementation, CI, build or boot in S1;
device state remains S0's temporary framebench99 iOS boot (not freshly checked).
G1(a) supported with the provenance caveat; G1 stays open pending S2. Next: S2
offline CoreAnimation swap-surface feasibility; S3/S4 unfinished. Do not infer
implementation approval or a measured speedup from the optimistic overlap bounds.

### 2026-10-25 07:48 task 5: threaded context fixed, measured, installed

Leak fix in patch 0004 (`a9e95ec`): a TC flush replacing a barrier-created fence no
longer leaks the batch. Fix+dump build booted at 07:35: home drawn, dump never fired,
GL test 7/7. Framebench `research/framebench/20261025-threaded2/` vs empty-trace
baseline: CC A 14.49->18.79 arrivals/s (+30%), CC B +4%, Home B 20.63->18.52 (-10%,
one sample), Spotlight repeat +14%; display-thread CPU per arrival in CC 61.9->22.9 ms.
Display thread now mostly waits in CA's per-frame glFinish (GPU fence, driver drain).
**Installed at 07:48:** final library from `jasmine` (Mesa CI `40170072509`, SHA256
`14e32aea…`) at `/usr/local/bin/libsweetca.dylib`; the running backboardd still has the
equivalent fix+dump build until the next boot. Rollback: `research/t5tc/libsweetca-before2.dylib`
(`cfa9fd9c…`). Phone in iOS (framebench99 image), lock released, not parked. Details:
[report](jasmine/PERF-TASK5-THREADED-20261025.md). Next: task 16 (no per-frame glFinish).

### 2026-10-25 07:10 task 5: threaded context for a5xx; first boot froze, old library restored

[Report, ranking and next steps](jasmine/PERF-TASK5-THREADED-20261025.md). Profile of
the CC display thread: Mesa 72% of its CPU, ~2/3 of that freedreno driver work that
a5xx runs inline (upstream enables u_threaded_context only on a6xx). Commit `c954a07`
(patch 0004 + sweetgl kick/priority on the driver thread), Mesa CI `40166420782`,
library `38c8f967…`; its GL test passed 7/7 on the phone. Boot at 06:51 with it froze
between Apple logo and lock screen (user confirmed): driver thread `gdrv0` spins in
`fd_batch_from_fb`/`alloc_batch_locked` (census `research/t5tc/prof-hang`), all 32
batch-cache slots held. **Production library `cfa9fd9c…` restored at ~06:58 and
verified by hash; a verification boot drew the UI again.** The `jasmine` branch still
contains 0004 — do not install a library built from it until the leak is fixed.
Diagnostic dump on branch `t5tc-diag` not built yet (two CI failures explained in the
report). Phone left booted in iOS (framebench99 image, old library), lock released,
not parked in r109.
**~07:30 cause found in source:** `fd_fence_destroy()` never drops `fence->batch`;
a TC flush replacing a batch's barrier-created fence leaks the batch. Fix written into
`mesa/patches/0004-…` (uncommitted, third hunk in `freedreno_context.c`). Next command
(not yet run, shell checker was down):
`bash research/t5tc/build-fixdiag.sh` — applies 0001-0004 + diag 0005 to pristine
Mesa, host-checks, pushes `t5tc-diag`, starts Mesa CI. Then one boot: UI drawn = fix
works; still frozen = read the `fdbc:` lines, restore `research/t5tc/libsweetca-before.dylib`.

### 2026-10-25 task-5 new Mesa benchmark complete: no meaningful frame-time gain

User explicitly authorized using the new build and one further benchmark. This
superseded the earlier no-new-round restriction for this single run only; no
further rounds started or scheduled. [Full comparison](jasmine/PERF-TASK5-EMPTY-TRACE-BENCH-20261025.md).
Installed `0624366` / Mesa CI `40163837008` library at production path, read back
SHA256 `cfa9fd9c56305ed82b63f9d21b0134faf8b3ad661cf4d0d34ef6bf2e5bc8c0ea`.
Old exact production backed up under ignored new session. New CI GL test passes
all seven steps, sampler and IOSurface checks included; Home visually verified.
Same j0099 framebench image/args and configured clocks; plugins retained. Setup
iOS boot transferred library, one restart loaded it, then one standard capture
at 145 s after measurement boot: activity 59.89 s / collection 66.36 s, exit 0,
6340 events / 38376 samples / 12830 stacks; zero drops. Raw ignored directory:
`research/framebench/20261025-empty-trace/`; baseline `20261025-first/capture/`.
Home B arrivals 20.34->20.63/s (+1.4%), combined CC 14.05->14.28 (+1.6%). Median
intervals did not improve; repeated Spotlight slowed (22.92->13.73 arrivals/s,
47.04->63.40 ms median). Single short before/after: no clear net win, no proven
reproducible regression; no statistical claim. Home A remains unverified (0 vs 1
arrival). New run started ~6 C hotter; other startup/background variance remains.
Targeted trace paths disappear from CC primary CPU sample: old context_process
65 samples/130 ms and flush 8/16 ms -> neither sampled. Total primary render CPU
3550->3526 ms over ~4 s, essentially unchanged; per observed swap 61.21->61.86 ms.
Removal of unnecessary jobs validated, meaningful overall speedup unproven. No
CPU-vs-RAM bandwidth conclusion; do not resurrect the obsolete DDR comparison.
New library retained installed. No partitions flashed or clock/plugin changes.
Own diagnostics removed. Final temporary r109 parking boot succeeded; backlight
readback 0, float4050000, charger online1/Charging, +711425 uA, 4121327 uV, 78%.
Own collectors exited/stopped; shared phone lock released. Task 5 remains open;
next work is source-backed remaining draw/state/batch cost, not more automatic
rounds. Existing unrelated edits preserved. Commit subject:
`perf: record new Mesa trace optimization benchmark results`.

### 2026-10-25 task-5 offline step complete: empty trace-worker jobs

Implemented one focused Mesa change; [evidence and correctness](jasmine/PERF-TASK5-EMPTY-TRACE-20261025.md).
Current Control Center A primary thread: 65 on-CPU samples / 130 estimated ms
in `u_trace_context_process` (60 kernel wakeup samples), eight / 16 ms in
`u_trace_flush`. Source confirms default disabled/empty traces still allocate
and queue a job per finalized batch. Patch 0003 skips only those calls; any
enabled tracing or recorded events retains legacy behavior. GPU commands,
barriers, batch boundaries and fence/resource lifetimes unchanged. No claimed
frame-time gain: these inclusive samples are an opportunity, not savings.
Host compilation of changed gmem and matching u_trace units passed; all three
patches apply in order and resulting tree matches isolated implementation.
Implementation `0624366` committed and pushed. Mesa CI `40163837008` PASSED for
that exact commit (mesa job 2m52s); build log confirms gmem patch application.
Downloaded `xnu/out-mesa-t5empty-trace/libsweetca.dylib`, 19,233,936 bytes, SHA256
`cfa9fd9c56305ed82b63f9d21b0134faf8b3ad661cf4d0d34ef6bf2e5bc8c0ea`.
Actual ARM64 disassembly verifies the context-enable check and no-events branch
around `u_trace_flush`. Logs/disassembly saved under ignored session research.
No phone access, clock/plugin changes, boot or new benchmark. Device validation
pending. Shared WSL source and unrelated edits in jasmine/GPU.md, jasmine/NOTES.md
and PERF-TASKS.md remain untouched/uncommitted (178 insertions / 38 deletions).
Offline step complete; no runtime speedup claimed. Do not start device work or a
new benchmark round without new user authorization. Task 5 overall remains open.
Final handoff commit subject: `docs: record Mesa empty-trace build validation`.

### 2026-10-25 final task-5 handoff: offline work; no new benchmark round

User requests a new session to begin task 5's remaining per-draw Mesa CPU work.
Wallpaper is outside scope. **No new benchmark round, loop, clock sweep or device
boot is authorized for this next step.** Start from saved current captures and
source inspection; identify one confirmed avoidable cost, implement a focused
change and validate offline/build it. Report hardware validation as pending.
The user rejected using the old low-GPU-clock/plugin-disabled DDR test to exclude
RAM bandwidth on today's configuration. Retract that inference: current CPU
samples include possible memory stalls; CPU vs RAM limitation is not conclusively
separated. Task 5 is the strongest supported engineering recommendation, not proof
that RAM bandwidth cannot matter. No new run or clock change was started after
the user's objection. Latest phone state remains parked r109, own lock released.
Fresh usable Control Center primary-thread estimates: 3550 ms on CPU in ~4 s,
2274 ms Mesa (~64% of its CPU), 916 ms CA, 65 ms sampled GPU-fence waits. Home A
had zero updates and is invalid. Existing raw capture and symbols are detailed
in `jasmine/PERF-FRAMEBENCH-20261025.md`; use `capture/`, not Wallpaper, for this
work. Installed active-sampler fix `8877ff1` / CI `40053566696` stays the baseline.
Current report/host commits `e84104c`, `e81eeae`; no additional kernel/phone work.
Preserve unrelated edits in jasmine/GPU.md, jasmine/NOTES.md, PERF-TASKS.md. Any
older instruction to run new rounds or prioritize Wallpaper is superseded here.

### 2026-10-25 user scope correction: frame time first

User explicitly excludes Wallpaper from the current scope. Goal: identify CPU vs
GPU vs RAM-speed limitation and the highest-payoff frame-time improvement. Task 5
is first for this goal; do not continue the Wallpaper investigation from the prior
handoff. Latest usable Control Center sample: primary display on CPU ~89% of its
4 s window, Mesa ~64% of that CPU; GPU fence waits ~65 ms. Home A invalid. DDR
1296->1804 previously gave no measurable UI gain (historical, not a fresh sweep).
Next: remaining per-draw state/program emission and batch setup/finalization CPU
cost after the already-installed active-sampler fix. No phone access in this turn.

### 2026-10-25 jasmine framebench first device session complete

User made phone available in fastboot. [Results/priorities](jasmine/PERF-FRAMEBENCH-20261025.md).
One temporary j0099 boot, standard capture 59.86 s / 66.28 s with export, separate
45 s Settings capture on the same boot / 49.33 s with export; both successful,
zero drops. Installed graphics library hash independently matched. Wallpaper
service crashes/restarts and rapid wired/surface growth observed; exhaustion/leak
and full-system freeze not proven. Prioritize task 20 stability diagnosis, then
5 renderer CPU, with 21 background-service diagnosis alongside. Home A had no
updates: invalid comparison. No physical frame-counter events: mapping is topaz-only.
Host validity/CPU reporting corrected; 28 offline tests pass; saved captures
reanalyzed without another boot. CI remains 40160680219, image hash in result.
No partitions flashed or plugins/clocks/installed libraries changed. Parked once
in r109 charging console per standing request: online/Charging, +658202 uA,
4171376 uV, 85%; backlight 0, float 4050000. Own screenshots removed, collector
stopped and lock released (see active jasmine handoff). Next: bounded gallery
capture with early trigger and exception/memorystatus evidence. Commit subject:
`perf: record first framebench run and correct attribution validity`.
Preserve existing unrelated working edits.

### 2026-10-25 jasmine framebench implementation

Active handoff and CI IDs: top of [jasmine/NOTES.md](jasmine/NOTES.md).
[Usage](jasmine/FRAMEBENCH.md). User reports plugin-enabled performance regression
and Settings/RAM freezes; old benchmark priorities are not a current baseline.
Runner, compact kernel capture/export, memory snapshots and manual Settings mode
implemented; 24 offline tests and the actual eight-thread interning test pass.
Preceding CI `40160211557` and final CI `40160680219` passed. Prepared and verified
`shim/out/shim-boot-framebench99.img` (exact j98 shim/ADT/args). Earlier success
`40158474717` skipped j0099 and is not instrumentation validation. No device access.
Tool/image ready for first device validation. **Wait for user to confirm the phone
is free before accessing it**; verify actual baseline then. No on-phone result yet.
Implementation `4210ec8`; final validation subject `perf: validate framebench capture
and prepare first device run`. Preserve existing unrelated working edits.

### 2026-10-25 jasmine one-shot performance benchmark plan

Plan requested by user: [jasmine/PERF-BENCH-PLAN.md](jasmine/PERF-BENCH-PLAN.md).
Active handoff: top of [jasmine/NOTES.md](jasmine/NOTES.md). One bounded capture on
an existing settled boot; runtime frame trace plus existing gestures/profiler,
compact export and ranked slow-frame evidence. Instrumentation needs one setup
build/temporary boot; the benchmark never boots/retries automatically. Planning
only: no implementation, CI/build/boot/device changes. Commit subject:
`docs: plan one-shot frame bottleneck benchmark`. Prior unrelated edits preserved.

### 2026-10-24 jasmine documentation handoff

Mi A2 performance work is tracked in [jasmine/NOTES.md](jasmine/NOTES.md) and
[jasmine/PERF-TASKS.md](jasmine/PERF-TASKS.md). Cleanup committed as `2c62869`.
User subsequently approved the benefit/effort ranking and new tasks 17-21, including
a separate diagnostics group. Documentation-only; no CI/build/boot/device changes.
This milestone's commit subject: `docs: rank performance work and add diagnostic tasks`.

### >>> UPDATE 2026-10-21: sweetd works over USB Ethernet <<<

The new command daemon/client groundwork is in place. `ios/sweetd.c`,
`tools/sweet-sh.py`, and `tools/sweet-launchd.py` are tracked. USB Ethernet is
live at `169.254.7.2`: log/file services (5140/5142) and command service
(5143) answer. The local `research/sweetd.token` exists; keep it secret.
The phone has `/usr/local/bin/sweetd` (70,512-byte arm64 Mach-O, mode 0755).
The first helper version added its dictionary to the unsecure cache but omitted
the plist file launchd imports. Creating the file under `/Library/LaunchDaemons`
still did not work: launchd logs showed imports only from
`/System/Library/LaunchDaemons`. The corrected `tools/sweet-launchd.py` now
writes the binary plist under `/System/Library/LaunchDaemons`, updates the
unsecure cache, removes any stale `/Library` entry/file, and cleans up its plist
on `remove`.

**Verified 2026-10-21:** booted `shim/out/shim-boot-j26-slotb.img` with `fastboot
boot` (no partitions flashed). Fresh kernel log contains `exec sweetd`. The
client command `tools/sweet-sh.py /bin/df` returned the phone's filesystem
usage, including `/dev/ufsroot0` mounted at `/`, with exit code 0. `/usr/bin/id`
is not present on this iOS root; `/bin/df` is the confirmed working example.
Use `tools/sweet-sh.py /absolute/path [args...]` for subsequent commands. The
local `research/sweetd.token` is required by the client; keep it secret and do
not regenerate it.

## Agent handoff / active work (2026-10-15, latest)

### >>> UPDATE 2026-10-18 (read first, then the 10-17 handoff below) <<<

**STATE at end of 2026-10-18 (evening):**
- On the phone: userdata = **image v15** (`/run/media/dipa/android/ios-sweet-ipsw/ios16-root-20H392-v15.img/.simg`; = v14 + `/private/var/preferences/SystemConfiguration/preferences.plist` with one network service "USB Ethernet": Interface DeviceName ue0 Type Ethernet, IPv4 Manual 192.168.7.2/24 router 192.168.7.1, DNS 1.1.1.1 8.8.8.8, set "Automatic" as CurrentSet). Fallback image v14 (v12/v13 deleted).
- Kernels: **0078** = all 8 cores (`cpus=8`, cpu6/7 = A76, homogeneous SMP; mkadt now emits 8 CPU nodes; ADT `shim/out/sweet-0078hi.adt`); **0079** = display off/on via IOMFB selector 12 kern_RequestPowerChange(state) (fade over 6 vsyncs, then black; verified: power button gives "SWEET FB: display off/on"); **0080** = `SWEET NET: <proc> route add/delete/change ...` and `... add/delete address ...` trace (built, `shim/out/shim-boot-0080s.img`, NOT booted yet).
- **Internet over USB: not working yet.** Host side is ready (temporary iptables: FORWARD accept for 192.168.7.0/24 + MASQUERADE, comment "ios-sweet"; lost on host reboot). With v15 the phone sent no DNS and no outbound traffic (only mDNS/ARP) -> configd probably did not apply the service (or did, without default route/DNS). Next: boot 0080s on v15, watch `SWEET NET` lines (does configd add 192.168.7.2 / default route on ue0?). If configd ignores ue0 (not an IOKit IONetworkInterface; configd 1241.140.6 source in `research/configd-1241`, SCNetworkInterface createInterface needs IONetworkInterface -> controller (IOMACAddress, SelfNamed) -> bus), add IOKit stand-ins and/or rename the ifnet to en*.
- Live log listener (`nc -ukl 5140`) may still be running, writing `logs/live-0078s.txt`.

**LIVE LOG over USB (0077, boot 0077s): no more recovery round-trips.** Boot an image with `sweetusb=2`, run `tools/sweet-usbnet.sh logs/live-NAME.txt` on the PC: it waits for the phone's CDC-ECM interface, sets 192.168.7.1/24 (sudo) and prints/saves the kernel console the phone streams every 100 ms as UDP to 192.168.7.1:5140 (starts with the last 64 KiB). `ping 192.168.7.2` checks the link. Current image: `shim/out/shim-boot-0077s.img` (kernel 0077, ADT sweet-0069hi, cpus=6, sweetfb_noconsole=1, sweetfb_hz=30, sweetusb=2). The recovery pull (`tools/sweet-log-pull.sh`) is still the way after a panic/hang before USB comes up.

**🎉 USB networking works (boot 0076s, 18:24 local): `ping 192.168.7.2` from the PC answers in ~1 ms, 0 % loss (200-packet burst, 1500-byte frames, 512/1024-byte frames).** 0075: CDC-ECM function (bulk 0x81/0x01, interrupt 0x82 NETWORK_CONNECTION; host MAC 02:00:5e:77:ee:01) + kernel ethernet ifnet `ue0` (legacy output, header strip like if_fake) with 192.168.7.2/24 set from the kernel (proto_plumb + SIOCAIFADDR on an in-kernel socket). 0076: received frames into one cluster mbuf (mbuf_allocpacket gave a first mbuf of length 0 -> panic "Failed mbuf validity check: len -14"). Host side (Linux cdc_ether, interface `enp0s20f0u3u1`): `nmcli dev set IF managed no; sudo ip addr add 192.168.7.1/24 dev IF; sudo ip link set IF up`. Boot image `shim/out/shim-boot-0076s.img` (`sweetusb=2`). iOS itself does not see ue0 yet (configd needs an IONetworkInterface in IOKit).

**USB device mode works (boot 0074s, 17:45 local): the host enumerates the phone at high speed as `1209:0001 ios-sweet "Sweet iOS (USB bring-up)"`.** 0072 read-only probe: ABL leaves the USB30_PRIM GDSC and all 7 USB clocks on, DWC3 v3.20a (GSNPSID 0x5533320a) in device mode (GCTL 0x00112000), halted (DCTL RUN_STOP 0, DSTS 0x00d3de04), event buffer still at ABL's 0xfdfc8000, QUSB2 PHY alive. 0073 (`sweetusb=2`): DCTL soft reset, own event buffer (polled, interrupt masked), ep0 DEPSTARTCFG/SETEPCONFIG/SETTRANSFRESOURCE, setup TRB, RUN_STOP; control-transfer state machine as Linux ep0.c; descriptors: vendor class, no data endpoints. It ran but no event came: **0074** forces the VBUS session in the Qualcomm wrapper (QSCRATCH 0xa6f8800: HS_PHY_CTRL |= UTMI_OTG_VBUS_VALID(20)|SW_SESSVLD_SEL(28), SS_PHY_CTRL |= LANE0_PWR_PRESENT(24), as Linux dwc3_qcom_vbus_override_enable) -> connect + enumeration. Image `shim/out/shim-boot-0074s.img`. Black Phone app: main thread waits in -[VMVoicemailManager fetchAccounts] (sync XPC; voicemail needs the modem).

**Navigation works (boot 0071s on v14, log `logs/boot-0071s.txt`):** swipe up from the bottom edge returns to the home screen; app switcher works. Two fixes: **0070** pid_hibernate (syscall 435 was nosys on the macOS config -> SIGSYS killed SpringBoard in -[SBToAppsWorkspaceTransaction _didComplete] when an app left the foreground; the only CONFIG_EMBEDDED-only entry in syscalls.master); **0071** touches starting within 48 px of an edge carry kIOHIDDigitizerEventFromEdgeTip (UIKit `_UIEventHIDTouchEdgeTypeForHIDEvent` reads the digitizer EventMask 0xb0007 bits 0x800/0x1000/0x2000/0x40000). Diagnosed, not fixed: Settings (Preferences) SIGTRAP in PodcastsUI func_1cdc47c58: force-unwrap of `URL.volumeTotalCapacity` (nil on our HFS+ root). Phone/Photos/Messages show black (MobilePhone launches, no crash) - next: stack samples via boot-arg `sweetsample=MobilePhone,MobileSlideShow,MobileSMS,SpringBoard` (image `shim/out/shim-boot-0071s.img`).

**🎉🎉 MILESTONE 2026-10-18 ~15:30 local: iOS 16.7 SPRINGBOARD HOME SCREEN ON THE PHONE** (boot `shim/out/shim-boot-0069s.img` = kernel 0069 + ADT `shim/out/sweet-0069hi.adt`, image **v14**; log `logs/boot-0069s-v14-HOMESCREEN.txt`). Home screen with a few apps, Settings opens, Control Center / lock screen / notification center work, touch + buttons work, 6 A55 cores (`cpus=6`), `sweetfb_noconsole=1 sweetfb_hz=30`. Known issue: cannot leave Settings (home gesture / AssistiveTouch home do nothing) - to investigate.
What it took today (in order): 0058 HID services (Apple IOHIDFamily-1915 user client), 0059 iPhone X identity (hw.product etc.), 0060 SPMI keys + GENI touch, 0061 1125x2436 presented display, 0062 RPMh L11C touch power + IOPMPowerSource battery, 0063 GENI FIFO packing (Goodix GT9896), 0064 PRIV_WORK_INTERVAL grant (SpringBoard "Failed to create work interval"), 0065 SMP via PSCI (6 A55), 0066 crash map regions, 0067 console mute without cons_ops write, 0068 IOSurface lookup of an already-mapped surface returns base -1 (backboardd snapshot crash), 0069 UFS log flush 10 s. Image v13: CommCenter removed from launchd.plist, BKNoWatchdogs. **Image v14** = v13 + Setup skipped (`/var/mobile/Library/Preferences/com.apple.purplebuddy.plist` SetupDone/SetupFinishedAllSteps true, SetupVersion 11, daemonizeNeedsToRun false; purplebuddy.notbackedup mini-buddy flags false; managedconfiguration.notbackedup LockdownActivationIndicatesCloudConfigurationAvailable false; springboard MCForceShowCloudConfigurationUI false) + mobileactivationd data ark seeded (`/private/var/containers/Data/System/D90C94C4-F94E-4FCF-8A28-A93BE3846D8E/Library/internal/data_ark.plist`, -ActivationState Activated etc.) + MediaToolbox D22/D221/Default SubServerConfiguration StartRecorderServer=false (mediaserverd crash loop: portrait-filter prewarm called NULL GL). **Activation:** ADT /chosen certificate-production-status 0, effective-production-status-ap 0, certificate-security-mode 1, effective-security-mode-sep 1 -> mobileactivationd's native Hactivation branch (Codex `codex/activation/report.md`; alternative 4-byte daemon patch documented there). Fallback image v13; v12 deleted.

**🎉 TOUCH WORKS (boot 0063u on image v13, 2026-10-18 ~13:15 local):** tapping (i) on Setup's Hello opens the device-info sheet; swipe-up is recognised (spinner, then back to Hello - under investigation). Chain: RPMh L11C vote (0062, `bsd/dev/sweet_rpmh.c`) -> GT9896 @0x5d on GENI SE7 (0063 fixed FIFO packing: register address went out byte-swapped) -> sweet_hid_touch -> SweetHIDTouch -> backboardd. Battery icon OK (0062 SweetBattery IOPMPowerSource, static 100 %). **Image v13** (= v12 + CommCenter jobs removed from launchd.plist + `BKNoWatchdogs`=true and `FBLaunchWatchdogExceptions{com.apple.purplebuddy:100}` in /var/mobile/Library/Preferences/com.apple.springboard.plist): Setup no longer killed by the scene-create watchdog (it blocked in CoreTelephony getSubscriptionInfo -> CommCenter, Codex `codex/setup/report.md`; that report also lists how to skip Setup: SetupDone/SetupFinishedAllSteps/SetupVersion=11 in com.apple.purplebuddy.plist + activation check). v9 deleted, fallback = v12. Input latency ~1 min with 1 CPU -> Codex task 11 = SMP via PSCI (`codex/smp/`).

**INPUT WORKS (boot 0060u on a freshly flashed v12, log `logs/boot-0060u.txt`):** power, volume up, volume down reach iOS (PMIC -> sweet_keys.c -> SweetHIDButtons -> backboardd). Power locks/unlocks (screen "off" shows the kernel console because the panel never really turns off). **Device identity fixed: iPhone X** (home indicator, Face-ID-style Setup). Earlier test (0059u, `sweethidtest=15` fake Home presses) advanced Setup from Hello to the language list.
- **0058** HID: `iokit/Kernel/arm/hid/`: IOHIDEventServiceUserClient + IOHIDEventServiceQueue + IOHIDEvent compiled UNCHANGED from Apple IOHIDFamily-1915.140.3 (= exact version of the iOS 16.7 IOHIDLib, clone in `research/iohid-1915`) over our minimal IOHIDEventService (SweetHID.cpp: SweetHIDButtons consumer page 0x0C power 0x30 / vol 0xE9/0xEA / menu 0x40; SweetHIDTouch digitizer collections). C hooks `sweet_hid_key(key, down)` (0 power, 1 vol+, 2 vol-, 3 home) and `sweet_hid_touch(finger, down, x, y)`. HID logs go to IOLog. Boot-arg `sweethidtest=N` = fake Home press every N s.
- **0059** identity: hw.machine/hw.model/hw.target/hw.product from the ADT (macOS-config kernel used to answer "iPad8,6"/"Redmi Note 10 Pro"). mkadt: root compatible `D22AP|iPhone10,3|xiaomi,sweet|...`, model iPhone10,3, target-type D22, `/product` copied from the real D22AP device tree (`research/ipsw-x/d22ap.adt`, extracted from the IPSW, NOT in git), `/buttons home-button-type 2`. Codex report `codex/mg/report.md`: MG ProductType = sysctl **hw.product** (unrecognized -> iPod), HWModelStr = hw.target, HomeButtonType = `/buttons/home-button-type`; disk cache `/private/var/containers/Shared/SystemGroup/systemgroup.com.apple.mobilegestaltcache/Library/Caches/com.apple.MobileGestalt.plist` (keyed by build + UUID only -> stale iPod answers survived; reflashed clean v12 to clear it).
- **0060** drivers by Codex (`codex/input/hw-report.md`): `bsd/dev/sweet_keys.c` (SPMI arbiter v5 observer reads, PON 0x810 bits KPDPWR/RESIN SID0, PM6150L GPIO2 SID4 0xc110; works), `bsd/dev/sweet_touch.c` (GENI SE7 I2C @0xa84000, starts 45 s after boot). Touch result: SE7 fw ok (proto 3) but **0x5d and 0x38 both time out -> touch IC unpowered** (L11C LDO needs an RPMh vote). Codex task 8 = RPMh client (`codex/rpmh/`), task 7 = battery (`codex/battery/`).
- **0061** (CI 39117078444): red status bar "rdar:45025538" = UIKit "No status bar visual provider for screen" (360x800 pt is no real iPhone). AppleCLCD now presents **1125x2436** (iPhone X) and shows the centered 1080x2400; touch mapped the same; ADT canvas 1125x2436. `sweetfb_native=1` reverts.
- Images: `shim/out/shim-boot-0060b.img` (0060 + /buttons ADT `sweet-0060hi.adt`). Next: 0061 image with ADT from current mkadt.

### >>> HANDOFF 2026-10-17 late (read this first) <<<

**STATE: iOS 16.7 Setup.app "Hello" screen is ON THE PHONE** (boot `shim/out/shim-boot-0057u.img` on image v12). Photo `/run/media/dipa/android/ios-sweet-work/MILESTONE-setup-hello-2026-10-17.jpg`. SpringBoard + backboardd + Setup run; nothing crashes in the GUI path. Remaining crash/relaunch loops: installcoordinationd (should be fixed by 0057, unverified), mediaserverd (VirtualAudio removed in v12, unverified), mobileactivationd (~100/boot, not analysed), bluetoothd + fairplayd.H2 relaunch constantly (no hardware).

**What is on the phone now:** userdata = image **v12** (`/run/media/dipa/android/ios-sweet-ipsw/ios16-root-20H392-v12.img` + `.simg` + `.sha256`; v9 kept as fallback, v8/v10/v11 deleted or superseded). Kernel **0057** (`xnu/out-0057`, CI `39067532732`). ADT **`shim/out/sweet-0057hi.adt`** (QEMU twin `research/q0057-hi.adt`). Boot image **`shim/out/shim-boot-0057u.img`**. Boot args: `debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress rd=ufsroot0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin ufsrw=1 rootrw=1 launchd_unsecure_cache=1 wdt=-1`.

**Build a phone image** (kernel K, ADT A): `python3 tools/mkpayload.py $K $A shim/out/payload-X.bin --cmdline "$B" && (cd shim && ./build.sh ../shim/out/payload-X.bin && cp out/shim-boot.img out/shim-boot-X.img)` then check `python3 tools/unpack_bootv2.py shim/out/shim-boot-X.img shim/out/check-X && cmp shim/out/check-X/ramdisk shim/out/payload-X.bin`. QEMU smoke test: `python3 tools/mkpayload.py $K research/q0057-hi.adt $S/csq/payloadX.bin --ramdisk $S/csq/root-fork.img --cmdline "debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress rd=md0"` + `PATH=~/swift/usr/bin:$PATH python3 tools/qemu-sweet.py ... --secs 40 --kernel $K --fail-on-panic` (S = scratchpad; root-fork.img lives in the session scratchpad csq/ dir and may be gone in a new session).

**Kernel workflow:** edit `research/bt28/xnu/...` (keep the pre-edit copy in `research/preNNNN/`), syntax check `python3 tools/xnu-cc.py research/run28.log research/bt28 <file>`, make `xnu/patches/NNNN-*.patch` with `diff -u pre bt28 | sed` path rewrite, add new/changed files to `research/check-patch-order.py` list, run it (must say applied + MATCH), commit + push -> GitHub Actions `xnu` builds (~8 min) -> `gh run download <id> -R dipa-studio/ios-sweet -n xnu-kernel -D xnu/out-NNNN`. **Repo is PUBLIC since 2026-10-17** (private macOS runner minutes ran out: "recent account payments have failed"); public = free runners. Commit trailer: only `Co-Authored-By: dipa-studio <183933817+dipa-studio@users.noreply.github.com>`.

**Phone workflow (user does buttons, Claude runs commands):**
- Boot test kernel: phone in fastboot -> `fastboot boot shim/out/shim-boot-X.img`. NEVER `fastboot getvar`.
- **Read logs WITHOUT filming:** after a test the user holds Power+VolDown -> fastboot -> `fastboot boot recovery/recovery.img` (OrangeFox, temp) -> wait for `adb shell true` -> `tools/sweet-log-pull.sh /run/media/dipa/android/ios-sweet-work/logs/<name>.txt` (reads the 4 MiB console ring the kernel keeps in the last 1025 blocks of userdata; patch 0047). Then `adb reboot bootloader` brings the phone back to fastboot without the user.
- **Flash a root image:** `fastboot flash -S 512M userdata <img>.simg` (7 min, 25 chunks). After a big flash the Xiaomi ABL fastboot hangs: next `fastboot boot` stalls at "Sending" -> the USER must re-enter fastboot by hand (Power+VolDown). Do not retry commands against the hung ABL. A flash right after `adb reboot bootloader` once failed on chunk 1 (USB protocol error): just retry. User must NOT unplug during flash (once interrupted at 25/25 -> reflash).
- **Edit the phone root without reflashing (same-length only):** find the file's raw offset in the local image (it is one extent; search the image for its first 4 KiB), compare with `adb exec-out dd if=/dev/block/sda34 ...`, then `adb push` changed 4 KiB blocks and `dd of=/dev/block/sda34 seek=... conv=notrunc,fsync`, read back. Recovery kernel has no hfsplus.
- **Pull the whole phone root** (12 min): `adb exec-out "dd if=/dev/block/sda34 bs=1048576 count=16384" > img`; mount ro with udisksctl or `sudo mount -t hfsplus -o loop,ro`. To write into a pulled image: `sudo fsck.hfsplus -fy` first (volume is never cleanly unmounted -> Linux mounts ro even with -o force), then `sudo mount -t hfsplus -o loop,force`.
- Making images: copy latest img with `cp --sparse=always`, mount rw with force, change, `sync; umount`, `sha256sum`, `img2simg`. Keep only the latest image + one fallback on the SSD (/home is ~98% full; big work files live in `/run/media/dipa/android/ios-sweet-work/`, old kernels/images archived in `.../ios-sweet-work/archive/`).

**Diagnostics built into the kernel (all SWEET-only):** persistent console log (0047, boot-arg sweetlog=0 off; flush every ~1 s); `|name| text` copies of /dev/null writes for processes in `sweetnull` (default backboardd,SpringBoard; 0048); `IOK name:` IOKit lookup/open trace for `sweetiolog` (default backboardd,SpringBoard; 0049/0054, 400 lines max); `SWEET Sandbox: proc op N` (0050); `STR ...` heap text dump on SIGABRT/SIGTRAP for `sweetscan` (default backboardd,SpringBoard; 0051/0053) - this is how NSException/BSAssert reasons were found; `SMP name tN pc .. bt ..` user stack sampler for `sweetsample` (default SpringBoard,backboardd; first at 90 s then every 120 s, 40 samples, 16 frames; 0054/0055); `SWEET FB: N swaps` every 1000 swaps; `CRASH name ...` crash reports (0043/0044). Symbolicate cache addresses with `ipsw dyld a2s research/dsc/dyld_shared_cache_arm64 <addr - slide>`; main-binary addresses: addr - mh + 0x100000000.

**Patches added today (0046-0057, all CI-built):** 0046 IOSurface (IOCoreSurfaceRoot) + IOMobileFramebuffer (AppleCLCD on /arm-io/disp0) + arm-io nubs; 0047 persistent log; 0048 /dev/null tee; 0049 IOKit trace; 0050 permissive "Sandbox" MAC policy; 0051/0053 heap text on crash; 0052 RENAME_SWAP via exchangedata on HFS; 0054/0055 sampler, swap counter, AKS selectors 35 (extended device state = 17) and 101; 0056 panel copy from the vsync timer at 10 Hz (sweetfb_hz) instead of every swap; 0057 no config_ext_resolver (ACL group entries resolve without memberd). ADT (tools/mkadt.py): /arm-io/disp0, /chosen/display-scale 3, /chosen/unique-chip-id (synthetic 0x5357454554000001) + chip-id 0x8015 -> IOPlatformUUID A9683613-3704-53F2-95D0-98A8FB574E78. Image v9-v12: /private/var/containers/{Bundle,Data/System,Shared/SystemGroup,Temp}; launchd.plist StandardOut/ErrorPath renamed to ...PatX (pointing jobs at /dev/console stops them launching: EACCES); v12: LastSystemVersion=20H392 in plain /var/mobile/Library/Preferences/com.apple.migration.plist (stops the 1-hour data migration that ran every boot), VirtualAudio.plugin moved to /Library/Audio/Plug-Ins/HAL.disabled/.

**Codex helper** (`codex exec --skip-git-repo-check -m gpt-6.1-sol -c model_reasoning_effort=high -s workspace-write -C /run/media/dipa/android/ios-sweet-work/codex -o OUT "$(cat task.md)" < /dev/null`, run detached with setsid nohup; config already defaults to gpt-6.1-sol high). Reports in `/run/media/dipa/android/ios-sweet-work/codex/`: mediaserverd-report.md, installcoordinationd-report.md (-> 0057), ufs-performance.md (ranked UFS speed plan), **ufs/0058-sweet-ufs-faster.patch** (READY, not yet applied: ufslogsecs default 10 s log flush batching, optional ufscache=1 directional cache ops, optional ufswait=1 spin-then-sleep; syntax-checked, host-stub verified; see ufs/README.md). Apply it as patch 0058 after review.

**Claude safety-classifier note:** several messages about QuartzCore renderer selection / writing an HFS reader tool were cut off by an automatic classifier (false positives, user agrees). Keep those topics short or let them be; they are not blockers now (rendering already works).

**NEXT STEPS (in order):**
1. **Input** (Setup stuck on Hello): touch + power + volume as IOHIDEventService/IOHIDDevice services backboardd matches (log shows backboardd matching IOHIDDevice with DeviceUsagePairs and IOService with HIDServiceSupport=true). Phone hardware: Goodix/Focaltech touch over I2C/SPI (check live DT `dtb/`), buttons via PMIC (pon) and GPIO keys. Start with a fake HID service (e.g. power button via a timer or boot-arg) to learn the ABI, then real drivers.
2. **Device identity**: MobileGestalt reports iPod + Home button. Add /product node / product-type (iPhone10,3, D22AP), device class iPhone, home-button-less (Face ID) properties in mkadt; find exact MG keys (MGIOMFBSupport.c, `IODeviceTree:/product` lookups seen in backboardd trace).
3. **Battery**: AppleSmartBattery/IOPMPowerSource style service (status bar shows empty red battery).
4. Apply Codex 0058 (UFS speed), consider cpus>1, check whether installcoordinationd/mediaserverd loops are gone, analyse mobileactivationd.
5. Hide kernel console over the GUI when not debugging: boot-arg sweetfb_noconsole=1 (but then panics are not on screen).

- **🎉 MILESTONE: iOS GUI ON THE PHONE - Setup.app "Hello" screen (2026-10-17 ~21:30 UTC, boot 0057u on image v12).** Photo: `/run/media/dipa/android/ios-sweet-work/MILESTONE-setup-hello-2026-10-17.jpg` (animated "dobar d(an)" hello lettering, status bar "iPod" + battery icon, bottom "Pritisnite Home za otvaranje" = "Press Home to open" (locale hr), (i) button). Rendered by iOS 16.7 SpringBoard/Setup through CoreAnimation -> backboardd -> kernel IOSurface (IOCoreSurfaceRoot) -> kernel AppleCLCD swaps -> ABL panel memory. What made it: data migration finally skipped (v12: `LastSystemVersion` 20H392 in the plain `/var/mobile/Library/Preferences/com.apple.migration.plist`; ADT `/chosen/unique-chip-id` + `chip-id` for IOPlatformUUID), 0057 (no ext resolver -> ACL containers work), plus everything before (0046 display/IOSurface, 0050 Sandbox policy, display-scale 3, containers dirs, RENAME_SWAP, AKS 35/101, 10 Hz present).
  **Missing (next work, in rough order):**
  - **Input: no touch, no power button, no volume buttons** (no HID drivers; backboardd looks for IOHIDDevice / HIDServiceSupport services). Setup is stuck on "Hello".
  - **Device identity: it thinks it is an iPod with a Home button** (status bar "iPod", "Press Home to open"): MobileGestalt has no product/model identity (no /product node, product-type, etc.) - give it iPhone10,3 / home-button-less (Face ID class) identity.
  - **No battery detection** (no battery/charger/PMIC service; status bar battery shows empty/red).
  - Locale came up Croatian (hr) - harmless.
  - Performance: cpus=1, polled UFS (Codex UFS patch in progress: `codex/ufs/`), backboardd presents at 60 Hz.
- **README refreshed (2026-10-17):** read the full notes and updated the public overview through patch 0045, v7 hardware observations and prepared v8 diagnostics. Documents real Apple userspace, the missing display/IOSurface GUI work, limited security services, highmem, persistent userdata root, current tooling and build examples. Documentation only; no kernel build, tests, flashing or phone boot performed.

- **v11 still migrated (boot 0056u, 20:32 UTC, `logs/boot-0056u-v11.txt`).** On iOS kCFPreferencesCurrentHost lands in the plain plist: all DMEnvironment setters (setLastBuildVersionPref, setUserDataDispositionPref, ...) use CurrentHost and the phone's `/var/mobile/Library/Preferences/com.apple.migration.plist` holds DMUserDataDisposition; datamigrator's XPC service runs with `_RoleAccount: mobile`. **Image v12** = v11 + `LastSystemVersion` = 20H392 added to that plain `com.apple.migration.plist` (keeps DMUserDataDisposition, 501:501 0600) + `/Library/Audio/Plug-Ins/HAL/VirtualAudio.plugin` moved to `/Library/Audio/Plug-Ins/HAL.disabled/` (Codex: stops the mediaserverd SIGSEGV loop; untested). **installcoordinationd loop explained (Codex `codex/installcoordinationd-report.md`):** os_crash "Failed to create data directory" EACCES for `/private/var/containers/Shared/SystemGroup/systemgroup.com.apple.installcoordinationd/Library/InstallCoordination`: `Library`/`Library/Caches` in the container are ACL-only (uid/gid 0xfffffffe, mode 0000, ACE for group GUID ...012B = gid 299 systemusers); with `config_ext_resolver` the kernel asks an identity resolver (memberd/opendirectoryd) that iOS does not run -> EWOULDBLOCK -> ACE skipped -> EACCES. **Patch 0057**: drop config_ext_resolver from FILESYS_BASE (compatibility UID/GID<->GUID mapping is used instead), likely fixes other ACL-protected containers too. Codex task 3: UFS driver performance design (`codex/ufs-performance.md`).
- **mediaserverd SIGSEGV loop explained (Codex report `/run/media/dipa/android/ios-sweet-work/codex/mediaserverd-report.md`):** the fault (FAR 0x390) is in the HAL plug-in `/Library/Audio/Plug-Ins/HAL/VirtualAudio.plugin/VirtualAudio` (ApplyBeamFormerPreference <- VirtualAudio_PlugIn::SetPropertyData <- HALS_AHPPlugIn::ObjectSetPropertyData <- AudioObjectSetPropertyData <- MediaExperience vaemVADSerializationListener): the default virtual audio device ('vdef', VirtualAudioDevice_Default) does not exist (no audio hardware/driver, no /product/audio). Proposed workaround for GUI bring-up: move VirtualAudio.plugin out of /Library/Audio/Plug-Ins/HAL/ in the next root image (untested). v11 reflashed OK after an interrupted flash (USB unplugged at chunk 25/25). Codex task 2: installcoordinationd crash loop.
- **ROOT CAUSE of the endless migration: no IOPlatformUUID (2026-10-17).** datamigrator's `-[DMMigrator isMigrationNeededWithBuildVersion:lastBuildVersion:clientPID:]` gets lastBuildVersion from `-[DMEnvironment lastBuildVersionPref]` = `CFPreferencesCopyValue("LastSystemVersion", "com.apple.migration", kCFPreferencesCurrentUser, kCFPreferencesCurrentHost)` -> a ByHost file. The phone had `/var/mobile/Library/Preferences/com.apple.migration.plist` (only DMUserDataDisposition) and NO `Preferences/ByHost` directory at all. On arm XNU publishes IOPlatformUUID (gethostuuid) only from `/chosen/unique-chip-id` (8 bytes) + `/chosen/chip-id` (4 bytes) (IOPlatformExpertDevice::generatePlatformUUID, called from IOPlatformExpert::start); the SWEET ADT had neither, so every CurrentHost preference write failed. Fix: mkadt adds `unique-chip-id` = 0x5357454554000001 (synthetic) and `chip-id` = 0x8015 -> UUID `A9683613-3704-53F2-95D0-98A8FB574E78` (same SHA1 namespace computation as the kernel). ADT `shim/out/sweet-0057hi.adt`, boot image `shim/out/shim-boot-0056u.img` (0056 kernel + 0057hi ADT, QEMU OK). **Image v11** = v10 + `Preferences/ByHost/com.apple.migration.<UUID upper and lower>.plist` {LastSystemVersion: 20H392} (501:501, dir 0755 files 0600). Flashing v11 2026-10-17 ~20:10 UTC. Codex (gpt-6.1-sol high) analysing the mediaserverd SIGSEGV loop in `/run/media/dipa/android/ios-sweet-work/codex/` (report `mediaserverd-report.md`).
- **v10 did NOT stop the migration (boot 0056n on v10, 19:18 UTC, `logs/boot-0056n-v10.txt`):** datamigrator + migrationpluginwrapper ran again, backboardd drew the progress UI (13000+ swaps in ~5 min). So `com.apple.DataMigration.plist`/LastSystemVersion is not the deciding input. What is known about the decision (datamigrator XPC service `DataMigration.framework/XPCServices/com.apple.datamigrator.xpc/com.apple.datamigrator`, strings): `Migration sentinel present. Migration necessary.` (sentinel `/private/var/datamigrator/migrate`, created and removed by datamigrator itself; absent in v10), `System build version changed from %@ to %@. Migration necessary.` / `...unchanged... not necessary`, `Disposition dictionary with build version %@ is out of date relative to current build version %@`, `SyntheticDidUpgrade`, DMUserDataDispositionManager; previous build source not found yet (not in the binary's plain strings; likely in DataMigration.framework's DMUserDataDispositionManager / preferences domain `com.apple.migration`). backboardd calls `DMPerformMigrationIfNeeded` and holds SpringBoard in `checkInAndWaitForDataMigration` until it returns. NEXT: find where the previous build version / disposition dictionary is stored (disassemble DataMigration.framework DMUserDataDispositionManager + datamigrator's isMigrationNeeded path), write it into the image; or get datamigrator's os_log out (OS_ACTIVITY_DT_MODE needs a launchd env change).
- **Data migration never records completion -> skip it (image v10, 2026-10-17).** Boot 0056n (18:16 UTC, `logs/boot-0056n.txt`, 30 min): 10 Hz panel copies, backboardd still presents at ~60 Hz (107k swaps), SpringBoard still in `BKSSystemShellService _checkIn` at sample 14. Every migration run takes 1+ hour on cpus=1 and repeats each boot. DataMigration decides from `/var/mobile/Library/Preferences/com.apple.DataMigration.plist` key `LastSystemVersion` (vs ProductBuildVersion 20H392); the pulled phone root (21:01 local) had NO such file. **v10** = that pulled phone state + fsck.hfsplus -fy (volume was marked not cleanly unmounted -> Linux mounts it read-only even with -o force; fsck found only hard-link counts + minor volume header, repaired) + `com.apple.DataMigration.plist` {LastSystemVersion: 20H392} (501:501 0600). `/run/media/dipa/android/ios-sweet-ipsw/ios16-root-20H392-v10.img` (+ .sha256, .simg); v8 files deleted, v9 kept as fallback.
- **Repo made PUBLIC (2026-10-17, user request) so GitHub-hosted macOS runners are free:** the 0056 CI run was refused ("recent account payments have failed or your spending limit needs to be increased"). Checked before: no device dumps, serials, IMEI or Apple binaries in the history (.gitignore keeps backup/, dtb/, recovery/, research/ out); commit author emails are public now. 0056 rerun `39056660104` passed -> `xnu/out-0056`, QEMU OK, image `shim/out/shim-boot-0056n.img` booted 18:16 UTC.
- **Boot 0055n (17:16 UTC, ~65 min, `logs/boot-0055n.txt`): migration bar reached 99% in ~30 min (was ~60), then crawled.** Root cause of the slowness: backboardd presents the progress UI at ~58 Hz (**167,000 swaps in ~48 min**) and AppleCLCD copied the full 10 MB frame into the panel on every swap -> ~600 MB/s memcpy on the single CPU (cpus=1), starving everything (polled UFS I/O too). Sampler (16 frames): **SpringBoard waits in `-[BKSSystemShellService _checkIn]`** (synchronous BSXPC call to backboardd, from FBSystemShellInitialize <- SBSystemAppMain) - backboardd holds the system shell check-in until the data migration ends, so the migration is the gate to SpringBoard UI. **Patch 0056**: swap only records the latest swap record; the vsync timer copies it to the panel every 60/sweetfb_hz ticks (default 10 Hz); `SWEET FB: N swaps` every 1000.
- **Boot 0054n (16:53 UTC, ~12 min, `logs/boot-0054n.txt`, patch 0054 sampler):** the data migration runs AGAIN on every boot (it completed once in the 0053s run) - completion is not being recorded. backboardd keeps swapping the progress UI (3700+ swaps in ~10 min, `SWEET FB: N swaps`). Sample during migration: SpringBoard main thread blocked in a synchronous XPC call (`mach_msg2_trap <- dispatch_mach_send_and_wait_for_reply <- xpc_connection_send_message_with_reply_sync <- -[BSXPCServiceConnectionMessage _sendSynchronously:] <- BSXPCServiceConnectionProxy ...`). Unsupported AKS selectors seen: 101 `aks_assert_consume`, 93 `aks_get_internal_info`, 34 `_aks_stash_load` (datamigrator), **35 `aks_get_extended_device_state`** (SpringBoard, chronod, remindd, searchd, symptomsd...). **Patch 0055**: AKS 35 answered like 17 (same DER device state), 101 succeeds; sampler backtraces 16 frames, 40 samples (~80 min).
- **MILESTONE: FIRST iOS PIXELS ON THE PANEL (boot 0053s long run, 15:33 UTC, ~60 min; photos IMG_20261017_183029/183222/183419; log `/run/media/dipa/android/ios-sweet-work/logs/boot-0053s-long.txt`, 407 KB, 1428 flushes).** The iOS data-migration boot screen (Apple logo + progress bar) was shown and the bar advanced to full in ~60 minutes. It is drawn by **backboardd through our kernel display path**: `SWEET SURF: backboardd create id 2/3 1080x2400 fmt 0x42475241 (BGRA) bpe 4 bpr 4352 size 10452992 keys 11`, IOSurface sels 9, 27, 5, 34 and traps 2/3 (lock/unlock), IOMFB SwapBegin (4) / SwapEnd (5, 1132-byte struct) / GetLayerDefaultSurface (3) / 68 / 55, then `SWEET FB: swap N layer 0 surface 2|3 1080x2400 ... a 0,0 1080x2400 b 0,0 1080x2400` alternating (double buffering; only the first 16 swaps are logged). Triggered by `com.apple.datamigrator` (AKS sels 101/93/34 return unsupported) and `com.apple.migrationpluginwrapper`. Probably ProgressUI-style CoreGraphics drawing into IOSurfaces (no GPU used). After the migration: SpringBoard and backboardd stay up (exec once each, no crash), nothing new drawn; crash loops only for mediaserverd, installcoordinationd, mobileactivationd (~108 each in the hour); bluetoothd and fairplayd.H2 relaunch constantly (no hardware). Kernel console text overlays the image (sweetfb_noconsole=1 would hide it).
- **MILESTONE: SpringBoard and backboardd both stay up (boot 0053s on v9, 15:29 UTC, `logs/boot-0053s.txt`).** With /chosen/display-scale = 3: `exec SpringBoard` once, `exec backboardd` once, no CRASH for either; MobileGestaltHelper reads IOMFB size/dot pitch; backboardd opens AppleCLCD (sels 57,15,22,29,33,79,74 as before). No IOSurface creates and no swaps: backboardd keeps polling `IOProviderClass IOAcceleratorES` (-> 0 found) and AGXAccelerator/IOAcceleratorESLegacy - no GPU, so no CoreAnimation renderer yet. Log goes quiet after ~47 s (only 47 flushes): the system idles. NEXT WALL: CoreAnimation rendering without a GPU (CPU path) so the window server produces frames.
- **SpringBoard's invalid mode = scale 0 (boot 0053n, 15:19 UTC, `logs/boot-0053n.txt`, heap scan):** `FBSDisplayMode cannot be configured as requested : <FBSDisplayMode: ...; infxinf@0x (1080x2400/0) 60Hz sRGB SDR>` - pixel size and 60 Hz are fine, scale is 0. libMobileGestalt (MGIOMFBSupport.c, sub_19c560a54) reads `display-scale` (u32, default 0) and `display-rotation` from **IODeviceTree:/chosen**, pixel size via IOMobileFramebufferGetDisplaySize (MobileGestaltHelper sel 8/28 in the log). mkadt now adds `/chosen/display-scale` = 3 (1080x2400 @3x = 360x800 pt). ADT `shim/out/sweet-0054hi.adt` (QEMU `research/q0054-hi.adt`), image `shim/out/shim-boot-0053s.img` = 0053 kernel + 0054hi ADT. Possible catch: MobileGestalt may have cached scale 0 in `/private/var/containers/Shared/SystemGroup/systemgroup.com.apple.mobilegestaltcache/...`.
- **MILESTONE: backboardd survives and opens the display (boot 0052n on v9, 15:07 UTC, `logs/boot-0052n.txt`).** No `CRASH backboardd`. It walks `IODeviceTree:/arm-io` children, matches IOMobileFramebuffer, `open AppleCLCD type 0 -> 0x0`, calls IOMFB selectors 57, 15, 22, 29, 33, 79 (GetBlock, out 1580/40), 74 (SupportedFrameInfo), 12, 6, 27, 17, 84, 50; opens IOCoreSurfaceRoot (sel 13); looks for AGXAccelerator / IOAcceleratorES / IOAcceleratorESLegacy (none, repeatedly), `IODeviceTree:/product` (none, repeatedly), `/buttons`, aop-smart-cover, IOPMrootDomain. No swaps yet. **SpringBoard now gets past display discovery** and dies (sig 5) in `-[FBSDisplayMode _initWithWidth:height:preferredScale:scaleOverride:refreshRate:gamut:hdr:rotation:virtual:validityCheck:]+580` <- `_initWithCADisplayMode:scale:rotation:` <- `FBSDisplayConfiguration _initWithImmutableDisplay:` <- `FBSDisplaySource initWithDisplay:` <- `FBSDisplayMonitor` (slide 0x14504000): "FBSDisplayMode cannot be configured as requested". Checks: width/height >= 2, preferredScale > 0, scaleOverride >= 0, refreshRate non-zero, valid gamut/HDR/rotation. Suspects: refresh rate 0 (IOMFB timing blocks answered with zeros) and/or scale 0 (MobileGestalt main-screen-scale; no /product node in the ADT). **Patch 0053**: heap text scan also on SIGTRAP and for SpringBoard (default sweetscan list backboardd,SpringBoard) to read the exact mode description.
- **Image v9 (2026-10-17) = v8 + `/private/var/containers/{Bundle,Data/System,Shared/SystemGroup,Temp}` (root:wheel 0755; on iOS these live on the data volume, absent from the rootfs) + launchd.plist with StandardOutPath/StandardErrorPath renamed to ...PatX (the in-place phone fix; daemons' stdout reaches the log via the 0048 /dev/null tee).** `/run/media/dipa/android/ios-sweet-ipsw/ios16-root-20H392-v9.img` SHA256 aa9f9139...6e67, `.simg` 12,145,303,864 bytes; written through `sudo mount -t hfsplus -o loop,force`. **Patch 0052** (`xnu/patches/0052-sweet-hfs-rename-swap.patch`, CI `39042761826` -> `xnu/out-0052`, QEMU OK, image `shim/out/shim-boot-0052n.img`): vn_rename falls back to VNOP_EXCHANGE when VNOP_RENAMEX(RENAME_SWAP) returns ENOTSUP for two regular files on one volume (HFS exchange swaps data and cnode descriptors = swap semantics). Flashing v9 started 2026-10-17 ~15:00 UTC.
- **backboardd EXCEPTION FOUND (boot 0051n, 14:41 UTC, `logs/boot-0051n.txt`, patch 0051 heap scan):** `*** Terminating app due to uncaught exception 'NSInvalidArgumentException', reason: '*** -[NSURL initFileURLWithPath:]: nil string parameter'`. First-throw stack (slide 0x337f0000): `+[NSURL fileURLWithPath:]` <- `-[BSSystemContainerForCurrentProcessPathProvider libraryPath]` <- `cachesPath` <- backboardd main+0x1d858 (StartWindowServer, shader cache path). BaseBoard: libraryPath = `BSSystemSharedResourcesDirectoryForIdentifier` = `BSSystemSharedDirectoryForIdentifier(id)` + "/Library"; that calls `container_system_path_for_identifier` (libsystem_containermanager -> `_container_legacy_lookup` -> containermanagerd XPC), which returned NULL (BaseBoard logs "Error getting shared system container ..."). With 0050 the sandbox denials are gone. containermanagerd.log.0 in the pulled (pre-0050) image: "Did not receive any persona attributes", "Expected to find at least one persona", notify_register_dispatch failed 9; `/private/var/containers` does NOT exist in the root image (on iOS it lives on the data volume). usermanagerd does create kernel personas 99/199/1000, but fails to save `/private/var/keybags/usersession.kb` and `persona.kb`: "Failed to atomically swap writing file: Operation not supported (45)" (HFS has no RENAME_SWAP). NEXT: create `/private/var/containers` (and check what containermanagerd needs for system group containers), fix or emulate RENAME_SWAP on HFS, then re-check backboardd.
- **Disk housekeeping (2026-10-17):** /home was at 4 GiB free. Moved (not deleted) `xnu/out-0010..0044` and old `shim/out/*.img`/`payload-*.bin` (everything before 0046) to `/run/media/dipa/android/ios-sweet-work/archive/{xnu,shim-out}` (6.3 GiB); /home now 8.7 GiB free. Large work files (phone-root.img 16 GiB, logs, tracev3 dumps) live in `/run/media/dipa/android/ios-sweet-work/`. **Patch 0051** (`xnu/patches/0051-sweet-crash-heap-strings.patch`, CI `39041440935`): on SIGABRT of a process in boot-arg `sweetscan` (default backboardd) the crash log prints heap text runs as `STR ...` (to find the NSException reason). Boot 0051n 14:41 UTC.
- **Boot 0049n (14:11 UTC, `logs/boot-0049n.txt`, patch 0049 trace): backboardd's IOKit lookups before it dies** (each run): `IODeviceTree:/arm-io/pearl-sep` -> none, matching ApplePearlSEPDriver -> none, `IOService:/IOResources/AppleKeyStore` open OK, matching IOHIDDevice (DeviceUsagePairs) / `HIDServiceSupport` notifications, `usb-drd,t8027` notification; **never any IOMobileFramebuffer / display lookup** - the exception happens before display detection. launchd (tracev3) shows backboardd's mach lookups denied with `error = 159: Sandbox restriction`: com.apple.mobilegestalt.xpc, com.apple.iohideventsystem, com.apple.system.notification_center, com.apple.logd, containermanagerd, ACCHWComponentAuthService, oscard. libsystem_sandbox uses `__mac_syscall("Sandbox", op, arg)` (ops: 1 init, 2 check, 3 note, 4 container path, 5/6/7/8 extensions, 0x15 check_bulk, ...); with no policy named "Sandbox" every call gets ENOPOLICY. **Patch 0050** (`xnu/patches/0050-sweet-sandbox-policy.patch`): built-in permissive MAC policy "Sandbox" in sweet_amfi.c (mpo_policy_syscall returns 0, container/extension ops ENOENT; logs first use of each op as `SWEET Sandbox: proc op N`).
- **Phone root pulled (16 GiB, 12 min, `adb exec-out dd if=/dev/block/sda34`) to `/run/media/dipa/android/ios-sweet-work/phone-root.img` (loop-mounted ro at /run/media/dipa/iOSRoot).** No .ips crash reports. logd tracev3 (Persist, LZ4 `bv41` blocks, decompressed strings in `ios-sweet-work/tracev3/all.txt`): /private/var/db/uuidtext is EMPTY so only launchd's own messages are readable. Findings: v8 launch failure = `Service could not initialize: posix_spawn(/usr/libexec/backboardd), error 0xd - Permission denied` (xpcproxy exit 78) - /dev/console not openable for the mobile user; backboardd[98] spawned `com.apple.MTLCompilerService` before SIGABRT; **launchd denies many mach lookups with `error = 159: Sandbox restriction`** (mediaserverd -> com.apple.backboard.display.services, remoted, mobiletimerd -> sleepd, identityservicesd -> apsd) and **tccd exits OS_REASON_SANDBOX "profile not found"** - no Sandbox kext/profiles on SWEET; likely cause of many daemon crash loops (next wall after the display). CF's uncaught-exception text never reaches stderr for daemons (no CF handler; libc++abi prints only the type). **Patch 0049** (`xnu/patches/0049-sweet-iokit-trace.patch`): `IOK name: ...` console lines for registry path lookups, child iterators, matching (with result count/class), matching notifications and IOServiceOpen of the processes in boot-arg `sweetiolog` (default backboardd), max 400 lines.
- **CONFIRMED: launchd StandardOut/ErrorPath=/dev/console stops backboardd from launching.** After the in-place rename (boot 0047n-b, log `logs/boot-0047n-b.txt`) backboardd launches again and dies as on v7: sig 6, `___pthread_kill <- abort <- demangling_terminate_handler <- _objc_terminate <- std::terminate <- _dispatch_client_callout <- _dispatch_once_callout <- main+0x9334` (window-server dispatch_once). It never opened AppleCLCD or IOCoreSurfaceRoot (no `SWEET FB/SURF: backboardd` lines) -> throws before/at display detection. **Patch 0048** (`xnu/patches/0048-sweet-devnull-tee.patch`, CI `39037749668` -> `xnu/out-0048`, image `shim/out/shim-boot-0048n.img`): writes to /dev/null by processes named in boot-arg `sweetnull` (default `backboardd,SpringBoard`) are printed as `|name| text`. Boot 0048n (13:48 UTC, log `logs/boot-0048n.txt`): only `|backboardd| libc++abi: terminating due to uncaught exception of type NSException` (CF's reason line goes to os_log, not stderr, despite CFLOG_FORCE_STDERR/OS_ACTIVITY_DT_MODE). Next: pull the whole 16 GiB root from recovery (`adb exec-out dd if=/dev/block/sda34`) to `/run/media/dipa/android/ios-sweet-work/phone-root.img` and read ReportCrash .ips files / logd tracev3 for the exception reason.
- **Persistent log WORKS (boot 0047n on v8, 13:31 UTC; pulled from OrangeFox: 70 KB, 111 flushes, `/run/media/dipa/android/ios-sweet-work/logs/boot-0047n.txt`).** In 3 min **backboardd was never exec'd** (v7 ran it), ~70 bare `exec xpcproxy`, SpringBoard loops on FBSDisplayMonitor (no display), mediaserverd sig 11 loop, locationd, lockdownd sig 5. Suspect the v8 plist (StandardOut/ErrorPath=/dev/console on backboardd). **In-place plist edit from recovery (no reflash):** launchd.plist is one extent at image/partition byte offset 0x1e025f000 (195 blocks; verified bytes identical on phone vs local v8 mount); renamed StandardOutPath->StandardOutPatX and StandardErrorPath->StandardErrorPatX (same length, both jobs) in blocks 68 and 105 via `adb push` + `dd of=/dev/block/sda34 seek=... conv=notrunc,fsync`, read back VERIFIED. Phone now differs from local v8 image in those 2 blocks (files in `/run/media/dipa/android/ios-sweet-work/`). Test boot 0047n 13:38:42 UTC. Recovery kernel has no hfsplus (raw block edits only).
- **Patch 0047: persistent console log (CI `39036478663` -> `xnu/out-0047`, QEMU no panic; phone image `shim/out/shim-boot-0047n.img` = 0047 + sweet-0046hi.adt + 0045n cmdline).** `_cnputs` (all console output: kernel printf + daemons' /dev/console) also appends to a 4 MiB ring in sweet_ufs.c; after the UFS partition is ready and writable (ufsrw=1) a thread writes new ring blocks + header to the LAST 1025 blocks (4 KiB) of userdata every ~1 s and SYNCHRONIZE CACHE (prints `SWEET LOG: console log to the last 4100 KiB ...`). Read: phone to fastboot -> `fastboot boot recovery/recovery.img` (OrangeFox) -> `tools/sweet-log-pull.sh OUT.txt` (adb dd of that area + `tools/sweet-log.py`). Not yet verified on the phone. Panics after the last flush are not in it (screen still shows them). 2x font attempt reverted: XNU's v_scale only scales the progress icon.
- **Boot 0046n on v8 (13:05 UTC, VID_20261017_150522_HSR_120):** phone prints `SWEET SURF: IOCoreSurfaceRoot registered` and `SWEET FB: AppleCLCD 1080x2400 stride 4320 at 0x9c000000, default surface 1` (nubs + match work on hardware). Visible userspace: early boot tasks, launchd_cache_loader, `exec SpringBoard`; no `exec backboardd` / `SWEET FB: backboardd` line seen in the readable frames (video blurry). Frame 00:47: lower half of the screen shows OLDER console text (16:01:12) below newer lines -> unconfirmed hint that a swap copied an old snapshot of the panel (CA reads the default/displayed surface = panel memory). SpringBoard still dies in `-[FBSDisplayMonitor _initWithBookendObserver:transformer:]+1160` (sig 5, slide 0x30960000). **Shim: 2x console font** (`shim/loader.c` Video.v_depth scale field = 1) so phone videos are readable; image `shim/out/shim-boot-0046b.img` = 0046n + 2x font.
- **Patch 0046: built-in IOSurface + IOMobileFramebuffer (2026-10-17, offline, NOT phone-tested).** `xnu/patches/0046-sweet-iosurface-iomfb.patch`: new `iokit/Kernel/arm/SweetSurface.{h,cpp}` (IOCoreSurfaceRoot + IOSurfaceRootUserClient: sel 13/0/4/34/35, traps 0-5, wired buffers mapped into the caller, per-client refs) and `SweetFramebuffer.cpp` (AppleCLCD : IOMobileFramebuffer on /arm-io/disp0: sizes, swap = CPU copy of enabled layers into the ABL panel memory, 60 Hz vsync via sendAsyncResult64WithOptions(CanDrop), panel memory published as the default IOSurface, kernel text console paused on the first swap only with `sweetfb_noconsole=1` (default keeps the console: pausing switches it to serial and would hide panics)); SweetPlatformExpert creates nubs for /arm-io children (not gic) attached to the platform expert (IOPlatformDevice::compareName casts its provider to IOPlatformExpert, so nubs under the arm-io nub never matched - first CI build showed that in QEMU). mkadt: /arm-io/disp0 {device_type display-subsystem, compatible sweet,display, canvas-width 1080, canvas-height 2400}. CI `39021572169` -> `xnu/out-0046`. **QEMU** (`research/q0046-hi.adt`, RAM disk init, msgbuf): `SWEET SURF: IOCoreSurfaceRoot registered`, `SWEET FB: AppleCLCD 1080x2400 stride 4320 at 0x9c000000, default surface 1`, init alive, no panic. Phone image **`shim/out/shim-boot-0046n.img`** (SHA256 9c4d2fe9..., CI `39024108588` with the review fixes: swap bounds check, zeroed 64-bit async ref, port release, 1.5 GiB wired budget, ref leak/race fixes; QEMU re-checked) = 0046 kernel + `shim/out/sweet-0046hi.adt` + the 0045n cmdline; boot it on image v8 (backboardd/SpringBoard log to console) and film. Expected new console lines: `SWEET SURF: <proc> create id ...`, `SWEET FB: backboardd sel N ...`, `SWEET FB: swap ...`. Open question for the next wall: QuartzCore's IOMFB server builds its renderer from Metal first (`CAMetalContextCreate`), GLES only when enabled; how the CPU renderer gets selected on a device without a GPU is not yet established.
- **IOSurface values ABI (offline RE, `/run/media/dipa/android/ios-sweet-work/iosurface-values.md`) - TODO in SweetSurface (0046 only accepts and drops values, so IOSurfaceCopyValue always returns NULL):** sel 9 SetValue in = {u32 id, u32 pad, IOCFSerialize([value, key]) or ([dict] = merge)}, sel 0xb RemoveValue in = {u32 id, u32 pad, key\0} (empty key = remove all); both out 4 bytes = new generation, client accepts only (gen+2)|1. Kernel after each change: gen = (gen+2)|1 (odd, never 0) -> state+0x20, serialized size (>=1) -> state+0x28. sel 0xa in {u32 id, u32 0, u8 0}, out {u32 ?, u32 gen, serialized non-bulk dict}; too small -> 0xe00002db + needed size (client retries x16). sel 0x1b in 0x88: bulk struct 0x70 @0, u64 valid size @0x70, u64 changed mask @0x78, u32 id @0x80 -> copy masked fields into state+0x30 (bit0 32B @0, bit1 16B @0x20, bit2 8B @0x30, bits3-10 1B @0x38..0x3f, bits11-14 24B @0x40/4B @0x58/8B @0x5c/1B @0x64).
- **IOMFB display matching confirmed (offline RE, `/run/media/dipa/android/ios-sweet-work/iomfb-match.md`):** the framework never matches on "AppleCLCD"; any registered IOMobileFramebuffer subclass works. `iomfb_match_callback` reads only `dfr`/`AppleTV`/`external` (CFBoolean, service itself, no parents); internal main display = all absent/false (type 0, name "primary"). Display count = /arm-io children whose device_type starts with "display-subsystem" (count 0 -> CreateDisplayList returns NULL; more nodes than services -> 30 s wait). IOMobileFramebufferOpen fails only on IOServiceOpen failure; canvas-width/height read as 4-byte CFData from the IOService-plane parent (optional). CopyProperty = IORegistryEntrySearchCFProperty on the service only. Patch 0046 (disp0 node, `external`=false, AppleCLCD : IOMobileFramebuffer) fits all of this.
- **IOMobileFramebuffer swap + notification ABI (2026-10-17, offline).** Swap record = fb+0x18, **0x46c bytes**, zeroed by SwapBegin and sent whole by `kern_SwapEnd` = IOConnectCallStructMethod(sel 5, rec, 0x46c, no output). **SwapBegin** = sel 4, no input, 1 scalar out = swap id (stored at rec+0x50). `kern_SwapSetLayer(fb, layer<4, IOSurfaceRef, CGRect a, CGRect b, flags)`: rec+0x54+4*layer = **IOSurface id**; rec+0x104 bit layer = layer enabled (rec+0x108 bit cleared); rect a (int x,y,w,h, scaled) at rec+0x64+16*layer, rect b at rec+0xc4+16*layer; rec+0x114+4*layer = transform from flags&0xf; flag bits 5/31/6/7/8/9 set bytes rec+0x2ca/0x2cc/0x2e3/0x2e5/0x2e6/0x467+layer. A NULL surface only sets the enable bit with zero id. SwapWait = sel 6 scalars [swap id, timeout, 0].
  - **Notifications**: `IOMobileFramebufferScheduleWithDispatchQueue`/`GetRunLoopSource` create an IONotificationPort and `IOConnectSetNotificationPort(conn, type, port, 0)` (kernel `registerNotificationPort`). `kern_EnableNotifications(fb, type, cb, ctx)` = **sel 72 scalars [NotifyCallbackFuncs[type], fb, type, 0]** -> the kernel keeps an async reference {port, func, refcon=fb} per type and fires it with `sendAsyncResult64`. Types: 0 HotPlug, 1 Power, 3 FrameInfo (args[0] = mask of 31-bit keys, args[1] u32, then values), 4 CRC, **5 Vsync**: 6 args, each a 32-bit half in a u64 slot: (ts lo, ts hi), (t2 lo, hi) passed through the time-ingest helper, (t3 lo, hi); the framework then calls the client's vsync callback(fb, ts, t2', t3, ctx). Vsync callbacks are dropped while the notification port has queued messages.

- **IOSurface.framework user-client ABI reversed (2026-10-17, offline, step 2 of the GUI plan).** `ipsw dyld disass research/dsc/dyld_shared_cache_arm64 --image IOSurface` (selector scan script: scratchpad `selscan.py`).
  - Connect (`_iosConnectInitalize`, pthread_once): `IOServiceGetMatchingService(IOServiceNameMatching("IOCoreSurfaceRoot"))`, retried with sleep(1) up to 241 times (a missing service stalls every client ~4 min, no crash); `IOServiceOpen(type 0)`; then **sel 13** (no inputs, struct out 0x18 bytes = `_ioSurfaceLimits`) and requires u16 at out+0x16 == 1 (ABI version); out+0 = offset/plane-base alignment mask, out+4 = bytes-per-row alignment mask (used as (x+m)&~m), +0..+0x14 also copied into IOSurface remote-method init, otherwise logs and closes the connection.
  - **Create = sel 0**: scalar in [parent id or 0], struct in = `IOCFSerialize(props, kIOCFSerializeToBinary)` (OSUnserializeBinary format; keys IOSurfaceWidth/Height/BytesPerRow/BytesPerElement/PixelFormat/AllocSize/PlaneInfo/CacheMode/IsGlobal/...), struct out **0xa68 bytes** ("lock result"). **Lookup = sel 4**: scalar in [id], same struct out. LookupFromMachPort = sel 0x22 (scalar in [port name]); CreateMachPort = sel 0x23 (scalar in [id, options], scalar out [port name]).
  - Lock result (copied to client+0x68, size 0x68 + planes*0x80, min 0xe8): 0x00 u64 base address **mapped in the caller's task**; 0x08 u64 task VA of a per-surface shared state page (+0 u64 registry id, +8/+0xa u16 bound accel ids, +0xc u32 seed, +0x14 u8 tiled, +0x20 u32 value generation, +0x24 YCbCr matrix, +0x28 u32 non-bulk values size, +0x2d u8 displayable, +0x2e u8 sysmem-only, +0x30 0x70 bytes bulk attachments); 0x10 u64 task VA of timestamp page (4 u64 indexed timestamps, +0x20 detach code); 0x18 u32 surface id; 0x1c u32 alloc size; 0x20 width; 0x24 height; 0x28 bytes per row; 0x2c buffer offset; 0x30 pixel format; 0x34 u32 (dcache flush length); 0x38 plane count; 0x40 u16 bytes/element; 0x42 u8 element width; 0x43 u8 element height; 0x44 cache mode; 0x4c u8 subsampling; 0x4d u8 prohibit-use count; 0x50 parent id; 0x54 slice count; 0x58 u64 trace id; 0x60 u64 protection options; planes[n] at 0x68+n*0x80 (+0 width, +4 height, +8 bytes/row, +0xc offset, +0x14 size, +0x18 u16 bpe, +0x1a/+0x1b u8 element w/h, +0x1c u8 component count, +0x1d address format, +0x54 u8 compression type (non-zero -> no CPU base address)).
  - **Traps** (IOConnectTrapN -> `IOUserClient::getTargetAndTrapForIndex`): 0 IncrementUseCount(id, category), 1 DecrementUseCount(id, category), 2 **Lock**(id, options, &seed_out), 3 **Unlock**(id, options, &seed_out), 4 Release(id), 5 Release after a failed create/lookup setup (id).
  - Other selectors: 5 SetYCbCrMatrix, 6 WrapClientImage, 7 WrapClientMemory, 9 SetValue (serialized), 0xa UpdateNonBulkValueCache (struct in 9), 0xb RemoveValue, 0xc BindAccel, 0x11 SetSurfaceNotify (async), 0x12 RemoveSurfaceNotify, 0x13 Log, 0x14 SetPurgeable, 0x15 SetOwnership, 0x16 SetTiled, 0x18 SetTimestamp, 0x19 GetTileFormat, 0x1a CopyDataValueBytes, 0x1b SetBulkAttachments (struct 0x88), 0x1e/0x2e-0x31 (via outlined helpers), 0x1f SetCompressedTileDataRegionMemoryUsed, 0x20 GetGraphicsCommPageAddress, 0x21 SetIndexedTimestamp, 0x24-0x26/0x2d IOSurfaceAccelerator, 0x27-0x29 shared events, 0x2a SignalEvent, 0x2b Set/InitDetachModeCode, 0x2c SetOwnershipIdentity, 0x32-0x34 data properties.
  - => SWEET kernel service: class/name **IOCoreSurfaceRoot** + IOSurfaceRootUserClient; minimum = sel 13, 0, 4, 9/0xa/0xb (values), traps 0-5, 0x22/0x23 later for cross-process surfaces (CA sends surfaces to backboardd by mach port). Memory: IOBufferMemoryDescriptor per surface, mapped into each task with createMappingInTask; ids from a global table.

- **Image v8: daemon logs on the console.** `tools/patch-launchd-plist.py IN OUT LABEL...` rewrites launchd.plist (binary, plistlib): renames every `_PanicOnCrash` to `_PanicOnCrasX` and gives the listed jobs `StandardOutPath`/`StandardErrorPath` `/dev/console` (devfs console is 0622, writable by mobile) plus `OS_ACTIVITY_DT_MODE=YES` (os_log mirrored to stderr) and `CFLOG_FORCE_STDERR=1`. v8 = v7 + that plist for com.apple.backboardd and com.apple.SpringBoard, written through the mount (796310 bytes, root:80 0644), SHA256 in `ios16-root-20H392-v8.img.sha256`, `.simg` ready; boot with `shim/out/shim-boot-0045n.img`. Goal: see backboardd's uncaught exception text and the window server's display probing. ODDITY (unresolved): the v5 raw-image rename at offset 0x1e025f000 is present in the v5-v7 image bytes, but the plist read through a Linux mount of v7 still had the original `_PanicOnCrash` keys; filefrag shows the file as one extent. Never patch file contents through raw offsets again; write through the mount.
- **IOMobileFramebuffer.framework reversed (step 1 of the GUI plan).** `ipsw dyld disass research/dsc/dyld_shared_cache_arm64 --image IOMobileFramebuffer`.
  - Display discovery (`IOMobileFramebufferCreateDisplayList` -> `getDisplayListNumber`): iterates children of `IODeviceTree:/arm-io`, counts nodes whose `device_type` is "display-subsystem" or "ext-display-subsystem" (or `compatible` "paravirtualizedgraphics,gpu"); then `iomfb_populate_display_infos` adds an IOServiceAddMatchingNotification(IOServiceFirstMatch, **IOServiceMatching("IOMobileFramebuffer")**) and runs the run loop up to 30 s until that many services matched. `iomfb_match_callback` reads service properties `dfr`, `AppleTV`, `external` (CFBoolean) and names displays (external ones "%s-%d").
  - `IOMobileFramebufferOpen(service, task, type, &fb)`: `__ioMobileFramebufferAlloc` (CFPreferences com.apple.iokit.IOMobileGraphicsFamily: canvas_width/height, override_display_width/height, override_panel_width/height, benchmark, enable_ktrace), `IOServiceOpen(service, task, type)` (GetMainDisplay passes type 0), `getEDTProperty` reads `canvas-width`/`canvas-height` from the service's IODeviceTree parent, then fills a table of `kern_*` function pointers.
  - User client selectors (`kern_*` -> IOConnectCall*): 3 _kern_GetLayerDefaultSurface[ScalarMethod_stub]; 4 _kern_SwapBegin[ScalarMethod_stub]; 5 _kern_SwapEnd[StructMethod_stub]; 6 _kern_SwapWaitWithTimeout[ScalarMethod_stub] _kern_SwapWait[ScalarMethod_stub]; 7 _kern_GetID[ScalarMethod_stub]; 8 _kern_GetDisplaySize[ScalarMethod_stub]; 10 _kern_SetTVOutMode[ScalarMethod_stub]; 11 _kern_SetWSSInfo[ScalarMethod_stub]; 12 _kern_RequestPowerChange[ScalarMethod_stub]; 13 _kern_EnableStatistics[ScalarMethod_stub]; 14 _kern_SetFlags[ScalarMethod_stub]; 15 _kern_SetDebugFlags[ScalarMethod_stub]; 16 _kern_SetTVOutSignalType[ScalarMethod_stub]; 17 _kern_SetGammaTable[StructMethod_stub]; 18 _IOMobileFramebufferIsMainDisplay[ScalarMethod_stub]; 19 _kern_SetWhiteOnBlackMode[ScalarMethod_stub]; 20 _kern_SwapSignal[ScalarMethod_stub]; 22 _kern_SetDisplayDevice[ScalarMethod_stub]; 23 _kern_SetDigitalOutMode[ScalarMethod_stub]; 24 _kern_GetHDCPDownstreamState[StructMethod_stub]; 25 _kern_GetDigitalOutState[ScalarMethod_stub]; 26 _kern_printDisplayRegs[ScalarMethod_stub]; 27 _kern_GetGammaTable[StructMethod_stub]; 28 _kern_GetDotPitch[ScalarMethod_stub]; 29 _kern_GetDisplayArea[StructMethod_stub]; 30 _kern_EnableDisableDithering[ScalarMethod_stub]; 31 _kern_SetUnderrunColor[ScalarMethod_stub]; 33 _kern_EnableDisableVideoPowerSavings[ScalarMethod_stub]; 34 _kern_SetVideoDACGain[ScalarMethod_stub]; 35 _kern_SetLine21Data[ScalarMethod_stub]; 41 _IOMobileFramebufferEnableMirroring[ScalarMethod_stub]; 42 _IOMobileFrameBufferGetMirroringCapability[StructMethod_stub]; 43 _IOMobileFramebufferSetRenderingAngle[StructMethod_stub]; 44 _IOMobileFramebufferSetMirrorContentRegion[StructMethod_stub]; 47 _kern_HDCPSendRequest[ScalarMethod_stub]; 48 _kern_HDCPGetReply[ScalarMethod_stub]; 49 _kern_SurfaceIsReplaceable[ScalarMethod_stub]; 50 _kern_SetBrightnessCorrection[ScalarMethod_stub]; 51 _kern_SetColorRemapMode[ScalarMethod_stub]; 52 _kern_SwapCancel[ScalarMethod_stub]; 53 _IOMobileFramebufferSetCanvasSize[ScalarMethod_stub]; 54 _IOMobileFramebufferGetMatrix[Method_stub]; 55 _IOMobileFramebufferSetMatrix[Method_stub]; 56 _IOMobileFramebufferKernelTests[StructMethod_stub]; 57 _kern_GetColorRemapMode[ScalarMethod_stub]; 66 _kern_SPLCSetBrightness[ScalarMethod_stub]; 67 _kern_SPLCGetBrightness[ScalarMethod_stub]; 68 _kern_SetParameter[Method_stub]; 69 _kern_SwapSetColorMatrix[StructMethod_stub]; 72 _kern_DisableNotifications[ScalarMethod_stub] _kern_EnableNotifications[ScalarMethod_stub]; 73 _kern_ChangeFrameInfo[ScalarMethod_stub]; 74 _kern_SupportedFrameInfo[Method_stub]; 75 _kern_FactoryPortal[StructMethod_stub]; 77 _kern_GetCurrentAbsoluteTime[ScalarMethod_stub]; 78 _kern_SetBlock[Method_stub]; 79 _kern_GetBlock[Method_stub]; 80 _kern_GetLinkQuality[ScalarMethod_stub]; 81 _kern_SwapCancelAll[ScalarMethod_stub]; 82 _kern_GetProtectionOptions[ScalarMethod_stub]; 83 _kern_CopyLayerDisplayedSurface[ScalarMethod_stub]; 84 _kern_SetContrast[StructMethod_stub]; 85 _kern_GetBufBlock[Method_stub]; 86 _IOMFBGainEncoderFinishEncoding[Method_stub]; UNKNOWN {}
  - => Kernel needs: an `/arm-io` child node with device_type "display-subsystem" (+ canvas-width/height) and an IOService of class **IOMobileFramebuffer** (subclass name match) attached under it, opened with type 0, implementing at least GetDisplaySize(8), IsMainDisplay(18), GetID(7), GetLayerDefaultSurface(3), SwapBegin(4)/SwapEnd(5 struct)/SwapWait(6), Enable/DisableNotifications(72), frame info(73/74), CopyLayerDisplayedSurface(83), plus IOSurface for the swapped buffers. NEXT: CoreAnimation's AppleDisplay/IOMFBDisplay usage of these (constructor, first swap, vsync), then IOSurface.framework's IOSurfaceRoot selectors.
- **GUI PLAN (decided 2026-10-16): CPU rendering + kernel IOMobileFramebuffer.** User: CPU rendering is fine for now (goal = prove the GUI runs), may later research an Apple-style GPU driver for the Adreno 618 -> keep display output and renderer separable. QuartzCore findings (symbols from the cache's .symbols subcache: `ipsw dyld symaddr research/dsc/dyld_shared_cache_arm64 --image QuartzCore`; strings: `ipsw dyld macho ... QuartzCore --strings`):
  - Renderers: `sw_new_context` (CA::OGL::SWContext, full CPU renderer incl. blur, images, IOSurface-backed surfaces, make_buffer_current(WindowServer::Surface)), `gles_new_context`, `metal_new_context`, `new_null_context`. Env knobs include CA_ENABLE_OGL, CA_DISPLAY_TYPE, CA_FORCE_LOCAL_SERVER, CA_FORCE_TIMER, CA_CANVAS_WIDTH/HEIGHT, CA_MAIN_DISPLAY_SCALE/ORIENTATION, CA_DISABLE_RENDER, CA_ALWAYS_RENDER (selection logic not traced yet).
  - `-[CAWindowServer _detectDisplays]` (0x1884e3150) iterates static tables `open_funcs`/`count_funcs` = AppleCLCDDisplay, AppleRGBOutDisplay, AppleWirelessDisplay only; each `count()` = `display_count_of_type(IOMFBDisplayType)` over **`IOMobileFramebufferCreateDisplayList()`**, `open(i)` = `create_display_of_type` -> `CA::WindowServer::AppleDisplay(CFString name, ..., IOMFBDisplayType)` (an IOMFBDisplay driven by IOMFBServer: vsync_callback, frame_info_callback, swaps). `CA::WindowServer::VirtualDisplay` exists but is never auto-detected (explicit API only). => the main display MUST come from an IOMobileFramebuffer kernel service.
  - NEXT: reverse IOMobileFramebuffer.framework: IOMobileFramebufferCreateDisplayList / IOMobileFramebufferOpen (service matching, display type property), the user-client selectors used by IOMFBServer (display size/modes, swap begin/set-layer/end with IOSurface ids, vsync notifications), then the IOSurface kernel side (IOSurfaceRoot user client: create/lookup/lock, memory mapping) that both IOMFB swaps and CA surfaces need. Kernel: SWEET IOMobileFramebuffer service that copies the swapped IOSurface to the 1080x2400 framebuffer at 0x9c000000.
- **logd fixed; backboardd = DISPLAY WALL (boot 0045n on v7, 21:08:57 UTC, frames VID_20261016_230850 00:55-01:28, slide 0x4c3ec000, `research/crash-0045n-v7.txt`).** No `CRASH logd` any more; new daemons run (runningboardd, WirelessRadioManagerd, networkserviceproxy, dasd, cloudpaird, magicswitchd, atc, askpermissiond, ManagedSettingsAgent, containermanagerd uses AKS 0/17). New: locationd sig 11 at CFRunLoopAddSource+132 (NULL source) from its main+0x2af138 in a dispatch_once. **backboardd** sig 6: abort <- std::terminate <- _objc_terminate <- dispatch_once <- main+0x9334 = the "start %{public}@..." wrapper (0x100009264) for **"window server"** (block 0x10000a770 -> dispatch_once body 0x10001d7f0 = StartWindowServer): MTLSetShaderCachePath, `[CAWindowServer serverWithOptions:@{kCAWindowServerDisableUpdatesOnMainDisplay: @YES}]`, `setRendererFlags:`, **`mainDisplay`** -> `displayId` -> `[CADisplay displayWithDisplayId:]`, setWindowServerDisplay:, bounds, pointScale, currentMode, preferredScale, nativeOrientation, touchScales... With no display, mainDisplay is nil and it throws. (HID system and GS start fine before it.) SpringBoard dies on the same missing display (FBSDisplayMonitor). QuartzCore display backends (from the cache's .symbols subcache, `ipsw dyld str`): `CA::WindowServer::AppleCLCDDisplay` (IOMobileFramebuffer hardware) and **`CA::WindowServer::VirtualDisplay`** (open(), new_server, clone_update). `CA_DISPLAY_TYPE` and `CA_FORCE_LOCAL_SERVER` strings exist in QuartzCore but have no direct xref (likely read via a table of CA_* env names). NEXT: find how CA::WindowServer::Server enumerates displays (IOMobileFramebuffer services vs VirtualDisplay / CA_DISPLAY_TYPE) and choose: (a) kernel IOMobileFramebuffer service + IOSurface, or (b) a VirtualDisplay rendered by CA's CPU path (CA::OGL::SW) and copied to the framebuffer.
- **watchdogd + CommCenter + identityservicesd fixed (boot 0045n on v6, 20:41:30 UTC, frames VID_20261016_224133 00:39-01:13, slide 0x20fec000).** `SWEET WDT: watchdogd sel 0 in 0/0 out 1/0 -> ok`, no watchdogd/CommCenter/identityservicesd crashes (CommCenter/identityservicesd now call AKS 0/17/7). usermanagerd boot task runs (UMD_INIT creates primary session uid 501 "mobile", personas 99 System and 199 Default registered with the kernel); `Failed to atomically swap writing file /private/var//keybags/usersession.kb: Operation not supported (45)` (HFS lacks the atomic swap rename; non-fatal so far). Remaining: SpringBoard (FBSDisplayMonitor, no display), backboardd (uncaught exception), mediaserverd, lockdownd (crash inside obfuscated code, main+0x4c1b4?), logd. **logd**: main+0x18160 = `BUG IN LIBTRACE: Failed to migrate directory` from 0x10001801c(dir 0): 0x100016538 requires the dir to exist with uid/gid/mode from the table at 0x10002df14 (0: /private/var/db/diagnostics 272:272 0751, 1: /private/var/db/uuidtext 272:272 0755, 2: /private/var/db/diagnostics/timesync 272:272 0755) plus a `.migrated` file, else XPC "operation 6" to a helper and crash. **Image v7** = v6 + those dirs/markers (also in mkiosroot.sh), SHA256 in `ios16-root-20H392-v7.img.sha256`, `.simg` ready. Boot with `shim/out/shim-boot-0045n.img`.
- **Exit-reason text works (boot 0044n, frames VID_20261016_221726 00:32-00:53, slide 0x22d5c000).** CommCenter/identityservicesd: `couldn't dlopen libobjc-trampolines.dylib: dlopen(/usr/lib/libobjc-trampolines.dylib, 0x0106): tried: '/usr/lib/libobjc-trampolines.dylib' (no such file, not in dyld cache)`: the file only exists in the OS cryptex and dyld does not search cryptexes at ignition_level=1. 19 cryptex files have no root counterpart (OS: DriverKit dyld cache + .symbols, VisualTestKit, libffi-trampolines, libobjc-trampolines, libstdc++ 6.0.9 + 2 symlinks; App: SafariSupport.bundle, AuthenticationServicesAgent, com.apple.Safari.History, passwordbreachd, safarifetcherd, webbookmarksd, webinspectord, webpushd) -> hard-linked (symlinks copied: Linux hfsplus cannot hard-link symlinks); `tools/mkiosroot.sh` does it generically. watchdogd still crashed: the `-wdt_no_pmu` / `/arm-io/wdt no-pmu` check (0x10000a01c) only runs when os_variant_has_internal_diagnostics; otherwise 0x100009b18 looks up IOServiceMatching("IOService") + IOPropertyMatch {IOPMUPrimary: 1} (NSConstantDictionary) and crashes if absent, then IORegistryEntrySetCFProperty(boot stage 0xff) (failure only logged). Patch **0045**: IOWatchdog sets IOPMUPrimary = 1 and accepts setProperties; CI `38961814194` -> `xnu/out-0045`. **Image v6** = v5 + the 19 cryptex links, SHA256 7c610c6a...297a, `ios16-root-20H392-v6.simg` (full flash needed). Boot image `shim/out/shim-boot-0045n.img` (0045 + sweet-0044hi.adt). Still open: SpringBoard (no display), backboardd (uncaught exception, reason none), mediaserverd (Fig NULL dict), logd (main+0x18160), lockdownd (main+0x4c1b4).
- **System survives daemon crashes (boot 0043p, video frames VID_20261016_215006 00:25/00:42/00:54).** With the v5 plist patch no panic: launchd keeps launching (runningboardd, powerd, tccd, healthd, peopled, cryptexd, routined, aksd, mediaremoted, familynotificationd, nanoprefsyncd, navd, cloudpaird, passd, amsaccountsd, accessoryupdaterd, wcd ...). Shared cache slide that boot 0x406b4000 (`research/crash-0043p.txt`). watchdogd still crashed at main+0xb82c from the PMU step: `-wdt_no_pmu` is only honored when os_variant_has_internal_diagnostics; customer builds read `no-pmu` from IODeviceTree:/arm-io/wdt (IORegistryEntrySearchCFProperty) -> mkadt adds /arm-io/wdt {no-pmu}. **cryptexd** sig 6: abort_with_payload <- os_crash_fmt <- `__darwin_arm_secure_boot_chip.cold.7` ("panic: failed to get crypto algorithm") <- `_img4_chip_select_personalized_ap`: reads /chosen use-ddi-secure-boot, allow-ecid-mismatch, crypto-hash-method ("sha1" | "sha2-384"), /chosen/asmb lp-smb0/1 -> mkadt adds crypto-hash-method "sha2-384". **identityservicesd** sig 6 = same `_objc_fatal` in imp_implementationWithBlock as CommCenter (block trampolines; message needed). lockdownd sig 5 at main+0x4c1b4. Patch **0044**: crash report adds `CRASH name reason ns N code X: text` (exit reason description = abort_with_payload text). CI `38959096811` -> `xnu/out-0044`, QEMU OK. Image `shim/out/shim-boot-0044n.img` = 0044 + `shim/out/sweet-0044hi.adt` (wdt no-pmu, crypto-hash-method) + cmdline (wdt=-1, no -wdt_no_pmu).
- **First symbolicated daemon crashes (boot 0043u on journaled v4, 19:38:53 UTC; video frame chat image 36; transcribed in `research/crash-0043u.txt`; shared cache slide 0x40d60000 for every process).** (Gemini's video transcription invented values, use frames only.) `tools/sweet-crash.py research/dsc/dyld_shared_cache_arm64 x research/crash-0043u.txt`:
  - **watchdogd** pc main+0xb82c (`_os_crash` trap helper) from 0x100009bb0 = set PMU boot stage via IORegistry (no PMU) -> fix: boot-args `wdt=-1 -wdt_no_pmu` (Apple's own test mode writes "%s wdt=-1 -wdt_no_pmu"; watchdogd logs "skipping setting PMU boot stage because -wdt_no_pmu found in boot-args or no-pmu found in EDT"). Kernel effect of wdt=-1: sched hygiene debug off, zone_exhausted_timeout -1 (harmless).
  - **SpringBoard** sig 5 in `-[FBSDisplayMonitor _initWithBookendObserver:transformer:]+1160` <- `+[FBDisplayManager sharedInstance]` <- `FBSystemShellInitialize` <- `SBSystemAppMain`: no main display. GUI WALL: display service (IOMobileFramebuffer / CoreAnimation display).
  - **backboardd** sig 6: abort <- std::terminate <- _objc_terminate (uncaught exception; message not shown).
  - **CommCenter** sig 6: `_objc_fatal` in `imp_implementationWithBlock` (from `+[_PFRoutines initialize]`, CoreData): objc block trampolines cannot be allocated -> likely kernel gap (trampoline page remap); will hit many processes.
  - **mediaserverd** sig 11: CFDictionaryGetValue(NULL) in FigNotificationListenerStartNotifications (routing session manager).
  - **logd** sig 5 at its main+0x18160 (bt main+0x9dfc); lockdownd sig 5 (not yet symbolicated).
  - Image v5 = v4 + launchd.plist (`/System/Library/xpc/launchd.plist`, contiguous at image offset 0x1e025f000, 1456980 bytes) with the 7 `_PanicOnCrash` keys renamed `_PanicOnCrasX` in place (raw image patch, no metadata change) -> `diff-v4-v5.simg` = 7 blocks; v5 SHA256 78f96974...185a. Boot image `shim/out/shim-boot-0043p.img` = 0043 + `wdt=-1 -wdt_no_pmu`.
- **0043 console crash reports (QEMU verified); image `shim/out/shim-boot-0043u.img`; NEXT: flash v4 + boot 0043u.** Boot 0042u (video photo IMG_20261016_211646): short exec lines work; watchdogd crashes with NO `SWEET WDT:` line (fails before its first IOWatchdog call: lookup or IOServiceOpen, or elsewhere); lockdownd, SpringBoard, mediaserverd, CommCenter, identityservicesd, backboardd, watchdogd all crash repeatedly ("Too many corpses being created" = corpse limit, no crash reports). AKS callers: lockdownd (0, 7), imagent/sleepd (0, 17, 7), backboardd (0, 17), UserEventAgent (0, 7, 102, 103 -> unsupported). Patch **0043**: `sweet_crash_log` (osfmk/kern/exception.c, called from proc_prepareexit for crash exits on the current proc) prints `CRASH name[pid] sig S code (exc<<32|code) sub X slide SR mh MH`, `CRASH name pc lr sp fp far`, `CRASH name bt` (10 fp frames); AKS sel 103 notify_state_is_set -> 0. CI `38954520419` -> `xnu/out-0043`. QEMU test: init forks, child `brk #1`: `CRASH launchd[2] sig 5 code 0x600000001 sub 0x1000004f0 slide 0x0`, pc correct, parent keeps running (pid 1 crashes panic before proc_prepareexit, so test with a child). `tools/sweet-crash.py CACHE ROOT [report]` symbolicates typed-in CRASH lines (`ipsw dyld a2s` with addr - slide; main binary offsets = addr - mh + 0x100000000).
- **v3 reflashed 18:50-18:55 UTC (`research/flash-userdata-v3b.log`, 24/24 OKAY); 0042u booted 19:01:17 UTC on the clean disk (`research/boot0042u-2.log`), SLOW MO VID pending (watchdogd failure reason).** ABL hangs on the first `fastboot boot` after every big flash; user re-enters fastboot. User gave standing approval to reflash/boot without asking (memory standing-flash-approval). Commits now end with `Co-Authored-By: dipa-studio <183933817+dipa-studio@users.noreply.github.com>` (user request; never a Claude trailer).
  - watchdogd flow: connect_to_kext (0x100005408): IOServiceGetMatchingService("IOWatchdog") fails -> "failed to discover" + _os_crash; IOServiceOpen(type 1) fails -> "IOServiceOpen failed with error : 0x%x" + _os_crash. Then sel 0 (out 1 scalar): 0 -> "userspace monitoring disabled", 0x100009bb0, sleep 2, exit(0); nonzero -> "userspace monitoring enabled", normal operation.
  - **Image v4 (JOURNALED):** `tools/mkiosroot.sh` now does `mkfs.hfsplus -J`, mounts with `-o loop,force`, adds the /System/Library/Caches/com.apple.dyld hard links (44) and /private/var/keybags/systembag.kb (0700/0600 root). Built from the IPSW dmgs (OS 087-86698-044, SystemOS 087-86593-047, AppOS 087-86715-047) -> `/run/media/dipa/android/ios-sweet-ipsw/ios16-root-20H392-v4.img` SHA256 fba4aeae...ec0f9 + `.simg`. Header: attr 0x80002100 (unmounted, journaled), journal info block 129, journal 8 MiB at 532480 flagged need-init. Linux `fsck.hfsplus -n` reports "Volume header needs minor repair" on any fresh journaled volume even after -y (quirk). QEMU: 64 MB journaled test root (`rd=md0 rootrw=1`, 0042 kernel): `hfs: Initializing the journal (joffset 0x3000 sz 0x80000)` -> mounted -> init runs, no panic. NEXT: flash v4 (full), boot 0042u.
- **SPRINGBOARD STARTS (boot 0041u 18:39:53 UTC, photo IMG_20261016_204142).** backboardd, bluetoothd, fairplayd.H2, SpringBoard (pid 111, crashed: "Too many corpses"), xpcproxy run; `SWEET AKS: backboardd sel 0 -> 0`, `sel 17 in 1/0 out 0/4096 -> 0`. Panic: watchdogd[113] exited, namespace 2 subcode 5 (SIGTRAP = its _os_crash): watchdogd crashes on purpose when IOServiceGetMatchingService("IOWatchdog") fails ("connect_to_kext() unexpectedly failed") or IOServiceOpen(type 1) fails ("IOServiceOpen failed with error"); IOWatchdog DOES register (QEMU msgbuf: `SWEET WDT: IOWatchdog registered`), cause not on screen yet -> need video. Note `wdt_test=no_user_checkin` makes watchdogd log "detected testing boot-args to not run, exiting" (path not reached here?). **HFS CORRUPTION:** `hfs_swap_BTNode: offset #0 invalid (0xBC1D) (blockSize 0x2000 numRecords 81)`, `node=19677 fileID=4` (catalog), `hfs_mark_inconsistent` repeated. Likely cause: non-journaled HFS + unclean panics while writing (0038e wrote a 2.7 GB core then panicked; every boot since ends in panic). Plan: reflash v3 (clean), longer term HFS journaling. Patch **0042**: one short `exec NAME` console line instead of the 3-line "Allowing spawn of iOS binary" notice; CI `38949451276` -> `xnu/out-0042`; image `shim/out/shim-boot-0042u.img` (same cmdline as 0041u).
- **LAUNCHD DAEMONS RUN (boot 0039u, 18:29:13 UTC, photo IMG_20261016_203052).** With `launchd_unsecure_cache=1` all boot tasks pass and launchd starts LaunchDaemons (pids > 100: identityservicesd 114 and lockdownd 106 crash, "Too many corpses being created"). Fatal: `watchdogd: ERROR: failed to discover watchdog KEXT service` -> exit (namespace 2 = signal, subcode 5) -> `_PanicOnCrash` panic. watchdogd: IOServiceMatching("IOWatchdog"), IOServiceOpen type 1, IOConnectCallScalarMethod sel 0/1 (check in)/3/4 (disable/enable userspace monitoring)/5, IOConnectCallStructMethod sel 2 (1 KiB in) and 9 (small out); VM path ("detected virtual machine environment and no watchdog KEXT found, exiting...") only when it detects a VM. Console also flooded with `hfs: set hardlink bit on vol=iOSRoot cnid=321318` (Linux-made hard links lack kHFSHasLinkChainBit; repaired only in memory on each lookup). Patches **0040** (`iokit/Kernel/arm/SweetWatchdog.cpp`: IOWatchdog + IOWatchdogUserClient, all selectors succeed with zeroed outputs, each logged once as `SWEET WDT: ...`) and **0041** (sweet_hfs hfs_catalog.c: the three link-repair printfs limited to 8 per boot); CI `38948245372` PASSED -> `xnu/out-0041` (QEMU regression OK). Image `shim/out/shim-boot-0041u.img` (0041 + sweet-0038hi.adt + ufsrw rootrw + launchd_unsecure_cache=1) booted 18:39:53 UTC (`research/boot0041u.log`), photo pending.
- **v3 FLASHED + keybag passes; next wall AMFI (launchd_cache_loader).** User said "flash, nothing to lose": `fastboot -S 512M flash userdata ios16-root-20H392-v3.simg` 17:51:52-17:57:01 UTC, 24/24 chunks OKAY (`research/flash-userdata-v3.log`). userdata = v3 (SHA256 fa84274c...22df) until the next rw boot. ABL fastboot then hung ("Sending" forever, `reboot bootloader` timed out) until the user re-entered fastboot by hand (common Xiaomi ABL crash). Boot 0038e 18:06:15 UTC (`research/boot0038e-3.log`), photos IMG_20261016_200812/200838: keybag OK, then boot tasks tzinit (`Bad zoneinfo link`, resets to system partition, OK), finish-restore, finish-demo-restore, sysstatuscheck, prng_seedctl (`failed to load kernel prng seed`, `failed to load virtual random (-147)`, AllowCrash), auearlyboot, then **launchd_cache_loader: `abort: Unable to find AMFI`** -> 2.7 GB core written to /cores in 91 s -> launchd panic `launchd_cache_loader[22] exited -- exit reason namespace 7 subcode 0x1`. launchd_cache_loader: SecStaticCodeCheckValidity of /System/Library/xpc/launchd.plist with detached .sig, then IOServiceMatching("AppleMobileFileIntegrity") + IOServiceOpen type 0 + IOConnectCallMethod sel 6 (1 scalar = 1, struct in = cdhash) = trust the cdhash, then sends the cache to launchd. Boot-arg `launchd_unsecure_cache=1` skips signature + AMFI ("Using unsecure cache"); the value is parsed with strtoul base 10 (helper 0x100002da8), so a path = 0 = off: boot 0039w (18:17:13 UTC, `=/System/Library/xpc/launchd.plist`, photo IMG_20261016_202008) still aborted `Unable to find AMFI` (core dump now skipped: `Failed to generate core file ... error 14`, so 0039 works). Image `shim/out/shim-boot-0039u.img` uses `launchd_unsecure_cache=1`. Patch **0039**: do_coredump = 0 on SWEET (kern.coredump sysctl still works); CI `38945267341` -> `xnu/out-0039` (_do_coredump now in __common). Image `shim/out/shim-boot-0039w.img` = 0039 + sweet-0038hi.adt + ufsrw rootrw + `launchd_unsecure_cache=/System/Library/xpc/launchd.plist`. TODO later: real AppleMobileFileIntegrity IOService (sel 6 trust cdhash etc.).
- **Image v3 ready, awaiting user "flash".** Boot 0038w 17:38:10 UTC, photo (chat image 30): `SWEET AKS: keybagd sel 0 -> 0x0`, `sel 14 out 1/0 -> 0x0` (x2), `MKB_INIT: mount is with NO CPROTECT ... does not support Data Protection`, `System Keybag loaded`; then keybagd still opens /private/var/keybags/systembag.kb (0x100012d3c, for BackupKeyBagKeys) -> ENOENT, `no-effaceable-storage` not set -> `Can't load the keybag. tears in rain... Time to die` -> `FATAL KEYBAG ERROR: kb_load` -> reboot -> Halt/Restart Timed Out panic. Fix: ADT `/defaults/no-effaceable-storage` (mkadt.py; `shim/out/sweet-0038hi.adt`, `research/q0038-hi.adt`, QEMU OK) + file `/private/var/keybags/systembag.kb` (0600 root, dir 0700; XML plist {KeyBagKeys: data}). **v3 image** `/run/media/dipa/android/ios-sweet-ipsw/ios16-root-20H392-v3.img` = v2 + that file, fsck OK, SHA256 fa84274c...22df; `ios16-root-20H392-v3.simg` (img2simg: zero blocks become FILL chunks, so a full flash overwrites every block the rw boots changed). Flash: `fastboot -S 512M flash userdata ios16-root-20H392-v3.simg`, then boot `shim/out/shim-boot-0038e.img` (0038 + sweet-0038hi.adt + ufsrw=1 rootrw=1).
- **0038 AppleKeyStore (CI 38938744130 PASSED -> `xnu/out-0038`; QEMU msgbuf: `SWEET AKS: AppleKeyStore registered (no passcode, unlocked)`; phone image `shim/out/shim-boot-0038w.img` booted 17:38:10 UTC, `research/boot0038w.log`, photo pending).** QEMU full kernel log trick (fb.txt is only the last screen): `llvm-nm KERNEL | grep _msgbufp` -> `--hmp "x /1gx ADDR"` gives struct msgbuf address (static, 0xfffffe0007b56678 on 0038) -> `--hmp "x /3gx STRUCT"` gives bufc (3rd quad) -> `--hmp "memsave BUFC 0x20000 \"FILE\""` (quote the file name), `tr -d "\0" < FILE`. Same inputs give the same addresses. Boot 0037w 17:08:35 UTC, photo IMG_20261016_191052: bindfs fixed mount; mount-phase-1/2 pass; `cc_fips_test` boot task: all corecrypto FIPS POST tests PASSED in userspace; then keybag boot task `keybagd --init`: `MKB_INIT: FATAL KEYBAG ERROR: failed to load system bag`, `Could not get options entry from the device tree` (x2, IODeviceTree:/options = NVRAM, non-fatal), `REBOOTING INTO RECOVERY MODE` -> reboot -> panic `Halt/Restart Timed Out @IOPlatformExpert.cpp:884` (no restart path on SWEET).
  - keybagd (static libaks): load_devicebag (0x100012c30) calls aks_get_system (sel 14, 0-1 scalar in, 1 out) and loads /private/var/keybags/systembag.kb only if the result is 0xe00002f0 (NotFound); any other error -> fatal; SUCCESS -> skip the file (userspace-reboot path). systembag.kb is a plist {KeyBagKeys}; decrypted with effaceable storage unless IODeviceTree:/defaults has `no-effaceable-storage`. Image has no /private/var/keybags. has_data_protection: statfs of /private/var; no cprotect on our HFS -> device-bag volume mapping skipped.
  - libaks connection: IORegistryEntryFromPath / IOServiceMatching("AppleKeyStore"), IOServiceOpen type 0, then selector 0 (no args) must succeed.
  - **AppleKeyStore selector map (iOS 16.7 AppleKeyStore.framework, via `ipsw dyld disass`):** 0 open, 2 create_bag, 3 save_bag, 4 unload_bag, 5 set_system_with_passcode, 6 load_bag, 7 get_lock_state (1 in, 1 out; bit 2 = unlocked since boot), 9 unlock_device, 10 wrap_key, 11 unwrap_key, 12 unlock_bag/test_stashed_kek, 13 lock_bag, 14 get_system, 15 change_secret_se, 16 internal_state, 17 get_device_state (1 in, struct out <=4K: DER SET of SEQUENCE{UTF8 key, INTEGER}: ss state, sls lock_state (MKBGetDeviceLockState returns it), sb backoff, sbo, sfa failed attempts, sfao, sgs generation, sas assertions, sgpe grace, srcd countdown, sr reserved), 18 recover_with_escrow_bag, 19 obliterate_class_d, 20 drain_backup_keys, 21/22 set/clear_backup_bag, 23 get_bag_uuid, 24 rewrap_key_for_backup, 26/27 assert_hold/drop, 30/31 set/get_configuration, 33-37 stash, 38 auth_token_create, 40 generation, 41 fdr_hmac_data, 42 verify_password, 43 _aks_operation, 44 remote_session, 49/50 signing keys, 51/53/54 stash enable/persist/escrow, 55 unload_session_bags, 57/58 remote peer, 59-62 smartcard, 63 migrate_s_key, 65 set_keybag_for_volume_with_cookie_persona, 66/67 sync bags, 68 copy_volume_cookie_persona, 69-73 se_*, 74-79/84/85/99 fv_* (FileVault/VEK), 80/81 absinthe, 82 make_public_backup_bag, 83 drop_auxiliary_auth, 86 kext get/set options, 87 invalidate_bag, 88-91/94/95/106/107 se_*, 92 lower_iteration_count, 93 get_internal_info, 96-98/117 keybag_persona create/list/delete, 100/101 assert promote/consume, 102/103 notify_state set/is_set, 104 fairplay, 105 change_secret_epilogue, 108 delete_xart_leak, 110-113 backup volume, 114 sealed_hashes_set, 115 prewarm_sps, 118-128 AKSIdentity*/AKSGetLastUser.
  - Patch **0038**: `iokit/Kernel/arm/SweetKeyStore.cpp` (class AppleKeyStore on IOResources, IOUserClientClass AppleKeyStoreUserClient; personality in KernelConfigTables.cpp): 0/4/5/9/12/13/26/27/55/102 success, 14 -> handle 0, 7 -> 0x4, 17 -> DER state (ss 4, sls 0), others kIOReturnUnsupported; logs `SWEET AKS: <proc> sel N arg0 in a/b out c/d -> ret` for every call.
  - Tools: shared cache copied to `research/dsc/` (git-ignored; ipsw needs a writable dir for its .a2s symbol cache); `ipsw dyld disass research/dsc/dyld_shared_cache_arm64 --image AppleKeyStore|MobileKeyBag`; scratchpad `annot2.py BIN DIS FIXUPS` annotates llvm-objdump output with strings and import names (`ipsw macho info --fixups`).
- **0037 bindfs (phone boot 0037w pending photo).** Boot 0036mw 16:57:47 UTC, photo IMG_20261016_190102: WRITABLE ROOT WORKS: `/dev/ufsroot0 on / (hfs, local, noatime)` after mount_hfs update (GetMasterBlock EBUSY harmless), coredump of mount written to /cores (rw). Then `mount: failed to mount /private/preboot/5CBE3601.../usr/standalone/firmware -> ...: Operation not supported by device (19)` -> exit 74 -> launchd panic `mount[2] exited`. Cause: the macOS-derived config had nullfs but no bindfs (ENODEV = unknown fs type). Caller passes env 0 -> bind not required, ENOENT (missing source dir) tolerated. Patch **0037** adds `bindfs` to FILESYS_BASE in MASTER.arm64.sweet; CI `38936550483` -> `xnu/out-0037` (bindfs_vfsops present; QEMU probe regression OK). Image `shim/out/shim-boot-0037w.img` (0037 + sweet-0036hi.adt + ufsrw=1 rootrw=1) booted 17:08:35 UTC (`research/boot0037w.log`). NOTE: userdata has now been modified by rw boots; it no longer equals the v2 image, so sparsediff with v2 as OLD is not safe any more (full reflash or a new baseline needed).
- **0036 phone: launchd boot tasks run; mount -P 1 needs /chosen/boot-manifest-hash.** Boot 0036hr 16:15:32 UTC, photo IMG_20261016_185236: platform check passes; fsck boot task runs (`fsck: not booting main or diagnostic OS. Skipping fsck on OS container`); mount-phase-1: `failed to get filesystem info` x2 (no IODeviceTree:/filesystems/fstab, non-fatal), `mount: data volume missing, but not required in env: 0`, mount_hfs update of /: `GetMasterBlock: Error 16 opening /dev/ufsroot0` (EBUSY, mounted block dev, non-fatal) then mount() EROFS (read-only boot) -> `mount: / failed with 1`; then `failed to get boot-manifest-hash` -> errx exit 66 -> launchd panic `mount[3] exited`. /sbin/mount: fn 0x100005f90 reads IODeviceTree:/chosen boot-manifest-hash (hex), bindfs-mounts /private/preboot/<HEX>/usr/standalone/firmware (ENOENT tolerated unless required). `tools/mkadt.py` now adds `boot-manifest-hash` = SHA-384("sweet boot manifest") (5CBE3601...5205). ADTs `shim/out/sweet-0036hi.adt`, `research/q0036-hi.adt` (QEMU probe OK, csops 0x26000001). Image `shim/out/shim-boot-0036mw.img` (0036 + new ADT + ufsrw=1 rootrw=1), booted 16:57:47 UTC (`research/boot0036mw.log`): FIRST WRITABLE BOOT of userdata (restore source: v2 image on SSD).
- **0036 CS_SIGNED (phone boot 0036hr pending photo).** Phone boot 0035hr 2026-10-16 15:57:02 UTC (`research/boot0035hr.log`, photo IMG_20261016_180249): highmem works on hardware; shared cache maps (trust-cache warnings only), Apple launchd runs (`Darwin Bootstrapper Version 7.0.0`, `entering ondemand mode`), starts boot task fsck, then userspace panic `boot task is not a platform binary (fsck, /sbin/fsck)`. launchd+0x3fea0: `csops(pid, CS_OPS_STATUS)` must have bit 0x04000000. Cause: nothing set CS_SIGNED (AMFI does it in vnode_check_signature), so csproc_get_blob() returns NULL for every process and csops never reports CS_PLATFORM_BINARY (also breaks per-process cdhash/entitlement queries). QEMU probe init (`csops` status printer, scratchpad csq/) on 0035: `0x02000001`; patch **0036** (`*cs_flags |= CS_SIGNED` in the SWEET AMFI hook), CI `38929635791` -> `xnu/out-0036`: `0x26000001`. Images `shim/out/shim-boot-0036hr.img` / `-0036hw.img` (same cmdlines as 0035). 0036hr booted 16:15:32 UTC (`research/boot0036hr.log`). Next launchd boot tasks (embedded __config plist): fsck -qL and mount -P 1/2 (RequireSuccess); no /etc/fstab on the image.
- **0035 ENTITLEMENTS + PLATFORM BINARIES (QEMU verified).** `xnu/patches/0035-sweet-amfi-entitlements-platform-binaries.patch`: new `iokit/Kernel/arm/SweetEntitlements.cpp` (OSObject subclass: OSDictionary from OSUnserializeXML of the signature's XML entitlements + original XML for CS_OPS_ENTITLEMENTS_BLOB); `bsd/kern/sweet_amfi.c` answers queryEntitlementBoolean/String(+WithProc, string also matches array members), copyEntitlementAsOSObject(+WithProc, retained), asdict (retained), get_xml (kalloc_data copy); built-in MAC policy "SWEET AMFI" (registered from bsd_init before vfs/exec) with mpo_vnode_check_signature: every signed binary on the MNT_ROOTFS mount gets CS_PLATFORM_BINARY (stand-in for AMFI's static trust cache: iOS system binaries are ad-hoc, cd_flags 0x2, platform byte 0), and attaches entitlements ONLY for the writable copy (cs_blob != csb_ro_addr; revalidation passes the RO blob). LESSON: first version attached in adjustContextWithoutMonitor -> QEMU `unable to adjust OSEntitlements context without monitor: 53` because ubc_cs_convert_to_multilevel_hash (4K-page signatures on 16K kernel) sets csb_entitlements_blob = NULL; ALL iOS 16 binaries (launchd, backboardd, SpringBoard) use 4K code pages, so this would have broken launchd on the phone. Boot-arg `sweet_amfi_debug=1` logs `SWEET AMFI: <ident>: N entitlements (test: ...)`. `tools/mkinit.py OBJ OUT [ENTS.plist]` adds an XML entitlements blob (special slot -5; default output byte-identical). QEMU `research/q0035-ent` (RAM disk `research/root-hfs-ent.img`, init with 3 test entitlements, highmem): `org.sweet.init: 3 entitlements (test: bool 1 string 1 array 1)` then init PID 1. MAC policies loaded: 0034 = 1, 0035 = 2 (QMP `mac_policy_list`). CI `38909807230` -> `xnu/out-0035`. Phone images: `shim/out/shim-boot-0035hr.img` (highmem, ro), `-0035hw.img` (highmem, +ufsrw=1 rootrw=1), `-0035r.img` (low mem fallback).
- **PHONE TEST ORDER (updated):** 0035hr -> if instant reset, 0035r -> then 0035hw.

- **HIGHMEM: XNU in the upper DDR bank, ~3.95 GiB (was 1.2 GiB).** Live FDT memory = <0x80000000 2G> + <0x1_00000000 0xfcc00000>; all fixed reserved-memory carve-outs are in the low bank (highest: ramdump_fb 0xaf000000, rmtfs ~0xfde01000), dynamic pools have alloc-ranges <= 0xffffffff, UFS node has no `iommus` (Linux DMAs anywhere). `tools/mkadt.py --highmem` sets /chosen dram-base 0x100000000 dram-size 0xfcc00000; `tools/mkpayload.py` now takes phys_base/mem_size from the ADT (default payloads byte-identical, verified); `tools/qemu-sweet.py` sizes -m from the payload (8G for highmem). Patch **0034** (`0034-sweet-ufs-dma-above-4g.patch`): UFS refuses DMA memory above 4G without UFSHCI CAP.64AS (bit 24), logs `DMA at 0x...`. CI `38905889883` success -> `xnu/out-0034`. **QEMU verified** (`research/q0034-hi`, ADT `research/q0034-hi.adt` --qemu --highmem, HFS RAM disk): phys_base 0x100000000, init PID 1 heartbeat, no panic; `max_mem` = `mem_size` = 0xfcc00000 read via QMP (`research/q0034-hi-mem`). Phone images: `shim/out/shim-boot-0034hr.img` (read-only) / `-0034hw.img` (+ufsrw=1 rootrw=1), ADT `shim/out/sweet-0034hi.adt` (asmb SIP + sweet-ufs + highmem). PHONE RISK: unknown runtime TZ/XPU protection in the upper bank would show as an instant reset; fall back to 0033r/w. Watchdog ruled out for the overnight reset: msm-watchdog bark is 20 s (qcom,bark-time 0x4e20) yet panic screens stay up for many minutes.

- **Offline research 2026-10-16 (user away, phone unavailable). Images rebuilt** `shim/out/shim-boot-0033r.img` / `-0033w.img` now also carry `wdt_test=no_user_checkin`. NEXT ON PHONE: boot 0033r (expect past in6_nigroup), then 0033w (first writes: rw root fixes HFS link-chain bits itself and gives /var for launchd sockets /var/run/syslog, /var/run/lockdown.sock).
- **launchd.plist** (`/System/Library/xpc/launchd.plist`, compiled; 532 daemons, 66 RunAtLoad/KeepAlive, list in scratchpad `early-daemons.txt`). `_PanicOnCrash` daemons: containermanagerd/usermanagerd (InternalOnly), lockdownd/remoted/trustd/remotepairingdeviced (AutomationOnly), **watchdogd unconditional** (KeepAlive SuccessfulExit=false). watchdogd needs IOKit `IOWatchdog` kext service; if absent it exits only when `kern.hv_vmm_present` (ADT `/defaults/vmm-present`, hvg_sysctl.c) or with boot-arg `wdt_test=no_user_checkin` ("detected testing boot-args to not run, exiting"; reads kern.bootargs). Using the boot-arg (vmm-present would change many daemons; keep as an option).
- **GUI path research (QuartzCore in the shared cache, `ipsw dyld str CACHE STR`, ~10 s/search):** CA::WindowServer has IOMFBServer/IOMFBDisplay (Apple DCP/IOMobileFramebuffer), AppleCLCDDisplay, AppleRGBOutDisplay, **VirtualServer/VirtualDisplay** and **MemorySurface**, EAGLServer. Renderers: CA::OGL::MetalContext, GLContext and a **CPU software rasterizer CA::OGL::SW** (samplers/blend modes; "image is too large for software renderer"). Env knobs: `CA_ENABLE_OGL`, `CA_DISPLAY_TYPE`, `CA_FORCE_LOCAL_SERVER` (249 CA_* vars). Hypothesis (unverified): backboardd's render server could run a VirtualServer/MemorySurface with the SW renderer and we copy the surface to the ABL framebuffer -> needs disassembly of CA::WindowServer server creation. Expected other GUI walls: IOSurface (closed-source kext; needs a reimplementation), IOMobileFramebuffer user client, IOHID touch events, AppleKeyStore/keybag (SEP) for lock state, MobileGestalt answers (AppleCLCD etc.).

- **0032r RESULT (boot 05:07:50 UTC, `research/boot0032r.log`, photo IMG_20261016_071200): SHARED CACHE MAPPED, LAUNCHD RUNS.** With SIP relaxed (ADT asmb) the `not in trust cache` lines are only warnings for every subcache (.31 ... .42.dyldlinkedit); no SIP rejection; libSystem loads; launchd configures networking (`skip attaching fsw to lo0 using legacy TX model`) -> kernel data abort far 0x28 in `SHA1Init` (symbolized as sha1_init) from `in6_nigroup` (IPv6 on lo0): g_crypto_funcs NULL. Kernel addresses are unslid: `~/swift/usr/bin/llvm-symbolizer --obj=KERNEL ADDR` works directly.
- **0032** BearSSL SHA-1 (`0032-sweet-bearssl-sha1.patch`), **0033** BearSSL SHA-384/512 (`0033-sweet-bearssl-sha384-sha512.patch`, BearSSL ctx stored in SHA512_CTX, static-asserted to fit; ubc_subr.c uses SHA-384 for code directories). `0020-stage-bearssl.sh` now also stages hash/sha1.c, hash/sha2big.c, codec/{dec,enc}{32,64}be.c. CI `38854909053` success (0032-only run `38854802073` superseded). Kernel `xnu/out-0033` (SHA1Init -> _br_sha1_init verified by disassembly; nm symbols have a leading underscore). Images (ADT sweet-0032): `shim/out/shim-boot-0033r.img` (read-only), `shim-boot-0033w.img` (+ufsrw=1 rootrw=1). Still NULL g_crypto_funcs users: des, chacha20poly1305, rsa, aesxts, rand, flow_divert.
- `research/check-patch-order.py` now skips patches touching CI-staged sweet_hfs sources (0031) instead of stopping.

- **0031r RESULT (boot 05:03:52 UTC 2026-10-16, `research/boot0031r.log`, photo IMG_20261016_070508): SHARED CACHE FOUND.** dyld now opens `dyld_shared_cache_arm64` (v2 image hard links), kernel refuses to map it: `shared_region: ... map(...'dyld_shared_cache_arm64'): not in trust cache` -> `vnode is not SIP-protected` (vm_unix.c: macOS arm64 path needs trust cache, else root-owned + SF_RESTRICTED unless CSR_ALLOW_UNRESTRICTED_FS) -> `dyld cache '(null)' not loaded: syscall to map cache into shared region failed` -> libSystem not loaded -> coredump to /cores fails error 30 (EROFS) -> panic initproc failed -> "MACH Reboot" (spins; screen kept). Lots of `hfs: set hardlink bit on vol=iOSRoot cnid=... linkid=...` spam (Linux-made hard links lack the link-chain bit; read-only mount cannot persist the fix). FIX: ADT `/chosen/asmb` with `lp-sip0`=0x6f (u64; incl. CSR_ALLOW_UNRESTRICTED_FS) and `lp-sip1`=1 (unauthenticated root), `tools/mkadt.py` -> `shim/out/sweet-0032.adt`. Images with kernel 0031: `shim/out/shim-boot-0032r.img` (read-only) and `shim-boot-0032w.img` (+ufsrw=1 rootrw=1).

- **2026-10-16 morning:** userdata now = **v2** image (`diff-v1-v2.simg` flashed 21:06:50 UTC 2026-10-15, OKAY, `research/flash-userdata-diff-v2.log`); future diffs use `ios16-root-20H392-v2.img` as OLD. Booted `shim-boot-0029k.img` (ignition_level=1) right after (`research/boot0029k-v2.log`); **no photo** (user asleep). Next morning the phone was in PixelOS recovery = some hardware reset (ABL then booted Android, which cannot use userdata). OBSERVATION: our kernel cannot reset the SoC itself (`PE_halt_restart` is never set; reboot/halt print "MACH Reboot"/"CPU halted" and spin), so the reset came from outside XNU: Qualcomm watchdog or a TZ/XPU violation. Unknown which; re-boot 0029k and watch/video until the reset. Do NOT tap factory reset/format data in recovery (would wipe the iOS image).
- **0030** (`xnu/patches/0030-sweet-ufs-writes.patch`, CI `38852655542`): UFS WRITE(10) + read-modify-write for partial 4 KiB blocks + SYNCHRONIZE CACHE (DKIOCSYNCHRONIZE), only with boot-arg `ufsrw=1`; `ufs_write_blocks` re-checks partition bounds before every write (only place data goes out).
- **0031** (`xnu/patches/0031-sweet-read-write-root.patch`, CI `38852837176`): boot-arg `rootrw=1` clears MNT_RDONLY before the root mount (no data volume on sweet: /private/var is on the root; image has no /etc/fstab); Apple HFS accepts a dirty non-journaled ROOT read-write on SWEET (logs "mounting dirty non-journaled root read-write"). Later: journaled HFS for crash safety. Kernel `xnu/out-0031` (CI `38852837176` success, 5m31s; 0030 run cancelled by the newer push). Boot images (phone ADT `sweet-0028.adt`, ramdisk byte-matched): `shim/out/shim-boot-0031r.img` = 0029k args (read-only, ignition_level=1) and `shim/out/shim-boot-0031w.img` = same + `ufsrw=1 rootrw=1`. PLAN: boot 0031r first and film until the reset (diagnose overnight reset), then 0031w (first ever writes to userdata; v2 image on the SSD is the restore source). `research/check-patch-order.py` cannot check 0031 (staged sweet_hfs files are not in its index); CI stage scripts run first, so CI is the check.

- **ignition_level=1 result** (boot 21:01:39 UTC, `research/boot0029k.log`, photo IMG_20261015_230308): preboot/cryptex stages skipped (need >= 2/3), `dylib_cache: finding shared cache on system volume: ignition level = 1, search root fd = 4, subpath = System/Library/Caches/com.apple.dyld/` -> not found -> `ignition boot failed: 19` -> no shared cache -> libSystem not loaded. FIX IN PROGRESS: image v2 = copy of the flashed image + `/System/Library/Caches/com.apple.dyld/` with HARD LINKS to the 44 cryptex cache files (no extra space; avoids symlink-following doubts), then `tools/sparsediff.py ios16-root-20H392.img ios16-root-20H392-v2.img diff.simg` and flash only the diff. Boot with `ignition_level=1` (shim-boot-0029k.img).
- **ignition_level=0 result** (boot 20:58:07 UTC, `research/boot0029j.log`, photo IMG_20261015_230037): all stages skipped as "ignition level insufficient" (hello/preboot/cryptex1 sniff >= 2, select os cryptex path/graft >= 3, **dyld_cache >= 1**), `ignition boot failed: 89`, "ignition partially disabled", then same `Library not loaded: /usr/lib/libSystem.B.dylib (no such file, no dyld cache)`. => dyld gets the shared cache directory from ignition's dyld_cache stage. Next: `ignition_level=1` (`shim/out/shim-boot-0029k.img`) to skip preboot/cryptex stages but run dyld_cache; its log "finding shared cache on %s ... subpath = %s" will show where it searches. If it searches rootfs /System/Library/Caches/com.apple.dyld, add a symlink there (image rebuild; consider a diff-only sparse flash tool to avoid rewriting 12 GB).
- **APPLE dyld/launchd RUNNING (libignition) with `unentitled_ios_sim_launch=1`** (boot 20:53:24 UTC, `research/boot0029i.log`, photo IMG_20261015_225617): kernel prints "Allowing spawn of iOS binary ... boot-arg set to true"; `shared_region: ... check_np ... vm_shared_region_start_address() failed` (no region yet, normal); dyld's built-in **libignition** (Darwin Ignition Sequence 1.0.0, libignition-51~1974; prints rd=ufsroot0, hardware target sweet, ignition level 0x5, platform 0x2, boot spec local, 7 stages): `hello from launchd.1` -> `preboot: mounting preboot` -> `failed to lookup preboot: 25` (ENOTTY: looks for a separate Preboot volume by role) -> ignition fails -> dyld `Library not loaded: /usr/lib/libSystem.B.dylib ... (no such file, no dyld cache)` -> launchd exit -> panic initproc failed. dyld boot-args found via strings: `ignition_level`, `ignition_force_dylib_root` (forced rootfs/livefs/cryptex fallback), `ignition_halt_after`, `ignition_live_app_graft`; dyld cache search paths include /System/Cryptexes/OS, /System/Volumes/Preboot/Cryptexes/OS/, /private/preboot/Cryptexes/OS/ (present in our image). Next try `ignition_level=0` (`shim/out/shim-boot-0029j.img`).
- **APPLE launchd EXECUTED FROM UFS (2026-10-15).** Flashed iOS image: `img2simg` -> `ios16-root-20H392.simg` (12.1 GB) then `fastboot -S 512M flash userdata ...simg` (24 chunks, 307 s, `research/flash-userdata-ios16.log`; a raw-image flash was killed by earlyoom at 2.6 GB RSS - always flash the sparse image). ABL fastboot hung on getvar after the flash; power+vol-down fixed it. Boot 0029u 20:49:04 UTC (`research/boot0029u-ios16.log`), photo IMG_20261015_225134: `hfs: mounted iOSRoot` -> load_init_program /sbin/launchd -> panic `unexpected SIGKILL of launchd (CS_KILLED) with reason -- namespace 9 code 0xe` = OS_REASON_EXEC / EXEC_EXIT_REASON_WRONG_PLATFORM: our kernel is XNU_TARGET_OS_OSX, iOS-platform binaries are "alien" and refused unless spawn attr platform set or DEVELOPMENT TUNABLE `unentitled_ios_sim_launch`. Next try: same kernel, cmdline + `unentitled_ios_sim_launch=1` (`shim/out/shim-boot-0029i.img`). LONGER TERM: macOS-config kernel marks iOS maps alien (vm_map_mark_alien) and differs from iOS in many policies; an iPhoneOS-config kernel build may eventually be needed.
- **iOS 16 ROOT IMAGE BUILT:** `/run/media/dipa/android/ios-sweet-ipsw/ios16-root-20H392.img` (16 GiB case-sensitive HFS+, label iOSRoot, 12 GB used, fsck OK after `fsck.hfsplus -y` rewrote 32 non-ASCII localized WorkflowKit Shortcut names Linux decomposes differently). Built by `tools/mkiosroot.sh OS.dmg SYSTEMOS.dmg APPOS.dmg OUT.img [SIZE]` (needs sudo; apfs-fuse as root; OS dmg is UDIF -> link must end .dmg). Contents: iPhone X 20H392 OS root + SystemOS cryptex at /private/preboot/Cryptexes/OS (so /System/Cryptexes/OS -> cache, 44 files, dyld_v1 arm64) + AppOS at .../App. /sbin/launchd and /usr/lib/dyld root:wheel 0755. NEXT: (confirm) `fastboot flash userdata ios16-root-20H392.img` (auto-sparse), boot 0029u (rd=ufsroot0) -> Apple launchd attempt.
- **MILESTONE ON HARDWARE: BOOT FROM INTERNAL FLASH.** 0029 CI `38797924912` PASSED, `xnu/out-0029` SHA256 `a68bc847...2a37`. Image `shim/out/shim-boot-0029u.img` (payload-0029u = 0029 kernel + `shim/out/sweet-0028.adt` + `rd=ufsroot0`, NO RAM disk). Boots 20:01:34 and 20:12:37 UTC (`research/boot0029u*.log`), photo IMG_20261015_221403: `SWEET UFS: "userdata" on LUN 0: first block 0x2b8c00, 109643 MiB, read-only` -> `BSD root: ufsroot0, major 1, minor 0` -> `hfs: mounted SweetRoot on device b(1, 0)` -> `SWEET: root volume is not authenticated (error 25); continuing unsealed` -> `load_init_program ... /sbin/launchd` -> `*** SWEET userspace: init running as PID 1 ***` -> heartbeat (ran for minutes unattended). userdata currently holds the 8 MB `research/root-hfs.img`. NEXT: build a multi-GB HFS+ image with the iOS 16 (iPhone X 20H392) userland (OS rootfs + SystemOS cryptex contents incl. dyld shared cache at /System/Library/Caches/com.apple.dyld; preserve modes/owners/symlinks; decompress LZBITMAP via apfs-fuse), flash it to userdata (sparse, needs user OK), then try Apple's dyld/launchd. Driver is read-only (root mounts RDONLY), fine for first launchd attempts.
- **userdata FLASHED with the 8 MB HFS test volume** (user said "flash it", 2026-10-15 19:53:17 UTC, `research/flash-userdata-hfs-test.log`: `fastboot flash userdata research/root-hfs.img` OKAY; pre-checks: one sweet device, partition-size:userdata 0x1AC4BFB000, partition-type f2fs, image fsck OK, SHA256 3626ea69...). Android userdata is now destroyed (expected/approved). Boot 0028u at 19:53:20 (`research/boot0028u-hfs.log`), photo IMG_20261015_215541: `BSD root: ufsroot0` -> **`hfs: mounted SweetRoot on device b(1, 0)` from internal UFS** -> panic `rootvp not authenticated after mounting @bsd_init.c:931` (arm64 macOS-config requires FSIOC_KERNEL_ROOTAUTH sealed root for non-ramdisk roots). Patch **0029** (`dd1c284`): SWEET logs `SWEET: root volume is not authenticated (error N); continuing unsealed` instead of panicking (Apple configs keep the panic; pivot_root still requires auth). CI **`38797924912`** running. Next: download out-0029, phone image with sweet-0028.adt + rd=ufsroot0 (no RAM disk), boot -> expect init from UFS.
- **UFS ROOT DRIVER VERIFIED ON HARDWARE (read-only).** 0028 CI `38796139570` PASSED, `xnu/out-0028` SHA256 `8b981640...9da6`; QEMU HFS RAM-disk regression `research/q0028-hfs` still runs init. Phone boot 2026-10-15 19:50:24 UTC (`research/boot0028u.log`, image `shim/out/shim-boot-0028u.img`, phone ADT `shim/out/sweet-0028.adt` with /sweet-ufs, NO RAM disk, `rd=ufsroot0`), photos IMG_20261015_215151/215220: `SWEET UFS: "userdata" on LUN 0: first block 0x2b8c00, 109643 MiB, read-only` -> `BSD root: ufsroot0, major 1, minor 0` -> `hfs_ValidateHFSPlusVolumeHeader: unknown Volume Signature : f188` (Android-encrypted data, as expected) -> `cannot mount root, errno = 19`, kernel retries mountroot (no panic). Nothing written to flash. NEXT (destructive, needs user confirmation right before): `fastboot flash userdata research/root-hfs.img` (8 MB HFS with test init) then boot rd=ufsroot0 -> expect init from internal flash.
- **PATCH 0028 (`33aceac`): XNU read-only UFS root device**, CI **`38796139570`** running (next artifacts xnu/out-0028, research/bt29, run29.log). `bsd/dev/sweet_ufs.c`: reuses ABL's UFSHCI state (like the shim probe), takes over UTRL at a kmem_alloc_contig region (DMA layout: UTRL 0x0, UCD 0x1000, 1 MiB bounce 0x4000), verifies UTRLBA readback before any doorbell, IE=0 polled, one SCSI cmd at a time on LUN0 (TUR x3, READ(10) via bounce, PRDT 256 KiB chunks), flush_dcache64 by PA around each command (host not dma-coherent per DT), finds GPT partition by name (`ufsroot=` boot-arg, default `userdata`), exposes `/dev/ufsroot0`/`rufsroot0` (512-byte logical sectors, physical 4 KiB, DKIOC* ioctls), refuses writes (EROFS). IOKitBSDInit: `rd=ufsroot0` -> sweet_ufs_rootdev() (lazy init) else panic. ADT: `tools/mkadt.py` adds `/sweet-ufs` reg <0x1d84000 0x3000> for the PHONE only (not --qemu). Local compile OK, imports resolve. Sandbox research/bt28 (pre0028 originals). FIRST PHONE TEST PLAN (non-destructive): boot 0028 with phone ADT + `rd=ufsroot0` and NO RAM disk: expect `SWEET UFS: "userdata" on LUN 0: first block 0x2b8c00, 109643 MiB` + `BSD root: ufsroot0`, then root mount failure (userdata is still Android-encrypted) -> panic. That validates the driver before flashing an HFS image into userdata (needs explicit user confirmation at that time).
- **SUPERSEDES the 64 GiB iosroot GPT plan: user said "u can delete android" (2026-10-15).** Use the existing `userdata` partition (LUN0 sda34, 4K LBA 0x2B8C00, 0x1AC4B MiB ~107 GiB) directly as the iOS root: NO GPT changes. Keep bootloaders, recovery (OrangeFox), modem/persist/fsg/modemst untouched. Write the HFS image later with `fastboot flash userdata` (sparse, auto-split under the 768 MiB limit). Android will no longer boot normally (expected; reinstallable). Order: XNU UFS driver first, read-only against the current GPT; flash only once it can locate userdata. Nothing erased yet.
- **DECIDED (user, 2026-10-15): 64 GiB `iosroot` on LUN0 (sda), taken from userdata (wipes Android user data; Android/super kept).** Planned GPT (4K LBAs): userdata 0x2B8C00..0xD7D6FF (~43 GiB, keep type/unique GUIDs and attributes); iosroot 0xD7D700..0x1D7D6FF (0x1000000 blocks = 64 GiB, 1 MiB aligned); backup GPT area unchanged. Procedure: user backs up phone data -> boot OrangeFox recovery (adb) -> back up GPT (sgdisk --backup + raw dd of LBA 0-5 and last 6 blocks) to research/ -> sgdisk edit -> Format Data -> verify Android boots to setup. NOT EXECUTED YET.
- **INTERNAL UFS WORKS FROM THE SHIM (read-only), user authorized internal-UFS approach incl. flashing (2026-10-15, "i allow everything").** Shim probe `shim/ufs.c` (commit `12ed3ed` + filter): ufshc@1d84000 is UFSHCI 2.1 (ver 0x210, cap 0x1587031F, 32 slots), ABL leaves HCE=1, HCS=0x10F (device present, lists ready, UIC ready); probe takes over UTRL at its own buffer (verifies UTRLBA readback before any doorbell), TEST UNIT READY/READ CAPACITY/READ(10) all succeed. LUN0 = 0x1D7D800 x 4 KiB (~126.6 GB), valid GPT (64 entries at LBA 2). Photos IMG_20261015_212916/213325/213429. Big LUN0 partitions (start in 4K LBAs / MiB): super 0xCA00/0x2200 (8.5 GiB), logdump 0x22CA00/64, minidump 0x230A00/128, rawdump 0x238A00/128, recovery 0x240C00/128, cache 0x248C00/384 ext4, exaid 0x260C00/384, cust 0x278C00/1024 ext4, **userdata 0x2B8C00/0x1AC4B MiB (~107 GiB), fs unreadable = encrypted (metadata encryption)**. cache..cust contiguous = only 1.75 GiB (too small for iOS ~10+ GiB). Plan needing user consent: shrink userdata in GPT (wipes Android data) and add an `iosroot` partition at the end of LUN0. LUNs 1-5 not listed yet (sdb..sdf backed up in backup/lun).
- **fastboot limit measured (2026-10-15, read-only getvar):** `max-download-size: 805306368` (768 MiB); `max-fetch-size` unsupported; `is-userspace: no` (ABL fastboot). A `fastboot boot` image (shim+kernel+RAM disk) must be < 768 MiB, so the 2.5 GiB iOS shared cache cannot ride in the boot RAM disk even if XNU gets all RAM. Real userland needs storage access (UFS driver, or USB host) or a much smaller cache. Unlocking full RAM is still needed later (GUI).
- **iOS 16 USERLAND SOURCE (Claude, 2026-10-15).** Chose **iPhone X (iPhone10,3/10,6, D22/D221AP)** iOS **16.7.16 (20H392)** over iPhone 8: same A11 (no PAC -> plain arm64, runs on Kryo 470/ARMv8.2), last iOS for A11; X userland is home-button-less and tall-screen (1125x2436 vs sweet 1080x2400), better fit for later GUI. Note the X has its OWN SystemOS cryptex (different digest from iPhone 8's). IPSW URL in `research/ipsw-x/URL.txt` (+ BuildManifest). Images on the user's external SSD (NOT in git, do not format that disk: it holds the user's photos): `/run/media/dipa/android/ios-sweet-ipsw/iPhone10,3_16.7.16_20H392/` — `087-86593-047.dmg` = Cryptex1,SystemOS (2,743,074,816 B), `087-86698-044.dmg` = OS rootfs (4,730,814,044 B), both zip CRC-32 verified, plus Firmware/*.root_hash/.trustcache/.mtree. AppOS cryptex is 087-86715-047.dmg (10 MB, same as iPhone 8).
  - Images are raw APFS; files use LZBITMAP (decmpfs type 14). 7z cannot decode. Tools: `ipsw` 3.1.738 (AUR ipsw-bin, user-approved) needs apfs-fuse on Linux; **apfs-fuse** built in user space (system cmake broken: cmake 4.4.4 wants libjsoncpp.so.27, jsoncpp 1.9.6 installed = partial upgrade, NOT fixed) with pip cmake + `-DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DCMAKE_CXX_FLAGS="-include cstdint"`, installed to `~/.local/bin/apfs-fuse` (+apfs-dump-quick). Mount via a comma-free symlink (apfs-fuse splits options on ',' in `iPhone10,3`; exFAT has no symlinks -> put link elsewhere): `apfs-fuse LINK/087-86698-044.dmg MNT` -> `MNT/root/...`; unmount `fusermount3 -u MNT`.
  - Verified from headers: `dyld_shared_cache_arm64` magic `dyld_v1   arm64`; `/sbin/launchd`, `/usr/lib/dyld` = cputype 0x100000c subtype 0 (plain arm64). libSystem exists only inside the cache.
  - **BLOCKER for real userland via RAM disk:** shared cache = 3.10 GiB in 44 files (~2.5 GiB without the 592 MB `.symbols`), but the kernel manages only 1.20 GiB (0xb0000000..0xfd000000). Options: (A) give XNU the phone's full ~6 GB (banks 0x80000000+2G and 0x100000000+0xfcc00000, carve-out holes need pmap support) AND check fastboot max-download-size for a multi-GB boot image; (B) storage driver (Qualcomm UFS) to read a root from flash (no flashing allowed: would need a file/partition strategy); (C) run against individual dylibs extracted from the cache (uncertain).
- **MILESTONE ON HARDWARE: HFS+ ROOT FILESYSTEM -> PID 1.** Boot 2026-10-15 18:22:12 UTC (`research/boot0027b.log`, image `shim/out/shim-boot-0027b.img`), photo `IMG_20261015_202334.jpg`: `BSD root: md0` -> `hfs: mounted SweetRoot on device b(1, 0)` -> `load_init_program: attempting to load /sbin/launchd` -> `*** SWEET userspace: init running as PID 1 ***` -> repeated `SWEET init: still alive`, no panic. Kernel 0027 (built-in Apple OSS HFS + BearSSL MD5), init with SP alignment fix. NEXT: real iOS 16 userland on the HFS image (dyld, libSystem/dyld shared cache, launchd). Known gaps: entitlements (none granted), SHA-1/SHA-384/512 providers, no storage driver (RAM disk only), root mounted read-only.
- **PHONE HFS ROOT (0027) + SIGBUS ROOT-CAUSED.** Phone boot 2026-10-15 17:49:06 UTC (`research/boot0027.log`, photo `IMG_20261015_200031.jpg`): `hfs: mounted SweetRoot on device b(1, 0)` (HFS works on hardware), init printed its first line, then `pid 1 exited -- exit reason namespace 2 subcode 0xa` = SIGNAL/SIGBUS -> `initproc failed to start` panic. Diagnostic boot 18:08:13 UTC (`research/boot0027d.log`, image `shim/out/shim-boot-0027d.img`, diag init `research/diag-init` from scratch diag-init.S with [a][b][c] markers, `cs_debug=1`; photo `IMG_20261015_201547.jpg`): output `PID [a][b]` then SIGBUS -> fault at first `strb w21,[sp]`; no code-signing messages. Cause: kernel enters a static binary with sp at argc, not necessarily 16-aligned (depends on arg/apple string lengths, differs mockfs vs HFS); EL0 SP alignment check -> EXC_ARM_SP_ALIGN -> SIGBUS (sleh handle_sp_align). QEMU does not enforce SP alignment. NOT a kernel bug: real binaries start in dyld which aligns. Fix `1a8fc15`: sweet-init aligns sp at entry. Rebuilt `research/root-hfs.img`, QEMU `research/q0027-hfs2` OK. Phone image `shim/out/shim-boot-0027b.img` SHA256 `098ba46c...c5c` (payload-0027b, ramdisk match check-0027b) ready, awaiting FASTBOOT. Lesson: Assembly `;` is a comment in Apple arm64 asm (use .macro, not ;-joined #define).
- **HFS ROOT WORKS (QEMU).** 0027 CI `38779441895` PASSED, `xnu/out-0027` SHA256 `a8643886...5f6a`. QEMU `research/q0027-hfs` (RAM disk = `research/root-hfs.img`, rd=md0): `BSD root: md0` -> `hfs: mounted SweetRoot on device b(1, 0)` -> `load_init_program: attempting to load /sbin/launchd` -> `*** SWEET userspace: init running as PID 1 ***` + heartbeat, no panic. Phone image `shim/out/shim-boot-0027.img` (payload-0027 = 0027 kernel + sweet-0021.adt + root-hfs.img + rd=md0, ramdisk byte-match check-0027) ready; awaiting FASTBOOT for phone test.
- **HFS ROOT WORK (Claude), patches 0026-0027.**
  - 0026 (`f0e990c` + link fix `64c96f4`): Apple OSS **hfs-627.100.6** (commit `31d5ec238dfab485e78a9a30b8b92d13e8914f03`, paired with xnu-8796.141.3 in macos-135 release.json) staged by `xnu/patches/0026-stage-hfs.sh` into `bsd/sweet_hfs` (core + hfs_encodings; AppleKeyStore include/key prototypes guarded by CONFIG_PROTECT; SDK TargetConditionals copied). New config option `sweet_hfs` (MASTER + MASTER.arm64.sweet); 40 `optional sweet_hfs` files; Makefile.template foreach adds `_CFLAGS_ADD = -include sweet_hfs_compat.h -I...` (MUST come after kernel -D flags; compat undefs BSD/XNU_KERNEL_PRIVATE and the CONFIG_* HFS tests so kext-config.h decides: macOS profile, no content protection). `sweet_hfs_iokit.c` replaces hfs_iokit.cpp/hfs_encodings_kext.cpp: `sweet_hfs_register()` called in bsd_init after vfsinit (encodings init, vfs_fsadd VFS_TBLCANMOUNTROOT, zones, sysctls); is_ejectable 0, iterate_media none, serial KERN_NOT_SUPPORTED, OSKextGetCurrentLoadTag -> kOSKextInvalidLoadTag (renamed via compat macro). hfs_encodings' own `hfs_allocated` renamed per object (separate kexts on Apple; first CI `38777325964` failed on that duplicate at link). mockfs now validates Mach-O magic (its TODO) so non-Mach-O roots fall through to HFS (new fs entries come AFTER mockfs in vfsconf). CI `38778133720` PASSED, `xnu/out-0026` SHA256 `0b49170c...701a`, prints `SWEET HFS: hfs-627.100.6 registered`.
  - HFS+ image: `research/root-hfs.img` (8 MB, mkfs.hfsplus from AUR hfsprogs installed with user approval; loop-mounted with sudo; /sbin/launchd = research/sweet-init, /dev; fsck.hfsplus OK). QEMU `research/q0026-hfs`: `BSD root: md0` then data abort in MD5Init from hfs_getvoluuid (mount computes volume UUID).
  - 0027 (`14bf2b7`): 0020 stager also copies BearSSL hash/md5.c + codec/dec32le.c/enc32le.c; `corecrypto_md5.c` SWEET branch converts MD5_CTX <-> br_md5_context around br_md5_* calls; wrappers sweet_md5.c/sweet_dec32le.c/sweet_enc32le.c. Host test 40/40 match md5sum. CI **`38779441895`** running.
  - Local tooling: `tools/xnu-cc.py` has `XNU_CC_POST` (flags after logged ones). Sandbox `research/bt28/xnu` = 0025 CI tree + 0026/0027 edits; originals `research/pre0026`, `research/pre0027`. HFS local objects `research/hfs-objs`. Checker entries updated to bt28.
  - SHA-1 / SHA-384/512 still have no provider.
- **MILESTONE ON HARDWARE: USERSPACE PID 1 RUNS ON THE PHONE.** Boot 2026-10-15 17:16:00 UTC (`research/boot0025.log`: send OKAY0.410s, boot OKAY0.135s), image `shim/out/shim-boot-0025.img` SHA256 `9dbfa0b1...89db0`. Photo `IMG_20261015_191733.jpg`: `BSD root: md0` -> `load_init_program: attempting to load /sbin/launchd` -> `*** SWEET userspace: init running as PID 1 ***` -> repeated `SWEET init: still alive` (5 s heartbeat), no panic. Kernel 0025 + mockfs RAM disk + built-in no-entitlements AMFI. No flashing performed.
- **NEXT (toward real iOS userland):** real root filesystem with real binaries. Options: (a) build Apple OSS `hfs` (macOS 13.5 tag `hfs-627.100.6`) into SWEET like libpthread, then an HFS RAM disk image; (b) iOS 16 dyld + libSystem/dyld shared cache from the IPSW (needs APFS or repacking onto HFS). Expected hurdles: entitlements (sweet_amfi grants none), SHA-1/MD5/SHA-384/512 providers (BearSSL), missing kexts/daemons. Current init is a static test program, not launchd.
- **MILESTONE: USERSPACE RUNS (QEMU).** 0025 CI `38774788048` PASSED, `xnu/out-0025` SHA256 `5496069b...4877`. QEMU `research/q0025-rd` (150 s, no panic): `BSD root: md0` -> `load_init_program: attempting to load /sbin/launchd` -> `*** SWEET userspace: init running as PID 1 ***` -> `SWEET init: still alive` every 5 s. Exec, ad-hoc SHA-256 code signature, syscalls, devfs /dev/console, select timeouts all work. Phone image prepared: `shim/out/shim-boot-0025.img` 16,515,072 bytes SHA256 `9dbfa0b15140c0bd733a16c4f727f6a7df44a8741f98d8e266d5f2fa4f689db0` (payload-0025 = 0025 kernel + sweet-0021.adt + research/sweet-init + rd=md0; ramdisk byte-match check-0025). Waiting for user to put phone in FASTBOOT.
- **0024 CI `38773277811` PASSED**, `xnu/out-0024` SHA256 `a0ba964b...4348`. QEMU `research/q0024-rd` and **PHONE (boot 2026-10-15 17:05:55 UTC, `research/boot0024.log`, image `shim/out/shim-boot-0024.img` SHA256 `cf3dac86...6964`, 16,510,976 bytes, payload `shim/out/payload-0024.bin` = 0024 kernel + `shim/out/sweet-0021.adt` + RAM disk `research/sweet-init` + rd=md0; ramdisk byte-match `check-0024`)** agree: `Added memory device md0`, `BSD root: md0`, `load_init_program: attempting to load /sbin/launchd`, then data abort in accelerate_entitlement_queries (PC 0x...77d2458, FAR 0x1a0) = NULL AMFI interface. Photo `IMG_20261015_190715.jpg`. RAM disk root is physically verified.
- **0025 (`2518c79`)**: new `bsd/kern/sweet_amfi.c` registers a built-in AMFI interface at EARLY_BOOT/MIDDLE: no entitlements (adjustContextWithoutMonitor succeeds without creating a context, queries KERN_DENIED, copies NULL/KERN_NOT_FOUND, get_xml/transmuted false); WithMonitor KERN_NOT_SUPPORTED; OSEntitlements_query and query_context_to_object panic explicitly (CoreEntitlements closed; no kernel caller); TrustCache version 0 (0015 keys on trust_cache_rt==NULL, img4 absent -> still unavailable); CoreEntitlements table zero (PMAP_CS only). Compiles locally; checker updated (bt27 entries). CI **`38774788048`** running. Next artifacts `xnu/out-0025`, `research/bt29`, `research/run29.log`. Real iOS binaries will need real entitlements later (no OSS CoreEntitlements exists).
- **0021-0024 RAM-disk-root iteration (Claude), QEMU only so far, no new phone boot since 0020.** Each kernel tested with `tools/mkpayload.py KERNEL research/q0021.adt OUT --ramdisk research/sweet-init --cmdline "debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress rd=md0"` then `tools/qemu-sweet.py OUT DIR --secs 150 --kernel KERNEL --fail-on-panic` (PATH needs ~/swift/usr/bin for llvm-nm). Fresh ADTs: `research/q0021.adt` (QEMU), `shim/out/sweet-0021.adt` (phone).
  - 0021 CI `38769532000` PASSED, `xnu/out-0021` SHA256 `2b7500a1...962e`, `research/bt25`/`run25.log`. QEMU `research/q0021-rd`: md0 root, then assert `iomediaClass` in IOService::publishHiddenMedia.
  - 0022 (`20ece9c`, publishHiddenMedia without IOMedia class) CI `38770666158` PASSED, `xnu/out-0022` SHA256 `a4d0e787...30c5`, `research/bt26`/`run26.log`. QEMU `research/q0022-rd`: data abort in SHA256_Init (NULL g_crypto_funcs) from vm_kernel_addrhash_internal.
  - 0023 (`c8089d1`, libkern SHA256_Init/Update/Final use built-in ccsha256_ltc_di + ccdigest_init/update on SWEET; also serves code-signing SHA-256; SHA-1/MD5/SHA-384/512 still have NO provider - BearSSL from 0020 could supply them later) CI `38771876423` PASSED, `xnu/out-0023` SHA256 `d763fed7...1003`, `research/bt27`/`run27.log`. QEMU `research/q0023-rd`: **mockfs mounted md0, `load_init_program: attempting to load /sbin/launchd`**, then panic `mockfs_fsnode_vnode failed to create fictitious pages ... rvalue = 5` (mockfs.c:351).
  - 0024 (`3293c80`): mockfs used memdev mi_base (4K page number of a VIRTUAL kernel address for IOKit RAMDisk, truncated to 32 bits) << PAGE_SHIFT as a physical address. Now zero-copy pager mapping only when mi_phys (with 4K units); virtual md uses pagein/blockmap/strategy -> memdev bcopy. memdev's own mdPhys path assumes 4K ppnums (unsafe on 16K arm64), so do NOT switch the RAMDisk to physical. CI **`38773277811`** running. Next artifacts `xnu/out-0024`, `research/bt28`, `research/run28.log`.
  - Sandboxes: bt25/bt26/bt27 contain the next patch's edited files; pristine copies in `research/pre0022`..`pre0024`.
- **PATCH 0021 (Claude): RAM disk root via mockfs -> first userspace program.** Commits `9c37771` (initial; CI `38768500280` FAILED: mockfs_fsnode.c kfree_type(mockfs_fsnode_t) typed-alloc static assert; local xnu-cc stubs `__builtin_xnu_types_compatible` so it can't catch this) and `193772f` (fix), CI **`38769532000`** running: https://github.com/dipa-studio/ios-sweet/actions/runs/38769532000. Next artifacts: `xnu/out-0021`, `research/bt25`, `research/run25.log`.
  - Kernel: `config/MASTER.arm64.sweet` FILESYS_BASE += `mockfs` (XNU's built-in FS: root device is itself a Mach-O, served as /sbin/launchd, plus /dev for devfs). Upstream mockfs bit-rot fixed: kalloc_type/kfree_type used the POINTER typedef mockfs_fsnode_t (nodes were 8 bytes) -> `struct mockfs_fsnode`. `IOService::setRootMedia` asserted IOBlockStorageDriver class exists (IOStorageFamily absent): SWEET-only, a missing class means root=NULL (same as IOSetImageBoot); Apple path keeps assert. All 21 patches apply (`research/check-patch-order.py`); 5 TUs compile locally with -DMOCKFS (`research/mockfs-objs`), imports resolve vs 0020 kernel. Sandbox `research/bt24/xnu` now holds 0021 versions of those 3 files; pristine 0020 copies in `research/pre0021`.
  - Tools: `tools/mkpayload.py --ramdisk IMAGE` appends IMAGE as an extra payload segment right after the kernel, moves kernel_end past it (shim unchanged: ADT+boot_args follow it, image stays below topOfKernelData), and adds ADT `/chosen/memory-map` `RAMDisk`=<phys,size>. Boot with `rd=md0`. Without --ramdisk output is byte-identical to existing 0020 QEMU and phone payloads (verified). `tools/sweet-init.S` + `tools/mkinit.py`: PIC static init (open /dev/console, print PID, heartbeat every 5 s via select, never exits) wrapped into a static arm64 Mach-O (__PAGEZERO, __TEXT@0x100000000, LC_UNIXTHREAD, ad-hoc SHA-256 CodeDirectory v0x20400, 4K pages). Build: `~/swift/usr/bin/clang -target arm64-apple-ios16.0 -c tools/sweet-init.S -o X.o && tools/mkinit.py X.o research/sweet-init` (ld64.lld cannot link static iOS). Signature not verified by a real codesign; the kernel will tell.
  - QEMU with 0020 kernel + RAM disk (`research/q0020-rd.bin`, rd=md0, 150 s `research/q0020-rd150`): `Added memory device md0`, **`BSD root: md0, major 1, minor 0`** (plumbing works), then the setRootMedia assert (now fixed in 0021). NOTE: QEMU needs >60 s to reach IOFindBSDRoot (60 s run showed nothing after stf0; likely RTC/inittodr wait), so use --secs 150.
  - NEXT: download 0021, QEMU 150 s with ramdisk; expect mockfs mount then init exec -> `*** SWEET userspace: init running as PID 1 ***`. Then phone boot with same payload (phone ADT shim/out/sweet-0020.adt pattern + --ramdisk + rd=md0).
- **0020 PHONE RESULT (user transcription of screen, 2026-10-15): KERNEL INIT COMPLETE, WAITING FOR ROOT.** After Skywalk self-tests PASSED, kminit, ifnet_attach lo0/gif0/stf0, screen prints `BSD`, then `Waiting on <dict><key>IOProviderClass</key><string>IOMedia</string><key>Content</key><string>Apple_HFS</string></dict>` and `Failed to write boot-picker-bringup-reason to NVRAM.` No panic. This is IOFindBSDRoot waiting for a root device (none exists); NVRAM warning is expected (no NVRAM driver). QEMU `cpu_idle` snapshot is presumably the same wait (not GDB-confirmed; milestone GDB run was cancelled by user since phone answered it). Draft `research/check-milestones20.gdb` (hbreaks inittodr/vfs_mountroot/IOFindBSDRoot/bsd_utaskbootstrap) left uncommitted/ignored.
- **NEXT MILESTONE: root filesystem -> launchd.** Plan: (1) RAM disk: shim places an image in RAM, ADT /chosen/memory-map `RAMDisk` entry, boot-arg `rd=md0` (XNU md driver). (2) HFS is a separate kext on Apple; build Apple OSS `hfs` (tag paired with macOS 13.5 in distribution-macOS macos-135 release.json) into SWEET like libpthread 0019. APFS is closed. (3) Minimal HFS image with iOS 16 launchd (later: dyld/shared cache; AMFI/code-signing absent will be a later hurdle). User's end goal is full iOS GUI.
- **0020 (AES) VERIFIED + PHONE BOOTED (Claude took over after Codex usage limit).** Actions `38765422261` (`ab9e23f`) PASSED; kernel `xnu/out-0020/kernel.development.sweet` checksum OK; buildtree `research/bt24`, log `research/run24.log`. Actual-kernel AES checks PASS (`research/check-aes20.gdb` / `.log`, 12 extra CBC cases match OpenSSL). 45s QEMU `research/q0020`: no panic, zero unknown glyphs, past old TCP/AES panic -> Skywalk self-tests PASSED -> bsd_autoconf kminit -> ifnet_attach lo0/gif0/stf0; final snapshot PC in `cpu_idle` (idle or waiting; NOT yet diagnosed, could be root-device wait). Image `shim/out/shim-boot-0020.img` 16,461,824 bytes SHA256 `775200cb02d95fc750981516b79d91dcdc96184bbe67a38f9d57c59b4a391828`, ramdisk byte-matches `payload-0020.bin` (`check-0020`). **Phone temporarily booted 2026-10-15 16:10:00 UTC**: one FASTBOOT product sweet, send OKAY0.407s, boot OKAY0.134s, total0.549s, exit0 (`research/boot0020.log`). Awaiting user photo; do not reboot the phone before it. NEXT: read photo; diagnose what QEMU waits on after stf0 (GDB backtrace of threads / longer run). Codex's STOP request below is complete.
- User requests STOP after completing the current0020 AES iteration (Actions/QEMU/phone), then leave a precise committed handoff for another AI. User says FASTBOOT ready again after0019 photo. Do not start a new blocker fix after this iteration.
- Goal: iOS16-generation XNU on Redmi Note10Pro sweet/SM7150. Always commit, use gh/Actions for kernel builds, keep this handoff current. Temporary fastboot boot only; preserve Android/backups. No userland/root filesystem boot yet.
- **Patch0020 update:** initial `e71098d` / Actions `38765012466` superseded by scalar-only compile flags. Added -mgeneral-regs-only to all six provider/BearSSL TUs and corecrypto_aes.c; object disassembly now confirms no SIMD. Updated implementation `ab9e23f`, Actions `38765422261` queued/running: https://github.com/dipa-studio/ios-sweet/actions/runs/38765422261. Do not launch another run. portable BearSSL AES CBC and legacy one-block ECB wired directly into SWEET corecrypto_aes.c. Genuine bitslice implementation, no CPU AES/SIMD requirement, heap or fake global crypto table. Source fetched by `0020-stage-bearssl.sh` from official BearSSL git at immutable `7bea48e5e850ab4cafbe68d3765cdaba13a86d6f`; MIT license retained, downloaded source stays out of git. Kernel limits include adapter only. All128/192/256-bit keys, CBC encrypt/decrypt, copied contexts, in-place/out-of-place; zero block count and size overflow handled, invalid keys clear context. Seven TUs compile to arm64 objects (`research/aes-objs`), imports resolve, all20 patches apply and sources match (`research/patch0020-check.log`). Sandbox `research/bt23/xnu`, originals `research/pre0020`. NEXT: Actions then actual-kernel NIST/random CBC/ECB checks and >=45s QEMU before another phone boot. Next artifacts out-0020 / bt24 / run24.log. 0020 updated CI pending. Local sources/checks match the scalar-only patch.
- **Latest built kernel0019**, implementation `256d3f0`, patches0001-0019. Actions `38763072907` PASSED (4m5s): https://github.com/dipa-studio/ios-sweet/actions/runs/38763072907. Kernel `xnu/out-0019/kernel.development.sweet`, SHA256 `a27df7568f03fb541cf0e8024c0a594fa178a85054fcf9eba29158cbd4c5ecc0`; checksum verified. Log/source `research/run23.log` / `research/bt23` (no nested .git). Seven pthread source/build/header files and staged adaptations byte-match local compile inputs.
- **0019 hardware photo received** `IMG_20261015_175306.jpg`: pthread registration visible, passes mbinit and DLIL checksum/scheduling, same AES fault as QEMU: PC`0xfffffe00079174e0` (`aes_encrypt_key128`), LR`0xfffffe000767c3a4` (`tcp_init`), FAR0x78, x8=0. Disassembly proves NULL g_crypto_funcs->ccaes_cbc_encrypt. Photo processed; no more0019 observation pending. General crypto table remains absent, other hash/mode operations may still fault after0020. DO NOT bypass TCP or install fake crypto. XNU already contains SHA256/HMAC implementations; AES source there is a dispatch wrapper. Full future provider interface libkern/libkern/crypto/register_crypto.h. Apple/corecrypto default README describes evaluation-only licensing, so no external corecrypto was fetched or staged; BearSSL selected for this portable AES integration.
- **0019 pthread FIXED in QEMU and observed beyond its init on phone**: 45s QEMU `research/q0019`, zero unknown glyphs, then AES panic. Actual-kernel API checks PASS `research/check-pthread19.gdb` / `.log`, guest `research/q0019-api`: function/callback table identity, actual provider pthread_init returns, locks/global hash/threadcall/typed zones initialized, thread_selfid via syscall shim + buffer bounds, process hash init/delete via shims restores NULL. Monitor quit prints expected remote-disconnect after PASS. All fixture guests stopped.
- **0019 provider**: genuine Apple libpthread-514.100.2 commit `a6c70ca0e544347a0377babf748f831577ec24f9`, exact paired release with xnu8796.141.3 in distribution-macOS/macos-135/release.json (`research/macos-135-release.json`). 0019 shell stage runs before patches (workflow copies *.sh); three SWEET wrapper TUs use kext BSD header view, vm_fault_external, renamed provider-side pthread_kern/current_uthread; register real function table at EARLY_BOOT SECOND, real pthread_init later. Stager applies bounded address casts, zero user addresses, proper panic format. SWEET opaque ksyn storage enlarged48->56 for trailing kwe_uth, checked with provider static assertion. Local pre-CI TargetConditionals fixture was syntax-only; artifact bt23 carries actual SDK header and CI is authoritative.
- **Phone0019 temporarily booted** 2026-10-15 15:51:36 UTC: exactly one FASTBOOT/product sweet verified; send OKAY0.406s, boot OKAY0.134s, total0.546s, exit0 (`research/boot0019.log`). Image `shim/out/shim-boot-0019.img`, 16,457,728 bytes, SHA256 `19429a57e486b856880df9e27327ed488e0139345311fdb0350974e72103a9a1`. Phone ADT/payload `shim/out/sweet-0019.adt` / `payload-0019.bin` timer19, unpacked ramdisk byte-match (`check-0019`). EntryPA0xb146b488, kernelendPA0xb2000000, boot_argsPA0xb2004000/top0xb2008000. Last user FASTBOOT+USB reply preceded this boot; do not assume phone is still in FASTBOOT.
- **CPU0018 physically verified** by `IMG_20261015_173951 (2).jpg`: boot CPU0 registered, real SGI1 verified, initialization complete -> BSD/MAC/mbinit -> old pthread-table panic. SweetCPU uses legacy IOCPU, ml_processor_register/processor_start/initCPU, real SGI1 clears SIGPdisabled before max CPUs completion; no forced flags/skipped waits. CPU APIs and two-CPU rejection passed (`research/check-cpu18.gdb`, `q0018-api`, `q0018-smp`). Single core; SMP/suspend unsupported. CURRENT SWEET has NO USE_APPLEARMSMP.
- QEMU next run: generate fresh `tools/mkadt.py research/q0020.adt --qemu` (timer27), mkpayload with `debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress`, then `tools/qemu-sweet.py PAYLOAD OUT --secs 45 --kernel KERNEL --fail-on-panic`. 12s can miss later panics because IORTC waits30s. Runner snapshot only: panic exit2, blank/incomplete exit3; absence of panic does not mean complete boot. Qualcomm XPU/ABL/panel and phone SMC PSCI require hardware checks.
- Local checker `tools/xnu-cc.py research/run23.log research/bt23 FILTER --per-file`, XNU_CC_OBJDIR for objects. For new BearSSL TUs add XNU_CC_EXTRA with -I bt23/xnu/libkern/crypto/sweet_bearssl/{inc,src}. Patch checker `research/check-patch-order.py` uses temporary upstream index; source fixtures/artifacts ignored under research. GDB mask registers to unsigned64, use function-entry manual-call return traps, discard manipulated guests. No QEMU guest intentionally left running.

## Session log and earlier handoffs (superseded by the active summary above)

### Prior 0019 transition notes (superseded)

- Goal: iOS 16 generation XNU on sweet. Always commit completed work, use gh/Actions for kernel builds, keep this handoff current. Temporary fastboot boot only; preserve Android/backups.
- **0019 build PASSED** Actions `38763072907` (4m5s), implementation `256d3f0`. Kernel `xnu/out-0019/kernel.development.sweet`, SHA256 `a27df7568f03fb541cf0e8024c0a594fa178a85054fcf9eba29158cbd4c5ecc0`; checksum verified. Log/source `research/run23.log` / `research/bt23`; all seven patched files and staged provider adaptations match local compile inputs. Prefer bt23 as the next baseline.
- **0019 pthread FIXED in QEMU**: 45s run `research/q0019` registers provider, passes mbinit, DLIL SUM16 checks and DLIL thread scheduling. Actual-kernel GDB checks `research/check-pthread19.gdb` / `.log` PASS: function/callback table identity, real _pthread_init returns, locks/global hash/cleanup threadcall/typed zones non-NULL, thread_selfid via actual syscall shim with output bounds, process hash init/delete through actual shims restores NULL. Guest stopped after tests; no fixture left running. GDB monitor quit prints expected remote disconnect after PASS.
- **Current next blocker:** QEMU0019 panic data abort FAR0x78 at `aes_encrypt_key128` PC`0xfffffe00079174e0`, called by `tcp_init` LR`0xfffffe000767c3a4`. Disassembly confirms `g_crypto_funcs == NULL`, loading ccaes_cbc_encrypt at+0x78. General crypto registration is still absent; DO NOT bypass TCP or supply fake crypto. Next integrate a genuine compatible crypto implementation/provider (AES first needed here, other digest/mode APIs also used). XNU contains SHA256/HMAC but no AES implementation; its corecrypto_aes.c is a dispatch wrapper. Full crypto table is in libkern/libkern/crypto/register_crypto.h.
- **0019 phone image prepared and verified**, user reports FASTBOOT+USB again; exactly one device/product sweet verified. `shim/out/shim-boot-0019.img`, 16,457,728 bytes, SHA256 `19429a57e486b856880df9e27327ed488e0139345311fdb0350974e72103a9a1`; unpacked ramdisk matches phone payload (`shim/out/check-0019`, `payload-0019.bin`, `sweet-0019.adt`, timer19). EntryPA0xb146b488; kernelendPA0xb2000000; boot_argsPA0xb2004000/top0xb2008000. Usual debug cmdline cpus=1/-noprogress. **Temporarily booted 2026-10-15 15:51:36 UTC**: send OKAY0.406s, boot OKAY0.134s, total0.546s, exit0 (`research/boot0019.log`). User asked for photo after45s. Await the photo; DO NOT reboot again before observation. Bootloader acceptance only; no0019 physical progress observed yet.
- **Hardware photo confirms 0018 progress** (`IMG_20261015_173951 (2).jpg`): real phone prints `SWEET CPU: boot CPU 0 registered, SGI1 verified, initialization complete`, enters BSD/MAC, reaches `mbinit: done`, then the same missing-pthread-function-table panic as QEMU at pthread_shims.c:318. CPU completion/interrupt delivery is now physically observed. The photo was received; no further phone boot performed yet.
- **Patch0019 committed/pushed `256d3f0`; Actions `38763072907` queued/running:** https://github.com/dipa-studio/ios-sweet/actions/runs/38763072907. Do not launch a duplicate. genuine Apple OSS libpthread-514.100.2 provider (immutable commit `a6c70ca0e544347a0377babf748f831577ec24f9`), paired with xnu-8796.141.3 by Apple's `distribution-macOS/macos-135/release.json` (`research/macos-135-release.json`). `0019-stage-libpthread.sh` fetches/stages it before patches; workflow now copies shell scripts too. SWEET-only wrappers compile all three real kernel sources, rename provider-side symbols, use kext header view and vm_fault_external, register the real function table at EARLY_BOOT SECOND. Existing pthread_init then runs the actual provider initialization. No pthread wait/syscall is bypassed. Source staging includes bounded explicit address casts/zero user addresses and panic-format fixes. SWEET kernel opaque ksyn storage enlarged from48 to56 bytes to contain this provider's trailing kwe_uth, with a provider size assertion. Local compile of three provider TUs plus pthread_shims/kern_fork passed; imports resolve and provider exports do not collide with existing kernel symbols. All19 patches apply and changed sources match (`research/patch0019-check.log`). Source sandbox `research/bt22/xnu`, originals `research/pre0019`, objects `research/pthread-objs`. Local TargetConditionals fixture only has target macros for syntax; CI stages the real macOS SDK header and is authoritative. Next Actions artifacts: out-0019 / bt23 / run23.log; run QEMU >=45 seconds. 0019 CI is pending; no 0019 QEMU run yet.
- **Latest kernel implementation `e7d9550`, patches0001-0018; CI `38760004398` PASSED (3m56s)**: https://github.com/dipa-studio/ios-sweet/actions/runs/38760004398. No build is pending. Kernel `xnu/out-0018/kernel.development.sweet`, SHA256 `b3c8d59acc88f93a2c836eb2527a05ed4fbaac7c580a2ea8c3b795137f4aadf1`; checksum verified. Source/log `research/bt22` / `research/run22.log` (baseline for patch0019; no nested .git). New driver/config sources match CI exactly.
- **CPU wait FIXED in QEMU**: SweetCPU uses legacy IOCPU, validates single boot CPU, ml_processor_register -> processor_start -> initCPU real SGI1 -> scheduler/IOKit completion -> ml_set_max_cpus. It does NOT force a flag or skip a wait. CPU APIs passed: Running CPU0, processor_array[0] association, SGI signalling enabled, name, unsupported secondary-start error (`research/check-cpu18.gdb` / `.log`, `research/q0018-api`). Single-core only; SMP and suspend unsupported. Two-CPU topology fails explicitly (`research/q0018-smp`).
- **Next blocker reproduced in 45s QEMU** (`research/q0018-long`, zero unknown glyphs): BSD initialization reaches MAC framework, network mcache and `mbinit: done`, then **`pthread kernel extension not loaded (function table is NULL). @pthread_shims.c:318`**. Do not bypass pthread_init: find/integrate the matching open-source libpthread kernel implementation and register its real function table. A 12s run `research/q0018` looked panic-free before the 30s IORTC wait elapsed; use >=45s or GDB checkpoints for the next iteration. No userland/root filesystem boot yet.
- **Phone 0018 TEMPORARILY BOOTED** 2026-10-15 **15:31:15 UTC**: exactly one FASTBOOT device verified product sweet; send OKAY0.400s, boot OKAY0.134s, total0.539s, exit0. Local log `research/boot0018.log`. This confirms bootloader acceptance only. User was asked for a photo; await it, DO NOT reboot the phone again before their observation. No flashing performed.
- Current hardware image `shim/out/shim-boot-0018.img`, **16,437,248 bytes**, SHA256 **`b7a23595d143a76c72c9fe2cfcc5d77a8f16987b5af1a2703bbffdfa6922908c`**. Phone ADT/payload `shim/out/sweet-0018.adt` / `shim/out/payload-0018.bin` (timer19), unpacked ramdisk exactly matches payload (`shim/out/check-0018`). EntryPA0xb146b488; kernelendPA0xb1ffc000; boot_argsPA0xb2000000/top0xb2004000. Command line `debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress`.
- QEMU payload/ADT `research/q0018.bin` / `research/q0018.adt` (timer27). Run `python3 tools/qemu-sweet.py research/q0018.bin research/NEW-OUT --secs 45 --kernel xnu/out-0018/kernel.development.sweet --fail-on-panic`; fresh ADT seed for a new payload. Output fb.png/fb.txt/regs.txt/qemu.log/result.json. Visible panic exit2; blank/incomplete decode exit3; no_panic_observed is snapshot-only, not successful boot. -noprogress prevents the graphical indicator corrupting console text. Qualcomm XPU/bootloader/panel and SMC PSCI still need physical validation.
- Patches0014-0017 fixed PRNG registration/direct SHA256, explicit unavailable trust-cache service with rejected loads/no matches, built-in SweetPlatformExpert, and timer PPI from ADT (phone19/default19, QEMU27). All their checks/artifacts are preserved in the history below. CURRENT SWEET has NO USE_APPLEARMSMP; do not assume gCPUIC/gAIC/gPMGR AppleARMSMP globals exist.
- Local single-file checker: tools/xnu-cc.py research/run22.log research/bt22 FILTER --per-file, output via XNU_CC_OBJDIR. Patch checker `research/check-patch-order.py` applies all18 via temporary index, matches sandbox sources. Sandbox for0018 `research/bt21/xnu`, originals `research/pre0018`, objects `research/cpu-objs`. First compiler issues were missing machine/atomic.h and nonexistent getNameSymbol; fixed and both TUs compiled successfully before CI. Fixtures/artifacts under research are local-only/ignored.
- GDB: mask int(register)&((1<<64)-1) for unsigned kernel pointers; use function-entry manual-call return traps, discard manipulated guests. No QEMU fixture is intentionally left running.

### Earlier active handoff snapshot (superseded)


- **0018 milestone:** Actions `38760004398` PASSED (3m56s), checksums passed, new CPU/build files byte-match CI tree. Kernel `xnu/out-0018/kernel.development.sweet`, SHA256 `b3c8d59acc88f93a2c836eb2527a05ed4fbaac7c580a2ea8c3b795137f4aadf1`; log/tree `research/run22.log` / `research/bt22`. QEMU `research/q0018` 12s: boot CPU registered, SGI1 verified, CPU initialization complete, **BSD initialization entered** (copyright, MAC framework, buffer headers), no panic/zero unknown glyphs. Direct CPU API checks PASS (`research/check-cpu18.gdb`, `.log`, `research/q0018-api`): CPU0 Running, processor matches processor_array[0], real SGI enabled, CPU name correct, secondary-start returns KERN_NOT_SUPPORTED. Two-CPU ADT correctly panics before registration (`research/q0018-smp`). Longer 45s run `research/q0018-long` still running; next BSD wait/fault not yet identified.
- **Prepared 0018 phone image:** `shim/out/shim-boot-0018.img`, 16,437,248 bytes, SHA256 `b7a23595d143a76c72c9fe2cfcc5d77a8f16987b5af1a2703bbffdfa6922908c`. Phone ADT/payload `shim/out/sweet-0018.adt` / `shim/out/payload-0018.bin`, usual debug args with cpus=1 and -noprogress. Unpacked ramdisk byte-compared (`shim/out/check-0018`). Entry PA remains 0xb146b488; kernel end PA 0xb1ffc000, boot_args 0xb2000000/top0xb2004000. User reports FASTBOOT+USB ready; read-only check found exactly one product sweet. NEXT: temporary fastboot boot of this verified image, record send/boot results, then await hardware photo without rebooting again.
- Patch 0018 committed/pushed **`e7d9550`**; Actions **`38760004398`** queued/running: https://github.com/dipa-studio/ios-sweet/actions/runs/38760004398. Do not launch a duplicate run.
- Active continuation: patch **0018** implemented in `iokit/Kernel/arm/SweetCPU.cpp` + arm64 source list + exact qcom,kryo470 personality. Keeps legacy IOCPU, accepts ONLY the single boot CPU, fills ml_processor_info from parsed topology with CPU object as cpu_id, calls ml_processor_register and processor_start. initCPU sends SGI1 via ICC_SGI1R_EL1 and waits (1-second deadline) for real cpu_signal_handler to clear SIGPdisabled. Only after successful startup calls ml_cpu_init_completed/cpusRunning and publishes completion/max CPUs. Secondary startup/suspend are explicitly unsupported. Local C++ compile passed for both TUs (`research/cpu-objs`), all imports resolve, object contains dsb ishst / ICC_SGI1R / isb; all18 patches apply in order and match sources. Sandbox `research/bt21/xnu`, originals `research/pre0018`; next CI artifacts should use `xnu/out-0018`, `research/bt22`, `research/run22.log`. User has the phone available; first run QEMU, then prepare/temporarily boot useful hardware progress.
- Goal: iOS 16 generation XNU on Redmi Note 10 Pro / sweet. User wants persistent progress, commits, kernel builds via `gh` Actions, and this handoff kept current across agent switches. Temporary `fastboot boot` only; preserve Android and backups.
- Latest kernel implementation: **`aa3f991`**, patches **0001-0017**. All four new Actions builds PASSED: 0014 `38748543058` (4m0s), 0015 `38749549779` (4m3s), 0016 `38750733996` (4m3s), 0017 **`38751507437` (4m7s)**. Latest: https://github.com/dipa-studio/ios-sweet/actions/runs/38751507437. No build is pending.
- **Current blocker: CPU initialization has no SWEET CPU driver.** QEMU registers SweetPlatformExpert, then kernel_bootstrap_thread waits in **kperf_init_early -> ml_wait_max_cpus**. Confirmed via actual-kernel GDB call stack (`research/locate-cpu-wait2.log` / `.symbols`) and normal-run `max_cpus_initialized == 2` (MAX_CPUS_WAIT). Do not force the flag or remove the wait. Next implement real CPU registration and completion using XNU's CPU/processor interfaces. CURRENT SWEET uses legacy IOCPU (`USE_APPLEARMSMP` is absent); enabling AppleARMSMP is a separate architectural change requiring GIC/PMGR services. No userland/root filesystem boot yet.
- Fixed this session: PC=0 unregistered PRNG callback (0014, built-in HMAC-SHA256 provider + direct entropy/write_random hashing); absent Image4/AMFI trust-cache service (0015, unavailable runtime, loads rejected and queries no-match); missing platform driver (0016, SweetPlatformExpert exact personality); incorrect QEMU timer IRQ (0017, validated ADT PPI property, phone default19/QEMU27).
- **Latest kernel** `xnu/out-0017/kernel.development.sweet`, SHA256 `055a80190ab998b4df9203f1102072dcc78faad1779a537a514e522b682b582f`. Buildtree/log **`research/bt21` / `research/run21.log`**; all nine changed C/C++/header/config files byte-match local checked sources. Checksums passed. Entry PA `0xb146b488`, kernel end PA `0xb1ff4000`. Preferred baseline for patch 0018: `research/bt21/xnu` (no nested .git).
- **QEMU verified**: `research/q0017-noprogress` ran **30 seconds**, no visible panic, **zero unknown glyphs**, IRQ exceptions returned normally (4 IRQs, tickless idle). It still waits for CPU completion, so this is NOT a completed boot. Earlier 15s run `research/q0017` captured 122 IRQs, timer value27, GICR_ISENABLER0 `0x08000002`, and CPU WAIT; graphical progress overlay corrupted 13 glyphs. Add **`-noprogress`** to keep the console readable. New runner classifies incomplete/blank decoding explicitly (exit3 with --fail-on-panic), visible panic exits2. Snapshot-only; use regs/GDB to diagnose stalls.
- Current QEMU payload/ADT: **`research/q0017-noprogress.bin` / `research/q0017.adt`**. Run: `python3 tools/qemu-sweet.py research/q0017-noprogress.bin research/NEW-OUT --secs 30 --kernel xnu/out-0017/kernel.development.sweet --fail-on-panic`. Generate fresh seed with mkadt for a new payload. QEMU virt models generic ARM execution, not Qualcomm XPU/bootloader/panel or the phone's SMC PSCI conduit.
- **Prepared phone image**: **`shim/out/shim-boot-0017.img`**, 16,416,768 bytes, SHA256 `51ff7fe30b4a6668c3452ffe1da922c5ac30cb8de60625c2a652587ecbd0ec92`. Phone ADT/payload `shim/out/sweet-0017.adt` / `shim/out/payload-0017.bin` (timer19). Unpacked ramdisk exactly matches payload (`shim/out/check-0017`). Command line **`debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress`**. NOT sent to phone this session: known CPU-driver wait should be addressed in QEMU first. Last actual phone boot remains 0013; user's latest photo `IMG_20261015_160033.jpg` confirmed the old PRNG PC=0 panic.
- Direct QEMU/GDB API checks: PRNG 600-byte chunking, buffer bounds, changing output, zero-length reads/writes, user reseed, contended refresh, generator1 init/output PASS again on latest0017 (`research/check-prng17.gdb` / `.log`, guest `research/q0017-api`). Trust-cache unavailable-service/argument/output cases PASS on0015 (`research/check-trustcache.gdb` / `.log`). Platform registration + target/product normal/truncated/zero/null/bounds PASS on0016 (`research/check-platform.gdb`, `research/check-platform3.log`). Different platform ID correctly retains IOPanicPlatform fallback (`research/q0016-negative`). Timer PPI32 and size2 correctly panic (`research/q0017-badppi`, `research/q0017-badsize`); omitted property selects19 (`research/q0017-default`). These are API/bring-up checks, not crypto certification or SMP scheduling validation.
- Local checker **`research/check-patch-order.py`** verifies all17 patches and changed source equality using a temporary upstream git index. Fixtures/logs/artifacts under research are local-only and ignored. For GDB unsigned kernel pointers, mask `int(register_value) & ((1<<64)-1)`; x30/x29 may be rendered signed. Stop at a function entry for manual-call return traps, and discard each manipulated guest after API tests. All fixture QEMU guests have been stopped.


- User wants persistent progress toward iOS 16, commits for completed changes, builds through `gh` / GitHub Actions.
- Keep this file current at every milestone so another agent can resume immediately, including when usage limits interrupt a session.
- Patch 0017 committed/pushed `aa3f991`, Actions `38751507437` running: https://github.com/dipa-studio/ios-sweet/actions/runs/38751507437. Next artifacts: xnu/out-0017, research/bt21, research/run21.log. Do not duplicate.
- Patch 0016 kernel downloaded/checksum verified: SHA256 `d06336c54baa06e0df6561a8bd7df98a9b9f7502c9381c62d1a44c045cd1ce46`, `xnu/out-0016/kernel.development.sweet`; buildtree/log `research/bt20` / `research/run20.log`. QEMU `research/q0016` (10s) prints platform expert registered, zero unknown glyphs, no panic observed BUT stalls (timer mapping still wrong until 0017). Direct actual-kernel GDB tests passed for registered instance and target/product names, including maxLength=1/0 and NULL, sentinels intact (`research/check-platform.gdb`, `research/check-platform3.log`, `research/q0016-api3`). First two fixture attempts used premature/wrong return breakpoints; discarded, corrected fixture uses start-return observation then a function-entry return trap. No phone boot yet.
- Patch 0016 CI `38750733996` PASSED (4m3s); artifacts not yet downloaded/booted. Patch 0017 prepared to fix QEMU timer fidelity BEFORE interpreting future no-panic/stall runs: actual `qemu-system-aarch64 -M virt,gic-version=3,dumpdtb=research/qemu-virt.dtb ...` timer property has virtual PPI 11 => INTID 27, while phone uses INTID 19. Kernel formerly hardcoded 19. New optional /arm-io/gic virtual-timer-intid property selects the PPI (validate exact u32 and 16..31); missing property retains phone default 19. One RO-late global drives GIC enable and sleh_irq dispatch. tools/mkadt.py emits phone19/QEMU27. Both C TUs compile (`research/timer-objs`), ADT serialize/parse checks confirm values/addresses, all 17 patches apply and match. Sandbox `research/bt19/xnu`, originals `research/pre0017`; initial local sleh compile failed due read-only exported header not updated, fixed export and BOTH recompiled successfully. CI exports normally.
- Architecture correction for next agent: CURRENT SWEET board_config does NOT define USE_APPLEARMSMP; it compiles the legacy IOCPU path, not cpu_boot_thread/IOPMGR AppleARMSMP. Existing roadmap mentions AppleARMSMP as a future approach. Do not look for gCPUIC/gAIC/gPMGR globals in the current kernel: they are absent. Determine the actual CPU-init wait after platform registration before choosing the next driver architecture.
- Patch 0016 committed/pushed as `0dcdf5c`; Actions `38750733996` running: https://github.com/dipa-studio/ios-sweet/actions/runs/38750733996. Next artifacts: `xnu/out-0016`, `research/bt20`, `research/run20.log`.
- Patch 0016 implemented: new `iokit/Kernel/arm/SweetPlatformExpert.cpp`, arm64 source list, built-in personality in KernelConfigTables.cpp guarded by ARM64_BOARD_CONFIG_SWEET. Matches only xiaomi,sweet at score 10000, keeps IOPanicPlatform fallback for other hardware. Uses IODTPlatformExpert base initialization/power domain and createNubs CPU logical-ID annotation; overrides top-level publishing because base requires nonexistent Apple NVRAM /options. Publishes real CPU/top-level nodes, provides bounded target/product names, and registers the platform service. GIC/PMGR and arm-io child-bus drivers remain separate work. Both C++ TUs compile (`research/platform-objs`), all imports resolve against 0015/own objects, all 16 patches apply and sources match. Sandbox `research/bt19/xnu`; originals `research/pre0016`. NEXT: full Actions/QEMU; inspect CPU boot waits after the platform registers, do not equate absence of panic with successful boot.
- Patch 0015 CI `38749549779` PASSED (4m3s), checksum verified. Kernel `xnu/out-0015/kernel.development.sweet`, SHA256 `ca1b424a596c7058550ad1659080a333e7643270f019656401d80bf2b876645f`; buildtree/log `research/bt19` / `research/run19.log`. QEMU `research/q0015` (10s, zero unknown glyphs) passes trust-cache handling and machine lockdown, then panics `Unable to find driver for this platform: "xiaomi,sweet" @IOPlatformExpert.cpp:2319` (IOPanicPlatform fallback). Next concrete work: add a built-in SWEET IODTPlatformExpert personality/class; keep the fallback for mismatched platforms. No phone boot yet.
- Direct trust-cache API checks PASSED in the actual 0015 kernel under QEMU/GDB (`research/check-trustcache.gdb`, `research/check-trustcache.log`, `research/q0015-api`): runtime pointers NULL, hash/UUID queries return NOT_FOUND, typed/untyped/legacy loads return NOT_SUPPORTED, capabilities outputs zero and bounds preserved, invalid-argument cases still reject. Second PRNG check also verifies contended refresh returns immediately (`research/check-prng2.log`, `research/q0014-api2`).
- Patch 0015 committed/pushed `8f851d4`, Actions run `38749549779` running: https://github.com/dipa-studio/ios-sweet/actions/runs/38749549779. Do not duplicate.
- Direct PRNG API checks passed in the REAL 0014 kernel under QEMU/GDB, stopped before trust-cache init (`research/check-prng.gdb`, log `research/check-prng.log`, guest `research/q0014-api`). Invoked read_random for 600 bytes (chunking and buffer sentinel intact), repeated output differed, zero-length read/write succeeded, write_random(64-byte input) succeeded, secondary generator 1 initialized and generated distinct output. QEMU log has no exceptions during these checks; guest was discarded after the tests. This tests API behavior, not a cryptographic certification or SMP scheduling.
- Patch 0015 implemented in `bsd/kern/kern_trustcache.c`: SWEET with missing Image4/AMFI marks both runtime pointers NULL and logs service unavailability. Existing static loader handles NULL. Public load APIs return KERN_NOT_SUPPORTED; hash/UUID queries return KERN_NOT_FOUND; capabilities outputs are zero with KERN_NOT_SUPPORTED. Invalid-input checks remain, and Apple paths/available-provider initialization retain existing behavior. No trust is granted. Local arm64 compile passed (`research/trustcache-objs`), all 15 patches apply and sources match. Sandbox `research/bt18/xnu`, baseline `research/pre0015`. Next: Actions/QEMU and direct unavailable-service API checks using GDB.
- Patch 0014 CI `38748543058` PASSED (4m0s), artifact checksum passed. Kernel `xnu/out-0014/kernel.development.sweet`, SHA256 `741de20c851755d333759d7e668346f3edb4f325efac4cc7c142d80d1f5ff75c`; buildtree/log `research/bt18` / `research/run18.log`. QEMU run `research/q0014` (10s, zero unknown glyphs) prints `SWEET PRNG: HMAC-SHA256 registered`, passes commpage initialization, loads vnguard policy, THEN panics `image4 interface not available @kern_trustcache.c:253`. PC=0 fault FIXED IN QEMU. No new phone boot performed.
- Next work: SWEET currently has neither AppleImage4 nor AMFI. `trust_cache_runtime_init` unconditionally requires both; unlike BCM2837, SWEET enters this startup path. Investigate an explicitly unavailable trust-cache runtime with rejected loads/no query matches while providers are absent; preserve all Apple-platform checks. Merely skipping the startup call would leave later AMFI/IMG4 dereferences unsafe. Existing load_static_trust_cache already handles trust_cache_rt == NULL.
- QEMU runner now supports `--kernel MATCHING_KERNEL --fail-on-panic`: runtime font extraction from the payload produces exact `fb.txt`, plus `result.json`; a visible panic returns 2. Baseline 0013 re-run `research/q0013-text` detects the same NULL callback panic with zero unknown glyphs. Synthetic glyph roundtrip (including literal `?`) and invalid-VA rejection passed. Screen rows remain circular, not a full log; `no_panic_observed` does not prove successful boot. README has the invocation.
- Patch 0014 committed/pushed as `be61f99`; Actions run `38748543058` is running: https://github.com/dipa-studio/ios-sweet/actions/runs/38748543058. Do not start a duplicate build.
- 2026-10-15 active: hardware photo `IMG_20261015_160033.jpg` confirms the same PC=0 instruction-fetch abort as QEMU (LR `0xfffffe0007443fe4` = read_random). Independently reproduced with kernel 0013 in `research/q0013` (8-second run); prior allocator fix works. Latest tooling commit reviewed: `8d66d2d`.
- Patch 0014 implemented: registers a built-in HMAC-SHA256 DRBG provider at EARLY_BOOT/FIRST, before commpage creation. A shared mutex serializes output/reseed across CPUs (correctness first; no per-CPU scaling yet), initgen validates CPU identities, refresh uses try-lock and the existing entropy filter/health tests. SWEET entropy accumulation and write_random now use the built-in SHA256 directly; no incomplete g_crypto_funcs table is registered. The existing bootloader-seed requirement remains enforced.
- Local validation: both PRNG translation units compile to arm64 objects in `research/prng-objs`; no SHA256 wrapper imports remain. All 14 patches apply in CI order and resulting PRNG sources match local inputs. Sandbox `research/bt17/xnu`, originals `research/pre0014`, checker `research/check-patch-order.py`. NEXT: Actions kernel build, download to `xnu/out-0014`, run the QEMU payload before requesting another phone boot. Baseline QEMU ADT/payload are `research/q0013.adt` / `research/q0013.bin`.
- 2026-10-15 08:15 QEMU EMULATION WORKS (`tools/qemu-sweet.py`, see "QEMU emulation" below). Patch 0013 VERIFIED in QEMU: boot passes kmem_crypto_init and ulock_initialize. NEXT BLOCKER (reproduced in QEMU, expected on hardware too): `pmap_create_commpages -> random() -> RandomULong -> read_random -> prng_funcs.refresh == NULL` (instruction fetch abort at pc 0, lr read_random+0x34). Nobody calls `register_and_init_prng` (closed corecrypto kext does it on Apple). Fix = patch 0014: SWEET-registered cckprng_funcs provider (osfmk/prng/prng_random.c); note random_cpu_init also panics while !prng_ready. The 07:26 hardware boot of 0013 will most likely show this same panic.
- Previous hardware boot: patch 0013 (`a3a46e2`) CI `38686345689` PASSED (3m44s), image `shim/out/shim-boot-0013.img` was temporarily booted on 2026-10-15 at 05:26 UTC: send OKAY (0.407s), boot OKAY (0.134s), total 0.546s. Superseded by the hardware/QEMU PC=0 observation and patch 0014 work above.
- Latest kernel implementation commit: `8f851d4`. Latest successful kernel CI: `38749549779` (patch 0015), https://github.com/dipa-studio/ios-sweet/actions/runs/38749549779.
- CURRENT image: `shim/out/shim-boot-0013.img`, 16,412,672 bytes, SHA256 `110d1c46aee4b60253db24b6535e9781c4cf0fd25ca2a70e9016cf81378cea25`. Kernel `xnu/out-0013/kernel.development.sweet`, SHA256 `f0b1d375995316c550ce7014ff234d8271e9b9ac2857795ceff41b76ba2cd740`, plain arm64. CI log confirms 0013 applied; checksums passed. Entry PA `0xb146b488`, kernel end PA `0xb1ff4000`.
- Current log/buildtree: `research/run17.log`, `research/bt17` (extracted, no nested .git; preferred baseline for patch 0014). Payload/ADT: `shim/out/payload-0013.bin`, `shim/out/sweet-0013.adt` (includes /defaults). Unpacked ramdisk byte-compared with payload in `shim/out/check-0013`.
- Patch-0012 original image: `shim/out/shim-boot-0012.img`, 16,412,672 bytes, SHA256 `cf4b8ec4a65a51888d71c17d09cd0831d6b761b90e2531fdb8e575c32f4fd24a`. Kernel `xnu/out-0012/kernel.development.sweet`, SHA256 `69b78f49f6459cc63a0af44e7cf73c1779ef72130ef72b12ae86c88183ffc742`; checksums passed and sweet_early_relocate symbol present. Entry PA remains `0xb146b488`, kernel end PA `0xb1ff4000`.
- Patch-0012 log/tree: `research/run16.log`, `research/bt16` (extracted, no nested .git; preferred baseline for next patch). CI log confirms 0012 applied. Payload `shim/out/payload-0012.bin`, ADT `shim/out/sweet-0012.adt`; packed ramdisk byte-compared with payload in `shim/out/check-0012`.
- Active payload command line: `debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam`.
- Latest observed photo: `/home/dipa/Downloads/IMG_20261015_071346.jpg` (local only). Stages 9 (kernel framebuffer VA), 10 (TTBR0 off/TLB flush), 11 (physmap table pointers) and 12 (calling pmap_bootstrap) all visible. Persistent diagnostics are VERIFIED ON HARDWARE.
- pmap.c:1987 is the assert after SecureDTLookupEntry(NULL, "/defaults", &entry). The pmap-max-asids property itself is optional; an empty /defaults uses XNU's MAX_ASIDS. Do not bypass the assertion or guess an ASID limit.
- Previous payload-only fix image: `shim/out/shim-boot-0012-defaults.img`, SHA256 `3ff61a268853c6ea7cbf284833f1346a1d791980ca366b6e1a215a86e040512b` (16,412,672 bytes). Same kernel/CI as 0012; ADT 2516 bytes (`shim/out/sweet-0012-defaults.adt`), root /defaults present with no ASID override. Payload `shim/out/payload-0012-defaults.bin`; unpacked ramdisk exactly matches payload (`shim/out/check-0012-defaults`). This boot reached the allocator crypto NULL-pointer fault below.
- Latest hardware photo: `/home/dipa/Downloads/IMG_20261015_071608.jpg` (local only). Normal serial framebuffer console works. VM bootstrap/zone initialization, logging, scheduler, IPC, KDP and ulock_initialize print before the kmem_crypto_init data abort. gPanicBase warnings are expected because PLATFORM_PANIC_LOG_DISABLED is configured, and are not the faulting call.
- Faulting instruction: `ldr x0, [x8, #0x150]` in crypto_random_kmem_ctx_size; x8 = NULL g_crypto_funcs. Source: libkern/crypto/corecrypto_rand.c and osfmk/vm/vm_kern.c:2448. rand.h explicitly permits NON-cryptographic kmem RNGs, but requires no locking in generation and context size <=256. Do not substitute read_random here: the global PRNG provider is also unregistered and kmem generation must remain lock-free. early_random may seed contexts during single-CPU bootstrap; it uses the built-in HMAC-SHA256 DRBG with the host-generated ADT seed.
- Patch 0013 keeps the replacement entirely private to vm_kern.c: SplitMix64 state is 8 bytes per CPU/sizeclass, initialized using early_random. Uniform selection uses rejection sampling to avoid modulo bias. Other platforms retain the original corecrypto calls; SWEET's generic crypto APIs/registration remain untouched. Reference: https://prng.di.unimi.it/splitmix64.c (Sebastiano Vigna, public domain).
- Validation: vm_kern.c compiles to arm64 (`research/kmem-rng-objs`, using `research/run16.log` + `research/bt16`). Undefined symbols include early_random and NO crypto_random_* references. All 13 patches apply in CI order and match the checked source. Original saved as `research/vm_kern.pre0013.c`.
- RNG host checks: extracted actual new helper in `research/kmem-rng-check.c`; 16,384 outputs match the author's downloaded reference (`research/splitmix64-reference.c`), 147,456 bounded outputs satisfy their limits (including 1 and UINT64_MAX), and a forced rejection advances correctly. Full kernel crypto services and the registered kernel PRNG provider remain future work; this patch only supplies the allocator RNG contract.
- Patch-0011 artifacts: kernel `xnu/out-0011/kernel.development.sweet`, log `research/run15.log`, extracted buildtree `research/bt15` (no nested .git). CI log confirms patch 0011 applied; artifact checksums passed. Kernel is plain arm64, entry VA `0xfffffe000746b488` -> PA `0xb146b488`, kernel end PA still `0xb1ff4000`.
- Patch-0011 image: 16,412,672 bytes, SHA256 `29ad5cbfc752473de4af2c471a24a8b34f92da4bff5afec65c614b90cd3ad53a`. Kernel SHA256 `8ac3a956894b09f7bd0d890de8c5de38c65513287feb1e1bcd12db8ca772ee5c`. Payload/ADT in `shim/out/payload-0011.bin`, `shim/out/sweet-0011.adt`. Header unpacked/checked in `shim/out/check-0011`.
- First patch-0011 attempt timed out waiting for FASTBOOT; superseded by the successful send/boot recorded above. Do not repeat the boot before the user reports the current screen.
- Patch-0011 photo: `/home/dipa/Downloads/IMG_20261015_070218.jpg` (local only). Visible stages 1-8 and old red shim text; entry PA B146B488, boot args PA B1FF8000 / top B1FFC000. No evidence yet locating execution after stage 8.
- Patch-0012 sandbox: `research/bt15/xnu` (NO nested .git). Proposed permanent debug VA: VM_MIN_KERNEL_ADDRESS + ARM_TT_L2_SIZE, in the reserved gap below gVirtBase and above low globals; map the same PA framebuffer as Normal-NC in the final TTBR1 before arm_vm_physmap_init changes phystokv(). Keep the early panic sink until normal kprintf startup.
- Patch 0012 validation: all 4 changed C translation units compiled to arm64 objects in `research/post-ttbr0-objs`; internal header export added to osfmk/arm64/Makefile and recreated locally in EXPORT_HDRS for pe_serial.c. All 12 patches apply in CI order and match all 6 edited files. Baselines are saved under `research/pre0012/`.
- Actual mapping-helper host model (`research/early-map-check.c`, barrier stubbed only for host compilation) confirms: VA `0xfffffe0002000000`, L1 index 2016, L2 index 1; descriptor `0x006000009c000605` = framebuffer PA, Normal-NC, outer-shareable, EL1 RW, PXN+UXN. All other L2 entries preserved. The gap is excluded by ARM_LARGE_MEMORY's pmap_virtual_region(0).
- Next boot command line MUST add `-enable_kprintf_spam`: DEVELOPMENT disables kprintf_output by default even when DB_KPRT is set (`pexpert/arm/pe_kprintf.c`). Planned command line: `debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam`.

### Patch 0012 screen legend (after original stages 1-8)
- 9: kernel framebuffer VA live; 10: TTBR0 off / TLB flushed; 11: physmap pointers rebound.
- 12: calling pmap_bootstrap; 13: pmap_bootstrap returned; 14: early I/O page tables ready; 15: arm_vm_init returned.
- 16: calling serial_init; 17: fbcon config read / mapping; 18: fbcon mapping returned; 19: serial_init returned; 20: kprintf startup complete.
- Normal serial initialization clears the screen, so earlier stages may disappear before 19. If serial exists, early console disables after 20; otherwise early panic output stays enabled.
- Local source sandbox: `research/bt13/xnu` (git baseline `623b060`, patches 0001-0008 already in baseline; uncommitted export edits correspond to patch 0009). Preserve those edits when producing patch 0010.
- Previous compile log/tree: `research/run13.log`, `research/bt13`; previous kernel: `xnu/out/kernel.development.sweet`. New successful log/tree: `research/run14.log`, `research/bt14`; new kernel: `xnu/out-0010/kernel.development.sweet`.
- Current device access: patch-0012 image was temporarily started from FASTBOOT; no adb connection is expected. Never flash partitions for bring-up; use `fastboot boot` with the shim image.
- Patch `0010` lives in `xnu/patches/0010-sweet-early-framebuffer-debug.patch`. Its exact compiled sources are under `research/bt13/xnu`; generated objects are in `research/early-objs`.
- Local checks passed: all 5 changed/new translation units compiled to arm64 Mach-O objects; new console only imports `_doprnt` and `iso_font` (both exist in the previous kernel). All 10 patches applied to a temporary upstream git index in CI order, and all 7 resulting changed source files matched the local compile inputs.
- Reproduce changed-file compilation: `XNU_CC_OBJDIR="$PWD/research/early-objs" python3 tools/xnu-cc.py research/run13.log research/bt13 arm_init.c arm_vm_init.c kern/debug.c arm64/start.s osfmk/arm64/sweet_early.c --per-file` (create the output directory first). The helper now accepts explicit new source paths absent from the old artifact's Makefiles and rejects empty selections.
- Device command result: `adb reboot bootloader`, then `timeout 30s fastboot boot shim/out/shim-boot-0010.img`: send OKAY (16028 KB), boot OKAY, total 0.541s. This confirms bootloader acceptance only, not XNU progress.
- The successful boot above was on 2026-10-14. On 2026-10-15, `timeout 45s fastboot boot ...` timed out waiting for a device; no image was sent. Boot image SHA256 rechecked and unchanged. No new build is needed to repeat the trial.
- Earlier retry: `timeout 90s fastboot boot shim/out/shim-boot-0010.img` timed out (exit 124). This is superseded by the successful 2026-10-15 repeat boot recorded above; do not repeat it until the user reports the screen.
- User observation confirms MMU-on C entry, platform expert, CPU topology/bootstrap, startup bootstrap and cpu_init all complete. Failure is within arm_vm_physmap_init (non-XNU_MONITOR branch), before stage 8 / TTBR0 teardown. Old red shim text remains behind the early console; this is expected because only written rows are cleared.
- New edit/compile sandbox is `research/bt14/xnu` (extracted artifact, NO nested .git; `git diff` there would act on the parent project). Use a saved baseline file / generated unified diff, or explicitly initialize a local baseline before editing. `research/bt13/xnu` does have its own baseline git repo.
- Exact user-reported panic: `arm_vm_init.c:1606 Assertion failed: (temp_ptov_table[ptov_index - 1].va + temp_ptov_table[ptov_index - 1].len) <= physmap_end`.
- Root cause: MacOSX build sets `ARM_LARGE_MEMORY=1`; `XNU_MONITOR` is off. Block alignment in arm_vm_physmap_slide can add gaps, but the non-PPL large-memory physmap_end omitted the padding already present in the small-memory branch. Patch 0011 reserves PTOV_TABLE_SIZE*ARM_TT_TWIG_SIZE (8*32MB) in both the aperture bound and its L1 allocation; monitor/PPL builds retain zero padding. The assertion is preserved.
- Validation: `arm_vm_init.c` compiled to an arm64 object using `research/run14.log` + `research/bt14` (object in `research/physmap-objs`). All 11 patches apply in CI order and produce exactly that source. Host harness `research/physmap-check.c` extracts the real XNU slide function with page-table-write stubs: all 65,536 page-aligned slides within 1GB checked against the current kernel memory layout; old bound fails 65,504 cases, padded bound fails zero; worst overrun 0x1ffc000 bytes. Baseline source saved as `research/arm_vm_init.pre0011.c`.
- CI: https://github.com/dipa-studio/ios-sweet/actions/runs/38638702083 (success; artifacts and full log downloaded).
- New image: `shim/out/shim-boot-0010.img` (16,412,672 bytes, SHA256 `ed2c270e0081bad5ff517be415f9bfe8805463aea7866732203fa97ac737e64e`). Previous image preserved as `shim/out/shim-boot-pre0010.img`.
- New kernel SHA256: `3ee05270cc291c49589a101678f904b1b69cb2f2575e05398bce8a4e052f409a`. Artifact checksums passed; arm64 (not arm64e), early-console symbols present. Payload entry VA `0xfffffe000746a488` -> PA `0xb146a488`; kernel end PA `0xb1ff4000`. Command line remains `debug=0xc serial=3 cpus=1 keepsyms=1`.

### Patch 0010 screen legend
- Bottom-left white 64x32 tile: assembly entered `start_first_cpu`, before page tables/MMU.
- Text `SWEET EARLY 1`: entered `arm_init` with MMU on; 2: platform expert done; 3: CPU topology done; 4: CPU bootstrap done; 5: startup bootstrap done; 6: CPU init done; 7: entering `arm_vm_init`; 8: leaving bootstrap TTBR0.
- `SWEET EARLY PANIC:` prints a copy of panic arguments before normal panic handling needs per-CPU/thread state.
- In patches 0010/0011 the console disabled before TTBR0 invalidation; patch 0012 replaces that with a persistent kernel VA alias and diagnostics through normal serial/kprintf startup (see its legend above).
- Screen contents require a physical observation from the user: adb cannot capture a framebuffer after Android has been replaced by a bare-metal kernel.

## QEMU emulation (2026-10-15)
- `tools/mkadt.py OUT.adt --qemu` = same ADT with QEMU virt GICD 0x08000000 / GICR 0x080a0000 / CNTFRQ 62.5 MHz.
- `tools/qemu-sweet.py PAYLOAD OUTDIR [--secs N] [--hmp "x /8gx ADDR"] [--gdb]`: host-side copy of shim/loader.c
  (segments + ADT + boot_args at their PAs, 6-instruction stub sets x0 and jumps), `-M virt,gic-version=3 -cpu cortex-a76`
  (same ID_AA64MMFR0 as Kryo 470), 4G RAM so 0x9c000000 fb and 0xb0000000 kernel are plain RAM.
  Outputs `fb.png` (the screen), `regs.txt`, `qemu.log` (exceptions with ESR/FAR/ELR). `--gdb` halts with a stub on :1234
  (system `gdb` + `set architecture aarch64`, `hbreak *VA` works with the MMU on).
- Not emulated: Qualcomm XPUs, ABL, real panel, PSCI conduit (QEMU virt uses hvc). Hardware still decides those.
- Example: `python3 tools/mkadt.py /tmp/q.adt --qemu && python3 tools/mkpayload.py xnu/out-0013/kernel.development.sweet /tmp/q.adt /tmp/pq.bin --cmdline 'debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam' && python3 tools/qemu-sweet.py /tmp/pq.bin /tmp/q`

## Layout
- `backup/`  partition dumps + full sdb..sdf LUNs, `SHA256SUMS` (all verified on-device == local)
- `dtb/`     live FDT (from OrangeFox), PixelOS boot.img dtb, dtbo, dts versions
- `shim/`    bare-metal boot shim (`./build.sh` -> `out/shim-boot.img`)
- `research/` mainline sm7150 dts, XNU pe_fiq.c etc, PocketDarwin patches
- `tools/unpack_bootv2.py`

## Device access
- No root in PixelOS 17 (user build, adb root disabled). Root = `fastboot boot recovery/recovery.img` (OrangeFox R12.0_2, temp boot, not flashed).
- `fastboot boot` works for stock boot.img, OrangeFox, and our shim.
- Shim resets itself via PSCI SYSTEM_RESET; IMEM restart_reason 0x77665500 is seen
  (bootreason=bootloader) but ABL still boots Android, so it does not stop in fastboot.

## Hardware facts (live DT + shim measurements)
- Framebuffer (ABL cont splash): 0x9c000000, 1080x2400, stride 4320, a8r8g8b8, panel is DSC *video* mode (no kick needed).
- RAM: 0x80000000+2G, 0x100000000+0xfcc00000. Live reserved-memory = PixelOS base dtb + sweet dtbo fixups.
- GICv3: GICD 0x17a00000, GICR 0x17a60000 (stride 0x20000, 8 PEs). GICD_TYPER 0x007B041D: SecurityExtn=1 (DS=0).
  ABL leaves GICD_CTLR = 0x10 (ARE_NS on, groups off). Writing 0x13 reads back 0x12: EnableGrp1A (bit1) is the one that matters.
- GIC Group 1 VERIFIED (shim 2c): vtimer INTID 19 = 30 IRQs/300ms, ptimer INTID 18 = 30, SGI 1 to self = 10/10.
  ICC_SRE=1 already, ICC_CTLR 0x8440, priority/enable writes stick. GICR_IGROUPR0 and GICD_IGROUPRn read 0 from NS
  even though Group 1 delivery works (RAZ in NS view) - do not use them as a health check.
  INTID 28 shows pending constantly (unknown PPI 12).
- Timer 19.2 MHz. Qualcomm PPI numbering: secure-phys/phys/virt/hyp = PPI 1/2/3/0 -> vtimer INTID 19, ptimer 18 (NOT 27/30).
- PSCI 1.1 via SMC, SMCCC 1.1. CPU_ON ok; SYSTEM_SUSPEND and SYSTEM_RESET2 unsupported.
- SMP: CPU_ON works for all 7 secondaries (MPIDR 0x81000n00).
- Entry EL1, MMU off, x0 = DTB (magic ok). ID_AA64MMFR0 = ...101122: 16K granule YES, 4K YES.
- No serial console: debug UART SE is in SPI mode on sweet. Screen is the only debug channel.

## XNU implications
- XNU GICv3 path (pexpert/arm/pe_fiq.c, VMAPPLE) puts the timer (PPI 27) in Group 0 = FIQ. With SecurityExtn=1,
  Group 0 is secure -> impossible from NS EL1. Need: Group 1 IRQ, ICC_IGRPEN1, INTID 19, and the timer handled in the IRQ path.
- XNU VMAPPLE PSCI uses `hvc`; sweet needs `smc`.
- PocketDarwin NonAppleGenericCpu.patch only swaps -mcpu=apple-h7 for -march=armv8-a.

## Milestone 3 (2026-10-14): 16K MMU verified
- ABL loads the Image at 0x80080000 (base 0x80000000 + 0x80000) regardless of text_offset=0.
- 16K granule, T0SZ=28 (L2 start, 32MB blocks), MAIR 0x44ff00, TCR 0x1409CB51C, PARange=2 (40-bit PA).
- Only own image pages WB (Qualcomm XPUs: never map carve-outs cacheable); fb Normal-NC; rest Device.
- AT S1E1R checks all as expected; unmapped -> translation fault L2.
- Fill fb: 110 ms (MMU off) -> 3.5 ms (NC). Memory loop 70 ms -> 0.7 ms. vtimer + SGI IRQs still fine with MMU on.

## XNU loader design notes (xnu-8796)
- Entry: `_start` -> `start_first_cpu`, x0 = boot_args (PA), MMU off, EL1. boot_args: Revision/Version 2,
  virtBase/physBase/memSize/topOfKernelData, Boot_Video (fb 0x9c000000, rowBytes 4320, 1080x2400, depth 32),
  deviceTreeP/Length (ADT), CommandLine[608], bootFlags, memSizeActual.
- start.s maps [kernel mach header .. physBase+memSize) with cacheable BLOCKS. On Qualcomm every XPU carve-out
  must therefore lie below the kernel: use physBase = 0xb0000000 (above ramdump_fb 0xaf000000+16M,
  cdsp_sec, qseecom), end before rmtfs 0xfde01000 -> memSize ~0x4d000000 for bring-up.
- Base ADT: iPhone 8 d20ap DeviceTree from iOS 16.7.16 IPSW (tools/remotezip.py + tools/adt.py; LZFSE payload).
  Template values are empty: the loader must fill chosen/*, memory-map, cpu*/reg etc. like iBoot.
- XNU build: GitHub Actions (dipa-studio/ios-sweet, xnu.yml) via blacktop/darwin-xnu-build, MACOS_VERSION=13.5.
  New-clang fixes in xnu/patches; Xcode 16 iig is incompatible (IORPC.kernelContent) -> macos-14 runner, oldest Xcode.

## Kernel architecture plan (SWEET machine config)
- First stock build (VMAPPLE) is arm64e (PAC). Kryo 470 = ARMv8.2, no PAC -> SWEET must build plain arm64
  (HAS_APPLE_PAC is only defined for __arm64e__, so arm64 drops PAC automatically).
- Template: VMAPPLE (16K pages, GICv3 code in pe_fiq.c) minus APPLEVIRTUALPLATFORM hypercalls/paravirt PAC,
  plus BCM2837 (generic ARM: no APPLE_ARM64_ARCH_FAMILY Apple sysregs). Do not link the KDK lib<cfg>.os.*.a.
- Timer: XNU expects it on FIQ (sleh_fiq -> rtclock_intr). SWEET: GIC Group 1, so sleh_irq must ack ICC_IAR1,
  route INTID 19 to the same timer path, SGIs to cpu_signal_handler, EOI via ICC_EOIR1.
- SMP/interrupts: open-source AppleARMSMP (USE_APPLEARMSMP) needs an IOInterruptController (AIC role) and an
  IOPMGR (CPU power -> PSCI CPU_ON via SMC). Plan: built-in IOKit classes (SweetGIC, SweetPMGR, platform
  expert) compiled into the kernel and matched via iokit/KernelConfigTables.cpp -> no closed kexts needed.
- Debug: xnu patch 0003 sweet-fbcon = kprintf drawn on the framebuffer (ADT node "sweet-fbcon").
- ADT /arm-io ranges must not map to parent 0 (pe_arm_get_soc_base_phys()==0 disables serial): use parent 0x1000000.

## Status 2026-10-14 late: first XNU boot attempt
- SWEET kernel builds (CI run 38635343732, patches 0001-0009). Verified offline: arm64, no PAC, no >v8.2 code,
  70300 classic relocs all in range (slide 0 = no loader work), entry = __start.
- Boot: shim loader worked (initrd 0x846F0000-0x855FE3E0, BOOTARG 0xB1FF8000, JUMP 0xB146A488) but screen stayed
  red -> xnu died/hung before serial_init (fbcon). kprintf is a no-op before STARTUP_SUB_KPRINTF.
- Historical next-step plan (patch 0010, now implemented and built; see active handoff above): early fb debug channel
  1. start.s start_first_cpu (after mov x20,x0 / mov x21,#0): PA marker band (MMU off, direct store to 0x9c000000).
  2. start.s after both create_bootstrap_mapping calls: add ONE block entry to the existing V=P L2 table
     (x25 + 2*PGBYTES; do NOT call create_bootstrap_mapping again: fb and RAM share L1 entry 0, it would replace
     the L2 table). Entry = TYPE_BLOCK|VALID|SH(OUTER)|ATTRINDX(CACHE_ATTRINDX_WRITECOMB=1)|AF|PNX|NX|0x9c000000,
     index = (va & ARM_TT_L2_INDEX_MASK) >> ARM_TT_L2_SHIFT.
  3. new osfmk/arm64/sweet_early.c (+files.arm64 entry): sweet_early_mark(n) colored bands at screen bottom and
     sweet_early_putc using iso_font via VA=PA while the bootstrap TTBR0 is live; disable before
     arm_vm_init's set_mmu_ttb(invalid_ttep) (arm_vm_init.c:2148).
  4. markers in arm_init after PE_init_platform, ml_parse_cpu_topology, cpu_bootstrap, kernel_startup_bootstrap,
     cpu_init, before arm_vm_init.
  5. panic hook at top of panic_trap_to_debugger: va_copy + _doprnt(fmt, &copy, sweet_early_putc, 16).
  Verify with tools/xnu-cc.py (compile+symbols) and patch-order simulation before the single CI run.
