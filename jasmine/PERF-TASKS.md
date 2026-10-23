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
| 1 | ~~Display scale off the CPU~~ **done 2026-10-23** | 8.8 | `SweetFramebuffer.cpp` (+ `SweetSurface.cpp`) | j0058 |
| 2 | Gold clock 1747 -> 2208 MHz (voltage, DVFS) | ~7.7 | `sweet_cpuclk.c`, `sweet_osm.c`, PMIC code | j0059 |
| 3 | ~~GPU clock 266 -> ~650 MHz (RPM votes)~~ **works 2026-10-23, gain ~0.5 ms** (647 MHz is this chip's top); **default 588 MHz since 2026-10-23 05:45** (`mkimg.sh`; it had stayed at 266) | 0.5 measured | `bsd/dev/sweet_gpu.c`, `bsd/dev/sweet_rpm.c` | j0060 |
| 4 | Make Mesa's buffer caches hit (textures, render targets, rings) | ~17 % of CA's frame thread (j64p) | `mesa/darwin/*` (Mesa build only) | none |
| 5 | Cut Mesa's per-draw CPU cost | part of 14.6 | `mesa/` (+ a Mesa patch 0002) | none |
| 6 | Make 8 cores beat 4 (tune j0052) | 8 cores 96-128 ms vs 4 Gold 81 ms | `sched_clutch.c` / j0052 code | j0061 |
| 7 | Stop the XPC retry loops (~2 Gold cores) | CA's thread waits 45 ms/s for a CPU (~20 % on top of its 214 ms/s, j64p); needed for 8 cores and battery | userland services, maybe kernel | j0062 |
| 8 | Fix the pmap 32-bit page-number shift | ~0 (correctness) | `osfmk/arm/pmap/pmap.c` | j0063 |
| 9 | ~~DDR clock vote through the RPM~~ **done 2026-10-23: not the brake** (1296 -> 1804 MHz: no gain; below 1296 Mesa slows 20-60 %) | 0 measured | `bsd/dev/sweet_rpm.c`, `bsd/dev/sweet_ddr.c` | j0064 |
| 10 | Load-based DDR governor, ceiling 1804 MHz, on by default | 1804's CPU gains when busy (latency -14 %, copy faster), power back when idle | `bsd/dev/sweet_ddr.c` (+ `sweet_gpu.c` counters) | j0065 |
| 11 | GPU power management: hardware clock gating, idle power-down, load-based clock (DCVS) | power and heat (GPU busy only ~8-25 % while the UI moves, j64a) | `bsd/dev/sweet_gpu.c` | j0066 |
| 12 | CPU idle power: core / cluster power collapse instead of WFI, unused cores off | power and heat at idle | `osfmk/arm64` idle path, new `sweet_idle.c` | j0067 |
| 13 | Thermal limits: TSENS-driven caps on CPU and GPU clocks | keeps the phone usable under long load | new `sweet_thermal.c` (after 2 and 11) | j0068 |

Savings overlap (a faster CPU also shortens the copy), so they do not add up exactly. Tasks 4 and 5 both change
Mesa: give them to one agent, or run them one after the other. Tasks 10 and 11 both touch `sweet_gpu.c` (10 only
reads the bus counters j0064 added): run them one after the other or coordinate. Task 13 needs the clock levels of
tasks 2 and 11. Every other pair touches different files.

**Power and heat (state 2026-10-23, user: "the phone is hot"; tasks 7 and 10-13).** Nothing scales today: Gold is
fixed at 1747 MHz on XBL's voltage and Silver at XBL's 1382 MHz (no DVFS, no thermal throttling,
`HANDOFF-CPUCLK.md`); CPU idle is XNU's WFI only, no PSCI CPU_SUSPEND or cluster power collapse; the GPU is fixed at
266 MHz, never powered down after bring-up (`gpu_power_off` only on failures) and runs without hardware clock gating
(`sweet_gpu.c`: "a5xx_hw_init without clock gating"); the DDR is fixed at 1296 MHz. On top, task 7's daemon loops
keep ~1.9 of the 4 Gold cores at 100 % all the time, probably the largest heat source by itself: do task 7 early.
These tasks need a power reading: the PM660 fuel gauge's battery current (j0010 reads the FG; add the current if it
is missing; on battery, unplugged, with the user's OK) or a USB power meter reading from the user; TSENS (readable
through the command port, osmctl `tsens`) as the temperature side. Record idle and moving power before and after.

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

