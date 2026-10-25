# Task 5: where Mesa's CPU goes, and the threaded context (2026-10-25)

**Status: in progress, not installed.** The first device boot of the threaded
context froze backboardd between the Apple logo and the lock screen (user saw it).
The previous production library (`cfa9fd9c…`, empty-trace fix) was restored at
~06:58 and a verification boot drew the UI again. Root cause is being diagnosed.

## Where the display thread's CPU goes now

Source: `research/framebench/20261025-empty-trace/` (installed library
`cfa9fd9c…`), Control Center A, backboardd `coreanimation.display.primary`,
on-CPU samples only: 1763 samples x 2 ms = 3526 ms in ~4 s, 57 swap arrivals,
about 62 ms of render CPU per arrival. Each sample is counted once, in the
deepest matching bucket (`research/t5tc` scripts `cat.py`, `tree.py`):

| Bucket | Samples | Share of thread |
| --- | ---: | ---: |
| CoreAnimation's own code (not Mesa) | 487 | 27.6% |
| GL/st-mesa validation: `st_prepare_draw`, `_mesa_update_state`, draw validation, UseProgram, BindFramebuffer, uniforms, wrapper `draw_prep` | ~360 | ~20% |
| Per-batch work: `fd_batch_create` (ring BOs, submit object), ring heap alloc, render-pass setup (`fd_gmem_render_tiles`, mostly `render_sysmem`), `batch_flush` | 235 | 13.3% |
| State + program emission (`fd5_emit_state`, `fd5_program_emit`, `draw_impl`) | 222 | 12.6% |
| Kernel submits and submit teardown (the 32-draw kick, `flush_submit_list`, `slab_destroy_child`) | 158 | 9.0% |
| Resource tracking, `fd_draw_vbo`, `u_vbuf` user arrays | 136 | 7.7% |
| Other Mesa | ~165 | ~9% |

Mesa is 72% of the thread. Roughly 850 of its 1276 samples are freedreno
driver work (everything under `fd_draw_vbo`, batch flushes, submits), the rest
is GL frontend validation. Points found on the way:

* **a5xx emits every draw twice**: `fd5_draw_vbo` runs `draw_impl` for the draw
  ring and again for the binning ring. Call-site split: 161 samples draw pass,
  40 binning pass (2.3% of the thread).
* Most barrier-split batches already render in **sysmem** (no tile loop);
  their cost is batch setup/teardown and full state re-emission, not tiling.
* `fd5_program_emit` recomputes the VS/FS varying linkage and re-emits all
  program registers on every program change and every new batch (102 samples,
  5.8%); `fd_submit_append_bo` reallocs its BO table per batch.
* Each kernel submit does a whole-cache clean by cross-call on all CPUs
  (`sweet_gpu_flush_all` from `SweetGPUUserClient::maintain`), about 25 samples
  on this thread plus the IPIs elsewhere.

## Ranked fixes (biggest first)

1. **Threaded context for a5xx** (this change). Upstream freedreno enables
   `u_threaded_context` only on a6xx. With it, the ~850 driver samples move to
   a second Gold core and run alongside CA + GL validation (~900 samples), so
   the frame becomes max(app, driver) instead of their sum: up to ~1.6-1.8x
   render throughput in Control Center if the driver thread keeps pace. Not a
   measured gain yet.
2. **Fewer batches**: ~87 batches for ~182 draws per CC flush, 54 of them with
   one draw. Keep wrapper texture barriers inside a sysmem batch (CCU flush +
   UCHE invalidate) instead of splitting; ~29 splits/frame. Cleared GMEM batches
   need care (a5xx clears are GMEM blits).
3. **Cheaper batches**: recycle ring BOs/submit objects instead of allocating
   three rings, a submit, hash tables and a slab child per batch.
4. **Program-emission cache**: prebuilt register packets per (variant, binning,
   flat/sprite state), identical command stream.
