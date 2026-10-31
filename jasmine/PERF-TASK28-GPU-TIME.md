# Task 28: what fills the GPU's and gdrv0's time per Control Center frame (2026-10-31)

Question (after task 27): Control Center frames ran 23-27 ms, with the GPU ~20-22 ms "occupied" and gdrv0 (freedreno
draw emit and submit) ~18.5 ms on CPU per frame. What fills those, and what is the biggest avoidable part?

**Answers.**
1. **The GPU is not the limit.** In production it runs batches for ~16.3 ms of a ~26 ms instrumented CC frame and
   sits **idle ~9.7 ms waiting for work**. framebench's "GPU occupied" (submit to completion seen, an upper bound)
   counts that queueing. The hardware busy counter agrees: 64 % busy during CC motion.
2. **gdrv0's 18.9 ms is mostly per-batch overhead**: ~12 ms for ~103 batches per frame (batch create 2.7, batch flush
   2.7, submit list 4.3, a full context flush at every feedback barrier 1.7). Per-draw state emit is ~4.7 ms (program
   emit 2.2).
3. **Removing half the batches works on the driver but not on the frame.** Keeping CA's feedback barriers inside the
   batch (existing `SWEETCA_SYS_BARRIER=2`, task 24 stage 2) cuts batches 103 -> 55 per CC frame and **gdrv0
   18.5 -> 15.2 ms per frame**, but the mean CC frame stays at 23.0-23.8 ms. Two thirds of CC frames already make one
   vsync period. The slow third is set by SpringBoard's main thread (~20 ms on those frames, task 19) and GPU spikes
   (~29 ms), and neither moves.
4. **Barriers themselves are cheap on the GPU**: dropping their commands (timing-only knob) changed batch time by
   ~0.5 ms per frame, within noise.

Not installed. Level 2 is a real CPU saving (~3.3 ms gdrv0 per CC frame) with no measured frame-rate gain; see
"Recommendation".

## Instrumentation: patch 0015 (default off)

`mesa/patches/0015-freedreno-gpu-batch-trace.patch`:
- **Fix of GPUPROF's gap counter.** The old busy/gap sums assumed batches finish in slot order. One late batch moves
  `last_end` past all later starts, and the gap sum stays 0 from then on (every CC window in older logs shows
  "gaps 0.0 ms" next to ~60 % busy). Each report now also prints `gpuprof: union`: the union of the window's batch
  [start, end] stamps (covered), the gaps between them, how many are under 50 µs (back to back), and bad stamps.
- **`SWEETCA_GPUTRACE=<file>`**: each time that file's mtime changes, the next `SWEETCA_GPUTRACE_N` (300) batches
  (seqno, context, GPU start/end in µs, target, mode, draws, retained barriers, clears) and every draw recorded
  meanwhile (fs id/instrs, viewport, scissor, blend, first two textures, "*" = samples its own target) are written
  to `<file>.out`, or to the log if backboardd cannot write it (it cannot write `/usr/local/bin`; the log works).
  Reader: `research/t28/trace.py` (ignored; batch kinds by cost).
- **`SWEETCA_SYS_BARRIER_NOP=1`** (timing only, renders wrong): a retained barrier emits no commands.

Builds: WSL tree `~/t28-gpu` (branch t28 on the 0001-0014 commits), VM build `xnu/out-mesa-t28a`. With none of the
switches set the driver behaves as before.

## gdrv0 per CC frame (production, task 27 capture `t27x-j0119-b2`)

`research/t28/threadprof.py` / `callers.py` (WSL, framebench samples of the `gdrv0` thread, CC A windows, 148 frames):
on CPU 18.9 ms per frame.

