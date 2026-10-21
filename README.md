# ios-jasmine

**Apple's iOS 16 running on a Xiaomi Mi A2.**

This is a port of [MakrSas/ios-topaz](https://github.com/MakrSas/ios-topaz) (itself a port of [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet): Apple's open-source XNU kernel, xnu-8796, on a Qualcomm phone) to the Xiaomi **Mi A2** (`jasmine`, Qualcomm **SDM660** / Snapdragon 660, 4 GB). On top of it runs the **unmodified iOS 16.7.16 (20H392) userland of the iPhone X**: launchd, the system daemons, backboardd and SpringBoard.

As of **2026-10-21** the phone **boots iOS by itself** (power on, reboot or charger plug-in) to the lock screen and the **home screen**, with **touch, power and volume keys**, the right **date and time**, **charging and a battery percentage**, the backlight switching off with the display, and the CPU at 1.75 GHz. Settings, the App Library and the keyboard work. In the kernel, the **Adreno 512 GPU** is powered up and executes our command streams, and a **USB Ethernet** link streams the kernel log to the PC live. CoreAnimation still renders in software, so the UI is slow: getting it onto the GPU is the current work (see the roadmap).

> Experimental bring-up, not a usable phone OS. Many things are missing or stubbed, and Apple's security model is mostly switched off. iOS installs into the `userdata` partition and so **erases Android's user data**, and the standalone boot replaces `boot_b` / `vbmeta_b`. Keep a backup of every partition before you start.

## What works

| Area | State |
| --- | --- |
| Boot | Stock Xiaomi ABL (unlocked). Standalone: slot b's `boot_b` holds our shim + XNU, `vbmeta_b` has verification off, and the kernel marks the slot successful in the GPT 60 s after the root mounts (`abmark=b`, j0013), so ABL never falls back. Test kernels run from RAM with `fastboot boot`. Every reboot and panic lands in fastboot (PMIC PON reboot mode, j0003) |
| CPU | The four Kryo 260 Gold cores (MPIDR `0x100`–`0x103`), 16K pages, GICv3, timers. XBL leaves Gold at ~180 MHz: j0015/j0016 move it onto its own PLL at a fixed **1747 MHz**, checked by a workload on all four cores. The Silver cores are parked (see below) |
| Memory | 1.97 GiB at `0x1_00000000` (the part of the upper DDR bank above every carve-out) |
| Storage | Our own eMMC driver (SDHCI with ADMA2, HS200 8-bit, polled); the iOS root is a journaled HFS+ volume in `userdata`, read/write |
| iOS userland | Real iPhone X 16.7.16 root filesystem and shared cache |
| Display | The MDP pipe ABL lit for its splash (VIG0) flips between two back buffers, tear-free. iOS draws an iPhone X frame (1125×2436), scaled to fit the 1080×2160 panel (996×2160, nearest sample, on the CPU) |
| GUI | backboardd, SpringBoard, lock screen, home screen, Spotlight, Settings, App Library, keyboard |
| Touch | Novatek NT36672A on the old QUP v2 I2C (BLSP1 QUP1), polled, mapped through the same fit as the display |
| Keys and clock | Power and volume down from the PM660 PON, volume up from PM660L GPIO 7, all over the SPMI arbiter v3; the calendar from the PM660 RTC plus `rtcoffset=` |
| Battery | PM660 charger set up like Linux's `qcom_smbx` (1.5 A input, 3.95 V float, ~0.6–0.8 A into the cell), fuel gauge read out (voltage, current, temperature), percent shown in iOS; the PM660L WLED backlight goes off with the display |
| USB | The DWC3 (set up by the kernel itself after a normal boot, j0023) is a **CDC-NCM Ethernet gadget** (Windows, Linux and macOS drivers built in). The kernel log streams live over TCP (`tools/sweet-netlog.py`, 192.168.7.2 or 169.254.7.2 port 5140); a command port (5141) reboots the phone into fastboot on request, so `tools/sweet-run.py IMAGE LOG` runs a whole test round (reboot, `fastboot boot`, live log) without touching the phone |
| GPU (kernel only) | Adreno 512 power-up (GFX head switch, GPU GDSCs), GPU PLL at 266 MHz, GPU SMMU page tables, microcode, command ring, zap shader loaded through TrustZone: the GPU executes our command streams. Opt-in (`sweetgpu=`), not used for rendering yet |
| Device identity | iPhone X (`iPhone10,3` / `D22AP`): no Home button, gesture UI |

## What does not work (yet)

- **No GPU rendering**: CoreAnimation renders on the CPU, so the UI lags; WebKit wants a GPU, so Safari shows blank pages.
- **No Wi-Fi, Bluetooth, cellular, audio, camera, sensors, fingerprint, GPS, SEP.** `bluetoothd` relaunches every few seconds because its hardware is missing.
- **Only 4 of 8 cores**, at a fixed clock: no frequency scaling and no thermal throttling yet.
- **Some apps and panels crash**: some Settings panels and Photos.
- **Wallpaper and widgets**: LaunchServices registers apps but no app extensions on this root, so PosterBoard finds no wallpaper provider (the same in topaz).
- **Brightness**: the backlight is only switched on and off.
- **Security is off**: permissive AMFI and sandbox, stub AppleKeyStore, no data protection.

## How jasmine differs from topaz

| Problem | Fix |
| --- | --- |
| **eMMC**, not UFS | An SDHCI backend for the sweet disk driver (j0002): ADMA2 with 12-byte descriptors, Auto CMD12, polled. PIO never completed a command on this host. Command queueing stays off (it hung the controller under Linux), and FLUSH_CACHE is only sent when EXT_CSD reports an enabled cache (j0004) |
| ABL ignores the IMEM restart reason | Reset into fastboot through the PM660 PON `SOFT_RB_SPARE` reboot mode over SPMI (j0003) |
| Same Kryo 260 cores as topaz (Silver `0x51AF8014` without the 16K granule, Gold `0x51AF8002`) | topaz's Gold-only boot carries over unchanged; XBL leaves Gold on GPLL0 at ~180 MHz, so the kernel moves it onto its own PLL (j0015) |
| Touch is on the **old QUP v2** I2C, not GENI | A polled QUP v2 I2C driver (FIFO mode, v2 tags) for the NT36672A, clocks from GCC (j0006) |
| Keys are PMIC inputs, not GPIOs | Read through the SPMI arbiter v3 observer channels (j0005) |
| No GPU code to borrow: HackiOS's Adreno work is unpublished and a6xx, UniXNU's is a7xx Vulkan, and Mesa has no Vulkan driver for a5xx | Our own bring-up (j0018–j0020), heading for Mesa freedreno's GL driver behind iOS's OpenGL ES (`jasmine/GPU.md`) |
| A/B phone; topaz only RAM-boots | Standalone boot from `boot_b`, slot marked successful by the kernel (j0013) |
| Different MMIO map | GIC `0x17a00000`/`0x17b00000`, eMMC `0xc0c4000`, splash framebuffer `0x9d400000` (1080×2160), PS_HOLD `0x10ac000`, SPMI `0x800f000`, MDP `0xc901000`, GPU `0x5000000`, USB `0xa800000` |

### Why only the Gold cores

XNU for iOS uses 16K pages for the kernel and the userland on every CPU, and the Silver cores cannot translate 16K pages. Using all eight cores needs a 4K-page XNU (as in [UniXNU](https://github.com/UniXNU/UniXNU)); it is on the roadmap. The RAM bandwidth of one Gold core (6.4 GB/s read) is not what makes the UI slow, so the GPU comes first.

## How it boots

```
ABL (stock Xiaomi bootloader, unlocked)
  -> boot_b (standalone) or `fastboot boot shim-boot.img` (boot image v0, RAM only)
     -> shim on Silver CPU0: wakes Gold CPU 0x100 (PSCI CPU_ON), parks
        -> shim on Gold: GIC setup, finds the payload behind _end
           -> XNU Mach-O + Apple Device Tree (ADT) + boot-args
              -> eMMC driver -> HFS+ root in userdata
                 -> dyld + shared cache -> launchd -> backboardd + SpringBoard
```

There is no serial console. The kernel draws its console into ABL's splash framebuffer until iOS takes over the display, keeps a persistent log ring at the end of `userdata` (flushed every `ufslogsecs=` seconds), and, with USB connected, serves the same log live over USB Ethernet.

## How to do it yourself

You need a Mi A2 (`jasmine`, SDM660) with an **unlocked bootloader**, a PC with `fastboot`, a Linux environment (WSL works) and a GitHub account for the kernel build. **Back up every partition first.** `userdata` is erased; the standalone boot writes `boot_b` and `vbmeta_b` and makes slot b active (`fastboot set_active` also switches the firmware partitions of the slot).

1. **Kernel**: fork the repo and run the CI build on the `jasmine` branch (macOS runner, about 6 minutes):
   ```sh
   gh workflow run xnu.yml -R YOU/ios-jasmine --ref jasmine
   gh run download RUN_ID -R YOU/ios-jasmine -n xnu-kernel -D xnu/out-jasmine
   ```
2. **iOS root**: from the iPhone X (iPhone10,3) iOS 16.7.16 (20H392) IPSW, `tools/build-ios-root.sh IPSW OUTDIR` builds the HFS+ image (`apfs-fuse`, `hfsprogs`), adjusted by `tools/sweet-root-tweaks.py`. The device tree builder also wants `/product` from the real iPhone X device tree in `research/ipsw-x/d22ap.adt` (see topaz's README).
3. **Boot image** (`aarch64-linux-gnu-gcc`, AOSP `mkbootimg`):
   ```sh
   python3 tools/mkadt.py shim/out/jasmine.adt --highmem
   python3 tools/mkpayload.py xnu/out-jasmine/kernel.development.sweet shim/out/jasmine.adt shim/out/payload.bin \
       --cmdline 'debug=0xc serial=3 cpus=4 keepsyms=1 -noprogress rd=ufsroot0 ufsroot=userdata unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 panicwait=60 sweetfb_hz=30 ufsrw=1 rootrw=1 rtcoffset=SECONDS sweetgold=1747'
   bash shim/build.sh shim/out/payload.bin      # -> shim/out/shim-boot.img
   ```
   `rtcoffset` is the Unix time minus the PMIC RTC's raw seconds (read once from Linux). The GPU firmware (`a530_pm4.fw`, `a530_pfp.fw`, `a512_zap.*` from the stock `vendor` partition's `/firmware`) goes into `research/gpu-fw`; without it the GPU code just stays off.
4. **Root and first boot**: `fastboot -S 512M flash userdata ios16-root.simg`, then `fastboot boot shim/out/shim-boot.img`. The first boot sits on the Apple logo for a few minutes while LaunchServices builds its database.
5. **Standalone**: build the image again with `abmark=b` added, `fastboot flash boot_b` it, flash a `vbmeta_b` with verification disabled, `fastboot set_active b`.

| Boot-arg | Effect |
| --- | --- |
| `rd=ufsroot0 ufsroot=userdata ufsrw=1 rootrw=1` | Root on `userdata`, writable |
| `cpus=4` | The four Gold cores (`cpus=1` is the safe fallback) |
| `sweetgold=1747` | Gold cluster clock in MHz (1113, 1401, 1747 tested; 0 = leave XBL's) |
| `rtcoffset=` | Seconds added to the PMIC RTC |
| `abmark=b` | Mark `boot_b` successful once the root is up (standalone image only) |
| `chgmv=`, `chgfcc=`, `chgicl=`, `sweetchg=0` | Charger float voltage, charge current, input limit; `0` leaves the charger alone |
| `sweetgpu=1/2/3`, `gpumhz=160/266` | GPU bring-up steps (power, command processor, zap shader), GPU clock |
| `sweetusb=0`, `sweetusblog=0`, `sweetusbcmd=0` | USB Ethernet, live log, command port off |
| `ufslogsecs=` | Persistent log flush interval (default 10 s) |
| `sweetmdp=0`, `sweetfb_fit=0` | Old CPU copy into the boot framebuffer; crop instead of fitting |

## Roadmap

1. ~~Input, clock, display fit~~, ~~charging and battery~~, ~~standalone boot~~: done.
2. **CPU**: ~~Gold clock~~ (fixed 1747 MHz). Next, the proper way: OSM + CPRh with the fused voltages, frequency scaling and thermal limits. Later, all 8 cores with a 4K-page XNU.
3. **GPU (Adreno 512), in progress** (`jasmine/GPU.md`):
   - G1, the GPU in the kernel: ~~power~~, ~~command processor~~, ~~zap shader~~, ~~266 MHz~~. Next: an RPM client for the voltage vote (up to 750 MHz), then a first real job.
   - G2, CoreAnimation on the GPU: Mesa freedreno (Gallium, a5xx) built for iOS, behind iOS's OpenGL ES. iOS picks its GL renderer bundle by the `IOGLESBundleName` property of the kernel's `IOAcceleratorES` service, so our own `gld*` renderer plugs in without changing iOS binaries.
4. **USB**: ~~Ethernet, live log, command port, hands-free test loop~~. Next: file transfer into the iOS root, and a hardware watchdog so a hung test also comes back by itself.
5. **Wi-Fi** (WCN3990 behind the modem DSP; topaz's `TopazModem` is the model).
6. Brightness over DSI DCS, stopping the `bluetoothd` respawn loop, audio.

## Repository layout

| Path | What |
| --- | --- |
| `jasmine/` | **Start here**: working notes (`NOTES.md`), the plan (`PLAN.md`), hardware facts (`HARDWARE.md`), the GPU plan and findings (`GPU.md`) |
| `logs/` | Kernel logs of the test boots that settled something |
| `shim/` | Bare-metal boot shim (C + asm), Gold hand-off, GIC setup, payload loader |
| `xnu/patches/` | XNU patch series, applied in order by CI: sweet's 0001–0079, topaz's 0080–0139, jasmine's j0001+ |
| `.github/workflows/xnu.yml` | Kernel CI build |
| `tools/mkadt.py`, `tools/mkpayload.py` | Apple Device Tree for jasmine (cores, memory, MMIO, `/sweet-*` driver nodes, GPU firmware) and the payload packer |
| `tools/build-ios-root.sh`, `tools/sweet-root-tweaks.py`, `tools/launchd-disable-inplace.py` | Build and adjust the HFS+ iOS root |
| `tools/sweet-netlog.py`, `tools/sweet-cmd.py`, `tools/sweet-run.py` | Live log, kernel commands and a one-round test runner over USB Ethernet |
| `tools/pmos-shell.py`, `tools/pmos-push.py`, `tools/sweet-log.py` | The postmarketOS initramfs shell over USB (commands, file copy) and the persistent-log reader |
| `NOTES.md` (root) | sweet's and topaz's engineering log |

Not in git: partition backups, live device trees, Apple and Qualcomm firmware, root images, build trees.

## jasmine kernel patches

| # | What |
| --- | --- |
| j0001 | Board guards (SM6225-only drivers only on a topaz ADT), early console on jasmine's splash, reset and panic paths |
| j0002, j0004 | eMMC backend (SDHCI ADMA2) for the sweet disk driver; FLUSH_CACHE only with an enabled cache, write self-test |
| j0003 | Reset into fastboot through the PM660 PON reboot mode |
| j0005 | PMIC keys and RTC over the SPMI arbiter v3 |
| j0006 | NT36672A touch on BLSP1 QUP1 (polled QUP v2 I2C) |
| j0007, j0008 | Tear-free MDP flips and fit-to-screen; swap layout logging |
| j0009, j0010, j0012 | PM660 charger setup; fuel gauge readout and battery percent |
| j0011 | PM660L WLED backlight off with the display |
| j0013 | Mark the booted A/B slot successful |
| j0014–j0017 | CPU clock probe, Gold cluster onto its PLL (`sweetgold=`), clock table, memory bandwidth |
| j0018 | Adreno 512 bring-up: power, GPU SMMU, microcode, command processor (`sweetgpu=`) |
| j0019 | Zap shader through TrustZone, command processor out of secure mode |
| j0020 | GPU clock from the GPU PLL (`gpumhz=`) |
| j0021 | USB Ethernet (CDC-NCM) and the live log server |
| j0022 | USB command port (`reboot`), USB Ethernet on by default on jasmine |
| j0023 | USB after a normal boot: QUSB2 PHY init and DWC3 setup (ABL only sets USB up for fastboot) |

## Key hardware facts (jasmine)

- SoC SDM660: 4× Kryo 260 Silver (A53 class, MPIDR `0x0`–`0x3`) + 4× Kryo 260 Gold (A73 class, `0x100`–`0x103`). Only Gold has the 16K granule.
- 4 GB LPDDR4; the kernel uses `0x1_00000000` + 1.97 GiB. 32 GB eMMC (Hynix, HS200).
- GICv3 at `0x17a00000` (redistributors `0x17b00000`), 19.2 MHz timer.
- Panel 1080×2160 DSI video mode, continuous splash at `0x9d400000`; touch Novatek NT36672A at I2C `0x01`.
- PMICs PM660 (charger, gauge, RTC, keys) + PM660L (WLED, volume up), SPMI arbiter v3.
- GPU Adreno 512 (a5xx), rail VDD_CX through the GFX LDO head switch, SMMU-v2 with two non-secure context banks.
- More: [jasmine/HARDWARE.md](jasmine/HARDWARE.md).

## Credits

Based on [MakrSas/ios-topaz](https://github.com/MakrSas/ios-topaz) and [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet), which did the hard parts: XNU on Qualcomm phones with the iPhone X userland, and the SM6225 port this one starts from. Built on Apple's open-source releases (xnu, IOHIDFamily, libpthread, hfs), [blacktop/darwin-xnu-build](https://github.com/blacktop/darwin-xnu-build), [ipsw](https://github.com/blacktop/ipsw), mainline Linux and postmarketOS's SDM660 work, and Qualcomm/Xiaomi's published downstream kernel sources (LineageOS `android_kernel_xiaomi_sdm660`) for the GPU power, PIL and charger details. [UniXNU](https://github.com/UniXNU/UniXNU)'s published GPU and 4K-page work is the reference for what comes next. iOS itself is Apple's and is not distributed here.
