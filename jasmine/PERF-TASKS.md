# UI frame-rate tasks (ordered by gain)

State of 2026-10-23: a moving UI frame takes **49.3 ms** (about 20 fps) on 4 Gold cores at 1747 MHz, GPU at
266 MHz. Tasks 1-4 together could bring it to about 28-30 ms; an iPhone frame is 16.7 ms. Each task below is a
self-contained brief for one agent. Read "For every agent" first.

## Where a frame goes (j0057 profile, 2026-10-22 22:59, `jasmine/GPU.md` "Where a moving frame goes")

CoreAnimation's display thread in backboardd (`com.apple.coreanimation.display.primary`) builds every frame; it is
on a CPU 85-90 % of the time while the UI moves, so the frame is one CPU-bound thread.

| Part of a moving frame | ms | Share |
| --- | --- | --- |
| Mesa's own CPU work (draw validation, state, batches, allocation) | 14.6 | 30 % |
| Display copy: CPU scale of 1125x2436 to 997x2160 at each swap (`AppleCLCD::composeFit`) | 8.8 | 18 % |
| Waiting for the GPU at frame end (fence wait) | 7.5 | 15 % |
| Kernel GPU driver calls (buffer create/map/free 3.0, other 3.8) | 6.8 | 14 % |
| CoreAnimation's own code (backdrop blur the largest) | 6.1 | 12 % |
| Waits in SwapEnd and CA's run loop, other kernel time | 5.5 | 11 % |

## Task list

| # | Task | Saves (ms per frame) | Touches | Patch no. |
| --- | --- | --- | --- | --- |
| 1 | Display scale off the CPU | 8.8 | `SweetFramebuffer.cpp` (+ `SweetSurface.cpp`) | j0058 |
| 2 | Gold clock 1747 -> 2208 MHz (voltage, DVFS) | ~7.7 | `sweet_cpuclk.c`, `sweet_osm.c`, PMIC code | j0059 |
| 3 | GPU clock 266 -> ~650 MHz (RPM votes) | up to 7.5 | `bsd/dev/sweet_gpu.c`, new RPM client | j0060 |
| 4 | Reuse Mesa's batch buffers | ~5.4 | `mesa/darwin/*` (Mesa build only) | none |
| 5 | Cut Mesa's per-draw CPU cost | part of 14.6 | `mesa/` (+ a Mesa patch 0002) | none |
| 6 | Make 8 cores beat 4 (tune j0052) | 8 cores 96-128 ms vs 4 Gold 81 ms | `sched_clutch.c` / j0052 code | j0061 |
| 7 | Stop the XPC retry loops (~2 Gold cores) | small on 4 cores; needed for 8 cores and battery | userland services, maybe kernel | j0062 |
| 8 | Fix the pmap 32-bit page-number shift | ~0 (correctness) | `osfmk/arm/pmap/pmap.c` | j0063 |

Savings overlap (a faster CPU also shortens the copy), so they do not add up exactly. Tasks 4 and 5 both change
Mesa: give them to one agent, or run them one after the other. Every other pair touches different files.

## For every agent

**Project.** ios-jasmine runs iOS 16 (XNU xnu-8796, SWEET machine config from upstream topaz/sweet) on a Xiaomi Mi
A2 (SDM660: 4 Gold Cortex-A73 + 4 Silver A53, Adreno 512). The phone boots with `fastboot boot` of a shim image.
The UI is CoreAnimation's GLES renderer on the GPU through libsweetca (`mesa/darwin/sweetgl/sweetca.c`, injected
into backboardd) over Mesa freedreno. Background: `jasmine/NOTES.md` (top, "Kernel patches", "Test loop"),
`jasmine/GPU.md` (sections from "j0053" on), `jasmine/HARDWARE.md`.

**Kernel patches.** Source of truth is the WSL tree `~/xnu-8796`, branch `jasmine-merge`, one commit per patch.
Export with `git format-patch -1 --stdout > xnu/patches/j00NN-jasmine-<name>.patch`. Use only the patch number
listed for your task. Build the 4K/8-core kernel on CI:
`gh workflow run xnu.yml -R telegdyd/ios-jasmine --ref jasmine -f topaz_4k=1`. macOS runners queue 10-30 min;
a job cancelled without any step ran just lost its runner: `gh run rerun <id>`. Download:
`gh run download <id> -R telegdyd/ios-jasmine -n xnu-kernel -D xnu/out-jasmine-<tag>`.
Do not commit on `jasmine-merge` while another agent does: work in your own worktree
(`git -C ~/xnu-8796 worktree add ~/xnu-<task> -b <task> jasmine-merge`) and cherry-pick onto `jasmine-merge`
at the end.

