# iOS on the Mi A2: game plan

Status: phase 0 (backup done, fork pending). Written 2026-10-20.
Hardware details are in [HARDWARE.md](HARDWARE.md).

## Short version

- **It is feasible, and the Mi A2 fits ios-topaz very well.** The Mi A2's Silver cores have the exact MIDR
  (`0x51AF8014`) that topaz documents, and the Gold cores are the same Kryo 260 Gold. Both are ARMv8.0 without LSE atomics.
  topaz has already solved the hard CPU problems: the Silver core can't use 16K pages, so the shim hands off to a Gold core;
  the kernel is built for ARMv8.0; and the userland's LSE/`ldapr` instructions are trapped and emulated.
- **We don't need 4K pages to boot.** With 16K pages XNU runs on the 4 Gold cores, as on topaz. 4K pages only add
  the 4 Silver cores. UniXNU's 4K work looks real (details below), so it is a later upgrade, not a blocker.
- **The new work is the board:** an eMMC driver (neither port has one), BLSP QUP I²C plus Novatek touch, the PMIC
  arbiter v3 for the keys, a 2 GiB memory map, and the jasmine boot image. All of this is ordinary driver work
  with good references (Linux drivers and our own live device tree).
- **Decided 2026-10-20:** iOS goes on this phone (no second Mi A2). The Nura server can stay down indefinitely, so iOS
  uses the whole **userdata** partition, like sweet and topaz. Nura is backed up in full on the PC, outside git, in
  `Xiaomi A2/backup/nura-full-20261020/` (created by `tools/backup-nura.sh`) and is restored by writing userdata back. Base: ios-topaz, iOS 16 (iPhone X).
  The "Where to run it" section below is kept for the record; its Option B 6 GiB window no longer applies.

## The three projects

| | ios-sweet | ios-topaz | UniXNU |
| --- | --- | --- | --- |
| Device | Redmi Note 10 Pro, SM7150 | Redmi Note 12 4G, SM6225 | Xiaomi Pad 6S Pro, SM8550 |
| Created | 2026-10-14 | 2026-10-18 (fork of sweet) | 2026-10-19 (public) |
| Boot path | ABL → `fastboot boot` bare-metal shim → XNU | same, boot image v4, Gold hand-off | ABL → BootShim → Mu-Silicium **UEFI** → UniXNU boot manager → DarwinBoot → XNU |
| Kernel | xnu-8796, 16K pages, ~80 patches | sweet's + ARMv8.0 patches, 16K, Gold only, ~133 patches | xnu with **4K pages** (BCM2837 config + patches) |
| Userland | iPhone X iOS 16.7.16, unmodified | same | iPad7,1 iPadOS 17.7.11, unmodified |
| Storage | own UFS driver, HFS+ root in userdata | same | UFS, APFS root from the IPSW |
| Reached | home screen, touch, keys, Settings, CPU rendering 20–30 fps | lock screen; touch written; modem + Wi-Fi bring-up in progress | home screen, touch, partial Metal on Adreno 740 |
| Build host | GitHub macOS runner (CI) + Linux | same | **macOS with Xcode** (local) |
| Use for us | patch base, tools, root-image scripts | **closest sibling: start here** | 4K patches; Novatek touch reference |

Notes:

- Both iOS ports pick the iPhone X because it is the newest arm64 (non-arm64e, no pointer authentication) device on
  iOS 16. UniXNU picks iPad7,1 (A10X) for the same reason on iPadOS 17.
- **topaz's disk accident:** on 2026-10-18/19 its UFS driver wrote over LUN0's GPT and the phone booted nothing until
  the GPT was restored. Any new block driver here must be write-clamped from day one (see safety rules).
- All three are a few days old and move fast. Pin to a commit when we start.

## The 4K page question

**Why it matters:** XNU for iOS uses 16 KiB pages everywhere. Kryo 260 Silver has no 16K translation granule,
so a 16K kernel can only run on the Gold cores. To use all 8 cores, the kernel must use 4K pages on every core.

**What UniXNU did** (`docs/xnu/four-k-page-tables.md`), with named patches and check scripts:

