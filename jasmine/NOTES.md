# jasmine (Mi A2) working notes

Read this first. Plan: [PLAN.md](PLAN.md). Hardware: [HARDWARE.md](HARDWARE.md). GPU plan: [GPU.md](GPU.md).
`NOTES.md` at the repo root is sweet's/topaz's log, kept for reference.

## State (2026-10-20 ~22:45)

| Phase | State |
| --- | --- |
| 0 Prep | Nura fully backed up (70 images verified, 3.5 GB) in `Xiaomi A2/backup/nura-full-20261020/` (not in git). Fork `telegdyd/ios-jasmine`, branch `jasmine` |
| 1 Shim | Works. Silver `51AF8014` tg16=0, Gold `51AF8002` tg16=1, GIC/vtimer/SGI OK on Gold, PSCI 1.0, APSS WDT off |
| 2 XNU | Boots on 4 Gold cores (`cpus=4`), console on the 0x9d400000 splash. Panic/reboot/halt reset into **fastboot** (0138, PMIC PON) |
| 3 eMMC | Read path works (0137, ADMA2): EXT_CSD rev 8, 29820 MiB, HS200 8-bit, userdata at block 0x16c0000, 18171 MiB. Write path written, not yet exercised |
| 4 iOS root | **iOS 16 LOCK SCREEN on the Mi A2, 2026-10-20 ~22:40** (kernel 0139, `shim/out/shim-boot-ios-rwf139.img`, image `~/ios-work/root-build/ios16-root.simg` flashed to userdata 21:12). iPhone10,3 iOS 16.7.16 (20H392), 17 GiB HFS+ root. Writes verified: self-test OK, GPT copies unchanged after rw sessions |
| 5 Input | **Keys + clock work (0140, 2026-10-21 ~01:00)**: power, volume up/down reach backboardd; date correct with `rtcoffset=1790955133` (PMIC RTC raw + offset, measured 2026-10-21 00:16). **Touch works (0141, 2026-10-21 01:15)**: unlocked to the home screen and Spotlight. **Display fitted and tear-free (j0007, 2026-10-21 02:40)**: whole 1125x2436 iOS frame scaled to 997x2160 (status bar, home indicator visible), touch mapped through the same fit; Settings, App Library, keyboard typing work. Next: wallpaper/widgets (no app extensions, upstream issue), battery driver, charger driver in XNU |

## Roadmap (agreed 2026-10-21)

1. Battery life: charger setup (j0009) and battery readout (j0010), then panel brightness / real screen off over DSI DCS (topaz 0104-0110 style), stop the bluetoothd / fairplayd.H2 respawn loop.
2. ~~Standalone boot~~ **done 2026-10-21** (slot b, j0013 marks it successful).
3. CPU: **Gold clock, quick way (j0015, `sweetgold=MHz`)**: XBL leaves the Gold cluster on GPLL0 (~600 MHz; Silver on its PLL at 1382 MHz). j0015 moves Gold onto its own PLL at a downstream table step **without touching the voltage**, checked by a deterministic workload (one core at the switch, all four at 20 s; wrong results -> back to GPLL0). Then all 8 cores (4K pages, UniXNU).
   **Settled 2026-10-21 at a fixed 1747.2 MHz** (`sweetgold=1747` in the slot b image `shim/out/shim-boot-j16-slotb.img`): XBL's boot clock measured ~180 MHz (GPLL0 arrives divided), workload x6.05 at 1094, x5.78 at 1382, x6.23 at 1728 MHz vs boot; 1094/1382/1728 MHz all correct with 0 errors on four cores at XBL's voltage. Higher steps (1958/2150/2208, images built, j0016) not tested: the proper way replaces this anyway. No DVFS: fixed clock, no throttling (TSENS logged around the load check). Fallback if it ever misbehaves: `sweetgold=1401`.
   **TODO, the proper way:** port msm-4.4 `clk-cpu-osm.c` + `cprh` (sdm660.dtsi `qcom,clk-cpu-660@179c0000`, sdm660-regulator.dtsi `apc1_cpr` 0x179c4000): read the speed-bin and CPR fuses (0x784130, fuse_base 0x784000), build the OSM LUT (perfcl speed bin 1: 300/1113.6/1401.6/1747.2/1958.4/2150.4/2208 MHz, ceilings 724/724/788/868/988/988/1068 mV, floors 588..844 mV), program the OSM sequencer and APM (crossover 872 mV), enable CPRh closed loop. Then per-chip voltages, DVFS and the hardware limits (LMh) instead of a fixed clock at XBL's voltage. Facts found 2026-10-21: Gold PLL 0x17816000 (L 0x20, user 0xf, config 0x200d4828, mode 7), RCG 0x17811050 cmd 2 cfg 0x401; Silver PLL 0x17916000 L 0x48, RCG cfg 0x501; OSM version 0x70000, enable 0; SAW4 PMIC_STS and CPRH_STATUS 0 (never used); speed-bin fuse 0x784130 = 0x3040008c 0x88614230; the APC rails (PM660 S1-S3) are not readable from the apps EE.
