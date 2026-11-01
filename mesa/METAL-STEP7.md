# Metal step 7: backboardd on Metal (in progress)

2026-10-31, user: "re-run the probes, then start step 7". Temporary `fastboot boot` only; side files in
`/usr/local/bin`; no flash, no root bundle/plist, production libsweetca untouched. Raw logs, scripts and shots:
ignored `research/metal-step7/`.

## Probe re-run with the corpus-pass libbgair (PASS)

VM `metal-s7a` (libbgair `90cfa405` = corpus cq3; libbgmtl, injector, libsweetca `1441c96d` byte-identical to
step 6). Temporary boot of the installed `shim-boot-j0120on-slotb.img`, two rounds each:

| Probe | Result per round |
| --- | --- |
| bgair_test | 3 passed, 0 failed |
| bgmtl_probe | 11 passed, 0 failed |
| bgmtl_quad_probe | output identical to step 5 |
| bgmtl_render_probe | 25 passed, 0 failed (incl. expected 64 KiB UBO refusal) |
| registered probe (bgmtl_exec 1) | 25 passed, 0 failed |

Stock process after: no device, injector absent. Console: 0 SMMU faults, panics, ticket errors, crashes.
Production readback `bb3a7a9e...` unchanged.

## How backboardd gets Metal

`EAGLServer::renderer()` tries `CAMetalContextCreate()` first (GPU.md G2 step A); with a Metal device present it
uses `new_metal_context`. So no CA patching: the step 6 injector, allowed in `backboardd` too (still needs
`BGMTL_ENABLE=1`), registers the device before CA asks. Image `research/metal-step7/mkimg-mtl.sh` ->
`shim/out/shim-boot-j0120on-metal-s7bb.img`: installed j0120on settings, sweetenv
`backboardd:DYLD_INSERT_LIBRARIES=/usr/local/bin/bgmtl_inject.dylib,BGMTL_ENABLE=1,BGMTL_BB=1` (no libsweetca in
backboardd, so no GL fallback in this boot; a plain reboot returns to installed boot_b).

## Rounds

1. **r1** (`metal-s7b`): CA picked BGMTLDevice, loaded QuartzCore's default.metallib, then aborted "Metal failed to
   build render pipeline": colour attachment format **551** (`RGB10A8_2P_XR10_sRGB`) unknown. backboardd crash loop
   (sig 6), launchd respawns. Fix: 551 stands in as BGRA8 sRGB, beside Chlorophyll's 550 -> BGRA8.
2. **r2** (`metal-s7c`): no crash; ~20 pipelines (uber shader, blurs, home affordance, overdrive). The user saw the
   boot "glitchy and pretty broken". Log: 19,389 refusals in 5 min of client IOSurfaces with 288/352/544-byte rows
   (a5xx imports multiples of 64 only), and BGR5A1 (Metal 43) refused (a5xx has B5G5R5A1, not R5G5B5A1).
3. **r3** (`metal-s7d`, image s7bb with `BGMTL_BB=1`): **zero refusals, zero crashes/faults/command-buffer
   failures**. Lock screen drawn through Metal with correct colours (wallpaper, clock, status bar, camera button)
   in the swap-surface captures (`s7-r3-shot*.png`), BUT the captures show moving horizontal black bands with ragged
   edges, and CA's render-into-our-surface capture (`sweet_shot` default mode) came back all black.

Fixes in r3:
- Sampled IOSurfaces whose pitch is not a multiple of 64 (and that CA asked only to sample; usage not Unknown) become
  textures of own memory with the pixels copied in, re-copied whenever the surface seed moves (libsweetca's
  `copy_surface` approach). Writable/RT ones are still refused, the refusal now names CA's usage.
- Metal 43 BGR5A1 resolves to `B5G5R5A1` when the screen lacks R5G5B5A1; `rwa_texture_write` / `rwa_texture_read`
  exchange the red and blue fields. IOSurface imports of format 43 would show red/blue exchanged (not seen).

