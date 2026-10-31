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

## Open (next)

- More CPU off the commit: the per-draw state above (state that did not change re-emitted?), resource tracking per
  draw, `rwaTextureSampled`. Then GL vs Metal on the same boot type. Whether sysmem is needed for passes with no
  framebuffer fetch (GPU time).
- Drop `CA_DISABLE_FRAMEBUFFER_COMPRESSION=1` (last env line; added in r10 without effect).
- `RWA_CB_DELTA` on a5xx (above).
- One ASTC_4x4 no-copy texture refresh computes its row as 832 bytes for 828 texels (texel rows instead of block
  rows) in `bgmtl.m` `rwaTexture` (`_ncLength / height`): refused (23 times in r6).
- Unimplemented selectors answered zero: `setCompletionQueue:`, `setGPUPriority:` (command queue).
- Not yet: unlock/home screen, UI rounds, frame times vs GLES, libsweetca + libbgair in one process.
