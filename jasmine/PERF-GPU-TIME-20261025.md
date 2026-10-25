# Where the GPU's time goes (2026-10-25 21:30 to 22:20)

**Status: measured, nothing changed by default yet.** GPU timestamps per batch and per
draw (Mesa patches 0005/0006) on the task 16 mode-2 boot (`t16b2` kernel j0101,
`SWEETCA_PIPELINE=2`, 4 Gold at 1747, GPU 588 MHz), framebench standard gestures.
Rounds `gp1` (per batch), `gm1` (GMEM allowed), `gd1`/`gd2` (per draw, flush reasons),
`gd2-1804` (same boot, DDR voted to 1804). Captures in `research/t16/s8/<tag>/`, logs in
`logs/netlog-t16-<tag>.txt`; `tools/g2/gpuwin.py LOG [FIRST LAST] [--shaders]` prints the
per-frame summary of each 100-flush window.

## Answer

**The GPU is memory-bound, and the frame moves far too many bytes.** During motion the
GPU is 93-98% busy (timestamps) and **65% of its busy cycles are RAM-starved** (`ddr bw`
counters while swiping Home: busy 552 Mcyc/s, RAM-starved 362 Mcyc/s, VBIF 171 M beats/s
at DDR 1296, 212 M beats/s at 1804). It reaches about 6 GB/s, so a Home frame of ~40 ms
of GPU is ~240 MB of DRAM traffic: about 22 full-screen layers' worth.

Why so many bytes:

1. **Every batch renders in sysmem** (`FD_MESA_DEBUG=sysmem`, libsweetca, set since G2
   because GMEM resolves overran unpadded IOSurfaces on the Pixel). Each blended
   full-screen draw reads the texture, reads the framebuffer and writes it back in DRAM:
   ~33 MB, 3-5 ms. GMEM (tiling) exists to keep that blending on-chip.
2. **CA draws at 1125x2436** (iPhone X), 17.5% more pixels than the 1080x2160 panel
   (`SWEET FB: AppleCLCD 1080x2160 ... presented as 1125x2436`).
3. **A frame is split into many batches:** Home ~87 draws in ~30 batches (per frame:
   13.7 texture barriers, 10 resource dependencies, 4.8 context flushes, 1 frame flush),
   Control Center ~193 draws in ~87 batches (36 barriers, 40 dependencies). In sysmem a
   split costs little GPU time, but it is what makes GMEM lose (below).
4. **Control Center's blur runs at full resolution:** ping-pong passes between
   1127x2438 and 1131x2442 offscreen buffers, one 87-instruction pass 11.9 ms, a
   63-instruction one 5.7-6.8 ms. CA's GL renderer blurs a downsampled mip chain; our
   GLES surfaces have level 0 only (the same limit sca_vblur works around).

   Task 23 audit correction: the measured sizes/times remain valid, but this
   causal explanation is unproven. Gaussian blur has separate-target 2x/4x
   downsampling and ordinary GL intermediate storage. Variable blur has an
   explicit approximation in our wrapper. See [audit](PERF-TASK23-AUDIT.md);
   do not infer missing downsampling from slowest-only summaries.

## Home frame at DDR 1296 (gd2, window at log line 5866: 40.8 ms per frame, GPU 39.9 ms)

| Fragment shader (per frame) | Draws | GPU ms | Slowest draw |
| --- | ---: | ---: | --- |
| 1: 10 instrs, blended, 1 texture (slowest: 1271x1823 BGRA) | 19.3 | 13.7 | 5.2 ms, full-screen viewport |
| 0: 5 instrs, opaque, small r8 texture | 13.5 | 6.5 | 2.0 ms |
| 37: 48 instrs, blended, 284x611 + 32x32 | 1.7 | 3.1 | 4.4 ms |
| 3: 14 instrs, blended, 1082x1226 | 1.9 | 2.8 | 3.3 ms |
| 13: 34 instrs, into 284x611, samples the 1125x2436 frame | 3.1 | 2.8 | 3.5 ms |
| 19: 10 instrs, into 1082x1226 | 1.0 | 2.7 | 3.3 ms |
| 7: 38 instrs, opaque, 256x1 RGBA16F + 32x32 | 1.0 | 2.0 | 2.3 ms |

Per batch (gp1, Home B): ~16 full-screen batches ~29 ms, 6 "large" ones (0.25-2 Mpx)
~11 ms, the rest small. The single costliest batch, 12-14 draws on the 1125x2436 frame,
takes **22 ms** in sysmem. The textures are linear, no mipmaps; the shaders are short:
the time is bytes, not ALU.

## Tests

| Round | Change | Home B median / p95 ms | CC A | CC B | GPU per Home frame |
| --- | --- | --- | --- | --- | --- |
| m2a (no timing) | mode 2 | 41.4 / 82.4 | 48.6 / 125.6 | 49.7 / 92.6 | ~39 (ticket estimate) |
| gp1 | batch timing | 41.1 / 68.4 | 53.4 / 85.4 | 55.0 / 94.6 | 40 |
| gm1 | **GMEM allowed** (`FD_MESA_DEBUG=nofp16`) | **55.9 / 163.9** | 94.5 / 199.7 | 86.3 / 218.3 | 59 |
| gd2 | draw timing, DDR 1296 | 37.5 / 85.1 | 53.0 / 86.6 | 53.1 / 82.5 | 40 |
| gd2-1804 | same boot, **DDR 1804** | **32.9 / 60.5** | **40.9 / 60.0** | **40.9 / 84.1** | 32 |

- **GMEM as it stands is worse:** the 22 ms batch drops to 12-14 ms (blending on-chip),
  but every one of the ~16 full-screen batches now restores and resolves the whole 11 MB
  frame (42 bins), full-screen batches average 3.8 ms instead of 1.8. No GPU or SMMU fault
  logged in that boot (not checked by eye). GMEM pays only once a frame is a few batches.
- **DDR 1804 helps now** (task 9 found no gain at 1296 -> 1804 when the frame was
  CPU-bound): GPU per Home frame 40 -> 32 ms, CC 46 -> 35 ms. Home stays GPU-bound
  (33 ms frames); CC becomes partly CPU-bound (43 ms frames on 35 ms of GPU).
- The timing itself costs little (Home B 41.1 vs 41.4 ms); the per-draw stamps drain the
  pipeline per draw, so per-draw times are upper bounds.

## What would get the big gain

1. **DDR at the stock top rate under load** (`sweetddr=1804` today; better a vote that
   follows GPU load, as kgsl's gpubw does): -12% Home, -23% CC frame time, no code.
2. **Control Center blur at reduced resolution**: the full-size ping-pong passes are
   up to ~12 ms each.
3. **Fewer, larger batches, then GMEM for the main framebuffer**: the sysmem blending
   traffic is most of a Home frame. Needs libsweetca's barrier/dependency splits cut
   (framebuffer-fetch copies, render-then-sample order) and padded IOSurface mappings
   (already 128 KB of scratch VA after every buffer).
4. Rendering at the panel's 1080x2160 would save 15% of all pixel work.

Tools: Mesa `0005-freedreno-gpu-batch-timing.patch` (`SWEETCA_GPUPROF=1`: per batch,
`sweetca: gpuprof:` lines), `0006-freedreno-a5xx-gpu-draw-timing.patch`
(`SWEETCA_GPUPROF=2`: also per draw, `sweetca: gpudraw:`), both off by default;
`SWEETCA_DRAWPROF=1` for flush reasons.
