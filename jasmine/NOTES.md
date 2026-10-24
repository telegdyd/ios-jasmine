# jasmine (Mi A2) working notes

**2026-10-24: PERF-TASKS.md editorial cleanup.** Existing tasks grouped into open performance
improvements (2/3/5/6/10/11/12/13/16), open bugs (8/14), completed work (1/4/7/9),
and closed investigation (15, persistence premise disproved by the later wallpaper investigation).
Numbers preserved; completed briefs condensed; obsolete 266-MHz default and deadlock/persistence
claims corrected. Historical timings and outstanding validation remain labelled. No new tasks
added; performance blind spots are recommendations in the chat awaiting the user's decision.
Documentation-only: no build, CI run, boot, flash, root change or phone access. Existing
task-5/GPU/CPU-clock working edits preserved. Next: user's choice of proposed additions;
task 5 remains the measured steady-rendering lead. Commit: see git log for
`docs: group performance tasks and separate completed work`.

Read this first. Plan: [PLAN.md](PLAN.md). Hardware: [HARDWARE.md](HARDWARE.md). GPU plan: [GPU.md](GPU.md).
**2026-10-24 05:05-05:45: why there are no wallpapers (and no widgets/app extensions) — cause found, fix j0070 building.**
- Observed (slot b j69b, `logs/netlog-wp1-slotb.txt`): PosterBoard runs, but no poster extension
  (CollectionsPoster, Gradient, Emoji, ... 10 on the root) is ever started. The stock wallpaper data is on the root
  (`/Library/Wallpaper/Collections`: iOS 16 WWDC_2022 in 375w-812h, Stripes, Bokeh, Desert, ...; iOS 14/15 sets are
  plists whose images come from MobileAsset).
- `ios/sweet_extq` (new, through sweetd): LaunchServices has **1 plugin in all** (an ExtensionKit `.appexpt` one);
  every poster extension `-10814` "Unable to find this application extension record"; ExtensionKit and NSExtension
  queries for `com.apple.posterkit.provider` return 0. `--sync` (lsd syncs with installd) changes nothing.
- `ios/sweet_oslog` (new, reads the unified log on the phone through LoggingSupport's OSLogEventStore; OSLogStore's
  system store returns nil on iOS): lsd at "Registering extension points" logs ExtensionKit
  `Failed to read extension point cache ... Unable to find AMFI` (error 12). The NSExtensionSDK extension points
  (PosterKit.framework etc.) come only from that signed cache, so every extension using them is rejected.
- ExtensionFoundation (disassembly, `~/ios-work/lsd/ExtensionFoundation.s`): `IOServiceMatching("AppleMobileFileIntegrity")`
  -> none -> "Unable to find AMFI"; else `IOServiceOpen` type 0, `IOConnectCallMethod` selector 6 (scalar 1 + cdhash);
  0 = trusted, 0xe00002f0 = not in trust cache. topaz 0151 publishes exactly this service, but j0001's board guard put
  `sweet_amfi_service_init()` under `if (topaz)` ("not yet tried on jasmine"), so jasmine never had it.
- Fix **j0070** (`xnu/patches/j0070-jasmine-amfi-service-all-boards.patch`): call it on every board. Kernel CI
  `40059091430` (topaz_4k=1, `xnu/out-jasmine-j70`). Earlier "no -10814 lines" checks (j51) meant nothing: the netlog
  carries no userland log; use `sweet_oslog SECONDS proc[,proc] [substring]` now.