4. **r4** (image s7ds: `+BGMTL_DEFER_SCHEDULED=1`, CA told "scheduled" only after the GPU finished; `sweetgpu_tickets=1`
   dropped for command-line room, libsweetca's only): log clean, but the user saw black areas "running down" the panel
   like an old TV, and a box around the camera button that came and went.
5. **r5** (`metal-s7e`, drawable shadows): the screen went entirely black.
6. **r6** (`metal-s7h`): **lock screen clean** in every swap-surface capture (`s7-r6-shot1.{2,3}.png`): wallpaper,
   clock, "Swipe up to open", blurred camera button; 0 refusals/crashes/faults.

What the flicker was (measured vs guessed): CA's server draws into a swap surface the panel's scaler may still read
(the kernel counts ~65 % of GL submits and ~97 % of Metal submits drawing into a held surface; same CA buffer logic).
GL renders in GMEM, so memory only goes from one finished frame to the next; Chlorophyll forces sysmem (fbfetch
emulation), so the clear's black is in memory while the frame's draws follow (guess for the mechanism; the fix below
removed the symptom). Fix: in the compositor (`BGMTL_BB`) each imported drawable is drawn in a private shadow and
copied to the surface in one GPU blit per command buffer (`BGMTL_SHADOW=0` turns it off).

r5's black screen was a second bug, reproduced in a test process: **the a5xx 2D blitter's copies come out empty**
on the a512 (new render probe P13: private texture -> imported surface 12800/12800 texels zero; with `--bb` also
private -> private). `rwa_texture_copy` now sends renderable same-format 2D copies through the 3D engine (a scissored
`pipe->blit`, which fd5_blitter declines, so u_blitter draws it). Render probe 26/26 plain and 26/26 `--bb`, quad
output and compute 11/11 unchanged. Not investigated: why the 2D blitter writes nothing (Mesa fd5 vs our kernel);
`resource_copy_region` remains for compressed/other copies.

## Rounds 7-14: corner boxes, flicker and tearing (user checked the panel each round)

A/B switches no longer need a new image: the injector reads `KEY=VALUE` lines from `/private/var/tmp/bgmtl-bb.env`
(a temporary file on the phone) and sets them before the device exists. Image `shim-boot-j0120on-metal-s7tk.img`
(`research/metal-step7/mkimg-mtl.sh`): sweetenv only inserts the injector with `BGMTL_ENABLE=1`, plus
`sweetgpu_tickets=1`; `BGMTL_BB=1` and `BGMTL_DEFER_SCHEDULED=1` come from the env file.

| Round | Change | Panel (user) |
| --- | --- | --- |
| r6 | shadow + 3D-engine copies | camera button a square box, CC platters missing, widget corners octagonal; flashing |
| r7 | `FD_MESA_DEBUG=inorder` | same: not the a6xx barrier/reorder race |
| r8 | `BGMTL_SYNC=1` | same: not CPU/GPU buffer reuse |
| r9 | `RWA_TEX_POOL=0 RWA_LINEAR_SAMPLED=0 RWA_CB_DELTA=0` | **boxes and flicker gone**; motion "twitchy", tearing |
| r10-r12 | `CA_DISABLE_FRAMEBUFFER_COMPRESSION=1`; `CA_FORCE_TRIPLE_BUFFERING` (not an iOS 16 variable, no effect); `CA_DISABLE_LOW_LATENCY=1` (5 framebuffers, no change) | still tearing |
| r13 | `BGMTL_SHADOW=0` | black band back |
| r14 | **render tickets** (`metal-s7k`) | **"fixed, no tearing"** |

Which of r9's three switches fixed the boxes is not known yet (all three still off).

**Tearing, measured.** framebench (r12): frames flip in order, no drops (1159 admitted/flipped), 26-34 swaps/s in
motion (GL t19: 40-47). Kernel GPU jobs touched the surface on the panel in 47-88 % of Metal frames (GL ~6 %),
a median 0.5 ms after that surface was flipped: CA hands a framebuffer to the display (SwapEnd) without waiting for
the GPU (Apple's display waits on the GPU itself), and the present queue only waits for jobs already submitted.
**Fix:** Chlorophyll opens a kernel render ticket (j0110, as libsweetca mode 2) for every IOSurface a render pass
draws into, when the pass is encoded, and seals it with the command buffer's submit seqno at commit (abort if never
committed); the presenter shows the surface only once sealed and passed. r14 kernel: tickets begin/seal/abort
614/613/0, 0 stale/error/timeout, **0 jobs into a held surface, guard q/s/r 0/0/0** (was 79/282/0), 0 faults.

## Rounds 15-18: speed switches back (user checked the panel each round)

All on the s7tk image with tickets; one change per reboot.

| Round | Env file | Panel (user) |
| --- | --- | --- |
| r15 | r14 minus `RWA_TEX_POOL=0`, `RWA_LINEAR_SAMPLED=0` (pool and linear textures back on) | clean, no boxes |
| r16 | minus `BGMTL_DEFER_SCHEDULED=1` | clean and smooth |
| r17 | plus `BGMTL_SHADOW=0` (no shadow copy) | clean and smooth |
| r18 | `metal-s7l` defaults below; file holds only `CA_DISABLE_FRAMEBUFFER_COMPRESSION=1` | clean and smooth |

So the corner boxes and flashing were **`RWA_CB_DELTA`** (misaligned unbounded constant buffers bound in place, the
shader adding the remainder from slot 15). Not understood on a5xx; traced as far as ir3's a5xx `ldg` UBO path (Mesa 26
`emit_intrinsic_load_ubo`; fd5 never invalidates UCHE, our ring neither; a5xx keeps user constant buffers as pointers
until emit, `fd_set_constant_buffer` uploads only for gen >= 6). Not a CPU/GPU reuse race (r8 `BGMTL_SYNC=1` kept it).
On a6xx it was worth ~3 % of backboardd.

