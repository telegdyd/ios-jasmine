# ios-jasmine

**Apple's iOS 16 running on a Xiaomi Mi A2.**

This is a port of [MakrSas/ios-topaz](https://github.com/MakrSas/ios-topaz) (itself a port of [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet): Apple's open-source XNU kernel, xnu-8796, on a Qualcomm phone) to the Xiaomi **Mi A2** (`jasmine`, Qualcomm **SDM660** / Snapdragon 660, 4 GB). On top of it runs the **unmodified iOS 16.7.16 (20H392) userland of the iPhone X**: launchd, the system daemons, backboardd and SpringBoard.

> **Thanks to HackiOS.** The GPU (Adreno through Mesa), display presentation, audio, Wi-Fi glue,
> sandbox and tweak-injection work in topaz (and its kernel patches carried here) started from [HackiOS](https://github.com/oosexgang/hackios-xnu-kernel)
> by OOSEX GANG (kernel: APSL 2.0, [user space](https://github.com/oosexgang/hackios-xnu-userland): MIT).
> What comes from it and under which licence: [CREDITS.md](CREDITS.md).

As of **2026-10-26**, the phone boots iOS from slot b to the **lock screen and home screen**, with touch, power and volume keys, date and time, battery reporting, and the backlight switching off with the display. **CoreAnimation renders on the Adreno 512 GPU** through `libsweetca` and Mesa freedreno; the display uses MDP hardware scaling. Settings, the App Library and the keyboard work. USB Ethernet provides live logs, commands and file transfer.

**Wi-Fi has demonstrated scanning, WPA2 connection, DHCP, internet access and automatic reconnection in test boots.** Acceptance of the combined Wi-Fi/performance integration build remains pending; these results do not mean Wi-Fi is installed in the standalone image. UI performance, graphics correctness, stability, charging and power management remain active work.

> Experimental bring-up, not a usable phone OS. Many things are missing or stubbed, and Apple's security model is mostly switched off. iOS installs into the `userdata` partition and so **erases Android's user data**, and the standalone boot replaces `boot_b` / `vbmeta_b`. Keep a backup of every partition before you start.

## What works

| Area | State |
| --- | --- |
| Boot | Stock Xiaomi ABL (unlocked). Standalone: slot b's `boot_b` holds our shim + XNU, `vbmeta_b` has verification off, and `abmark=b` marks the slot successful after root mount. Test kernels run from RAM with `fastboot boot`. The PM660 PON reset path returns to fastboot; shutdown hangs remain a validation concern |
| CPU | Four Kryo 260 Gold cores (MPIDR `0x100`–`0x103`) at fixed **1747 MHz** by default, GICv3 and timers. Both 16K and 4K page builds exist; the 4K build can run all eight cores, but four Gold cores remain the performance default |
| Memory | 1.97 GiB at `0x1_00000000` (the part of the upper DDR bank above every carve-out) |
| Storage | Our own eMMC driver (SDHCI with ADMA2, HS200 8-bit, polled); the iOS root is a journaled HFS+ volume in `userdata`, read/write |
| iOS userland | Real iPhone X 16.7.16 root filesystem and shared cache |
| Display | iOS renders an iPhone X frame (1125×2436), fitted to approximately 997×2160 on the 1080×2160 panel. MDP VIG0/QSEED3 scales and presents GPU surfaces in hardware; composition falls back to the CPU for some multi-layer frames |
| GUI | backboardd, SpringBoard, lock screen, home screen, Spotlight, Settings, App Library, keyboard |
| Touch | Novatek NT36672A on the old QUP v2 I2C (BLSP1 QUP1), polled, mapped through the same fit as the display |
| Keys and clock | Power and volume down from the PM660 PON, volume up from PM660L GPIO 7, all over the SPMI arbiter v3; the calendar from the PM660 RTC plus `rtcoffset=` |
| Battery | PM660 charger support and fuel-gauge voltage/current/temperature readout; percentage shown in iOS. PM660L WLED backlight switches off with the display. Reliable net charging is unresolved: recent charging-shell samples showed discharge despite the Charging label |
| USB | The DWC3 (set up by the kernel itself after a normal boot, j0023) is a **CDC-NCM Ethernet gadget** (Windows, Linux and macOS drivers built in). The kernel log streams live over TCP (`tools/sweet-netlog.py`, 192.168.7.2 or 169.254.7.2 port 5140); a command port (5141) reboots the phone into fastboot on request, so `tools/sweet-run.py IMAGE LOG` runs a whole test round (reboot, `fastboot boot`, live log) without touching the phone; `tools/sweet-fs.py` copies files into and out of the iOS root (port 5142) |
| GPU | Adreno 512 through the SweetGPU kernel driver, Mesa freedreno (Gallium/a5xx), sweetgl and injected `libsweetca.dylib`. CoreAnimation's GLES renderer runs on the GPU. Documented defaults: **GPU 588 MHz, DDR 1804 MHz**; graphics and power-management limitations remain |
| Wi-Fi (test boots) | WCN3990 via the modem DSP and Apple80211 integration: Settings scans, WPA2 join, DHCP, internet, auto-join and leave/rejoin demonstrated; USB Ethernet coexists. See [tested results](https://github.com/telegdyd/ios-jasmine/blob/codex/wifi-integration/jasmine/WIFI-HANDOFF.md) and the [combined integration acceptance gate](https://github.com/telegdyd/ios-jasmine/blob/codex/wifi-integration/jasmine/WIFI-INTEGRATION.md) |
| Device identity | iPhone X (`iPhone10,3` / `D22AP`): no Home button, gesture UI |

## What does not work (yet)

- **Graphics and performance**: GPU acceleration works, but UI motion is still slow. CPU driver work, GPU memory traffic and frame-completion waits matter by workload. Variable blur uses an approximation; the Task 24 experimental pixel test failed with its candidate disabled, and the cause is unresolved. Its retained-batch path is untested and off by default; no gain is established. See [current correctness gate](jasmine/PERF-TASK24-PIXEL-GATE.md).
- **Safari/WebKit**: blank pages were reported before GPU acceleration; current WebKit functionality has not been revalidated here.
- **Bluetooth, cellular, audio, camera, sensors, fingerprint, GPS and SEP** remain unsupported on jasmine. Modem DSP startup for Wi-Fi does not establish cellular support.
- **Power and heat**: no CPU DVFS or thermal throttling, no normal GPU idle power-down, and no load-following DDR governor. Eight-core operation works but has not beaten four Gold cores in the documented UI comparisons.
- **Charging**: a Charging status or configured input limit does not establish net energy gain; the latest charging investigation is in [NOTES.md](NOTES.md).
- **Some apps and panels crash**: some Settings panels and Photos.
- **Stability**: the SweetGPU buffer-free freeze remains unresolved. Settings > Wallpaper has reported freezes; captures show wallpaper-service crashes/restarts and memory growth, but full-system exhaustion or a leak is not established. App extensions are registered since j0070.
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
| Adreno 512 needs an a5xx rendering path | SweetGPU kernel bring-up plus Mesa freedreno's GL driver, sweetgl and the CoreAnimation bridge in `libsweetca`; see [GPU history](jasmine/GPU.md) |
| A/B phone; topaz only RAM-boots | Standalone boot from `boot_b`, slot marked successful by the kernel (j0013) |
| Different MMIO map | GIC `0x17a00000`/`0x17b00000`, eMMC `0xc0c4000`, splash framebuffer `0x9d400000` (1080×2160), PS_HOLD `0x10ac000`, SPMI `0x800f000`, MDP `0xc901000`, GPU `0x5000000`, USB `0xa800000` |

### Four cores by default; eight-core builds available

The Silver cores cannot translate 16K pages, so the 16K build runs on Gold only. The optional **4K-page/AMP build** supports both clusters and all eight cores. Four Gold cores remain the default because earlier eight-core UI comparisons were slower; scheduler tuning remains open. A 4K kernel can also run with `cpus=4`. See [GPU measurements](jasmine/GPU.md) and [performance tasks](jasmine/PERF-TASKS.md).

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

The steps below outline the build and installation flow. Use [root NOTES.md](NOTES.md) and [jasmine/NOTES.md](jasmine/NOTES.md) for the latest validated artifacts and board-specific prerequisites. Preserve bootloaders, recovery, modem, persist and backups; each destructive operation needs explicit confirmation when an agent operates the device.

1. **Kernel**: fork the repo and run the CI build on the `jasmine` branch (macOS runner; queue time varies):
   ```sh
   gh workflow run xnu.yml -R YOU/ios-jasmine --ref jasmine
   gh run download RUN_ID -R YOU/ios-jasmine -n xnu-kernel -D xnu/out-jasmine
   ```
   Add `-f topaz_4k=1` to the dispatch for the 4K-page/AMP kernel. Pair it with `--amp` when generating the ADT; `cpus=4` keeps Gold only, while `cpus=8` enables both clusters. The workflow defaults to the 16K build. Match kernel, ADT and boot arguments rather than mixing artifacts from different builds.
2. **iOS root**: from the iPhone X (iPhone10,3) iOS 16.7.16 (20H392) IPSW, `bash tools/build-ios-root.sh IPSW WORKDIR` builds `WORKDIR/ios16-root.simg`, adjusted by `tools/sweet-root-tweaks.py`. Linux needs HFS+ support, `apfs-fuse`, `hfsprogs`, `lzfse`, `img2simg`, `unzip` and `sudo`. The script extracts the device tree to `research/ipsw-x/d22ap.adt`; `mkadt.py` uses its `/product` node. For fresh Wi-Fi-enabled roots, see [offline provisioning](https://github.com/telegdyd/ios-jasmine/blob/codex/wifi-integration/jasmine/WIFI-INTEGRATION.md); existing installs should not have all root tweaks reapplied just to add Wi-Fi.
3. **Boot image** (`aarch64-linux-gnu-gcc`, AOSP `mkbootimg`):
   ```sh
   python3 tools/mkadt.py shim/out/jasmine.adt --highmem
   python3 tools/mkpayload.py xnu/out-jasmine/kernel.development.sweet shim/out/jasmine.adt shim/out/payload.bin \
       --cmdline 'debug=0xc serial=3 cpus=4 keepsyms=1 -noprogress rd=ufsroot0 ufsroot=userdata unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 panicwait=60 sweetfb_hz=30 ufsrw=1 rootrw=1 rtcoffset=SECONDS sweetgold=1747'
   bash shim/build.sh shim/out/payload.bin      # -> shim/out/shim-boot.img
   ```
   This is a base boot recipe. For a 4K kernel add `--amp` to `mkadt.py`. `rtcoffset` is the Unix time minus the PMIC RTC's raw seconds (read once from Linux). The GPU firmware (`a530_pm4.fw`, `a530_pfp.fw`, `a512_zap.*` from the stock `vendor` partition's `/firmware`) goes into `research/gpu-fw`.
4. **Root and first boot**: `fastboot -S 512M flash userdata WORKDIR/ios16-root.simg`, then `fastboot boot shim/out/shim-boot.img`. The first boot sits on the Apple logo for a few minutes while LaunchServices builds its database.
5. **Accelerated CoreAnimation**: build the Mesa/userland bridge separately from the same reviewed source revision:
   ```sh
   gh workflow run xnu.yml -R YOU/ios-jasmine --ref jasmine -f build=mesa
   gh run download MESA_RUN_ID -R YOU/ios-jasmine -n mesa-ios -D xnu/out-mesa
   python3 tools/sweet-fs.py put xnu/out-mesa/libsweetca.dylib /usr/local/bin/libsweetca.dylib --mode 0755
   ```
   Back up an existing library before replacing it. Rebuild the boot image with `sweetgpu=4 gpumhz=588 sweetddr=1804 gpudelay=1 gpupause=0 sweetfb_sync=1 sweetenv=backboardd:DYLD_INSERT_LIBRARIES=/usr/local/bin/libsweetca.dylib sweetcmd=1` appended to the command line, then temporarily boot and validate it. Installing the library alone does not enable injection into an already running backboardd. See [GPU history and validation](jasmine/GPU.md) and [Mesa sources](mesa/README.md); experimental Task 24 options remain off.
6. **Wi-Fi integration**: use the [integration runbook](https://github.com/telegdyd/ios-jasmine/blob/codex/wifi-integration/jasmine/WIFI-INTEGRATION.md) for the combined branch, firmware prerequisites, image preparation, recovery and acceptance checks. It is not yet an accepted standalone upgrade. On the integration branch, radio/modem startup and the WLAN ADT node default on; `wifi=0`/`modem=0` and an ADT without WLAN provide the off fallback.
7. **Standalone**: only after temporary-boot validation, rebuild with `abmark=b`, write the approved image to `boot_b`, use a `vbmeta_b` with verification disabled, and select slot b. These writes are separate from `fastboot boot` and require explicit approval on the shared device.

`tools/g2/mkimg.sh` wraps the accelerated-image recipe but includes local WSL paths and a device-specific RTC offset; adapt those before reuse. Do not treat a successful CI build as device acceptance.

| Boot-arg | Effect |
| --- | --- |
| `rd=ufsroot0 ufsroot=userdata ufsrw=1 rootrw=1` | Root on `userdata`, writable |
| `cpus=4`, `cpus=8` | Four Gold cores by default; eight requires the 4K/AMP kernel and matching ADT |
| `sweetgold=1747` | Gold cluster clock in MHz (1113, 1401, 1747 tested; 0 = leave XBL's) |
| `rtcoffset=` | Seconds added to the PMIC RTC |
| `abmark=b` | Mark `boot_b` successful once the root is up (standalone image only) |
| `chgmv=`, `chgfcc=`, `chgicl=`, `sweetchg=0` | Charger float voltage, charge current, input limit; `0` leaves the charger alone |
| `sweetgpu=4`, `gpumhz=588` | GPU rendering support and documented default GPU clock; earlier 1/2/3 values are bring-up stages |
| `sweetddr=1804` | Documented fixed DDR rate; load-following governor remains open |
| `sweetenv=backboardd:DYLD_INSERT_LIBRARIES=/usr/local/bin/libsweetca.dylib` | Load the CoreAnimation bridge into backboardd at launch |
| `sweetfb_sync=1`, `sweetfb_scale=0` | Synchronize presentation; explicitly disable hardware scaling for fallback diagnosis |
| `wifi=0`, `modem=0`, `wifi_diag=1` | Combined integration: radio off, modem off, or opt-in radio diagnostics; see the integration runbook |
| `sweetusb=0`, `sweetusblog=0`, `sweetusbcmd=0`, `sweetusbfs=0` | USB Ethernet, live log, command port, file server off |
| `sweetwdt=SECS` | Hardware watchdog (test images): a hang resets into fastboot |
| `ufslogsecs=` | Persistent log flush interval (default 10 s) |
| `sweetmdp=0`, `sweetfb_fit=0` | Old CPU copy into the boot framebuffer; crop instead of fitting |

## Roadmap

1. **Charging and power**: diagnose net discharge, then CPU DVFS/thermal limits, GPU idle power and a DDR governor. Higher clocks need validated voltage and thermal handling.
2. **Graphics correctness and performance**: resolve the [Task 24 pixel-test failure](jasmine/PERF-TASK24-PIXEL-GATE.md) before evaluating batch-retention gains. Continue work on CPU driver cost, GPU traffic and presentation synchronization; GMEM and pipelining are not established default improvements. The shared-blur investigation closed without an optimization or measured gain.
3. **Wi-Fi**: build and validate the combined integration, including auto-join, USB coexistence, joined reboot and the radio-off fallback, before considering a standalone installation.
4. **Stability and hardware coverage**: diagnose the GPU buffer-free freeze and app crashes; improve eight-core scheduling, brightness control and unsupported peripherals.

Detailed status and evidence: [performance tasks](jasmine/PERF-TASKS.md), [GPU measurements](jasmine/PERF-GPU-TIME-20261025.md), [framebench](jasmine/FRAMEBENCH.md), [Wi-Fi integration](https://github.com/telegdyd/ios-jasmine/blob/codex/wifi-integration/jasmine/WIFI-INTEGRATION.md), and the active handoffs in [NOTES.md](NOTES.md) and [jasmine/NOTES.md](jasmine/NOTES.md). Reports use specific workloads and software revisions; swap-arrival rates are not measured distinct displayed FPS.

## Repository layout

| Path | What |
| --- | --- |
| `jasmine/` | Board handoff (`NOTES.md`), hardware facts, GPU history, Wi-Fi acceptance, performance tasks and reports; `PLAN.md` preserves the original port plan |
| `logs/` | Local test evidence; keep device dumps and identifying data out of git |
| `shim/` | Bare-metal boot shim (C + asm), Gold hand-off, GIC setup, payload loader |
| `xnu/patches/` | Ordered upstream sweet/topaz and jasmine kernel patches, including 4K/AMP and Wi-Fi work |
| `mesa/` | freedreno Darwin backend, sweetgl, CoreAnimation bridge and Mesa patches |
| `.github/workflows/xnu.yml` | Kernel, iOS tools and Mesa CI builds |
| `tools/mkadt.py`, `tools/mkpayload.py` | Apple Device Tree for jasmine (cores, memory, MMIO, `/sweet-*` driver nodes, GPU firmware) and the payload packer |
| `tools/build-ios-root.sh`, `tools/sweet-root-tweaks.py`, `tools/launchd-disable-inplace.py` | Build and adjust the HFS+ iOS root |
| `tools/sweet-netlog.py`, `tools/sweet-cmd.py`, `tools/sweet-run.py`, `tools/sweet-fs.py` | Live log, kernel commands, a one-round test runner and file transfer over USB Ethernet |
| `tools/pmos-shell.py`, `tools/pmos-push.py`, `tools/sweet-log.py` | The postmarketOS initramfs shell over USB (commands, file copy) and the persistent-log reader |
| `tools/g2/` | Graphics build and measurement helpers; Wi-Fi image/provisioning/log tools are currently on `codex/wifi-integration` |
| `NOTES.md` (root) | Active cross-task handoff, current blockers and artifact/build references, followed by historical sweet/topaz notes |

Not in git: partition backups, live device trees, Apple and Qualcomm firmware, root images, build trees.

## Selected kernel milestones

The early board patches below are followed by the GPU, scheduler, display and radio work linked at the end of the table. This is an overview; the patch directory and active handoffs carry the complete series and validation status.

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
| j0024 | File access to the iOS root over USB Ethernet (port 5142: put, get, ls, mkdir, rm) |
| j0025 | APSS hardware watchdog for test boots (`sweetwdt=`): a hung test kernel resets into fastboot |
| GPU rendering | SweetGPU user client, buffers, IOSurface import and fences, plus the Mesa/sweetgl/CoreAnimation bridge; [implementation history](jasmine/GPU.md) |
| 4K/AMP and scheduling | Optional eight-core build and cluster scheduling work; [comparison and remaining tasks](jasmine/PERF-TASKS.md) |
| j0058 | MDP hardware scaling and presentation synchronization; [GPU/display history](jasmine/GPU.md) |
| j0060, j0064 | GPU clock levels/RPM votes and DDR clock control; [current measurements](jasmine/PERF-GPU-TIME-20261025.md) |
| j0070 | AMFI service support for extension registration; wallpaper stability remains unresolved |
| Wi-Fi series and integration | Modem DSP, WLAN transport, Apple80211, USB coexistence and reboot fixes; [tested history](https://github.com/telegdyd/ios-jasmine/blob/codex/wifi-integration/jasmine/WIFI.md), [combined acceptance](https://github.com/telegdyd/ios-jasmine/blob/codex/wifi-integration/jasmine/WIFI-INTEGRATION.md) |

## Key hardware facts (jasmine)

- SoC SDM660: 4× Kryo 260 Silver (A53 class, MPIDR `0x0`–`0x3`) + 4× Kryo 260 Gold (A73 class, `0x100`–`0x103`). Only Gold has the 16K granule.
- 4 GB LPDDR4; the kernel uses `0x1_00000000` + 1.97 GiB. 32 GB eMMC (Hynix, HS200).
- GICv3 at `0x17a00000` (redistributors `0x17b00000`), 19.2 MHz timer.
- Panel 1080×2160 DSI video mode, continuous splash at `0x9d400000`; touch Novatek NT36672A at I2C `0x01`.
- PMICs PM660 (charger, gauge, RTC, keys) + PM660L (WLED, volume up), SPMI arbiter v3.
- GPU Adreno 512 (a5xx), rail VDD_CX through the GFX LDO head switch, SMMU-v2 with two non-secure context banks.
- More: [jasmine/HARDWARE.md](jasmine/HARDWARE.md).

## Credits

Based on [MakrSas/ios-topaz](https://github.com/MakrSas/ios-topaz) and [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet), which did the hard parts: XNU on Qualcomm phones with the iPhone X userland, and the SM6225 port this one starts from. Built on Apple's open-source releases (xnu, IOHIDFamily, libpthread, hfs), [Mesa](https://www.mesa3d.org/), [blacktop/darwin-xnu-build](https://github.com/blacktop/darwin-xnu-build), [ipsw](https://github.com/blacktop/ipsw), mainline Linux and postmarketOS's SDM660 work, and Qualcomm/Xiaomi's published downstream kernel sources (LineageOS `android_kernel_xiaomi_sdm660`) for the GPU power, PIL and charger details. [UniXNU](https://github.com/UniXNU/UniXNU)'s published GPU and 4K-page work is also a reference. iOS itself is Apple's and is not distributed here.