## 1. Move the display scale off the CPU (saves ~8.8 ms) -- DONE

**Done 2026-10-23 01:55 (j0058, option a).** VIG0's QSEED3 scaler fits the frame; backboardd's frames come from the
GPU pool and are scanned in place (present 7-40 us, `composeFit` only for multi-layer frames). The "Catch" below
was a wrong SwapWait: CoreAnimation reuses a swap surface when `IOMobileFramebufferSwapWait` says done, not on
IOSurface in-use; ours said done at once. Now a swap is done once a later one ended and the GPU waits for the latch
before drawing into a frame still on the panel. Round j58d: 48 held draws (1662 without), the user saw no flicker
and smooth motion. Not done: a same-day baseline and a profile round (the user judged it by eye). Details:
GPU.md "j0058".

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

## 3. GPU clock 266 -> ~650 MHz (saves up to 7.5 ms of GPU wait) -- WORKS, SMALL GAIN

**Result 2026-10-23 (j0060, GPU.md "j0060").** RPM GLINK client (from ios-sailfish) + CX level votes + mem-acc +
cx_ipeak; `gpumhz=` any stock level, `gpu clk MHZ` live. This phone's speed bin 0x87 tops out at **647 MHz**
(measured 647). The GPU wait per flush fell only 3.5 -> 2.9 ms from 266 to 588 MHz, frames did not get visibly
shorter: the GPU's work is bound by memory or fixed costs, the frame by the CPU (task 7's daemons take ~1.9 of 4
cores). Images still boot `gpumhz=266`. Open: one of two 647 MHz boots (j60b) had backboardd stop after 35 GPU
jobs; j60c did not repeat it. Not done: a clean 10-minute 647 series, the user's visual check.

**Now.** `bsd/dev/sweet_gpu.c` (j0020) clocks the Adreno 512 from GPU PLL0 at 160 or 266 MHz (`gpumhz=`). Higher
levels need a CX corner vote through Qualcomm's RPM, plus a memory-bus (bimc / DDR) vote for bandwidth. There is
no RPM client yet. See `jasmine/GPU.md` (search "RPM"). Sailfish patches 0144/0146/0147/0164 did this on MSM8996;
SDM660 needs its own resource IDs and levels from the stock DT: `~/jasmine-dtb/stock/dtb0.dts` (`qcom,gpu-pwrlevels`,
`qcom,system-voltage`) and the msm-4.4 kgsl / rpm-smd drivers (`~/cpuclk-src`, `~/lin660`).
The same RPM client can later raise the RAM clock.

**Done when:** the GPU runs at its top stock level, measured with the CP cycle counter as in j0020; the GPU wait
in the libsweetca `prof:` lines drops; there are no hangs over a 10-minute `uiround.sh` series.

## 4. Make Mesa's buffer caches hit (~17 % of CA's frame thread; Mesa build only)