- builds for XNU's own `BCM2837` (Raspberry Pi 3) machine config, which already has a 4K layout;
- sizes the boot page-table pool for 4K and adds an exhaustion check in `start.s`;
- forces `PAGE_SHIFT` = 12 for the kernel and 32-bit users at every RAM size (Apple's 4K policy flips to 16K above 1 GiB);
- gives 64-bit processes, the commpage and the dyld shared region 4K page shifts;
- **code signing:** the IPSW's signatures hash 16K pages. The kernel checks each 16K block against the original hash,
  then derives and caches one hash per 4K page (`native-4k-signature-hash-cache`);
- fixes PGZ alignment and a 32-bit shift in `pmap_sync_page_attributes_phys` for RAM above 4 GiB.

They report SpringBoard, the lock screen, the home screen and Settings on a 4K kernel. The engineering is credible.

**Limits of that evidence for us:**

1. SM8550's cores support 16K anyway. 4K userland has not yet run on an ARMv8.0 core, and not together with
   topaz's LSE emulation (both change the trap and fault paths).
2. The userland is iPadOS 17, not iOS 16. The topaz README lists 16K assumptions in the iOS userland (malloc,
   JIT guard pages, IOSurface, commpage), so iOS 16 on 4K is a separate test.
3. One device, pre-release, and the build driver needs a Mac. We would take only their XNU patches, not the UEFI chain.

**What it buys:** 4 extra cores. Silver cores are maybe a third to half as fast as Gold, so roughly +40–60% throughput.
That helps CPU rendering, but it is not needed to boot. Topaz reached the lock screen in about 3 minutes on 4 Gold cores;
sweet took about 4 minutes on six A55s.

**Plan:** 16K Gold-only first (phases 1–5). The 4K kernel is phase 7, kept as a separate build with 16K as the fallback.

**Why not UniXNU's UEFI route as the base:** Mu-Silicium does support SDM660 (`StarlordPkg`, with the Redmi Note 7
`lavenderPkg` as a device), so a jasmine UEFI port is possible. But it adds a firmware port and a Mac-only build,
and buys nothing the bare-metal shim doesn't already do. Keep it as an option if a UEFI environment is wanted for other OSes.

## Where to run it

**Option A, recommended: a second Mi A2** (used, typically €30–50; same 4 GB model if possible, see HARDWARE.md).

- The server stays up. Bring-up means dozens of reboots, often with Power + Volume down by hand and a USB cable to the PC
  for `fastboot boot`. The server phone sits on a wall charger, and PC USB ports give it only about 75 mA.
- iOS can use all of userdata (18 GiB), as in sweet/topaz, so there are no size limits.
- A bad block driver can only damage a phone with nothing on it.

