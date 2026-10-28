# GMEM plan stage 2: fewer, larger batches (2026-10-28)

Stage 2 of [the GMEM plan](PERF-GMEM-PLAN-20261028.md). Question: with in-batch sysmem barriers
(patch 0008) a frame should become a few large batches; how many, what does it do to GPU time
and frame rate, and which batches are then GMEM candidates? **Result: batches per frame fall
2.9x (Home) / 1.9x (CC) with the widened rule; GPU ms per frame and frame rate do not move.**
Nothing installed; production library unchanged (4780fbaa, read back at the end).

## Build

Commit `167c44a`, Mesa CI **40622879956** (macos-15) PASS: libsweetca `1772b043779bd222d6a2bc4e8c5a14d2829f91beab5f27b31c0ffd0486be550f`,
sweetgpu_gltest `dd0c6707a638545061e769d899c8a0ae4d5947a5822e722de1605c3d8219b468`
(artifacts in ignored `research/t24/stage2/ci-40622879956/`). Stage 1's fixes (0009 clear order, darwin cpu_prep) plus:

- **Counters** (`SWEETCA_DRAWPROF` drawevents): forced-sysmem clears `clear-fast` /
  `clear-blit-after-draw` / `clear-blit-zs` (0009's branch), and 0008's decision
  `sysbarrier-retained` / `sysbarrier-reject-{draws,cleared,deps,fence,fb,other-batch,state}` /
  `sysbarrier-clear-split`.
- **`SWEETCA_SYS_BARRIER` is a level.** 1 = 0008 as before (1-5 draws, no clear, no deps,
  no other pending batch, RGBA8/BGRA8). **2 = widened**: any draw count, cleared batches and no
  clear split (with 0009 any clear after a draw is a u_blitter draw; a fast clear only starts a
  batch), other pending batches and batch dependencies (cross-batch order stays resource
  tracking's job, as for any draw without a barrier), any uncompressed color format. Still forced
  sysmem only, one linear level-0 2D color target, no depth/stencil, queries, streamout,
  prologue, tessellation. Marker `sysbarrier retained (...) level 2`.
- **gltest**: `--sysbarrier-wide` (level 2) and one more acceptance check: fast clear, an
  unchanged draw (blend ZERO,ONE), then seven barrier+feedback draws in one batch (exercises
  "cleared" and ">5 draws" retention).

## Quick checks (stage 1 follow-ups)

**(a) Does CoreAnimation hit draw -> clear in one batch?** No. In every GPUPROF boot (Home
swipes, CC open/close, ~2000 profiled frames each) `clear-blit-after-draw` = 0 and
`clear-blit-zs` = 0; all clears are first-in-batch fast clears (Home 4.6-4.7/frame, CC 22-24/frame).
Also 0 under level 1 and level 2, where batches are longer. So the installed library has no
lost-clear glitch from root cause (a) in these screens (observed for this workload only; other
apps/screens not covered).

**(b) Cost of 0009's u_blitter clears:** zero in normal use, because the path is never taken.
GPU ms/frame production lib vs stage-1 lib (barrier off): Home 26.5 vs 27.6, CC 33.1 vs 32.2,
i.e. within boot-to-boot variation (the stage-1 boot also had ~4 more draws/frame on Home).

## Measurements

Kernel j0110 (`xnu/out-jasmine-j0110`), all boot-args identical to installed boot_b
(`sweetfb_sleep=1 sweetfb_queue=1 sweetgpu_tickets=1`, `SWEETCA_PIPELINE=2`, GPU 588, DDR 1804,
CPU auto) minus `abmark=b`; only sweetenv differs. GPUPROF boots: `SWEETCA_GPUPROF=1,SWEETCA_DRAWPROF=1`,
`tools/g2/gpwork.py`, steady windows (first/last window of each phase dropped;
`research/t24/stage2/s2sum.py ... --trim`, `summ.sh`). Per frame:

| Home | prod lib | stage-1 lib, off (L0) | L1 (0008) | L2 (widened) |
| --- | ---: | ---: | ---: | ---: |
| draws | 97 | 101 | 101 | 102 |
| batches (full-screen) | 50.8 (41.8) | 54.6 (45.8) | **25.7** (19.1) | **18.5** (12.2) |
| 1-draw batches | 31.9 | 35.8 | 3.9 | 2.5 |
| GPU busy ms | 26.5 | 27.6 | 27.4 | 27.4 |
| ends: barrier / dependency / context / frame | 35.4 / 10.2 / 4.2 / 1 | 39.0 / 10.3 / 4.4 / 1 | 10.2 / 10.3 / 4.3 / 1 | **0** / 11.3 / 6.2 / 1 |
| barriers retained | - | 0 | 28.0 | 36.1 |
| L1 rejects: draws>5 / cleared / deps / state | | | 4.8 / 1.6 / 0.8 / 1.1 | state 1.2 |

| Control Center | prod lib | L0 | L1 | L2 |
| --- | ---: | ---: | ---: | ---: |
| draws | 192 | 198 | 193 | 191 |
| batches (full-screen) | 100.6 (67.7) | 104.2 (66.0) | **72.5** (38.7) | **54.3** (29.1) |
| 1-draw batches | 67.7 | 70.7 | 33.5 | 16.6 |
| GPU busy ms | 33.1 | 32.2 | 30.5 | 30.9 |
| ends: barrier / dependency / context / frame | 54.5 / 37.4 / 7.6 / 1.2 | 56.6 / 38.5 / 7.9 / 1.2 | 26.5 / 37.3 / 7.6 / 1.2 | 5.5 / 37.1 / 10.6 / 1.2 |
| barriers retained | - | 0 | 28.4 | 44.0 |
| L1 rejects: cleared / draws / state / deps / other batch | | | 7.0 / 4.4 / 3.7 / 2.8 / 0.8 | state 3.7 |

("state" is mostly a barrier in a batch with no draw yet, which correctly falls back.)
Per-window values are tight (gpuwin: Home L2 18-19 batches in every window, L0 53-56).

Uninstrumented frame rate (framebench via `tools/g2/abround.py`, swap arrivals/s; median/p95 ms):

| Phase | L0 run 1 | L0 run 2 | L1 | L2 run 1 | L2 run 2 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Home B | 33.69 (28.3/42.5) | 32.93 (28.3/44.3) | 33.21 (28.0/47.7) | 33.81 (27.7/44.4) | 33.45 (28.4/43.0) |
| Control A | 25.12 (38.8/61.4) | 26.09 (36.4/60.4) | 24.25 (39.9/70.1) | 23.40 (39.3/69.1) | 24.89 (39.1/55.9) |
| Control B | 22.72 (40.3/74.2) | 22.84 (39.5/68.5) | 24.72 (38.0/62.2) | 23.71 (38.9/62.2) | 24.08 (38.9/60.8) |
| Spotlight repeat | 26.46 | 25.06 | 25.66 | 26.61 | 26.85 |

Means L0 vs L2: Home B 33.3 vs 33.6, CC A 25.6 vs 24.1, CC B 22.8 vs 23.9, Spotlight 25.8 vs 26.7.
All within the run-to-run spread (CC A/B swap places). **No measurable frame-rate change.**
(Mode-2 reference from the installed A/B, prod lib: Home B 33.06.)

## Pixel gate (every variant measured)

`research/t24/stage2/gate.py`: six cases `--sysbarrier-off/-on/-wide` x TC/`--no-tc`, each needs
exit 0, `PASS: all`, no FAIL, marker exactly in on/wide and "level 2" exactly in wide.
Round 1 (during the prod GPUPROF boot): 6/6 PASS. Rounds 2-4 (during the L2 framebench boot,
backboardd itself on level 2): 18/18 PASS. 21 checks each incl. the new one (expected
`44260fff` = 40+28, 24+14, 8+7, read back exactly). Production lib hash checked before/after each gate.
Screen dumps of Home and CC in every GPUPROF boot (prod, L0, L1, L2): correct, no missing layers,
CC material and labels intact; pixel differences between boots are the animated wallpaper and clock.
No SMMU fault, panic, GPU hang or ticket/submit error in any of the 9 boots.

## Reading

- Batch splits were not where the GPU time goes. Removing ~36 (Home) / ~50 (CC) batch ends
  per frame left GPU busy time unchanged (Home 27.4-27.6 ms, CC ~31 ms, CC -1 to -2 ms at most).
  Sysmem per-batch overhead is small; the time is DRAM traffic of the draws themselves, which
  barriers do not change. This is what the plan expected ("GPU time itself may move little").
- What remains on Home under L2: ~12 full-screen batches costing 26.4 ms of 27.4. The slowest are
  1125x2436 BGRA, 5-6 draws, ~9-10 ms each (gpuprof's slowest-batch list per window; guess: the
  full-screen composites holding the blended copy, wallpaper passes and self-sampling label
  draws; how many per frame is not in the log), plus 10-draw ones (~6.6 ms).
  CC: 1127x2438 backdrop batches of 2 draws with a clear (~10-11 ms), 1131x2442 blur batches
  (2 draws, clear, 11 ms), 1125x2436 6-8 draw composites (~9 ms).
- Remaining ends are structural: resource dependencies (10 Home / 37 CC: a target is sampled by
  a later pass, so its producer batch must be submitted first) and context flushes (6 / 11).
  Neither is a split of one target's work; fewer would need CA-level reordering. Not pursued.

## Stage 3 recommendation

Proceed to stage 3, but with low expectations for Home and a specific target list:

- **Caveat:** a batch with a retained barrier is forced to sysmem (0008's veto), because a
  self-sampling draw must read memory, not the tile. With L2 nearly every big Home composite
  contains feedback draws, so as built **L2 removes the main GMEM candidates from GMEM**. Stage 3
  must either split at the first feedback draw (GMEM for the non-feedback prefix, sysmem after),
  or resolve/restore around each barrier (costs ~22 MB per full-screen restore+resolve, which is
  what lost in gm1). Barrier-free batches can use GMEM as-is.
- **Candidates** (from the L2 profile): CC's 1127x2438 backdrop batches with clear + 2 draws and
  the 1131x2442 blur batches with clear (cleared = no restore, full write once: GMEM saves the
  separate sysmem clear plus blended draw traffic, ~10-11 ms each now); CC/Home 1125x2436 composites
  of 6-11 draws only where they contain no feedback draw (needs a per-batch "has feedback" flag;
  add a gpuprof column for retained barriers first). Small batches (<1/4 screen) stay sysmem.
- Before any GMEM run: the IOSurface padding/overrun check from the plan, and the pixel gate
  extended with a GMEM case.
- Independently of GMEM, L2 is a correct, harmless driver simplification (half the batches,
  fewer submits) but gives no fps today; it is not worth installing on its own.

## Not established / open

- `clear-blit-*` = 0 only for these screens (Home, CC); apps, Spotlight, lock screen not counted.
- GPU time is end-stamp serialized under GPUPROF; small (~1 ms) CC gains are inside noise.
- Which CA layers the big batches are (shader ids still not mapped to layers).
- Test library `/usr/local/bin/libsweetca-s2.dylib` (1772b043) left on the phone under its test
  name (inert: only test sweetenv uses it); gltest test binary removed.

## Reproduce

Images: `wsl env GPUDBG=0 VARIANT=s2gp-l2 EXTRA_ARGS="gpudelay=1 gpupause=0 sweetfb_sync=1 sweetenv=backboardd:DYLD_INSERT_LIBRARIES=/usr/local/bin/libsweetca-s2.dylib,SWEETCA_PIPELINE=2,SWEETCA_GPUPROF=1,SWEETCA_DRAWPROF=1,SWEETCA_SYS_BARRIER=2 sweetfb_sleep=1 sweetfb_queue=1 sweetgpu_tickets=1" bash .../tools/g2/mkimg.sh j0110`
(`s2gp-prod/l0/l1/l2`, `s2fb-l0/l1/l2` = without the profiling variables). GPUPROF boot:
`MSYS_NO_PATHCONV=1 python research/t24/stage2/gpround.py shim/out/shim-boot-j0110-s2gp-l2.img s2gp-l2`
then `bash research/t24/stage2/summ.sh s2gp-l2`. Frame rate: `python tools/g2/abround.py shim/out/shim-boot-j0110-s2fb-l2.img NAME --kernel xnu/out-jasmine-j0110/kernel.development.sweet --lib research/t24/stage2/ci-40622879956/libsweetca.dylib --lock <private>`.
Gate: `python research/t24/stage2/gate.py research/t24/stage2/ci-40622879956/sweetgpu_gltest OUT ROUNDS`.
Logs: `logs/netlog-s2gp-*.txt`, `logs/netlog-s2fb-*.txt`; captures `research/ab/s2fb-*`; evidence
(summaries, gate outputs, dumps) in ignored `research/t24/stage2/`.
