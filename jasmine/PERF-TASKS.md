# Performance, bug-fix and diagnostic tasks

Reviewed 2026-10-24 against [NOTES.md](NOTES.md) and the measurement reports.
Task2 update2026-10-27: opt-in eight-core DVFS passes both clusters' full stock
OPP sweeps, cross-core RAM/cache checks and automatic floor/ceiling scaling.
Physical UI swiping and final auto-on boot are responsive after fixing released-
surface pixel retention; the user confirms the Wallpaper hang is gone (incorrect
rendering is deferred). CI40520184930 passes. Thermal throttling is
deferred per latest user direction; persistent defaults remain unchanged.
[Active DVFS plan](PERF-TASK2-DVFS.md), [UI fix and validation](PERF-CPU-UI-FREEZE-20261027.md).
Task numbers stay unchanged so existing handoffs and logs still refer to the same work.
Tasks are grouped by purpose and status. The recommended order below ranks benefit
versus effort; category tables keep stable task-number order. New tasks 17-21 were
approved by the user on 2026-10-24; implementation has not started.

## Current state and priorities

- **2026-10-29 fresh measurement on boot_b j0118 (828x1792@2, DDR governor, GPU collapse): Control Center is
  now limited by the CoreAnimation render thread's CPU (25 ms/frame: CA 12.6, Mesa 10.4), GPU close behind
  (~15-23 ms, 64 % RAM-starved); frames sit at 2 periods. The 10-28 "CPU clock has no effect" result no longer
  applies. [Report](PERF-BOTTLENECK-20261029.md).
- **2026-10-28 fresh measurement on the installed config (8 cores, CPU auto, GPU 588, DDR 1804):
  the GPU's DRAM traffic is the bottleneck.** Same-boot clock sweep: CPU pinned at 1401 MHz or
  2208 MHz = no change; GPU -27% = -4..-10%; DDR -28% = -15..-24%. 56-66% of GPU busy cycles
  are RAM-starved; frames land on 2-3 periods of the 16.7 ms clock. CPU-side tasks (5, DVFS) will
  not raise frame rate until GPU time per frame falls; tasks 24/25 are the levers.
  [Report](PERF-BOTTLENECK-20261028.md). The ranking table below predates this.
  Same-day GPUPROF boots: Home 100 draws / 54 batches / 26-27 ms GPU per frame, CC 195 / 103 /
  30-35 ms; batches end at ~40/~55 texture barriers per frame; CC spends ~10 ms/frame outside
  draws (full-target clears in sysmem); full-screen blended copies cost 5-6 ms each.
- **2026-10-28 task 16 mode 2 ported to the current kernel (j0109/j0110), not yet default:** same-kernel
  A/B Home B 27.1 -> 33.1/s (+22%), CC +4-7%, Spotlight +26%, no faults.
  [Report](PERF-TASK16-MODE2-20261028.md). **Installed to boot_b 2026-10-28 02:50** (image 9096026c...).
- **2026-10-25: the GPU is now the limit for Home and memory-bound** (65% of busy cycles RAM-starved, every batch in
  sysmem at 1125x2436): [GPU time report](PERF-GPU-TIME-20261025.md), new **tasks 23-25** in
  [PERF-TASK23-25-GPU-TRAFFIC.md](PERF-TASK23-25-GPU-TRAFFIC.md). DDR 1804 is the default since then (task 10).
- Sustained UI motion is still mainly limited by CPU rendering work. Continue **task 5**;
  its first optimization is installed, but the remaining work is open. Investigate
  **task 16** after task 18 measures the linked CPU/GPU/swap/latch timeline.
