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
| 3 | ~~GPU clock 266 -> ~650 MHz (RPM votes)~~ **works 2026-10-23, gain ~0.5 ms** (647 MHz is this chip's top); **default still 266**: booting at 588/647 freezes backboardd at startup in 2 of 4 boots, task 14 | 0.5 measured | `bsd/dev/sweet_gpu.c`, `bsd/dev/sweet_rpm.c` | j0060 |
| 4 | ~~Make Mesa's buffer caches hit~~ **done 2026-10-23 07:40** (sub-allocation heaps; on the phone) | buffer path 17.8 -> ~6 % of CA's thread, Mesa CPU -3 ms/frame; frames not faster at 266 MHz (GPU-wait tail) | `mesa/darwin/*` (Mesa build only) | none |
| 5 | Cut Mesa's per-draw CPU cost | part of 14.6 | `mesa/` (+ a Mesa patch 0002) | none |
| 6 | Make 8 cores beat 4 (tune j0052) | 8 cores 96-128 ms vs 4 Gold 81 ms | `sched_clutch.c` / j0052 code | j0061 |
| 7 | ~~Stop the XPC retry loops (~2 Gold cores)~~ **done 2026-10-24 01:12** (BTAudioHALPlugin disabled, vmd job removed; on the phone's root) | idle daemons 2.16 cores -> ~0.003, TSENS ~8 C lower; moving-frame gain not yet measured | phone iOS root, `tools/sweet-root-tweaks.py` | none |
| 8 | Fix the pmap 32-bit page-number shift | ~0 (correctness) | `osfmk/arm/pmap/pmap.c` | j0063 |
| 9 | ~~DDR clock vote through the RPM~~ **done 2026-10-23: not the brake** (1296 -> 1804 MHz: no gain; below 1296 Mesa slows 20-60 %) | 0 measured | `bsd/dev/sweet_rpm.c`, `bsd/dev/sweet_ddr.c` | j0064 |
| 10 | Load-based DDR governor, ceiling 1804 MHz, on by default | 1804's CPU gains when busy (latency -14 %, copy faster), power back when idle | `bsd/dev/sweet_ddr.c` (+ `sweet_gpu.c` counters) | j0065 |
| 11 | GPU power management: hardware clock gating, idle power-down, load-based clock (DCVS) | power and heat (GPU busy only ~8-25 % while the UI moves, j64a) | `bsd/dev/sweet_gpu.c` | j0066 |
| 12 | CPU idle power: core / cluster power collapse instead of WFI, unused cores off | power and heat at idle | `osfmk/arm64` idle path, new `sweet_idle.c` | j0067 |
| 13 | Thermal limits: TSENS-driven caps on CPU and GPU clocks | keeps the phone usable under long load | new `sweet_thermal.c` (after 2 and 11) | j0068 |
| 14 | **Fix the startup freeze above 266 MHz GPU** (588 default again since 2026-10-24 00:42). **Boot-logo freeze fixed 2026-10-24 02:45** (lsd seed waited 5 s per built-in app for a Wi-Fi MAC; MACs now in the ADT `/chosen`; 12/12 clean boots). Open: lock-screen freeze (backboardd stuck in SweetGPU buffer free, j60b/t4d2) | unblocks task 3's clock (and task 11's DCVS) | `bsd/dev/sweet_gpu.c`, `iokit/Kernel/arm/SweetGPU.cpp` | j0069 |
| 15 | Make lsd keep its LaunchServices store across boots (it rebuilds its database at every boot; task 14) | boot time, and no seed window at startup | phone iOS root (ownership / protection of lsd's directories), maybe a kernel trace | none (j0070 if a trace is needed) |
| 16 | Pipeline rendering and presentation using surface completion fences | unmeasured; overlap CPU preparation with the previous frame's GPU tail | libsweetca, `SweetFramebuffer.cpp`, possibly SweetGPU submission | reserve kernel number when implementation is scoped |

Savings overlap (a faster CPU also shortens the copy), so they do not add up exactly. Tasks 4 and 5 both change
Mesa: give them to one agent, or run them one after the other. Tasks 10 and 11 both touch `sweet_gpu.c` (10 only
reads the bus counters j0064 added): run them one after the other or coordinate. Task 13 needs the clock levels of
tasks 2 and 11. Every other pair touches different files.

**Power and heat (state 2026-10-23, user: "the phone is hot"; tasks 7 and 10-13).** Nothing scales today: Gold is
fixed at 1747 MHz on XBL's voltage and Silver at XBL's 1382 MHz (no DVFS, no thermal throttling,
`HANDOFF-CPUCLK.md`); CPU idle is XNU's WFI only, no PSCI CPU_SUSPEND or cluster power collapse; the GPU is fixed at
266 MHz, never powered down after bring-up (`gpu_power_off` only on failures) and runs without hardware clock gating
(`sweet_gpu.c`: "a5xx_hw_init without clock gating"); the DDR is fixed at 1296 MHz. On top, task 7's daemon loops
kept ~1.9 of the 4 Gold cores at 100 % all the time (fixed 2026-10-24: idle TSENS ~8 C lower).
These tasks need a power reading: the PM660 fuel gauge's battery current (j0010 reads the FG; add the current if it
is missing; on battery, unplugged, with the user's OK) or a USB power meter reading from the user; TSENS (readable
through the command port, osmctl `tsens`) as the temperature side. Record idle and moving power before and after.

## For every agent

**Done means on the phone (the user's rule, 2026-10-23).** These tasks configure the phone to run as well as it can;
they are not experiments. A task is done only when its result is **on by default and the phone runs it after a plain
reboot**:
1. the setting is the default: in the kernel, or in `tools/g2/mkimg.sh`'s boot-args (every image built from then on
   gets it); userland pieces (libsweetca, tools) installed in the phone's root;
2. the slot b image is rebuilt from the current kernel with those defaults:
   `wsl env GPUDBG=0 VARIANT=slotb AMP=1 CPUS=4 EXTRA_ARGS="gpudelay=1 gpupause=0 sweetfb_sync=1 sweetenv=backboardd:DYLD_INSERT_LIBRARIES=/usr/local/bin/libsweetca.dylib sweetcmd=1 abmark=b" bash tools/g2/mkimg.sh <ktag>`
   from the repo root in Git Bash (writes `shim/out/shim-boot-<ktag>-slotb.img`);
3. flashed with `bash tools/g2/flash-slotb.sh shim/out/shim-boot-<ktag>-slotb.img logs/netlog-<ktag>-slotb.txt` (it
   waits for and takes the phone lock, runs `fastboot flash boot_b`, refuses images without `abmark=b`), booted once with
   `fastboot reboot`, and the first boot checked from the live log (`python tools/sweet-netlog.py <log>`): the setting
   is active, the UI comes up, no panic;
4. NOTES.md "Slot b = iOS" updated with the image, kernel run and what it contains.

A real gain that stays off by default is not done. If a setting has a real cost (heat, power, a risk), say so and let
the user decide; never leave it off silently, and never call a task done while the phone still runs the old setting.

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
- Flash only `boot_b`, and only with a slot b image built as in "Done means on the phone" (the user's standing OK since
  2026-10-23). Never any other partition, the GPT or slot a. Test kernels: `fastboot boot` only.
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

## 4. Make Mesa's buffer caches hit (~17 % of CA's frame thread; Mesa build only) -- DONE

**Done 2026-10-23 07:40 (GPU.md "Mesa buffer caches").** The control fence is exact (ctrl == last_fence), so the
caches' idle checks work; the churn was the ring cache running dry (~145 rings a frame, 2.6 SweetGPU creates a
frame). Fix: freedreno's sub-allocation heaps on Darwin (`use_heap`, as on a6xx+), the bo cache matches ignoring
hint bits, and a darwin IB-address bug the heaps exposed (047332e). Creates 2.6 -> 0.1-0.35 per frame; profile
share of buffer create/map/free 17.8 -> ~6 %; Mesa CPU per frame 25.9 -> 22-23 ms against the same-day baseline
(17-20 ms in 12-minute runs); SweetGPU handles flat over 12 min. Installed in `/usr/local/bin` and checked on a
plain slot b boot (`logs/netlog-t4slotb.txt`). At 266 MHz the saving reappears as GPU wait at the frame's
`glFinish`, so frames are not visibly faster: the next lever is overlapping that tail with the next frame's CPU
work (libsweetca: no per-frame `glFinish`). Left: CA's large blur surfaces still miss (`realloc_bo` 4.5 %, new
sizes as layers animate). libsweetca's `prof:` lines keep the cache counters (`tools/g2/cachesum.py LOG`).
Note for every round script: a command-port reboot can hang in shutdown (05:52 and 07:11 today); power +
volume-down recovers it.


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

