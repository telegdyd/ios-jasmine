# Tasks 23-25: cut the GPU's memory traffic

Opened 2026-10-25 22:40 from the GPU timestamp measurements in
[PERF-GPU-TIME-20261025.md](PERF-GPU-TIME-20261025.md) (read that first: numbers, rounds,
logs). Registered in [PERF-TASKS.md](PERF-TASKS.md). Ground rules: PERF-TASKS "For every
agent" (phone lock, flash only `boot_b`, done = on by default on the phone, minimal test
rounds with the user's eyes for anything visible).

## The problem in one paragraph

During motion the Adreno 512 is 93-98% busy and **65% of its busy cycles wait for RAM**
(`ddr bw` while swiping: busy 552 Mcyc/s, RAM-starved 362 Mcyc/s). It moves ~6 GB/s, so a
~40 ms Home frame (DDR 1296) is ~240 MB of DRAM traffic, about 22 full-screen layers.
Three things multiply it: every batch renders in **sysmem** (blending reads and writes
the framebuffer in DRAM), CoreAnimation draws at **1125x2436** (iPhone X) instead of the
panel's 1080x2160, and a frame is cut into **~30 batches (Home) / ~87 (Control Center)**,
which is what stops GMEM (on-chip tiles) from paying. Control Center adds **full-resolution
blur passes** of 6-12 ms each. Shaders are short (5-87 instructions); the time is bytes.

DDR 1804 (shipped 2026-10-25 as the default, task 10) cut Home B 37.5 -> 32.9 ms and
Control Center 53 -> 41 ms; at 1804 Home is still GPU-bound (~32 ms of GPU per frame) and
Control Center partly CPU-bound (43 ms frames on 35 ms of GPU). These tasks go after the
bytes themselves.

| # | Task | Expected gain | Effort | Order |
| --- | --- | --- | --- | --- |
| 23 | Control Center blur at reduced resolution | CC GPU ~-10 ms/frame (guess from the pass times) | Medium | 1st: small, contained |
| 24 | Fewer batches per frame, then GMEM for the big ones | Home GPU 32 -> ~15-20 ms/frame (estimate) | High | 2nd: the big lever |
| 25 | Render at (or nearer) the panel resolution | ~20% of all pixel work | Investigation | Last; may be infeasible |

## Measuring (all three tasks)

Tools already in Mesa and on CI (both **off by default**; production lib unaffected):

- `SWEETCA_GPUPROF=1` (patch `mesa/patches/0005-freedreno-gpu-batch-timing.patch`,
  `freedreno_gmem.c`): RB_DONE_TS around every batch; per 100 flushes the log gets
  `sweetca: gpuprof:` lines: GPU busy, gaps, totals by mode (sysmem/gmem/nondraw) x size
  (full >= 2 Mpx, large >= 0.25 Mpx, small), and the 12 slowest batches with framebuffer,
  draws, bins, clear/restore/resolve masks.
- `SWEETCA_GPUPROF=2` (also patch `0006-freedreno-a5xx-gpu-draw-timing.patch`,
  `a5xx/fd5_draw.c`): per draw, `sweetca: gpudraw:` lines: the 10 costliest fragment
  shaders (draws, total, max, and the slowest draw's instruction count, waves, framebuffer,
  viewport, scissor, vertex count, blend, first two textures with size, format, levels,
  mip filter, tile mode, "(the target)" when it samples its own render target) and the 10
  slowest draws. **Sysmem batches only** (GMEM replays the draw ring per bin: stamps then
  cover the last bin). The stamps drain the pipeline per draw: times are upper bounds.
- `SWEETCA_DRAWPROF=1`: `sweetca: drawevent: flush-*` counts per window (barrier,
  resource-dependency, context, frame, kick, capacity): why batches end.
- `python tools/g2/gpuwin.py LOG [FIRST LAST] [--shaders]`: one line per 100-flush window
  (ms per frame, draws, batches, GPU ms per frame, flush reasons per frame), batch classes
  per frame, `--shaders` adds the shader table per frame.
- `ddr bw 4000 bg` on the command port, then gestures: GPU busy / VBIF beats / RAM-starved
  counters in the log (`SWEET DDR: ddr bw at ...`). VBIF beats x 32 bytes = GPU traffic.

