# Task 5: Mesa's per-draw CPU on CoreAnimation's render thread (2026-10-30)

**Result: no measurable swap-rate gain. The render thread's Mesa time is a flat profile.** It is spread over
many 1-3 µs costs per GL call, none above ~0.7 ms per CC frame except Mesa's own draw validation
(`st_prepare_draw`, ~2.7 ms in ~13 µs pieces per draw). Patch 0012 (three render-thread cuts) gives
-0.3 ms render-thread Mesa, -0.55 ms render CPU and -0.4 ms mean frame per Control Center frame, and
the 100-flush stats stall is gone (10-14 ms in one frame of ~100). Both B runs beat both A runs on render CPU
and mean frame; on Mesa time alone they overlap (B1r 8.56 vs A2 8.50). Swap rates moved within run-to-run
spread. Not installed.

## Where the render thread's Mesa time goes (before 0012)

Capture `research/ab/t5af-b2` (production lib bf5328c0 = 0001-0011), Control Center A, render thread
(`com.apple.coreanimation.display.primary`) on-CPU samples, inclusive ms per frame. Script:
`subtree.py`/`callers.py` (scratch, a copy of framecrit's symbolizer loop).

| Function | ms / CC frame | Note |
| --- | ---: | --- |
| `w_DrawElements` | 5.2 | 165 calls/frame, 33 µs wall each (Home: 81 draws, 18 µs) |
| of it `st_prepare_draw` (all draw paths: 2.7) | 2.3 | fragment textures 0.44, constants 0.34, arrays 0.23, framebuffer 0.21, rasterizer 0.19, samplers 0.16, fp 0.13, blend 0.11 |
| of it `u_vbuf_draw_vbo` (all: 0.59) | 0.42 | 0.23 of it memmove of CA's client vertex arrays; upload buffer allocation only 0.03 |
| of it `ticket_write` (all: 0.57) | 0.47 | 0.3 of it is the first-per-surface kernel calls (`darwin_ticket_begin`, `bo_from_iosurface`) |
| of it `draw_prep` (wrapper) | 0.37 | unit loop, fetch uniforms |
| `_mesa_update_state_locked` | 0.69 | `_mesa_update_texture_state` 0.34 |
| `w_DrawArrays` | 1.0 | 37 calls/frame |
| `w_BindFramebuffer` | 0.71 | 56 calls/frame |
| `w_UseProgram` | 0.59 | 119 calls/frame |
| `darwin_bo_new` | 0.22 | from CA's `glTexImage2D` (new texture BOs), not from the vertex uploader |
| stats report (`sca_log` in `w_Flush`) | 0.13 average | **10-16 ms in one frame of ~100**: ~40 lines to stderr = kernel console, printed synchronously (`fbcon_transmit_data`) |

Call counts from the wrapper's own 100-flush statistics (`logs/netlog-t5af-b2.txt`). Other render-thread
items seen on the way, not Mesa: XNU signs every Mach message with SHA-256 (`ikm_sign`/`ikm_validate_sig`,
~0.24 ms per CC frame on this thread); CA's own malloc ~1.3 ms per frame.

**Open question from 0011 (driver-thread back-pressure): not the cause.** The render thread waits in total
~0.2 ms per CC frame (wait-lock 0.12, fence 0.07, no `util_queue_fence_wait`). The +0.2-0.3 ms in
`w_DrawElements` after 0011 is CPU, not waiting (guess: cache/bus contention with the busier gdrv0;
not measured).

Candidates from the bottleneck report, checked against this:
- `u_vbuf` per-frame upload buffer: the uploader already suballocates (0.03 ms); what's left is copying
  the vertex data itself.
- `darwin_bo_new`: comes from texture creation (TexImage2D, 0.2-0.7 calls/frame, BO cache hit rate low
  because sizes vary), 0.22 ms/frame.
- Per-draw validation: real state churn (CC changes program on 119 of 202 draws), each atom ~1 µs.

## Change (patch 0012)

`mesa/patches/0012-sweetgl-render-thread-report-ticket-fast-path.patch`:
1. The 100-flush report is built in a buffer on the render thread and written from a utility dispatch
   queue (`sweetca.report`), one write per line.
2. `sgl_ticket_write`: a surface already in the open ticket batch returns before the mutex and the inflight
   scan. The open batch's entries had their hazard resolved when added, and every inflight batch predates
   the open one, so the result is the same.
3. `w_Clear`: `getenv("SWEETCA_REGION")` read once instead of on every clear.

Builds: B `xnu/out-mesa-t5r12` (d2d94a70..., measured below); `xnu/out-mesa-t5r12b` (52b9cf97..., current
patch). t5r12b only differs in the report writer: the measured build wrote the whole report in one write,
which split the live log's per-line `|backboardd|` tags mid-line (text intact; breaks greps like
`drawsum.py`). t5r12b writes per line. **t5r12b has not run on the phone.**