**Re-profiled 2026-10-24 03:14-03:22, no changes to installed software or clocks:**
[Current baseline](PERF-BASELINE-20261024.md). At GPU 588 MHz with task 4/7 fixes, CA's
display thread is on CPU ~75% during home swipes and 82-85% in Control Center; Mesa/wrapper
user code plus its support calls are ~63-66% of that CPU time. Lower-rate profiles agree.
The task remains a strong lead. `w_DrawElements` includes 52-57% of the thread's CPU,
`draw_prep` 10-13%, batch creation ~7% (inclusive, overlapping shares). GPU average busy
34-46%, with a secondary RAM-stall signal. This is not a new ms/frame or FPS estimate:
flushes are not frames, and the old sampled-present frame detector no longer works.

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

## 7. Stop the XPC retry loops (~2 Gold cores busy all the time) -- DONE

**Done 2026-10-24 01:12 (GPU.md "Task 7").** The loops were clients of daemons we had removed: mediaserverd's
`BTAudioHALPlugin` reconnecting to bluetoothd's `com.apple.BTAudioHALPlugin.xpc` (bluetoothd's MachServices emptied
2026-10-21), vmd retrying CoreTelephony without CommCenter (no baseband); launchd and logd only served their
lookups and error logs. Fix on the phone's root: `BTAudioHALPlugin.driver` moved to `HAL.disabled/`, the vmd job
removed from the launchd cache; `tools/sweet-root-tweaks.py` does both for new roots. Idle census: launchd 966 ->
1.7 ms/s, vmd 644 -> gone, mediaserverd 412 -> 1.3, logd 139 -> 0.3 (2.16 cores -> ~0.003); still so at 02:55 after
the task 14 fix (launchd 16.7, mostly nanotimekitcompaniond launches). Not done: an after-figure for CA's runnable
wait while moving (the t7c round hit task 14's boot-logo freeze), the user's check of Settings and sounds.

**Before.** The j0057 profile found launchd ~901 ms/s (XPC / kqueue, ~65 % in the kernel), vmd ~561 ms/s (a
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

## 14. Fix the startup freeze above 266 MHz GPU, then default to 588 MHz

**Symptom.** Booting with the GPU above 266 MHz, backboardd's UI sometimes stops right after startup: the kernel's
10-second line shows only "backboardd: 4-5 submits in ~29000 ms" and then nothing more; the screen shows the status
bar only. `gpu state` says the GPU is idle with every job completed (36 of 36). Seen in **j60b** (647 MHz,
`logs/netlog-j60b-clk.txt`, "backboardd stopped after 35 GPU jobs") and **t4d2** (588 MHz, `logs/netlog-t4d2-ui.txt`);
not in j60c (647) or t4b1 (588), which ran normally. **Never in 54 logged boots at 266 MHz.** Switching to 588 live
*after* startup ran clean (j60a, `gpu clk 588`). The same library as t4d2 at 266 MHz ran clean (t4d3, full gesture
script), so the freeze follows the clock, not the library. The clock changes timing, and a race at startup fires.

**What was seen in t4d2 (from the task 4 session).** CoreAnimation's display thread stuck in the kernel for minutes
in a SweetGPU buffer free: Mesa `darwin_bo_close_handle` -> `IOConnectCallScalarMethod` selector 2 -> the user client
takes `fLock` (`iokit/Kernel/arm/SweetGPU.cpp`), then `sweet_gpu_vm_unmap` takes `gpu_lock` and runs
`smmu_tlb_sync` (`bsd/dev/sweet_gpu.c`). `smmu_tlb_sync` polls with a timeout, so a thread blocked for minutes is
most likely waiting for a lock: look for a lock-order inversion between `fLock` and `gpu_lock` across the free,
submit (`sweet_fb_gpu_write_wait`, up to 50 ms waiting for the panel latch), wait (`sweet_gpu_wait`) and retire
(`retireJobs`) paths, and the threads that use them at startup at once: CA's display thread, Mesa's shader compile
threads (`ir3q0`/`ir3q1` allocate buffers in `upload_shader_variant`) and backboardd's render-server thread.

**Code diagnosis (2026-10-23 17:50-18:16, no phone; four read-only Codex passes + checks).** Result: the freeze is
*located* exactly, but it is **not a lock-order inversion**, and code reading alone does not show what the kernel waits on.
- **Where (proven from the binaries).** The frozen boots' SMP samples, symbolized against the libsweetca on the phone
  (j60b `xnu/out-mesa-kick`, base 0x101fcc000; t4d2 `xnu/out-mesa-t4diag`, base 0x101eb0000; unique BL/BLR fit over
  16 return addresses each), show CA's display thread in `mach_msg2_trap` <- `IOConnectCallScalarMethod` (`mov w1, #2`
  just before the call: **SweetGPU selector 2, buffer free**) <- `darwin_bo_close_handle` <- `fd_bo_fini_common` (holds
  Mesa's global `table_lock`) <- `fd_bo_del_list_nocache` <- `fd_bo_cache_cleanup` (expiry of cached buffers > 1 s
  old) <- `fd_bo_cache_free` <- `fd_bo_del` <- `fd_ringbuffer_sp_destroy` <- `cleanup_submit` <- `fd_batch_flush` <-
  `fd_draw_vbo`. Same PC, LR, SP and backtrace in all 7 j60b samples (~12 min) and both t4d2 samples. The sampler
  reads the saved user state (`sweet_sample_task`), which changes on every interrupt while a thread runs in user
  space, so the thread sat **inside one selector-2 call in the kernel** the whole time. It is not looping in Mesa: a
  cyclic free list would spin in `bo_finalize`'s loop in user space first. With `table_lock` held, every other Mesa
  thread that touches buffers stops too: no submits, GPU idle, all jobs done. A single close_handle sample is normal
  (t4d3 has one and moves on).
- **No other backboardd thread is in the kernel** in those samples: run loops in `mach_msg`, ir3q/traceq workers in
  `cnd_wait`, workqueue threads parked, one `__ulock_wait` that clean boots show too. So no visible thread can own
  a lock the free waits for.
- **Ruled out by reading** (`research/t14/` holds the source snapshot used, gitignored):
  - Kernel lock graph (SweetGPU.cpp, sweet_gpu.c, SweetSurface.cpp, SweetFramebuffer.cpp): edges only
    fLock -> gpu_lock / pool / sweet_surface_lock, client lock -> surface lock / pool, framebuffer -> surface /
    pool, gpu_lock -> rpm. No reverse edge, so **no cycle**.
  - No lock region exits early with its lock held. `SweetSurface::free` never calls back into SweetGPU or the
    framebuffer.
  - Every wait in the free path is bounded: `smmu_tlb_sync` 1 ms, `poll32`, `gpu_va_release` and `pt_l3` loops.
  - The boot clock path (`gpu_set_clock`, RPM vote) runs in `sweet_gpu_thread` without gpu_lock and finishes before
    SweetGPU is published. The RPM, clock and framebuffer log sequence is the same in frozen and clean boots.
  - Mesa: Darwin has no submit worker (synchronous flush), no retry loop on SweetGPU errors, and no user-space lock
    cycle.
  - No SMMU fault is logged in any of the five boots, and CB0 terminates faults (no stall).
- `gpu state` takes neither gpu_lock nor fLock, so its "36 of 36" says nothing about the locks.
- **What is left.** The display thread is blocked in the kernel on something whose owner or cause is outside the
  state these drivers show. Candidates:
  - (a) A lock on the last-reference destruction path under fLock, held by a thread outside backboardd that is stuck
    itself. That path is `SweetGPUBuffer::free`: gpu_lock, the pool lock, `sweet_surface_lock`, and XNU's
    IOMemoryDescriptor and VM locks when the descriptor, kernel mapping and surface are released.
  - (b) A CPU wedged inside the SMMU access of the unmap (TLBIASID / TLBSYNC writes, TLBSTATUS reads). The hypervisor
    mediates this SMMU (the `sCR0.USFCFG` note at `sweet_gpu.c:826`) and is known to hang on some MMIO
    (`str wzr`). No software timeout can catch that, and the other 3 cores keep the phone running.

  Neither is visible in user stacks.
- **Next step (no build needed).** Reproduce at 588 and take a 2 s j0057 profile with the census
  (`tools/g2/prof.py fetch ... --tasks backboardd`). The kernel stack of the frozen display thread decides it:
  `lck_mtx_lock` / `IOLockLock` (and which lock) for (a); a running sample in `smmu_tlb_sync` / `gpu_pte_set` on one
  CPU that never leaves it for (b).
- **Side defects found on the way** (real, not shown to cause this freeze):
  - `smmu_tlb_sync` ignores its poll timeout.
  - `sweet_rpm.c` `RPM_POLL` drains `while (rpm_rx_one())` with no budget.
  - Selector 6 looks up `surfaceHandle()` and then `buffer(handle)` in two separate `fLock` sections (a concurrent
    free can slip in between).
  - Mesa `fd_submit_sp_flush_execute` ignores the backend's submit error.
  - SwapWait counts swap N done only once a later swap ended (strict `>`).

**Round t14a (2026-10-23 22:43, one boot, j64 kernel, `gpumhz=588`, Mesa t4final; `logs/netlog-t14a-ui.txt`,
`logs/prof-t14a*`, symbolized with `research/t14/smpsym.py`).** It froze, but **not the way j60b/t4d2 did**:
- `gpu state`: 588 MHz, **completed 5 of 5**. No 10-second stats line ever printed, and uibench found no moving
  frame.
- No backboardd thread is inside SweetGPU or libsweetca. The ir3 queues wait in `cnd_wait`; the four IOMFBServer
  threads, the render server and the main thread sit idle in run loops.
- backboardd **and** SpringBoard each have a thread blocked in a synchronous NSXPC call
  (`xpc_connection_send_message_with_reply_sync` <- `__LAUNCH_SERVICE...`, CoreServices), i.e. waiting on lsd.
  lsd ran 69 ms/s; launchd took 711 ms/s and mediaserverd 463 ms/s (task 7's loops).
- The display never went off and on again as in every earlier boot.
- **The census misses a thread that never runs:** it records only threads that ran in the last 500 ms, so a thread
  blocked for minutes never appears. The "next step" above needs a census of every thread of the task (kernel
  change) or a command-port stack dump.

Open: whether this is the same race showing another face, or a separate startup stall (LaunchServices) that
happened to land on a 588 boot. One round does not tell.

**User's question: not enough voltage? (2026-10-23 22:50.)** On SDM660 the GPU core has no rail of its own:
- The stock `gfx_corner` CPR4 regulator's `vdd-supply` is a stub (`gfx_stub_corner`); the core is fed through the
  BHS from VDD_CX (`system-supply`).
- kgsl's only voltage control is the CX level per corner: 0x100 = NOM for 585.6 MHz, 0x140 = NOM_L1 for 647. That
  is what j0060 votes, so by the stock tables 588 is not undervolted.
- Against it as well: j60b froze at 647 at the stock NOM_L1 vote, and a live switch to 588/647 after startup (j60a)
  ran clean.

**Round t14b (22:53, one boot, `gpumhz=588 gpucxfloor=0x140`: CX 924 -> 816 mV, more than stock gives 588).**
Clean: lock screen reached, the whole gesture script played (~3 min, 150-305 submits per 10-15 s window), median
moving frame 117.7 ms, no panic. Two 1-submit windows right before and at the gesture start were idle screen, not a
freeze: the next window had 280 submits. One clean boot does not settle a ~50 % event; it fits a voltage margin
effect and a race equally.

**j0069 (2026-10-23 23:10-23:30, test branch `t14-census`, CI 40026354719, `xnu/out-jasmine-j69`).**
- The fix for the census gap above: `prof start SECS PERIOD CENSUS NAME,NAME,all` takes every thread of the tasks,
  however long it has slept. For each blocked thread it also records the kernel stack, walked from the context the
  thread switched out with, or the continuation if it has no stack.
- `tools/g2/prof.py stuck OUT --kernel K --lib L` prints each thread's last census record: kernel stack, user
  stack, wait event, block hint.
- Usage: `prof.py fetch OUT --secs 3 --census 200000 --tasks backboardd,SpringBoard,all`.
- The patch is only on the test branch, not on `jasmine-merge`.

**Round t14c (23:33, one boot, j69 at `gpumhz=588`, normal CX 772 mV).**
- No freeze: lock screen, then 160-200 submits per window while the gestures ran, and a swipe at 23:37 still drew
  (GPU jobs 1091 -> 1106).
- The full census works: all 18 backboardd threads came back with kernel frames (logs/prof-t14c2-stuck.txt).
- **Tool catch:** `prof.py fetch` during `uibench.py play` makes uibench lose the command port (t14a and t14c), so
  the gesture script stops. Take the census after the play, or between plays.
- So far at 588/647: 3 freezes (j60b, t4d2, t14a) and 4 clean boots (j60c, t4b1, t14b, t14c).

**Freeze hunt (2026-10-23 23:42 to 00:04).** `tools/g2/freezehunt.sh KTAG TAG ARGS` boots up to N times with no
gestures. It reboots as soon as backboardd draws (>= 25 submits in one 10-second line); with no draw after 150 s it
counts the boot as frozen, takes the j0069 census and stops.
- j69 at 588, normal voltage: **1 freeze in 14 boots**.
  - t14h boots 1-4 and t14i boots 1-8 were clean, all drawing 60-94 s after boot.
  - **t14h-5 froze like t4d2** (5 submits, then nothing) and was lost: a stray byte made grep treat the log as
    binary, so the loop called the boot clean and the next boot's launcher rebooted the phone (the user saw it
    freeze).
  - Fixed with `grep -a` and a numeric check.
- Tally at 588/647: 4 freezes (j60b, t4d2, t14a, t14h-5) in 19 boots at normal voltage, plus t14b (high voltage,
  clean). The rate is well under the ~50 % first seen.

**Freeze hunt t14j (2026-10-24 00:05 to 00:34).** 11 more clean boots at 588 (drawing 69-122 s after boot). Boot 12
never happened: after boot 11's command-port reboot no fastboot device came (the known shutdown hang), and the phone
stayed unreachable until power + volume-down. The script called that "frozen"; it now stops with "no boot".
Where the shutdown stopped (`logs/netlog-t14j-11.txt`): launchd called reboot(2) (00:26:44), processes were killed, and
`unmount(0) /` was the last shutdown line. A good shutdown logs "hfs: unmount initiated on iOSRoot" next and reboots;
here the kernel stayed alive for minutes (charger, battery and USB lines, SMP sample 2 min later) but the root
unmount never finished. Then the command and log ports stopped answering, and `sweetwdt=20` did not reset it.
This is a separate shutdown bug in the HFS/UFS root unmount, not task 14.
- j69 at 588, normal voltage: **1 freeze in 25 boots** (t14h-5, lost).
- All boots at 588/647, normal voltage: 4 freezes in 30.

**588 MHz is the default again (2026-10-24 00:42, user's call).** Slot b = `shim-boot-j69-slotb.img` (j0069 included,
`mkimg.sh` gpumhz=588); first boot clean. The task is parked until the user sees a freeze in normal use. Then,
before any reboot: `prof.py fetch logs/prof-NAME --secs 3 --census 200000 --tasks backboardd,SpringBoard,all` and
`prof.py stuck` (WSL) on it; the stuck thread's kernel stack decides between a lock wait and something else.

**Boot-logo freeze in another agent's round t7c (2026-10-24 01:17, slot b j69 kernel at 588), census at 01:22**
(`logs/prof-t7c-freeze*`, `logs/prof-t7c-lsd*`).
- Like t14a: 4 GPU jobs done, no 10-second line, SpringBoard not in the census (not running yet), whole system idle
  (only kernel_task on a CPU). **No thread in SweetGPU or Mesa**; CA's display and render threads idle in run loops.
- **backboardd waits on lsd:** one thread in a synchronous NSXPC call from `_LSContextInitCommon` (LaunchServices),
  another `__ulock_wait` inside the same `_LSContextInitCommon`; a third waits on mediaserverd (CoreMedia FigXPC).
- **lsd is stuck seeding its database:** its main thread `__LSServerMain` -> `seedDatabase` ->
  `-[LSDatabaseBuilder createAndSeedLocalDatabase:]` -> `_LSDatabaseClean` -> `dispatch_sync`, blocked in
  `__ulock_wait`; no other lsd thread works on that queue.
- mediaserverd also waits: CoreAudio HAL plug-in activation in `dispatch_sync`, AirPlay `_carManager_copyProperty`,
  a MobileGestalt NSXPC call, PowerLog XPC.

Wider census at 01:25 (`logs/prof-t7c-odd.txt`, `research/t14/odd.py`) covered 16 processes: launchd, SpringBoard,
MobileGestaltHelper, cfprefsd, securityd, runningboardd, containermanager, mobileassetd, logd, configd,
UserEventAgent, lsd, mediaserverd, backboardd. **No runnable thread waiting for a CPU, and no thread blocked
mid-kernel** (a lock wait would show a real frame chain). Every thread is parked in a continuation: mach_msg
receive, ulock, psynch cv, kevent, workq. So nothing in the kernel holds anything. Either the startup is a wait
cycle among daemons, or a wakeup or message was lost. Lost wakeups are the one way our kernel could still cause this
picture; to tell them apart, read the owner of lsd's `dispatch_sync` queue lock (in lsd's memory).