4. Wi-Fi (WCN3990 on the modem DSP; topaz 0113-0130 as the model).
5. GPU: topaz runs CoreAnimation on its Adreno 610 with HackiOS's private patches (kernel driver + Mesa freedreno as the GL ES renderer), to be published in topaz once HackiOS publishes. `git fetch topaz` and check after each step; if still unpublished after 1-4, consider our own Adreno 512 (a5xx) work: firmware (a530_pm4/pfp, zap shader via TZ), GPU clocks/GX power, GPU SMMU, freedreno.

## Kernel patches (ours, on top of topaz's)

Ours are `xnu/patches/j0001-*` onward so they sort after every upstream topaz number (topaz kept going at 0136; merged 2026-10-21 with topaz 0136-0139). The WSL tree `~/xnu-8796` is `6d393c1 topaz-series` (0001-0135) + topaz 0136-0139 + ours, one commit each; `git format-patch` a new commit into the next j number.

- **j0001** (was 0136) board guards (SM6225-only drivers only on a `xiaomi,topaz` ADT), early console on jasmine's splash, `/sweet-reset` (PS_HOLD + IMEM) for reboot/halt/panic (`panicwait=` s, default 60).
- **j0002** (was 0137) eMMC backend in `bsd/dev/sweet_ufs.c` for ADT `/sweet-emmc`: SDHCI ADMA2 (64-bit, 12-byte descriptors), polled, Auto CMD12, 512-byte blocks. PIO did **not** work on this host (CMD8 never completed). Refuses if CQE is on or EXT_CSD is not user area / CMDQ off. Only CMD6 is FLUSH_CACHE.
- **j0004** (was 0139) eMMC: FLUSH_CACHE only when EXT_CSD reports an enabled cache (this card: CACHE_CTRL 0; a flush left SWITCH_ERROR, status 0x980, on the next write = the journal header, and HFS returned EINVAL for everything); R1 check logs twice; write self-test at attach with `ufsrw=1`.
- **j0005** (was 0140) `bsd/dev/sweet_pmic.c` (ADT `/sweet-pmic`): keys polled every 20 ms on the arbiter observer channels (PON 0x810 bit 0 power, bit 1 volume down; PM660L GPIO7 0xc610 volume up, active low), PM660 RTC (RDATA 0x6048) + `rtcoffset=` as the calendar clock (SweetPlatformExpert get/setUTCTimeOfDay, publishes IORTC). Read only.
- **j0006** (was 0141) `bsd/dev/sweet_nvt.c` (ADT `/sweet-touch`): NT36672A at 0x01 on BLSP1 QUP1 (0xc175000, QUP v2 0x20070000, FIFOs 64/64), polled FIFO-mode v2-tag I2C at 400 kHz, clocks from GCC (AHB vote 0x52004 bit 17 was already set by ABL; QUP1 core RCG 0x19020 from XO, CBCR 0x19008). ABL leaves the touch reset (GPIO 66) high, so the controller answers at once (params `25 da 12 20 04 38 08 70 0e 0a 00 01 01 00 08`: 1080x2160, 10 touches, irq type 1 = falling, chip 8). 100 Hz polling, one record idle. SweetHIDTouch takes the panel size from the boot console.
- **j0007** jasmine MDP flips + fit (ADT `/sweet-mdp`): ABL scans the splash with **VIG0 at physical 0x9d400000** (no SMMU translation), staged by **CTL_0** (layer 0x1000005); two back buffers at 0x9dd00000 / 0x9e600000 inside the splash reservation `memory@9d400000` (0x23ff000), mapped write-combined through an IOMemoryDescriptor (`ml_io_map_wcomb` of 9 MB panicked: `kmem_alloc ... failed with 3`), flipped with SSPP_SRC0_ADDR + CTL_FLUSH (VIG0 bit 0 + CTL bit 17). Fit: nearest-sample scale of the 1125x2436 frame to 997x2160 at x 40; SweetHIDTouch maps through it (`sweet_fit_x/w`). `sweetmdp=0` = old CPU copy into the boot framebuffer (cropped), `sweetfb_fit=0` = crop.
- **j0008** logs every swap layout change: iOS always sends one full-screen 1125x2436 BGRA layer (surfaces 2/3 alternating), even with Spotlight and the keyboard up.
- **j0009** PM660 charger (Linux qcom_smbx init + Nura fixes): before it the input limit was 50-500 mA; after: DCP/CDP 1.5 A input, +0.6..0.83 A into the battery, 3.945 V float (`chgmv=`, `chgfcc=`, `chgicl=`, `sweetchg=0`).
- **j0010** battery readout from the PM660 FG (`/sweet-pmic fg`), SweetBattery on jasmine (3000 mAh, measured temperature). **j0012** IR-corrected (110 mOhm) averaged percent, 1 %/poll.
- **j0011** PM660L WLED: backlight off/on with the display (`sweetbl_level=`, `sweetbl=1` for the slider); PMIC and touch set up before `registerService`.
- **j0013** A/B: `abmark=a|b` marks boot_<slot> successful in both GPT copies 60 s after the root mounts (validated, read back; the GPT watchdog follows).
- **j0003** (was 0138) reset into fastboot: PM660 PON SOFT_RB_SPARE 0x88f = bootloader (2 << 1) through the SPMI arbiter v3 (apid 4). jasmine's ABL ignores the IMEM restart reason.

