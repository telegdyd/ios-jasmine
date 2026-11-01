# Metal speed: ideas to get back to (and past) the GL path

Written 2026-11-01, after Metal became the installed default (see [METAL-STEP7.md](METAL-STEP7.md) for the rounds
behind every number here). Each idea says what we saw, what it might give, the risk, how to test it and where to
start. They are ordered by expected gain per effort. **Observations** are measured; **guesses** are marked.

## Where we are

Frame rate in motion (framebench swap arrivals per second, settled boot):

| | home-b | Control Center a / b | Notes |
| --- | ---: | ---: | --- |
| GL (installed GL boot, `fb-gl1`) | **56.5** | **42.7 / 43.4** | libsweetca + glthread + u_threaded_context |
| Metal r20 (in-batch barrier) | 37.3 | 28.4 / 28.2 | |
| Metal r25b (state cache etc.) | 39.3 | 27.9 / 29.9 | |
| Metal r26 (replay on a worker, `BGMTL_ASYNC=1`) | 37.7 | **33.9 / 32.2** | lost render tickets on one boot, see idea 1 |
| **Installed now** (r25b behaviour, async off) | ~39 | ~28-30 | |

What the profile and the timing log say (Control Center, `BGMTL_TIMING=1`):

- **Inline replay (now):** backboardd ~80-90 % of a core. CoreAnimation's render thread does its own frame and then
  our whole `commit` (the replay into Mesa), which costs ~1.3-1.5x CoreAnimation's own time on that thread.
- **Async replay (r26):** the render thread is 64 % QuartzCore / 9 % ours, the same split as GL (61 % / 15 %).
  backboardd drops to 54-67 % of a core. Replay is ~5 ms and submit-to-GPU-completion ~11 ms per command buffer.
  84 % of command buffers are created with none in flight, 39 % within 2 ms of a completion. So CoreAnimation
  mostly waits for the previous command buffer to finish: ~7 ms (CA) + 5 ms (replay) + 11 ms (GPU) ≈ 23 ms, more
  than one 16.7 ms refresh.
- What is left inside the replay, per unit of QuartzCore time (r25b, control-a): `fd_draw_vbo` 0.85 (state emission
  0.42, resource tracking 0.23), batch flush + kernel submit 0.20, command buffer dealloc 0.13, CPU texture uploads
  0.16 (home), `rwa_render_draw` validation ~0.1.

## Ideas

### 1. Bring back the worker-thread replay without losing render tickets (biggest proven gain)

**Seen:** `BGMTL_ASYNC=1` gave Control Center +15 % (r26). On the first installed boot one render ticket went stale
early: the display epoch moved between its begin (at pass encode) and its seal (end of the replay). The next swap of
that surface was refused (`sweet_surface_cpu_access` -> `sweet_ticket_wait` -> `rejectFrame(..., 16, ...)`, in
`xnu/patches/j0110-jasmine-render-tickets.patch`). The kernel then logged "QUEUE FALLBACK reason 16 ... synchronous
for rest of boot", ran without tickets, and the black band came back. The async replay leaves a ticket open for
milliseconds instead of microseconds, which widens that window.

**Options** (best first):
- a. **Kernel:** on a stale/aborted ticket at swap, drop that one frame (or show it untracked once) instead of
  `queueFallback` for the whole boot. Fallback stays for real faults. Needs a kernel round
  (`tools/vm-build.sh TAG`) and a temporary boot first.
- b. **Kernel:** don't make a ticket stale when the epoch moves; re-epoch open tickets instead. Find what bumps
  `sweet_render_epoch` at boot (display power/mode set, `sweet_ticket_cancel(NULL)`).
- c. **Userland:** in `bgTicketFor` (`mesa/metal/src/bgmtl.m`), on `-EBUSY` wait for the replay queue to drain and
  retry once. This covers CA reusing a surface whose previous ticket is still open. It does not cover the epoch case,
  so it only helps together with a or b.
- d. **Userland fallback:** in `commit`, wait for the replay's submit (`_sched`) only when the command buffer holds a
  ticket (`_tcount > 0`). That is safe, but it probably gives back most of the gain because most command buffers
  draw to the display.

**Test:** about 10 boots with `BGMTL_ASYNC=1` in `/private/var/tmp/bgmtl-bb.env`. For each, grep the netlog for
`QUEUE FALLBACK` and check `SWEET FB: tickets begin/seal/abort` / `stale` counts. Then the user checks the panel for
the band.