`metal-s7l` (libbgair `6d611be8`, libbgmtl `6154f42a`, inject `fc4d5071`, in `/usr/local/bin`): the injector sets
`BGMTL_BB=1` in backboardd itself; the shadow is opt-in (`BGMTL_SHADOW=1`); `RWA_CB_DELTA` defaults off on gen < 6
(`=1` forces it); `waitUntilScheduled` waits for the GPU only with `BGMTL_DEFER_SCHEDULED=1` (before, it waited in the
compositor even without the deferral). Render probe 26/26 plain and `--bb`. r15-r18 logs: 0 SMMU faults, panics,
crashes, command-buffer failures; 0 jobs into a held surface; tickets e.g. r18 1218/1217/0, one ticket timeout in r15
and r17 each (not looked at).

**Speed, measured (framebench, swap arrivals/s in motion):** unchanged by all of it.

| Phase | r12 (all off, deferral, shadow) | r17 (no deferral, no shadow) | r18 (s7l) | GL t19 |
| --- | ---: | ---: | ---: | ---: |
| home-b | 33.9 | 34.5 | 33.3 | 40-47 |
| control-a / control-b | 27.7 / 25.7 | 25.1 / 25.6 | 27.1 / 25.8 | |

(home-a was a broken capture in r12 and r18.) r18: presenter's ticket wait median 8.9 ms / p95 17.8 ms after the
swap; GPU job submit-to-completion median 11.1 ms / p90 16.1 ms (fence observation, an upper bound); backboardd about
half a core in control-a. Guess (not measured): CA's encoding and the GPU do not overlap (~15 ms CPU + ~11 ms GPU
~ the 29 ms frame), e.g. a frame-in-flight limit in CA released late by our completion queue. Second lead: sysmem
rendering forced for every pass (fbfetch emulation) where GL renders in GMEM.

## Rounds 19-20: where the 29 ms went (user checked r20: clean and smooth)

**r19** (`metal-s7m`: libbgmtl `a1ac5f12` with `BGMTL_TIMING=1`, a once-a-second commit timeline in backboardd's log;
env file `CA_DISABLE_FRAMEBUFFER_COMPRESSION=1`, `BGMTL_TIMING=1`). Per second, idle and in motion alike: ~41
command buffers; our `commit` 7-10 ms each, CA between commits ~16-17 ms (one refresh: CA starts a frame on vsync),
submit to fence observed ~16.5 ms (asynchronous); CA created a command buffer with none in flight in ~1/3 of
cases, right after a completion in ~1/5; `waitUntilScheduled` never waited; **process CPU 82-91 %**. So backboardd
is CPU-bound, not waiting for the GPU. CPU samples of the render thread (framebench `fb-r19`, symbolized with the
one-off `research/metal-step7/bbcpu.py`, ignored), Control Center (control-a, 4 s): 3106 ms, **ours 62 %** (54 % inside
`-[BGMTLCommandBuffer commit]`, which replays the recorded draws into Mesa), QuartzCore 28 %. Inside commit:
`fd_draw_vbo` 802 ms and **`fd_texture_barrier` 248 ms**: on a5xx freedreno's texture barrier is a whole context
flush (only a6xx has an in-batch one), and Chlorophyll's attachment feedback calls it before every fetching draw
(CoreAnimation's rounded-corner clip), so each one ended the batch, began a new one (`fd_batch_create`,
`alloc_batch_locked`, new ringbuffers) and re-emitted all state.