| Inclusive ms / CC frame | |
| --- | ---: |
| `fd_draw_vbo` | 9.7 |
| of it `fd5_emit_state` (program emit 2.2, consts, textures, MRT) | 3.5 |
| of it `fd_batch_from_fb -> fd_batch_create` (new submit, ringbuffers via `fd_bo_heap_alloc`, hash tables) | 2.7 |
| of it `batch_draw_tracking` (resource read slow path) | 2.2 |
| `fd_pipe_fence_finish -> flush_deferred_submits` (the frame's kernel submits) | 4.7 |
| of it the SweetGPU submit ioctl (incl. `retireJobs` dcache maintenance 0.9) | 2.0 |
| of it `fd_submit_del` | 1.5 |
| `fd_batch_flush` (render_sysmem / emit) | 2.7 |
| `fd_texture_barrier` (production: `fd_context_flush` at every feedback barrier) | 1.7 |
| malloc / free (self) | 2.0 |

About 12 ms scales with the number of batches.

## GPU per CC frame (round 1, three temporary boots)

Temporary j0119on boots (`shim/out/shim-boot-j0119on-t28.img` = slot b's command line, backboardd lib
`/usr/local/bin/t28.dylib` = t28a, settings file `t28.dylib.env`), `SWEETCA_GPUPROF=1`, `DRAWPROF`, `GPUTRACE`,
workload `research/t28/work.py` (gpwork's gestures plus `ddr bw 8000 bg` and a trace trigger per phase). Script
`research/t28/s1.sh`, logs `logs/netlog-t28-{A0,A2,A2N}.txt`, 15:43-16:05. GPUPROF serializes batches, so absolute
frame times are instrumented ones.

| Per CC frame, mean of the 8 steady 100-flush windows | A0 production | A2 level 2 | A2N level 2, barrier NOP |
| --- | ---: | ---: | ---: |
| batches | 103 | 55 | 55 |
| GPU covered by a batch | 16.3 ms | 18.2 | 17.7 |
| GPU idle between batches | 9.7 ms | 6.0 | 7.8 |
| of the gaps back to back (< 50 µs) | 0.02 ms | 0.01 | 0.01 |
| frame (GL flush interval) | 25.9 ms | 24.0 | 25.3 |
| hardware GPU busy (`ddr bw`, of 588 Mcyc/s) | 377 (64 %) | 448 (76 %) | 405 (69 %) |
| RAM-starved Mcyc/s | 231 | 290 | 256 |

Nearly all idle comes in a few long gaps (A0 trace: 28.7 of 28.8 ms of gaps in 4 gaps over 200 µs), i.e. the GPU
drains the frame's work and waits for the next submit. It does not stall between batches.

**Where the drawing time goes** (A0 CC trace, `research/t28/trace.py research/t28/s1/A0-cc.trace --frames 2.9`;
one moment of the animation, 22.5 ms covered per frame there):

| Pass kind | ms / frame | Note |
| --- | ---: | --- |
| Full-screen copies / composites into the frame (BGRA IOSurface): fs6 (5 instr, full + 110x110 mask) 3.1, fs10 (14 instr, blended full-screen) 3.0, fs23 (48 instr) 1.3 | ~7.4 | DRAM traffic of ~6 MB layers |
| Backdrop blur chain (fs7 variable blur with 256x1 LUT 1.9, BORDER 834x1798 self-sampling fs18 1.9, fs5/fs6 down/up copies 1.8, fs19/20 1.1) | ~6.7 | task 23 (closed) territory |
| Clear-only batches (full-screen RGBA targets, no draw in the batch) | 1.7 | 2.8 per frame, ~0.6 ms each |
| Framebuffer-fetch draws (fs8/fs9, 52 instr, self + small mask) | ~1.5 | ~26 per frame |
| Rest (labels, glyphs, small offscreens) | ~5 | |

Barrier cost: A2 -> A2N (no barrier commands) covered 18.2 -> 17.7 ms, within window-to-window spread (±1.5 ms).
Content differs between windows, so per-window GPU time is noisy at the ~1-2 ms level.

## Level 2 A/B (uninstrumented, `research/t28/abba.sh t28a l2`, 16:09-16:37)

Same image and library, settings file only (b = `SWEETCA_SYS_BARRIER=2`), framebench via `tools/g2/abround.py`.

| Swap arrivals/s | a1 | a2 | b1r | b2 |
| --- | ---: | ---: | ---: | ---: |
| Home B | (11.9) | 55.24 | 51.57 | 54.97 |
| Control Center A | (6.0) | 43.16 | 44.33 | 42.06 |
| Control Center B | (6.0) | 38.63 | 38.16 | 42.30 |
| Spotlight repeat | (10.3) | 41.56 | 39.89 | 42.00 |

a1 is a bad boot (Home no frames, every phase 6-12/s, no settings file, nothing else wrong in the log) and is
excluded. b1's first attempt timed out in framebench (DDR found at 768 MHz at that moment) and was repeated (b1r).

Per CC A frame (`tools/g2/framecrit.py`; gdrv0 by `research/t28/threadprof.py`):

| ms per CC frame | a2 | b1r | b2 |
| --- | ---: | ---: | ---: |
| Frame (mean / median) | 23.0 / 21.8 | 23.0 / 20.8 | 23.8 / 22.4 |
| gdrv0 on CPU | 18.5 | 14.8 | 15.6 |
| glthread worker | 6.1 | 4.4 | 5.8 |
| GPU occupied | 20.3 | 19.1 | 20.6 |
| Render thread on CPU | 16.8 | 18.0 | 18.1 |
| SpringBoard main | 9.2 | 9.2 | 9.9 |
| Frames in 1 / 2 / 3+ periods | 105/47/3 | 108/43/5 | 99/49/3 |
| Slowest 25 %: frame / GPU / SpringBoard | 32.0 / 29.1 / 19.5 | 32.9 / 28.8 / 20.1 | 33.9 / 31.3 / 22.1 |

Correctness (b rounds): gltest `--sysbarrier-wide` 9 steps PASS; sweetca_test the known 9958-pixel orientation
mismatch (identical to tasks 26/27); 0 faults, 0 ticket errors; Home/CC screen dumps normal, and round 1's A0/A2 CC
dumps are identical apart from the battery figure.

## Reading

- In production the frame is not gated by one stage. Fast frames (~2/3) already make one period. Slow frames
  coincide with SpringBoard's main thread (~20 ms, task 19) and GPU frames of ~29 ms (the blur-heavy moments of the
  CC animation).
- Level 2 removes ~3.3 ms of gdrv0 CPU and ~1 ms of glthread worker per CC frame. That is CPU time and power, but it
  gives the frame nothing while gdrv0 (15-18 ms) is below the frame (23 ms).
- The GPU's own time is bytes: full-screen composites and the blur chain are ~14 of ~16-22 ms. Cutting that needs
  fewer full-screen passes (CA's structure) or GMEM, which tasks 23/24 and 0013 ruled out.

## Recommendation

- **Level 2 as default: optional, CPU/power only.** No frame-rate gain measured (2 B vs 1 valid A). It saves ~3-4 ms
  CPU per CC frame on the Gold cores. Correctness checks pass, but the path is "experimental" since task 24. User's
  call; not installed.
- **No further gdrv0 work for frame rate now**: with level 2, gdrv0 is ~15 ms against a 23 ms frame.
- The next CC lever is the slow third of frames: SpringBoard (task 19) and the GPU spikes of the blur moments.

## Heat test: 10 minutes of continuous motion on the installed system (16:38-16:54)

`research/t28/heat.sh`: plain boot of installed boot_b (j0119on, production libsweetca 21ca5c4d, DDR 1804, GPU 588,
CPU DVFS auto), unlock, 150 s settle, then 10 minutes without pauses: Control Center open/close x3 and home swipes
x3, repeated. Samples every 30 s (`research/t28/heat/samples.txt`), live log `logs/netlog-t28-heat.txt`. Phone on
the USB charger throughout (no unplugged drain run).

| | Start | 1 min | 5 min | 9 min | 10 min (end) | 1 min after |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Hottest TSENS sensor | 55.0 C | 72.8 | 75.4 | 78.0 | 76.4 | 59.5 |
| Battery current (negative = charging) | -113 mA | -38 | -17 | +8 | -19 | -28 |
| State of charge | 71 % | 71 | 71 | 70 | 70 | 70 |

- **No hang, 0 SMMU faults/panics.** This closes the outstanding DDR 1804 soak (task 9: ~8 min tested before).
- **No throttling**, because none exists (thermal off). Gold stayed at 2208 MHz (DVFS auto, 55-75 % busy), GPU 588,
  DDR 1804 for all 10 minutes. TSENS jumps ~18 C in the first 30 s, then climbs ~0.5 C per minute to 78 C at 9 min,
  not yet flat. Battery temperature read a constant 39.3 C (fuel-gauge value not updating; not a measurement).
- **Frame rate drifts ~5 %** with nothing else changing: mean GL flush interval per quarter 25.0 -> 25.8 -> 26.0 ->
  26.2 ms (mixed CC + Home). Cause not established (guess: temperature-dependent leakage or memory timing; clocks
  were fixed).
- **Power**: the charger's surplus fell from ~240 mA (idle, booting) to about 0. Under motion the phone draws about
  what the charger delivers (~1 W more than idle at 3.94 V). An unplugged drain number needs the user's OK to run on
  battery.
- Reading: 78 C after 10 min, still rising, is the point where task 13 (TSENS-driven caps) matters for longer use.
  Nothing failed.
