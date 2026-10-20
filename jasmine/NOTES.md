# jasmine (Mi A2) working notes

Read this first. Plan: [PLAN.md](PLAN.md). Hardware: [HARDWARE.md](HARDWARE.md).
`NOTES.md` at the repo root is sweet's/topaz's log, kept for reference.

## State (2026-10-20 ~22:45)

| Phase | State |
| --- | --- |
| 0 Prep | Nura fully backed up (70 images verified, 3.5 GB) in `Xiaomi A2/backup/nura-full-20261020/` (not in git). Fork `telegdyd/ios-jasmine`, branch `jasmine` |
| 1 Shim | Works. Silver `51AF8014` tg16=0, Gold `51AF8002` tg16=1, GIC/vtimer/SGI OK on Gold, PSCI 1.0, APSS WDT off |
| 2 XNU | Boots on 4 Gold cores (`cpus=4`), console on the 0x9d400000 splash. Panic/reboot/halt reset into **fastboot** (0138, PMIC PON) |
| 3 eMMC | Read path works (0137, ADMA2): EXT_CSD rev 8, 29820 MiB, HS200 8-bit, userdata at block 0x16c0000, 18171 MiB. Write path written, not yet exercised |
| 4 iOS root | **iOS 16 LOCK SCREEN on the Mi A2, 2026-10-20 ~22:40** (kernel 0139, `shim/out/shim-boot-ios-rwf139.img`, image `~/ios-work/root-build/ios16-root.simg` flashed to userdata 21:12). iPhone10,3 iOS 16.7.16 (20H392), 17 GiB HFS+ root. Writes verified: self-test OK, GPT copies unchanged after rw sessions |
| 5 Input | **Keys + clock work (0140, 2026-10-21 ~01:00)**: power, volume up/down reach backboardd; date correct with `rtcoffset=1790955133` (PMIC RTC raw + offset, measured 2026-10-21 00:16). **Touch works (0141, 2026-10-21 01:15)**: unlocked to the home screen and Spotlight. Next: display (canvas fit, compositor artifacts on blurred/translucent layers) |

## Kernel patches (ours, on top of topaz's)

Ours are `xnu/patches/j0001-*` onward so they sort after every upstream topaz number (topaz kept going at 0136; merged 2026-10-21 with topaz 0136-0139). The WSL tree `~/xnu-8796` is `6d393c1 topaz-series` (0001-0135) + topaz 0136-0139 + ours, one commit each; `git format-patch` a new commit into the next j number.

- **j0001** (was 0136) board guards (SM6225-only drivers only on a `xiaomi,topaz` ADT), early console on jasmine's splash, `/sweet-reset` (PS_HOLD + IMEM) for reboot/halt/panic (`panicwait=` s, default 60).
- **j0002** (was 0137) eMMC backend in `bsd/dev/sweet_ufs.c` for ADT `/sweet-emmc`: SDHCI ADMA2 (64-bit, 12-byte descriptors), polled, Auto CMD12, 512-byte blocks. PIO did **not** work on this host (CMD8 never completed). Refuses if CQE is on or EXT_CSD is not user area / CMDQ off. Only CMD6 is FLUSH_CACHE.
- **j0004** (was 0139) eMMC: FLUSH_CACHE only when EXT_CSD reports an enabled cache (this card: CACHE_CTRL 0; a flush left SWITCH_ERROR, status 0x980, on the next write = the journal header, and HFS returned EINVAL for everything); R1 check logs twice; write self-test at attach with `ufsrw=1`.
- **j0005** (was 0140) `bsd/dev/sweet_pmic.c` (ADT `/sweet-pmic`): keys polled every 20 ms on the arbiter observer channels (PON 0x810 bit 0 power, bit 1 volume down; PM660L GPIO7 0xc610 volume up, active low), PM660 RTC (RDATA 0x6048) + `rtcoffset=` as the calendar clock (SweetPlatformExpert get/setUTCTimeOfDay, publishes IORTC). Read only.
- **j0006** (was 0141) `bsd/dev/sweet_nvt.c` (ADT `/sweet-touch`): NT36672A at 0x01 on BLSP1 QUP1 (0xc175000, QUP v2 0x20070000, FIFOs 64/64), polled FIFO-mode v2-tag I2C at 400 kHz, clocks from GCC (AHB vote 0x52004 bit 17 was already set by ABL; QUP1 core RCG 0x19020 from XO, CBCR 0x19008). ABL leaves the touch reset (GPIO 66) high, so the controller answers at once (params `25 da 12 20 04 38 08 70 0e 0a 00 01 01 00 08`: 1080x2160, 10 touches, irq type 1 = falling, chip 8). 100 Hz polling, one record idle. SweetHIDTouch takes the panel size from the boot console.
- **j0003** (was 0138) reset into fastboot: PM660 PON SOFT_RB_SPARE 0x88f = bootloader (2 << 1) through the SPMI arbiter v3 (apid 4). jasmine's ABL ignores the IMEM restart reason.