5. **Submit cost**: no whole-cache clean per submit (write-combined command and
   upload buffers, which needs task 8's pmap fix first).
6. Binning-pass emission only for batches that can bin (small framebuffers never do).

1-6 are independent of GPU state except 2; with the threaded context, 2-6
shorten the driver thread once it becomes the critical path.

## The change

* `mesa/patches/0004-freedreno-a5xx-threaded-context.patch`: `fd5_context_create`
  returns `fd_context_init_tc()` as on a6xx; `prefer_real_buffer_in_constbuf0`
  for a5xx (the threaded context requires it). `GALLIUM_THREAD=0` turns it off.
* `mesa/darwin/sweetgl`: `sgl_kick()` runs the per-32-draw kick on the driver
  thread (a zero-timeout fence check from CA's thread would only queue a flush,
  never send the deferred submits to the kernel); `sgl_follow_thread()` gives
  the driver thread the display thread's scheduling (log: policy 4, priority 54).
* Commit `c954a07`, Mesa CI `40166420782`, library SHA256
  `38c8f967caa78137330fc53a91bcb14e28e2ac2da27b189e02332cc82264763e`.
  `sweetgpu_gltest` from that build: all 7 steps PASS on the phone.

## First device boot: livelock in the batch cache

Boot of `shim-boot-framebench99.img` at 06:51 with the new library: EAGL context
at 51 s, driver thread scheduling set at 57 s, then no frame; swap surfaces kept
the boot logo and `CARenderServerRenderDisplay` timed out after 60 s.
Census `research/t5tc/prof-hang` (3 s, 06:55): backboardd's only driver thread
`gdrv0` at 999 ms/s on CPU in `fd_batch_from_fb -> batch_from_key ->
alloc_batch_locked` (+ key hash, hash search); nothing else in backboardd runs.

`fd_batch_from_fb` retries until `batch_from_key` returns a batch.
`alloc_batch_locked` returns NULL when all 32 slots of the screen's batch cache
are taken and none holds an unflushed batch of this context: flushed batches
keep their slot until their last reference drops. So under the threaded context
something keeps 32 flushed batches (or other contexts' batches) referenced.
Which holder is not established; the diagnostic patch
`research/t5tc/0005-fdbc-diag.patch` (branch `t5tc-diag`, not for `jasmine`)
prints every slot's owner, flushed state, refcount, dependency bits and fence
links once the loop has spun 100000 times.

**Cause, confirmed in the source (device confirmation pending):**
`fd_fence_destroy()` (`freedreno_fence.c:101`) drops `last_fence`, the TC token,
pipe and kernel fence, but never `fence->batch`. The sequence below therefore
leaks one batch reference each time. Fix in patch 0004 (`fd_context_flush`): when a
TC flush replaces a fence that still holds this batch, that fence drops the
reference on the driver thread and gets the new fence as its `last_fence`, so
waiting on it still waits for the same submit. The original description follows.

**Original hypothesis:** `fd_context_flush()` with
`TC_FLUSH_ASYNC` and a fence does `fd_pipe_fence_set_batch(*fencep, batch)` then
`fd_pipe_fence_ref(&batch->fence, *fencep)`, overwriting any fence already on
the batch. Driver-thread flushes without TC (our kick, and every
`fd_texture_barrier()` -> `fd_context_flush(pctx, NULL, 0)`) attach a fence that
holds a batch reference (`fd_pipe_fence_create(batch)`) and, when
`ctx->last_fence` is set on a batch with no draws yet, return without flushing.
If the TC flush then replaces that fence and `fd_fence_destroy()` does not drop
`fence->batch`, the batch is never freed after its flush: one leaked slot per
occurrence, 32 slots gone within the first frames. CA issues ~28 texture
barriers per frame, which a6xx apps rarely do. Check `fd_fence_destroy()` and
the dump before fixing; the fix belongs in freedreno's fence/batch link, not a
larger cache or a timeout.

## Fixed build on the phone (07:35-07:41)

Fix + dump library (branch `t5tc-diag` `d400e26`, CI `40169317271`, SHA256
`bb543dc9…`) installed at the production path; GL test 7/7 PASS. Measurement boot
of the same `shim-boot-framebench99.img` at 07:35:54: EAGL at 69 s, home drawn,
no `fdbc:` dump. One standard framebench capture at 07:39:27 (~210 s after boot;
baseline started at 145 s), exit 0: `research/framebench/20261025-threaded2/`.
Comparison script `research/t5tc/compare.py`, output `research/t5tc/comparison.json`,
against `research/framebench/20261025-empty-trace/capture/` (installed `cfa9fd9c…`).
Swap arrivals, not confirmed displayed frames; one capture each, no statistics.

| Segment | Arrivals/s before -> after | Median ms | p95 ms |
| --- | ---: | ---: | ---: |
| Control Center A | 14.49 -> 18.79 (+30%) | 70.9 -> 54.0 | 86.2 -> 76.0 |
| Control Center B | 14.07 -> 14.68 (+4%) | 73.0 -> 72.5 | 88.6 -> 82.5 |
| Home B | 20.63 -> 18.52 (**-10%**) | 49.3 -> 52.4 | 53.4 -> 65.1 |
| Home A | baseline invalid (0.1/s) -> 18.59 | - -> 51.8 | - -> 62.2 |
| Spotlight first | 6.99 -> 18.38 | 80.0 -> 32.3 | 311 -> 218 |
| Spotlight repeat | 13.73 -> 15.63 (+14%) | 63.4 -> 55.8 | 73.4 -> 81.5 |

Display thread in the CC A CPU window (4 s): on CPU 3526 -> 1766 ms, per arrival
61.9 -> 22.9 ms; Mesa on it 2314 -> 632 ms. The driver thread `gdrv0` ran
~1366 ms in the same window. The display thread now mostly waits in CA's
per-frame `glFinish` (`w_Flush`): GPU fence 805 ms, driver-thread drain
(`util_queue_fence_wait`, labelled shader-worker-wait) 700 ms, runnable 490 ms.
In Home A it was runnable (wanted a CPU) for 765 ms: SpringBoard (~0.8 core),
trustd and accessoryupdater (~0.8 core together) and the two render threads
compete for 4 Gold cores. Home B's -10% is one sample and has no baseline CPU
data (baseline Home A was invalid); it may be variance or CPU contention.

**What this changes in the ranking:** the display thread is no longer CPU-bound
in Control Center. The next large gains are (a) task 16, presenting without the
per-frame `glFinish` so GPU work and the driver drain overlap the next frame,
now the largest wait; (b) CPU headroom: task 21's trustd/accessoryupdater load
and task 6's 8-core comparison; (c) items 2-5 above, which now shorten the
driver thread.

## Next steps

1. Push `research/t5tc/0005-fdbc-diag.patch` to branch `t5tc-diag`
   (`mesa/patches/0005-fdbc-diag.patch`, one file only; the two earlier CI runs
   `40167668725`/`40167924433` failed: missing `assert_dt`, then the patch also
   carried sweetgl changes). Build `-f build=mesa --ref t5tc-diag`.
2. One boot with that library (it will freeze again), read `fdbc:` lines from
   the live log, restore `research/t5tc/libsweetca-before.dylib` (`cfa9fd9c…`).
3. Fix the reference leak in patch 0004, rebuild on `jasmine`, GL test, one
   framebench run against `research/framebench/20261025-empty-trace/`, user's look.
4. Only then install; slot b needs no reflash (userland library).