**Option B: dual-boot on the server phone** (if you'd rather not buy one).

- iOS root in **system_a + system_b**: contiguous, exactly 6 GiB, unused by Nura. vendor_a (Nura's firmware), vendor_b
  and userdata are not touched.
- Boot iOS only with `fastboot boot` (RAM). Nothing is flashed to boot_a, and the slot setup is unchanged. Any reboot
  or panic → PS_HOLD reset → ABL boots slot a → Nura comes back on its own.
- The kernel's persistent log ring lives at the end of the window, so after a test you SSH into Nura and read it with
  `dd` from `/dev/mmcblk1p66`. No recovery image needed (sweet/topaz need one).
- The root image can be written from Nura over SSH (`dd` to p65/p66), so no 7-minute fastboot flashes.
- Cost: the server is down for every iOS session, and the 6 GiB window must hold the trimmed iOS root plus `/private/var`.
  The iPhone X system volume is several GB, so measure it in phase 4. If it doesn't fit, the next option is to shrink
  Nura's root filesystem (needs an offline resize) and take the tail of userdata. That's more invasive.
- Later, an even more remote path: `kexec` the shim from Nura over SSH. That needs CONFIG_KEXEC, CPU offlining (which
  crashed this phone once, on 2026-10-02) and a display Linux has already taken over. Experimental only.

**Not an option:** wiping Nura for iOS. iOS can't do the server's job.

## Phases

Each phase has an exit test. Nothing writes to the eMMC before phase 3b, and nothing outside the iOS window, ever.

### Phase 0: preparation

- Second phone: unlock the bootloader (Mi A2 Android One: `fastboot flashing unlock`, no Mi Unlock wait), back up
  persist/modemst1/modemst2/fsg/fsc/boot/vbmeta as we did for the server. **New: dump the GPT** (first 34 and last 33
  LBAs of the user area). We don't have that for the server phone either; take it now.
- Fork ios-topaz on GitHub (kernel CI runs on free macOS runners for public repos). Install `gh` on Windows.
- WSL Debian: `gcc-aarch64-linux-gnu`, `mkbootimg` (we already have pmbootstrap's), `python3`, `hfsprogs`, `apfs-fuse`
  (build from source), `img2simg`. About 40 GB of free disk for the IPSW and the root image.
- Download the iPhone X (iPhone10,3) iOS 16.7.x IPSW from Apple. Use the build sweet/topaz use (16.7.16, 20H392)
  so their root tweaks apply unchanged.
- New repo: `ios-jasmine` (this folder becomes its docs). Branch from topaz at a pinned commit.

### Phase 1: shim hello world (RAM only, no XNU)

Port topaz's `shim/` to jasmine:

- Pack as boot header v0 with gzip Image + appended DTB, the format jasmine's ABL already boots for Nura.
- Draw to the ABL framebuffer at `0x9d400000` (1080×2160, stride 4320).
- Print MIDR, MPIDR and `ID_AA64MMFR0` on Silver; PSCI `CPU_ON` Gold `0x100`; print the same on Gold; run the speed probe.
  Drop topaz's `gold_cpufreq_max()`, since SDM660 has no cpufreq-hw block.
- Check for a running APSS watchdog.
- After 20 s, reset through PS_HOLD (`0x10ac000`).

**Exit:** the screen shows `tg16=0` on Silver and `tg16≠0` on Gold, then the phone resets by itself.
Also check with `qbootctl` that a RAM boot doesn't use up slot a's retry count (on the server, ABL drops to fastboot
after 7 boots that are never marked successful; see the 2026-10-03 incident).

### Phase 2: XNU to the kernel console (no storage)

- Machine config `JASMINE` (copy topaz's, which is `SWEET`-derived): GIC `0x17a00000`/`0x17b00000`, Gold MPIDRs
  `0x100`–`0x103`, 19.2 MHz timer, framebuffer `0x9d400000`.
- `tools/mkadt.py`: memory `0x1_00000000` + `0x7e4c0000` (HARDWARE.md); 4 Gold cores; strip sweet/topaz MMIO nodes
  (UFS, GENI, TLMM tiles) so no driver touches the wrong address.
- Boot-args: `cpus=1`, then `cpus=4`. No root device yet, so it should stop at "waiting for root" or run a tiny mockfs ramdisk.
- Panic → PS_HOLD reset must work in this phase. topaz's shim already resets through PS_HOLD, and its MMIO table lists
  PS_HOLD and the IMEM restart-reason address. Make XNU's panic and reboot paths write jasmine's `0x10ac000` the same way.

**Exit:** XNU console on screen, 4 Gold cores up, a forced panic resets the phone.

### Phase 3: eMMC driver (the main new piece)

- **3a, read-only.** XNU block driver for SDHCI-MSM v5 at `0xc0c4000`. Reuse ABL's state (card selected and in transfer state;
  check which bus mode ABL leaves). ADMA2 with 64-bit descriptors, CMD18 multi-block read. **No CMD6 (SWITCH) at all.** Never
  change `PARTITION_CONFIG`, so the driver can never land in the boot0/boot1/RPMB hardware partitions. Read and log the GPT, compare
  the window's partition names and LBAs to the compiled-in values, and refuse to attach on any mismatch.
- **3b, write the log ring.** Enable writes (CMD25) only for the last 4 MiB of the window. Port sweet's persistent log.
- **Write clamp, in the lowest layer:** every request is checked against `[window_start, window_end)` right before the
  command is issued. Anything outside it panics. Unit-test this with QEMU (`tools/qemu-sweet.py`) by feeding it bad LBAs.

**Exit:** XNU reads the GPT and the HFS+ volume header from the window; the log ring is readable from Linux.

### Phase 4: iOS root and first userland boot

- `tools/mkiosroot.sh` + `sweet-root-tweaks.py` on WSL. Option A: size as sweet does (it goes into userdata).
  Option B: measure first; it must fit in 6 GiB minus `/private/var` headroom (trim language packs, voices and so on).
- Write it: Option A `fastboot flash userdata`; Option B `dd` from Nura to p65 (first 3 GiB) and p66 (the rest).
- Boot-args from topaz minus its hardware flags: `rd=<emmc root>`, first read-only (`ufsrw` off: the topaz lesson), then `rootrw=1`.

**Exit:** launchd → backboardd → SpringBoard lock screen, rendered by the CPU (expect a few minutes on the Apple logo).

### Phase 5: input and display fit

- BLSP QUP v2 I²C driver (`0xc175000`), NT36672A at `0x01`, reset GPIO 66, IRQ from the DT. Protocol reference: Linux
  `novatek-nvt-ts`, UniXNU's Novatek driver. Deliver HID digitizer events (sweet patch 0058/0060 path).
- Keys: PM660 PON power + volume down, volume up on the PMIC GPIO, through SPMI arbiter v3.
- Display: 1080×2160 vs the 1125×2436 iPhone X canvas. Use topaz's aligned crop/scale (0114) and tune `sweetfb_hz`.

**Exit:** unlock with a swipe, open Settings, lock with the power key.

### Phase 6: make it pleasant

- RTC from the PM660 RTC (`rtc@6000`). topaz still starts on 31 December.
- Battery: an IOPMPowerSource fed by the real fuel gauge (we know the PM660 FG SRAM layout from the Nura work).
- **Charger:** under iOS nothing sets the 3.95 V limit or the 1.5 A input (that's our Linux patch + `battery-limit.service`).
  Port those SPMI writes into the XNU battery driver: same registers, same clamps.
- USB networking (sweet patches 0072–0081, ECM gadget) for SSH and logs over USB, if the DWC3 at `0xa800000` cooperates.

### Phase 7: 4K pages and all 8 cores (experiment)

- Port UniXNU's XNU patches (granule, page-shift policy, user map, commpage, shared region, code-signing hash cache, PGZ, ptoa)
  onto our kernel as a second build: `JASMINE4K`.
- ADT describes two clusters (Gold = P, Silver = E). The shim no longer needs the Gold hand-off for page size, but
  booting on Gold first is still fine.
- Recheck every 16K assumption in the shim and in sweet/topaz's own drivers (DMA alignment, framebuffer surfaces, IOSurface).
- The 16K build stays the default until 4K reaches the home screen.

### Phase 8: Wi-Fi (big, optional)

Port topaz 0113–0130 (modem PAS boot, GLINK/QRTR, pd-mapper/tftp/rmtfs, WLFW, HTT/WMI, WPA2) to SDM660's
WCN3990, and carry the TxBF-on-disassociation fix we needed in Linux r109. Only after this would iOS be on the network.

GPU (Adreno 512) is out of scope; nobody has a starting point for it.

## Safety rules

1. Nothing is flashed to boot/vbmeta/ABL/XBL/modem/persist. iOS only boots with `fastboot boot`.
2. The block driver is read-only until 3b. After that, writes are clamped to the window in the lowest layer, checked
   against the GPT at attach, and the driver never sends CMD6.
3. GPT, persist and the modem partitions are backed up before the first test (Option B: the server phone too).
4. Every kernel build must reset through PS_HOLD on panic. A hang means a hardware long-press, and on the server
   that means you have to be there.
5. Only Gold cores until phase 7, and no CPU hotplug (the server powered off after re-onlining cores on 2026-10-02).
6. Battery: during iOS sessions the charge limit isn't enforced until phase 6, and the default 500 mA input limit may be
   below the load. Short sessions, or watch the voltage.
7. Apple's IPSW is downloaded by us from Apple and never put in git or shared (sweet/topaz handle it the same way).

## Rough effort

Going by how fast sweet → topaz went (lock screen within days, with the same base): phases 1–2 take a few sessions.
Phase 3 is the biggest unknown (a new driver plus disk safety). Phase 4 is mostly image building. Phase 5 is two
small drivers. Phases 7 and 8 are open-ended.

## Decisions for you

1. **Second Mi A2 (Option A) or dual-boot on the server (Option B)?** Recommended: A.
2. **Base:** ios-topaz with the iOS 16.7 iPhone X userland (recommended) vs UniXNU with iPadOS 17 (needs a Mac or
   a macOS CI port of their build driver, and a UEFI port for jasmine).
3. **GitHub account** for the fork, since kernel builds run on its free macOS runners.