Build: `gh workflow run xnu.yml -R telegdyd/ios-jasmine --ref jasmine` (macOS runner, ~6-8 min), artifact `xnu-kernel`. Patches are written against a local patched tree in WSL `~/xnu-8796` (topaz series applied after running `xnu/patches/*.sh` with `MACHINE_CONFIG=SWEET MACOS_VERSION=13.5`).

## Standalone boot (since 2026-10-21 04:13)

- **Slot b = iOS:** `boot_b` holds the shim image built with `abmark=b` (since 2026-10-21 06:25: `shim/out/shim-boot-j17-slotb.img`, j0017 kernel, `sweetgold=1747`), `vbmeta_b` = `images/vbmeta-disabled.img`, active slot b. Power-on, reboot and charger plug-in boot iOS. The kernel (j0013) marks boot_b successful 60 s after the root mounts, so ABL never falls back (verified: `fastboot getvar slot-successful:b` = yes; both GPT copies valid; only bit 54 of entry 62 written by us).
- `fastboot set_active` also swaps the partition **type GUIDs** of every `_a`/`_b` pair (xbl, tz, abl, modem, ...): slot b's firmware chain (stock Android's) now boots the phone. Expected Qualcomm behaviour.
- **Linux shell:** `fastboot boot shim/out/nura-r109-boot_a.img` (the r109 boot_a from the backup; RAM only, slot stays b). Charging there: screen off + 3.95 V as in the charging-shell note.
- **New iOS kernel:** build the image with `abmark=b`, `fastboot flash boot_b IMG`. Test kernels: build without `abmark` and `fastboot boot` them (no GPT writes).
- **Back to Nura:** `fastboot set_active a` (boot_a untouched). Restore boot_b / vbmeta_b from `backup/nura-full-20261020/p63_boot_b.img.gz` / `p08_vbmeta_b.img.gz` if needed.

## Test loop

1. Phone in fastboot (after any XNU reset it is there by itself; otherwise Power + Volume Down).
2. `fastboot boot shim/out/<image>.img` (RAM only, nothing flashed).
3. Images: `tools/mkadt.py shim/out/jasmine.adt --highmem`, `tools/mkpayload.py KERNEL ADT PAYLOAD --cmdline '...'`, `shim/build.sh PAYLOAD` (BOARD=jasmine default; v0 boot image with the Nura DTB from `dtb/jasmine.dtb`).
4. Read-only test boot-args: `debug=0xc serial=3 cpus=4 keepsyms=1 -noprogress rd=ufsroot0 ufsroot=userdata unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 panicwait=60 sweetfb_hz=30`; read-write adds `ufsrw=1 rootrw=1`.

## Linux shell without a recovery

**Charging shell (use this one):** `fastboot reboot` boots boot_a = the r109 Nura kernel (charger HC/ICL and OSI idle patches), which finds no root and stops in the initramfs debug shell (telnet 172.16.42.1). Then `tools/pmos-shell.py 'echo 0 > /sys/class/backlight/backlight/brightness; echo 3950000 > /sys/class/power_supply/pm660-charger/constant_charge_voltage'`: about +0.9 A into the battery on the PC port. `shim/out/nura-debugshell.img` is built from `images/boot.img` (stock 2026-10-02 kernel: 500 mA input cap, no cluster idle) and **discharges** even on a charger; use it only if boot_a is gone.