### 2. Find what CoreAnimation waits on between frames

**Seen:** with the async replay CA starts most frames only after the previous command buffer completed (the numbers
above). GL reaches 56 on home with the same GPU work, so either GL has no such wait or its chain is shorter.
**Guess:** CA's Metal renderer (`CA::OGL::MetalContext`) limits frames in flight with a semaphore released from our
`addCompletedHandler:` callbacks. Or it swaps from the scheduled handler and waits for it.
**Do:**
- Log the order of events per command buffer: create, commit, replay start/end, scheduled handlers run, fence,
  completed handlers run, next create. Extend `bg_tm` in `bgmtl.m`.
- Count `addCompletedHandler:` / `addScheduledHandler:` per command buffer. Check whether CA calls
  `presentDrawable` or `waitUntilScheduled` (the timing log says it never calls `waitUntilScheduled`).
- Look at where the render thread blocks. It's off-CPU, so CPU samples don't show it; use the scheduler events or
  `kevent_id` stacks in framebench.

**Possible fixes:** report "scheduled" as early as Metal allows. Make sure completion handlers run the moment the
fence passes (the completion queue's `bg_fence_wait` blocks in the kernel; check for extra latency). If CA keeps a
fixed in-flight count, overlap more of our side so each frame's chain is shorter.

### 3. Pipeline the replay further, as GL does

**Seen:** GL has three stages: CA thread → glthread (`gl0`) → u_threaded_context driver thread (`gdrv0`, Mesa patch
`0004-freedreno-a5xx-threaded-context`). Metal has at most two (CA → our replay worker). **Do:** create libbgair's
pipe context through `threaded_context_create` (as libsweetca does on a5xx). Freedreno emission and the kernel submit
then run on their own thread while our worker records the next draws. Our `bg_lock` model (one context, many
threads) and the places that read back from the context (`rwa_finish`, fences, `texture_subdata`) need checking
against TC's rules. Combine with idea 1.

### 4. Fewer kernel submits per frame (merge batches)

**Seen:** batch flush + submit is ~0.2x QuartzCore. Most of it is the kernel call (`flush_submit_list` ->
`IOConnectCallMethod`, ~0.25 ms per submit, ~50 BOs each), plus `fd_submit_append_bo` hashing. A batch is flushed
whenever CA samples a texture another unflushed batch rendered (`fd_batch_resource_read_slowpath` ->
`flush_write_batch`), i.e. for every offscreen pass. GL merges these: libsweetca's `SWEETCA_SYS_BARRIER` batch
merging and Mesa patch `0007-freedreno-bounded-batch-graph`. **Do:** look at what 0007/0016 do for GL and whether
libbgair gets the same merging. Freedreno's deferred submits (`flush_deferred_submits`) could carry all batches of
one command buffer in one kernel call. Measure submits per frame first: the `SWEET GPU: backboardd: N submits` line
in the netlog, vs GL's.

### 5. Stop uploading CoreAnimation's uniforms on every draw (RWA_CB_DELTA on a5xx)

**Seen:** CA's per-draw uniforms sit at offsets the a5xx can't bind directly (alignment 64), so each one becomes a
user constant buffer. Freedreno uploads and emits it per draw (`ir3_emit_ubos` -> `u_upload_data`,
`emit_const_user`), ~0.15-0.2x QuartzCore together. `RWA_CB_DELTA` binds the buffer at the aligned offset and has the
shader add the remainder. It is off on a5xx (`cb_delta_gpu` in `air_metal.c`) because shapes came out wrong in some
frames (step 7 r15; traced as far as ir3 a5xx `ldg`/UCHE, not understood). Comparing bytes to skip equal uploads
cost more than it saved (r22). **Do:** reproduce the wrong shapes with `RWA_CB_DELTA=1` in a render probe (corpus
shaders with an offset uniform block), compare the ir3 disassembly with the aligned case, check UCHE invalidation
around `ldg`. Once fixed, this removes most user buffers.

### 6. Less state re-emitted per batch

**Seen:** after the state cache (r24/r25) `fd5_emit_state` is still ~0.4x QuartzCore. Freedreno marks everything
dirty when it switches batches (`fd_context_all_dirty`), and CA switches render targets many times per frame (blur
chain, corner clip copies). `fd5_program_emit` and `emit_common_consts` run again on the first draw of every batch.
**Do:** count batches per frame and draws per batch. Check which passes could share a batch (clears done as draws,
small copy passes). Check whether sysmem batches need the full GMEM-style restore. Lower priority than 1-4.

### 7. GPU time per frame (~11 ms submit to completion)

**Seen:** the observed fence time is an upper bound. Everything renders in sysmem: `fd_mesa_debug` SYSMEM is set for
the whole process once any shader fetches a framebuffer attachment (`rwa_render_draw`). GL also runs with
`FD_MESA_DEBUG=sysmem`, so this alone doesn't explain the gap. **Do:** measure GL's submit-to-fence on a settled
boot for comparison. Measure GPU time per batch with Mesa patches 0005/0006 (GPU batch/draw timing). If Metal's GPU
time is clearly higher, look for draws GL doesn't make (CA's Metal corner-clip copies into a second attachment,
clears) and for GMEM in batches without framebuffer fetch.