- **Result (test image `shim-boot-j70-amfi.img`, 05:49):** "AppleMobileFileIntegrity service published", lsd calls
  selector 6 (1 scalar, 20-byte cdhash), lsd logs 133 "Registering extension point". The stored LS database
  (it *is* kept across boots, in `/private/var/mobile/Containers/Data/InternalDaemon/D7413A5E-.../Library/Caches`;
  task 15's premise looked at another container) still had the old bundles without plugins, so one
  `sweet_extq --rebuild` (needs `com.apple.lsapplicationworkspace.rebuildappdatabases`, now in
  `ios/entitlements.plist`) was run at 05:53: **413 plugins** (was 1), 9 of 10 poster providers (Weather placeholder
  missing). Persisted after a reboot (05:57). A fresh root seeding with j0070 should get them directly (not tested).
- **Slot b = j0070 since 05:58** (`shim/out/shim-boot-j70-slotb.img`, `flash-slotb.sh`, cmdline identical to j69b,
  first boot `logs/netlog-j70-slotb.txt`: boot_b marked successful, no panic, GPU self-test OK). PosterBoard starts
  Gradient/Collections/Extragalactic/Emoji/Pride/Unity/Photos/Aegir posters at boot; CollectionsPoster renders
  7400 (WWDC_2022) and PosterBoard saves gallery snapshots (`research/wp-j70-posters.txt`).
- **OPEN, new on j0070: Settings > Wallpaper freezes the phone** (user, ~06:01). `logs/netlog-j70-freeze2.txt`:
  PosterBoard[188] and AegirPoster abort (SIGABRT, uncaught ObjC exception on the main queue: `_objc_terminate`
  <- `_dispatch_client_callout` <- `FBSSerialQueue`); AegirPoster respawns and aborts 5x, then jetsam-style SIGKILLs;
  assetsd aborts 4x; "Failed to open swap file 2"; backboardd "caches of 4914 MB maintained ... 822 whole-cache
  flushes", then "3 submits in 76585 ms". Later the command port, sweetd and the netlog server stopped answering
  (netlog accepts and closes with 0 bytes): looks like memory exhaustion (guess, not proven). User recovered with
  Power+VolDown 06:17. Next: on a fresh boot *before* opening Settings, `sweet_oslog` over the frozen boot's window
  for the exception text ("Terminating app due to uncaught exception") and memorystatus/jetsam lines; then likely
  keep AegirPoster (Astronomy; Metal/SceneKit?) from respawning, and see what grows backboardd's cache maintenance.
- 06:18 I ran `fastboot reboot` after the WiFi session had taken the phone lock (06:16:53; my lock check did not
  gate the command); told that session. Phone left to it, booting slot b. Not parked (user: not needed now).
**2026-10-24 task 5 step 2 in progress (user authorized):** gate the wrapper's texture
barrier on Mesa's active graphics-program 2D sampler units, rather than stale bindings
(especially the reserved framebuffer-fetch unit). Mesa updates linked sampler maps on
UseProgram/Uniform/relink; no per-draw uniform queries or duplicate sampler cache.
`SWEETCA_ACTIVE_BARRIERS=0` retains legacy behavior for comparison; default is active
sampler gating. Opt-in counters distinguish needed/skipped barriers. Added actual GL
sampler-state regression cases; corrected the known IOSurface helper stride/offset
swap to restore render-target test coverage. Local helper/test syntax passes and
patches apply in order. Next: Mesa CI, separate test dylib and temporary RAM boots,
pixel checks and repeated profiling-off comparison. Phone remains in r109 charging
console while building; no lock held, production dylib/slot b unchanged.
**2026-10-24 task 5 step 1 complete:** [draw-path diagnostics](PERF-TASK5-DIAGNOSTICS-20261024.md).
Results, parser and GPU/PERF references committed and pushed as `91c2346`.
Pipelining is now task 16 in PERF-TASKS.md. No optimization or sync change yet;
task 5 overall remains open. Next: trace active sampler use and required dependencies,
then reduce unnecessary barrier-driven batch breaks while preserving framebuffer fetch.
Measured: 76-80% one-draw batches; texture barriers cause 60-74% of finalizations,
resource dependencies another 19-32%. Warm program-cache hits 100%; uploads smaller.
Timers are elapsed incl/excl, not CPU/frame time. Independent display CPU ~77% home,
~89% Control Center, Mesa/wrapper user + support ~65.5% of its CPU (off samples).
Counter-on GL elapsed +0.9% home / +5.1% Control Center vs off; approximate, not a
precise overhead calibration. Four six-second profiles, 227328 records, zero dropped;
two ~30 s repeats per workload/variant. Raw logs/profiles/scripts in `research/t5/`.
Opt-in `SWEETCA_DRAWPROF=1`; parser `tools/g2/drawsum.py`. All 13 changed Mesa TUs
pass host syntax; nested/early-return, four-thread counters, exclusive time and disabled
mode checks pass; fresh patch order verified. Diagnostic commit `8a3ed2b`,
Mesa CI `40051205502` PASSED; downloaded under
`xnu/out-mesa-t5diag/`, dylib SHA256 `7df9e5224e25d87da68a2a1adb732291f8ebfbe1a0be8ab992d94b598447e5fd`.
Uploaded separate `/usr/local/bin/libsweetca-t5diag.dylib` and test binaries; production
library untouched. Temporary `shim/out/shim-boot-j69b-t5on.img` booted 03:55:13,
`...-t5off.img` 04:04:33; same j69b kernel (CI 40040874776), Gold1747/GPU588/DDR1296,
adds diagnostic env and `sweetfps=1` (swap arrivals, not confirmed latch FPS). No flash.
On->off reboot hung at root unmount; user Power+VolDown recovered fastboot. Off->r109
reboot succeeded normally; r109 RAM boot at ~04:08:30. At ~04:10 qcom-battery reports
Charging, +709960 uA, 3983144 uV, 58%; backlight 0, charge voltage 3950000.
Regression-test caveat: fresh diagnostic and exact task-4 `sweetgpu_gltest` both fail
the IOSurface target helper with row stride 0 (other five cases pass); the much older
installed test passes. Root cause found: `sgl_surface_create_iosurface()` passes 0 as
stride and `bytes_per_row` as offset to `sgl_import_iosurface()`. Pre-existing since
offset support was added, and only used by the test, not CA; no fix included in diagnostics.
**User's standing request (2026-10-24): park in the charging console whenever the phone
is not needed.** Park in r109 Linux charging shell, temporarily booted from
`shim/out/nura-r109-boot_a.img`, backlight 0, charge voltage 3950000. Earlier verified
Charging, +722655 uA at 34%, later +402831 uA at 38%. USB shell takes a few minutes
after the Nura logo; a 90 s connection timeout does not prove failure.
Use `tools/pmos-shell.py`; its network is 172.16.42.1, host Ethernet 172.16.42.2/24.
Final charging check passed; our phone lock released and own collectors stopped.
Do not use the older `nura-debugshell.img`
for parking (its kernel discharges). Existing unstaged CPU-clock notes below belong to
earlier work; preserve them.
**2026-10-24 03:22: current bottleneck first pass complete**: [baseline report](PERF-BASELINE-20261024.md).
Nine 6-second profiles (0 dropped), repeated home/Control Center/Spotlight and lower-rate checks;
separate GPU counters. Same running j69b slot-b boot, 4 Gold at 1747, GPU 587-588, DDR ~1296,
installed dylib exactly matches `out-mesa-t4final`. CA display thread on CPU ~75% home,
82-85% Control Center; Mesa/wrapper + support ~63-66% of its CPU. GPU busy averages 34-46%,
with RAM stalls; first Spotlight has ~276 ms shader-worker wait, absent in repeat.
No software/clock change, reboot, flash, new build or CI run. Raw artifacts/scripts ignored in
`research/perf-firstpass-20261024/`. Task 5 remains next; current FPS/ms-frame still unmeasured.
Final 03:24 check: profiler idle, GPU 12516/12516 completed, clocks unchanged;
our console collector stopped and phone lock released. No new CI run.
Report and GPU/task references committed as `b031eac`; no implementation change yet.
**2026-10-24 02:45: boot-logo freeze fixed (PERF-TASKS task 14)**: not a deadlock: lsd's database seed waited 5 s per built-in app (173 bundles, ~14 min) because MobileGestalt's UniqueDeviceID needs a Wi-Fi MAC; with none in `/chosen` and no IONetworkController it waits 5 s for one and returns NULL (not cached). `tools/mkadt.py` now puts synthetic `mac-address-wifi0` / `mac-address-bluetooth0` into `/chosen` as iBoot does (the phone now has a UDID); 12/12 clean boots at 588 MHz, on slot b. Open: lsd never saves its store (seeds every boot; [PERF-TASKS.md](PERF-TASKS.md) task 15), syscfg 5-second waits (no `syscfg-v2-data`).
**2026-10-24 01:12: daemon retry loops gone (PERF-TASKS task 7)**: mediaserverd's BTAudioHALPlugin reconnected to bluetoothd's removed service and vmd retried CoreTelephony without CommCenter; launchd and logd served them. On the phone's root: `BTAudioHALPlugin.driver` in `/System/Library/Audio/Plug-Ins/HAL.disabled/`, vmd job out of the launchd cache (originals in `research/t7/`); `tools/sweet-root-tweaks.py` does both for new roots. Idle: 2.16 cores -> ~0.003 (launchd 966 -> 1.7 ms/s, vmd 644 -> 0, mediaserverd 412 -> 1.3, logd 139 -> 0.3), TSENS ~8 C lower. GPU.md "Task 7".
**2026-10-23 01:55: j0058, the MDP scales the frame (PERF-TASKS task 1 done)**: no CPU display copy any more (VIG0 QSEED3 + GPU-pool frames scanned in place), honest SwapWait + GPU wait for the latch; no flicker, smooth (user). On by default, kernel CI `39873547890` (`xnu/out-jasmine-j58`), on `jasmine-merge` as `90c3934`. Next frame-rate tasks: [PERF-TASKS.md](PERF-TASKS.md) 2-8; GPU.md "j0058".
**2026-10-22 22:15: j0052 Edge scheduler CLPC stand-in** (UI QoS on Gold, DF/UT/BG on Silver, Silver takes UI work only when Gold is overloaded; `sweetclpc=0` off): UI threads no longer land on Silver, ~10 s of background work per 10 s leaves Gold; 8-core frames ~96-128 ms vs ~132 before (reference lib), on/off/`cpus=4` within noise on j0053-56. `SWEET CLPC` stats lines name where CPU goes: mediaserverd spins ~40 % of a Gold core (IN QoS), not yet looked at. GPU.md "j0052".
**GPU work (G2) handoff, 2026-10-21 21:45: [HANDOFF-G2.md](HANDOFF-G2.md)** (state, rules, workflow, next steps).
**2026-10-22 17:17: ALL 8 CORES RUN** (4K-page kernel, topaz 0140/0141 AMP, CI `39798911718`, image `shim/out/shim-boot-m4kf-osm.img` = `AMP=1 bash tools/cpuclk/osm-round.sh - m4kf "sweetosm=0"`): Gold P cluster at 1747 MHz + Silver E cluster at XBL's 1382 MHz, `SWEET GOLD: 1747 MHz, 8 cores x 100 runs at once: 0 errors`, SpringBoard + GPU UI up. Upstream (topaz e477291, sweet 067c9b3) merged first. Details: section "Upstream merge and 8 cores" below. Slot b still has the old 4-core kernel (nothing flashed).
**Next (user, 2026-10-22 05:10): Gold clock done properly (OSM + CPRh + DVFS): brief [HANDOFF-CPUCLK.md](HANDOFF-CPUCLK.md).** G2 speed state: GPU.md "G2 step 3, speed" (kernels j0035-j0038).
**G2 step 3, 2026-10-22 04:09: backboardd draws the UI on the Adreno 512** (libsweetca injected with `sweetenv`; home screen and Settings correct incl. all labels, no SMMU fault/hang/panic in 5 rounds; kernel j0034; GPU.md "G2 step 3"). Open: lock screen not captured, speed not measured, `sweetca_test` now FAIL on image orientation.
**Licence, 2026-10-22 ~04:10 (user): ios-sailfish's code MAY be copied and adapted.** Its author (Joran Vancoillie, [joranv1/ios-sailfish](https://github.com/joranv1/ios-sailfish)) consented on Reddit to adapting it to other devices. This voids the "write our own code" rule in HANDOFF-G2-STEP2.md §3 and GPU.md (an agent's assumption, never the user's). Port from sailfish (`tools/sweetgl/eagl.c` and friends) whenever it covers a problem, and credit it in comments and docs.
**G2 step 2 done 2026-10-22 03:01: `sweetca_test` PASS** (CA's GLES renderer on the Adreno 512 matches the CPU renderer within tolerance; the black corners were an incomplete render-target texture sampled for framebuffer fetch, fixed with our own sampler, commit `d8503bf`, CI `39702791445`; GPU.md "G2 step 2 done"). Next: step 3 (backboardd), needs the user's OK.
**G2 step 2, 2026-10-22 02:20: CoreAnimation's GLES renderer draws on the Adreno 512 through libsweetca** (2290 of 65536 pixels still differ from the CPU renderer: black corners on a cornerRadius+masksToBounds layer; `sweetca_test` not yet PASS). Details, tries and next experiments: [HANDOFF-G2-STEP2.md](HANDOFF-G2-STEP2.md) (Result).
**G2 step A done 2026-10-21 ~22:00** ([GPU.md](GPU.md), "G2 step A"): backboardd already falls back to CA's GLES
renderer when `[[EAGLContext alloc] initWithAPI:3 ...]` works; CA calls GL only through Apple's GLI dispatch (60
entries, [ca-gles-calls-ios16.txt](ca-gles-calls-ios16.txt)). Recommended: EAGL on sweetgl (route 2); the `gld*`
plugin (route 1) would be a full GLD driver. Waiting for the user's route decision.
**2026-10-21 ~23:00:** ios-sailfish (Pixel 1, Adreno 530) runs CA on freedreno by route 2; comparison and new
next steps in [GPU.md](GPU.md). **2026-10-21 23:39: kernel j0033 PASS** (CI `39668634610`): `sweetenv` boot-arg +
"AMFI" dyld policy call let `DYLD_INSERT_LIBRARIES` load a library (`sweet_envtest`), GPU SMMU faults no longer
reported to the GPU, 128 KiB scratch pad after each GPU buffer, freed GPU VAs reused; fdtest/gltest still PASS.
Next: step 2 (EAGL layer on sweetgl, CARenderer test), brief in [HANDOFF-G2-STEP2.md](HANDOFF-G2-STEP2.md).
Licence of ios-sailfish's code: open (no licence file); until noted here, write our own code. CI note: macOS arm64 runners were unavailable for ~45 min;
`tools/g2/ci-wait.sh RUN...` re-runs jobs no runner picked up.
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
3. CPU (**8 cores since 2026-10-22 17:17**, see "Upstream merge and 8 cores"): **Gold clock, quick way (j0015, `sweetgold=MHz`)**: XBL leaves the Gold cluster on GPLL0 (~600 MHz; Silver on its PLL at 1382 MHz). j0015 moves Gold onto its own PLL at a downstream table step **without touching the voltage**, checked by a deterministic workload (one core at the switch, all four at 20 s; wrong results -> back to GPLL0). Then all 8 cores (4K pages, UniXNU).
   **Settled 2026-10-21 at a fixed 1747.2 MHz** (`sweetgold=1747` in the slot b image `shim/out/shim-boot-j16-slotb.img`): XBL's boot clock measured ~180 MHz (GPLL0 arrives divided), workload x6.05 at 1094, x5.78 at 1382, x6.23 at 1728 MHz vs boot; 1094/1382/1728 MHz all correct with 0 errors on four cores at XBL's voltage. Higher steps (1958/2150/2208, images built, j0016) not tested: the proper way replaces this anyway. No DVFS: fixed clock, no throttling (TSENS logged around the load check). Fallback if it ever misbehaves: `sweetgold=1401`.
   **TODO, the proper way:** port msm-4.4 `clk-cpu-osm.c` + `cprh` (sdm660.dtsi `qcom,clk-cpu-660@179c0000`, sdm660-regulator.dtsi `apc1_cpr` 0x179c4000): read the speed-bin and CPR fuses (0x784130, fuse_base 0x784000), build the OSM LUT (perfcl speed bin 1: 300/1113.6/1401.6/1747.2/1958.4/2150.4/2208 MHz, ceilings 724/724/788/868/988/988/1068 mV, floors 588..844 mV), program the OSM sequencer and APM (crossover 872 mV), enable CPRh closed loop. Then per-chip voltages, DVFS and the hardware limits (LMh) instead of a fixed clock at XBL's voltage. Facts found 2026-10-21: Gold PLL 0x17816000 (L 0x20, user 0xf, config 0x200d4828, mode 7), RCG 0x17811050 cmd 2 cfg 0x401; Silver PLL 0x17916000 L 0x48, RCG cfg 0x501; OSM version 0x70000, enable 0; SAW4 PMIC_STS and CPRH_STATUS 0 (never used); speed-bin fuse 0x784130 = 0x3040008c 0x88614230; the APC rails (PM660 S1-S3) are not readable from the apps EE.
4. Wi-Fi (WCN3990 on the modem DSP; topaz 0113-0130 as the model).
5. GPU (moved ahead of 8 cores and Wi-Fi: the lag is CoreAnimation's CPU renderer), plan in [GPU.md](GPU.md); G1 under way, the CP runs commands since 2026-10-21 13:40. Background: topaz runs CoreAnimation on its Adreno 610 with HackiOS's private patches (kernel driver + Mesa freedreno as the GL ES renderer), to be published in topaz once HackiOS publishes. `git fetch topaz` and check after each step; if still unpublished after 1-4, consider our own Adreno 512 (a5xx) work: firmware (a530_pm4/pfp, zap shader via TZ), GPU clocks/GX power, GPU SMMU, freedreno.

## CPU clock (OSM + CPRh, brief [HANDOFF-CPUCLK.md](HANDOFF-CPUCLK.md))

- **Licence (user, 2026-10-22 ~05:25): close adaptation of the Linux msm-4.4 drivers into the XNU patches is OK**, with The Linux Foundation copyright notice and credit in the file.
- Sources: LineageOS `android_kernel_xiaomi_sdm660` lineage-19.1 in WSL `~/cpuclk-src` (clk-cpu-osm.c, cprh-kbss-regulator.c, cpr3-*.c, msm-spm.c, gcc-sdm660.c). Stock DT `~/jasmine-dtb/stock/dtb0.dts`. On stock TZ owns the OSM sequencer setup (no `qcom,osm-no-tz`: Linux writes SEQ_REGs with `scm_io_write`).
- **Phase 0 (05:20):** `tools/cpuclk/cpuclk_model.py DTS FUSES` computes speed bin, fuse combo, CPRh corners (floor / open loop / ceiling / target quotient / `CPRH_REG_CORNER` words) and the OSM LUT, every step with its source line.
- **Phase 1, j0039 (`sweetosm=1`, read only), rounds:**
  - 05:27 `j39` (CI `39716392018`): probe inside the platform expert, read fuse rows 36..72: **the read of row 36 (0x784120) never completed**, boot stopped there (no watchdog yet, user needed). Read only rows Linux reads.
  - 05:37 / 05:51 `j39b` (CI `39717275885`): probe in its own thread at 8 s: panicked before USB was up (no log). Probe moved to 60 s.
  - 06:00 `j39c` (CI `39719520608`, `logs/netlog-j39c-osm.txt`): fuses read, table computed, OSM LUTs of both clusters all zero (OSM never programmed), GCC HMSS: RBCPR CBCR 0x48008 = 1 (on, XO), hmss_gpll0 RCG cfg 0x100 (GPLL0 undivided). Then **SError ("Unhandled implementation specific error") on CPRh offset 0x0**, which Linux never reads: dump only the registers the drivers use.
  - **Kernel table = model table exactly** (model run on the j39c fuse lines). This chip: speed bin 1, CPR fusing rev 2, fuse combo 10, all ROs 7. Fuse rows: 38 `0x886142303040008c`, 65 `0x0700084210020000`, 66 `0x0416c5455c41f150`, 67 `0x2463338e8af07777`, 68 `0xeee0a28c2f150184`, 69 `0x4085e07513cb454e`, 70 `0xf3f5b82c89e484b4`, 71 `0x0000010021c39550`.

    | Corner | MHz | Floor mV | Open loop = ceiling mV (DT ceiling) | Quot | CPRH_REG_CORNER |
    | --- | --- | --- | --- | --- | --- |
    | 0 | 300 | 652 | 692 (724) | 468 | 0x0e003f49 |
    | 1 | 1113.6 | 652 | 692 (724) | 468 | 0x0e003f49 |
    | 2 | 1401.6 | 708 | 748 (788) | 583 | 0x0e1d4d57 |
    | 3 | 1747.2 | 788 | 828 (868) | 737 | 0x0e44616b |
    | 4 | 1958.4 | 852 | 880 (988) | 840 | 0x0e5d7178 |
    | 5 | 2150.4 | 864 | 928 (988) | 932 | 0x0e747484 |
    | 6 | 2208 | 908 | 948 (1068) | 1037 | 0x0e8f7f89 |
    | 7 (APM crossover) | - | 872 | 872 | - | 0x20007676 |

    OSM: APM threshold vc 4 (pre 3), crossover vc 7; MEM-ACC threshold vcs 1 2 5 6, SEQ_REG(32) L 0x73.
  - 06:11 `j39d` (CI `39720350595`): OSM both clusters at reset values (enable 0, LUT 0, PDN_FSM 0x05000000, LMh request 0x05dc00ff); APCS LMH RCG cmd 2 cfg 0x105 = hmss_gpll0 (600 MHz) / 3 = 200 MHz OSM clock, running; CPRh CPR_CTL 0xfffffe3e (reset). SError on the CPRh GCNT / sensor registers (0x0d4..0x140, Linux only writes them).
  - 06:19 `j39e` (CI `39721248584`): complete. Through TZ IO read: OSM program memory 0, Gold SEQ 4 = 0x179c0240, SEQ 7 = 0x17811250, SEQ 47 = 0xf, SEQ 55-58 = 7/8/11/12, SEQ 72 = 0x19, SEQ 73 = 0x400000, SEQ 76 = 0x5b9; Silver alike. CPRh CTL / STATUS 0, SAW4 PMIC_STS 0.
  - 06:31 `j39f` (CI `39722215911`): TZ IO writes of the current value return 0 for SEQ 72, SEQ 0 and program word 0.
  - 07:19 `j43` (j0043, CI `39726717817`): **the sequencer region is not readable from the apps side** (direct reads give the previous bus value, then 0). TZ's values above are its defaults for a 25-row LUT (crossover 25, APM threshold 22): TZ ran an OSM init of its own.
- **Phase 2 (j0040 `sweetosm=2`, j0041/j0042/j0044 diagnostics), the stock TZ path (stock Linux and SoMainline's upstream MSM8998/SDM630 series write only the LUT + policy directly and SEQ 15/31/32/55-58/72/76 through `scm_io_write`; no other OSM TZ call exists in the downstream kernel):**
  - 06:40 `j40` (CI `39723238644`): no hang. CPRh init (open loop) CTL 0x80a00c9 MARGIN_ADJ_CTL 0x4080, SAW AVS_CTL/LIMIT as stock, LUT read back correct, all 9 TZ sequencer writes read back. **OSM enable 1, desired stepped 0..3, but the clock never moved**: Gold PLL L 0x20, RCG cfg 0x401 (GPLL0 = index 0's source), pstate 0, CPRh corner 0, SAW PMIC_STS 0, workload ~580 MHz at every step. The sdm660-mainline OSM PR #239's SDM660 tester (Redmi Note 3, same speed-bin fuse 0x3040008c) saw the same.
  - 06:54 `j41` (CI `39724520008`, `osmseq=1`): B (LLM votes and CC DCVS off) no change; C (Linux's no-TZ sequencer load through TZ IO writes) no change: **TZ answers 0 to IO writes outside stock Linux's set but drops them** (SEQ 0, SEQ 39 and the branch table read back 0). The no-TZ path is impossible from the apps side.
  - 07:07 `j42` (CI `39725646937`, osm watch, `osmdelay=15`): the word at OSM+0 is no version register (flips 0 / 0x70000 / 0x1 every few hundred ms); enabling at 15 s changes nothing either.
  - 07:31 `j44` (CI `39727833856`): D, the zero-core override (CC_ZERO_BEHAV_CTRL bit 0 + index), no change. Cycle counter control reads back 0x113 but the counter (0x1f04) and the sequencer PC (0x1c74) stay 0: **the OSM core does not execute at all**.
  - Every j40..j44 step passed the 4-core check: nothing broke, the cluster simply stays on GPLL0 (~590 MHz while sweetgold is skipped).
- **Live tool, j0045 (2026-10-22 ~07:50):** with `sweetosm=` set the USB command port takes `r/w ADDR` (whitelisted clock / OSM / CPRh / SAW / APCS / GCC / TSENS blocks), `tr/tw` (TZ IO), `check`, `tsens`, `state`, `table`, `prog`; host `tools/cpuclk/osmctl.py 'cmd; cmd'`. `sweetosm=8` = table + commands only. Image `shim/out/shim-boot-j45-osm.img` (CI `39729734795`), log `logs/netlog-j45-osm.txt`.
- **Live session 07:52-08:05 (j45):**
  - OSM cycle counter enabled (0x113 reads back) on both clusters: stays 0. APCS LMH (OSM clock) RCG re-latched (0x179d112c 0x3 -> 0x2, cfg 0x105): no change.
  - **Silver OSM is dead too**: Silver LUT (stock pwrcl rows) written and read back, enable 1, desired 0 -> 3 with the Silver cores off: Silver PLL L 0x48 / RCG 0x501 unchanged, PC 0, counter 0. So neither OSM core executes; it is not about Gold or CPRh.
  - APCS common 0x179d1050 and 0x179d1058 read 0x80000002 (CBCR-like: CLK_OFF, HW_CTL, enable 0); 0x179d104c = 1, 0x179d1070 = 0xb. 0x1050 ignores writes (secure); 0x1058 takes the enable bit but stays CLK_OFF; TZ IO writes to both are dropped. Restored.
  - Gold SAW4: version 0x40010001, ID 0x2020016f (PMIC arbiter present), CFG 0x14, PMIC_DATA_0 0x03030080, DATA_1 0x30000, VCTL / AVS / PMIC_STS 0: the SAW voltage interface has never been used on this boot. Silver SAW identical.
  - **Stock-kernel reference (08:00-08:18), no result:** the backed-up slot-b boot image (`backup/nura-full-20261020/p63_boot_b.img.gz`, msm-4.4 Android kernel, `buildvariant=userdebug`) repacked with a static `/init` (`tools/cpuclk/refinit.c`, no Android userspace; `shim/out/stock-ref-boot.img`, built from WSL `~/stockboot`) and `fastboot boot`ed. j0046 (`osmctl ramoops KEY`, CI `39732000976`) found nothing in ramoops at 0xa0000000 afterwards (not even the pstore signature), and with a 60 s sleep as the init's first action the phone still came back to fastboot 24 s after the boot: **that kernel resets ~20 s after start without reaching init** on this boot path, so it gives no OSM reference. `tools/cpuclk/ref-round.sh` automates the round.
  - Conclusion so far: OSM bring-up (sequencer program, its clocks) belongs to TZ and does not happen on this boot path; the apps side can neither load it (TZ drops the writes) nor clock it (secure branches). Open: whether stock Android gets OSM running with the same firmware (stock-kernel reference), else software DVFS through the SAW (needs the PMIC level code for a known voltage).
- **Software DVFS (user approved ~14:40): software PLL switching + Gold voltage through the SAW, a load governor and a TSENS limit.** Voltage path work, 2026-10-22 afternoon:
  - j0047 (`osmctl spmi SID ADDR [N]`, `rails`; v1 CI `39785267850` read through `sweet_spmi.c`, which is topaz-only and never initialised on jasmine, so every read failed; v2 reads through `sweet_pmic_peek`). j0048 (CI `39789569984`, image `shim/out/shim-boot-j48-osm.img`): sequences in the live tool, `m` (read-modify-write), `poll ADDR MASK VAL [US]` (a timeout skips the rest of the line), `d US`, `t`, `rep N`; 2 KiB lines, 8 KiB replies. Experiments are command lines now, not kernel builds. CI waits today: the macOS arm64 runners queued 10-30 min per build.
  - **PM660 (SID 1) APC supplies, all FTS426 (type 0x1c/0x0a), auto mode, enabled, upper limit 1396 mV: S1 (0x1400, Silver) 872 mV, S2 (0x1700) + S3 (0x1a00) = the Gold rail, 868 mV** as the bootloader leaves them (16:03). Above this chip's 828 mV open loop for 1747 MHz, which is why the fixed 1747 MHz runs. FTS426: +0x40/0x41 set point (mV, LB/UB), +0x42/0x43 "valid" (what the PMIC took), +0x68/0x69 limit.
  - **Gold SAW (0x17812000) VCTL reaches S2 + S3** (16:04, Gold on GPLL0 ~590 MHz): SAW_RST = 1, VCTL = 0x370 -> PMIC_STS 0x370 at once (it echoes wide values; 0x400 too), S2/S3 set point 868 -> 880. **But the SAW writes only the low byte** (16:08: VCTL 0x400 left S2/S3 at `00 03` = 0x300) **and the PMIC commits only on an upper-byte write**: "valid" stayed 868 in both tests. So as configured (port 0, PMIC_DATA_0 0x03030080) the SAW cannot move the rail; stock CPRh drives it in mV units (`qcom,cpr-saw-use-unit-mV`), so a 2-byte mode exists somewhere in the SAW / CPRh setup. Next: find it (SAW CFG / PMIC_DATA format, CPRh's SAW interface), else the voltage goes another way. Restored to 0x364 (868) at 16:08; 4-core check clean throughout.
  - APM (0x179d0010 mode / 0x179d0018 status) reads 0 = Gold arrays on VDD_MX; MEM-ACC 0x179d1368..1370 (addresses from the msm8998-interposer-sdm660 DT) all 0. OSM normally switches APM at 872 mV and the MEM-ACC levels with the corner; software DVFS has to do both.
  - 16:05 panic `kmem_alloc ... failed with 3` after ~300 PMIC reads: `sweet_pmic_peek` mapped the observer channel again on every read. j0049 (CI `39792993720`, queued 16:07) maps each channel once. Until then keep PMIC reads sparse (4 per check).
  - Paused 16:10 at the user's request: first bring the branch up to date with upstream (commits that may enable the 4 unused cores), then continue here. Software DVFS must then cover both clusters (S1 Silver, S2 + S3 Gold).

## Upstream merge and 8 cores (2026-10-22 16:10-17:20)

- **Merged** topaz/topaz `e477291` (fe7625f "GPU, AMP, sound and the rest" = patches 0140-0152 + 0900-0947 from HackiOS, 0948/0949/0950) and sweet/main `067c9b3`. From sweet NOT taken: `xnu/patches/0080-sweet-net-trace` / `0081-sweet-usb-link-state` (sweet's ECM ue0 and a route trace; their numbers would apply before topaz's 0080+ and ours) and the mkadt.py `/pram` panic region (jasmine never hung at "kdp_core zlib memory"; j0030 already sends panics over USB). LICENSE (MIT, sweet's), site/, QEMU and host tools came along.
- **Our patches rebased** in WSL `~/xnu-8796` branch `jasmine-merge` = topaz-0139 + topaz 0140-0950 (one commit each) + j0001-j0050; the old stack is branch `jasmine-pre-merge` (6c60ee1). Checked: all 118 patches after topaz-series apply with `git apply` (dxb only warns and SKIPS a patch that does not apply!) and give the WSL tree exactly. Conflicts: j0001 (board guards now also keep topaz's ADSP audio, AMFI service and Adreno 610 init on topaz; TOPAZ_4K early console on jasmine's splash), j0007 (MDP flips next to topaz's GPU-pool scanout), j0010 (battery next to topaz 0148 charger), j0011 (WLED before topaz 0143 panel sleep), j0033 (our AMFI dyld policy replaced by topaz's 0902/0150, which also answers all other AMFI calls with success), j0034 (readOnly next to topaz's surface fields). j0039-j0049 (OSM, osmctl, PMIC cache) applied unchanged.
- **What upstream changed in CPU/clock/cluster code:** only 0140 (`TOPAZ_4K=1`, a make variable: 4 KiB pages, compact kernel VA at 0xfffffff007004000, 16 KiB-signed shared cache accepted with code signing off, user tasks keep 16 KiB pages) and 0141 (with TOPAZ_4K: `__ARM_AMP__`, `MAX_CPU_CLUSTERS 2`; clusters from ADT `cluster-type` 'P'/'E', Edge scheduler, no CLPC). Nothing for clocks (topaz's cpufreq-hw is SM6225-only and guarded). Topaz did NOT publish the ADT or shim side of its 8 cores; ours below.
- **Ours for 8 cores:** j0050 (SweetGPU buffers 16 KiB-sized/aligned for 16 KiB user pages; `PAGE_SIZE` is not a constant in a 4K kernel; `osmctl check` per core; cluster in the SweetCPU log), `tools/mkadt.py --amp` (cpu0-3 Gold 0x100-0x103 'P' first, boot CPU 0x100 = CPU 0 as SweetCPU wants; cpu4-7 Silver 0x0-0x3 'E', l2-cache-id 1), shim: with `cpus>4` in the payload the parked Silver boot core powers itself off (PSCI CPU_OFF) before the jump, otherwise XNU's CPU_ON(0x0) would fail (it sat in a WFI loop in shim memory). XNU's own `pe_init_fiq` wakes each CPU's redistributor, so the shim does not touch Silver's. `xnu.yml` input `topaz_4k=1` (and no ccache for `.s`: assym.s offsets change with TOPAZ_4K + AMP). `tools/g2/mkimg.sh` / `osm-round.sh`: `AMP=1`, `CPUS=N`, `RO=1`.
- **Rounds:**
  - 16:30 CI `39796201950` (4K) failed only on `sweet_gpu.c:735` (static init with PAGE_SIZE); CI `39796206722` (16K, Gold only) success.
  - 16:45 the running j48 kernel answered ping but no TCP port (5140/5141/5142) for 7 min, then reset itself into fastboot at 16:53 (cause unknown; it had run since ~16:10).
  - 16:53 `m16` (16K merge kernel, `sweetosm=8`, `logs/netlog-m16-osm.txt`): boots, 4 Gold, GPU UI via libsweetca, no panic in 150 s, `osmctl check` 4 x 0 errors (~585 MHz, sweetgold skipped by sweetosm). **New: syncdefaultsd aborts in a loop (SIGABRT, 12x in 150 s)**, not in j45-j48 logs: from the merge (likely topaz's AMFI "everything succeeds" or sandbox container hook), not investigated.
  - 17:04 `m4k` with `RO=1` (read-only root) and 17:08 `m4kg` (`CPUS=4`, RO): **launchd panics `mount[3] exited`**: its mount boot task cannot remount `/` rw on a read-only root (photo from the user). Not a 4K problem: read-only roots do not work with this launchd setup; `RO=1` is useless.
  - 17:09 `m4k` (CI `39798911718`, `AMP=1`, rw, `sweetosm=8`, `logs/netlog-m4k-osm.txt`): **8/8 CPUs**, PSCI CPU_ON rc 0 for all seven, Silver 0x0-0x3 = cluster 1 type E; SpringBoard, backboardd with libsweetca (EAGL on Mesa FD512) as on 16K. `osmctl check` 31 times 8 cores x 20 runs, 0 errors: Gold ~42.5 ms/run (GPLL0 ~600 MHz), Silver ~26.1 ms/run (1382 MHz); TSENS 50-57 C. Crashes the same as m16.
  - 17:14 `m4kf` (`AMP=1`, `sweetosm=0`, so `sweetgold=1747` runs; `logs/netlog-m4kf-osm.txt`): Gold to 1747 MHz (x6.05 vs boot), **`8 cores x 100 runs at once: 0 errors (3006 ms)`**, TSENS 56-70 C before and after.
  - **syncdefaultsd loop solved (j0051, 17:20-18:11).** Backtrace (cache slide 0x3e814000): `abort` <- `_objc_terminate` <- `std::terminate` <- `_dispatch_client_callout4` <- `_dispatch_mach_msg_invoke` = uncaught ObjC exception in a mach message handler. 17:39 `sds` (m4kf kernel + `sweetscan=syncdefaultsd`, `logs/netlog-sds-osm.txt`, not in git: heap dump with account UUIDs): `NSInvalidArgumentException ... -[NSURL initFileURLWithPath:isDirectory:]: nil string parameter`, thrown in syncdefaultsd (+0x1ad6c -> +0x1cf48) under NSXPCListener for `connection from pid N on mach service named com.apple.kvsd`, i.e. at every client connection. No `SWEET AMFI: syscall N` line in any merge log, so topaz's "all AMFI calls succeed" is not involved. Cause: topaz 0936 `sweet_sandbox_container_path` (Sandbox op 4) returned **0 with the buffer untouched** when the process has no `CFFIXED_USER_HOME` (every daemon); libsystem_sandbox `sandbox_container_path_for_audit_token(token, buf, size)` packs {pid, pidversion, buf, size, 1} and returns the `__mac_syscall` result as is, so syncdefaultsd took uninitialised bytes as the client's container path. Before the merge op 4 was ENOENT. j0051 answers ENOENT (no variable, no stack, memory unreadable); processes launched with `CFFIXED_USER_HOME` (apps by RunningBoard, extensions by pkd) get their path as with 0936. CI `39807738178` (4K; attempt 1 got no macOS runner in 15 min, rerun OK), 18:07 `j51` (`AMP=1`, `sweetosm=0 sweetscan=syncdefaultsd`, `logs/netlog-j51-osm.txt`): syncdefaultsd started once, **0 crashes in 200 s** (only driverkitd sig 9, as before the merge), 8 cores x 100 runs 0 errors; PosterBoard and pkd start as in m4kf, no PlugInKit / -10814 / "invalid sandbox or container" lines in either. New in j51: MobilePhone, WebKit, Safari History, remotemanagement subscribers, splashboardd start (partly the longer window). Phone left running `shim/out/shim-boot-j51-osm.img`.
- **For software DVFS (next):** two clusters now: Gold = P (cpu0-3, pset0) on PM660 S2+S3, Silver = E (cpu4-7) on S1 (872 mV), Silver PLL 0x17916000 (L 0x48 = 1382.4 MHz) / RCG cfg 0x501 untouched by us. The Edge scheduler prefers P and spills to E; without CLPC nothing tells it the clocks, so a governor should keep Gold faster than Silver (at GPLL0 Gold is slower). Both SAWs (Gold 0x17812000; Silver's) and both PLLs need the voltage/PLL work.
- ~~Open: slot b still the old kernel~~ flashed 2026-10-23 02:11 with j0058 (see "Standalone boot"); 4K iOS userland only watched for ~10 min so far.

## Kernel patches (ours, on top of topaz's)

Ours are `xnu/patches/j0001-*` onward so they sort after every upstream topaz number (topaz kept going at 0136; merged 2026-10-21 with topaz 0136-0139, 2026-10-22 with topaz 0140-0950). The WSL tree `~/xnu-8796` (branch `jasmine-merge`) is `6d393c1 topaz-series` (0001-0135) + topaz 0136-0139 + topaz 0140-0950 + ours, one commit each; `git format-patch` a new commit into the next j number. A kernel with all eight cores: `gh workflow run xnu.yml ... -f topaz_4k=1` and an ADT from `mkadt.py --amp` with `cpus=8`.

- **j0050** 4K pages + AMP on jasmine: SweetGPU buffers sized/aligned to 16 KiB user pages under TOPAZ_4K, no PAGE_SIZE in static initialisers, `osmctl check` per core (MPIDR, P/E, us per run, errors), cluster id/type in the SweetCPU log.
- **j0051** Sandbox op 4 (container path, topaz 0936) answers ENOENT for a process without `CFFIXED_USER_HOME` instead of 0 with the caller's buffer untouched (syncdefaultsd read the garbage as a path and aborted on every `com.apple.kvsd` connection).
- **j0052** CLPC stand-in for the Edge scheduler (jasmine ADT with both clusters only): every thread group prefers Gold for FIXPRI/FG/IN and Silver for DF/UT/BG; Gold-preferred work spills/is stolen to Silver only at a Gold runqueue depth >= 2 per CPU (`sweetclpc_depth=`), Silver-preferred work moves to Gold only onto an idle Gold CPU. `sweetclpc=0` off, `sweetclpc=2` DF on Gold. Logs `SWEET CLPC: 10 s ms` (CPU ms per cluster/QoS, off-type ms, border decisions) and every 30 s the top 5 threads by CPU. 8 cores with the reference libsweetca: frames ~96-128 ms vs ~132 before (4 Gold ~81); DF/UT/BG (~10 s per 10 s) off Gold. Found: mediaserverd spins ~40 % of a Gold core at IN QoS. Details: GPU.md "j0052". WSL `jasmine-merge` 6c7db2b (after j0056).
- **j0053** GPU speed: Mesa buffers from a write-combined pool of unmanaged RAM (0xc0000000-0xf3ffffff, topaz pool code, placed beside the shim, which passes `sweetshim=`/`sweetshimsz=`), imported IOSurfaces kept up lazily (clean if the CPU wrote them, invalidate at the CPU's next lock or the display copy). backboardd cache maintenance ~1 % instead of ~25 %, frames 38-68 ms vs 54-100 ms (4 Gold cores). `sweetgpu_pool=0` / `sweetgpu_lazy=0` switch each half off. Details: GPU.md "j0053". (j0052 = the Edge scheduler CLPC stand-in, its own session.)
- **j0058** display scale on the MDP (PERF-TASKS task 1): VIG0's QSEED3 scaler fits CA's 1125x2436 frame into 996x2160 at x 40 (ABL's VIG0 values restored for panel-size buffers), backboardd's screen-sized IOSurfaces from the GPU pool so the MDP scans them in place (no `composeFit`: present 7-40 us instead of ~8.8 ms), `IOMobileFramebufferSwapWait` (selector 6) answers honestly: a swap is done once a later one ended, and a SweetGPU submit that writes a frame the panel still shows waits for the latch. Root cause of j0056's held draws/flicker: CA reuses a swap surface when SwapWait says done, not on IOSurface in-use. `sweetfb_scale=0`, `gpu_fbpool=0`, `sweetfb_swapwait=0|2` for comparisons; MDP block open to `osmctl.py r/w`. Round j58d 2026-10-23 01:53: held draws 48 (1662 without the latch wait), user: no flicker, smooth. Details: GPU.md "j0058".
- **j0064** DDR clock vote (PERF-TASKS task 9): RPM clock handoff of every sdm660 RPM clock + scaling on, bimc "KHz " vote; command port `ddr state|MHZ|bench|bw [MS] [load] [bg]` and raw `rpm SETS TYPE ID KEY VALUE`; `sweetddr=MHZ`; CPU bwmon4 (1 MiB units) and GPU VBIF counters. Bootloader DDR = 1296 MHz; 1804 gives no UI gain (round j64a, GPU.md "j0064"), so off by default.

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
- **j0018** Adreno 512 bring-up, `bsd/dev/sweet_gpu.c` (ADT `/sweet-gpu`, firmware from `research/gpu-fw`), off unless `sweetgpu=1|2` (`gpudelay=` s, default 25): GFX LDO head switch + GPU CX/GX GDSCs + clocks from XO, the GPU SMMU's context bank 0 with an identity table (no WZR stores: the hypervisor's emulation hangs on them), microcode, CP ring, `CP_ME_INIT` and `CP_MEM_WRITE`. **2026-10-21 13:40: the GPU executes our commands** (details in [GPU.md](GPU.md)). Test images `shim/out/shim-boot-j18-gpu{1,2}.img`; the slot b image does not set `sweetgpu`.
- **j0019** zap shader through TrustZone (PAS 13; `mem_setup` needs a 4 KiB-aligned size) and `CP_SET_SECURE_MODE 0` at `sweetgpu=3`: **works since 2026-10-21 14:07**.
- **j0020** GPU core clock from GPU PLL0, `gpumhz=160|266` (measured 159 / 266 MHz, 2026-10-21 14:25); higher needs an RPM CX vote.
- **j0021** USB Ethernet (CDC-NCM, Windows inbox UsbNcm) on the DWC3 + live log server (TCP 5140); **j0022** command port (TCP 5141, `reboot` -> fastboot), USB on by default on jasmine; **j0023** USB after a normal boot: QUSB2 PHY init (Linux sdm660 table), UTMI as pipe clock, GUSB2PHYCFG as fastboot (ABL only sets USB up in fastboot mode; GDSC and clocks are on either way). `tools/reboot-bootloader.c` (static aarch64) takes the Linux charging shell back to fastboot (`pmos-push.py` it to /tmp).
- **j0024** `bsd/dev/sweet_netfs.c`: files over USB Ethernet (TCP 5142, kernel credentials): `tools/sweet-fs.py put|get|ls|mkdir|rm` (from Git Bash set `MSYS_NO_PATHCONV=1`, else `/` paths get rewritten; use Windows paths for local files). Tested 2026-10-21 15:30: 3 MB round trip identical; ~365 KB/s up, ~220 KB/s down (one frame per USB transfer, 1 ms event polling).
- **j0025** `bsd/dev/sweet_wdt.c`: APSS watchdog at 0x17817000 for test boots, `sweetwdt=SECS` (PON mode bootloader first, bark SECS, bite +3 s, pet every SECS/4), `sweetwdt_test=N` stops petting. **Tested 2026-10-21 15:44:** bite reset the phone into fastboot by itself (no crash-dump mode). Off in the slot b image. Test images: add `sweetwdt=20`, so a hang comes back without buttons.
- **j0026** SweetGPU IOKit user client (G2): buffers in a 4K-page GPU VM from 32 GiB, IB submit + CACHE_FLUSH_TS fence, kernel self-test; `sweetgpu=4`. Self-test passed 2026-10-21 (CB0 FSR reads 0x400 afterwards, unexplained). Mesa `sweetgpu_fdtest` froze the phone (watchdog) on every run.
- **j0027** IB range check (every IB inside a buffer of the client) + `sweetgpu_debug=1` (each call logged with a 150 ms pause; after a submit, 1 s hang check that dumps fault state and powers the GPU off). **j0028** logs every call on entry, clock-controller state before the timestamp read, `sweetgpu_debug=2` 10 s heartbeat (state + one GPU core read). **Result 2026-10-21 20:05 (j0028):** heartbeats fine (GPU registers keep answering), Mesa's param calls 0,2,1,3,4 all return, then the freeze is inside call 1 (first buffer, 16 KB), before its log line.
- **j0029** step log inside buffer creation; `sweetgpu_wc=0` keeps buffers cacheable (kernel and client mapping) and cleans/invalidates the client's buffers around submit/wait/completed. Suspect (not proven): a write-combined IOBufferMemoryDescriptor changes the cache attributes of its pages for every mapping (physical aperture included); SweetSurface never uses one. CI run 39650030594; test images `shim/out/shim-boot-j29-wc0.img` / `-wc1.img`.
  **Result 2026-10-21 20:16 (j0029, `sweetgpu_wc=0`):** no freeze; Mesa got the screen up, then fdtest crashed (SIGSEGV, missing `glsl_type_singleton_init_or_ref()`, fixed in the Mesa patch).
- **j0030** panic over USB: `SavePanicInfo()` spins forever on this board (no iBoot panic region), so it now first sends the console ring tail + XNU's panic buffer over the live log TCP connection (hand-built Ethernet/IPv4/TCP frames with the socket's own seq/ack/timestamps, DWC3 polled, go-back-N, 10 s max). `sweetpanic_test=SECS` panics on purpose. **Tested 2026-10-21 20:32:** the panic line and marker arrived in `logs/netlog-j30-ptest.txt`; the write-combined GPU run (`sweetgpu_wc=1`) turned out to be a panic: `phystokv_range: illegal PA: 0x7c994000; phys base 0x100000000` (`logs/netlog-j30-wc1.txt`).
- **j0031** SweetGPU buffers cacheable by default (clean/invalidate around submit/wait/completed). **2026-10-21 20:35: `sweetgpu_fdtest` PASS** — Mesa freedreno cleared a render target on the Adreno 512, 0 of 4096 pixels wrong (`logs/netlog-j30-fdtest.txt`). Test images `shim/out/shim-boot-j30-{ptest,gpu,wc1}.img`; slot b unchanged (j0024). **2026-10-21 20:49: first triangle** (fdtest stage 2, RGB-interpolated, 0 of 4032 pixels wrong, `logs/netlog-j31-tri.txt`). **21:09: OpenGL ES 3.1 through sweetgl** (`sweetgpu_gltest`: clear, GLSL triangle, blended texture, depth test all PASS, `logs/netlog-j31-gl.txt`).
- **j0032** SweetGPU imports IOSurfaces (selector 6: the surface's own pages mapped into the GPU address space, one handle per surface and client; selector 7: buffer info). **2026-10-21 21:33: GPU renders into and samples IOSurfaces** (`sweetgpu_gltest` steps 5-6 PASS: triangle into a junk-filled 64x64 BGRA IOSurface, 0 of 4032 wrong both via glReadPixels and in the surface's memory read through IOSurface.framework, top row first; CPU-painted BGRA IOSurface sampled as a texture, 0 of 4096 wrong; `logs/netlog-j32-iosurface.txt`). Test image `shim/out/shim-boot-j32-gpu.img`; slot b unchanged (j0024).
- **j0003** (was 0138) reset into fastboot: PM660 PON SOFT_RB_SPARE 0x88f = bootloader (2 << 1) through the SPMI arbiter v3 (apid 4). jasmine's ABL ignores the IMEM restart reason.

Build: `gh workflow run xnu.yml -R telegdyd/ios-jasmine --ref jasmine` (macOS runner, ~6-8 min), artifact `xnu-kernel`. Patches are written against a local patched tree in WSL `~/xnu-8796` (topaz series applied after running `xnu/patches/*.sh` with `MACHINE_CONFIG=SWEET MACOS_VERSION=13.5`).

## Standalone boot (since 2026-10-21 04:13)

- **Slot b = iOS:** root changes since 2026-10-24 01:05 (PERF-TASKS task 7): `BTAudioHALPlugin.driver` moved to `/System/Library/Audio/Plug-Ins/HAL.disabled/`, `com.apple.voicemail.vmd` removed from `/System/Library/xpc/launchd.plist` (before/after copies in `research/t7/`); first boot `logs/netlog-t7b-slotb.txt`, UI drawn, no vmd, mediaserverd started once. Userland: `/usr/local/bin/libsweetca.dylib` since 2026-10-23 07:11 = Mesa CI `39903986273` (2fc0a87, PERF-TASKS task 4: sub-allocation heaps; checked on a plain slot b boot, `logs/netlog-t4slotb.txt`; the previous one is `xnu/out-mesa-kick`). `boot_b` holds the shim image built with `abmark=b` (**since 2026-10-24 02:45: `shim/out/shim-boot-j69b-slotb.img` rebuilt with Wi-Fi/Bluetooth MACs in the ADT `/chosen` (PERF-TASKS task 14, boot-logo freeze), first boot `logs/netlog-j69m-slotb.txt`: 587 MHz, self-test PASS, UI drawn; the 01:47 build without them is `shim-boot-j69b-slotb-nomac.img`**, kernel CI `40040874776` = j0050-j0064 + j0069 + j0069b (meta wait chains, `prof peek`); before it since 00:42 `shim-boot-j69-slotb.img`, kernel CI `40026354719` = j0050-j0064 + j0069 (prof census of every thread with kernel stacks, `prof start ... NAME,all`, `tools/g2/prof.py stuck`), **GPU 588 MHz by default** (`mkimg.sh` gpumhz=588, PERF-TASKS task 14: the user watches how often the startup freeze happens; on a freeze take `prof.py fetch OUT --secs 3 --census 200000 --tasks backboardd,SpringBoard,all` before any reboot), DDR 1296 MHz; first boot `logs/netlog-j69-slotb.txt`: measured 587 MHz, self-test PASS, lock screen drawn, boot_b marked successful in both GPT copies, no panic. Before: since 2026-10-23 06:20 `shim/out/shim-boot-j64-slotb.img`, kernel CI `39889598650` = j0050-j0064 (adds j0060 GPU levels + live `gpu clk`, j0064 DDR vote / `ddr` / `rpm` command port lines; defaults unchanged: GPU 266 MHz, DDR 1296 MHz), same boot-args as before; flashed with `tools/g2/flash-slotb.sh` (PERF-TASKS "Done means on the phone"); first boot `logs/netlog-j64-slotb.txt`: GPU measured 266 MHz, self-test PASS, backboardd on the GPU, boot_b marked successful in both GPT copies, no panic. Before: since 2026-10-23 02:11 `shim/out/shim-boot-j58-slotb.img`, kernel CI `39873547890` = j0050-j0058, 4K pages, 4 Gold cores (`AMP=1 CPUS=4` ADT), the UI on the GPU (`sweetgpu=4 gpumhz=266 gpudelay=1 gpupause=0 sweetenv=backboardd:DYLD_INSERT_LIBRARIES=/usr/local/bin/libsweetca.dylib`), `sweetfb_sync=1`, `sweetcmd=1`, `sweetwdt=20` (a hang resets into fastboot); built with `GPUDBG=0 VARIANT=slotb AMP=1 CPUS=4 EXTRA_ARGS="... abmark=b" tools/g2/mkimg.sh j58`; first boot marked boot_b successful in both GPT copies, `logs/netlog-j58-slotb.txt`. Before: `shim/out/shim-boot-j24-slotb.img` from 2026-10-21 15:32, j0024 kernel, CPU renderer), `vbmeta_b` = `images/vbmeta-disabled.img`, active slot b. Power-on, reboot and charger plug-in boot iOS. The kernel (j0013) marks boot_b successful 60 s after the root mounts, so ABL never falls back (verified: `fastboot getvar slot-successful:b` = yes; both GPT copies valid; only bit 54 of entry 62 written by us).
- `fastboot set_active` also swaps the partition **type GUIDs** of every `_a`/`_b` pair (xbl, tz, abl, modem, ...): slot b's firmware chain (stock Android's) now boots the phone. Expected Qualcomm behaviour.
- **Linux shell:** `fastboot boot shim/out/nura-r109-boot_a.img` (the r109 boot_a from the backup; RAM only, slot stays b). Charging there: screen off + 3.95 V as in the charging-shell note.
- **New iOS kernel:** build the image with `abmark=b`, `fastboot flash boot_b IMG`. Test kernels: build without `abmark` and `fastboot boot` them (no GPT writes).
- **Back to Nura:** `fastboot set_active a` (boot_a untouched). Restore boot_b / vbmeta_b from `backup/nura-full-20261020/p63_boot_b.img.gz` / `p08_vbmeta_b.img.gz` if needed.

## Test loop

**Hands-free since 2026-10-21 14:51 (j0021 + j0022):** with any j0022+ kernel running (or the phone in fastboot), `python tools/sweet-run.py IMAGE logs/OUT.txt --secs N` asks the kernel to reboot over USB Ethernet (command port 5141; every reboot lands in fastboot), `fastboot boot`s IMAGE and records the live console log (port 5140) for N seconds. Windows binds its inbox UsbNcm driver to the phone ("ios-sweet Sweet iOS (USB Ethernet)") and gives it a 169.254 address; the phone answers on 169.254.7.2 and 192.168.7.2. `tools/sweet-netlog.py` alone attaches to a running phone. With `sweetwdt=20` in the test image (j0025) even a hung boot comes back to fastboot by itself (~23 s after the hang); without it a hang still needs Power + Volume Down.

Old manual loop:

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
- Respawn loop: **fairplayd.H2 is out of service** (launchd.plist patched in place on the phone 2026-10-21 03:53 with `tools/launchd-disable-inplace.py`: blocks 76 and 87 of the file at partition 4K block 1966695, sha256 3a6e896d...; original 7b41fa30...). **bluetoothd still starts** (at boot and about every 10 s) although its only job in the cache now has no MachServices/LaunchEvents and RunAtLoad/KeepAlive false: something else brings it up; not chased further (a few % CPU). 2026-10-24: still ~20 execs per 4 min, < 2 ms/s of launchd. Its removed services set off mediaserverd's BTAudioHALPlugin loop (fixed, PERF-TASKS task 7).
- Flashing boot_b makes ABL clear its successful bit (`slot-successful:b: no` right after the flash); the next boot with `abmark=b` sets it again.
- **Memory bandwidth (j0017, 2026-10-21):** XNU, one Gold core at 1747 MHz: write 7.6 GB/s, read 6.4 GB/s, copy 3.2 GB/s (Linux initramfs reference, Gold: 4.8 / 3.5 / 3.1 GB/s). RAM is not the brake (a 9 MB frame copy is ~3 ms); the lag is CoreAnimation's software rendering. TSENS: 55-69 C at 1747 MHz while charging, no rise under the 2 s four-core load.
- Settings (Preferences, pc 0) and Photos (abort) crashed once each in the j0012 sessions; Settings opened fine on 2026-10-21 02:40.
- j0012 battery: percent from the IR-corrected (110 mOhm) averaged rest voltage; 46-50 % at 3.78-3.79 V while the gauge said 51-52 %.
- `sweetlog=WORD,...` has no effect (conflicts with 0047's integer parse of the same boot-arg).

- Under Nura's Linux, sustained eMMC reads hung the controller (CQE timeout, "cqhci: Failed to halt") and twice `reboot bootloader` from Nura hung. Linux sdhci-msm CQE on this Hynix eMMC; our XNU driver keeps CQE off.
- Shim speed probe: Gold looks 55x slower than Silver with the MMU off; under Linux Gold is about Silver's speed, so it is an MMU-off artifact, but the Gold clock is probably lowish (no CPU clock driver).
- jasmine ABL does not honor IMEM restart reasons (fixed with 0138).