User's point (01:30): the signs match the 588-only freezes, so it may still be our bug. True as a correlation. But
j60b/t4d2 had a thread *inside* a SweetGPU kernel call, while here every thread is parked.

So this freeze is a **userland startup deadlock around lsd's database seeding**, not the SweetGPU buffer free of
j60b/t4d2. t14a had the same LaunchServices waits, so it was probably the same lsd hang. Whether the GPU clock makes
it more likely is open: it was seen only at 588/647 so far, but at a low rate. Next: why lsd seeds a fresh database
on these boots (is the LS store not kept across boots?), and what its `dispatch_sync` target queue waits for.

**Boot-logo freeze solved: a deadlock inside lsd (2026-10-24 01:49, slot b `shim-boot-j69b-slotb.img` = j0069 +
j0069b, frozen on its first boot; `logs/prof-j69b-f1*`).** j0069b adds a meta `wait` line per census thread (user
x0-x3, the word at x1, the turnstile inheritor chain) and `prof peek PID ADDR LEN`.
- The chains: backboardd 1049, SpringBoard 509 and mediaserverd 473 wait through IPC turnstiles (ts4 -> ts5) on
  **lsd thread 1477**; lsd's main thread 470 waits (workloop turnstile) on **lsd thread 1480**; 1477 and 1480 both
  sit in `__ulock_wait` compare-and-wait on the same word (0x15d0a5314, value 0), no owner.