- The latest documented default is **4 Gold cores at 1747 MHz, GPU 588 MHz,
  DDR 1804 MHz** (since 2026-10-25 22:57; was the bootloader's 1296). Slot b is j0070 (kernel CI `40059091430`), rebuilt with `sweetddr=1804`;
  installed Mesa is `8877ff1` / CI `40053566696`. Earlier profiles use j69b;
  record the actual software and workload when making a new comparison.
- The old 49.3 ms/frame breakdown below predates tasks 1, 4, 7 and the first task-5
  optimization. It is historical evidence, not today's baseline or an additive savings budget.
  Current distinct displayed FPS and touch-to-display latency remain unmeasured.
- **Task 14 remains open:** the MAC-related boot-logo stall was fixed, while the
  SweetGPU buffer-free freeze is unresolved. **Task 15 is closed:** the database
  was found persisted in another container; no persistence fix is justified by the old premise.

Read [For every agent](#for-every-agent) before implementing a task. Latest measurements:
[whole-system baseline](PERF-BASELINE-20261024.md),
[task-5 diagnostics](PERF-TASK5-DIAGNOSTICS-20261024.md).
The latest installed task-5 result is summarized below.

## Recommended order: benefit versus effort

User approved this ranking and the new tasks on 2026-10-24. It prioritizes visible
responsiveness relative to implementation effort, not maximum theoretical savings.
Effort is a planning judgment, not a measured implementation result. Keep a small,
repeatable baseline throughout using existing tools; task 18's full instrumentation
does not need to block the first focused Mesa optimization.

| Order | Work | Type | Effort | Why / decision point |
| --- | --- | --- | --- | --- |
| 1 | **Task 5: Mesa draw preparation, state and batch costs** | Performance | Medium | Strongest measured opportunity for sustained animation. Confirm one avoidable cost, then make one focused optimization. |
| 2 | **Task 17: persistent shader cache** | Performance, feasibility first | Low-medium if supported; otherwise higher | Candidate for fewer first-use compilation hitches. Not necessarily a one-flag fix; expect little warmed-scrolling gain. |
| 3 | **Task 6: repeat 4-core versus 8-core comparison** | Diagnostic stage of a performance task | Low for comparison | Old timings predate major fixes. Continue scheduler changes only if the current comparison identifies a fixable problem. |
| 4 | **Task 11: hardware clock gating only** | Performance: power/heat | Low-medium | Smallest GPU power-management part, with an A512 reference. No immediate FPS gain established. |
| 5 | **Task 19: SpringBoard CPU profiling** | Diagnostics | Low-medium for diagnosis | Check the other substantial CPU consumer for cheaper opportunities before large architecture changes. |
| 6 | **Task 16: presentation pipelining** | Performance | High | Task 18 must establish useful overlap first. Fence ordering and surface reuse make implementation delicate. |
| 7 | **Tasks 2 + 13: CPU DVFS with thermal limits** | Performance: speed/power/heat | High; transition/governor work | Small voltage steps now work on both clusters (2026-10-27); PLL/array sequencing, full-range validation and thermal limits must accompany higher clocks. |
| 8 | **Task 10: DDR governor** | Performance: power/latency | Medium | Raising fixed DDR already showed no measurable UI gain. Calibrate load counters before using them as policy inputs. |
| 9 | **Remaining task 11, then task 12** | Performance: power/heat | High | GPU power-down/DCVS and CPU power collapse involve substantial transition and resume work. |

**Alongside this order:**

- **Task 18:** build measurement coverage incrementally; use existing matched timing/CPU
  comparisons immediately, then add actual swap/latch and input latency measurement.
- **Task 3:** finish chosen-clock validation alongside normal rounds. The 588 MHz default
  is already installed; trying 647 MHz is not a leading new speed opportunity.
- **Task 8:** a relatively small correctness fix, with no demonstrated speed gain;
  handle before relying on the affected write-combined/non-pool memory path.
- **Task 14:** take a census whenever the freeze occurs; move the fix ahead of optimization
  if it repeatedly interrupts normal use or benchmarking.
- **Task 20:** investigate memory/cache growth when reproducing the Wallpaper freeze
  or other degradation; escalate if it prevents representative performance tests.
- **Task 21:** investigate startup/storage/service waits when boot or app-launch latency
  is the priority. Separate it from warmed animation and task 17's compilation work.

## Open performance improvements

Includes throughput, latency, power and sustained performance. A partial implementation
stays here until its remaining scope is finished and the result is on by default on the phone.

| # | Task | Status / evidence | Kernel patch |
| --- | --- | --- | --- |
| [2](#2-gold-clock-and-dvfs) | Both-cluster CPU DVFS: Gold up to 2208, Silver up to 1843 MHz | Opt-in8-core stock OPPs, memory integrity and demand scaling pass; physical UI responsive after surface-retention fix. Persistent defaults unchanged; thermal policy deferred. [Active plan](PERF-TASK2-DVFS.md). | j0104/j0104a controller; j0105 diagnostics; j0106 surface fix |
| [3](#3-gpu-clock-and-validation) | GPU stock clock levels and validation | Levels up to 647 MHz work; default is 588. Historical GPU-wait gain ~0.5-0.6 ms; long top-level validation open, task 14 unresolved. | j0060 |
| [5](#5-cut-mesas-per-draw-cpu-cost) | Cut Mesa per-draw CPU cost | Partial: active-sampler barrier fix installed; +3% home / +5% Control Center swap arrivals, not confirmed display FPS. More CPU work open. | Mesa only |
| [6](#6-make-8-cores-beat-4-j0052-tuning) | Make 8 cores beat 4 | Older rounds: 96-128 ms vs 81 ms on 4 Gold; repeat on the current baseline. | j0061 reserved |
| [10](#10-load-based-ddr-governor-ceiling-1804-mhz-on-by-default) | Load-based DDR governor | Partial: **fixed 1804 is the default since 2026-10-25 22:57** (`mkimg.sh` `sweetddr=1804`, slot b): with the GPU memory-bound it cut Home B 37.5 -> 32.9 ms and CC 53 -> 41 ms. The load-following governor (idle power) is still open. | j0065 reserved |
| [11](#11-gpu-power-management-hardware-clock-gating-idle-power-down-load-based-clock) | GPU clock gating, idle power-down and DCVS | Open; power/heat target. Clock transitions must account for task 14. | j0066 reserved |
| [12](#12-cpu-idle-power-power-collapse-instead-of-wfi-unused-cores-off) | CPU/cluster power collapse; unused cores off | Open; idle power target. | j0067 reserved |
| [13](#13-thermal-limits-tsens-driven-caps-on-cpu-and-gpu-clocks) | Thermal clock limits | Open; sustained performance and heat; depends on tasks 2 and 11. | j0068 reserved |
| [16](#16-pipeline-rendering-and-presentation-using-surface-completion-fences) | Pipeline rendering and presentation | Planned 2026-10-25: [step plan](PERF-TASK16-PLAN.md). After the threaded context, `glFinish` (GPU fence + driver drain) is the display thread's largest wait. G1 passed 2026-10-25 16:21 (CA uses a third swap surface when the previous page is busy); S4 design approved 16:46; next build 1 (S5 + S7, mode 1). Benefit unmeasured. | j0100 (build 1) and j0101 (build 2, conditional) reserved 2026-10-25 |
| [17](#17-persistent-shader-cache) | Persistent shader cache | New, unstarted; target first-use/reboot compilation hitches, not warm lookup. Feasibility and gain unvalidated. | Mesa/build; no reservation |
| [24](PERF-TASK23-25-GPU-TRAFFIC.md#24-fewer-batches-per-frame-then-gmem-for-the-big-ones) | Fewer batches per frame, then GMEM | 2026-10-28: stages 1/2 done in test libraries. [Stage 3 measured](PERF-GMEM-STAGE3-20261028.md): 16/16 pixel cases pass, but two framebench pairs show no global gain (Home 33.09 -> 32.92/s; CC B 23.87 -> 23.50). Current GMEM rule stays off; no production install. Feedback-path redesign/user direction open. | Mesa/libsweetca; kernel only if the VA pad must grow |

## Open bug fixes

Correctness and reliability work, even where fixing a bug may also improve performance.

| # | Task | Status / impact | Kernel patch |
| --- | --- | --- | --- |
| [8](#8-fix-the-pmap-32-bit-page-number-shift-correctness) | Fix the pmap 32-bit page-number shift | Open; incorrect physical address above 4 GiB, not a measured frame-time optimization. | j0063 reserved |
| [14](#14-fix-the-sweetgpu-buffer-free-freeze) | Fix the SweetGPU buffer-free freeze | Partial: MAC-related boot-logo stall fixed; selector-2 freeze still needs a kernel census. | j0069 + j0069b diagnostics |

## Open diagnostics

These tasks produce measurements and a scoped next action. They do not claim a speed
gain by themselves. A discovered defect becomes bug-fix work; an avoidable cost becomes
performance work, with its own implementation and validation.

| # | Task | Evidence / deliverable |
| --- | --- | --- |
| [18](#18-displayed-frame-and-input-latency-benchmarks) | Displayed-frame and input-latency benchmarks | Actual presentation intervals, slow-frame percentiles, missed refreshes and correlated input latency; shared measurement prerequisite for task 16. |
| [19](#19-profile-springboards-cpu-work) | Profile SpringBoard CPU work | Home-swipe main-thread load ~711-743 ms/s in the earlier baseline; identify layout/animation/IPC costs and whether they delay output. |
| [20](#20-investigate-memory-and-cache-growth) | Investigate memory and cache growth | Buffer/surface/memory high-water marks, allocation stalls and pressure across repeated transitions; Wallpaper exhaustion remains a hypothesis. |
| [21](#21-profile-cold-start-boot-and-storage-waits) | Profile cold-start, boot and storage waits | Separate storage, service/IOKit waits and compilation; five-second syscfg fallback waits are an existing lead. |
| [25](PERF-TASK23-25-GPU-TRAFFIC.md#25-render-at-or-nearer-the-panel-resolution) | Render at (or nearer) the panel resolution | CA renders 1125x2436 for a 1080x2160 panel (fitted to 997x2160). 2026-10-28: [j0111 small-canvas switch, mkadt option and a SpringBoard notch hook make 828x1792 @2x run with a status bar](PERF-RENDER-SIZE-20261028.md); GPU time per frame drops ~3x but framebench is ~20% slower (a ~42 ms non-GL floor); 750x1624 is impossible (UIKit accepts only fixed pixel widths). Not installed. | j0111 (default off) |
Task 6's initial 4/8-core comparison is also diagnostic, but its scheduler implementation
remains under performance. Task 16's shared timeline measurement is tracked in task 18;
task 16 retains the pipelining implementation and its acceptance criteria.

## Completed work and closed investigations

Completed implementations and experiments are separate from work closed because its premise was disproved.
Outstanding validation is called out in the detailed results below.

| # | Task | Result / remaining validation |
| --- | --- | --- |
| [1](#1-move-the-display-scale-off-the-cpu--done) | Display scaling off the CPU | Done 2026-10-23, j0058, default on phone; present 7-40 us. Original same-day before/after profile not captured. |
| [4](#4-make-mesas-buffer-caches-hit--done) | Mesa buffer caches | Done 2026-10-23, default on phone; buffer-path profile share 17.8% -> ~6%; 12-minute handle counts flat. |
| [7](#7-stop-the-xpc-retry-loops--done) | XPC retry loops | Done 2026-10-24, root changes installed; idle daemon load 2.16 cores -> ~0.003, TSENS ~8 C lower. Moving-frame gain not isolated. |
| [9](#9-ddr-clock-vote-through-the-rpm--experiment-complete) | DDR clock vote and bottleneck experiment | Experiment complete 2026-10-23, j0064; 1296 -> 1804 gave no measured UI gain then (CPU-bound frame). Re-measured 2026-10-25 with the GPU the limit: -12% Home, -23% CC; 1804 now the default (task 10). Full 10-minute top-rate soak outstanding; governor is task 10. |
| [15](#15-launchservices-store-persistence--closed-premise-disproved) | LaunchServices store persistence | Closed 2026-10-24: persisted store found in the actual InternalDaemon container, survives reboot. No persistence repair made. |
| [22](#22-post-boot-accessory-sync-cpu--closed-normal-behavior) | Post-boot accessory sync CPU | Closed 2026-10-25: accessoryupdater + trustd sync accessory metadata from iCloud after each boot (~0.8 core), gone by 24 min. Normal; no action. Benchmarks must not start inside it. |
| [23](PERF-TASK23-25-GPU-TRAFFIC.md#23-control-center-blur-at-reduced-resolution) | Shared UI blur / missing-downsampling investigation | Closed at user request 2026-10-26. Gaussian downsampling observed on device; proposed missing-copy premise disproved for that path. No optimization delivered or speedup measured. Variable-blur approximation remains a documented limitation with unmeasured runtime impact. [Evidence](PERF-TASK23-DEVICE-AUDIT.md). |

## Dependencies and shared files

- Task 5 and completed task 4 share Mesa code. Retain task 4 and the installed first task-5 fix in new baselines.
- Tasks 10 and 11 both touch `sweet_gpu.c`; coordinate changes or run sequentially.
- Task 13 needs the clock controls from tasks 2 and 11; implement thermal limits alongside higher CPU clocks.
- Task 18 owns the shared render/GPU/swap/latch measurements required to justify task 16.
- Tasks 17 and 21 share cold-start evidence; keep shader-cache effects separate from storage/service waits.
- Diagnostic tasks 19/20 may reveal work related to task 5 or a bug; cross-reference evidence instead of duplicating fixes.
- Task 14 is a reliability concern for tasks 3 and 11; 588 MHz is already the default by the user's decision.
- Historical patch reservations are retained above. **j0070 is already used by the AMFI service fix**;
  check the patch directory before assigning any new kernel number.

## Power and heat measurements

Gold is fixed at 1747 MHz on XBL's voltage and Silver at XBL's 1382 MHz; no CPU DVFS or thermal
throttling is implemented. CPU idle uses WFI. The GPU now defaults to 588 MHz and has no normal idle
power-down or hardware clock gating. DDR is fixed at 1804 MHz since 2026-10-25 (the bootloader leaves 1296), the RPM buses at their maximum. Task 7 removed the large daemon
retry load, but tasks 2 and 10-13 still cover power and heat.

Record idle and moving power before/after: PM660 fuel-gauge battery current (j0010;
add the current readout if missing), on battery with the user's OK, or a USB power meter supplied
by the user. Use `osmctl tsens` for temperature. Temperature alone is not a power measurement.

## For every agent

**Completion by task type.** Diagnostics finish with reproducible evidence and their
stated report/tooling deliverables; they do not need to invent or install a speed gain.
Completed experiments and disproved premises are labelled separately below.

**Done means on the phone for implementation tasks (the user's rule, 2026-10-23).**
A performance improvement or bug fix is done only when its result is **on by default
and the phone runs it after a plain reboot**:

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
Export with `git format-patch -1 --stdout > xnu/patches/j00NN-jasmine-<name>.patch`. Use the reserved patch number
listed for your task only after checking it is still free; j0070 is already assigned to AMFI. Build the 4K/8-core kernel on CI:
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
  legacy 100-GL-flush interval summaries, GPU wait, flicker checks, and GPU draws into held surfaces.
  These averages are not distinct displayed-frame intervals or FPS; see task 18 for latch measurement.
- `bash tools/g2/profround.sh <ktag> <tag> "<boot-args>"` does the same with the j0057 sampling profile; the report
  is `tools/g2/prof.py` / `profsplit.py`. Keep profile windows short: the download runs at about 20 KB/s.
- Compare against a baseline round from the same script on the same day. Rounds vary: use 2 rounds per variant.
- **Check that the post-boot accessory sync has finished** before measuring. After every boot
  accessoryupdater and trustd sync accessory metadata from iCloud for some minutes (~0.8 of
  the 4 Gold cores; task 22). Take the phone lock, sample them for 3 s:
  `python tools/g2/prof.py fetch research/<run>/precheck --secs 3 --tasks trustd,accessoryupdater`,
  then in WSL `python3 tools/g2/prof.py report research/<run>/precheck --kernel <kernel symbols>`.
  If either shows more than ~20 ms/s in "CPU time per process", wait a minute and check
  again; start the round when both are idle, and note the check in the results. Fresh-boot
  round scripts (`uiround.sh`, `profround.sh`) boot and play at once, inside the sync: use
  them only to compare variants run the same way. All 2026-10-25 framebench captures ran inside the sync.
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

## Historical frame breakdown (j0057 profile, 2026-10-22 22:59, `jasmine/GPU.md` "Where a moving frame goes")

**Historical configuration, before the completed fixes below.**

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

## Performance task details

### 2. Gold clock and DVFS

2026-10-27: both-cluster controller and temporary eight-core automatic boot pass
stock OPP, cross-core memory and physical UI acceptance. User-confirmed Wallpaper
hang resolved by the released-surface retention fix; rendering is separate.
See [current DVFS plan](PERF-TASK2-DVFS.md) and [final validation](PERF-CPU-UI-FREEZE-20261027.md).
Thermal policy is deferred and persistent boot defaults are unchanged. The
starting assumptions below are historical.

**Scope restarted 2026-10-26:** all eight CPUs with stock maximum clocks and
load scaling. The user subsequently deferred thermal throttling. The controller
and physical acceptance results are now complete for the temporary images in
the [active plan](PERF-TASK2-DVFS.md); persistent deployment is separate.

**Historical starting point.** Gold ran at a fixed1747MHz on XBL's voltage (`sweetgold=1747`, j0015 in `osfmk/arm64/sweet_cpuclk.c`).
Silver stays at XBL's 1382 MHz. OSM (Qualcomm's hardware DVFS) is dead on this boot path: TrustZone owns its
sequencer. So the plan is software DVFS: switch PLLs in software, set the voltage through the SAW / PM660 SPMI,
run a load governor with a TSENS limit, and cover both clusters (Gold on PM660 S2+S3, Silver on S1).
The voltage-commit blocker was resolved with small SAW16 steps on2026-10-27:
[hardware evidence](PERF-CPU-VOLTAGE-20261027.md). Higher clocks, full-range
transitions and the governor were subsequently validated as linked above. The old HANDOFF-CPUCLK.md and NOTES.md
"CPU clock (OSM + CPRh)" retain the historical investigation.
The live tool `tools/cpuclk/osmctl.py` (j0045-j0048: register reads/writes, sequences, SPMI reads, `check`,
`tsens`) turns experiments into command lines instead of kernel builds. The per-chip table comes from
`tools/cpuclk/cpuclk_model.py`: perfcl speed bin 1 reaches 2208 MHz and pwrcl reaches
1843.2 MHz. Raw DT voltage ceilings are further reduced by per-chip adjustments;
the current model gives top ceilings of 948 mV Gold / 900 mV Silver, still untested
on hardware. The APM crossover is at 872 mV, and MEM-ACC levels must follow the corner.

**Done when:** both clusters can reach their validated stock maxima when load and
thermal headroom allow, with verified supply/array transitions, load-based scaling
and tested thermal caps/recovery. All-core and transition checks give zero errors;
matched 4/8-core UI and idle/load power/temperature comparisons support the chosen
defaults. No frame-time gain is assumed. See the active plan for installation
acceptance. Say before each round that could hang the phone.

### 3. GPU clock and validation

**Partial; default 588 MHz since 2026-10-24 00:42.** j0060 provides RPM GLINK, CX corner votes,
mem-acc and cx_ipeak; `gpumhz=` and live `gpu clk MHZ` select stock levels. This chip tops out
at **647 MHz**, measured with the CP cycle counter. See [GPU.md](GPU.md), "j0060", and task 14.

The 2026-10-23 comparison at 266 -> 588 MHz reduced GPU wait per flush from 3.5 to 2.9 ms,
without visibly shorter frames. That result predates the daemon and first task-5 fixes;
it is not a current frame-time gain or a reason to promise 7.5 ms of savings.

588 MHz (measured ~587) is already the phone default. The MAC-related boot-logo stall was
fixed; j60b/t4d2's separate SweetGPU buffer-free freeze remains unresolved under task 14.

**Remaining acceptance:** validate the chosen final stock level with measured clocks,
matched UI runs and at least 10 minutes without hangs, then the user's visual check.
If 647 has no useful gain or has a heat/power cost, agree the final level with the user;
do not silently mark the original top-level goal complete. Keep default/slot-b status accurate.

### 5. Cut Mesa's per-draw CPU cost

**Partial, first optimization installed 2026-10-24.** Active-sampler gating avoids
texture barriers for inactive bindings while preserving required feedback barriers.
Implementation `8877ff1`, Mesa CI `40053566696`, default on the phone. Matched
production comparisons: swap arrivals 31.11 -> 32.05/s home and 18.51 -> 19.51/s
Control Center (+3.0%/+5.4%); these are not confirmed displayed FPS. All seven GL
steps pass; the CA tree retains its pre-existing image-orientation mismatch.

**2026-10-29: async glFlush in mode 2** (patch 0011, [report](PERF-TASK5-ASYNC-FLUSH-20261029.md)): removes the
per-frame `tc_sync` (inline TC batch + 1.3-2 ms wait) from CA's render thread; ABBA +10 % Home, +6-12 % CC swap
arrivals; render-thread Mesa CPU only -0.4 ms/frame. Installed 2026-10-29 23:05 (bf5328c0), plain reboot verified.

**Remaining work:** use CPU sampling and opt-in draw diagnostics to split
`st_prepare_draw` / `st_validate_state` atoms, `fd5_emit_state` / `fd5_program_emit`,
and remaining batch creation/finalization. Confirm redundant state or avoidable
allocation/dependency work before optimizing it. Preserve the installed active-sampler
fix, resource/fence lifetimes and scanout protections. Warm shader-program hits are
100%; first-use compilation is a separate cold path. Pipelining remains task 16.

Use the installed library as baseline, matched warmed home/Control Center repeats
with diagnostics off for timing, and separate CPU sampling. Elapsed stage timers
include blocking/descheduling and overlap; they are not removable ms/frame.

**Done for subsequent work:** reduce a measured CPU cost, demonstrate a matched
improvement without rendering/synchronization regressions, install by default and
verify a plain reboot. Keep task 5 open until its remaining scope is closed with
the user. Evidence: [baseline](PERF-BASELINE-20261024.md),
[diagnostic report](PERF-TASK5-DIAGNOSTICS-20261024.md), and the current handoff.

### 6. Make 8 cores beat 4 (j0052 tuning)

**Now.** j0052 (`xnu/patches/j0052-jasmine-clpc-standin.patch`, `sweetclpc=`) keeps UI QoS on Gold and moves
DF/UT/BG to Silver: background load on Gold fell from 10.7 s to 0.6 s per 10 s. But scripted 8-core rounds still
take 96-128 ms per frame, against 81 ms on 4 Gold cores (`jasmine/GPU.md`, the j0052 section). Find what still
costs on 8 cores: CA's frame thread or Mesa on Silver, cross-cluster IPIs, or the whole-cache flush reaching
Silver. Use j0052's per-cluster stats and the j0057 profile.

**Baseline note (2026-10-24):** those timings predate tasks 4, 7 and the first task-5 fix;
repeat the 4/8-core comparison on the installed software before attributing the remaining gap.

**2026-10-26 repeat:** [current matched baseline](PERF-CPU-BASELINE-20261026.md)
has two settled captures each at Gold1747/Silver1382/GPU588/DDR1804. The old
twofold regression is absent, but no clear eight-core gain is established. The
sampled CA render thread stayed entirely on Gold. Continue with task2 scaling
and thermal work; no broad scheduler change or new default is justified yet.

**Done when:** 8 cores are at least as fast as `cpus=4` in 2+2 scripted rounds, and the 8-core image becomes the
default.

### 10. Load-based DDR governor, ceiling 1804 MHz, on by default

**Why.** The user wants every optimization on. 1804 MHz gives the CPU 14 % lower memory latency (320 -> 275 ns),
faster writes and copies, and halves the GPU's RAM-starved time (task 9, round j64a). The UI frame did not measurably
gain, but other work (app launch, decompression, anything memory-heavy) may. Fixed 1804 holds the DDR and, after
j0064's handoff, every RPM bus at maximum even when idle. Stock Android scales instead, and so should we: full rate
while busy, lower while idle.

**Since 2026-10-25 22:57 the images vote a fixed 1804 MHz** (`tools/g2/mkimg.sh` `sweetddr=1804`, slot b rebuilt):
the GPU became the limit and is memory-bound ([PERF-GPU-TIME-20261025.md](PERF-GPU-TIME-20261025.md): Home B
37.5 -> 32.9 ms, Control Center 53 -> 41 ms). What remains here is the governor, for idle power.

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

### 11. GPU power management: hardware clock gating, idle power-down, load-based clock

**Now.** `bsd/dev/sweet_gpu.c` powers the Adreno 512 up once at boot (GFX head switch, GDSCs, clocks, j0018-j0020) and
never down again except on a failure. `a5xx_hw_init` runs **without hardware clock gating** (HWCG), so every GPU
block keeps its clock running whether it works or not. The core clock is fixed (`gpumhz=`, 588 MHz by default since 2026-10-24; j0060
added every stock level up to this chip's 647 MHz and the live `gpu clk MHZ`). Historical j64a counters at 266 MHz showed ~8-25% busy during UI motion. The later baseline at
588 MHz measured ~34-46% busy during home/Control Center motion; collect a current
idle/moving baseline before setting policy.

**How** (msm-4.4 kgsl, GPL code may be adapted closely with credit):

1. **HWCG**: `adreno_a5xx.c` `a5xx_hwcg_set()` with the A512 register table (`a512_hwcg_regs`, line ~1140) and
   `RBBM_CLOCK_CNTL` as `a5xx_start` sets it. Cheapest, no policy, likely the biggest idle win.
2. **Idle power-down**: kgsl's idle timer (`kgsl_pwrctrl.c`, `idle_timeout`, ~80 ms by default): when no job is
   pending, drop to NAP (core clock off) and later SLUMBER (clocks off, GX GDSC off, CX vote down); wake on the next
   submit (SweetGPU's submit path). Save and restore what a power-down loses (the CP state, SMMU programming, ring
   pointers: check what `gpu_power_on` sets up and what j0026's VM needs).
3. **DCVS**: a load governor over the j0060 levels (160-647 MHz) from the busy counter (j0064's
   `sweet_gpu_bus_counters`), as kgsl's `msm-adreno-tz` does: up fast on busy, down after a few idle samples. The
   GPU clock barely changes the frame (task 3: 2.2x clock = -15 % GPU wait), so lean low. Task 14 tracks the unresolved selector-2 buffer-free freeze at 588/647 MHz;
   the separate MAC-related boot-logo stall is fixed. Validate idle/wake/clock transitions against it.

**Test (as few builds as possible: put 1-3 behind boot-args in one build).** Same uibench rounds with each part
on/off; Mesa CPU time per flush (`tools/g2/ddrcost.py`) and the GPU wait must not get worse; held draws / flicker
unchanged; idle power (task list note) and TSENS lower; no GPU fault or hang over 10 minutes.

**Done when:** HWCG on, idle power-down on, DCVS on, all by default; UI cost unchanged within noise; idle and moving
power measured lower than today; 10 minutes without a GPU fault.

### 12. CPU idle power: power collapse instead of WFI, unused cores off

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

### 13. Thermal limits: TSENS-driven caps on CPU and GPU clocks

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

### 16. Pipeline rendering and presentation using surface completion fences

**Plan and tracker (2026-10-25): [PERF-TASK16-PLAN.md](PERF-TASK16-PLAN.md).** Agents
take steps from its tracker. Key findings there: with the threaded context a plain
`glFlush` would let the kernel scan a frame whose last submit has not arrived; with
two swap surfaces SwapWait must mean "a later flip was programmed", which may limit
overlap (research step S2); the present path spins on CTL_FLUSH (step S5 is worth
doing on its own). The text below is the original task statement.

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

**Measurement dependency: task 18.** Use its linked CPU/GPU/swap/latch timeline to
identify the critical path and available overlap before implementing pipelining; keep
panel waits distinct from GPU execution. The [first pass](PERF-BASELINE-20261024.md)
found explicit GPU-fence sleeping around 5-6% of the home capture and 1% in Control
Center; submission waits add more but include other causes. These are not removable
frame-time estimates. Run task 5 first and re-evaluate overlap after CPU cost changes.
Shared measurement tooling belongs to task 18; task 16 owns queued presentation and
fence/surface-lifetime changes. Do not infer displayed FPS from GL flushes.

**Done when:** matched home/Control Center runs show shorter measured presentation
intervals or lower end-to-end latency, bounded queue depth and correct fence/surface
lifetime; no new corruption, tearing, flicker, held-surface writes or hangs in a sustained
UI run; the result is on by default on the phone, with the baseline and result in GPU.md.

### 17. Persistent shader cache

**Type: performance improvement; feasibility and benefit not yet validated.** CI builds
Mesa with `-Dshader-cache=disabled` (`.github/workflows/xnu.yml`). The earlier
[baseline](PERF-BASELINE-20261024.md) captured about 276 ms of shader-worker waiting
on the first measured Spotlight opening, absent in the repeat. This was not guaranteed
to be a cold boot. Warm program-cache hits are already 100%; target first-use/reboot
hitches, not steady-state shader lookup or a promised scrolling-FPS gain.

**Approach:**

1. Check the exact Mesa version's disk-cache support on this Darwin backend, required
   file/locking/hash facilities and a writable cache location for backboardd. Establish
   whether it caches the shader work seen in the profile; a build flag alone proves nothing.
2. Enable a separate test build with proper cache keys/invalidation for GPU, shader,
   compiler version and options. Check successful writes, subsequent reads and bounded
   storage use. Keep disabled-cache comparisons available; respect root-change rules.
3. Compare repeated first-use workloads with an empty cache, populated cache and after
   reboot, with identical software, clocks and settling. Separate shader-worker wait
   from filesystem/cache I/O and other startup waits (task 21). Use task 18's displayed
   frame metrics as they become available; label earlier proxies accurately.

**Done when:** the cache demonstrably persists and hits after reboot, matched repeats
show fewer relevant first-use stalls without new rendering/invalidation regressions,
and the validated configuration is on by default on the phone. If support or benefit
is absent, record the result and revisit scope rather than claiming an improvement.
No kernel patch reserved; likely Mesa/build configuration, with userland path setup if needed.

## Bug-fix task details

### 8. Fix the pmap 32-bit page-number shift (correctness)

**Now.** `osfmk/arm/pmap/pmap.c` `pmap_sync_page_attributes_phys` does
`flush_dcache((vm_offset_t)(pp << PAGE_SHIFT), ...)` on a 32-bit `ppnum_t`, so pages above 4 GiB lose bit 32. All
of jasmine's RAM is above 4 GiB. This caused the j0029/j0030 panic `phystokv_range: illegal PA 0x7c994000`
(really 0x1_7c994000) when a write-combined IOBufferMemoryDescriptor was created. Found by ios-flame
(github.com/NWylynko/ios-flame, METAL-NEXT.md section 4). Fix with `ptoa(pp)`, look for other `<< PAGE_SHIFT` on a
`ppnum_t` in `pmap.c` / `caches.c`, and test `sweetgpu_wc=1` (write-combined IOBufferMemoryDescriptor buffers)
without the pool (`sweetgpu_pool=0`).

**Done when:** the `sweetgpu_wc=1 sweetgpu_pool=0` boot no longer panics and the UI renders; the default (pool)
path is unchanged.

### 14. Fix the SweetGPU buffer-free freeze

**Partial, still open.** Two different startup symptoms were initially grouped together.
GPU clock correlation is an observation, not proof of a GPU-clock fault.

**Open: lock-screen freeze (j60b at 647 MHz; t4d2 at 588 MHz).** CoreAnimation's display thread
stays inside SweetGPU selector 2 (buffer free) for minutes:
`darwin_bo_close_handle` -> `IOConnectCallScalarMethod` -> `SweetGPUBuffer::free` /
`sweet_gpu_vm_unmap`. Mesa's global `table_lock` is held by its caller, stopping other buffer
work. GPU jobs are all complete and the GPU is idle. Exact symbolication of 16 return
addresses per binary located this call; this is not a Mesa user-space loop.

The initial lock-order-inversion theory was **not supported** by the code audit:
no reverse lock edge or unbalanced lock exit was found. A lock in last-reference destruction
(pool/surface/IOMemoryDescriptor/VM paths) or an MMIO access wedged inside SMMU unmap remain
possibilities, not diagnoses. Software poll timeouts cannot catch a hung MMIO transaction.
`gpu state` takes neither `fLock` nor `gpu_lock`, so completed jobs do not establish lock health.

**Next action on a freeze, before reboot:**
`prof.py fetch logs/prof-NAME --secs 3 --census 200000 --tasks backboardd,SpringBoard,all`,
then `prof.py stuck` in WSL with the exact kernel/library symbols. j0069's full census records
threads even if they have slept for minutes; j0069b adds wait chains and `prof peek`.
Kernel CI: `40026354719` (j69), `40040874776` (j69b). Capture between gesture plays:
profiler fetch and uibench compete for the command port. Identify the blocked kernel operation
before changing locking; do not substitute an arbitrary timeout for a root-cause fix.

**Fixed: MAC-related boot-logo stall, 2026-10-24 02:45.** The j69b-f1 boot recovered after
~14 minutes, disproving the earlier lsd deadlock theory. A database scan asked MobileGestalt
for UniqueDeviceID per built-in bundle; missing Wi-Fi MAC data caused a 5-second IOKit wait
and NULL result per lookup (173 bundles, about 14.4 minutes). `tools/mkadt.py` now supplies
synthetic Wi-Fi/Bluetooth MACs in `/chosen`, as iBoot does. No iOS-root change was needed.
12/12 test boots at 588 MHz were clean (t14n, drawing after 44-88 seconds) and the matching
wait disappeared. The mechanism, rather than twelve boots alone, supports the fix.
Installed in rebuilt `shim/out/shim-boot-j69b-slotb.img` at 02:45;
`logs/netlog-j69m-slotb.txt`: measured 587 MHz, self-test PASS, UI drawn, no panic.
The latest documented slot-b kernel is now j0070; GPU default remains 588 MHz.

**Corrections and unresolved observations:**
- Task 15's later investigation found the persisted LaunchServices store in another container;
  the earlier "lsd never saves" explanation is withdrawn. What selected the per-bundle scan
  was not established by the MAC fix.
- The t7c `_LSDatabaseClean` / `dispatch_sync` variant has no final diagnosis. Its
  MobileGestaltHelper also showed a separate 5-second syscfg fallback wait; the MAC fix
  does not prove those waits fixed. See the historical evidence in [NOTES.md](NOTES.md).
- Shutdown hangs at HFS/UFS root unmount are a distinct issue, not successful reproductions
  of this freeze. A missing fastboot device after shutdown is "no boot", not a frozen UI.
- The audit also noted ignored SMMU poll timeouts, unbudgeted RPM receive draining,
  a selector-6 lookup/free race and ignored backend submit errors. None was demonstrated
  to cause this freeze. Investigation artifacts are ignored under `research/t14/`;
  logs/censuses use prefixes `j60b`, `t4d2`, `t14*`, `t7c` and `j69b-f1`.

**Done when:** the selector-2 freeze has an identified cause and validated fix; at least
10 consecutive startup/gesture boots at the chosen default are clean, plus a sustained UI run;
the fix is on by default on slot b and documented in GPU.md. Clean boots of the MAC fix
alone do not close the buffer-free bug. Preserve current 588 MHz defaults unless the user
agrees a change.

## Diagnostic task details

### 18. Displayed-frame and input-latency benchmarks

**Type: diagnostics.** Existing 100-GL-flush averages and swap arrivals do not establish
distinct displayed FPS, slow-frame percentiles or touch-to-display latency. The old
sampled-present detector stopped working when present became microseconds long.

**Approach, in stages:**

1. Retain existing reproducible home/Control Center workloads and matched CPU/elapsed
   comparisons. Record kernel/library identity, clocks, core count, temperatures and
   startup/warmup state. Keep cold/warm and home/blur-heavy workloads separate.
2. Correlate monotonic timestamps and surface/swap/fence IDs across CPU rendering,
   GPU submission/completion, presentation queueing and actual observed display latch.
   Distinguish attempted/dropped/replaced swaps, repeats and newly latched surfaces;
   validate the latch signal rather than assuming a timer or register write is scanout.
3. Report displayed update intervals, median/p95/p99, stalls and missed refresh
   opportunities against the measured refresh period. Define which intervals are active
   animation; do not mix scripted rests into motion statistics. Measure collection overhead.
4. Correlate injected input receipt with the first causally responding latched update.
   Distinguish this software latency from physical touch-to-photon latency; document
   sensor/input and panel scanout components not measured by the software trace.

**Done when:** reusable collection/analysis commands and a baseline report reproduce
the above metrics on matched runs, explain event loss/clock alignment/measurement limits,
and quantify overhead. Deliver the stage-2 timeline before task 16 implementation;
full input instrumentation need not delay the first task-5 improvement. This task
establishes evidence, not an optimized renderer. Do not duplicate the shared timeline in task 16.

### 19. Profile SpringBoard's CPU work

**Type: diagnostics.** The earlier [baseline](PERF-BASELINE-20261024.md) found
SpringBoard's main thread at 711-743 ms/s during home swipes, 428-473 during Control
Center. High CPU use alone does not prove it delays the display critical path.

**Approach:** capture symbolized current-baseline samples and runnable/waiting state
through matched home and Control Center motion. Split layout/animation preparation,
transaction production, IPC, allocations and background callbacks. Correlate production
with task 18's render/latch events to distinguish necessary work from repeated work
or blocking that starves rendering. Avoid disabling visual effects as an assumed solution.

**Done when:** a reproducible report quantifies the main costs and their relationship
to visible stalls, with either a specific justified optimization/bug-fix proposal or
evidence that another path should take priority. No speed gain is required to close
the diagnostic task; do not bundle an unmeasured broad SpringBoard rewrite into it.

### 20. Investigate memory and cache growth

**Type: diagnostics; may lead to bug fixes or performance improvements.** The j0070
Wallpaper freeze showed repeated poster/asset crashes, a swap-file error and large
cache-maintenance totals. Memory exhaustion is a hypothesis, not a demonstrated leak.
Cumulative maintained bytes are not necessarily resident or retained memory.

**Approach:**

1. Establish idle and moving memory baselines, then repeat bounded app transitions,
   home/Control Center gestures and, with normal hang precautions, wallpaper activity.
   Record actual resident/wired/free memory, process footprints, GPU buffer/surface
   counts and bytes, cache sizes, allocation latency/failures and memory-pressure events.
2. Compare high-water marks and post-idle recovery; distinguish bounded cache warming,
   still-in-flight/scanout surfaces, leaks and crash/respawn churn. Read unified-log
   exception/pressure messages and attribute growth before imposing a cache budget.
3. If growth or allocation stalls are proven, scope a targeted lifetime/eviction/error
   fix. Preserve fence and scanout retention; do not free live surfaces to reduce a counter.

**Done when:** repeatable before/during/after evidence identifies or rules out memory
pressure for the reproduced slowdown, localizes any unbounded growth, and proposes a
specific next action. The separate Wallpaper crash need not be repaired to complete
the measurement report; observed crash causes and pressure remain distinct findings.

### 21. Profile cold-start, boot and storage waits

**Type: diagnostics; may lead to bug fixes or performance improvements.** Steady motion
does not cover boot/app-launch latency. Task 14 documented five-second MobileGestalt
syscfg fallback waits; these are a lead, not proof of every slow launch. Task 15's
LaunchServices-persistence premise was disproved and must not be reused.

**Approach:** timestamp boot to first usable UI and representative app launches, with
explicit cold/warm definitions and repeats. Separate actual storage I/O/metadata waits,
CPU work, shader compilation (task 17), IPC service availability and IOKit timeouts.
Use kernel/user stacks and unified logs to attribute long waits; distinguish normal
initialization, unavailable-hardware retry behavior and filesystem defects. Compare
read-only root/ADT facts before proposing root changes; preserve existing permission rules.
Post-boot accessoryupdater/trustd CPU was closed as normal behavior (task 22); it still
competes with first-use UI work for the first minutes after a boot.

**Done when:** a report ranks measured boot/launch delays by cause and reproducibility,
with one scoped highest-value next action or evidence to deprioritize the path. No
storage rewrite, fabricated identity data or indiscriminate cache prewarming is implied.

## Completed task details

### 1. Move the display scale off the CPU — done

**Done 2026-10-23 01:55, j0058, default on phone.** VIG0's QSEED3 scaler fits the frame;
GPU-pool surfaces scan out in place, with present taking 7-40 us. `composeFit` remains a
multi-layer fallback. Honest SwapWait completion and a GPU wait for the latch prevent
premature surface reuse. Round j58d: 48 held draws versus 1662 without the latch wait;
the user saw no flicker and smooth motion. Later baseline captures used the MDP for all
600 recorded frames, with zero CPU display copies.

**Validation limit:** the original same-day before/after profile and frame-time comparison
were not captured; do not treat the historical 8.8 ms estimate as a current measured gain.
Keep scanout/SwapWait protections in later work. Evidence: [GPU.md](GPU.md), "j0058",
and [current baseline](PERF-BASELINE-20261024.md).

### 4. Make Mesa's buffer caches hit — done

**Done 2026-10-23 07:40, installed and plain-slot-b verified.** Darwin sub-allocation heaps,
buffer-cache matching ignoring hint bits, and an IB-address fix (`047332e`) reduced
buffer creates from 2.6 to 0.1-0.35 per frame and create/map/free profile share from
17.8% to about 6%. Historical Mesa CPU cost fell from 25.9 to 22-23 ms/frame;
12-minute runs showed flat SweetGPU handles. At GPU 266 MHz the saving reappeared as
GPU wait, without visibly faster frames; task 16 investigates overlap with correct fencing.

Mesa CI `39903986273`, production commit `2fc0a87`, boot log `logs/netlog-t4slotb.txt`.
Task 5's subsequently installed library retains this fix. Large blur-surface reallocations
were still present; counters remain in `tools/g2/cachesum.py`. Evidence:
[GPU.md](GPU.md), "Mesa buffer caches".

### 7. Stop the XPC retry loops — done

**Done 2026-10-24 01:12, installed in the phone root and reproduced by
`tools/sweet-root-tweaks.py`.** mediaserverd's BTAudioHALPlugin retried bluetoothd's removed
service; vmd retried CoreTelephony without CommCenter. The HAL plugin was moved to
`HAL.disabled/` and the vmd launchd-cache job removed. launchd/logd had been servicing
their retries. Idle daemon load fell from 2.16 cores to ~0.003, TSENS about 8 C lower:
launchd 966 -> 1.7 ms/s, mediaserverd 412 -> 1.3, logd 139 -> 0.3, vmd gone.

Verified at idle again after the MAC fix. **Validation still missing:** isolated moving-frame
gain/CA runnable-wait comparison and the user's Settings/sounds check. Small remaining
bluetoothd/nanotimekitcompaniond respawns are not proof the original two-core storm persists.
Evidence: [GPU.md](GPU.md), "Task 7"; boot `logs/netlog-t7b-slotb.txt`; backups in `research/t7/`.

### 9. DDR clock vote through the RPM — experiment complete

**Result 2026-10-23 05:10, j0064.** RPM clock handoff/scaling and BIMC votes work.
Votes 768/1017/1296/1804 MHz read back 766/1016/1294/1804; the debug-mux counter is
half the DDR rate. One boot/seven plays: GL CPU cost per flush 31.1 ms at 768,
24.2 at 1017, 18.6-20.0 at 1296, 18.9-19.5 at 1804; GPU wait was flat.
No measured UI improvement from raising the bootloader's 1296 rate to 1804.

Default remains ~1296; the vote/tooling is available, **fixed 1804 is not an installed
performance improvement**. Lower memory latency/faster copies motivate task 10's governor.
**Outstanding validation:** original full 10-minute 1804 soak (~8 minutes tested without hang).
The experiment's result does not establish memory can never limit a later workload.
Tools: `ddr state|MHZ|bench|bw`, raw `rpm`, CPU bwmon/GPU VBIF, `ddrround.sh`, `ddrsum.py`,
`ddrcost.py`. The later baseline excludes implausible CPU-bandwidth values; do not rely on
uncalibrated counters for governor tuning. Evidence: [GPU.md](GPU.md), "j0064".

## Closed investigation details

### 15. LaunchServices store persistence — closed, premise disproved

**Closed 2026-10-24 05:57.** The earlier search inspected another data container and
incorrectly concluded lsd never saved its store. The wallpaper/extension investigation
found the persisted database under
`/private/var/mobile/Containers/Data/InternalDaemon/D7413A5E-.../Library/Caches`.
Do not change ownership, protection classes or kernel file operations based on the old premise.

j0070 publishes the missing AppleMobileFileIntegrity service (CI `40059091430`);
after one entitled `sweet_extq --rebuild`, registered plugins increased from 1 to 413
and persisted after reboot at 05:57. This fixed extension registration, not database
persistence. Slot b updated at 05:58. Fresh-root seeding with j0070 is not yet tested.
Full evidence and the separate open Wallpaper freeze: [NOTES.md](NOTES.md), top handoff.
The syscfg fallback waits and task 14's selector-2 freeze were not resolved by this finding.

### 22. Post-boot accessory sync CPU — closed, normal behavior

**Closed 2026-10-25.** In all three 2026-10-25 framebench captures (started 2.5-4 minutes
after boot) accessoryupdater and trustd used about 0.8 of the 4 Gold cores during UI motion.
Stacks (`research/t5tc/daemons-threaded2.txt`): accessoryupdater's
`UARPiCloudManager handleRemoteFetchRequestSyncForCHIPAccessoriesMetadata` fetches
Matter/CHIP accessory firmware metadata from CloudKit and evaluates a certificate per
record (`SecTrustEvaluateWithError`); each evaluation is an XPC call to trustd, which
spends the time in EC signature checks (`ccec_verify`). An idle sample 24 minutes after
boot (`research/t22/at-boot-plus`, 07:59:57) showed neither process busy.

This is ordinary post-boot work that ends by itself, not a cause of slow frames once
the phone has settled. Not investigated: the exact end time, and whether a stock iPhone
also redoes the full sync on every boot. No change made. What remains is the benchmark
check under "Measuring": sample the two processes and start only once they are idle.