Build: `gh workflow run xnu.yml -R telegdyd/ios-jasmine --ref jasmine` (macOS runner, ~6-8 min), artifact `xnu-kernel`. Patches are written against a local patched tree in WSL `~/xnu-8796` (topaz series applied after running `xnu/patches/*.sh` with `MACHINE_CONFIG=SWEET MACOS_VERSION=13.5`).

## Test loop

1. Phone in fastboot (after any XNU reset it is there by itself; otherwise Power + Volume Down).
2. `fastboot boot shim/out/<image>.img` (RAM only, nothing flashed).
3. Images: `tools/mkadt.py shim/out/jasmine.adt --highmem`, `tools/mkpayload.py KERNEL ADT PAYLOAD --cmdline '...'`, `shim/build.sh PAYLOAD` (BOARD=jasmine default; v0 boot image with the Nura DTB from `dtb/jasmine.dtb`).
4. Read-only test boot-args: `debug=0xc serial=3 cpus=4 keepsyms=1 -noprogress rd=ufsroot0 ufsroot=userdata unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 panicwait=60 sweetfb_hz=30`; read-write adds `ufsrw=1 rootrw=1`.

## Linux shell without a recovery

`fastboot boot shim/out/nura-debugshell.img` (Nura kernel + initramfs, `pmos.debug-shell`): telnet on 172.16.42.1, nothing mounted. `tools/pmos-shell.py 'cmd'`, `tools/pmos-shell.py --raw 'dd if=/dev/mmcblk1 ...' > file`. In that kernel the eMMC is `mmcblk1`, userdata `mmcblk1p69` (start 23855104, 37216223 sectors). Use it to read the persistent log (last 4 MiB + 4 KiB of userdata) and to compare the GPT with the backup after read-write sessions.

## Host setup (WSL Debian 13)

- `gcc-aarch64-linux-gnu`, `mkbootimg`, `img2simg`, `unzip`, `hfsprogs` (non-free .deb from deb.debian.org), `apfs-fuse` + `lzfse` built from source in `~/ios-work`.
- WSL2's kernel has no hfsplus: `~/ios-work/wsl-kernel` = microsoft/WSL2-Linux-Kernel `linux-msft-wsl-6.18.54.1`, running config + `HFSPLUS_FS=m`, built with `CC=gcc-13 HOSTCC=gcc-13 KERNELRELEASE=$(uname -r)` (GCC 14 changes the modversion CRCs), `Module.symvers` from `vmlinux.symvers`. Module in `/lib/modules/$(uname -r)/extra/` (`sudo modprobe hfsplus` after a WSL restart).
- IPSW `~/ios-work/ipsw/iPhone10,3_16.7.16_20H392_Restore.ipsw` (Apple CDN, SHA-1 verified). Root: `tools/build-ios-root.sh IPSW ~/ios-work/root-build` -> `ios16-root.img` / `.simg`.
- Run WSL commands from script files (inline variables get lost through `wsl.exe`), and write files on Windows in binary mode (CRLF breaks bash).

## Known issues / findings

- **Battery: XNU has no charger driver and no low-battery shutdown.** 2026-10-20 the lock screen ran the battery flat on PC USB. Keep sessions short. When the phone auto-boots on a charger (`oem off-mode-charge 0`) it lands in Nura's initramfs debug shell (no root), where the patched charger driver does charge; turn the screen off there: `tools/pmos-shell.py 'echo 0 > /sys/class/backlight/backlight/brightness'`. `fastboot getvar battery-voltage` reads the cell in fastboot.
- iOS log of the lock screen boot: `logs/boot-0139-lockscreen.txt` (`tools/sweet-log.py` on the ring pulled with `dd if=/dev/mmcblk1 bs=512 skip=61063134 count=8193`). PosterBoard crashes with SIGTRAP (no wallpaper); bluetoothd and fairplayd.H2 respawn ~140 times each.
- `sweetlog=WORD,...` has no effect (conflicts with 0047's integer parse of the same boot-arg).

- Under Nura's Linux, sustained eMMC reads hung the controller (CQE timeout, "cqhci: Failed to halt") and twice `reboot bootloader` from Nura hung. Linux sdhci-msm CQE on this Hynix eMMC; our XNU driver keeps CQE off.
- Shim speed probe: Gold looks 55x slower than Silver with the MMU off; under Linux Gold is about Silver's speed, so it is an MMU-off artifact, but the Gold clock is probably lowish (no CPU clock driver).
- jasmine ABL does not honor IMEM restart reasons (fixed with 0138).
