# Frame-time bottleneck on the installed configuration (2026-10-29)

Fresh measurement, no earlier benchmark used as a baseline. Installed boot_b j0118 (kernel
xnu/out-jasmine-j0118: DDR governor on, GPU HWCG + GX collapse on, 828x1792@2 canvas from j0112),
production libsweetca 4780fbaa (xnu/out-mesa-diag). One boot, no reboot, no flash. Phone charging
on the PC port, 57 %, TSENS 48-53 C, CPU auto governor, GPU 588 MHz, DDR 1804 under load.

Capture: `research/framebench/perfnow-20261029` (framebench standard run: swap arrivals, 2 ms CPU
stack samples + 5 ms census in home-a/control-a, GPU job submit/complete events, present queue),
per-frame analysis `tools/g2/framecrit.py` -> `framecrit.txt`, CPU placement `placement.txt`, then GPU/DDR
hardware counters (`ddr bw 10000 bg`) over the same Home and Control Center gestures
(`logs/perfnow-20261029*.txt`, `logs/netlog-perfnow-20261029*.txt`).

## Answer

**Control Center is now limited by the CoreAnimation render thread's CPU time, with the GPU close
behind; neither fits in one 16.7 ms period, so frames land on exactly 2 periods (30 fps).**
At 828x1792 the GPU is no longer the clear single limit it was at 1125x2436.

| Phase | Swap arrivals/s | Median / p95 ms |
| --- | ---: | ---: |
| Home (home-b) | 40.8 | 24.5 / 29.6 |
| Control Center (a / b) | 29.2 / 29.0 | 34.5 / 41.8, 33.5 / 42.3 |
| Spotlight repeat | 32.1 | 26.2 / 36.5 |

## Control Center, per frame (104 sampled frames, control-a)

98 of 104 frames took exactly 2 periods (33.3 ms); mean 34.3 ms.

| Resource | ms per frame | Note |
| --- | ---: | --- |
| Render thread on CPU (backboardd display.primary) | **25.4** | CoreAnimation 12.6, Mesa frontend 10.4, kernel 2.3 |
| Render thread blocked in `kern_SwapWait` (IOMFBDisplay is_ready/can_update) | 2.8 | waits for the previous swap |
| Render thread waiting for the driver thread at glFlush (`tc_sync` in finish_update) | 1.5 | |
| Render thread runnable (no core) | 0.7 | no real CPU contention |
| GPU occupied, submit -> completion observed (upper bound) | 22.6 | includes queueing |
| GPU busy from the hardware counter | ~15 | 263 Mcyc/s of 588 MHz / 29 fps, window includes gaps |
| Mesa driver thread gdrv0 on CPU | 17.6 | parallel to the render thread |
| Neither GPU nor render thread busy | 4.5 | |

- Fastest quarter of frames (28.8 ms): render CPU 21.2, GPU 15.5. Even the best frames miss one
  period because of the render thread, not the GPU.
- Slowest quarter (40.4 ms): render CPU 30.5, GPU 30.3, ~8 GPU jobs.
- GPU counters: 64 % of busy cycles RAM-starved, ~3.6 GB/s VBIF. Home: 322 Mcyc/s busy (~13 ms per
  frame), 55 % starved, ~4.2 GB/s. (Counters taken with `gpu pc off` for 25 s, restored to on.)
- Placement: render thread, gdrv0 and SpringBoard's main thread ran only on CPUs 0-3 (Gold, P
  cluster); each Gold core ~50 % busy, Silver nearly idle. Gold frequency during motion was not
  recorded (only `dvfs stat` before/after).

Hot code (control-a, 4 s):
- Render thread, CoreAnimation: `Updater::prepare_layer0/prepare_layer/layer_node`, `HitTestTree::append_layer_node`,
  `OGL::Shape::FillRenderer::render_lines` (CPU shape rasterization), `GLContext::update_shader`.
- Render thread, Mesa: `u_vbuf_draw_vbo` (client vertex arrays re-uploaded per draw), `_mesa_update_state_locked`,
  `_mesa_update_valid_to_render_state`, `draw_prep`, `_mesa_uniform`, `darwin_bo_new` (BO allocation per frame),
  `st_update_fp/blend`, memmove/memcmp.
- gdrv0: `flush_submit_list` (~30 %), malloc/free + `slab_*` + hash tables (batch churn), `fd5_program_emit`,
  `fd_submit_append_bo`, kernel `FlushPoC_DcacheRegion` (~0.75 ms per frame).

## Home

home-b ran at 40.8/s, so about half of the frames fit in one period. home-a (the CPU-sampled Home phase)
produced no data: 1 swap in 9.6 s of swipes. SpringBoard's main thread received the touches
(`SBHomeGesturePanGestureRecognizer`) and committed transactions, but the render thread never ran and no GPU job
was submitted; the next phase (Control Center) rendered normally. Cause unknown (observation, not
diagnosed). So this run has no per-frame CPU split for Home, only the counters above.