**Measured 2026-10-23 05:12 (profile j64p, `logs/prof-j64p-report.txt`, CA's display thread, 2137 on-CPU samples).**
The cost is the buffer *cache misses*, not a missing cache. Share of the thread's CPU time:
- `darwin_bo_new` **11.6 %** (a cache miss, then SweetGPU's create: `SweetGPUBuffer::create` 6.2 % self, the GPU
  page tables `pt_l3` and cache flushes in `sweet_gpu_vm_map`, an `IOMemoryDescriptor`, `vm_map_enter`);
- `fd_bo_map` -> `darwin_bo_map` **3.6 %** (`IOConnectMapMemory64` for every new buffer);
- frees **2.5 %** (`darwin_bo_close_handle` 2.0, `darwin_bo_destroy` 0.6).

Where the new buffers come from (callers of `bo_new`):
- **6.7 %** `fd_resource_create_with_modifiers` -> `realloc_bo`: textures and render targets created again and again,
  mostly CA's offscreen surfaces for the backdrop blur (`CA::OGL::ImagingNode::retain_surface` 18.8 % inclusive);
- **5.3 %** `fd_bo_new_ring` (the ring cache) from `fd_submit_sp_new_ringbuffer`, via `fd_batch_create` 3.4 and
  `subpass_create` 1.9: the per-batch command rings (non-streaming, `SUBALLOC_SIZE` 32 KiB).

The caches are initialized and consulted (`fd_bo_cache_alloc` is reached, 0.3 %), but they miss. The freed buffers
are *expired*: almost every free goes `fd_bo_del` -> `fd_bo_cache_free` -> `fd_bo_cache_cleanup` ->
`fd_bo_del_list_nocache` -> `close_handle`, i.e. buffers sit in the cache for over a second unused while new ones
are created. Both caches (bo_cache and ring_cache) fail the same way, so look first at what they share,
`find_in_bucket()` in `src/freedreno/drm/freedreno_bo_cache.c`:
1. **`fd_bo_state(entry) != FD_BO_STATE_IDLE`** -> it stops at the first busy entry. A buffer counts as idle only once
   `pipe->control->fence` (written by the GPU's `CACHE_FLUSH_TS` from `fd_pipe_emit_fence`) has passed the buffer's
   `ufence` (`cleanup_fences()` in `freedreno_bo.c`). **First check: does `pipe->control->fence` advance at all
   on Darwin?** The control buffer comes from SweetGPU like any other (`fd_bo_new(... _FD_BO_NOSYNC ...)` in
   `freedreno_pipe.c`); if the GPU's write never lands there, or the CPU reads a stale copy, every fenced buffer is
   busy forever, which matches this profile exactly (and it would also send every `fd_pipe_wait` to the kernel
   instead of returning early, `freedreno_pipe.c` line ~178). Log `pipe->control->fence` against
   `pipe->last_fence` in libsweetca's `prof:` line.
2. `entry->alloc_flags == flags`: a flags mismatch also skips an idle entry.
3. Only if those are fine: why CA's offscreen render targets are destroyed and created again at all (sweetgl /
   EAGL side, `mesa/darwin/sweetgl/`).

Set `FD_BO_CACHE_STATS 1` (top of `freedreno_bo_cache.c`) in the same Mesa build: it logs hits, misses and expired per
bucket every 32 frees and settles 1 and 2 in one round. Put both diagnostics into **one** Mesa build, then the fix
into the next.

Tips:
- Symbols: `tools/g2/prof.py report` needs the libsweetca.dylib that is on the phone; j64p used
  `xnu/out-mesa-kick` (the newest build, plausible but not checked). Fetch the phone's copy first:
  `MSYS_NO_PATHCONV=1 python tools/sweet-fs.py get /usr/local/bin/libsweetca.dylib <local file>`.
- Measure with Mesa's CPU time per flush (`tools/g2/ddrcost.py LOG` on a uiround log: GL - wait from libsweetca's
  `prof:` lines). The 100-flush "ms each" figure mostly measures the idle gaps of the gesture script and is too noisy.
  j64a baseline at DDR 1296: 18.6-20.0 ms Mesa CPU per flush.
- `tools/g2/profsplit.py` finds no frames since j0058 (it counts runs inside `AppleCLCD::present`).

**Done when:** SweetGPU buffer creates and frees per frame are near 0 while the UI moves (add a counter if needed);
the profile's `darwin_bo_new` / `darwin_bo_map` / `close_handle` share drops from ~17 % to a few %; Mesa's CPU time
per flush drops against a same-day baseline; no leak over a 10-minute run (SweetGPU per-client buffer count flat).

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

**Measured again 2026-10-23 05:12 (profile j64p, `logs/prof-j64p-report.txt`, 4 Gold, UI moving):** launchd 901 ms/s
(two threads ~440 each), vmd 531, mediaserverd 435 (one thread 433), logd 130: **1.87 of the 4 Gold cores**.
CoreAnimation's display thread was on a CPU 214 ms/s and **runnable, waiting for a CPU, 45 ms/s**, so on 4 cores
these loops cost the frame directly, about as much as task 4's buffer churn. The loops have not changed since
j0057 (2026-10-22), so they are steady, not boot-time.

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