**Mesa / libsweetca.** Sources in `mesa/darwin/`; `tools/g2/mkmesa.sh` (run in WSL) regenerates
`mesa/patches/0001-freedreno-darwin-backend.patch`. Build on CI: `gh workflow run xnu.yml -R telegdyd/ios-jasmine
--ref jasmine -f build=mesa`. Put it on the phone:
`MSYS_NO_PATHCONV=1 python tools/sweet-fs.py put <dir>/mesa-ios/libsweetca.dylib /usr/local/bin/libsweetca.dylib --mode 755`.
The new library is used from the next boot.

**Measuring (no person needed).** These rounds run without anyone touching the phone:
- `AMP=1 CPUS=4 bash tools/g2/uiround.sh <ktag> <tag> "<boot-args>"` boots `xnu/out-jasmine-<ktag>` and plays a fixed
  gesture script (`tools/g2/uibench.py`): home pages, Control Center, Notification Center, Spotlight. It prints
  the frame interval (median/best/worst), the GPU wait, flicker checks, and GPU draws into surfaces still on
  screen.
- `bash tools/g2/profround.sh <ktag> <tag> "<boot-args>"` does the same with the j0057 sampling profile; the report
  is `tools/g2/prof.py` / `profsplit.py`. Keep profile windows short: the download runs at about 20 KB/s.
- Compare against a baseline round from the same script on the same day. Rounds vary: use 2 rounds per variant.
- `osm-round.sh` already adds `sweetfb_sync=1` (the flicker fix) to every image.
- Ask the user only for a final visual check.

**One phone, several agents.** Before booting, create `phone.lock` atomically in the shared notes folder
`C:\Users\teleg\AppData\Local\Claude-Data\claude_pzs8sxrjxfjjc\side-session-notes\local_b57c5c9a-db18-434e-a448-e6d69fa0dddf`
(bash: `( set -C; echo "<you>, <time>" > phone.lock )`; `uiround.sh` and `profround.sh` do this). Delete only your
own lock. While someone else's lock exists, wait.

**Ground rules (the user's, always).**
- Never flash any partition, GPT or slot b; boot with `fastboot boot` only.
- Ask before anything destructive, or before changing the phone's iOS root. Test binaries in `/usr/local/bin` are fine.
- Never write outside the iOS window of the disk.
- No launchd jobs, no remote or self-hosted runners.
- Keep device dumps, serial numbers and Apple artifacts out of git.
- Say before a round that may hang the phone. Recovery is power + volume-down; `sweetwdt=20` resets a hung boot to fastboot.
- No `str wzr` MMIO stores (the hypervisor's emulation hangs on them). No live module reload.
- Prefer root-cause fixes. Say clock times ("at 22:40").
- Commit and push each milestone to `jasmine` (`git pull --rebase` first, commit only your own files), and add the result to `jasmine/GPU.md`.
- Code from the Linux msm-4.4 drivers and from ios-flame (MIT) may be adapted closely, with credit.
- Git Bash: set `MSYS_NO_PATHCONV=1`; write multi-line scripts to files (WSL edits through python scripts avoid quoting problems).

---

## 1. Move the display scale off the CPU (saves ~8.8 ms)

**Now.** On every swap, `AppleCLCD::swap` -> `present` -> `composeFit` (`iokit/Kernel/arm/SweetFramebuffer.cpp`)
scales CoreAnimation's 1125x2436 surface by nearest sample into a 996x2160 window at x 40 of the 1080x2160 panel.
It writes into one of two write-combined flip buffers inside the splash carve-out (0x9dd00000 / 0x9e600000) and
flips MDP pipe VIG0 to it. Since `sweetfb_sync=1` this runs on CoreAnimation's thread, so it adds straight to the
frame time.

**Options.**
- (a) **The MDP's own scaler.** VIG0 has a QSEED3 scaler (msm-4.4 `sde_hw_sspp.c` `_sde_hw_sspp_setup_scaler3`; a
  bilinear filter needs no LUT). VIG0 reads physical memory with no SMMU, so the source must be physically
  contiguous, below 4 GiB. Candidates: CoreAnimation's swap surfaces from the j0053 GPU pool (0xc0000000-0xf3ffffff,
  64 MB contiguous chunks; topaz does this with `sweet_gpu_pool_eligible` for backboardd's screen-sized surfaces),
  or topaz's scanout slots.
  **Catch:** CoreAnimation does not honour our "in use" hold (j0056 measured 1130 GPU draws into a surface still on
  screen). With direct scanout it would draw into the surface the panel is reading, which is the old flicker. So
  either find out why `IOSurfaceClientIsInUse` (state page +0x18) is ignored and fix that, or keep one copy and let
  the hardware do it.
- (b) **The GPU does the copy and scale** into the flip buffer: no CPU work and no hold problem. The kernel would
  need its own GPU job (a blit) on SweetGPU's ring, or the scale moves into libsweetca (draw the final frame at
  panel size).