## Correctness

- gltest of B (`sweetgpu_gltest` from t5r12) on the installed boot: plain, `--sysbarrier-off`, `-on`, both
  with `--no-tc`: 9 steps, all PASS; `--feedback-diagnostics` 45/45 PASS (`research/t5r12/gl_*.txt`).
- B boots: tickets begin/seal/abort 2191/2190/0 and 2043/2043/0, stale/error/timeout 0/0/0, submit errors 0,
  no "full finish for process" fallback, no SMMU fault, no new panic lines (the 4 "panic" matches are boot
  args and `debug_log_init`, same in A). 19-20 stats reports per boot, as in A. Screen dumps
  `research/ab/t5r12x-*/shot.*.png`.

## A/B (ABBA, 2026-10-29 23:41 - 2026-10-30 00:08)

Same method as the 0011 report: temporary boots of `shim/out/shim-boot-j0118-t5lib1.img` (A,
`/usr/local/bin/libsweetca1.dylib` = bf5328c0, production content) and `-t5lib2.img` (B,
`libsweetca2.dylib` = d2d94a70), `tools/g2/abround.py`, script `research/t5r12/abba.sh`. The first attempt
never booted: the command-port reboot hung (known root-unmount stall); the user forced fastboot, then the
ABBA ran. B1 stopped in control-b on a command-port timeout (flake); repeated once as b1r.

| Swap arrivals/s | A1 | B1r | B2 | A2 | A mean -> B mean |
| --- | ---: | ---: | ---: | ---: | ---: |
| Home B | 44.44 | 44.08 | 44.21 | 43.28 | 43.9 -> 44.1 (+0.5 %) |
| Control Center A | 32.50 | 33.24 | 33.29 | 32.22 | 32.4 -> 33.3 (+2.6 %) |
| Control Center B | 32.20 | 31.37 | 29.11 | 29.70 | 31.0 -> 30.2 (-2.4 %) |
| Spotlight repeat | 34.89 | 34.82 | 34.93 | 37.42 | 36.2 -> 34.9 (-3.5 %) |

Medians Home B 21.4/22.6 (A) vs 21.8/22.0 (B) ms. Only CC A has both B above both A; the others overlap.
Read as **no swap-rate change**.

Per Control Center A frame (`tools/g2/framecrit.py`, `research/ab/t5r12x-*/framecrit.txt`):

| ms per frame | A1 | A2 | B1r | B2 |
| --- | ---: | ---: | ---: | ---: |
| Frame (mean) | 30.8 | 30.5 | 30.2 | 30.2 |
| Render thread on CPU | 24.0 | 24.2 | 23.8 | 23.2 |
| of it Mesa | **8.88** | **8.50** | **8.56** | **8.22** |
| of it CoreAnimation | 12.1 | 12.6 | 12.8 | 12.3 |
| kernel other | 2.25 | 2.09 | 1.55 | 1.90 |
| gdrv0 on CPU | 18.3 | 18.5 | 18.0 | 18.9 |
| Stats report on the render thread | 14 ms once | 4 + 10 ms | none | none |

(Mesa per frame in these A runs is lower than the 9.4-9.8 ms of the 0011 B runs with the same library:
run-to-run level shift; compare only within this ABBA.)

Home A had no frames in all four captures again (home-a stall, library-independent, known).

## What would move the render thread

The frame is bounded by CA (~12.5 ms) + Mesa (~8.5 ms) + kernel (~2.5 ms) serially on one thread. The Mesa
part has no single cost left that a small patch removes. The structural lever is moving Mesa's GL
frontend (validation + state atoms + u_vbuf, ~7 of the 8.5 ms) off the render thread, as Mesa's glthread does.
That is not a focused change here: the wrapper reads Mesa state directly per draw
(`sgl_sampled_2d_units`, `glGetUniformiv` for rect samplers, `glGetIntegerv` after binds, ticket writes and
`sgl_texture_barrier` ordered against draws). All of those would need marshalling or caching first. Smaller
candidates: XNU's per-message SHA-256 signing (~0.24 ms/frame, kernel config), batching the per-surface
ticket kernel calls (~0.3 ms).

## State

- Phone: back on installed boot_b j0118 (command-port reboot -> fastboot -> `fastboot reboot`, slot b),
  production `/usr/local/bin/libsweetca.dylib` read back bf5328c0 (unchanged). Side files now:
  `libsweetca1.dylib` (bf5328c0), `libsweetca2.dylib` (d2d94a70 = 0012 first build), `sweetgpu_gltest-t5r12`,
  `t5r-shot.raw.*`.
- Evidence (ignored): `research/ab/t5r12x-{a1,b1,b1r,b2,a2}/`, `logs/netlog-t5r12x-*.txt`, `research/t5r12/`.