`fastboot boot shim/out/nura-debugshell.img` (Nura kernel + initramfs, `pmos.debug-shell`): telnet on 172.16.42.1, nothing mounted. `tools/pmos-shell.py 'cmd'`, `tools/pmos-shell.py --raw 'dd if=/dev/mmcblk1 ...' > file`. In that kernel the eMMC is `mmcblk1`, userdata `mmcblk1p69` (start 23855104, 37216223 sectors). Use it to read the persistent log (last 4 MiB + 4 KiB of userdata) and to compare the GPT with the backup after read-write sessions.

## Host setup (WSL Debian 13)

- `gcc-aarch64-linux-gnu`, `mkbootimg`, `img2simg`, `unzip`, `hfsprogs` (non-free .deb from deb.debian.org), `apfs-fuse` + `lzfse` built from source in `~/ios-work`.
- WSL2's kernel has no hfsplus: `~/ios-work/wsl-kernel` = microsoft/WSL2-Linux-Kernel `linux-msft-wsl-6.18.54.1`, running config + `HFSPLUS_FS=m`, built with `CC=gcc-13 HOSTCC=gcc-13 KERNELRELEASE=$(uname -r)` (GCC 14 changes the modversion CRCs), `Module.symvers` from `vmlinux.symvers`. Module in `/lib/modules/$(uname -r)/extra/` (`sudo modprobe hfsplus` after a WSL restart).
- IPSW `~/ios-work/ipsw/iPhone10,3_16.7.16_20H392_Restore.ipsw` (Apple CDN, SHA-1 verified). Root: `tools/build-ios-root.sh IPSW ~/ios-work/root-build` -> `ios16-root.img` / `.simg`.
- Run WSL commands from script files (inline variables get lost through `wsl.exe`), and write files on Windows in binary mode (CRLF breaks bash).

## Known issues / findings

- **Battery: XNU has no charger driver and no low-battery shutdown.** 2026-10-20 the lock screen ran the battery flat on PC USB. Keep sessions short. When the phone auto-boots on a charger (`oem off-mode-charge 0`) it lands in Nura's initramfs debug shell (no root), where the patched charger driver does charge; turn the screen off there: `tools/pmos-shell.py 'echo 0 > /sys/class/backlight/backlight/brightness'`. `fastboot getvar battery-voltage` reads the cell in fastboot.
- iOS log of the lock screen boot: `logs/boot-0139-lockscreen.txt` (`tools/sweet-log.py` on the ring pulled with `dd if=/dev/mmcblk1 bs=512 skip=61063134 count=8193`). PosterBoard crashes with SIGTRAP (no wallpaper); bluetoothd and fairplayd.H2 respawn ~140 times each.
- Respawn loop: **fairplayd.H2 is out of service** (launchd.plist patched in place on the phone 2026-10-21 03:53 with `tools/launchd-disable-inplace.py`: blocks 76 and 87 of the file at partition 4K block 1966695, sha256 3a6e896d...; original 7b41fa30...). **bluetoothd still starts** (at boot and about every 10 s) although its only job in the cache now has no MachServices/LaunchEvents and RunAtLoad/KeepAlive false: something else brings it up; not chased further (a few % CPU).
- Flashing boot_b makes ABL clear its successful bit (`slot-successful:b: no` right after the flash); the next boot with `abmark=b` sets it again.
- **Memory bandwidth (j0017, 2026-10-21):** XNU, one Gold core at 1747 MHz: write 7.6 GB/s, read 6.4 GB/s, copy 3.2 GB/s (Linux initramfs reference, Gold: 4.8 / 3.5 / 3.1 GB/s). RAM is not the brake (a 9 MB frame copy is ~3 ms); the lag is CoreAnimation's software rendering. TSENS: 55-69 C at 1747 MHz while charging, no rise under the 2 s four-core load.
- Settings (Preferences, pc 0) and Photos (abort) crashed once each in the j0012 sessions; Settings opened fine on 2026-10-21 02:40.
- j0012 battery: percent from the IR-corrected (110 mOhm) averaged rest voltage; 46-50 % at 3.78-3.79 V while the gauge said 51-52 %.
- `sweetlog=WORD,...` has no effect (conflicts with 0047's integer parse of the same boot-arg).

- Under Nura's Linux, sustained eMMC reads hung the controller (CQE timeout, "cqhci: Failed to halt") and twice `reboot bootloader` from Nura hung. Linux sdhci-msm CQE on this Hynix eMMC; our XNU driver keeps CQE off.
- Shim speed probe: Gold looks 55x slower than Silver with the MMU off; under Linux Gold is about Silver's speed, so it is an MMU-off artifact, but the Gold clock is probably lowish (no CPU clock driver).
- jasmine ABL does not honor IMEM restart reasons (fixed with 0138).