- (c) **A cheaper CPU copy** (NEON, 2x2 blocks): a fallback only.

**Done when:** `composeFit` is gone from the frame thread's profile (`profround.sh`); a moving frame is ~8 ms
shorter in `uiround.sh` against a same-day baseline; there is no new flicker (GPU draws into surfaces on screen
stay 0, or are harmless with a copy); touch still lands right (`sweet_fit_x/w` in SweetHID.cpp). Get the user's
visual check at the end.

## 2. Gold clock 1747 -> 2208 MHz through core voltage control (saves ~7.7 ms; all CPU-bound work)

**Now.** Gold runs at a fixed 1747 MHz on XBL's voltage (`sweetgold=1747`, j0015 in `osfmk/arm64/sweet_cpuclk.c`).
Silver stays at XBL's 1382 MHz. OSM (Qualcomm's hardware DVFS) is dead on this boot path: TrustZone owns its
sequencer. So the plan is software DVFS: switch PLLs in software, set the voltage through the SAW / PM660 SPMI,
run a load governor with a TSENS limit, and cover both clusters (Gold on PM660 S2+S3, Silver on S1).
The work is paused at the voltage path. Read `jasmine/HANDOFF-CPUCLK.md` and NOTES.md "CPU clock (OSM + CPRh)".
The live tool `tools/cpuclk/osmctl.py` (j0045-j0048: register reads/writes, sequences, SPMI reads, `check`,
`tsens`) turns experiments into command lines instead of kernel builds. The per-chip table comes from
`tools/cpuclk/cpuclk_model.py`: perfcl speed bin 1 = 1747.2/1958.4/2150.4/2208 MHz with ceilings
868/988/988/1068 mV. The APM crossover is at 872 mV, and MEM-ACC levels must follow the corner.

**Done when:** Gold runs at 2208 MHz with a voltage set by us, not XBL's (read back); the j0015 workload check
on all cores gives 0 errors and TSENS stays under a limit you set; the governor drops the clock when idle; and
`uiround.sh` shows the gain. Say before each round that could hang the phone.

## 3. GPU clock 266 -> ~650 MHz (saves up to 7.5 ms of GPU wait)

**Now.** `bsd/dev/sweet_gpu.c` (j0020) clocks the Adreno 512 from GPU PLL0 at 160 or 266 MHz (`gpumhz=`). Higher
levels need a CX corner vote through Qualcomm's RPM, plus a memory-bus (bimc / DDR) vote for bandwidth. There is
no RPM client yet. See `jasmine/GPU.md` (search "RPM"). Sailfish patches 0144/0146/0147/0164 did this on MSM8996;
SDM660 needs its own resource IDs and levels from the stock DT: `~/jasmine-dtb/stock/dtb0.dts` (`qcom,gpu-pwrlevels`,
`qcom,system-voltage`) and the msm-4.4 kgsl / rpm-smd drivers (`~/cpuclk-src`, `~/lin660`).
The same RPM client can later raise the RAM clock.

**Done when:** the GPU runs at its top stock level, measured with the CP cycle counter as in j0020; the GPU wait
in the libsweetca `prof:` lines drops; there are no hangs over a 10-minute `uiround.sh` series.

## 4. Reuse Mesa's batch buffers (saves ~5.4 ms; Mesa build only)

