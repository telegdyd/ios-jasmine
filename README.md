# ios-jasmine

**Apple's iOS 16 running on a Xiaomi Mi A2.**

This is a port of [MakrSas/ios-topaz](https://github.com/MakrSas/ios-topaz) (itself a port of [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet): Apple's open-source XNU kernel, xnu-8796, on a Qualcomm phone) to the Xiaomi **Mi A2** (`jasmine`, Qualcomm **SDM660** / Snapdragon 660, 4 GB). On top of it runs the **unmodified iOS 16.7.16 (20H392) userland of the iPhone X**: launchd, the system daemons, backboardd and SpringBoard.

> **Thanks to HackiOS.** The GPU (Adreno through Mesa), display presentation, audio, Wi-Fi glue,
> sandbox, tweak-injection and Metal shader-compiler work in topaz and here started from [HackiOS](https://github.com/oosexgang/hackios-xnu-kernel)
> by OOSEX GANG (kernel: APSL 2.0, [user space](https://github.com/oosexgang/hackios-xnu-userland): MIT).
> What comes from it and under which licence: [CREDITS.md](CREDITS.md).

As of **2026-11-01**, the phone boots iOS by itself from slot b to the **lock screen and home screen**. Touch, the power and volume keys, date and time, battery reporting and **Wi-Fi** work, and the backlight turns off when the phone sleeps. **CoreAnimation renders on the Adreno 512 GPU through Metal** (our port of the [Chlorophyll](https://github.com/telegdyd/Chlorophyll) driver on Mesa freedreno), and the display scales and presents the frames in hardware. Settings, Spotlight, the App Library, Control Center and the keyboard work. All eight CPU cores run, with clock speeds that follow the load. USB Ethernet provides live logs, commands and file transfer.

**Metal is the default.** Apple's Metal API runs on the Adreno 512, and CoreAnimation's own Metal renderer draws the system UI without flicker or tearing. It is still slower than the OpenGL ES path (`libsweetca`) this port used before, which remains available by boot argument.

> Experimental bring-up, not a usable phone OS. Many things are missing or stubbed, and Apple's security model is mostly switched off. iOS installs into the `userdata` partition and so **erases Android's user data**, and the standalone boot replaces `boot_b` / `vbmeta_b`. Keep a backup of every partition before you start.

## What works

| Area | State |
| --- | --- |
| Boot | Stock Xiaomi ABL (unlocked). Slot b's `boot_b` holds our shim + XNU, `vbmeta_b` has verification off, and the kernel marks the slot successful once the root is mounted. Test kernels run from RAM with `fastboot boot` |
| CPU | All eight Kryo 260 cores (four Gold, four Silver) with automatic frequency scaling on both clusters, GICv3 and timers. This needs the 4K-page kernel; a 16K-page build exists and runs on the four Gold cores only |
| Memory | 1.97 GiB at `0x1_00000000` (the part of the upper DDR bank above every carve-out); the memory clock follows the load |
| Storage | Our own eMMC driver (SDHCI with ADMA2, HS200 8-bit, polled); the iOS root is a journaled HFS+ volume in `userdata`, read/write |
| iOS userland | Real iPhone X 16.7.16 root filesystem and shared cache |
| Display | iOS draws an 828×1792 frame at 2× scale (the iPhone XR's size), which the display hardware scales up to fill the 1080×2160 panel. Frames are queued and paced, without tearing |
| GUI | backboardd, SpringBoard, lock screen, home screen, Spotlight, Settings, App Library, Control Center, keyboard |
| Touch | Novatek NT36672A on the old QUP v2 I2C (BLSP1 QUP1), polled, mapped through the same fit as the display |
| Keys and clock | Power and volume down from the PM660 PON, volume up from PM660L GPIO 7, all over the SPMI arbiter v3; the calendar from the PM660 RTC plus `rtcoffset=` |
| Battery | Charger and fuel gauge (voltage, current, temperature); percentage shown in iOS. Wall chargers are detected properly and charge at full speed. The PM660L WLED backlight turns off with the display |
| USB | The phone is a **USB Ethernet gadget** (CDC-NCM; Windows, Linux and macOS have drivers built in) that repairs itself if the PC drops the link. The kernel log streams live over TCP (`tools/sweet-netlog.py`, 192.168.7.2 or 169.254.7.2 port 5140); a command port (5141) reboots into fastboot on request, so `tools/sweet-run.py IMAGE LOG` runs a whole test round (reboot, `fastboot boot`, live log) without touching the phone; `tools/sweet-fs.py` copies files into and out of the iOS root (port 5142). The previous boot's log can be read after a crash |
| GPU | Adreno 512 through the SweetGPU kernel driver and Mesa freedreno (Gallium/a5xx); the GPU powers down when idle |
| Metal | Chlorophyll's AIR-to-ir3 shader compiler and Metal runtime on Gallium freedreno (`libbgair`, `libbgmtl`, `bgmtl_inject.dylib` injected into backboardd); CoreAnimation's own Metal renderer draws the system UI. The default |
| OpenGL ES | The previous path: sweetgl and `libsweetca.dylib` injected into backboardd run CoreAnimation's OpenGL ES renderer. Faster for now, no longer the default |
| Wi-Fi | WCN3990 through the modem DSP and Apple80211: scanning in Settings, WPA2, DHCP, internet, joining a saved network at boot, leaving and rejoining. USB Ethernet keeps working alongside it |
| HEVC decoding | In software, on the CPU: VideoToolbox's own software HEVC decoder takes over when Apple's hardware decoder declines the platform. HEIC images (photos, the iOS 16 wallpapers) decode correctly |
| Device identity | iPhone X (`iPhone10,3` / `D22AP`): no Home button, gesture UI |

## What does not work (yet)

- **Speed**: through Metal the UI runs at roughly 38 frames per second on the home screen and 28–30 in Control Center (OpenGL ES: about 56 and 43). The driver work per frame and the GPU are the limits now.
- **Heat**: there is no thermal throttling yet.
- **Charging from a PC port** is slower than what the phone uses with the screen on. Use a wall charger.
- **Bluetooth, cellular, audio, camera, motion sensors, fingerprint, GPS and the SEP** are unsupported. Without motion sensors, the home screen's parallax effect is turned off.
- **Brightness**: the backlight is only switched on and off.
- **Hardware video decoding and encoding**: HEVC is decoded in software only; the Snapdragon 660's video block (Venus) is not used yet.
- **Stability**: a rare GPU freeze is still unsolved. A reboot sometimes stalls for a while, and the phone sometimes powers off instead of restarting.
- **Some apps and panels crash**, for example some Settings panels and Photos. The wallpaper does not draw correctly. Safari has not been rechecked since GPU rendering arrived.
- **Security is off**: permissive AMFI and sandbox, stub AppleKeyStore, no data protection.

## How jasmine differs from topaz

| Problem | Fix |
| --- | --- |
| **eMMC**, not UFS | An SDHCI backend for the sweet disk driver: ADMA2 with 12-byte descriptors, Auto CMD12, polled. PIO never completed a command on this host. Command queueing stays off (it hung the controller under Linux), and the cache is only flushed when the eMMC reports an enabled cache |
| ABL ignores the IMEM restart reason | Reset into fastboot through the PM660 PON reboot mode over SPMI |
| Silver cores lack the 16K page granule | topaz's Gold-only 16K boot carries over; the 4K-page kernel runs both clusters. XBL leaves Gold on GPLL0 at ~180 MHz, so the kernel moves each cluster onto its own PLL and scales voltage and frequency itself |
| Touch is on the **old QUP v2** I2C, not GENI | A polled QUP v2 I2C driver (FIFO mode, v2 tags) for the NT36672A, clocks from GCC |
| Keys are PMIC inputs, not GPIOs | Read through the SPMI arbiter v3 observer channels |
| Adreno 512 needs an a5xx rendering path | SweetGPU kernel bring-up plus Mesa freedreno's GL driver, sweetgl and the CoreAnimation bridge in `libsweetca`, and Chlorophyll for Metal; see [GPU history](jasmine/GPU.md) |
| A/B phone; topaz only RAM-boots | Standalone boot from `boot_b`, slot marked successful by the kernel |
| Different MMIO map | GIC `0x17a00000`/`0x17b00000`, eMMC `0xc0c4000`, splash framebuffer `0x9d400000` (1080×2160), PS_HOLD `0x10ac000`, SPMI `0x800f000`, MDP `0xc901000`, GPU `0x5000000`, USB `0xa800000` |

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

You need a Mi A2 (`jasmine`, SDM660) with an **unlocked bootloader**, a PC with `fastboot`, a Linux environment (WSL works), and either a GitHub account for the CI builds or a Mac (a macOS VM works). **Back up every partition first.** `userdata` is erased; the standalone boot writes `boot_b` and `vbmeta_b` and makes slot b active (`fastboot set_active` also switches the firmware partitions of the slot).

The steps below outline the build and installation flow. [NOTES.md](NOTES.md) and [jasmine/NOTES.md](jasmine/NOTES.md) have the latest details. Keep backups of the bootloaders, recovery, modem and persist partitions.

1. **Kernel**: fork the repo and run the CI build on the `jasmine` branch (macOS runner; queue time varies):
   ```sh
   gh workflow run xnu.yml -R YOU/ios-jasmine --ref jasmine
   gh run download RUN_ID -R YOU/ios-jasmine -n xnu-kernel -D xnu/out-jasmine
   ```
   The default is the 4K-page, eight-core kernel; `-f topaz_4k=0` builds the 16K Gold-only one. On your own Mac, `tools/vm-build.sh TAG` does the same build over SSH in about a minute (see the script's header; first-time setup is in `tools/vm-mesa-setup.sh`).
2. **iOS root**: from the iPhone X (iPhone10,3) iOS 16.7.16 (20H392) IPSW, `bash tools/build-ios-root.sh IPSW WORKDIR` builds `WORKDIR/ios16-root.simg`, adjusted by `tools/sweet-root-tweaks.py`. Linux needs HFS+ support, `apfs-fuse`, `hfsprogs`, `lzfse`, `img2simg`, `unzip` and `sudo`. The script extracts the device tree to `research/ipsw-x/d22ap.adt`; `mkadt.py` uses its `/product` node. For Wi-Fi, see the [integration runbook](jasmine/WIFI-INTEGRATION.md).
3. **Boot image** (`aarch64-linux-gnu-gcc`, AOSP `mkbootimg`):
   ```sh
   python3 tools/mkadt.py shim/out/jasmine.adt --highmem --amp --canvas 828x1792 --scale 2
   python3 tools/mkpayload.py xnu/out-jasmine/kernel.development.sweet shim/out/jasmine.adt shim/out/payload.bin \
       --cmdline 'debug=0xc serial=3 cpus=8 -noprogress rd=ufsroot0 ufsroot=userdata unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 panicwait=60 sweetfb_hz=30 ufsrw=1 rootrw=1 rtcoffset=SECONDS sweetgpu=4 gpumhz=588 sweetddr=1804 sweetcmd=1 gpudelay=1 gpupause=0 sweetfb_sync=1 sweetfb_sleep=1 sweetfb_queue=1 sweetgpu_tickets=1 sweetfb_lw=828 sweetenv=backboardd:DYLD_INSERT_LIBRARIES=/usr/local/bin/bgmtl_inject.dylib,BGMTL_ENABLE=1;SpringBoard:DYLD_INSERT_LIBRARIES=/s.dylib'
   bash shim/build.sh shim/out/payload.bin      # -> shim/out/shim-boot.img
   ```
   `rtcoffset` is the Unix time minus the PMIC RTC's raw seconds (read once from Linux). The GPU firmware (`a530_pm4.fw`, `a530_pfp.fw`, `a512_zap.*` from the stock `vendor` partition's `/firmware`) goes into `research/gpu-fw`. The command line has room for about 608 bytes. `tools/g2/mkimg.sh` wraps this recipe but has local WSL paths and an RTC offset for one phone; adapt those first.
4. **Root and first boot**: `fastboot -S 512M flash userdata WORKDIR/ios16-root.simg`, then `fastboot boot shim/out/shim-boot.img`. The first boot sits on the Apple logo for a few minutes while LaunchServices builds its database.
5. **GPU rendering and the smaller frame**: build the Metal driver, the Mesa bridge and the SpringBoard helper from the same source revision, by CI (`-f build=mesa`, artifact `mesa-ios`; the iOS tools are artifact `ios-tools`) or on your Mac (`tools/vm-mesa.sh mesa TAG`, `tools/vm-mesa.sh ios TAG`), put the outputs in `xnu/out-mesa` and `xnu/out-ios`, then copy them onto the phone:
   ```sh
   for f in libbgair.dylib libbgmtl.dylib bgmtl_inject.dylib; do
     python3 tools/sweet-fs.py put xnu/out-mesa/$f /usr/local/bin/$f --mode 0755
   done
   printf 'CA_DISABLE_FRAMEBUFFER_COMPRESSION=1\n' > bgmtl-bb.env
   python3 tools/sweet-fs.py put bgmtl-bb.env /private/var/tmp/bgmtl-bb.env --mode 0644
   python3 tools/sweet-fs.py put xnu/out-ios/sweet_sbshape.dylib /s.dylib --mode 0755
   ```
   The injector reads `KEY=VALUE` lines from `/private/var/tmp/bgmtl-bb.env` into backboardd's environment. For OpenGL ES instead, copy `xnu/out-mesa/libsweetca.dylib` to `/usr/local/bin` and use `sweetenv=backboardd:DYLD_INSERT_LIBRARIES=/usr/local/bin/libsweetca.dylib,SWEETCA_PIPELINE=2;...`. `sweet_sbshape` gives SpringBoard the status bar and notch layout of the 828×1792 frame. Back up an existing library before replacing it, and reboot to load the new one. See [GPU history](jasmine/GPU.md) and [Mesa sources](mesa/README.md).
6. **Standalone**: once a temporary boot works, add `abmark=b` to the command line, write the image to `boot_b`, use a `vbmeta_b` with verification disabled, and select slot b.

| Boot-arg | Effect |
| --- | --- |
| `rd=ufsroot0 ufsroot=userdata ufsrw=1 rootrw=1` | Root on `userdata`, writable |
| `cpus=8`, `cpus=4` | All eight cores (4K kernel and `--amp` ADT) or the four Gold cores only |
| `sweetdvfs=0`, `sweetdvfsauto=0` | CPU frequency scaling off, or manual instead of automatic |
| `sweetgold=` | Gold clock in MHz at boot (0 = leave XBL's) |
| `sweetddr=1804`, `sweetddrgov=0` | Memory clock under load; `sweetddrgov=0` keeps it fixed instead of following the load |
| `sweetgpu=4`, `gpumhz=588` | GPU rendering and the GPU clock |
| `sweetenv=PROCESS:VAR=VALUE,...;PROCESS:...` | Environment variables for named processes; used to inject the Metal driver (or `libsweetca`) into backboardd and `/s.dylib` into SpringBoard |
| `sweetfb_lw=`, `sweetfb_lh=` | Size of the frame iOS draws (must match `mkadt.py --canvas`) |
| `sweetfb_sync=1`, `sweetfb_queue=1`, `sweetfb_sleep=1`, `sweetgpu_tickets=1` | Paced, queued presentation that waits for the GPU to finish each frame |
| `sweetfb_scale=0`, `sweetfb_fit=0`, `sweetmdp=0` | Fallbacks: no hardware scaling, crop instead of fit, old CPU copy into the boot framebuffer |
| `rtcoffset=` | Seconds added to the PMIC RTC |
| `abmark=b` | Mark `boot_b` successful once the root is up (standalone image only) |
| `chgmv=`, `chgfcc=`, `chgicl=`, `sweetchg=0` | Charger float voltage, charge current, input limit; `0` leaves the charger alone |
| `wifi=0`, `modem=0`, `wifi_diag=1` | Wi-Fi off, modem off, or extra Wi-Fi diagnostics |
| `sweetusb=0`, `sweetusblog=0`, `sweetusbcmd=0`, `sweetusbfs=0` | USB Ethernet, live log, command port, file server off |
| `sweetwdt=SECS` | Hardware watchdog: a hang resets into fastboot |
| `ufslogsecs=` | Persistent log flush interval (default 10 s) |

The Metal driver reads switches from `/private/var/tmp/bgmtl-bb.env`: `BGMTL_TIMING=1` logs a once-a-second commit timeline, `BGMTL_ASYNC=1` replays command buffers on a worker thread (faster in Control Center, but it can turn off the display's render tickets at boot; see [step 7](mesa/METAL-STEP7.md)), and `RWA_STATE_CACHE=0`, `RWA_FB_BARRIER=0` turn off state caching and the in-batch framebuffer-fetch barrier for comparison. `libsweetca` reads `SWEETCA_PIPELINE=2` (pipelined frame submission), `SWEETCA_GLTHREAD=0` and `SWEETCA_SYS_BARRIER=0` through `sweetenv=`.

## Roadmap

1. **Speed**: bring Metal up to the OpenGL ES path's frame rate: driver work off CoreAnimation's thread without losing render tickets, then the GPU time per frame.
2. **Heat and battery**: thermal limits, then further idle power savings.
3. **Stability**: the GPU freeze, the reboot stall and power-off, crashing apps and panels, wallpaper drawing.
4. **Hardware coverage**: brightness control, audio and the other unsupported parts.
5. **Hardware HEVC**: a kernel driver for the Venus video block (firmware through TrustZone, its HFI message queues; the Linux msm-4.4 `vidc` driver is the reference) and a VideoToolbox decoder plugin that uses it. Measure software playback first; camera recording will need Venus's encoder.

Detailed status and measurements: [performance tasks](jasmine/PERF-TASKS.md), [power plan](jasmine/POWER-PLAN-20261029.md), [Metal port](mesa/METAL-HANDOFF.md), [Wi-Fi](jasmine/WIFI.md), and the running notes in [NOTES.md](NOTES.md) and [jasmine/NOTES.md](jasmine/NOTES.md).

## Repository layout

| Path | What |
| --- | --- |
| `jasmine/` | Board notes, hardware facts, GPU history, Wi-Fi, performance and power reports; `PLAN.md` keeps the original port plan |
| `shim/` | Bare-metal boot shim (C + asm), Gold hand-off, GIC setup, payload loader |
| `xnu/patches/` | Ordered upstream sweet/topaz and jasmine kernel patches |
| `mesa/` | freedreno Darwin backend, sweetgl, the CoreAnimation bridge and Mesa patches; `mesa/metal` is the Chlorophyll Metal driver (submodule) |
| `ios/` | Small iOS helpers built for the phone, such as `sweet_sbshape` for SpringBoard |
| `.github/workflows/xnu.yml` | Kernel, iOS tools and Mesa CI builds |
| `tools/vm-build.sh`, `tools/vm-mesa.sh` | The same builds on your own Mac over SSH |
| `tools/mkadt.py`, `tools/mkpayload.py` | Apple Device Tree for jasmine (cores, memory, MMIO, `/sweet-*` driver nodes, GPU firmware, frame size) and the payload packer |
| `tools/build-ios-root.sh`, `tools/sweet-root-tweaks.py`, `tools/launchd-disable-inplace.py` | Build and adjust the HFS+ iOS root |
| `tools/sweet-netlog.py`, `tools/sweet-cmd.py`, `tools/sweet-run.py`, `tools/sweet-fs.py` | Live log, kernel commands, a one-round test runner and file transfer over USB Ethernet |
| `tools/pmos-shell.py`, `tools/pmos-push.py`, `tools/sweet-log.py` | The postmarketOS initramfs shell over USB (commands, file copy) and the persistent-log reader |
| `tools/charge-shell/`, `tools/jasmine-charger.pyw` | A small Linux boot image that only charges the phone, and a Windows app that shows the battery under it and under iOS |
| `tools/cpuclk/` | CPU clock and voltage tables and checks |
| `tools/tracev3-strings.py` | Reads iOS's unified log files pulled from the phone |
| `tools/g2/` | Graphics build, image and measurement helpers |
| `logs/` | Local test logs (not in git) |
| `NOTES.md` (root) | Running notes, newest first, followed by the historical sweet/topaz notes |

Not in git: partition backups, live device trees, Apple and Qualcomm firmware, root images, build trees.

## Kernel work on jasmine

What the jasmine patches in `xnu/patches/` add on top of topaz:

- Board guards (SM6225-only drivers stay off), early console on the splash framebuffer, reset and panic paths
- eMMC (SDHCI ADMA2) for the sweet disk driver, with safe cache flushing
- Reset into fastboot through the PMIC reboot mode
- PMIC keys and RTC over SPMI
- Touch on the old QUP v2 I2C
- Display: tear-free flips, hardware scaling, queued and paced presentation, smaller frame sizes
- Charger, fuel gauge and battery percentage; charger-type detection that gives wall chargers full current
- Backlight on and off with the display
- Marking the booted A/B slot successful
- CPU: both clusters on their own PLLs, voltage control and automatic frequency scaling, all eight cores on the 4K kernel
- Memory clock that follows the load
- Adreno 512: power, SMMU, microcode, zap shader through TrustZone, clock levels, idle power-down, the SweetGPU user client with buffers, IOSurface import and fences
- USB Ethernet with live log, command port and file access, self-repair of the link, previous-boot log
- Hardware watchdog for test boots
- AMFI support for app extension registration
- Wi-Fi: modem DSP start, WLAN transport, Apple80211 for wifid, coexistence with USB, clean reboots
- Background polling threads moved to the Silver cores, out of the UI's way

## Key hardware facts (jasmine)

- SoC SDM660: 4× Kryo 260 Silver (A53 class, MPIDR `0x0`–`0x3`) + 4× Kryo 260 Gold (A73 class, `0x100`–`0x103`). Only Gold has the 16K granule.
- 4 GB LPDDR4; the kernel uses `0x1_00000000` + 1.97 GiB. 32 GB eMMC (Hynix, HS200).
- GICv3 at `0x17a00000` (redistributors `0x17b00000`), 19.2 MHz timer.
- Panel 1080×2160 DSI video mode, continuous splash at `0x9d400000`; touch Novatek NT36672A at I2C `0x01`.
- PMICs PM660 (charger, gauge, RTC, keys) + PM660L (WLED, volume up), SPMI arbiter v3.
- GPU Adreno 512 (a5xx), rail VDD_CX through the GFX LDO head switch, SMMU-v2 with two non-secure context banks.
- More: [jasmine/HARDWARE.md](jasmine/HARDWARE.md).

## Credits

Based on [MakrSas/ios-topaz](https://github.com/MakrSas/ios-topaz) and [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet), which did the hard parts: XNU on Qualcomm phones with the iPhone X userland, and the SM6225 port this one starts from. The Metal driver is Chlorophyll from [Bergamota](https://github.com/ry-diffusion/Bergamota) (iOS 18 on the Poco F1; our a5xx fork: [telegdyd/Chlorophyll](https://github.com/telegdyd/Chlorophyll)), whose shader compiler comes from HackiOS. Built on Apple's open-source releases (xnu, IOHIDFamily, libpthread, hfs), [Mesa](https://www.mesa3d.org/), [blacktop/darwin-xnu-build](https://github.com/blacktop/darwin-xnu-build), [ipsw](https://github.com/blacktop/ipsw), mainline Linux and postmarketOS's SDM660 work, and Qualcomm/Xiaomi's published downstream kernel sources (LineageOS `android_kernel_xiaomi_sdm660`) for the GPU power, PIL and charger details. [UniXNU](https://github.com/UniXNU/UniXNU)'s published GPU and 4K-page work is also a reference. iOS itself is Apple's and is not distributed here.
