# Task 26: CoreAnimation's GL frontend off the render thread (glthread), 2026-10-31

Goal: shorter render-thread CPU per frame in backboardd (`com.apple.coreanimation.display.primary`). Today
every GL call CA makes runs Mesa's frontend (st/mesa validation, state atoms, u_vbuf vertex copies) on that
thread, serially after CA's own work: per Control Center frame ~24 ms render CPU = CA 12.6 + Mesa 8.5 +
kernel 2.3 (PERF-TASK5-RENDER-CPU-20261030.md). The Mesa part is a flat profile; the lever left is overlap.

## Choice: Mesa's own glthread, enabled by the sweetgl frontend

Two ways were considered:

1. **Mesa glthread** (`_mesa_glthread_init`): every public `gl*` entry dispatches through the context's
   current table, so with glthread on CA's calls (through the wrapper) are recorded into 8 KB batches and
   a per-context worker thread ("gl") replays them on Mesa. glthread already tracks the state it needs to
   answer common queries (framebuffer bindings, active texture, current program, pixel store) and copies
   client vertex arrays and client indices at record time (index min/max scan, upload into a mapped
   buffer). The wrapper already calls only public entries for GL work.
2. **A libsweetca-side command queue**: re-implement record/replay for the ~70 wrappers, including client
   array copying. Same semantics work, several times the code, and nothing glthread does not have.

**Picked 1.** What it needs from us:

