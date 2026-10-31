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

## Open (next)

- The user's look at the panel on r6 (captures clean). Whether `BGMTL_DEFER_SCHEDULED` is still needed with shadows.
- Cost of the shadow copy (6 MB per frame) and of the deferral: frame times vs GLES not measured yet.
- One ASTC_4x4 no-copy texture refresh computes its row as 832 bytes for 828 texels (texel rows instead of block
  rows) in `bgmtl.m` `rwaTexture` (`_ncLength / height`): refused (23 times in r6).
- Unimplemented selectors answered zero: `setCompletionQueue:`, `setGPUPriority:` (command queue).
- Not yet: unlock/home screen, UI rounds, frame times vs GLES, libsweetca + libbgair in one process.