## 9. DDR clock vote through the RPM (find out first whether memory is the brake) -- DONE, NOT THE BRAKE

**Result 2026-10-23 05:10 (j0064, GPU.md "j0064").** The vote works (RPM clock handoff of 19 resources + scaling on at
the first try; read back 766 / 1016 / 1294 / 1804 for votes 768 / 1017 / 1296 / 1804: the debug-mux counter is half
the DDR rate, the bootloader leaves 1296). Round j64a, one boot, 7 plays: Mesa's CPU time per flush 31.1 ms at 768,
24.2 at 1017, 18.6-20.0 at 1296, 18.9-19.5 at 1804; GPU wait per flush flat. Memory is not the brake at the
bootloader's rate; 1804 stays off until task 10's governor (`sweetddr=1804` or `ddr 1804` live). Fresh profile j64p: the daemon loops (task 7,
1.87 of 4 Gold cores; CA's thread waits 45 ms/s for a CPU) and buffer churn (task 4, ~15-20 % of CA's thread) come
next. New tools: `ddr state/MHZ/bench/bw`, raw `rpm`, CPU bwmon (1 MiB units) and GPU VBIF counters,
`tools/g2/ddrround.sh`, `ddrsum.py`, `ddrcost.py` (per-flush GL cost, the steadier measure). Not done: a 10-minute
series at 1804 (~8 min over two plays without a hang).


**Now.** Nothing in XNU votes for the DDR (bimc) clock, so it stays where the bootloader left it. j0060's `gpu state`
reads `bimc_clk` through the GCC debug mux (sel 0x19d) as **647 MHz** every boot. sailfish's MSM8996 doubles that
counter, and the CPU already reads 6.4 GB/s, so the real rate is probably ~1294 MHz; the stock bus tables
(`qcom,gpubw` OPPs, `opp-1804`) go to 1804. Confirm the counter's factor first (a second clock, or the DDR PLL).
Hints that memory matters: 2.2x the GPU clock cut the GPU wait by only ~15 % (j60a).

**How.** The RPM client is there (`bsd/dev/sweet_rpm.c`). A rate vote is `clk2` id 0, key `KHz ` (sailfish 0146),
but the RPM ignores rate votes until clock scaling is on (`clk0` id 2, `Enab` 1, sailfish 0147), and once it is on
the RPM follows the AP's votes for **every** RPM clock: first vote each one at a safe rate in both sets (sailfish's
handoff list is MSM8996's; take SDM660's from msm-4.4 `clk-smd-rpm` / `clock-rpm` for sdm660 and the stock DT),
or the buses drop and the phone hangs. Add `sweetddr=MHZ` and a live `ddr MHZ` on the command port, like `gpu clk`.

**Test (one build, one round, as clkround.sh):** step DDR down and up in one boot (e.g. 1017, now, 1555, 1804) with
uibench at each; if frame time and GPU wait follow the DDR rate, memory is the brake; if flat, it is not, and a fresh
j0057 profile decides the next task. Say before the round: the scaling handoff can hang the phone (`sweetwdt=20`).

**Done when:** the measured DDR rate follows the vote (read back); no hang over a 10-minute uibench series at the top
rate; the frame / GPU-wait answer above is written into GPU.md.

## 10. Load-based DDR governor, ceiling 1804 MHz, on by default

**Why.** The user wants every optimization on. 1804 MHz gives the CPU 14 % lower memory latency (320 -> 275 ns),
faster writes and copies, and halves the GPU's RAM-starved time (task 9, round j64a). The UI frame did not measurably
gain, but other work (app launch, decompression, anything memory-heavy) may. Fixed 1804 holds the DDR and, after
j0064's handoff, every RPM bus at maximum even when idle. Stock Android scales instead, and so should we: full rate
while busy, lower while idle.

