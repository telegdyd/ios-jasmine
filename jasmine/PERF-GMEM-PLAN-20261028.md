# GMEM: render on-chip instead of through RAM (plan, 2026-10-28)

The next frame-rate lever after pipelined presentation (mode 2, installed 2026-10-28). This is
task 24 in [PERF-TASKS](PERF-TASKS.md), restated against today's measurements. Earlier task 24
documents (read for detail, not for current numbers): [plan](PERF-TASK24-PLAN.md),
[audit](PERF-TASK24-AUDIT.md), [device audit](PERF-TASK24-DEVICE-AUDIT.md),
[barrier candidate](PERF-TASK24-CANDIDATE.md), [pixel gate](PERF-TASK24-PIXEL-GATE.md).

## In one paragraph

The Adreno 512 is a tiler. It has a small on-chip memory (GMEM) and is designed to draw the
screen one tile at a time: all overlapping layers and blending of a tile happen on-chip, and the
finished tile is written to RAM once. libsweetca forces `FD_MESA_DEBUG=sysmem` instead, so every
draw reads and writes the 1125x2436 framebuffer in DRAM. DRAM is the bottleneck: the GPU's busy
cycles are 56-66% RAM-starved, and frame rate follows the DDR clock, not the GPU or CPU clock
([bottleneck report](PERF-BOTTLENECK-20261028.md)). With mode 2 installed, Home's GPU time
(~27 ms/frame) is now essentially its frame time, so cutting GPU bytes converts directly into
frame rate on every screen.

## Why it is not a switch