How the measurement rounds were run (scratchpad scripts of the 2026-10-25 session; copy the
pattern): build the test library on CI (`gh workflow run xnu.yml -R telegdyd/ios-jasmine
--ref jasmine -f build=mesa`), put it on the phone under a **test name**
(`MSYS_NO_PATHCONV=1 python tools/sweet-fs.py put <dir>/mesa-ios/libsweetca.dylib
/usr/local/bin/libsweetca-<tag>.dylib --mode 755`), make a test image whose `sweetenv`
loads it with the env above (any image's cmdline with `sweetenv=backboardd:DYLD_INSERT_LIBRARIES=/usr/local/bin/libsweetca-<tag>.dylib,SWEETCA_GPUPROF=2,...`;
`sweetenv` takes comma-separated VAR=VAL, 512 bytes max), `fastboot boot` it, wait for the
post-boot accessory sync to end (task 22), run one standard capture
(`python tools/g2/framebench.py run --lock <private lock> --out DIR --ui-ready --kernel K --lib L`),
then `gpuwin.py` on the live log. Compare like with like: same DDR rate (1804 now), same
kernel, same pipeline mode. Env set in `sweetenv` wins over libsweetca's own `setenv(..., 0)`
defaults (e.g. `FD_MESA_DEBUG`).

Baseline to beat (DDR 1296, mode 2, gd2 round; redo at 1804 before starting):

| Frame | Draws | Batches | Flushes per frame | GPU ms per frame |
| --- | ---: | ---: | --- | ---: |
| Home | ~87 | ~29 | barrier 13.7, resource-dependency 10.0, context 4.8, frame 1 | ~40 (1296), ~32 (1804) |
| Control Center | ~193 | ~87 | barrier 36, resource-dependency 40, context 9, frame 1.3 | ~46 (1296), ~35 (1804) |

## 23. Control Center blur at reduced resolution

**Device investigation:** [results](PERF-TASK23-DEVICE-AUDIT.md). Gaussian
downsampling is observed on the phone, including 74x156/72x42 intermediates.
Full-size four-tap passes coexist with it. Do not implement a universal missing
mip/downsample fix based on the hypothesis below. Variable blur has a separate
GLES compatibility approximation; this session did not establish runtime impact.
Task remains open; no algorithm change or measured gain.

**Initial offline audit:** [findings](PERF-TASK23-AUDIT.md). The missing-mip
explanation below is unproven. Gaussian blur has explicit 2x/4x downsample
passes and ordinary GL intermediate storage. Our variable-blur shader does
deliberately bypass intermediate draws, but that does not establish a Gaussian
defect. Slowest-only GPU summaries cannot prove that all downsampling is absent.

**User scope clarification:** Control Center is the benchmark that exposed the
cost, not the scope boundary. Task 23 targets correct, efficient blur throughout
the UI and higher frame rates wherever the affected paths are used. Audit shared
Gaussian/variable-blur storage, mip and copy handling, including the existing
variable-blur workaround. Fix confirmed defects for every caller of that path;
preserve intended blur appearance. Validate Home/dock/folder and Notification
Centre as well as CC, plus available in-app cases. CC-only gains do not establish
completion. See [updated plan](PERF-TASK23-PLAN.md).

**Evidence** (gd1, `logs/netlog-t16-gd1.txt` around line 4987, CC A): offscreen passes
ping-pong between **1127x2438 and 1131x2442** buffers (the 1125x2436 frame plus a small
border): one draw of an 87-instruction shader (8 waves) took **11.88 ms**, a 63-instruction
one 5.7-6.8 ms, a 47-instruction one into 1127x2438 sampling its own target 4.3 ms. Home has
small blur passes too (284x611, 1082x1226: dock/folder backdrops, 2-3 ms each), which are
already reduced in size.