- Stacks:
  - 470: `__LSServerMain` -> `dispatch_once` -> `+[_LSInstallProgressService beginListening]` ->
    `-[_LSInstallProgressService performJournalRecovery]` -> `dispatch_sync`.
  - 1480, on that queue: `-[_LSInstallProgressService restoreInactiveInstalls]` -> `dispatch_group_wait`.
  - 1477: an XPC request in `__LAUNCH_SERVICES_CLIENTS_ARE_WAITING_FOR_THE_DATABASE_TO_FINISH_SEEDING__` ->
    `dispatch_group_wait` on the same group.
- So: journal recovery runs synchronously on the main thread and waits for `restoreInactiveInstalls`, which waits
  for the database seeding, which the main thread does after `beginListening` returns. A cycle inside lsd.
- `prof peek 98 0x15d0a5300 64`: the group's wait word is still 0 with one enter outstanding. Nobody ever left the
  group; no wakeup was lost. Not our kernel.
- t7c (01:17) was the other order of the same cycle: the main thread was already seeding (`_LSDatabaseClean` ->
  `dispatch_sync`) behind the same install queue. t14a was probably this too.
- Needed for it: lsd seeding its database at boot (the store missing or rejected) **and** an install journal to
  recover; which side runs first is timing. The GPU clock is not involved, except as timing.