### 8. Smaller per-draw costs in our layer

- **Recorded work:** each draw is an Objective-C `BGWork` (alloc, autorelease, retains, dealloc), ~0.1x QuartzCore
  in deallocs. Use a C struct array per command buffer, with retains only for objects not already held.
- **Validation per draw** in `rwa_render_draw` / `check_bindings`: the same pipeline + attachments + bindings are
  checked again for each draw. Cache the last checked combination. `index_range()` reads every index of each indexed
  draw to compute min/max; freedreno may not need valid bounds (`index_bounds_valid = false`).
- **CPU-memory textures** (`_linSrc`, `_ncBytes`) are refreshed once per commit (r24), still ~0.16x QuartzCore on
  home. Find which textures these are, and whether `RWA_LINEAR_SAMPLED` (zero-copy) could cover them (pitch alignment).

### 9. Cheap checks

- Drop `CA_DISABLE_FRAMEBUFFER_COMPRESSION=1` from the env file. It was added in r10 and never shown to matter.
- **Thread placement:** framebench flags "render-runnable" time. Check that CA's render thread and the replay worker
  run on the Gold cores (CPU 4-7) and aren't preempted by `aggregated` / `trustd`, which use most of a core for minutes
  after boot. QoS of `chlorophyll.replay` is user-interactive.

## How to measure (lessons from step 7)

- **Benchmark only after the boot has settled** (~4 minutes). `aggregated` (85 %), `trustd` (59 %) and
  `accessoryupdaterd` (34 %) skew anything started right after boot (r23-r25).
- framebench's **home-a** sometimes reports no swaps on any renderer, GL included. Use home-b.
- The profiler drops a different share of samples each run, so **don't compare absolute ms between runs**. Divide
  our costs by QuartzCore's own time on the render thread in the same phase.
- One boot is noisy (±5 %). For a decision, compare two boots of each configuration.
- `BGMTL_TIMING=1` in the env file prints a once-a-second commit timeline (command buffers, commit/replay ms, CA gap,
  submit-to-fence, process CPU). The netlog splits long lines; the regex in `timing.py` spans the split.
- The user checks the panel after every round (black band, flicker, boxes, tearing). Don't build visual test tooling.

**Local helpers** (in `research/metal-step7/`, git-ignored, only in this checkout):
- `round.sh NAME 'ENV'`: env file → temporary s7tk boot → settle → framebench + netlog.
- `bb.py`: the boot part of a round.
- `reboot-installed.py NAME`: plain reboot into the installed boot_b, with the log captured.
- `glref.py`: GL reference boot.
- `bbcpu.py`: render-thread breakdown by owner and function. Run it in WSL; `BBTHREAD=-` selects the unnamed
  replay worker.
- `norm.py ROUNDS`: the normalized table.
- `timing.py NETLOG`, `leafof.py`, `hotpc.py`.
- `mkimg-mtl.sh` / `mkimg-mtl-slotb.sh`: temporary / installed Metal boot image.

**Build and deploy:** `tools/vm-mesa.sh mesa TAG` → `xnu/out-mesa-TAG/{libbgair,libbgmtl}.dylib` → `tools/sweet-fs.py
put ... /usr/local/bin/...`. Then the render probe:
`tools/sweet-sh.py /usr/local/bin/bgmtl_render_probe /usr/local/bin/bg_kernels.metallib
/usr/local/bin/bg_render.metallib --bb` must report 26/26. Then a boot. Use `MSYS_NO_PATHCONV=1` in Git Bash.

**Installed state and rollback** are in NOTES.md (2026-11-01 01:30 entry). Ask the user before changing boot_b again.