**Hypothesis to verify first.** CA's GL renderer (`GaussianBlurFilter`, `filter_backdrop`,
`capture_backdrop` in QuartzCore; the profile in GPU.md "j0055" shows them) blurs a
downsampled copy, built as mip levels or as smaller render targets. Our textures backed by
IOSurfaces have level 0 only, and libsweetca already found that for the variable blur
(`sca_vblur`, `mesa/darwin/sweetgl/sweetca.c` ~1311-1395: "CA blurs by sampling a mip chain of
a copy of the source, which a GLES surface (level 0 only) cannot hold, so the mip passes draw
nothing"). If the Gaussian blur also expects levels, it falls back to full-size passes with a
wide kernel. Check, in this order:

1. `SWEETCA_TRACE=2` (`trace_draw`, sweetca.c ~1632) on one CC open: each draw's program,
   FBO texture and size, viewport, scissor, blend, bound textures. Find the passes at
   1127x2438/1131x2442 and what feeds them.
2. QuartzCore disassembly (iPhone X cache, `~/ios-work/gl/out/qc.s` in WSL; GPU.md "Three GL
   texture functions" explains how the tables were found) around `GaussianBlurFilter` /
   `filter_backdrop`: does it call `glGenerateMipmap` (libsweetca wraps it: `w_GenerateMipmap`,
   sweetca.c ~1173, slot 681), `glTexStorage2D` with levels (`w_TexStorage2D` ~906), render
   into level > 0 (`glFramebufferTexture2D` level argument), or `glBlitFramebuffer` downscales?
   Which GL calls fail or are emulated as no-ops on our side (SWEETCA_TRACE=1 logs GL errors)?
3. Whether the 1127x2438 buffers are IOSurfaces (kernel `SweetSurface`) or plain GL textures
   (then they could have real mip levels).

**Fix options** (choose after 1-3): give the blur's textures real levels (plain GL storage
instead of an IOSurface, or a level chain beside the surface); or downsample explicitly in
libsweetca when CA's pass sequence is recognized; or, as for sca_vblur, substitute a
cheaper single pass at reduced resolution. Keep the look: the user checks it by eye.

**Done when:** no full-resolution blur pass over ~2 ms in `gpudraw` during CC; CC GPU ms per
frame and CC A/B frame medians lower at DDR 1804 than the baseline; the user confirms the CC
and notification-centre blur look the same; library installed as
`/usr/local/bin/libsweetca.dylib` (the slot b default) with the fix on by default.

## 24. Fewer batches per frame, then GMEM for the big ones

**Why GMEM, why not yet.** In sysmem a blended full-screen draw costs 3-5 ms (texture read
+ framebuffer read + write, ~33 MB). GMEM keeps blending on-chip and writes the frame once.
Round gm1 (`FD_MESA_DEBUG=nofp16`, i.e. sysmem no longer forced; `logs/netlog-t16-gm1.txt`,
`research/t16/s8/gm1/`) showed both sides: the costliest batch (12-14 draws on the 1125x2436
frame) went **22 ms -> 12-14 ms**, but **Home B got worse, 41 -> 56 ms**, because each of
the ~16 full-screen batches per frame now restores and resolves the whole 11 MB frame
(42 bins): full-screen batches averaged 3.8 ms instead of 1.8. No GPU or SMMU fault was
logged in that boot; nobody looked at the screen.

So the order is: first make a frame a few big batches, then let those go GMEM.

**Where the splits come from** (per Home frame: 13.7 barrier, 10 resource-dependency,
4.8 context, 1 frame):

- **Barriers:** libsweetca's `draw_prep` (sweetca.c ~1553-1625) calls `sgl_texture_barrier()`
  (sweetgl.c ~443, `_mesa_TextureBarrierNV`) whenever a draw samples the texture it renders
  into: CA's `gl_LastFragData` (framebuffer-fetch emulation through `fbfetch_unit`) and other
  feedback reads. freedreno's `fd_texture_barrier` (`freedreno_context.c` ~155) is a full
  `fd_context_flush`: a new batch. In sysmem a barrier only needs the written data visible to
  the texture unit (CCU flush + UCHE invalidate inside the batch), not a new batch; task 5's
  notes rank this as "keep wrapper texture barriers inside a sysmem batch"
  ([PERF-TASK5-THREADED-20261025.md](PERF-TASK5-THREADED-20261025.md), ranked fix 2; note "a5xx
  clears are GMEM blits", so cleared batches need care). A batch that reads its own target
  cannot run in GMEM on a5xx (the texture reads memory, not the tile): such batches stay
  sysmem, but the batches around them need not split.
- **Resource dependencies:** CA renders the frame, then copies part of it for a backdrop
  (shader 13: 284x611 or 1082x1226 target sampling the 1125x2436 frame), blurs, and draws the
  result back. freedreno must flush the frame's batch before the copy reads it. Inherent to
  backdrops; count which ones they are (`SWEETCA_TRACE=2`) before deciding. Reordering is on
  (`screen->reorder`, the darwin device version is new enough), so plain render-target
  switches do not split.
- **Context flushes** (4.8/frame Home, 9 CC): find the callers (glFlush, fence syncs, the
  per-32-draw kick `kick_after_draw`/`sgl_kick` sweetca.c ~1653-1690 and `SWEETCA_KICK`,
  IOSurface locks, `copy_refresh`). Each one ends the batch.

**Then GMEM per batch.** Remove the forced sysmem (`setenv("FD_MESA_DEBUG", "sysmem,nofp16", 0)`
in sweetca.c ~2210; keep `nofp16`) and let freedreno choose per batch. On a5xx the autotune
has no history (no `gmem_reason_mask`), so `fallback_use_bypass` (`freedreno_autotune.c` ~137)
picks GMEM for any batch that is cleared, blends, or has more than 5 draws. That sent the
many small blended batches to GMEM in gm1. A better rule needs the area the batch touches:
GMEM pays when (blended full-screen draws x 8 bytes x pixels) clearly exceeds a restore plus
a resolve of the bins touched. Options: compute each draw's bounding box in libsweetca from
CA's client vertex arrays and keep a tight scissor (freedreno's GMEM key uses
`batch->max_scissor`: only touched bins are restored/resolved), or a per-batch heuristic on
draw count and blend. Measure with `SWEETCA_GPUPROF=1` (per-batch GMEM times are exact;
per-draw ones are not in GMEM).

**IOSurface overrun safety.** G2 forced sysmem because on the Pixel GMEM resolves overran
unpadded IOSurfaces and faulted the GPU on the display surface. Here every GPU buffer is
followed by `GPU_VA_PAD` = 128 KB of VA mapped to a shared scratch page, and SMMU faults
terminate (no stall), so an overrun lands in scratch (`bsd/dev/sweet_gpu.c` comments near
`GPU_VA_PAD`, SMMU CB0 `SCTLR`). freedreno clips tiles to the framebuffer (`freedreno_gmem.c`
"clip bin width/height"), but check what the resolve can write past the last row: 2436 rows is
not a multiple of the bin alignment, and 28 rows x a 4.5 KB stride is ~127 KB, right at the
pad. Confirm no `FSR` fault lines and no corrupted bottom rows (user's eyes) over a long run;
grow the pad (kernel) if needed.

**Done when:** a Home frame has a handful of full-screen batches; GPU ms per Home frame and
Home B median clearly lower than the baseline at DDR 1804; GMEM on by default in the
installed library; no faults, no visual regressions (user checks Home, CC, notification
centre, an app); task 16's mode-2 paths still pass if mode 2 has shipped by then.

## 25. Render at (or nearer) the panel resolution

**Evidence.** CA renders the iPhone X's 1125x2436 (2.74 Mpx); the panel is 1080x2160 and the
image is fitted to 997x2160 (`SWEET FB: AppleCLCD 1080x2160 stride 4320 ... presented as
1125x2436`; GPU.md "j0055": the old CPU `composeFit` was 1125x2436 -> 997x2160; task 1 moved
the scaling off the CPU). So ~27% of all pixel work is never shown at full detail.

**Investigation only.** The size comes from the device identity the userland sees (the
AppleCLCD / IOMobileFramebuffer reported size and MobileGestalt's main-screen size/scale);
iOS 16 lays out for known iPhone sizes, and an unknown one may break SpringBoard or apps.
Find what decides CA's render size, whether a known smaller iPhone geometry with the same
aspect exists (none is 18:9; compare 19.5:9 sizes at lower scale), and what it would cost in
layout/visuals. Report options to the user before changing anything in the root.

**Done when:** a written answer (feasible or not, what it would change, risks); an
implementation only after the user picks an option.

## Related

- DDR 1804 default and a load-following governor: PERF-TASKS task 10 (fixed 1804 shipped
  2026-10-25; the governor remains for power).
- CPU side of Control Center (43 ms frames on 35 ms of GPU at 1804): task 5.
- Presentation pipelining (mode 2): task 16, [PERF-TASK16-PLAN.md](PERF-TASK16-PLAN.md).