**Now (j0064, `bsd/dev/sweet_ddr.c`, GPU.md "j0064").** The DDR rate is fixed: the bootloader's 1296 MHz, or whatever
the last `ddr MHZ` / `sweetddr=` vote set. The RPM does not watch load itself; it applies the highest vote of its
masters. On stock the HLOS decides: msm-4.4 devfreq governors `bw_hwmon` (`drivers/devfreq/governor_bw_hwmon.c`, the
CPU bwmon, DT `qcom,cpu-cpu-ddr-bw`), `bw_vbif` (`governor_bw_vbif.c`, the GPU's VBIF counters, DT `qcom,gpubw`),
and `cpu0-cpu-ddr-latfloor` (a DDR floor from the CPU clock), aggregated by msm_bus into one bimc vote. XNU has none
of this. What j0064 already provides: the RPM clock handoff + scaling (`sweet_rpm_clk_scaling`), the bimc vote
(`sweet_rpm_clk`, ~23 ms per switch), the CPU bwmon4 reader (MON2 bytes, **1 MiB units**, 54.6 ms hardware window),
GPU busy / VBIF beats / RAM-starved counters (`sweet_gpu_bus_counters`), and the stock rate table (DT
`generic-bw-opp-table`: 547, 681, 768, 1017, 1296, 1353, 1555, 1804 MHz; lower ones exist).

**How.** A kernel thread in `sweet_ddr.c`, sampling every ~50 ms, adapted closely from `governor_bw_hwmon.c` (msm-4.4
GPL code may be adapted with credit): up fast, down slow with hysteresis; the GPU's busy and RAM-starved rates as a
second input (as `bw_vbif`); a jump to 1804 on touch or when CA's frames start (SweetHID / the framebuffer swap can
poke the governor), so motion never waits for a sample. Limits:
- **Ceiling 1804.**
- **Floor 1296 while the display is on**: below it Mesa's frame work grows 20-60 % (j64a), and a 23 ms switch on
  every gesture would show as stutter. Lower rates only with the display off.
- On any failed RPM vote: fall back to a fixed 1804 vote and log it; never leave scaling on without a bimc vote.