- **Two different freezes, then:** (1) this lsd deadlock, the boot logo (t14a, t7c, j69b-f1); (2) the lock-screen
  freeze with CA's thread inside SweetGPU selector 2 (j60b, t4d2), still not caught with the census.
- Next for (1): find why lsd seeds at every boot and which install journal it recovers (in the phone's iOS root,
  `/var/mobile/Library/...`); clearing a stale journal or keeping the LS store is a root change (the user's OK).

**Boot-logo freeze, corrected: not a deadlock but a 14-minute lsd seed waiting for a Wi-Fi MAC (2026-10-24 01:57-02:50;
fix in `tools/mkadt.py`, on slot b since 02:45).**
- **The j69b-f1 boot recovered by itself.** At 02:09 lsd's main thread idled in `_runServerMainRunLoop`
  (`logs/prof-j69b-f1b*`), `gpu state` read 1949 of 1949 jobs, and the first kernel stats line after the freeze reads
  "backboardd: 5 submits in **832233 ms**". So the cycle above is wrong: the seed does not wait on the main thread.
- **The seeder is lsd thread 506**, overlooked at 01:49: `_LSServer_LSEnumerateAndRegisterAllBundles` ->
  `-[ICLWorkspace enumerateBuiltInSystemContentWithBlock:]` -> `MIFilesystemScanner` scanning the apps ->
  `-[MIInstalledInfoGatherer _populatePlaceholderRecordValues:signingInfo:]` ->
  `+[MIInstallationIdentity installationIdentityForBundle:settingIfNotSet:error:]` ->
  `__GenerateBuiltInAppInstallSessionID` -> `MGCopyAnswer("re6Zb+zwFKJNlkQTUeT+/w")` = **UniqueDeviceID** ->
  MobileGestalt's IOKit helper (`MGIOKitSupport.c`) in `dispatch_semaphore_wait`; its run-loop thread 1467 sat in
  `CFRunLoopRunInMode("MobileGestaltRunLoopMode", 5 s)`. (Obfuscated MG keys are base64(MD5("MGCopyAnswer" + name)),
  22 characters.)
- **What MobileGestalt does (libMobileGestalt disassembly, iOS 16.7.16):**
  - UniqueDeviceID = SHA-1 of serial number, ECID, WifiAddress and BluetoothAddress (format `%@%@%@%@%@`).
  - WifiAddressData reads `IODeviceTree:/chosen` `mac-address-wifi0`, then IORegistry services `sdio`, `wlan`,
    `marconi-wifi`. Failing those (and not a VM: `kern.hv_vmm_present`), it **waits 5 s for an `IONetworkController`**
    (IOServiceMatched), then falls back to syscfg `WMac`.
  - BluetoothAddressData reads `/chosen` `mac-address-bluetooth0`, then a `bluetooth` service; no wait.
  - Our ADT had neither MAC, and our kernel has no IONetworkController (the USB Ethernet is a plain ifnet). So every
    UDID request waited 5 s and returned NULL, and MG does not cache a NULL answer.
- **InstalledContentLibrary:** for a built-in app or app extension, `installationIdentityForBundle:` always generates
  the install session ID (it reads the `com.apple.install_uuid` xattrs only for other bundles), so a scan asks for
  the UDID once per bundle. 141 apps in `/Applications` + 32 in `/System/Library/AppPlaceholders` = 173 x 5 s =
  14.4 min, the stall measured.
- **Why only some boots.** lsd keeps no LaunchServices store: no `com.apple.LaunchServices-*-v2.csstore` in its
  container's `Library/Caches` (`/private/var/containers/Data/System/D4CD3628-...`), `/var/db/lsd` empty, one empty
  `/private/var/tmp/NSIRD_lsd_*` per boot (175 so far). So it builds its database at every boot, but a normal build
  does not take this path: boot t14k (02:20, `sweetiolog=lsd,SpringBoard`) was clean and lsd made **no**
  IONetworkController wait (SpringBoard makes one on every boot). Which state sends a build through the per-bundle
  scan is not known (the frozen census also had journal recovery and `restoreInactiveInstalls` waiting on it).
- **The GPU clock** only shifts timing; it is not involved.
- **Fix (real-hardware behaviour, no iOS root change):** `tools/mkadt.py` puts `mac-address-wifi0` and
  `mac-address-bluetooth0` into `/chosen`, as iBoot does. The values are synthetic, locally administered, made from the
  synthetic ECID: `4a:41:53:4d:49:01` / `:02`. Every image `mkimg.sh` builds gets them (the ADT is rebuilt each time;
  no kernel change).
  - The phone now has a UniqueDeviceID; before, every caller got NULL.
  - Check t14m (02:25, one boot): SpringBoard's IONetworkController wait is gone, the UI drew 46 s after boot, no panic.
- **Not explained by this:** t7c's lsd (01:17) had only its main thread, in `_LSDatabaseClean` -> `dispatch_sync`
  onto a queue in a CoreServices object (`[obj+0x18]`, function 0x181cd6ed8), with no other lsd thread. Its
  MobileGestaltHelper was in the same 5-second IOKit helper for another key: the sysconfig fallback reads `/chosen`
  `syscfg-v2-data`, then the `AppleDiagnosticDataSysCfg` service, then waits 5 s for `AppleDiagnosticDataAccessReadOnly`,
  serving mediaserverd. So keys that come from syscfg also cost 5 s per uncached lookup.
- **Verified (02:28-02:44, `freezehunt.sh j69b t14n "sweetiolog=lsd,SpringBoard"`, 588 MHz, no gestures): 12 of 12
  boots clean**, drawing 44-88 s after boot (60-122 s in the earlier 588 hunts), no IONetworkController wait in any
  boot (`logs/netlog-t14n-*.txt`), no panic. With the 1-in-10 to 1-in-25 rate seen before, 12 boots alone are not
  proof; the measured mechanism is: the 5-second wait is gone.
- **On the phone:** slot b = `shim/out/shim-boot-j69b-slotb.img` rebuilt at 02:45 (same j69b kernel, ADT with the
  MACs; the previous image is kept as `shim-boot-j69b-slotb-nomac.img`), flashed with `flash-slotb.sh`; first boot
  `logs/netlog-j69m-slotb.txt`: GPU 587 MHz, self-test PASS, UI drawn, no panic.
- **Open:**
  - Why lsd never writes its store (seeds every boot; `com.apple.lsd` runs as mobile; its errors go to os_log only,
    which the netlog does not carry).
  - What sends a seed through the per-bundle scan.
  - The t7c variant above.
  - The syscfg 5-second waits: no `syscfg-v2-data` in `/chosen`.
  - The lock-screen freeze (2), SweetGPU selector 2.

**How.** Reproduce: boot at `gpumhz=588` repeatedly (`uiround.sh` with `ARGS=gpumhz=588`; ~50 % freeze, so a few
boots). In a frozen boot, take a 2 s j0057 profile (`tools/g2/prof.py fetch ... --tasks backboardd`): its census
records kernel stacks of every waiting backboardd thread, which shows who holds which lock. Fix the order (one lock
order everywhere, or drop `fLock` before taking `gpu_lock`), no timeouts as workarounds.

**Done when:** 10 boots in a row at 588 MHz without the freeze; `tools/g2/mkimg.sh` back to `gpumhz=588` (the top level
at the bootloader's CX corner: no voltage increase, measured 587 MHz in t4b1); the slot b image rebuilt and flashed
("Done means on the phone"); result in GPU.md.

## 15. Make lsd keep its LaunchServices store across boots

**Now (found 2026-10-24 during task 14).** lsd never has a store on disk, so it builds its database from scratch
at every boot:
- No `com.apple.LaunchServices-NNN-v2.csstore` (name pattern `%s-%03llu-v2.csstore` under `Library/Caches`, from
  CoreServices' strings) in lsd's data container `/private/var/containers/Data/System/D4CD3628-6EE5-4032-90C0-BB7818F0299A/`
  (`.com.apple.mobile_container_manager.metadata.plist` says `com.apple.lsd`). Its `Library/Caches` and
  `Library/Preferences` are empty, also long after a seed finished (checked 02:16 in the recovered j69b-f1 boot,
  after the clean t14k / t14m boots).
- `/private/var/db/lsd` is empty: no `com.apple.lsdidentifiers.plist` (vendor IDs, `LSVendorSeed`), no
  `com.apple.lsdschemes.plist`.
- `/private/var/tmp` holds one empty `NSIRD_lsd_*` directory per boot (175 on 2026-10-24 02:20). These are
  NSFileManager item-replacement directories: lsd starts an atomic write every boot, and the result never lands.
- Not in `/private/var/mobile/Library/Caches` or `/private/var/root/Library/Caches` either.
- Two lsd jobs: `com.apple.lsd` (UserName `mobile`, the one that runs at boot, one `exec lsd` per boot) and
  `com.apple.lsd.system` (root, `systemSessionDaemon runAsRoot`, on demand). The census pid 98 is the mobile one.
- lsd reports its failures only via os_log, which the netlog does not carry: "Failed to save database to %{public}@:
  %{public}@", "%{public}s: error saving database for session %@: %{public}@", "Failed to write database header",
  "Failed to write plist data for identifiers: %@".

**Why it matters.** Every boot pays a full seed while backboardd, SpringBoard and mediaserverd wait on lsd through
XPC. Task 14's 14-minute stall needed a seed through the per-bundle scan. The MAC fix made that scan cheap but does
not stop the seed. Which state sends a seed down that path is not known: journal recovery and
`restoreInactiveInstalls` were also waiting in the frozen census, and installd started only after the stall.

**Leads, in order.**
1. Ownership and mode of lsd's directories in our root build. `tools/mkiosroot.sh` makes `/private/var` by hand
   (only logd's directories get owners; `sweet-root-tweaks.py` makes the containers). On iOS the restore makes them.
   lsd runs as `mobile` (501): check owner and mode of `/private/var/db/lsd`, `/private/var/tmp`, the container and
   its `Library/Caches` (Linux shell: `fastboot boot shim/out/nura-r109-boot_a.img`, `tools/pmos-shell.py`,
   read-only mount; or extend `sweet-fs.py ls` to print mode and uid). Compare with a real iOS 16 device's
   values if known (`/private/var/db/lsd` is `mobile` there, unverified).
2. Data protection: the store may be written with a protection class that our AppleKeyStore stub
   (`SWEET AKS` lines) cannot serve, so the open or rename fails. Look for lsd's AKS calls around the save.
3. If 1-2 show nothing: see the errno. Either a kernel trace of failed `open` / `rename` / `renamex_np` / `mkdir`
   by process name (like `sweetiolog`, e.g. `sweetfslog=lsd`, new patch), or read logd's persisted logs
   (`/private/var/db/diagnostics/*.tracev3` + `uuidtext`) with a tracev3 parser (download needs the user's OK).
4. Then: why a seed sometimes goes through the per-bundle scan (`-[ICLWorkspace enumerateBuiltInSystemContentWithBlock:]`
   -> `_populatePlaceholderRecordValues`) instead of the normal path. With a kept store this may not happen at all.

**Rules.** Changing ownership or files in the iOS root needs the user's OK first (also a fix in `mkiosroot.sh` /
`sweet-root-tweaks.py` that is then applied to the phone). Read-only checks are fine.

**Related, not this task.** MobileGestalt's sysconfig fallback waits 5 s per uncached lookup. It reads `/chosen`
`syscfg-v2-data`, then an `AppleDiagnosticDataSysCfg` service, then waits for `AppleDiagnosticDataAccessReadOnly`;
we provide none of them (t7c: MobileGestaltHelper in that wait, serving mediaserverd). That is a separate ADT task:
syscfg data with serial and region. Also open from task 14: the t7c lsd variant (main thread in `_LSDatabaseClean` ->
`dispatch_sync` onto a CoreServices object's queue, function 0x181cd6ed8, no other lsd thread).

**Tools from task 14.** Unslid census addresses: scratch `raw.py`. Shared cache disassembly per image:
`ipsw dyld disass $D --image NAME -q`, dumps in WSL `~/ios-work/lsd` (CoreServices strings, InstalledContentLibrary.s,
libMobileGestalt.dylib.s). Obfuscated MG keys: base64(MD5("MGCopyAnswer" + name))[:22].

**Done when:** after one boot a `com.apple.LaunchServices-*-v2.csstore` exists in lsd's container and
`/var/db/lsd/com.apple.lsdidentifiers.plist` exists; the next boot loads the store instead of seeding (no new
`NSIRD_lsd_*`; lsd's census shows no `seedDatabase`); on the phone by default ("Done means on the phone").

## 16. Pipeline rendering and presentation using surface completion fences

**Why (2026-10-24).** libsweetca's `w_Flush()` calls `glFinish()`, so CA's rendering thread
waits for queued GPU work before it can prepare more CPU work. Task 4's CPU savings at
266 MHz reappeared as GPU waiting. Submitting frame N and preparing N+1 while the GPU
finishes N is a real opportunity, but its current gain has not been measured.

**The catch.** Replacing that `glFinish()` with `glFlush()` alone is insufficient:
`AppleCLCD::directPresent()` calls `sweet_surface_cpu_access()` before scanning the surface,
which waits for its GPU fence on the same calling thread. The wait can simply move there.
True overlap requires a queued presentation that becomes eligible after the surface's
render-completion fence, allowing CA's thread to return before GPU completion. Keep genuine
`Finish`/CPU-readback semantics intact. Jobs must be submitted before publishing their fences.

**Required ordering.** Do not present unfinished pixels; retain each queued surface until
its render fence completes and it retires from scanout; do not let GPU writes reuse a
surface the panel still reads. Preserve j0058's SwapWait/latch protections. Bound the queue
to avoid turning throughput gains into extra touch latency. Earlier overlap experiments
exposed flicker from premature surface reuse (GPU.md, "The flicker found").

**Measure first.** Add timestamps/IDs for CPU render/flush, GPU submission/completion,
swap queueing and actual observed latch, linked by surface/swap/fence. Identify the critical
path and available CPU/GPU overlap; distinguish panel waits from GPU execution. The current
[first pass](PERF-BASELINE-20261024.md) finds explicit GPU-fence sleeping around 5-6% of the
home capture and 1% in Control Center; submission waits add more but include other causes.
These are not removable frame-time estimates. Run task 5 first; revisit overlap after its
CPU cost changes. Do not infer FPS from GL flushes or the old sampled-present detector.

**Done when:** matched home/Control Center runs show shorter measured presentation
intervals or lower end-to-end latency, bounded queue depth and correct fence/surface
lifetime; no new corruption, tearing, flicker, held-surface writes or hangs in a sustained
UI run; the result is on by default on the phone, with the baseline and result in GPU.md.