**Now.** The profile shows a new set of GPU buffers for every batch (one per render target): 2.4 ms per frame in
Mesa's allocation path, plus 3.0 ms in the kernel creating, mapping (`IOConnectMapMemory`) and freeing them. Mesa
normally recycles these through its BO cache and ring pool (`fd_bo_cache`, `fd_pipe_sp_ringpool_*`). Find out why
the darwin backend (`mesa/darwin/darwin_bo.c`, `darwin_device.c`) misses that path: cache flags, `madvise`
returning "willneed", or the IOKit mapping freed in `darwin_bo_destroy`. Make freed buffers go back to the cache,
mapped, and come out of it again.

**Done when:** kernel `SweetGPU` buffer create/free calls per frame are near 0 while moving (add a counter if
needed); the profile's allocation and ioctl time drops; frames are ~5 ms shorter; no leak over a 10-minute run
(SweetGPU per-client buffer count stays flat).

## 5. Cut Mesa's per-draw CPU cost (part of 14.6 ms)

**Now.** About 70-100 draws per frame at ~0.16 ms each (`w_DrawElements` in the libsweetca profile); a normal
freedreno draw costs a few microseconds. Every render target gets its own batch (CoreAnimation's offscreen
passes, the backdrop blur), and each batch costs setup. Profile inside Mesa first (the j0057 profile has Mesa
symbols through libsweetca.dylib's symbol table), then fix the biggest items. Candidates: batch flush reasons
(add counters in a Mesa patch 0002), state emitted again on every draw, shader variant lookups, client-memory
vertex/index uploads.

**Done when:** the profile shows the cost split by cause; the biggest one is reduced; frames are measurably
shorter. Coordinate with task 4 (same files).

## 6. Make 8 cores beat 4 (j0052 tuning)

**Now.** j0052 (`xnu/patches/j0052-jasmine-clpc-standin.patch`, `sweetclpc=`) keeps UI QoS on Gold and moves
DF/UT/BG to Silver: background load on Gold fell from 10.7 s to 0.6 s per 10 s. But scripted 8-core rounds still
take 96-128 ms per frame, against 81 ms on 4 Gold cores (`jasmine/GPU.md`, the j0052 section). Find what still
costs on 8 cores: CA's frame thread or Mesa on Silver, cross-cluster IPIs, or the whole-cache flush reaching
Silver. Use j0052's per-cluster stats and the j0057 profile.

**Done when:** 8 cores are at least as fast as `cpus=4` in 2+2 scripted rounds, and the 8-core image becomes the
default.

## 7. Stop the XPC retry loops (~2 Gold cores busy all the time)

**Now.** The j0057 profile found launchd ~901 ms/s (XPC / kqueue, ~65 % in the kernel), vmd ~561 ms/s (a
CoreTelephony retry loop) and mediaserverd ~423 ms/s (an XPC connection cancelled and reconnected over and over),
even with the UI idle. The likely cause is a service these daemons talk to that never comes up on jasmine
(telephony, audio). Name the service, then give them what they wait for or stop the daemon from retrying.
Prefer a root fix over disabling things. Changing the phone's iOS root needs the user's OK first.

**Done when:** the three daemons use under 50 ms/s each at idle (j0052 stats or the profile census); nothing
that worked before breaks (SpringBoard, Settings, the apps the user uses).

## 8. Fix the pmap 32-bit page-number shift (correctness)

**Now.** `osfmk/arm/pmap/pmap.c` `pmap_sync_page_attributes_phys` does
`flush_dcache((vm_offset_t)(pp << PAGE_SHIFT), ...)` on a 32-bit `ppnum_t`, so pages above 4 GiB lose bit 32. All
of jasmine's RAM is above 4 GiB. This caused the j0029/j0030 panic `phystokv_range: illegal PA 0x7c994000`
(really 0x1_7c994000) when a write-combined IOBufferMemoryDescriptor was created. Found by ios-flame
(github.com/NWylynko/ios-flame, METAL-NEXT.md section 4). Fix with `ptoa(pp)`, look for other `<< PAGE_SHIFT` on a
`ppnum_t` in `pmap.c` / `caches.c`, and test `sweetgpu_wc=1` (write-combined IOBufferMemoryDescriptor buffers)
without the pool (`sweetgpu_pool=0`).

**Done when:** the `sweetgpu_wc=1 sweetgpu_pool=0` boot no longer panics and the UI renders; the default (pool)
path is unchanged.