On by default on jasmine, from GPU bring-up (as `sweetddr=` is now). `sweetddrgov=0` turns it off (then `sweetddr=`
or the bootloader's rate). Command port `ddr gov`: current rate, time per rate, switches, last inputs. Live tuning of
the thresholds through `ddr gov KEY VALUE` keeps the build-test loops down.

**Test (one build, one or two rounds).**
- UI: uibench plays with the governor against fixed 1804 in the same boot (`ddr gov off` / `on` live); Mesa's CPU time
  per flush (`tools/g2/ddrcost.py`) equal within noise (j64a: 18.9-19.5 ms at 1804).
- Idle: the rate drops to the floor within seconds and stays there; time-per-rate in `ddr gov`.
- Power: battery current from the PM660 fuel gauge (j0010, `/sweet-pmic fg`), idle with the governor against fixed
  1804, on battery (unplugged) if the user agrees; this is the number that justifies the governor.
- No hang over a 10-minute uibench series. Say before the round: the boot-time handoff and frequent RPM switches can
  hang the phone (`sweetwdt=20`).

**Done when:** on by default; UI per-flush cost equal to fixed 1804; idle rate at the floor; the idle current saving
measured; 10 minutes without a hang; result in GPU.md.

## 11. GPU power management: hardware clock gating, idle power-down, load-based clock

**Now.** `bsd/dev/sweet_gpu.c` powers the Adreno 512 up once at boot (GFX head switch, GDSCs, clocks, j0018-j0020) and
never down again except on a failure. `a5xx_hw_init` runs **without hardware clock gating** (HWCG), so every GPU
block keeps its clock running whether it works or not. The core clock is fixed (`gpumhz=`, 266 MHz by default; j0060
added every stock level up to this chip's 647 MHz and the live `gpu clk MHZ`). While the UI moves the GPU is busy
only ~8-25 % of the time (j64a/j0064 bus counters: busy 15-64 Mcyc/s of 266), and idle the rest.

**How** (msm-4.4 kgsl, GPL code may be adapted closely with credit):
1. **HWCG**: `adreno_a5xx.c` `a5xx_hwcg_set()` with the A512 register table (`a512_hwcg_regs`, line ~1140) and
   `RBBM_CLOCK_CNTL` as `a5xx_start` sets it. Cheapest, no policy, likely the biggest idle win.
2. **Idle power-down**: kgsl's idle timer (`kgsl_pwrctrl.c`, `idle_timeout`, ~80 ms by default): when no job is
   pending, drop to NAP (core clock off) and later SLUMBER (clocks off, GX GDSC off, CX vote down); wake on the next
   submit (SweetGPU's submit path). Save and restore what a power-down loses (the CP state, SMMU programming, ring
   pointers: check what `gpu_power_on` sets up and what j0026's VM needs).
3. **DCVS**: a load governor over the j0060 levels (160-647 MHz) from the busy counter (j0064's
   `sweet_gpu_bus_counters`), as kgsl's `msm-adreno-tz` does: up fast on busy, down after a few idle samples. The
   GPU clock barely changes the frame (task 3: 2.2x clock = -15 % GPU wait), so lean low. Note j60b: one 647 MHz boot
   had backboardd stop after 35 GPU jobs (not reproduced); watch for it.

**Test (as few builds as possible: put 1-3 behind boot-args in one build).** Same uibench rounds with each part
on/off; Mesa CPU time per flush (`tools/g2/ddrcost.py`) and the GPU wait must not get worse; held draws / flicker
unchanged; idle power (task list note) and TSENS lower; no GPU fault or hang over 10 minutes.

**Done when:** HWCG on, idle power-down on, DCVS on, all by default; UI cost unchanged within noise; idle and moving
power measured lower than today; 10 minutes without a GPU fault.

## 12. CPU idle power: power collapse instead of WFI, unused cores off

**Now.** XNU's idle on these cores is WFI (`machine_idle` -> `Idle_context`); nothing calls PSCI CPU_SUSPEND, so cores
and clusters never power-collapse, and the L2 and the cluster rails stay up. With `cpus=4` the Silver cores' state
is unknown (`HANDOFF-CPUCLK.md` section 4 lists it as a check: spinning, WFE or PSCI CPU_OFF after the shim hands
over to Gold). Gold runs at a fixed 1747 MHz on XBL's voltage (task 2 adds DVFS and a governor).

**How.** PSCI CPU_SUSPEND with the stock idle states (stock DT `qcom,lpm-levels`, `~/jasmine-dtb/stock/dtb0.dts` line ~7419:
core retention, core power collapse, cluster power collapse; msm-4.4 `drivers/cpuidle/lpm-levels.c` and
`arch/arm64/kernel/psci.c` for the state IDs), chosen by the expected idle time from XNU's timer deadlines. XNU
already has the hooks Apple uses for deep idle (`cpu_idle` / `ml_arm_sleep`, `CPU_SUSPEND`-like state save in
`osfmk/arm64/start.S` / `caches_asm.s`): reuse them instead of a new path. Silver: PSCI CPU_OFF for every core XNU
does not use (`cpus=4`). Check the timers survive power collapse (the generic timer keeps counting; the per-CPU
timer interrupt may need the broadcast timer or a wake from the GIC).

**Test.** One build with the deepest state behind a boot-arg; idle on the lock screen and uibench rounds; no lost
timers (clock and animations run on time), no hang over 10 minutes, idle power lower.

**Done when:** core and cluster power collapse used at idle by default; unused cores off; idle power measured lower;
UI unchanged; 10 minutes without a hang.

## 13. Thermal limits: TSENS-driven caps on CPU and GPU clocks

**Now.** No thermal management: TSENS is readable (osmctl `tsens`, j0045), nothing acts on it. With fixed clocks a
long load (or task 7's loops while charging) just heats up.

**How.** A kernel thread reading the TSENS sensors (CPU clusters, GPU, the stock DT `thermal-zones` sensor map)
every ~250 ms and capping the CPU governor's top level (task 2) and the GPU's (task 11) step-wise above a limit, as
the stock `thermal-engine` / msm-4.4 `msm_thermal` limits do (use the stock trip points from the DT); LMh (hardware
limits, `HANDOFF-CPUCLK.md` phase 5) as the hardware backstop. `sweetthermal=0` off; command port `thermal` shows
temperatures and active caps.

**Test.** A long all-core load plus uibench: the caps engage before the stock limits, clocks recover when it cools,
UI stays usable.

**Done when:** on by default; caps engage and release as above; documented limits.