- freedreno does not claim `map_unsynchronized_thread_safe`, so `_mesa_glthread_init` silently refuses.
  The reason is real: glthread maps its upload buffer from the app thread (`PIPE_MAP_THREAD_SAFE`), and
  freedreno takes the transfer from `ctx->transfer_pool_unsync`, a slab child pool the frontend thread
  (now the glthread worker, through TC's unsynchronized maps) also allocates from. Patch: thread-safe maps
  get a heap transfer (freed at unmap), never the upload-pointer path, and the cap is set.
- sweetgl must provide `set_background_context` (st asserts it when the worker starts).
- An ordered "run this function on the worker" command: a new internal GL function
  `InternalSweetCallbackMESA(fn, data)` (GLintptr args, so the generator marshals it asynchronously).
  Through the current dispatch it is queued with glthread on and called inline with glthread off.

Switch: `SWEETCA_GLTHREAD=1` (read once by libsweetca, applied to every context it creates, at creation:
glthread must see every call from the start, its VAO/binding tracking cannot be started mid-life).
Default off: with it off no code path changes (every new branch tests the per-context flag).

## Inventory: what the wrapper does on the hot path that a deferred thread cannot answer

From `sweetca.c` / `sweetgl.c` / `sweetgl_tickets.inc` at patch 0013, mode 2 (production). "Sync" means
`_mesa_glthread_finish`: wait for the queued batches, then run the partial batch on the calling thread.

| Wrapper site | Per CC frame | Today | With glthread |
| --- | ---: | --- | --- |
| `draw_prep` -> `sgl_sampled_2d_units` (reads `ctx->_Shader->CurrentProgram` directly) | per draw with a feedback texture bound (~45) | direct Mesa read | **wrong** without change (worker lags). Shadow in the wrapper: per program, the active `sampler2D` uniforms (location, unit), filled at link, updated by `glUniform1i/1iv` (CA's and our own `sca_fb` set). Programs past `OBJMAX` or with >16 samplers: sync + the Mesa read. |
| `draw_prep` -> `glGetUniformiv(rect sampler)` | per rect-program draw | sync query | same shadow (the rect sampler is one of the program's samplers) |
| `draw_prep` -> `sgl_texture_barrier` (`_mesa_TextureBarrierNV` direct) | ~45 | direct | **must** go through the dispatch (`CALL_TextureBarrierNV`): queued in order with the draw |
| `w_BindFramebuffer` -> `glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING)` (mode 2) | ~16 | query | answered by glthread without a sync (it tracks the binding; a failing bind would report the requested name, CA never binds unknown names) |
| `w_FramebufferTexture2D` -> 2 x `glGetError` (`ticket_gl_capture`) | ~1 | queries | 2 syncs. Skipped with glthread; the FBO is marked ticket-bad (sync-frame fallback) whenever the wrapper cannot vouch that the attach is valid (texture name never bound, non-0 level, other attachment/target) |
| `bind_surface` -> `glGetError` x2 around `sgl_tex_image_iosurface_fmt` | per IOSurface bind | queries | skipped: `st_context_teximage` raises no GL error |
| `bind_surface` -> `sgl_tex_image_iosurface_fmt` (`st_context_teximage` direct) | per IOSurface bind | direct | import on the render thread (screen-level, as today), `st_context_teximage` + unref queued to the worker; the binding it targets is the one in effect at that point of the stream |
| `bind_surface` -> `glGetTexParameteriv(MIN_FILTER)` | per IOSurface bind | query | shadow: the wrapper records CA's MIN_FILTER per texture (TexParameteri/f), default = mipmap filter |
| `w_FenceSync` / `w_ClientWaitSync` / `w_DeleteSync` | 1 / 1.3 / 1 | 25-30 µs each, no real wait | FenceSync/ClientWaitSync return values -> 2.3 syncs per frame. Wrapper fences (below) |
| `w_Flush` mode 2: `sgl_flush_async` + `sgl_ticket_flush` (st/pipe direct) | 1 | direct | one queued callback; Mesa's marshalled `glFlush` would sync (HasExternallySharedImages), which is exactly what 0011 removed for TC |
| `kick_after_draw` -> `sgl_kick` (TC `callback` + `flush`) | ~5 | direct | queued callback (TC must only be driven by the worker, its single producer) |
| `sgl_follow_thread` (once per context) | - | direct | queued callback; also gives the **glthread worker** the render thread's policy and priority |
| `sgl_trace_frame_end` (trace only) | - | direct | queued callback |
| `sgl_ticket_write` | first write per surface per frame | kernel BEGIN + device-level BO lookup on the render thread | unchanged (no TC/st access); BEGIN now lies even earlier before the GPU write |
| `sgl_ticket_write` "pending" -> `sgl_flush_submit` | rare today | TC callback + wait | sync first, then as today; counted (the worker lag may make a target reused next frame still pending) |
| `sgl_ticket_finish` / `sgl_tickets_available` / `ticket_resolve` / `w_Finish` / `glReadPixels` / shadow write-back | rare (fault/sync frames) | drains | sync first, then as today (needed: CPU reads) |
| `glTexImage2D/TexSubImage2D` from client memory, `copy_refresh` | ~0.1-0.3 | | glthread syncs itself (no PBO bound): correct, the pointer is used during the call |
| `glGenTextures`, `glGetUniformLocation`, `glIsProgram`, `LinkProgram` queries, `glGetString` | rare | | syncs (rare) |
| `bind_ctx` -> `sgl_make_current` to another context | per context switch | | `_mesa_make_current` flushes the old context directly: sync the old context first (as DRI does) |
| `sgl_context_destroy` | - | | sync first; ticket teardown runs directly |

Every queued callback runs on the worker in stream order, so ordering against draws, flushes and ticket
seals is the same as today's TC ordering (worker -> TC -> gdrv0).

**Tickets (mode 2).** `sgl_ticket_flush` is split: the open batch moves to the inflight list on the
render thread at once (the next frame's `sgl_ticket_write` must start a new batch), and only
`pipe->callback(sgl_render_driver)` + `pipe->flush(ASYNC)` are queued. The display still waits for each
surface's SEAL, which still comes from gdrv0 after its flush.

**Wrapper fences.** `w_FenceSync` returns a wrapper object and queues the real `glFenceSync`. The worker
owns a per-context list of live fences and polls them (`glClientWaitSync(real, 0, 0)`) in the frame-end
callback, publishing "signaled". `w_ClientWaitSync` with timeout 0 answers from that state (not
signaled -> `GL_TIMEOUT_EXPIRED`, which is always a legal answer for a zero timeout: the fence's commands
may not even have reached the driver). A second zero-timeout call on the same unsignaled fence, or any
non-zero timeout, takes the real path (sync, real wait), so a client that spins until signaled makes
progress. `GL_SYNC_FLUSH_COMMANDS_BIT` additionally hands the current batch to the worker. DeleteSync is
queued (the worker removes and deletes). Only CA's private, unshared contexts use these.

## GL semantics check

- glthread is Mesa's standard implementation (used by default on radeonsi/iris/zink); everything not
  listed above keeps GL's ordering and error semantics (errors reported at the next `glGetError`, which
  syncs).
- Client memory: vertex arrays and indices are copied when the draw is recorded; texture uploads from
  client memory sync (executed during the call); uniforms with pointers are copied. CA's IOSurface memory
  that the CPU writes (copied surfaces) goes through `glTexSubImage2D` from client memory: sync.
- Shadows answer only what the wrapper itself set up or CA set through the wrapper; every value the
  wrapper cannot vouch for falls back to a sync.
- Lifetime: queued `st_context_teximage` holds a resource reference until it runs; wrapper fences are
  freed only by the worker.

## Expected gain and risks

Expected (estimate, not measured): the render thread keeps CA (12.6), kernel (2.3), the wrapper's own work
(draw_prep loop, tickets ~0.8), glthread's marshalling (~0.3 µs per call, ~2000 calls) and the client array
copy + index scan (~0.5): render CPU per CC frame ~24 -> ~17-18 ms; Home ~16 -> ~11-12 ms. The worker takes
~7-8 ms per CC frame on another Gold core.

Why CC may still not reach 1 period: gdrv0 (freedreno draw/emit/submit) is already ~18 ms per CC frame and
the GPU ~15 ms; the next limit after the render thread is gdrv0. Home (render 16, GPU 13-16, SpringBoard
main 15) has more to gain.

Risks: (1) a sync source on the hot path I missed (mitigation: per-wrapper sync counts in the 100-flush
report, first boot tells); (2) one more pipeline stage of latency per frame, more if CA throttles on its
fences; (3) a target IOSurface reused next frame hitting the "pending" drain more often; (4) a freedreno
race in the thread-safe map path (only glthread's upload buffer uses it); (5) CA reacting to fences
reported unsignaled later than before.

## Implementation

Patch `mesa/patches/0014-sweetgl-glthread.patch` (freedreno cap + thread-safe transfers, the internal
callback function, sweetgl, libsweetca, `sweetgpu_gltest --glthread`). Switches, read by libsweetca (boot
environment or the `<library>.env` settings file of 0013):

- `SWEETCA_GLTHREAD=1`: glthread for every context libsweetca creates. Default off; off changes no path.
- `SWEETCA_GLTHREAD_ASYNC_ERRORS=1` (only with the above): `glGetError` answers from errors the worker has
  collected (polled at frame ends and on each ask) instead of waiting. Errors still arrive, in order, but
  up to a frame late: a GL deviation, so a separate switch (see "glGetError" below).

The 100-flush report gains a `syncs` column per wrapper (glthread waits) and a `glthread:` line (sampler
fallbacks, fence answers from state, real fence waits, ticket pending drains). `tools/g2/framecrit.py` now
counts the worker (`backboardd:gl0`, column `glw`), a `wait-glthread` render-thread category, and a test
library under another name as Mesa.

Builds (VM): `xnu/out-mesa-t26a` (libsweetca 28b9d9df..., glthread), `xnu/out-mesa-t26b` (3f1d0b9d..., + the
async-errors switch). Both contain patches 0001-0014.

## Correctness (installed j0118, 2026-10-31 01:21-01:23, `research/t26/t26a/`)

- `sweetgpu_gltest` of t26a: plain 85/85 PASS (9 steps), `--feedback-diagnostics` 45/45; with `--glthread`:
  plain, `--sysbarrier-on`, `--sysbarrier-off`, `--no-tc` 86/86 each (the extra PASS is "glthread on"),
  `--glthread --feedback-diagnostics` 46/46. Includes the active-sampler-unit step (Mesa read after a sync),
  IOSurface target/texture (queued `st_context_teximage`) and the ordered feedback cases (queued barriers).
- `sweetca_test` (own directory, library from t26a) with the settings file empty / `SWEETCA_GLTHREAD=1` /
  `+ SWEETCA_PIPELINE=2`: identical result in all three, 9958 of 65536 pixels differ (image 9201, rounded
  119, rotated 144, text 494) = the known image-orientation mismatch of the test (GPU.md G2 step 3); glthread
  on in both glthread runs, the worker followed the caller's priority.
- CA boots with glthread: screen dumps after framebench's gestures are the normal Home screen and Control
  Center (identical to glthread off apart from the moving wallpaper, clock and battery), 0 SMMU faults, 0
  panics, 0 ticket/submit errors, tickets balanced.

**A wrong test image cost two rounds**: the first t26 image was built without `CANVAS=828x1792 SCALE=2`, so
its ADT had the native canvas while the command line says `sweetfb_lw=828`; backboardd looped on
`IOServiceMatching AppleM2ScalerCSCDriver` (hundreds per boot, 4 normally), framebench saw almost no swaps
and the display surfaces were black, **with glthread off, on, and with the fbr5 library alike** (control
boot). Those captures are in `research/t26/bad-canvas/` and not used. `research/t26/mkimg.sh` now passes the
canvas; the image differs from fbr5's only in the library name.

## A/B (ABBA, 2026-10-31 01:47-02:15)

One library (t26a as `/usr/local/bin/t26.dylib`), temporary boots of `shim/out/shim-boot-j0118-t26.img`
(slot b's j0118 command line minus `keepsyms=1`/`abmark`, 828x1792@2), `research/t26/abba.sh`: A = empty
settings file, B = `SWEETCA_GLTHREAD=1`. `tools/g2/abround.py` (150 s settle, standard framebench). a2
stopped on a framebench timeout, repeated once as a2r.

| Swap arrivals/s | A1 | B1 | B2 | A2r | A mean -> B mean |
| --- | ---: | ---: | ---: | ---: | ---: |
| Home B | 43.65 | 44.90 | 41.70 | 45.35 | 44.5 -> 43.3 (within spread) |
| Control Center A | 31.48 | 35.44 | 34.58 | 33.08 | 32.3 -> 35.0 (**+8 %**) |
| Control Center B | 31.86 | 35.25 | 35.60 | 33.09 | 32.5 -> 35.4 (**+9 %**) |
| Spotlight repeat | 34.42 | 35.90 | 34.21 | 36.03 | 35.2 -> 35.1 |

Both B runs beat both A runs in both Control Center phases; Home and Spotlight unchanged.

Per Control Center A frame (`tools/g2/framecrit.py`, `research/ab/t26x-t26a-*/framecrit.txt`):

| ms per frame | A1 | A2r | B1 | B2 |
| --- | ---: | ---: | ---: | ---: |
| Frame (mean / median) | 31.4 / 30.2 | 30.2 / 29.5 | 28.7 / 27.5 | 29.3 / 28.0 |
| Render thread on CPU | **24.9** | **23.8** | **18.6** | **17.8** |
| of it Mesa | 9.1 | 8.8 | 2.3 | 2.6 |
| of it CoreAnimation | 13.0 | 12.2 | 13.0 | 12.3 |
| Render thread waiting for the worker (`wait-glthread`) | - | - | 1.6 | 2.4 |
| glthread worker on CPU | - | - | 6.0 | 7.1 |
| gdrv0 on CPU | 19.1 | 18.0 | 19.2 | 19.6 |
| GPU occupied (upper bound) | 23.4 | 21.3 | 22.7 | 22.7 |
| Frames of 1 / 2 / 3+ periods | 3 / 106 / 4 | 5 / 110 / 3 | 47 / 68 / 7 | 36 / 81 / 4 |

Render-thread CPU per CC frame -6.1 ms (Mesa 9 -> 2.4, the rest of Mesa's 7 ms runs on the worker). The
render thread is no longer the longest stage: gdrv0 (~19 ms) and the GPU (~22 ms occupied) now are, which
is why CC moved from almost always 2 periods to ~1/3 of frames in 1 period, not to 1 period. Home: home-a
had no frames in all four captures (the known library-independent home-a stall), so Home has only the swap
rates of home-b, which did not move (Home was already bounded by render 16 / GPU 13-16 / SpringBoard 15).

**Where the remaining render-thread waits come from** (B1's 100-flush reports during CC motion): CA calls
`glGetError` twice per frame and each waits for the worker (~2 syncs, ~2.2 ms per frame of wrapper time);
`glGenTextures`/`glTexImage2D` from client memory ~0.1/frame; fences: 0 real waits (all answered from the
polled state); sampler fallbacks 0; ticket pending drains 0 during CC (up to 50 per 100 flushes in other
motion of the first boot).

## glGetError without waiting (t26b, 2026-10-31 02:16-02:39)

Same image and method, library t26b, rounds b3 e1 e2 b4 (b = `SWEETCA_GLTHREAD=1`, e = `+
SWEETCA_GLTHREAD_ASYNC_ERRORS=1`), `research/t26/abba.sh t26b "b3 e1 e2 b4"`.

| Swap arrivals/s | B3 | E1 | E2 | B4 | B mean -> E mean |
| --- | ---: | ---: | ---: | ---: | ---: |
| Home B | 42.64 | 49.69 | 41.59 | 46.34 | 44.5 -> 45.6 |
| Control Center A | 38.01 | 37.89 | 37.78 | 36.09 | 37.1 -> 37.8 |
| Control Center B | 35.08 | 37.29 | 36.80 | 37.15 | 36.1 -> 37.0 |
| Spotlight repeat | 35.39 | 36.75 | 36.87 | 36.44 | 35.9 -> 36.8 |

Per CC A frame (framecrit): B3 frame 26.2 ms, render CPU 16.9, Mesa 2.3, wait-glthread 0.79, worker 4.9;
E1/E2 frame 26.6/26.6, render CPU 17.8/16.7, Mesa 1.8/1.6, wait-glthread 0.04/0.02, worker 6.1/5.8; frames
in 1 period 67/136 (B3), 62/135, 66/135. The switch removes the last render-thread waits, but swap rates and
frame times stay within the B spread: **no measurable gain for a GL deviation; not recommended**.
(B runs of this session are ~2 swaps/s higher in CC than B1/B2: a run-to-run level shift, as in earlier
reports; compare within a session.) Every boot clean: 0 faults/panics, 0 ticket/submit errors.

## Recommendation

**Install glthread (`SWEETCA_GLTHREAD=1`) as the default**: Control Center +8-9 % swap arrivals in the
ABBA (both B above both A), render-thread CPU per CC frame -6 ms (24.4 -> 18.2 mean), a third of CC
frames now in one display period; Home/Spotlight unchanged; gltest and sweetca_test unchanged; clean boots.
Costs: one more thread per CA context (~6 ms CPU per CC frame on a Gold core, same total work moved, not
added: Mesa render-thread time fell by about what the worker spends), and one more pipeline stage of
latency per frame. Leave `SWEETCA_GLTHREAD_ASYNC_ERRORS` off.

How it would be the default (needs the user's OK; userland only, no flash): make glthread the default in
libsweetca (`SWEETCA_GLTHREAD=0` keeps the old path), rebuild, install as `/usr/local/bin/libsweetca.dylib`
(production now bf5328c0 = 0001-0011), plain reboot and check. Note that 0012 and 0013 (both default
off/neutral) come along with it.

Next limit for Control Center: gdrv0 (~19 ms per frame, freedreno emit/submit) and the GPU (~21 ms occupied);
the render thread (~17 ms) is now below both.