## Tool problem found

With GPU idle collapse on (j0115 default), `ddr bw` reports "gpu counters not available": the counter read
fails while GX is off at the start or end instant. Fix: hold GX on for the `ddr bw` window.

## Ideas, ranked by expected frame-time benefit

1. **(Ruled out by the Gold A/B below.) Check Gold clock during motion.** The serial render thread is now the limit; the 2026-10-28
   "CPU clock has no effect" result was measured while GPU-bound at 1125x2436 and does not apply here. The auto
   governor sees four Gold cores ~50 % busy; if it drops below max mid-animation, the render thread grows. One
   A/B: `dvfs auto 0; dvfs set 0 2208000` vs auto. If it helps, have the governor keep Gold high while frames are
   being produced (the ddrgov touch/submit hooks already exist), not a fixed clock.
2. **Mesa frontend on the render thread (10.4 ms per CC frame, task 5).** Targets from this run: client-side vertex
   arrays through `u_vbuf` (stream them into one per-frame upload buffer), per-draw state validation
   (`_mesa_update_state`, `st_update_*`), `darwin_bo_new` on the render thread (suballocate from a pool).
3. **Don't drain the driver thread at every glFlush.** CA's `finish_update` -> `glFlush` -> `tc_sync` blocks
   ~1.5 ms per frame waiting for gdrv0; an async flush (fence returned, submit stays on gdrv0) removes that wait and
   lets CPU and GPU overlap more.
4. **gdrv0 cost (17.6 ms per frame; becomes critical once 2-3 shrink):** submit path (`flush_submit_list`),
   per-batch allocation churn (malloc/slab/hash), program re-emission, CPU cache maintenance on BOs.
5. **Present pipeline:** 2.8 ms per frame in `kern_SwapWait`; CA waits for the previous swap to retire before
   starting the next frame (queue high-water 1). Retiring earlier or allowing two in flight overlaps it.
6. **GPU bytes (needed for 60 fps too):** ~15-23 ms per CC frame, 55-64 % RAM-starved; the remaining big passes
   are CC's backdrop blur and full-screen blended copies. A quick, user-visible way to measure the blur share:
   Settings > Accessibility > Reduce Transparency on/off.
7. **CoreAnimation's own 12.6 ms** (layer tree prepare, hit test, CPU shape fill) is Apple code; only fewer or
   cheaper layers reduce it (same Reduce Transparency switch, fewer widgets).

60 fps in Control Center needs both the render thread and GPU under ~16 ms per frame: about -35 % render CPU and
-30 % GPU. Smaller gains do not show as frame rate in CC (frames stay at 2 periods) but do show in Home and
Spotlight, which already land partly on 1 period.

Bugs worth separate work: home-a's 10 s without rendering; `ddr bw` + GPU collapse; a burst of GPU
pre-wake/collapse pairs every ~12 ms with the display off seen in `gpu pc` before the run (443 pre-wakes in total,
so a burst, not a constant drain).

## Gold A/B (same boot, 22:00-22:05): Gold clock is not a lever

Same framebench schedule, phone untouched in between. `goldab-pin2`: `dvfs auto 0; dvfs set 0 2150400` (auto's own
top clock, so only the governor changes), then `goldab-auto`: `dvfs auto 1` (restored, read back auto=1). The first
pinned attempt (`goldab-pin`) stopped in warmup on one 1 s command-port connect timeout (no USB event in the log);
repeated once unchanged. TSENS 49-56 C in all runs.

| Run | Home A | Home B | CC A | CC B | Render CPU per CC frame | per Home frame |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| auto (perfnow, 21:42) | (no frames) | 40.8/s | 29.2/s | 29.0/s | 25.4 ms | - |
| Gold pinned 2150 | 40.5/s | 40.1/s | 29.1/s | 28.5/s | 24.2 ms | 15.9 ms |
| auto (22:03) | 39.9/s | 40.0/s | 28.7/s | 29.7/s | 25.5 ms | 15.8 ms |

Differences are within run-to-run spread (CC B auto 29.0/29.7 vs pinned 28.5). The governor already holds Gold at
max during motion; idea 1 is ruled out (the only higher OPP, 2208, is +2.7 %).

Home, now sampled in both runs (about 150 frames each): 24.8-25.0 ms mean, half the frames on 1 period
(82/69 and 75/72), render thread CPU 15.8-15.9 ms (CA 7.5-7.8, Mesa 5.6-5.7), GPU occupancy 16.0-16.2 ms,
SpringBoard main thread 14.5-14.7 ms mean (median 18-19), gdrv0 10.4-10.5 ms. **Home sits right at the
16.7 ms boundary on three resources at once** (render CPU, GPU, SpringBoard's main thread), so all three need to
drop for a steady 60; a cut in only one moves few frames.

The home-a stall of the 21:42 run did not repeat (home-a rendered normally in both runs).