**r20** (`metal-s7n`, libbgair `ab94be09`): `fd5_feedback_barrier` in `air_metal.c` emits libsweetca's
`SWEETCA_SYS_BARRIER=2` commands (Mesa patch 0008, GL's production setting) in the batch: CCU colour flush (+ depth
if bound), `CACHE_FLUSH_TS`, WFI, CCU colour invalidate, UCHE invalidate + WFI. Wider than GL's rule: up to four colour
attachments and depth (CA's corner clip draws into two). Falls back to the flush for UBWC/compressed attachments, no
or empty batch, queries, a pending fence; `RWA_FB_BARRIER=0` always flushes. Render probe 26/26 plain and `--bb`;
on the phone 60,000 barriers kept, 0 fell back; 0 faults/crashes.

| Phase (swaps/s) | r18 | r19 (timing on) | r20 |
| --- | ---: | ---: | ---: |
| spotlight-repeat | 24.1 | 26.9 | **39.3** |
| home-a / home-b | (broken) / 33.3 | (broken) / 34.3 | **37.4 / 37.3** |
| control-a / control-b | 27.1 / 25.8 | 25.8 / 25.0 | **28.4 / 28.2** |

Render thread in control-a: 3106 -> **1892 ms** (commit 1684 -> 992). It is now busy about half the time and spends
~17 ms CPU per displayed Control Center frame, right at the 16.7 ms refresh, so frames still slip a vsync. What is
left in commit (r20, ms of 1892): `fd5_emit_state` 354 (`emit_common_consts` 152, `fd5_program_emit` 130,
`ir3_emit_ubos` 88), `batch_draw_tracking` 150 (`fd_batch_resource_read_slowpath` 132), batch flush at commit 136,
`rwaTextureSampled` 94, CPU texture uploads 72, command buffer dealloc 72.

## Rounds 22-25: state that did not change, bound again every draw (user checked r25: clean and smooth)

Yes: `rwa_render_draw` bound blend, depth/stencil, rasterizer, both shaders, vertex elements and buffers, viewport,
scissor and stencil reference for every draw, and freedreno marks state dirty on every bind, equal or not (Mesa
26.2.5 `freedreno_state.c`, `freedreno_program.c`). A dirty program re-runs `fd5_program_emit` and re-tracks every
bound resource. Changes, all in Chlorophyll:

- `rwa_device.gs` in `air_metal.c`: what the last draw bound; an equal bind is skipped (pointers for state objects;
  values for viewport, scissor, stencil ref; resource + offset for vertex buffers and for constant buffers that are
  real buffers). `gs_invalidate` when a pipeline or depth/stencil state is destroyed (they bind NULL) and before
  `util_gen_mipmap`. `RWA_STATE_CACHE=0` binds everything as before. A new batch still re-emits everything
  (freedreno's `fd_context_all_dirty`), which needs nothing from us.
- User constant buffers (CA's per-draw uniforms at offsets the a5xx cannot bind) are bound every time. r22 also
  compared and copied their bytes to skip equal ones: `memcmp` + `memmove` cost 124 ms per 8 s, more than the skip
  saved (normalised commit 1.84 -> 2.21, worse). Dropped in r24.
- Error text built only on failure: `snprintf` of "colour attachment %u" per attachment and "buffer %u of %s" per
  buffer ran on every draw (≈1 % and ≈4 % of the commit).
- `bgmtl.m`: a texture over CPU memory (`_linSrc`, `_ncBytes`) is refreshed once per commit, and again after a CPU
  blit in the replay (`bg_refresh_epoch`), instead of at every draw that samples it. Each refresh after the first
  wrote a texture the open batch had already read.
- `bgRecordDraw` retains only up to the highest bound slot of each table (was all 16 of four tables).

**Measuring.** Swap rates right after boot are not comparable: `round.sh` (ignored helper: env file, `bb.py`,
framebench with the netlog) started the benchmark 3 s after boot, while `aggregated` (85 % CPU), `trustd` (59 %) and
`accessoryupdaterd` (34 %) were still busy. r23-r25 then showed slow early phases and a home-a with no swaps; r25
re-run minutes later (r25b) was normal. The profiler also drops a varying share of samples, so absolute ms differ
between runs; costs below are our time divided by QuartzCore's own time on the render thread in the same phase
(`research/metal-step7/norm.py`, ignored), which my changes do not touch.

| Round (VM build) | change | home-b | control-a / -b | commit / CA, home-a | commit / CA, control-a |
| --- | --- | ---: | ---: | ---: | ---: |
| r20 (`metal-s7n`) | before | 37.3 | 28.4 / 28.2 | 1.68 | 1.84 |
| r22 (`metal-s7o`) | cache + byte compare | 35.6 | 26.5 / 26.2 | 1.88 | 2.21 |
| r23 (`metal-s7o`) | same, `RWA_STATE_CACHE=0`, bench at boot | 33.8 | 25.0 / 24.5 | - | 2.79 |
| r24 (`metal-s7p`) | no byte compare, refresh per commit, bench at boot | 38.2 | 27.0 / 25.7 | - | 1.56 |
| r25b (`metal-s7q`) | + lazy error text, fewer retains, settled boot | **39.3** | **27.9 / 29.9** | **1.31** | **1.48** |

r25 (`metal-s7q`: libbgair `852bf5dd`, libbgmtl `b7d0a818`): render probe 26/26 `--bb`; 0 faults/crashes, 0 command
buffer failures, feedback barriers all kept in the batch. Commit cost relative to CA's own work: −22 % home, −20 %
Control Center; texture refresh on home 0.37 -> 0.16, `check_bindings` 0.06 -> 0.00-0.03. Left in commit (r25b
control-a, per unit of CA time): `fd_draw_vbo` 0.85 (state emit 0.42, resource tracking 0.23), batch flush and
submit 0.20 (the kernel submit call itself is most of it, same path as GL), command buffer dealloc 0.13.

## Round 26: GL reference, and the replay off CoreAnimation's thread (user checked r26: fine)

**GL reference** (installed boot_b, production libsweetca `bb3a7a9e`, framebench `fb-gl1` after a 4-minute settle):
spotlight-repeat 40.9, home-b **56.5**, control-a / -b **42.7 / 43.4** swaps/s (the old "40-47" was an early-boot
figure). The render thread there is 61 % QuartzCore and 15 % libsweetca: the driver work runs on other threads,
`gdrv0` (u_threaded_context, patch 0004) 2486 ms and `gl0` (glthread, patch 0014) 840 ms in control-a. On Metal all
of the replay into Mesa ran inside `commit` on CoreAnimation's render thread.

**r26** (`metal-s7r`: libbgair `852bf5dd` unchanged, libbgmtl `4ab1879e`). In the compositor `commit` now only marks
the command buffer committed and hands the replay to one serial queue (`chlorophyll.replay`, user-interactive QoS), in
commit order; `BGMTL_ASYNC=0`, `BGMTL_SYNC=1` and tracing replay inline. `waitUntilScheduled` waits for the replay's
submit (`_sched` group), `waitUntilCompleted` as before; status changes and the handler lists are under
`@synchronized`. The worker lets go of the context lock between work items, and the lock is fair-share
(`PTHREAD_MUTEX_POLICY_FAIRSHARE_NP`), so CoreAnimation's thread can open the next frame's passes (render tickets)
during a replay. Render probe 26/26 plain and `--bb`; 0 faults/crashes/command buffer failures.

| Phase (swaps/s, settled boot) | r25b | r26 | GL |
| --- | ---: | ---: | ---: |
| home-b | 39.3 | 37.7 | 56.5 |
| control-a / control-b | 27.9 / 29.9 | **33.9 / 32.2** | 42.7 / 43.4 |

Control-a render thread: QuartzCore 64 %, ours 9 % (GL: 61 % / 15 %); the replay worker carries what commit did
(≈1.5x QuartzCore's time, unchanged). backboardd CPU 54-67 % of a core (was 77-95 %): no longer CPU-bound. Replay
~5 ms per command buffer, submit to GPU completion ~11 ms. 84 % of command buffers are now created with none in flight
and 39 % within 2 ms of a completion (r20: 54 % / 14 %), so CoreAnimation mostly starts the next frame once the last
one completed; CA + replay + GPU ≈ 7 + 5 + 11 ms does not fit one refresh. (Guess, not measured: a completion gate in
CA's Metal renderer that GL's path does not have, or that GL's shorter chain fits.) GL renders in sysmem too
(`FD_MESA_DEBUG=sysmem` in sweetca.c), so that is not the difference.

## Installed: Metal is the default boot (user, 2026-11-01: "set up Metal to be the default on boot ... I'm done with GL")

`boot_b` = `shim/out/shim-boot-j0120on-metal-slotb.img` (SHA256 `c5e8f056...`), built by
`research/metal-step7/mkimg-mtl-slotb.sh` (ignored): the s7tk recipe plus `abmark=b`. Its payload differs from the GL
`shim-boot-j0120on-slotb.img` only in `sweetenv=backboardd:...` (`bgmtl_inject.dylib,BGMTL_ENABLE=1` instead of
`libsweetca.dylib,SWEETCA_PIPELINE=2`) and the build's 64-byte random seed; same kernel j0120on, same ADT, 598-byte
command line. `fastboot flash boot_b` OKAY, then `fastboot reboot` (slot b). In `/usr/local/bin`: libbgair `852bf5dd`,
libbgmtl `97dfeff0` (`metal-s7s`), bgmtl_inject `fc4d5071`; `/private/var/tmp/bgmtl-bb.env` =
`CA_DISABLE_FRAMEBUFFER_COMPRESSION=1`. libsweetca (`bb3a7a9e`) stays in `/usr/local/bin` for the GL image.
**Rollback:** `fastboot flash boot_b shim/out/shim-boot-j0120on-slotb.img` (`bf33a55f`, GL).

**First installed boot: the black band again** (user). Cause, from that boot's log (`netlog-metal-installed.txt`):
early in boot one render ticket went stale (the display epoch moved between its begin at encode and its seal), the
next swap of that surface was refused (`sweet_surface_cpu_access` -> `sweet_ticket_wait` not ready ->
`rejectFrame(..., 16, ...)`), and the kernel fell back to synchronous presentation **without tickets for the rest of
the boot** ("QUEUE FALLBACK reason 16", tickets begin/seal/abort 4/3/1, stale 1). With the async replay (r26) a ticket
stays open until the worker submits, milliseconds instead of microseconds, so the window is wider; r26 did not hit it.
Fix for the default: the async replay is now opt-in (`BGMTL_ASYNC=1`, libbgmtl `97dfeff0`). Plain reboot after that
(`netlog-metal-installed2.txt`): tickets 4206/4206/0, stale/error/timeout 0/0/0, no fallback, 0 drew into a surface
the display holds, 0 faults/crashes/command buffer failures; render probe 26/26 `--bb`. Speed is r25's (home ~39,
Control Center ~28-30); user: "Looks right". To bring the async replay back safely: the kernel should drop one frame instead of falling
back for the whole boot on a stale ticket, or the ticket's begin should move to the replay.

## Open (next)

The speed work is laid out idea by idea in [METAL-SPEED-IDEAS.md](METAL-SPEED-IDEAS.md).


- More CPU off the commit: state emission per new batch (each render-target switch re-emits everything), resource
  tracking per draw, the dealloc of recorded work. Then GL vs Metal on a settled boot of each. Whether sysmem is
  needed for passes with no framebuffer fetch (GPU time).
- Benchmark only a few minutes after boot (background services). home-a of framebench comes out with no swaps on
  some boots, GL included (fb-gl1): a benchmark problem, not a renderer one.
- Async replay without losing tickets (above), then what CoreAnimation waits on between frames (completion handler, scheduled handler, drawable/ticket), and the GPU
  time per frame (~11 ms submit to completion).
- Drop `CA_DISABLE_FRAMEBUFFER_COMPRESSION=1` (last env line; added in r10 without effect).
- `RWA_CB_DELTA` on a5xx (above).
- One ASTC_4x4 no-copy texture refresh computes its row as 832 bytes for 828 texels (texel rows instead of block
  rows) in `bgmtl.m` `rwaTexture` (`_ncLength / height`): refused (23 times in r6).
- Unimplemented selectors answered zero: `setCompletionQueue:`, `setGPUPriority:` (command queue).
- Not yet: unlock/home screen, UI rounds, frame times vs GLES, libsweetca + libbgair in one process.