GMEM was allowed once (2026-10-25, round gm1, `FD_MESA_DEBUG=nofp16`) and Home got worse,
41 -> 56 ms per frame ([GPU time report](PERF-GPU-TIME-20261025.md)). In GMEM mode every
render pass loads the target into the tiles (restore) and writes it back (resolve): about 22 MB
for a full-screen 1125x2436 target. That only pays when a pass has enough overlapping work. A
frame today is cut into many tiny passes (same-day GPUPROF profile,
[bottleneck report](PERF-BOTTLENECK-20261028.md#where-the-gpu-time-goes-per-batch-and-per-draw-profile-same-day)):

| Per frame | Draws | Batches (full-screen) | One-draw batches | Batch ends at texture barriers |
| --- | ---: | ---: | ---: | ---: |
| Home | ~100 | 54 (45) | ~34 | 37-39 |
| Control Center | ~195 | ~103 (64) | ~69 | 54-56 |

The barriers come from draws that sample their own render target (labels, vibrancy). libsweetca
calls `glTextureBarrierNV` before each, and freedreno's `fd_texture_barrier` ends the batch
(`fd_context_flush`). In sysmem, a barrier only needs the color writes flushed and the texture
cache invalidated inside the command stream, not a new batch. That is what
`mesa/patches/0008-freedreno-a5xx-sysmem-barrier-experiment.patch` does (default off,
`SWEETCA_SYS_BARRIER=1`, only with forced sysmem).

A second reason sysmem was forced (G2, on the Pixel): GMEM restore/resolve overran unpadded
IOSurfaces. Jasmine's kernel maps 128 KiB of scratch VA after every buffer (j0033), which
contains an overrun but does not prove correct output. This must be re-checked before stage 3.

## Stages

1. **Make the GPU correctness gate trustworthy.** The task 24 pixel test
   (`sweetgpu_gltest`, feedback step, `mesa/darwin/sweetgl/sweetgpu_feedback_test.inc`) failed on
   2026-10-26 **with the experimental barrier disabled**: feedback -> clear -> partial-scissor
   feedback (4096/4096 pixels wrong, the clear appears not to take effect) and target revisit /
   imported alias (112/4096 stale). Either the test is wrong or the current driver/wrapper has a
   real ordering bug in those paths. Nothing can be validated until this is explained. A
   diagnostic mode (`--feedback-diagnostics`, 28 separate checks) and a pre-0008 control build
   exist (source 339bb02, Mesa CI 40252267715) but were never run on the phone. Done when: root
   cause known, any real bug fixed, the four-case acceptance matrix
   (`--sysbarrier-off/on`, each with and without `--no-tc`) passes, and the enabled cases print
   the retained-path marker.
   **DONE 2026-10-28** ([pixel gate](PERF-TASK24-PIXEL-GATE.md#2026-10-28-root-causes-found-fixed-four-case-gate-pass)):
   two real bugs, neither in the test nor in 0008. (a) In forced sysmem the a5xx fast clear
   (a GMEM BLIT event) is not ordered after earlier draws of the same batch: draw -> clear
   kept the draw's pixels; fixed by patch 0009 (u_blitter clear after draws and for depth).
   (b) Mesa's CPU reads of imported (cacheable) IOSurfaces skipped the kernel's lazy cache
   upkeep, so glReadPixels returned lines cached by an earlier read; fixed in
   `darwin_bo_cpu_prep` (IOSurface lock/unlock protocol). Commit 97c59cf, Mesa CI 40620265076:
   all four cases PASS (enabled ones print the marker), 28 diagnostics PASS, 30 repeat runs
   clean. Not installed in production. For stage 2: check whether CA hits draw -> clear in
   one batch and what the u_blitter clear costs.
2. **Fewer batches.** Turn on in-batch barriers (0008 or its successor) in a test library,
   measure batches and GPU ms per frame with `SWEETCA_GPUPROF=1,SWEETCA_DRAWPROF=1`
   (`tools/g2/gpuwin.py`) and frame rate with framebench (`tools/g2/abround.py`). Also look at the
   resource-dependency (10/frame Home, 38 CC) and context (6/10) batch ends. Expected: a frame
   in a handful of large batches; GPU time itself may move little (sysmem traffic is the same).
   **DONE 2026-10-28** ([stage 2 report](PERF-GMEM-STAGE2-20261028.md)): CA never clears after a
   draw in one batch (0009's u_blitter path unused, no live lost-clear glitch, zero cost).
   Widened rule `SWEETCA_SYS_BARRIER=2` (commit 167c44a, Mesa CI 40622879956): Home 54.6 -> 18.5
   batches/frame, CC 104 -> 54; GPU ms/frame unchanged (Home 27.6 -> 27.4, CC 32.2 -> 30.9);
   framebench unchanged within noise. Pixel gate (6 cases incl. `--sysbarrier-wide`) 24/24 PASS.
   Not installed. Stage 3 caveat: retained-barrier batches are forced sysmem, so GMEM needs
   a split at the first feedback draw or barrier-free batches (CC backdrop/blur clears).
3. **GMEM for the big batches.** Select GMEM per batch where it is cheaper than sysmem (many
   blended draws on the same target), keep sysmem for small or feedback-heavy ones. Check
   IOSurface padding/overrun safety on jasmine first. Measure as in stage 2; the user checks
   motion by eye for glitches. Install only after that.
   **PAUSED 2026-10-28 06:55** (NOTES.md handoff): patch 0010 (SWEETCA_GMEM, default off) built; v1
   sample-count rule broke large-target rendering (counting itself), v2 times each batch kind in both
   modes (CI 40638109900, 77f9316) and is not yet gated; no GMEM boot of backboardd, no measurements.
   **PAUSED again 2026-10-28 16:25:** extent check fixed to upstream's pitch rule (rows a multiple of
   64 px; CA frames have 4608-byte rows) and the full 128 KiB pad (d7db729, not yet built: macOS runner
   outage); baseline GPUPROF s3gp-base measured (Home 27.4 ms GPU/frame, CC 33.0, Settings scroll 9.8).

Each stage is its own milestone with its own measurement; stop if a stage's premise fails.

## Expected payoff and risk

Target from the 2026-10-26 plan: Home GPU ~27 -> 15-20 ms per frame. This is an aspiration
(it assumes most blending moves on-chip after stage 2), not a forecast. With mode 2 that would
put Home at roughly 45-60 fps, and it applies to every screen. The risks are visual correctness
(stale pixels, missing clears, glitches only visible in motion) and memory safety of GMEM
resolves; every stage needs the pixel gate and the user's eyes.

## Ground rules (from AGENTS.md / PERF-TASKS "For every agent")

Temporary boots and test-name libraries only (`/usr/local/bin/libsweetca-<tag>.dylib`,
`sweetgpu_gltest-<tag>`); never replace `/usr/local/bin/libsweetca.dylib` or flash without the
user's OK. Battery >= 30% before booting iOS (it brownouts near 11%); park in the r109 charging
shell when done. Use a private phone lock; the shared default lock and
`Temp/claude/phone-j0108.lock` are stale leftovers. Update NOTES.md after each milestone.
